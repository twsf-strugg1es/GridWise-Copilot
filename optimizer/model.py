from pulp import LpProblem, LpMinimize


def create_model():

    model = LpProblem(
        "GridWise_Energy_Optimization",
        LpMinimize
    )

    return model



def add_cost_objective(
        model,
        variables,
        tariff,
        hours
):

    total_cost = sum(
        variables["grid"][h] * tariff[h]
        for h in hours
    )

    model += total_cost