"""Regression coverage for canonical operator-note clock ranges."""

import json

import pytest

from app.directives.time_windows import clock_token_to_hour, explicit_time_window_hours
from app.directives.validator import validate_directives
from app.config import Settings
from app.directives.normalizer import normalize_directives
from app.optimizer.solver import solve_optimization
from app.optimizer.validator import validate_solution
from app.schemas import BatteryInput, HourInput, OptimizeRequest


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("Keep reserve from 6 PM until 10 PM.", [18, 19, 20, 21]),
        ("No charging from 2 PM until 5 PM.", [14, 15, 16]),
        ("Limit the feeder between 7 PM and 9 PM.", [19, 20]),
        ("Solar work from noon until 2 PM.", [12, 13]),
        ("No discharge from 13:00 to 15:00.", [13, 14]),
        ("Reserve the battery from 9 PM to midnight.", [21, 22, 23]),
        ("No charging from 10 PM to 2 AM.", [22, 23, 0, 1]),
    ],
)
def test_explicit_time_window_hours(note, expected):
    assert explicit_time_window_hours(note) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [("6 PM", 18), ("6PM", 18), ("12 PM", 12), ("12 AM", 0), ("noon", 12), ("midnight", 0), ("18:00", 18), ("2:30 PM", 14)],
)
def test_clock_token_to_hour(token, expected):
    assert clock_token_to_hour(token) == expected


def test_vague_time_does_not_get_invented():
    assert explicit_time_window_hours("Keep a reserve later tonight.") is None


def test_validator_replaces_bad_llm_hours_with_original_note_window():
    request = OptimizeRequest(
        scenario_id="REGRESSION",
        operator_notes=[
            "Keep at least 90 kWh in the battery from 6 PM until 10 PM for emergency services."
        ],
        hours=[HourInput(hour=h, demand_kwh=100, solar_kwh=0, tariff_bdt_per_kwh=5) for h in range(24)],
        battery=BatteryInput(
            capacity_kwh=250,
            initial_energy_kwh=150,
            minimum_energy_kwh=40,
            max_charge_kwh_per_hour=60,
            max_discharge_kwh_per_hour=60,
        ),
    )
    raw = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "minimum_battery_reserve",
                    "structured_adjustment": {
                        "hours": [18, 19, 20],
                        "minimum_energy_kwh": 90,
                    },
                    "explanation": "Emergency reserve.",
                }
            ]
        }
    )

    result = validate_directives(raw, request)

    assert result[0].structured_adjustment.hours == [18, 19, 20, 21]
    assert result[0].structured_adjustment.minimum_energy_kwh == 90

    response = solve_optimization(
        request,
        normalize_directives(request, result),
        Settings(),
        result,
    )
    validate_solution(request, normalize_directives(request, result), response)


def test_sample_07_bad_llm_window_becomes_valid_official_cost():
    import pathlib

    case_file = pathlib.Path(__file__).resolve().parents[1] / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
    case = next(case for case in json.loads(case_file.read_text(encoding="utf-8"))["cases"] if case["id"] == "SAMPLE-07")
    request = OptimizeRequest.model_validate(case["input"])
    bad_output = case["expected_output"]["directive_interpretation"]
    bad_output[0] = {
        **bad_output[0],
        "structured_adjustment": {"hours": [18, 19, 20], "minimum_energy_kwh": 90},
    }
    directives = validate_directives(json.dumps({"directive_interpretation": bad_output}), request)
    constraints = normalize_directives(request, directives)
    response = solve_optimization(request, constraints, Settings(), directives)

    validate_solution(request, constraints, response)
    assert directives[0].structured_adjustment.hours == [18, 19, 20, 21]
    assert response.total_cost_bdt == 38550.0
