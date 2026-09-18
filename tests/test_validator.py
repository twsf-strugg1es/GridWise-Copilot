from backend.validator.guardrails import validate_directive


test_directive = {
    "directive_type": "no_charge_window",
    "structured_adjustment": {
        "hours": [14,15]
    }
}


result = validate_directive(
    test_directive
)


print(result)