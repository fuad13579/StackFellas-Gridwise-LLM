"""API endpoint integration tests using FastAPI TestClient."""

import json
from unittest.mock import MagicMock, patch

import pytest
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


def test_optimize_energy_raw_invalid_json_syntax_returns_400():
    response = TestClient(app, raise_server_exceptions=False).post(
        "/optimize-energy",
        content=b"{invalid: json syntax",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "invalid_request"


def test_optimize_energy_empty_body_returns_400():
    response = client.post("/optimize-energy", json={})
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("missing_field", ["scenario_id", "operator_notes", "hours", "battery"])
def test_optimize_energy_missing_required_field_returns_400(missing_field):
    payload = {
        "scenario_id": "API-TEST",
        "operator_notes": ["Note 1"],
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
    del payload[missing_field]
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "invalid_request"


def test_optimize_energy_extra_field_returns_400():
    payload = {
        "scenario_id": "API-TEST",
        "operator_notes": ["Note 1"],
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
        "extra_field": "disallowed",
    }
    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "invalid_request"


@patch("app.main.LLMInterpreter")
def test_optimize_energy_llm_not_configured_returns_503(mock_interpreter_cls):
    from app.errors import AppError
    mock_instance = MagicMock()
    mock_instance.interpret.side_effect = AppError(
        "llm_not_configured", "Missing configuration", 503
    )
    mock_interpreter_cls.return_value = mock_instance

    payload = {
        "scenario_id": "API-TEST",
        "operator_notes": ["Note"],
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
    assert response.status_code == 503
    data = response.json()
    assert data["error"]["code"] == "llm_not_configured"


@patch("app.main.LLMInterpreter")
def test_optimize_energy_llm_unavailable_returns_502(mock_interpreter_cls):
    from app.errors import AppError
    mock_instance = MagicMock()
    mock_instance.interpret.side_effect = AppError(
        "llm_unavailable", "The LLM provider request failed.", 502
    )
    mock_interpreter_cls.return_value = mock_instance

    payload = {
        "scenario_id": "API-TEST",
        "operator_notes": ["Note"],
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
    assert response.status_code == 502
    data = response.json()
    assert data["error"]["code"] == "llm_unavailable"


@patch("app.main.LLMInterpreter")
def test_optimize_energy_invalid_llm_output_returns_502(mock_interpreter_cls):
    mock_instance = MagicMock()
    mock_instance.interpret.return_value = "invalid json from model"
    mock_interpreter_cls.return_value = mock_instance

    payload = {
        "scenario_id": "API-TEST",
        "operator_notes": ["Note"],
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
    assert response.status_code == 502
    data = response.json()
    assert data["error"]["code"] == "invalid_llm_output"


@patch("app.main.LLMInterpreter")
def test_optimize_energy_infeasible_problem_returns_409(mock_interpreter_cls):
    # Operator note caps grid at 0, while solar is 0 and battery cannot discharge
    mock_instance = MagicMock()
    mock_instance.interpret.return_value = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": True,
                    "directive_type": "max_grid_window",
                    "structured_adjustment": {"hours": [0], "max_grid_kwh": 0.0},
                    "explanation": "No grid import at hour 0.",
                }
            ]
        }
    )
    mock_interpreter_cls.return_value = mock_instance

    payload = {
        "scenario_id": "API-INFEASIBLE",
        "operator_notes": ["Zero grid import at hour 0."],
        "hours": [
            {"hour": h, "demand_kwh": 100.0, "solar_kwh": 0.0, "tariff_bdt_per_kwh": 5.0}
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 200.0,
            "initial_energy_kwh": 0.0,
            "minimum_energy_kwh": 0.0,
            "max_charge_kwh_per_hour": 0.0,
            "max_discharge_kwh_per_hour": 0.0,
        },
    }

    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert data["error"]["code"] == "infeasible"


@patch("app.main.validate_solution")
@patch("app.main.LLMInterpreter")
def test_optimize_energy_replay_validator_failure_returns_500(mock_interpreter_cls, mock_validate_sol):
    from app.errors import AppError
    mock_instance = MagicMock()
    mock_instance.interpret.return_value = json.dumps(
        {
            "directive_interpretation": [
                {
                    "note_index": 0,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "No-op.",
                }
            ]
        }
    )
    mock_interpreter_cls.return_value = mock_instance
    mock_validate_sol.side_effect = AppError("invalid_solution", "Energy balance mismatch.", 500)

    payload = {
        "scenario_id": "API-VALIDATION-FAIL",
        "operator_notes": ["Note"],
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
    assert response.status_code == 500
    data = response.json()
    assert data["error"]["code"] == "invalid_solution"

