# StackFellas SmartGrid AI Backend

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![SciPy](https://img.shields.io/badge/SciPy-linprog-orange.svg)](https://scipy.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Backend service for **StackFellas SmartGrid AI**, built for the **BUP CSE Fest 2026 Hackathon (Preliminary Round)**.

Live service: `https://stackfellas-gridwise-llm.onrender.com`

The service receives a 24-hour campus energy scenario (demand, solar forecast, grid tariff) alongside 1–3 natural-language campus operator notes. It uses an LLM to interpret operator directives into structured constraints, validates them deterministically, optimizes grid electricity costs using linear programming (`scipy.optimize.linprog`), and independently replays the schedule for validation before returning a 24-hour operating plan.

---

## System Architecture

```
                                  ┌───────────────────────────────┐
                                  │      POST /optimize-energy    │
                                  └──────────────┬────────────────┘
                                                 │
                                                 ▼
                                  ┌───────────────────────────────┐
                                  │   1. LLM Directive Interpreter│
                                  │ (OpenRouter/OpenAI-compatible)│
                                  └──────────────┬────────────────┘
                                                 │
                                                 ▼
                                  ┌───────────────────────────────┐
                                  │ 2. Deterministic Guardrails   │
                                  │    & Directive Validation     │
                                  └──────────────┬────────────────┘
                                                 │
                                                 ▼
                                  ┌───────────────────────────────┐
                                  │ 3. LP Cost Optimization       │
                                  │    (scipy.optimize.linprog)   │
                                  └──────────────┬────────────────┘
                                                 │
                                                 ▼
                                  ┌───────────────────────────────┐
                                  │ 4. Independent Solution Replay│
                                  │    Schedule Verification      │
                                  └──────────────┬────────────────┘
                                                 │
                                                 ▼
                                  ┌───────────────────────────────┐
                                  │        HTTP 200 Response      │
                                  └───────────────────────────────┘
```

---

## Features & Supported Directives

- **GET /health**: Instant process readiness check (`{"status": "ok"}`).
- **POST /optimize-energy**: Synchronous FastAPI route that runs the full interpretation and optimization pipeline within the 30-second deadline without blocking the event loop.
- **Strict request validation**: Invalid JSON and schema violations return JSON-safe HTTP 400 errors.
- **Bounded runtime**: The API uses a total 30-second request deadline shared by the LLM and optimizer stages.
- **Supported Operator Directives**:
  1. `solar_reduction`: Usable solar output reduction during specific hours. (`factor` = fraction remaining).
  2. `minimum_battery_reserve`: Elevated minimum battery energy reserve during specific hours.
  3. `no_charge_window`: Disables battery charging during specified hours.
  4. `no_discharge_window`: Disables battery discharging during specified hours.
  5. `max_grid_window`: Grid import cap during specified hours.
  6. `no_op`: Irrelevant notes marked with `applies=false` and `structured_adjustment=null`.
- **Battery State Tracking**: The optimizer enforces per-hour energy balance and cumulative battery bounds while respecting charge/discharge caps and reserve constraints.
- **Two-stage optimization**: Stage 1 minimizes grid electricity cost only; Stage 2 keeps that cost optimal while minimizing battery throughput.
- **Independent Solution Replay**: Every schedule is re-verified hour-by-hour prior to output emission to guarantee exact feasibility for the published constraints and directives.
- **Time-window canonicalization**: The LLM determines the semantic directive and values. When an original note includes an explicit clock range, deterministic code reconstructs the official `[start, end)` hour list, then returns sorted unique hour indices. Same-day examples: `6 PM to 10 PM` → `[18, 19, 20, 21]`, `2 PM to 5 PM` → `[14, 15, 16]`, `noon to 2 PM` → `[12, 13]`. Overnight windows wrap and are then sorted, so `10 PM to 2 AM` → `[0, 1, 22, 23]` and `9 PM to midnight` → `[21, 22, 23]`. SAMPLE-07 is covered by this path.

### Request Rules

- `operator_notes` contains 1-3 non-empty strings. Notes are stripped before validation; whitespace-only notes are rejected with HTTP 400.
- `hours` contains exactly one entry for every hour 0 through 23. Entries may arrive in any order and are normalized to ascending hour order before optimization.
- `battery.capacity_kwh` must be positive. Initial and minimum energy cannot exceed capacity.
- Directive hours use start-inclusive, end-exclusive windows. For example, 1 PM to 3 PM maps to `[13, 14]`.

---

## Prerequisites & Installation

- **Python**: 3.11 or higher
- **Dependencies**: Listed in `requirements.txt` (`fastapi`, `uvicorn`, `scipy`, `pydantic`, `httpx`, `pytest`).

### Setup Environment

```bash
# Clone repository
git clone https://github.com/fuad13579/StackFellas-Gridwise-LLM.git
cd StackFellas-Gridwise-LLM

# Create and activate virtual environment
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

---

## Environment Configuration

Create a `.env` file in the root directory (refer to `.env.example`):

```env
# LLM Provider Credentials (OpenAI-compatible API)
LLM_API_URL=https://openrouter.ai/api/v1/chat/completions
LLM_API_KEY=your-api-key-here
LLM_MODEL=openai/gpt-4o-mini

# Optional Performance Settings
LLM_TIMEOUT_SECONDS=30
SOLVER_TIME_LIMIT_SECONDS=10
# Total /optimize-energy request deadline (maximum 30 seconds)
REQUEST_TIMEOUT_SECONDS=30
LOG_LEVEL=INFO
```

`LLM_API_URL`, `LLM_API_KEY`, and `LLM_MODEL` are required for `/optimize-energy`. The service starts without them so `/health` and offline tests remain available, but optimization requests return HTTP 500 (`llm_not_configured`) until an LLM provider is configured. Never commit `.env` or real API keys.

---

## Running the API Locally

Start the server using Uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Health Check

```bash
curl http://localhost:8000/health
```
**Response:**
```json
{"status": "ok"}
```

### Sample Optimization Request

```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "SAMPLE-01",
    "operator_notes": [
      "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
      "The sports office moved next month registration deadline."
    ],
    "hours": [
      {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 2, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 3, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 4, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 5, "demand_kwh": 95, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 6, "demand_kwh": 110, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
      {"hour": 7, "demand_kwh": 130, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
      {"hour": 8, "demand_kwh": 150, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
      {"hour": 9, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
      {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
      {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
      {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
      {"hour": 14, "demand_kwh": 170, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
      {"hour": 15, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 16, "demand_kwh": 170, "solar_kwh": 45, "tariff_bdt_per_kwh": 18},
      {"hour": 17, "demand_kwh": 185, "solar_kwh": 10, "tariff_bdt_per_kwh": 22},
      {"hour": 18, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 28},
      {"hour": 19, "demand_kwh": 215, "solar_kwh": 0, "tariff_bdt_per_kwh": 30},
      {"hour": 20, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 26},
      {"hour": 21, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
      {"hour": 22, "demand_kwh": 135, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
      {"hour": 23, "demand_kwh": 105, "solar_kwh": 0, "tariff_bdt_per_kwh": 7}
    ],
    "battery": {
      "capacity_kwh": 220,
      "initial_energy_kwh": 110,
      "minimum_energy_kwh": 40,
      "max_charge_kwh_per_hour": 50,
      "max_discharge_kwh_per_hour": 50
    }
  }'
```

### Sample Response

The API returns the note interpretation plus the resulting hourly schedule and aggregate cost metrics.

```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {
        "hours": [12, 13],
        "factor": 0.25
      },
      "explanation": "Solar output is reduced during the cleaning window."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "This note is unrelated to the current 24-hour energy schedule."
    }
  ],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 90.0,
      "solar_used_kwh": 0.0,
      "battery_action": "idle",
      "battery_kwh": 0.0,
      "battery_energy_after_kwh": 110.0
    }
  ],
  "total_grid_kwh": 2450.5,
  "total_cost_bdt": 30164.25,
  "peak_grid_kwh": 185.0,
  "plan_summary": "Optimized 24-hour schedule applying 1 operator directive(s). Total grid import: 2450.5 kWh, cost: 30164.25 BDT, peak grid: 185.0 kWh."
}
```

---

## Testing

### Automated Offline Tests (Mocked LLM + All 10 Public Cases)

Run unit tests and verify optimization against ground-truth interpretations for all 10 public sample cases:

```bash
pytest -v
```

The suite includes the 10 official public optimization cases, directive validation, explicit same-day and overnight time-window regressions (including SAMPLE-07), API error-status contract checks, timeout behavior, overlapping solar reductions, and paraphrase contract cases. Current baseline: 87 passing tests.

### Live LLM Test Script

Run public sample cases against a live running API instance using real LLM API calls:

```bash
python scripts/test_live_llm.py --url http://localhost:8000
```

Useful options:

```bash
python scripts/test_live_llm.py \
  --url http://localhost:8000 \
  --case SAMPLE-01 \
  --request-timeout 35 \
  --health-timeout 10
```

The live runner checks each response against the public reference directive semantics, replays the entire hourly plan against those directives using the same independent validator as the API, recomputes totals, compares cost within `0.01` BDT, and exits non-zero on any failure. It requires a running API configured with OpenRouter and `openai/gpt-4o-mini`. SAMPLE-07 is included in the official public set and is validated the same way.

### Real-LLM Benchmarks

For 10 public cases with three real LLM runs per case:

```bash
python scripts/evaluate_30_runs.py
```

For a single run across the public cases with latency reporting:

```bash
python scripts/benchmark_latency.py
```

These scripts call the provider directly and require the same `.env` configuration. They may consume provider credits.

### Error Responses

The API returns a JSON object with an `error` object for controlled failures:

| Status | Code examples | Meaning |
| --- | --- | --- |
| 400 | `invalid_request` | Malformed JSON or invalid request schema, including whitespace-only notes. |
| 422 | `infeasible` | Semantically valid request, but no schedule satisfies the scenario and directive constraints. |
| 500 | `llm_unavailable`, `invalid_llm_output`, `llm_not_configured`, `request_timeout`, `invalid_solution`, `internal_error` | Provider failure, invalid LLM completion, missing LLM configuration, request timeout, replay-validation failure, or other controlled internal error. |

The LLM is used only for semantic interpretation of operator notes. Deterministic validation protects the optimizer from malformed provider output, and SciPy `linprog` produces the cost-minimizing schedule. API keys are supplied only through environment variables and are never committed or returned by the API.

---

## Docker Support & Fallback Deployment

### Build Container Image

```bash
docker build -t gridwise-llm .
```

### Run Container

```bash
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name gridwise-service \
  gridwise-llm
```

Verify status:
```bash
curl http://localhost:8000/health
```

---

## Project Structure

```
.
├── app/
│   ├── directives/
│   │   ├── time_windows.py # Deterministic [start, end) hour canonicalization
│   │   └── validator.py    # Deterministic LLM output guardrails
│   ├── llm/
│   │   ├── interpreter.py  # HTTP client for LLM completions
│   │   └── prompt.py       # LLM system prompt & JSON schema builder
│   ├── optimizer/
│   │   ├── solver.py       # SciPy linprog LP solver
│   │   └── validator.py    # Independent solution replay validator
│   ├── config.py           # Environment & Settings
│   ├── errors.py           # Custom exception definitions
│   ├── main.py             # FastAPI entry point & exception handlers
│   └── schemas.py          # Pydantic v2 data models
├── docs/
│   └── API_CONTRACT.md     # Official API specification
├── scripts/
│   ├── test_live_llm.py    # Live API test runner
│   ├── evaluate_30_runs.py # 30-call directive/latency benchmark
│   └── benchmark_latency.py # Single-pass latency benchmark
├── tests/                  # Pytest suite (unit & public case tests)
├── Dockerfile              # Production container build recipe
├── requirements.txt        # Python package requirements
└── README.md               # Documentation
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
