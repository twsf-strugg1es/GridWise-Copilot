"""Optimizer and API tests, including the full public sample suite."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.validator.guardrails import Directive, validate_interpretation
from optimizer.model import BatterySpec
from optimizer.solver import _net_battery, optimize
from scripts.replay import replay

CASES_PATH = Path(__file__).parent / "public_sample_cases.json"
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]

FLAT_BATTERY = BatterySpec(
    capacity_kwh=200.0,
    initial_energy_kwh=100.0,
    minimum_energy_kwh=20.0,
    max_charge_kwh_per_hour=50.0,
    max_discharge_kwh_per_hour=50.0,
)


# --------------------------------------------------------------------------- #
# Netting
# --------------------------------------------------------------------------- #


def test_simultaneous_charge_and_discharge_collapses_to_one_action():
    # A degenerate LP optimum can set both; the schema allows exactly one action.
    assert _net_battery(30.0, 10.0) == ("charge", 20.0)
    assert _net_battery(10.0, 30.0) == ("discharge", 20.0)
    assert _net_battery(15.0, 15.0) == ("idle", 0.0)


def test_no_plan_row_ever_reports_both_directions():
    result, _ = optimize(
        demand_kwh=[100.0] * 24,
        solar_kwh=[0.0] * 24,
        tariff=[5.0 if h < 12 else 15.0 for h in range(24)],
        battery=FLAT_BATTERY,
        directives=[],
    )
    for row in result.hourly_plan:
        assert row.battery_action in ("charge", "discharge", "idle")
        if row.battery_action == "idle":
            assert row.battery_kwh == 0.0


# --------------------------------------------------------------------------- #
# Directive application
# --------------------------------------------------------------------------- #


def _directive(kind, adjustment):
    return Directive(0, True, kind, adjustment, "test")


def test_battery_returns_to_its_starting_level():
    result, _ = optimize(
        demand_kwh=[120.0] * 24,
        solar_kwh=[0.0] * 24,
        tariff=[3.0 if h < 6 else 12.0 for h in range(24)],
        battery=FLAT_BATTERY,
        directives=[],
    )
    assert result.hourly_plan[-1].battery_energy_after_kwh == pytest.approx(
        FLAT_BATTERY.initial_energy_kwh, abs=0.01
    )


def test_no_charge_window_is_obeyed():
    result, _ = optimize(
        demand_kwh=[100.0] * 24,
        solar_kwh=[0.0] * 24,
        tariff=[2.0 if h < 6 else 20.0 for h in range(24)],
        battery=FLAT_BATTERY,
        directives=[_directive("no_charge_window", {"hours": [0, 1, 2, 3, 4, 5]})],
    )
    for hour in range(6):
        assert result.hourly_plan[hour].battery_action != "charge"


def test_max_grid_window_is_obeyed():
    result, _ = optimize(
        demand_kwh=[100.0] * 24,
        solar_kwh=[0.0] * 24,
        tariff=[10.0] * 24,
        battery=FLAT_BATTERY,
        directives=[_directive("max_grid_window", {"hours": [12, 13], "max_grid_kwh": 60.0})],
    )
    assert result.hourly_plan[12].grid_kwh <= 60.01
    assert result.hourly_plan[13].grid_kwh <= 60.01


def test_minimum_reserve_raises_the_floor_only_in_its_hours():
    result, _ = optimize(
        demand_kwh=[100.0] * 24,
        solar_kwh=[0.0] * 24,
        tariff=[2.0 if h < 6 else 20.0 for h in range(24)],
        battery=FLAT_BATTERY,
        directives=[_directive("minimum_battery_reserve", {"hours": [18, 19], "minimum_energy_kwh": 150.0})],
    )
    assert result.hourly_plan[18].battery_energy_after_kwh >= 149.99
    assert result.hourly_plan[19].battery_energy_after_kwh >= 149.99


def test_solar_reduction_caps_usable_solar():
    result, _ = optimize(
        demand_kwh=[100.0] * 24,
        solar_kwh=[80.0 if 10 <= h <= 14 else 0.0 for h in range(24)],
        tariff=[10.0] * 24,
        battery=FLAT_BATTERY,
        directives=[_directive("solar_reduction", {"hours": [13, 14], "factor": 0.2})],
    )
    # factor is the fraction REMAINING: 80 kWh * 0.2 = 16 kWh usable.
    assert result.hourly_plan[13].solar_used_kwh <= 16.01
    assert result.hourly_plan[12].solar_used_kwh > 16.01


def test_impossible_directive_degrades_instead_of_crashing():
    # A grid cap below demand with an empty battery cannot be met. The service
    # must still answer with a parseable plan rather than a 500.
    result, _ = optimize(
        demand_kwh=[500.0] * 24,
        solar_kwh=[0.0] * 24,
        tariff=[10.0] * 24,
        battery=BatterySpec(10.0, 10.0, 10.0, 1.0, 1.0),
        directives=[_directive("max_grid_window", {"hours": list(range(24)), "max_grid_kwh": 1.0})],
    )
    assert len(result.hourly_plan) == 24
    assert result.degraded is True


# --------------------------------------------------------------------------- #
# Public sample suite, optimizer only (no LLM, no key needed)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case", CASES, ids=[c["input"]["scenario_id"] for c in CASES])
def test_public_sample_case_is_valid_and_optimal(case):
    scenario = case["input"]
    hours = sorted(scenario["hours"], key=lambda h: h["hour"])
    battery_in = scenario["battery"]

    directives = validate_interpretation(
        case["expected_output"]["directive_interpretation"],
        note_count=len(scenario["operator_notes"]),
        battery_capacity_kwh=battery_in["capacity_kwh"],
    )

    result, _ = optimize(
        demand_kwh=[h["demand_kwh"] for h in hours],
        solar_kwh=[h["solar_kwh"] for h in hours],
        tariff=[h["tariff_bdt_per_kwh"] for h in hours],
        battery=BatterySpec(**battery_in),
        directives=directives,
    )

    response = {
        "scenario_id": scenario["scenario_id"],
        "directive_interpretation": [d.as_response_dict() for d in directives],
        "hourly_plan": [row.as_dict() for row in result.hourly_plan],
        "total_grid_kwh": result.total_grid_kwh,
        "total_cost_bdt": result.total_cost_bdt,
        "peak_grid_kwh": result.peak_grid_kwh,
        "plan_summary": "test",
    }

    report = replay(case, response)
    assert report.valid, report.violations
    # We should match the organizer's optimum, not merely stay under it.
    assert report.quality_ratio == pytest.approx(1.0, abs=1e-4)


# --------------------------------------------------------------------------- #
# API contract
# --------------------------------------------------------------------------- #

client = TestClient(app)


def test_health():
    reply = client.get("/health")
    assert reply.status_code == 200
    assert reply.json()["status"] == "ok"


def test_malformed_request_is_a_400_not_a_500():
    reply = client.post("/optimize-energy", json={"scenario_id": "X"})
    assert reply.status_code == 400
    assert "error" in reply.json()


def test_a_short_hours_array_is_rejected():
    scenario = json.loads(json.dumps(CASES[0]["input"]))
    scenario["hours"] = scenario["hours"][:12]
    assert client.post("/optimize-energy", json=scenario).status_code == 400


def test_four_notes_are_rejected():
    scenario = json.loads(json.dumps(CASES[0]["input"]))
    scenario["operator_notes"] = ["a", "b", "c", "d"]
    assert client.post("/optimize-energy", json=scenario).status_code == 400


def test_full_pipeline_returns_a_schema_valid_response():
    # Runs with whatever interpreter is configured; the schema and the physics
    # must hold either way.
    scenario = CASES[0]["input"]
    reply = client.post("/optimize-energy", json=scenario)
    assert reply.status_code == 200
    body = reply.json()
    assert body["scenario_id"] == scenario["scenario_id"]
    assert len(body["directive_interpretation"]) == len(scenario["operator_notes"])
    assert [d["note_index"] for d in body["directive_interpretation"]] == list(
        range(len(scenario["operator_notes"]))
    )
    assert len(body["hourly_plan"]) == 24
    for entry in body["directive_interpretation"]:
        if entry["directive_type"] == "no_op":
            assert entry["applies"] is False and entry["structured_adjustment"] is None
        else:
            assert entry["applies"] is True and entry["structured_adjustment"] is not None
