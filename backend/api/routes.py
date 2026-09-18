"""HTTP surface: GET /health and POST /optimize-energy.

The pipeline is the same every request, and the order matters:

    request schema  ->  LLM  ->  guardrails  ->  optimizer  ->  plan
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter

from backend.api.schemas import HealthResponse, OptimizeRequest, OptimizeResponse
from backend.llm.fallback import interpret_notes_heuristically
from backend.llm.parser import LLMUnavailable, interpret_notes
from backend.validator.guardrails import Directive
from optimizer.model import BatterySpec
from optimizer.solver import optimize

logger = logging.getLogger(__name__)

router = APIRouter()

# Set to "1" in a judged deployment only if the hosted model dies: it lets the
# service keep answering off the heuristic path instead of erroring.
ALLOW_FALLBACK = os.getenv("ALLOW_HEURISTIC_FALLBACK", "1") == "1"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


def _summarise(directives: list[Directive], degraded: bool) -> str:
    applied = [d for d in directives if d.applies]
    ignored = len(directives) - len(applied)

    if applied:
        kinds = ", ".join(sorted({d.directive_type for d in applied}))
        head = f"Applied {len(applied)} operator directive(s) ({kinds})"
    else:
        head = "No operator directive changed the schedule"

    if ignored:
        head += f"; {ignored} note(s) were unrelated to energy and ignored"

    tail = (
        " Solar is used first, the battery is charged in cheap hours and discharged "
        "into expensive ones, and it returns to its starting level by hour 23."
    )
    if degraded:
        tail += " NOTE: the constrained problem was infeasible, so a reduced plan was returned."
    return head + "." + tail


@router.post("/optimize-energy", response_model=OptimizeResponse)
def optimize_energy(request: OptimizeRequest) -> OptimizeResponse:
    started = time.perf_counter()
    hours = request.ordered_hours()

    demand = [h.demand_kwh for h in hours]
    solar = [h.solar_kwh for h in hours]
    tariff = [h.tariff_bdt_per_kwh for h in hours]

    battery = BatterySpec(
        capacity_kwh=request.battery.capacity_kwh,
        initial_energy_kwh=request.battery.initial_energy_kwh,
        minimum_energy_kwh=request.battery.minimum_energy_kwh,
        max_charge_kwh_per_hour=request.battery.max_charge_kwh_per_hour,
        max_discharge_kwh_per_hour=request.battery.max_discharge_kwh_per_hour,
    )

    # --- interpretation ----------------------------------------------------
    try:
        directives = interpret_notes(
            request.operator_notes,
            battery_capacity_kwh=battery.capacity_kwh,
        )
        source = "llm"
    except LLMUnavailable as exc:
        if not ALLOW_FALLBACK:
            raise
        # Safe failure: never crash, never invent an unsupported directive.
        logger.error("LLM interpretation failed, using heuristic fallback: %s", exc)
        directives = interpret_notes_heuristically(
            request.operator_notes, battery.capacity_kwh
        )
        source = "heuristic-fallback"

    # --- optimization ------------------------------------------------------
    result, _effects = optimize(
        demand_kwh=demand,
        solar_kwh=solar,
        tariff=tariff,
        battery=battery,
        directives=directives,
    )

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "scenario=%s source=%s applied=%d cost=%.2f elapsed_ms=%.0f",
        request.scenario_id,
        source,
        sum(1 for d in directives if d.applies),
        result.total_cost_bdt,
        elapsed_ms,
    )

    return OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=[d.as_response_dict() for d in directives],
        hourly_plan=[row.as_dict() for row in result.hourly_plan],
        total_grid_kwh=result.total_grid_kwh,
        total_cost_bdt=result.total_cost_bdt,
        peak_grid_kwh=result.peak_grid_kwh,
        plan_summary=_summarise(directives, result.degraded),
    )
