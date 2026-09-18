# Official GridWise SmartGrid AI Backend API Contract

This document describes the canonical REST API contract for the StackFellas SmartGrid AI backend (BUP CSE Fest 2026 Preliminary Round).

## Endpoints

- `GET /health`: HTTP 200 `{"status": "ok"}`
- `POST /optimize-energy`: Accepts 24-hour scenario + operator notes; returns note interpretation + 24-hour optimized schedule.

## `POST /optimize-energy` Request

```json
{
  "scenario_id": "GRID-101",
  "operator_notes": [
    "Solar output will drop to about 20% from 1 PM to 3 PM.",
    "Do not charge the battery between 2 PM and 4 PM.",
    "The cafeteria menu changes tomorrow."
  ],
  "hours": [
    {
      "hour": 0,
      "demand_kwh": 180,
      "solar_kwh": 0,
      "tariff_bdt_per_kwh": 7
    },
    ...
    {
      "hour": 23,
      "demand_kwh": 200,
      "solar_kwh": 0,
      "tariff_bdt_per_kwh": 9
    }
  ],
  "battery": {
    "capacity_kwh": 500,
    "initial_energy_kwh": 200,
    "minimum_energy_kwh": 50,
    "max_charge_kwh_per_hour": 100,
    "max_discharge_kwh_per_hour": 100
  }
}
```

### Validation Rules
- `scenario_id`: String identifier.
- `operator_notes`: Array of 1–3 non-empty natural-language strings.
- `hours`: Array of exactly 24 unique entries for hours 0 through 23 in ascending order.
  - `demand_kwh`: Non-negative number.
  - `solar_kwh`: Non-negative number.
  - `tariff_bdt_per_kwh`: Non-negative number.
- `battery`: Object specifying battery parameters.
  - `capacity_kwh`: Positive number.
  - `initial_energy_kwh`: Non-negative number $\le$ `capacity_kwh`.
  - `minimum_energy_kwh`: Non-negative number $\le$ `initial_energy_kwh`.
  - `max_charge_kwh_per_hour`: Non-negative number.
  - `max_discharge_kwh_per_hour`: Non-negative number.

## `POST /optimize-energy` Successful Response (HTTP 200)

```json
{
  "scenario_id": "GRID-101",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {
        "hours": [13, 14],
        "factor": 0.2
      },
      "explanation": "Solar availability is reduced during panel cleaning."
    },
    {
      "note_index": 1,
      "applies": true,
      "directive_type": "no_charge_window",
      "structured_adjustment": {
        "hours": [14, 15]
      },
      "explanation": "Battery charging is disabled."
    },
    {
      "note_index": 2,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "This note does not affect today's energy schedule."
    }
  ],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 180,
      "solar_used_kwh": 0,
      "battery_action": "idle",
      "battery_kwh": 0,
      "battery_energy_after_kwh": 200
    },
    ...
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 185.0,
  "plan_summary": "Optimized schedule applying solar reduction and charging restriction."
}
```

### Supported Directive Types & Adjustment Shapes
1. `solar_reduction`: `{"hours": [integers 0..23], "factor": number in [0, 1]}`
2. `minimum_battery_reserve`: `{"hours": [integers 0..23], "minimum_energy_kwh": number}`
3. `no_charge_window`: `{"hours": [integers 0..23]}`
4. `no_discharge_window`: `{"hours": [integers 0..23]}`
5. `max_grid_window`: `{"hours": [integers 0..23], "max_grid_kwh": number}`
6. `no_op`: `null` (Must use `applies: false`).

## Error Responses

Errors return a JSON object with error code, message, and optional details.

| HTTP Code | Error Code | Description |
| --- | --- | --- |
| 400 | `invalid_request` | Malformed JSON or structurally invalid request. |
| 422 | `invalid_directives` / `unsupported_notes` | Semantically invalid request or directives. |
| 500 | `invalid_solution` / `internal_error` | Independent solution check failure or internal error. |
| 502 | `llm_unavailable` / `invalid_llm_output` | Provider network failure or unparseable completion. |
| 503 | `llm_not_configured` / `optimization_failed` | Missing configuration or LP solver failure. |
