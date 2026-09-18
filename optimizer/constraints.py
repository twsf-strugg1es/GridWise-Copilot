from pulp import LpVariable


def create_variables(model, hours):

    variables = {}

    variables["grid"] = {
        h: LpVariable(
            f"grid_{h}",
            lowBound=0
        )
        for h in hours
    }


    variables["solar_used"] = {
        h: LpVariable(
            f"solar_used_{h}",
            lowBound=0
        )
        for h in hours
    }


    variables["charge"] = {
        h: LpVariable(
            f"charge_{h}",
            lowBound=0
        )
        for h in hours
    }


    variables["discharge"] = {
        h: LpVariable(
            f"discharge_{h}",
            lowBound=0
        )
        for h in hours
    }


    variables["battery"] = {
        h: LpVariable(
            f"battery_{h}",
            lowBound=0
        )
        for h in hours
    }


    return variables



def add_energy_balance_constraints(
        model,
        variables,
        demand,
        solar,
        hours
):

    for h in hours:

        # Energy balance
        model += (
            variables["solar_used"][h]
            +
            variables["grid"][h]
            +
            variables["discharge"][h]
            -
            variables["charge"][h]
            ==
            demand[h]
        )


        # Solar generation limit
        model += (
            variables["solar_used"][h]
            <=
            solar[h]
        )



def add_battery_constraints(
        model,
        variables,
        battery_config,
        hours
):

    capacity = battery_config["capacity"]
    initial = battery_config["initial"]
    max_charge = battery_config["max_charge"]
    max_discharge = battery_config["max_discharge"]


    for h in hours:

        # Charging limit
        model += (
            variables["charge"][h]
            <= max_charge
        )


        # Discharging limit
        model += (
            variables["discharge"][h]
            <= max_discharge
        )


        # Battery capacity
        model += (
            variables["battery"][h]
            <= capacity
        )


    # Battery state transition

    for h in hours:

        if h == 0:

            model += (
                variables["battery"][h]
                ==
                initial
                +
                variables["charge"][h]
                -
                variables["discharge"][h]
            )

        else:

            model += (
                variables["battery"][h]
                ==
                variables["battery"][h-1]
                +
                variables["charge"][h]
                -
                variables["discharge"][h]
            )
def add_directive_constraints(
        model,
        variables,
        directives
):

    for directive in directives:

        directive_type = directive.get(
            "directive_type"
        )

        adjustment = directive.get(
            "structured_adjustment",
            {}
        )


        if directive_type == "no_charge_window":

            hours = adjustment.get(
                "hours",
                []
            )

            for h in hours:
                model += (
                    variables["charge"][h] == 0
                )


        elif directive_type == "no_discharge_window":

            hours = adjustment.get(
                "hours",
                []
            )

            for h in hours:
                model += (
                    variables["discharge"][h] == 0
                )