"""The 24-hour linear program.

Decision variables per hour h:

    g[h]  grid energy imported          >= 0, <= grid cap where a directive sets one
    s[h]  solar energy used             0 <= s[h] <= effective_solar[h]   (rest is curtailed)
    c[h]  battery charge amount         0 <= c[h] <= max_charge_kwh_per_hour
    d[h]  battery discharge amount      0 <= d[h] <= max_discharge_kwh_per_hour
    e[h]  battery energy AFTER hour h   reserve[h] <= e[h] <= capacity

Charge and discharge are separate non-negative variables rather than one signed
variable, because the hourly rate limits differ in each direction. The cost of
that choice is that a degenerate optimum may set both non-zero in the same hour
-- there is no round-trip loss in this problem, so the solver is not penalised
for it -- and the response schema allows exactly one action per hour. The solver
module nets them out afterwards; see `_net_battery`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pulp

from optimizer.constraints import DirectiveEffects

HOURS_IN_DAY = 24

# Nudges the solver away from pointless simultaneous / churning battery moves
# when they cost nothing. Bounded total distortion is 1e-6 * sum(rate limits),
# far below the judge's 0.01 BDT tolerance.
CHURN_EPSILON = 1e-6


@dataclass(frozen=True)
class BatterySpec:
    capacity_kwh: float
    initial_energy_kwh: float
    minimum_energy_kwh: float
    max_charge_kwh_per_hour: float
    max_discharge_kwh_per_hour: float


@dataclass
class LPModel:
    problem: pulp.LpProblem
    grid: list[pulp.LpVariable]
    solar: list[pulp.LpVariable]
    charge: list[pulp.LpVariable]
    discharge: list[pulp.LpVariable]
    energy: list[pulp.LpVariable]


def build_lp(
    *,
    demand_kwh: list[float],
    tariff: list[float],
    battery: BatterySpec,
    effects: DirectiveEffects,
    apply_directives: bool = True,
) -> LPModel:
    """Build the cost-minimising LP. `apply_directives=False` builds the base
    GridWise problem only, which the solver uses as a feasibility fallback."""

    problem = pulp.LpProblem("gridwise", pulp.LpMinimize)

    effective_solar = effects.effective_solar_kwh if apply_directives else None
    reserve = effects.reserve_kwh if apply_directives else None
    no_charge = effects.no_charge_hours if apply_directives else set()
    no_discharge = effects.no_discharge_hours if apply_directives else set()
    grid_cap = effects.grid_cap_kwh if apply_directives else {}

    grid, solar, charge, discharge, energy = [], [], [], [], []

    for h in range(HOURS_IN_DAY):
        solar_ceiling = (
            effective_solar[h] if effective_solar is not None else effects.effective_solar_kwh[h]
        )
        floor = reserve[h] if reserve is not None else battery.minimum_energy_kwh

        grid.append(
            pulp.LpVariable(f"grid_{h}", lowBound=0, upBound=grid_cap.get(h))
        )
        solar.append(pulp.LpVariable(f"solar_{h}", lowBound=0, upBound=solar_ceiling))
        charge.append(
            pulp.LpVariable(
                f"charge_{h}",
                lowBound=0,
                upBound=0 if h in no_charge else battery.max_charge_kwh_per_hour,
            )
        )
        discharge.append(
            pulp.LpVariable(
                f"discharge_{h}",
                lowBound=0,
                upBound=0 if h in no_discharge else battery.max_discharge_kwh_per_hour,
            )
        )
        energy.append(
            pulp.LpVariable(f"energy_{h}", lowBound=floor, upBound=battery.capacity_kwh)
        )

    # Objective: grid cost, plus a vanishing penalty on battery movement.
    problem += (
        pulp.lpSum(grid[h] * tariff[h] for h in range(HOURS_IN_DAY))
        + CHURN_EPSILON * pulp.lpSum(charge[h] + discharge[h] for h in range(HOURS_IN_DAY))
    )

    for h in range(HOURS_IN_DAY):
        # Energy balance (Problem Statement 9.5).
        problem += (
            grid[h] + solar[h] + discharge[h] == demand_kwh[h] + charge[h],
            f"balance_{h}",
        )
        # Battery state transition (9.1).
        previous = battery.initial_energy_kwh if h == 0 else energy[h - 1]
        problem += (energy[h] == previous + charge[h] - discharge[h], f"state_{h}")

    # End-of-day neutrality (9.6): the starting charge is a carrier, not a source.
    problem += (
        energy[HOURS_IN_DAY - 1] == battery.initial_energy_kwh,
        "end_of_day_neutrality",
    )

    return LPModel(
        problem=problem, grid=grid, solar=solar, charge=charge, discharge=discharge, energy=energy
    )
