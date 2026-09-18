"""Turn validated directives into the numbers the LP actually constrains.

Section 5.3 of the Problem Statement is the whole of this file. The only
judgement call it makes is how to combine two directives of the same type over
the same hour: it always takes the STRICTER of the two, because both were issued
by an operator and satisfying only the looser one would violate the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.validator.guardrails import Directive

HOURS_IN_DAY = 24


@dataclass
class DirectiveEffects:
    """Per-hour effects, indexed 0..23."""

    effective_solar_kwh: list[float]
    reserve_kwh: list[float]
    no_charge_hours: set[int] = field(default_factory=set)
    no_discharge_hours: set[int] = field(default_factory=set)
    grid_cap_kwh: dict[int, float] = field(default_factory=dict)
    applied_types: list[str] = field(default_factory=list)


def build_effects(
    *,
    solar_kwh: list[float],
    base_minimum_energy_kwh: float,
    directives: list[Directive],
) -> DirectiveEffects:
    effects = DirectiveEffects(
        effective_solar_kwh=list(solar_kwh),
        reserve_kwh=[base_minimum_energy_kwh] * HOURS_IN_DAY,
    )

    for directive in directives:
        if not directive.applies or directive.structured_adjustment is None:
            continue

        adjustment = directive.structured_adjustment
        hours = adjustment["hours"]
        effects.applied_types.append(directive.directive_type)

        if directive.directive_type == "solar_reduction":
            factor = adjustment["factor"]
            for hour in hours:
                # Two overlapping reductions: the smaller remaining fraction wins.
                effects.effective_solar_kwh[hour] = min(
                    effects.effective_solar_kwh[hour], solar_kwh[hour] * factor
                )

        elif directive.directive_type == "minimum_battery_reserve":
            reserve = adjustment["minimum_energy_kwh"]
            for hour in hours:
                # Section 5.3: max(base minimum, directive minimum).
                effects.reserve_kwh[hour] = max(effects.reserve_kwh[hour], reserve)

        elif directive.directive_type == "no_charge_window":
            effects.no_charge_hours.update(hours)

        elif directive.directive_type == "no_discharge_window":
            effects.no_discharge_hours.update(hours)

        elif directive.directive_type == "max_grid_window":
            cap = adjustment["max_grid_kwh"]
            for hour in hours:
                existing = effects.grid_cap_kwh.get(hour)
                effects.grid_cap_kwh[hour] = cap if existing is None else min(existing, cap)

    return effects
