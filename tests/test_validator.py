"""Unit tests for deterministic LLM output directive validator."""

import json
import pytest

from app.directives.validator import validate_directives
from app.errors import AppError
from app.schemas import BatteryInput, HourInput, OptimizeRequest


def make_sample_request():
    hours = [
        HourInput(hour=h, demand_kwh=100.0, solar_kwh=50.0, tariff_bdt_per_kwh=5.0)
        for h in range(24)
    ]
    battery = BatteryInput(
        capacity_kwh=200.0,
        initial_energy_kwh=100.0,
        minimum_energy_kwh=30.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )
    return OptimizeRequest(
        scenario_id="S-01",
        operator_notes=["Note 1", "Note 2"],
        hours=hours,
        battery=battery,
    )


def test_valid_llm_output():
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": {"hours": [14, 15]},
                    "explanation": "No charging from 2 to 4 PM.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Irrelevant note.",
                },
            ]
        }
    )
    result = validate_directives(raw, req)
    assert len(result) == 2
    assert result[0].applies is True
    assert result[1].applies is False


def test_invalid_applies_for_no_op():
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Invalid no_op applies=true.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Irrelevant note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert excinfo.value.code == "invalid_llm_output"


def test_unsorted_hours():
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": {"hours": [15, 14]},
                    "explanation": "Unsorted hours.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Irrelevant note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert excinfo.value.code == "invalid_llm_output"


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"directive_interpretation": []}',
        '{"directive_interpretation": [{"note_index": 0, "applies": false, "directive_type": "no_op", "structured_adjustment": null, "explanation": "ok", "extra": true}, {"note_index": 1, "applies": false, "directive_type": "no_op", "structured_adjustment": null, "explanation": "ok"}]}',
        '{"directive_interpretation": [{"note_index": 0, "applies": false, "directive_type": "no_op", "structured_adjustment": null, "explanation": "ok"}, {"note_index": 0, "applies": false, "directive_type": "no_op", "structured_adjustment": null, "explanation": "ok"}]}',
        '{"directive_interpretation": [{"note_index": 0, "applies": false, "directive_type": "no_op", "structured_adjustment": null, "explanation": "ok"}, {"note_index": 1, "applies": false, "directive_type": "no_op", "structured_adjustment": null, "explanation": "ok"}], "directive_interpretation": []}',
        '{"directive_interpretation": [{"note_index": 0, "applies": true, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [0], "factor": NaN}, "explanation": "bad"}, {"note_index": 1, "applies": false, "directive_type": "no_op", "structured_adjustment": null, "explanation": "ok"}]}',
    ],
)
def test_malformed_llm_output_is_rejected(raw):
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, make_sample_request())

    assert excinfo.value.code == "invalid_llm_output"


@pytest.mark.parametrize("hours", [[], [1, 1], [24], [-1]])
def test_invalid_directive_hours_are_rejected(hours):
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": {"hours": hours},
                    "explanation": "Invalid hours.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Irrelevant note.",
                },
            ]
        }
    )

    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)

    assert excinfo.value.code == "invalid_llm_output"


