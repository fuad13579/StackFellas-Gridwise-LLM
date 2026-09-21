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
    assert excinfo.value.status_code == 500


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
    assert excinfo.value.status_code == 500


def test_invalid_llm_output_does_not_echo_raw_content():
    req = make_sample_request()
    raw = '{"directive_interpretation": [{"synthetic_secret":"must-not-echo"}]}'
    with pytest.raises(AppError) as excinfo:
        validate_directives(raw, req)
    assert "must-not-echo" not in excinfo.value.message
    assert excinfo.value.status_code == 500
