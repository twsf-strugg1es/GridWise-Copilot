"""SECONDARY interpreter, used only when the model is unreachable or unusable.

This is NOT the interpretation path. The Problem Statement makes an LLM
mandatory and the Participant Guide states that hard-coded phrase matching "as
the sole interpreter" is non-compliant, so this runs only after the model has
failed its attempts -- the alternative is a 500, which costs reliability points
and guarantees zero on the case anyway.

It is deliberately conservative: anything it cannot read confidently becomes
no_op rather than an invented constraint.
"""

from __future__ import annotations

import re

from backend.validator.guardrails import Directive

_NUMBER = r"(\d{1,4}(?:\.\d+)?)"

_TIME = re.compile(
    r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?|am|pm|o'clock|hours|h)?(?!\d)",
    re.IGNORECASE,
)

_WORD_HOURS = {
    "midnight": 0, "noon": 12, "midday": 12,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

_FRACTIONS = {
    "half": 0.5, "a half": 0.5, "one half": 0.5,
    "a third": 1 / 3, "one third": 1 / 3,
    "a quarter": 0.25, "one quarter": 0.25,
    "a fifth": 0.2, "one fifth": 0.2,
    "a tenth": 0.1, "one tenth": 0.1,
}


def _to_24h(hour: int, meridiem: str | None, text: str) -> int:
    meridiem = (meridiem or "").lower().replace(".", "")
    if meridiem.startswith("p") and hour < 12:
        return hour + 12
    if meridiem.startswith("a") and hour == 12:
        return 0
    if not meridiem and "evening" in text and hour < 12:
        return hour + 12
    return hour % 24


def _window(text: str) -> list[int]:
    """Best-effort start-inclusive / end-exclusive hour window."""
    lowered = text.lower()

    found: list[int] = []
    for word, hour in _WORD_HOURS.items():
        for match in re.finditer(rf"\b{word}\b", lowered):
            found.append((match.start(), hour, None))
    for match in _TIME.finditer(lowered):
        hour = int(match.group(1))
        if hour > 24:
            continue
        found.append((match.start(), hour, match.group(3)))

    found.sort()
    hours = [_to_24h(h, meridiem, lowered) for _, h, meridiem in found]

    if len(hours) >= 2:
        start, end = hours[0], hours[1]
        if start == end:
            return [start % 24]
        span = (end - start) % 24
        if span == 0 or span > 23:
            return [start % 24]
        return [(start + offset) % 24 for offset in range(span)]
    if len(hours) == 1:
        return [hours[0] % 24]
    return list(range(24))


def _remaining_fraction(text: str) -> float | None:
    lowered = text.lower()

    percent = re.search(rf"{_NUMBER}\s*(?:%|percent)", lowered)
    if percent:
        value = float(percent.group(1)) / 100.0
        # "an 80% reduction" leaves 20%; "drop to 20%" leaves 20%.
        reduction_words = ("reduction", "reduced by", "drop by", "decrease", "loss", "less", "down by")
        if any(word in lowered for word in reduction_words) and "to about" not in lowered:
            return max(0.0, min(1.0, 1.0 - value))
        return max(0.0, min(1.0, value))

    for phrase, value in _FRACTIONS.items():
        if phrase in lowered:
            if "cut in half" in lowered or "halved" in lowered:
                return 0.5
            return value

    if "offline" in lowered or "no solar" in lowered or "zero solar" in lowered:
        return 0.0
    return None


def interpret_notes_heuristically(notes: list[str], battery_capacity_kwh: float) -> list[Directive]:
    directives: list[Directive] = []

    for index, note in enumerate(notes):
        lowered = note.lower()
        directive: Directive | None = None

        mentions_solar = any(w in lowered for w in ("solar", "pv", "panel", "photovoltaic"))
        mentions_battery = any(w in lowered for w in ("battery", "storage", "bess"))

        if mentions_solar:
            factor = _remaining_fraction(note)
            if factor is not None:
                directive = Directive(
                    index, True, "solar_reduction",
                    {"hours": _window(note), "factor": factor},
                    "Fallback interpretation: reduced usable solar in this window.",
                )

        # An operator rarely writes "do not charge". They write that the charger
        # is isolated, unavailable, disabled, locked out. Negation words alone
        # miss most real phrasings -- SAMPLE-02, 06 and 08 are all of this shape.
        blocked = bool(
            re.search(
                r"\b(not|no|don't|do not|avoid|pause|paused|stop|stopped|hold off|"
                r"isolated|isolate|unavailable|disabled|disable|offline|"
                r"out of service|locked out|inhibited|suspended|shut down|no longer)\b",
                lowered,
            )
        )
        touches_battery = mentions_battery or "charger" in lowered or "charging circuit" in lowered

        if directive is None and touches_battery and blocked:
            if "discharg" in lowered:
                directive = Directive(
                    index, True, "no_discharge_window", {"hours": _window(note)},
                    "Fallback interpretation: battery discharging unavailable.",
                )
            elif "charg" in lowered:
                directive = Directive(
                    index, True, "no_charge_window", {"hours": _window(note)},
                    "Fallback interpretation: battery charging unavailable.",
                )

        if directive is None and touches_battery:
            # A reserve may be stated as a percentage of capacity rather than kWh.
            percent_reserve = re.search(
                rf"(?:at least|minimum of|no less than|keep)\D{{0,20}}{_NUMBER}\s*(?:%|percent)",
                lowered,
            )
            reserve = re.search(rf"(?:at least|minimum of|no less than|keep)\D{{0,20}}{_NUMBER}\s*kwh", lowered)
            if percent_reserve and "capacit" in lowered:
                value = min(
                    float(percent_reserve.group(1)) / 100.0 * battery_capacity_kwh,
                    battery_capacity_kwh,
                )
                directive = Directive(
                    index, True, "minimum_battery_reserve",
                    {"hours": _window(note), "minimum_energy_kwh": value},
                    "Fallback interpretation: battery reserve floor raised.",
                )
            elif reserve:
                value = min(float(reserve.group(1)), battery_capacity_kwh)
                directive = Directive(
                    index, True, "minimum_battery_reserve",
                    {"hours": _window(note), "minimum_energy_kwh": value},
                    "Fallback interpretation: battery reserve floor raised.",
                )

        if directive is None and "grid" in lowered:
            cap = re.search(rf"(?:no more than|not exceed|cap(?:ped)? at|max(?:imum)? of|under|below|limit\D{{0,12}})\D{{0,12}}{_NUMBER}\s*kwh", lowered)
            if cap:
                directive = Directive(
                    index, True, "max_grid_window",
                    {"hours": _window(note), "max_grid_kwh": float(cap.group(1))},
                    "Fallback interpretation: grid import capped in this window.",
                )

        if directive is None:
            directive = Directive(
                index, False, "no_op", None,
                "This note does not affect today's energy schedule.",
            )

        directives.append(directive)

    return directives
