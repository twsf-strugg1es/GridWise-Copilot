from pulp import LpStatus, PULP_CBC_CMD


def solve_model(
        model,
        variables,
        hours
):

    # Solve silently (hide CBC logs)
    result = model.solve(
        PULP_CBC_CMD(msg=False)
    )


    hourly_plan = []


    for h in hours:

        hourly_plan.append(
            {
                "hour": h,

                "grid_kwh": round(
                    variables["grid"][h].value() or 0,
                    2
                ),

                "solar_kwh": round(
                    variables["solar_used"][h].value() or 0,
                    2
                ),

                "charge_kwh": round(
                    variables["charge"][h].value() or 0,
                    2
                ),

                "discharge_kwh": round(
                    variables["discharge"][h].value() or 0,
                    2
                ),

                "battery_kwh": max(
                    0,
                    round(
                        variables["battery"][h].value() or 0,
                        2
                    )
                )
            }
        )


    return {
        "status": LpStatus[result],

        "total_cost_bdt": round(
            model.objective.value() or 0,
            2
        ),

        "hourly_plan": hourly_plan
    }