"""Contract tests for paraphrased operator-note interpretations."""

import json

import pytest

from app.directives.validator import validate_directives
from app.schemas import BatteryInput, HourInput, OptimizeRequest


def make_request(notes: list[str]) -> OptimizeRequest:
    return OptimizeRequest(
        scenario_id="PARAPHRASE-01",
        operator_notes=notes,
        hours=[
            HourInput(hour=h, demand_kwh=100.0, solar_kwh=50.0, tariff_bdt_per_kwh=5.0)
            for h in range(24)
        ],
        battery=BatteryInput(
            capacity_kwh=200.0,
            initial_energy_kwh=100.0,
            minimum_energy_kwh=20.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0,
        ),
    )


CASES = [
    (
        "solar at noon",
        ["Solar generation will be limited to 25% from noon until 2 PM."],
        [{"directive_type": "solar_reduction", "hours": [12, 13], "factor": 0.25}],
    ),
    (
        "solar percentage reduction",
        ["An 80% solar reduction applies between 1 PM and 3 PM."],
        [{"directive_type": "solar_reduction", "hours": [13, 14], "factor": 0.2}],
    ),
    (
        "solar usable fraction",
        ["Only half of the forecast solar can be used during hours 8 AM to 10 AM."],
        [{"directive_type": "solar_reduction", "hours": [8, 9], "factor": 0.5}],
    ),
    (
        "solar afternoon",
        ["Treat solar availability as 30 percent of forecast from 2 PM through 5 PM."],
        [{"directive_type": "solar_reduction", "hours": [14, 15, 16], "factor": 0.3}],
    ),
    (
        "solar overnight wording",
        ["Panel output is capped at 70% for the 6 PM to 8 PM window."],
        [{"directive_type": "solar_reduction", "hours": [18, 19], "factor": 0.7}],
    ),
    (
        "reserve explicit",
        ["Keep at least 120 kWh stored from 6 PM until 9 PM."],
        [{"directive_type": "minimum_battery_reserve", "hours": [18, 19, 20], "minimum_energy_kwh": 120.0}],
    ),
    (
        "reserve percentage",
        ["The battery must retain 50% of its 200 kWh capacity between 7 PM and 10 PM."],
        [{"directive_type": "minimum_battery_reserve", "hours": [19, 20, 21], "minimum_energy_kwh": 100.0}],
    ),
    (
        "reserve evening peak",
        ["Do not let stored energy fall below 150 kWh during the evening peak."],
        [{"directive_type": "minimum_battery_reserve", "hours": [17, 18, 19, 20, 21], "minimum_energy_kwh": 150.0}],
    ),
    (
        "reserve overnight",
        ["Maintain a 60 kWh battery reserve from midnight through 3 AM."],
        [{"directive_type": "minimum_battery_reserve", "hours": [0, 1, 2], "minimum_energy_kwh": 60.0}],
    ),
    (
        "charge prohibition",
        ["Battery charging is forbidden from 2 PM to 4 PM."],
        [{"directive_type": "no_charge_window", "hours": [14, 15]}],
    ),
    (
        "charge pause",
        ["Pause charging during the noon-to-1 PM interval."],
        [{"directive_type": "no_charge_window", "hours": [12]}],
    ),
    (
        "charge restriction morning",
        ["Do not store additional energy between 8 AM and 10 AM."],
        [{"directive_type": "no_charge_window", "hours": [8, 9]}],
    ),
    (
        "discharge prohibition",
        ["Battery discharge must be disabled from 6 PM until 9 PM."],
        [{"directive_type": "no_discharge_window", "hours": [18, 19, 20]}],
    ),
    (
        "discharge pause",
        ["Hold the battery steady between 10 AM and noon; do not discharge it."],
        [{"directive_type": "no_discharge_window", "hours": [10, 11]}],
    ),
    (
        "discharge restriction night",
        ["The battery may not supply load from 9 PM to midnight."],
        [{"directive_type": "no_discharge_window", "hours": [21, 22, 23]}],
    ),
    (
        "grid cap explicit",
        ["Grid imports must stay at or below 50 kWh from 6 PM to 8 PM."],
        [{"directive_type": "max_grid_window", "hours": [18, 19], "max_grid_kwh": 50.0}],
    ),
    (
        "grid ceiling",
        ["Limit utility draw to 75 kWh during the 1 PM through 4 PM period."],
        [{"directive_type": "max_grid_window", "hours": [13, 14, 15], "max_grid_kwh": 75.0}],
    ),
    (
        "grid import limit",
        ["The campus connection can provide no more than 100 kWh between 8 AM and 10 AM."],
        [{"directive_type": "max_grid_window", "hours": [8, 9], "max_grid_kwh": 100.0}],
    ),
    (
        "grid peak cap",
        ["Keep the evening peak grid purchase under 40 kWh from 7 PM until 9 PM."],
        [{"directive_type": "max_grid_window", "hours": [19, 20], "max_grid_kwh": 40.0}],
    ),
    (
        "irrelevant menu note",
        ["The cafeteria menu changes tomorrow."],
        [{"directive_type": "no_op"}],
    ),
    (
        "irrelevant registration note",
        ["The sports office moved the registration deadline."],
        [{"directive_type": "no_op"}],
    ),
    (
        "irrelevant weather note",
        ["A campus event has been moved to next week."],
        [{"directive_type": "no_op"}],
    ),
    (
        "two directives ordered",
        [
            "Solar output is reduced to 40% from 1 PM to 3 PM.",
            "Keep 90 kWh in reserve from 7 PM to 9 PM.",
        ],
        [
            {"directive_type": "solar_reduction", "hours": [13, 14], "factor": 0.4},
            {"directive_type": "minimum_battery_reserve", "hours": [19, 20], "minimum_energy_kwh": 90.0},
        ],
    ),
    (
        "directive plus distractor",
        [
            "Do not charge the battery between 2 PM and 4 PM.",
            "The library will close early on Friday.",
        ],
        [
            {"directive_type": "no_charge_window", "hours": [14, 15]},
            {"directive_type": "no_op"},
        ],
    ),
]


def expected_entry(index: int, expected: dict) -> dict:
    directive_type = expected["directive_type"]
    if directive_type == "no_op":
        return {
            "note_index": index,
            "applies": False,
            "directive_type": directive_type,
            "structured_adjustment": None,
            "explanation": "The note is unrelated to energy operations.",
        }

    adjustment = {key: value for key, value in expected.items() if key != "directive_type"}
    return {
        "note_index": index,
        "applies": True,
        "directive_type": directive_type,
        "structured_adjustment": adjustment,
        "explanation": "The note changes the energy schedule.",
    }


@pytest.mark.parametrize("case_id, notes, expected", CASES, ids=[case[0] for case in CASES])
def test_paraphrased_notes_match_structured_contract(case_id, notes, expected):
    request = make_request(notes)
    raw_output = json.dumps(
        {"directive_interpretation": [expected_entry(index, item) for index, item in enumerate(expected)]}
    )

    interpretations = validate_directives(raw_output, request)

    assert len(interpretations) == len(notes), case_id
    assert [item.note_index for item in interpretations] == list(range(len(notes)))
    assert [item.directive_type.value for item in interpretations] == [
        item["directive_type"] for item in expected
    ]