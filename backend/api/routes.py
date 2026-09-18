from fastapi import APIRouter
from backend.api.schemas import OptimizationRequest


router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "ok"
    }


@router.post("/optimize-energy")
def optimize_energy(request: OptimizationRequest):

    return {
        "scenario_id": request.scenario_id,
        "message": "API skeleton working",
        "directive_interpretation": [],
        "hourly_plan": [],
        "total_grid_kwh": 0,
        "total_cost_bdt": 0,
        "peak_grid_kwh": 0,
        "plan_summary": "Optimization engine not connected yet"
    }