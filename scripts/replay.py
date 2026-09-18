"""An independent re-implementation of the judge's checks.

Deliberately written from the Problem Statement rather than by importing the
service, so a bug in the optimizer cannot hide behind the same bug in the
checker. Section 11 of the Problem Statement is the checklist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

TOL = 0.01  # absolute tolerance, kWh and BDT (Problem Statement 11.5)
HOURS_IN_DAY = 24


@dataclass
class Report:
    scenario_id: str
    violations: list[str] = field(default_factory=list)
    interpretation_errors: list[str] = field(default_factory=list)
    total_cost_bdt: float = 0.0
    reference_cost_bdt: float | None = None

    @property
    def valid(self) -> bool:
        return not self.violations

    @property
    def interpretation_ok(self) -> bool:
        return not self.interpretation_errors

    @property
    def quality_ratio(self) -> float | None:
        """min(1, organizer_optimal / team_cost) -- the Optimization Quality formula."""
        if self.reference_cost_bdt is None or not self.valid:
            return None
        if abs(self.reference_cost_bdt) <= TOL and abs(self.total_cost_bdt) <= TOL:
            return 1.0
        if abs(self.total_cost_bdt) <= TOL:
            return 1.0
        return min(1.0, self.reference_cost_bdt / self.total_cost_bdt)


def _near(a: float, b: float, tol: float = TOL) -> bool:
    return abs(a - b) <= tol


def _ground_truth_effects(directives, base_min, solar):
    effective_solar = list(solar)
    reserve = [base_min] * HOURS_IN_DAY
    no_charge = set()
    no_discharge = set()
    grid_cap = {}

    for directive in directives:
        if not directive.get("applies"):
            continue
        adjustment = directive.get("structured_adjustment") or {}
        hours = adjustment.get("hours", [])
        kind = directive.get("directive_type")

        if kind == "solar_reduction":
            for h in hours:
                effective_solar[h] = min(effective_solar[h], solar[h] * adjustment["factor"])
        elif kind == "minimum_battery_reserve":
            for h in hours:
                reserve[h] = max(reserve[h], adjustment["minimum_energy_kwh"])
        elif kind == "no_charge_window":
            no_charge.update(hours)
        elif kind == "no_discharge_window":
            no_discharge.update(hours)
        elif kind == "max_grid_window":
            for h in hours:
                cap = adjustment["max_grid_kwh"]
                grid_cap[h] = min(grid_cap.get(h, cap), cap)

    return effective_solar, reserve, no_charge, no_discharge, grid_cap


def check_interpretation(actual, expected):
    """Compare against organizer ground truth. Explanation text is NOT compared."""
    errors = []

    if len(actual) != len(expected):
        return ["expected %d interpretation entries, got %d" % (len(expected), len(actual))]

    if [d.get("note_index") for d in actual] != list(range(len(expected))):
        errors.append("directive_interpretation is not in note_index order 0..N-1")

    by_index = {d.get("note_index"): d for d in actual}

    for want in expected:
        index = want["note_index"]
        got = by_index.get(index)
        if got is None:
            errors.append("note %s: missing" % index)
            continue

        if bool(got.get("applies")) != bool(want["applies"]):
            errors.append(
                "note %s: applies=%s want %s" % (index, got.get("applies"), want["applies"])
            )
        if got.get("directive_type") != want["directive_type"]:
            errors.append(
                "note %s: type=%s want %s"
                % (index, got.get("directive_type"), want["directive_type"])
            )
            continue

        want_adj = want["structured_adjustment"]
        got_adj = got.get("structured_adjustment")
        if want_adj is None:
            if got_adj is not None:
                errors.append("note %s: no_op must carry a null structured_adjustment" % index)
            continue
        if not isinstance(got_adj, dict):
            errors.append("note %s: structured_adjustment missing" % index)
            continue

        if got_adj.get("hours") != want_adj.get("hours"):
            errors.append(
                "note %s: hours=%s want %s" % (index, got_adj.get("hours"), want_adj.get("hours"))
            )
        for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
            if key in want_adj:
                if key not in got_adj:
                    errors.append("note %s: %s missing" % (index, key))
                elif not _near(float(got_adj[key]), float(want_adj[key])):
                    errors.append(
                        "note %s: %s=%s want %s" % (index, key, got_adj[key], want_adj[key])
                    )

    return errors


def replay(case, response):
    scenario = case["input"]
    expected = case.get("expected_output", {})
    report = Report(scenario_id=scenario["scenario_id"])

    # --- top level ---------------------------------------------------------
    if response.get("scenario_id") != scenario["scenario_id"]:
        report.violations.append("scenario_id does not echo the request")

    plan = response.get("hourly_plan")
    if not isinstance(plan, list) or len(plan) != HOURS_IN_DAY:
        report.violations.append("hourly_plan must contain exactly 24 entries")
        return report
    if sorted(row.get("hour") for row in plan) != list(range(HOURS_IN_DAY)):
        report.violations.append("hourly_plan hours must be 0..23, each exactly once")
        return report

    plan = sorted(plan, key=lambda r: r["hour"])
    hours_in = sorted(scenario["hours"], key=lambda h: h["hour"])
    demand = [h["demand_kwh"] for h in hours_in]
    solar = [h["solar_kwh"] for h in hours_in]
    tariff = [h["tariff_bdt_per_kwh"] for h in hours_in]
    battery = scenario["battery"]

    # --- interpretation vs ground truth ------------------------------------
    if expected.get("directive_interpretation"):
        report.interpretation_errors = check_interpretation(
            response.get("directive_interpretation") or [],
            expected["directive_interpretation"],
        )

    # Directives are replayed from ORGANIZER ground truth where available, which
    # is what the judge does: correct extraction without application fails here.
    ground_truth = expected.get("directive_interpretation") or response.get(
        "directive_interpretation", []
    )
    effective_solar, reserve, no_charge, no_discharge, grid_cap = _ground_truth_effects(
        ground_truth, battery["minimum_energy_kwh"], solar
    )

    # --- hour by hour ------------------------------------------------------
    energy = battery["initial_energy_kwh"]

    for h, row in enumerate(plan):
        grid = row.get("grid_kwh")
        solar_used = row.get("solar_used_kwh")
        action = row.get("battery_action")
        magnitude = row.get("battery_kwh")
        after = row.get("battery_energy_after_kwh")

        for name, value in (
            ("grid_kwh", grid),
            ("solar_used_kwh", solar_used),
            ("battery_kwh", magnitude),
            ("battery_energy_after_kwh", after),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                report.violations.append("hour %d: %s is not a finite number" % (h, name))
                return report
            if value < -TOL:
                report.violations.append("hour %d: %s is negative (%s)" % (h, name, value))

        if action not in ("charge", "discharge", "idle"):
            report.violations.append("hour %d: battery_action %r is not allowed" % (h, action))
            return report
        if action == "idle" and abs(magnitude) > TOL:
            report.violations.append("hour %d: idle must carry battery_kwh 0" % h)

        charge = magnitude if action == "charge" else 0.0
        discharge = magnitude if action == "discharge" else 0.0

        if charge - battery["max_charge_kwh_per_hour"] > TOL:
            report.violations.append("hour %d: charge %s exceeds hourly limit" % (h, charge))
        if discharge - battery["max_discharge_kwh_per_hour"] > TOL:
            report.violations.append("hour %d: discharge %s exceeds hourly limit" % (h, discharge))

        if solar_used - effective_solar[h] > TOL:
            report.violations.append(
                "hour %d: solar_used %s exceeds effective solar %.4f"
                % (h, solar_used, effective_solar[h])
            )

        if not _near(grid + solar_used + discharge, demand[h] + charge):
            report.violations.append(
                "hour %d: energy balance broken (%s + %s + %s != %s + %s)"
                % (h, grid, solar_used, discharge, demand[h], charge)
            )

        energy = energy + charge - discharge
        if not _near(after, energy):
            report.violations.append(
                "hour %d: battery_energy_after_kwh %s does not match the transition (%.4f)"
                % (h, after, energy)
            )
        energy = after  # continue from what the plan claims

        if after - battery["capacity_kwh"] > TOL:
            report.violations.append("hour %d: battery above capacity (%s)" % (h, after))
        if reserve[h] - after > TOL:
            report.violations.append(
                "hour %d: battery %s below required reserve %s" % (h, after, reserve[h])
            )

        if h in no_charge and charge > TOL:
            report.violations.append("hour %d: charging inside a no_charge_window" % h)
        if h in no_discharge and discharge > TOL:
            report.violations.append("hour %d: discharging inside a no_discharge_window" % h)
        if h in grid_cap and grid - grid_cap[h] > TOL:
            report.violations.append(
                "hour %d: grid %s exceeds max_grid_window cap %s" % (h, grid, grid_cap[h])
            )

    if not _near(energy, battery["initial_energy_kwh"]):
        report.violations.append(
            "end-of-day battery %s does not return to initial %s"
            % (energy, battery["initial_energy_kwh"])
        )

    # --- totals ------------------------------------------------------------
    total_grid = sum(row["grid_kwh"] for row in plan)
    total_cost = sum(row["grid_kwh"] * tariff[row["hour"]] for row in plan)
    peak_grid = max(row["grid_kwh"] for row in plan)

    if not _near(response.get("total_grid_kwh", -1), total_grid):
        report.violations.append(
            "total_grid_kwh %s != recalculated %.4f" % (response.get("total_grid_kwh"), total_grid)
        )
    if not _near(response.get("total_cost_bdt", -1), total_cost):
        report.violations.append(
            "total_cost_bdt %s != recalculated %.4f" % (response.get("total_cost_bdt"), total_cost)
        )
    if not _near(response.get("peak_grid_kwh", -1), peak_grid):
        report.violations.append(
            "peak_grid_kwh %s != recalculated %.4f" % (response.get("peak_grid_kwh"), peak_grid)
        )
    if not isinstance(response.get("plan_summary"), str) or not response["plan_summary"].strip():
        report.violations.append("plan_summary must be a non-empty string")

    report.total_cost_bdt = total_cost
    if expected.get("total_cost_bdt") is not None:
        report.reference_cost_bdt = float(expected["total_cost_bdt"])

    return report
