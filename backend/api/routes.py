from fastapi import APIRouter

from backend.api.schemas import (
    OptimizeRequest,
    OptimizeResponse
)

from backend.llm.parser import parse_operator_note

from backend.validator.guardrails import (
    validate_directive
)

from optimizer.model import (
    create_model,
    add_cost_objective
)

from optimizer.constraints import (
    create_variables,
    add_energy_balance_constraints,
    add_battery_constraints,
    add_directive_constraints
)

from optimizer.solver import solve_model


router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok"}

@router.post(
    "/optimize-energy",
    response_model=OptimizeResponse
)
def optimize_energy(
        request: OptimizeRequest
):

    hours = range(24)


    # 1. Parse operator note

    directive = parse_operator_note(
        request.operator_note,
        0
    )


    # 2. Validate LLM output

    validation = validate_directive(
        directive
    )


    if not validation["valid"]:

        return {
            "status": "invalid directive",
            "total_cost_bdt": 0,
            "applied_directives": [],
            "battery_summary": {},
            "hourly_plan": []
        }


    # 3. Create optimizer model

    model = create_model()


    variables = create_variables(
        model,
        hours
    )


    # 4. Add energy constraints

    add_energy_balance_constraints(
        model,
        variables,
        request.demand,
        request.solar,
        hours
    )


    # 5. Add battery constraints

    add_battery_constraints(
        model,
        variables,
        request.battery.dict(),
        hours
    )


    # 6. Apply AI directives

    add_directive_constraints(
        model,
        variables,
        [directive]
    )


    # 7. Add optimization objective

    add_cost_objective(
        model,
        variables,
        request.tariff,
        hours
    )


    # 8. Solve optimization

    result = solve_model(
        model,
        variables,
        hours
    )


    # 9. Create battery summary

    battery_summary = {

        "initial_battery": request.battery.initial,

        "final_battery": (
            result["hourly_plan"][-1]["battery_kwh"]
        ),

        "total_discharge": sum(
            item["discharge_kwh"]
            for item in result["hourly_plan"]
        ),

        "total_charge": sum(
            item["charge_kwh"]
            for item in result["hourly_plan"]
        )
    }


    # 10. Return final response

    return {

        "status": result["status"],

        "total_cost_bdt": result["total_cost_bdt"],

        "applied_directives": [
            directive
        ],

        "battery_summary": battery_summary,

        "hourly_plan": result["hourly_plan"]
    }
