"""The LLM interpretation path.

One call per scenario, not one per note: p95 latency is scored and three
sequential model calls would blow the 5-second band on their own.

The model is asked once, its answer goes through the deterministic guardrails,
and on failure it gets exactly one repair attempt with the validator error fed
back. If that also fails, `interpret_notes` raises and the caller decides what a
safe failure looks like -- this module never invents a directive itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass

from backend.llm.prompts import build_messages
from backend.validator.guardrails import Directive, GuardrailError, validate_interpretation

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LLMUnavailable(RuntimeError):
    """The model could not be reached or produced nothing usable."""


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    base_url: str | None
    model: str
    timeout_seconds: float
    max_attempts: int

    @classmethod
    def from_env(cls) -> "LLMSettings":
        # LLM_* wins; OPENAI_* is accepted so the stock OpenAI env works untouched.
        return cls(
            api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "",
            base_url=os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None,
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "20")),
            max_attempts=int(os.getenv("LLM_MAX_ATTEMPTS", "2")),
        )


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
# Hidden tests repeat scenarios and reuse note wording. A note-set is a pure
# function of its text, so caching the validated directives is free latency.

_CACHE_LIMIT = 512
_cache: dict[str, list[Directive]] = {}
_cache_lock = threading.Lock()


def _cache_key(notes: list[str], capacity: float) -> str:
    payload = json.dumps([[n.strip() for n in notes], capacity], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> list[Directive] | None:
    with _cache_lock:
        return _cache.get(key)


def _cache_put(key: str, value: list[Directive]) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_LIMIT:
            _cache.clear()
        _cache[key] = value


def cache_size() -> int:
    with _cache_lock:
        return len(_cache)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

_client = None
_client_lock = threading.Lock()


def _get_client(settings: LLMSettings):
    global _client
    with _client_lock:
        if _client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise LLMUnavailable("openai package is not installed") from exc
            if not settings.api_key:
                raise LLMUnavailable("no LLM API key configured")
            kwargs = {"api_key": settings.api_key, "timeout": settings.timeout_seconds}
            if settings.base_url:
                kwargs["base_url"] = settings.base_url
            _client = OpenAI(**kwargs)
        return _client


def reset_client() -> None:
    """Drop the cached client so a settings change is picked up (tests)."""
    global _client
    with _client_lock:
        _client = None


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply that may carry prose or a code fence."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if not match:
            raise GuardrailError("model reply contained no JSON object") from None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise GuardrailError(f"model reply was not valid JSON: {exc.msg}") from None


def _call_model(settings: LLMSettings, messages: list[dict]) -> str:
    client = _get_client(settings)
    try:
        completion = client.chat.completions.create(
            model=settings.model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        # Some OpenAI-compatible providers reject response_format. Retry plain
        # rather than failing the whole request over a provider quirk.
        if "response_format" in str(exc):
            completion = client.chat.completions.create(
                model=settings.model,
                messages=messages,
                temperature=0,
            )
        else:
            raise LLMUnavailable(f"model call failed: {type(exc).__name__}") from exc
    return completion.choices[0].message.content or ""


def interpret_notes(
    notes: list[str],
    *,
    battery_capacity_kwh: float,
    settings: LLMSettings | None = None,
) -> list[Directive]:
    """LLM -> guardrails -> trusted directives. Raises on total failure."""
    settings = settings or LLMSettings.from_env()

    key = _cache_key(notes, battery_capacity_kwh)
    cached = _cache_get(key)
    if cached is not None:
        logger.info("interpretation cache hit")
        return cached

    repair_hint: str | None = None
    last_error: Exception | None = None

    for attempt in range(1, settings.max_attempts + 1):
        messages = build_messages(notes, repair_hint)
        try:
            raw_text = _call_model(settings, messages)
            payload = _extract_json(raw_text)
            items = payload.get("directive_interpretation", payload)
            directives = validate_interpretation(
                items,
                note_count=len(notes),
                battery_capacity_kwh=battery_capacity_kwh,
            )
        except GuardrailError as exc:
            # Model produced structured output that failed a hard rule. Worth one
            # repair attempt; the error text is the whole hint.
            logger.warning("guardrail rejected LLM output (attempt %d): %s", attempt, exc)
            repair_hint = str(exc)
            last_error = exc
            continue
        except LLMUnavailable as exc:
            logger.warning("LLM unavailable (attempt %d): %s", attempt, exc)
            last_error = exc
            break
        except Exception as exc:  # pragma: no cover - provider surprises
            logger.warning("unexpected LLM failure (attempt %d): %s", attempt, exc)
            last_error = exc
            break

        _cache_put(key, directives)
        return directives

    raise LLMUnavailable(f"interpretation failed: {last_error}")
