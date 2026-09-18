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


# 24 hour simulation
hours = range(24)


# Create optimization model
model = create_model()


# Create decision variables
variables = create_variables(
    model,
    hours
)


# Input data

demand = {
    h: 100
    for h in hours
}


solar = {
    h: 50
    for h in hours
}


tariff = {
    h: 10
    for h in hours
}


battery = {
    "capacity": 200,
    "initial": 100,
    "max_charge": 50,
    "max_discharge": 50
}


# Example directive from Gemini parser
# "Do not charge battery between 2 PM and 4 PM"

directives = [
    {
        "directive_type": "no_charge_window",
        "structured_adjustment": {
            "hours": [14, 15]
        }
    }
]


# Add energy constraints

add_energy_balance_constraints(
    model,
    variables,
    demand,
    solar,
    hours
)


# Add battery constraints

add_battery_constraints(
    model,
    variables,
    battery,
    hours
)


# Add LLM generated directives

add_directive_constraints(
    model,
    variables,
    directives
)


# Add cost minimization objective

add_cost_objective(
    model,
    variables,
    tariff,
    hours
)


# Solve

result = solve_model(
    model,
    variables,
    hours
)


print(result)