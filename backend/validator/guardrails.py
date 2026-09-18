"""Deterministic guardrails over LLM output (Problem Statement Section 08).

LLM output is untrusted structured data until every check in here passes. This
module is the *only* gate between the language model and the optimizer: nothing
downstream re-checks a directive, so a hole here becomes a wrong schedule.

It normalises where normalising cannot change meaning (sorting hours, trimming
whitespace, coercing "13" to 13) and refuses where it could (unknown directive
type, factor out of range, a reserve above battery capacity).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

ALLOWED_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}

# Directive types that carry an hours list.
WINDOWED_TYPES = ALLOWED_TYPES - {"no_op"}

HOURS_IN_DAY = 24


class GuardrailError(ValueError):
    """Raised when LLM output cannot be trusted. Never leaks to the client body."""


@dataclass(frozen=True)
class Directive:
    note_index: int
    applies: bool
    directive_type: str
    structured_adjustment: dict[str, Any] | None
    explanation: str

    def as_response_dict(self) -> dict[str, Any]:
        return {
            "note_index": self.note_index,
            "applies": self.applies,
            "directive_type": self.directive_type,
            "structured_adjustment": self.structured_adjustment,
            "explanation": self.explanation,
        }


def _as_int_hour(value: Any) -> int:
    """Accept 13 and "13" and 13.0; reject 13.5 and anything outside 0-23."""
    if isinstance(value, bool):
        raise GuardrailError("hour must be an integer, not a boolean")
    if isinstance(value, str):
        value = value.strip()
        try:
            value = int(value)
        except ValueError:
            raise GuardrailError(f"hour {value!r} is not an integer") from None
    if isinstance(value, float):
        if not value.is_integer():
            raise GuardrailError(f"hour {value!r} is not a whole hour")
        value = int(value)
    if not isinstance(value, int):
        raise GuardrailError(f"hour {value!r} is not an integer")
    if not 0 <= value <= 23:
        raise GuardrailError(f"hour {value} is outside 0-23")
    return value


def _as_finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise GuardrailError(f"{field} must be a number, not a boolean")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise GuardrailError(f"{field} is not a number") from None
    if not math.isfinite(number):
        raise GuardrailError(f"{field} must be finite")
    return number


def _clean_hours(raw: Any) -> list[int]:
    """Unique whole hours 0-23 in ascending order (Section 08, 'Hours')."""
    if not isinstance(raw, (list, tuple)):
        raise GuardrailError("structured_adjustment.hours must be an array")
    hours = sorted({_as_int_hour(h) for h in raw})
    if not hours:
        raise GuardrailError("structured_adjustment.hours must not be empty")
    return hours


def _validate_adjustment(
    directive_type: str,
    raw: Any,
    *,
    battery_capacity_kwh: float,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise GuardrailError(f"{directive_type} requires a structured_adjustment object")

    hours = _clean_hours(raw.get("hours"))

    if directive_type == "solar_reduction":
        # factor is the fraction of solar that REMAINS: an 80% reduction is 0.2.
        factor = _as_finite_float(raw.get("factor"), "factor")
        if not 0.0 <= factor <= 1.0:
            raise GuardrailError(f"factor {factor} is outside 0-1")
        return {"hours": hours, "factor": factor}

    if directive_type == "minimum_battery_reserve":
        reserve = _as_finite_float(raw.get("minimum_energy_kwh"), "minimum_energy_kwh")
        if reserve < 0:
            raise GuardrailError("minimum_energy_kwh must be non-negative")
        if reserve > battery_capacity_kwh:
            raise GuardrailError("minimum_energy_kwh exceeds battery capacity")
        return {"hours": hours, "minimum_energy_kwh": reserve}

    if directive_type == "max_grid_window":
        cap = _as_finite_float(raw.get("max_grid_kwh"), "max_grid_kwh")
        if cap < 0:
            raise GuardrailError("max_grid_kwh must be non-negative")
        return {"hours": hours, "max_grid_kwh": cap}

    # no_charge_window / no_discharge_window carry hours only. Anything else the
    # model bolted on is dropped rather than forwarded.
    return {"hours": hours}


def validate_interpretation(
    raw_items: Any,
    *,
    note_count: int,
    battery_capacity_kwh: float,
) -> list[Directive]:
    """Turn raw LLM output into exactly `note_count` trusted directives.

    Raises GuardrailError on anything that does not match Section 04/08. The
    caller decides whether to retry the model or fall back.
    """
    if not isinstance(raw_items, (list, tuple)):
        raise GuardrailError("directive_interpretation must be an array")
    if len(raw_items) != note_count:
        raise GuardrailError(
            f"expected {note_count} interpretation entries, got {len(raw_items)}"
        )

    by_index: dict[int, Directive] = {}

    for item in raw_items:
        if not isinstance(item, dict):
            raise GuardrailError("each interpretation entry must be an object")

        try:
            note_index = int(item.get("note_index"))
        except (TypeError, ValueError):
            raise GuardrailError("note_index is missing or not an integer") from None
        if not 0 <= note_index < note_count:
            raise GuardrailError(f"note_index {note_index} does not name a note")
        if note_index in by_index:
            raise GuardrailError(f"note_index {note_index} appears more than once")

        directive_type = item.get("directive_type")
        if directive_type not in ALLOWED_TYPES:
            raise GuardrailError(f"unsupported directive_type {directive_type!r}")

        explanation = item.get("explanation")
        explanation = explanation.strip() if isinstance(explanation, str) else ""

        if directive_type == "no_op":
            # applies=false and a null adjustment are mandatory here, and this is
            # the ONLY directive allowed with applies=false.
            by_index[note_index] = Directive(
                note_index=note_index,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation=explanation or "This note does not affect today's energy schedule.",
            )
            continue

        adjustment = _validate_adjustment(
            directive_type,
            item.get("structured_adjustment"),
            battery_capacity_kwh=battery_capacity_kwh,
        )
        by_index[note_index] = Directive(
            note_index=note_index,
            applies=True,
            directive_type=directive_type,
            structured_adjustment=adjustment,
            explanation=explanation or f"Applied {directive_type} from this note.",
        )

    missing = sorted(set(range(note_count)) - set(by_index))
    if missing:
        raise GuardrailError(f"no interpretation returned for note index {missing}")

    # Returned in note_index order: 0, 1, ... N-1.
    return [by_index[i] for i in range(note_count)]
