# StackFellas SmartGrid AI Backend

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![SciPy](https://img.shields.io/badge/SciPy-linprog-orange.svg)](https://scipy.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Backend service for **StackFellas SmartGrid AI**, built for the **BUP CSE Fest 2026 Hackathon (Preliminary Round)**. 

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
                                  │   (OpenAI / Custom Provider)  │
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
- **POST /optimize-energy**: Complete scenario optimization pipeline within the 30-second deadline.
- **Supported Operator Directives**:
  1. `solar_reduction`: Usable solar output reduction during specific hours. (`factor` = fraction remaining).
  2. `minimum_battery_reserve`: Elevated minimum battery energy reserve during specific hours.
  3. `no_charge_window`: Disables battery charging during specified hours.
  4. `no_discharge_window`: Disables battery discharging during specified hours.
  5. `max_grid_window`: Grid import cap during specified hours.
  6. `no_op`: Irrelevant notes marked with `applies=false` and `structured_adjustment=null`.
- **Lossless Battery Accounting**: Enforces $E_{\text{after}} = E_{\text{before}} + \text{charge} - \text{discharge}$ and end-of-day battery neutrality ($E_{23} = E_{\text{initial}}$).
- **Independent Solution Replay**: Every schedule is re-verified hour-by-hour prior to output emission to guarantee exact feasibility.

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
# LLM Provider Credentials
LLM_API_URL=https://api.openai.com/v1/chat/completions
LLM_API_KEY=your-api-key-here
LLM_MODEL=gpt-4o-mini

# Optional Performance Settings
LLM_TIMEOUT_SECONDS=30
SOLVER_TIME_LIMIT_SECONDS=10
LOG_LEVEL=INFO
```

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

---

## Testing

### Automated Offline Tests (Mocked LLM + All 10 Public Cases)

Run unit tests and verify optimization against ground-truth interpretations for all 10 public sample cases:

```bash
pytest -v
```

### Live LLM Test Script

Run public sample cases against a live running API instance using real LLM API calls:

```bash
python scripts/test_live_llm.py --url http://localhost:8000
```

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
│   │   ├── normalizer.py   # Maps directives to normalized LP constraints
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
│   └── test_live_llm.py    # Live API test runner
├── tests/                  # Pytest suite (unit & public case tests)
├── Dockerfile              # Production container build recipe
├── requirements.txt        # Python package requirements
└── README.md               # Documentation
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
