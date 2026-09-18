ALLOWED_DIRECTIVES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
}


def validate_directive(directive: dict):

    errors = []

    # Check required fields
    required = [
        "directive_type",
        "structured_adjustment"
    ]

    for field in required:
        if field not in directive:
            errors.append(
                f"Missing field: {field}"
            )


    # Validate directive type
    directive_type = directive.get(
        "directive_type"
    )

    if directive_type not in ALLOWED_DIRECTIVES:
        errors.append(
            f"Unsupported directive: {directive_type}"
        )


    adjustment = directive.get(
        "structured_adjustment",
        {}
    )


    # Validate hours
    if "hours" in adjustment:

        for hour in adjustment["hours"]:

            if hour < 0 or hour > 23:
                errors.append(
                    f"Invalid hour: {hour}"
                )


    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "directive": directive
    }