def test_count_mismatch_is_rejected():
    req = make_sample_request()  # has 2 operator notes
    # only 1 interpretation
    raw_1 = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Only one item.",
                }
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw_1, req)
    assert excinfo.value.code == "invalid_llm_output"

    # 3 interpretations
    raw_3 = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Item 0",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Item 1",
                },
                {
                    "note_index": 2,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Item 2 extra",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw_3, req)
    assert excinfo.value.code == "invalid_llm_output"


@pytest.mark.parametrize("indices", [[1, 0], [0, 2], [1, 2]])
def test_invalid_note_indices_order_rejected(indices):
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": indices[0],
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Item 0",
                },
                {
                    "note_index": indices[1],
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Item 1",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert excinfo.value.code == "invalid_llm_output"


def test_unknown_directive_type_rejected():
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "invalid_directive_action",
                    "structured_adjustment": {"hours": [1]},
                    "explanation": "Unknown directive type.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert excinfo.value.code == "invalid_llm_output"


def test_non_no_op_with_applies_false_or_null_adjustment_rejected():
    req = make_sample_request()
    # applies: False for no_charge_window
    raw_false = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": False,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": {"hours": [1]},
                    "explanation": "Invalid applies.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw_false, req)
    assert excinfo.value.code == "invalid_llm_output"

    # structured_adjustment: null for no_charge_window
    raw_null = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": None,
                    "explanation": "Invalid adjustment.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw_null, req)
    assert excinfo.value.code == "invalid_llm_output"


def test_no_op_with_non_null_adjustment_rejected():
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": {"hours": [1, 2]},
                    "explanation": "Invalid no_op adjustment.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert excinfo.value.code == "invalid_llm_output"


@pytest.mark.parametrize("bad_factor", [-0.1, 1.05, 2.0])
def test_solar_reduction_factor_out_of_bounds_rejected(bad_factor):
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "solar_reduction",
                    "structured_adjustment": {"hours": [10, 11], "factor": bad_factor},
                    "explanation": "Bad factor.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert excinfo.value.code == "invalid_llm_output"


@pytest.mark.parametrize("good_factor", [0.0, 0.5, 1.0])
def test_solar_reduction_boundary_factors_accepted(good_factor):
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "solar_reduction",
                    "structured_adjustment": {"hours": [10, 11], "factor": good_factor},
                    "explanation": f"Factor {good_factor}.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    result = validate_directives(raw, req)
    assert result[0].structured_adjustment.factor == good_factor


@pytest.mark.parametrize("bad_reserve", [-1.0, 201.0, 500.0])
def test_minimum_battery_reserve_out_of_bounds_rejected(bad_reserve):
    req = make_sample_request()  # capacity is 200.0
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "minimum_battery_reserve",
                    "structured_adjustment": {"hours": [10, 11], "minimum_energy_kwh": bad_reserve},
                    "explanation": "Bad reserve.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert excinfo.value.code == "invalid_llm_output"


@pytest.mark.parametrize("good_reserve", [0.0, 50.0, 200.0])
def test_minimum_battery_reserve_boundary_values_accepted(good_reserve):
    req = make_sample_request()  # capacity is 200.0
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "minimum_battery_reserve",
                    "structured_adjustment": {"hours": [10, 11], "minimum_energy_kwh": good_reserve},
                    "explanation": f"Reserve {good_reserve}.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    result = validate_directives(raw, req)
    assert result[0].structured_adjustment.minimum_energy_kwh == good_reserve


def test_max_grid_window_negative_rejected():
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "max_grid_window",
                    "structured_adjustment": {"hours": [10], "max_grid_kwh": -5.0},
                    "explanation": "Negative max grid.",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert excinfo.value.code == "invalid_llm_output"


def test_max_grid_window_zero_accepted():
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "max_grid_window",
                    "structured_adjustment": {"hours": [10], "max_grid_kwh": 0.0},
                    "explanation": "Zero max grid (island mode).",
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    result = validate_directives(raw, req)
    assert result[0].structured_adjustment.max_grid_kwh == 0.0


def test_oversized_output_rejected():
    req = make_sample_request()
    oversized = " " * 32_001
    with pytest.raises(AppError) as excinfo:
        validate_directives(oversized, req)
    assert excinfo.value.code == "invalid_llm_output"


def test_hoist_explanation_from_structured_adjustment():
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": {
                        "hours": [14, 15],
                        "explanation": "Hoisted explanation.",
                    },
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Regular explanation.",
                },
            ]
        }
    )
    result = validate_directives(raw, req)
    assert result[0].explanation == "Hoisted explanation."


@pytest.mark.parametrize("bad_explanation", ["", "   "])
def test_whitespace_explanation_rejected(bad_explanation):
    req = make_sample_request()
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": {"hours": [14, 15]},
                    "explanation": bad_explanation,
                },
                {
                    "note_index": 1,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Ok note.",
                },
            ]
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert excinfo.value.code == "invalid_llm_output"
