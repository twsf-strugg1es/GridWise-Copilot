"""Run the 10 public sample cases and grade ourselves the way the judge would.

Three modes, because they fail differently and you want to know which half broke:

    --offline   skip the LLM entirely and feed the optimizer the case's own
                ground-truth directives. Proves the OPTIMIZER and the plan
                validity without spending a token or needing a key.
    (default)   in-process through the real FastAPI app, LLM included.
    --url URL   against a deployed service, exactly as the judge will call it.

Usage:
    python scripts/run_samples.py --offline
    python scripts/run_samples.py
    python scripts/run_samples.py --url https://your-service.example.com
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.replay import replay  # noqa: E402

DEFAULT_CASES = REPO_ROOT / "tests" / "public_sample_cases.json"


def _load_cases(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["cases"]


def _offline_response(case: dict) -> dict:
    """Bypass the LLM: hand the optimizer the organizer's own directives."""
    from backend.validator.guardrails import validate_interpretation
    from optimizer.model import BatterySpec
    from optimizer.solver import optimize

    scenario = case["input"]
    hours = sorted(scenario["hours"], key=lambda h: h["hour"])
    battery_in = scenario["battery"]

    directives = validate_interpretation(
        case["expected_output"]["directive_interpretation"],
        note_count=len(scenario["operator_notes"]),
        battery_capacity_kwh=battery_in["capacity_kwh"],
    )

    battery = BatterySpec(
        capacity_kwh=battery_in["capacity_kwh"],
        initial_energy_kwh=battery_in["initial_energy_kwh"],
        minimum_energy_kwh=battery_in["minimum_energy_kwh"],
        max_charge_kwh_per_hour=battery_in["max_charge_kwh_per_hour"],
        max_discharge_kwh_per_hour=battery_in["max_discharge_kwh_per_hour"],
    )

    result, _ = optimize(
        demand_kwh=[h["demand_kwh"] for h in hours],
        solar_kwh=[h["solar_kwh"] for h in hours],
        tariff=[h["tariff_bdt_per_kwh"] for h in hours],
        battery=battery,
        directives=directives,
    )

    return {
        "scenario_id": scenario["scenario_id"],
        "directive_interpretation": [d.as_response_dict() for d in directives],
        "hourly_plan": [row.as_dict() for row in result.hourly_plan],
        "total_grid_kwh": result.total_grid_kwh,
        "total_cost_bdt": result.total_cost_bdt,
        "peak_grid_kwh": result.peak_grid_kwh,
        "plan_summary": "offline optimizer check",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--url", default=None, help="base URL of a deployed service")
    parser.add_argument("--offline", action="store_true", help="skip the LLM, optimizer only")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"cases file not found: {cases_path}")
        return 2
    cases = _load_cases(cases_path)

    client = None
    if not args.offline and not args.url:
        from fastapi.testclient import TestClient

        from backend.main import app

        client = TestClient(app)

    mode = "offline" if args.offline else (args.url or "in-process")
    print(f"mode: {mode}\ncases: {len(cases)}\n")

    valid_count = 0
    interpretation_ok = 0
    ratios: list[float] = []
    latencies: list[float] = []
    failures: list[tuple[str, list[str], list[str]]] = []

    for case in cases:
        scenario = case["input"]
        started = time.perf_counter()

        if args.offline:
            response = _offline_response(case)
        elif args.url:
            import httpx

            reply = httpx.post(
                args.url.rstrip("/") + "/optimize-energy", json=scenario, timeout=35.0
            )
            if reply.status_code != 200:
                failures.append((scenario["scenario_id"], [f"HTTP {reply.status_code}"], []))
                print(f"  {scenario['scenario_id']:<12} HTTP {reply.status_code}")
                continue
            response = reply.json()
        else:
            reply = client.post("/optimize-energy", json=scenario)
            if reply.status_code != 200:
                failures.append((scenario["scenario_id"], [f"HTTP {reply.status_code}"], []))
                print(f"  {scenario['scenario_id']:<12} HTTP {reply.status_code}")
                continue
            response = reply.json()

        elapsed = time.perf_counter() - started
        latencies.append(elapsed)

        report = replay(case, response)
        if report.valid:
            valid_count += 1
        if report.interpretation_ok:
            interpretation_ok += 1
        ratio = report.quality_ratio
        if ratio is not None:
            ratios.append(ratio)

        status = "VALID  " if report.valid else "INVALID"
        interp = "interp OK " if report.interpretation_ok else "interp BAD"
        cost = f"cost {report.total_cost_bdt:>10.2f}"
        ref = (
            f" ref {report.reference_cost_bdt:>10.2f}"
            if report.reference_cost_bdt is not None
            else ""
        )
        quality = f" ratio {ratio:.4f}" if ratio is not None else ""
        print(
            f"  {scenario['scenario_id']:<12} {status} {interp} {cost}{ref}{quality}  {elapsed*1000:6.0f}ms"
        )

        if not report.valid or not report.interpretation_ok:
            failures.append(
                (scenario["scenario_id"], report.violations, report.interpretation_errors)
            )
            if args.verbose:
                for line in report.violations[:8]:
                    print(f"        ! {line}")
                for line in report.interpretation_errors[:8]:
                    print(f"        ? {line}")

    print()
    print(f"valid schedules      : {valid_count}/{len(cases)}")
    print(f"interpretation match : {interpretation_ok}/{len(cases)}")
    if ratios:
        avg = sum(ratios) / len(ratios)
        print(f"optimization quality : {avg:.4f}  -> {10 * avg:.2f}/10 points")
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
        print(f"latency p95          : {p95*1000:.0f} ms")

    if failures and not args.verbose:
        print("\nrerun with --verbose to see why these failed:")
        for scenario_id, violations, interp in failures:
            print(f"  {scenario_id}: {len(violations)} violation(s), {len(interp)} interp error(s)")

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
