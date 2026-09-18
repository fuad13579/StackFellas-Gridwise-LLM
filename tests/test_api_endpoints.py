"""API endpoint integration tests using FastAPI TestClient."""

import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_optimize_energy_malformed_request():
    response = client.post("/optimize-energy", json={"invalid": "payload"})
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "invalid_request"


def test_optimize_energy_whitespace_note_returns_json_safe_400():
    payload = {
        "scenario_id": "MALFORMED-01",
        "operator_notes": ["   "],
        "hours": [
            {"hour": h, "demand_kwh": 100.0, "solar_kwh": 10.0, "tariff_bdt_per_kwh": 5.0}
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 200.0,
            "initial_energy_kwh": 100.0,
            "minimum_energy_kwh": 20.0,
            "max_charge_kwh_per_hour": 50.0,
            "max_discharge_kwh_per_hour": 50.0,
        },
    }

    response = TestClient(app, raise_server_exceptions=False).post(
        "/optimize-energy", json=payload
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "invalid_request"
    assert data["error"]["details"][0]["type"] == "value_error"


@patch("app.main.LLMInterpreter")
def test_optimize_energy_success(mock_interpreter_cls):
    mock_instance = MagicMock()
    mock_instance.interpret.return_value = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "no_charge_window",
                    "structured_adjustment": {"hours": [14, 15]},
                    "explanation": "No charging test.",
                }
            ]
        }
    )
    mock_interpreter_cls.return_value = mock_instance

    payload = {
        "scenario_id": "API-TEST",
        "operator_notes": ["Do not charge between 2 PM and 4 PM."],
        "hours": [
            {"hour": h, "demand_kwh": 100.0, "solar_kwh": 20.0, "tariff_bdt_per_kwh": 5.0}
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 200.0,
            "initial_energy_kwh": 100.0,
            "minimum_energy_kwh": 30.0,
            "max_charge_kwh_per_hour": 50.0,
            "max_discharge_kwh_per_hour": 50.0,
        },
    }

    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["scenario_id"] == "API-TEST"
    assert len(data["hourly_plan"]) == 24
    assert "total_cost_bdt" in data
