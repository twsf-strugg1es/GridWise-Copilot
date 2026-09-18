"""Guardrail tests.

This layer is the only thing between an untrusted model and the optimizer, so
each test pins a rule that would otherwise become a wrong schedule.
"""

import pytest

from backend.validator.guardrails import GuardrailError, validate_interpretation


def _one(**overrides):
    item = {
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
        "explanation": "x",
    }
    item.update(overrides)
    return [item]


def test_accepts_a_well_formed_directive():
    directives = validate_interpretation(_one(), note_count=1, battery_capacity_kwh=500)
    assert directives[0].directive_type == "solar_reduction"
    assert directives[0].structured_adjustment == {"hours": [13, 14], "factor": 0.2}


def test_hours_are_sorted_and_deduplicated():
    # Normalising is safe here: order and repetition carry no meaning.
    directives = validate_interpretation(
        _one(structured_adjustment={"hours": [14, 13, 13], "factor": 0.5}),
        note_count=1,
        battery_capacity_kwh=500,
    )
    assert directives[0].structured_adjustment["hours"] == [13, 14]


def test_string_hours_are_coerced():
    directives = validate_interpretation(
        _one(structured_adjustment={"hours": ["13", 14.0], "factor": 0.5}),
        note_count=1,
        battery_capacity_kwh=500,
    )
    assert directives[0].structured_adjustment["hours"] == [13, 14]


@pytest.mark.parametrize("bad", [-1, 24, 99, 13.5])
def test_out_of_range_hours_are_refused(bad):
    with pytest.raises(GuardrailError):
        validate_interpretation(
            _one(structured_adjustment={"hours": [bad], "factor": 0.5}),
            note_count=1,
            battery_capacity_kwh=500,
        )


@pytest.mark.parametrize("factor", [-0.1, 1.1, "abc", None, float("nan")])
def test_factor_must_be_a_fraction(factor):
    with pytest.raises(GuardrailError):
        validate_interpretation(
            _one(structured_adjustment={"hours": [13], "factor": factor}),
            note_count=1,
            battery_capacity_kwh=500,
        )


def test_unsupported_directive_type_is_refused():
    with pytest.raises(GuardrailError):
        validate_interpretation(
            _one(directive_type="shed_load"), note_count=1, battery_capacity_kwh=500
        )


def test_no_op_is_normalised_to_false_and_null():
    directives = validate_interpretation(
        _one(directive_type="no_op", applies=True, structured_adjustment={"hours": [1]}),
        note_count=1,
        battery_capacity_kwh=500,
    )
    assert directives[0].applies is False
    assert directives[0].structured_adjustment is None


def test_reserve_above_capacity_is_refused():
    with pytest.raises(GuardrailError):
        validate_interpretation(
            _one(
                directive_type="minimum_battery_reserve",
                structured_adjustment={"hours": [18], "minimum_energy_kwh": 900},
            ),
            note_count=1,
            battery_capacity_kwh=500,
        )


def test_entry_count_must_match_note_count():
    with pytest.raises(GuardrailError):
        validate_interpretation(_one(), note_count=2, battery_capacity_kwh=500)


def test_duplicate_note_index_is_refused():
    items = _one() + _one()
    with pytest.raises(GuardrailError):
        validate_interpretation(items, note_count=2, battery_capacity_kwh=500)


def test_entries_come_back_in_note_index_order():
    items = [
        {
            "note_index": 1,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "",
        },
        _one()[0],
    ]
    directives = validate_interpretation(items, note_count=2, battery_capacity_kwh=500)
    assert [d.note_index for d in directives] == [0, 1]


def test_windowed_directive_needs_at_least_one_hour():
    with pytest.raises(GuardrailError):
        validate_interpretation(
            _one(directive_type="no_charge_window", structured_adjustment={"hours": []}),
            note_count=1,
            battery_capacity_kwh=500,
        )


def test_extra_keys_on_a_window_directive_are_dropped():
    directives = validate_interpretation(
        _one(
            directive_type="no_discharge_window",
            structured_adjustment={"hours": [3], "factor": 0.5, "nonsense": True},
        ),
        note_count=1,
        battery_capacity_kwh=500,
    )
    assert directives[0].structured_adjustment == {"hours": [3]}
