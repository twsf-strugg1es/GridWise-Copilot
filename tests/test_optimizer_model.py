from optimizer.model import create_model
from optimizer.constraints import create_variables


model = create_model()


hours = range(24)


variables = create_variables(
    model,
    hours
)


print("Model created")
print(
    variables.keys()
)