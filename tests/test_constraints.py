from optimizer.model import create_model

from optimizer.constraints import (
    create_variables,
    add_energy_balance_constraints,
    add_battery_constraints
)


hours = range(24)


model = create_model()


variables = create_variables(
    model,
    hours
)


demand = {
    h: 100
    for h in hours
}


solar = {
    h: 50
    for h in hours
}


battery_config = {
    "capacity": 200,
    "initial": 100,
    "max_charge": 50,
    "max_discharge": 50
}


add_energy_balance_constraints(
    model,
    variables,
    demand,
    solar,
    hours
)


add_battery_constraints(
    model,
    variables,
    battery_config,
    hours
)


print("Constraints added")
print("Number of constraints:", len(model.constraints))