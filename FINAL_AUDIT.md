# GridWise LLM Audit

Date: 2026-09-21

This audit describes the repository as it exists after overnight time-window canonicalization, official HTTP status alignment, test expansion, README correction, and restoration of the tracked official problem documents.

## Verified implementation

Present and in use:

- `app/main.py` — `GET /health` (async) and synchronous `POST /optimize-energy`
- `app/schemas.py` — official request/response field names
- `app/llm/` — OpenRouter-compatible client (`openai/gpt-4o-mini`)
- `app/directives/time_windows.py` — deterministic `[start, end)` hour lists, overnight ranges sorted
- `app/directives/validator.py` — guardrails plus explicit-window hour replacement
- `app/optimizer/solver.py` — two-stage SciPy `linprog` (cost, then throughput)
- `app/optimizer/validator.py` — independent schedule replay
- `README.md`, `docs/API_CONTRACT.md`, `Dockerfile`, `requirements.txt`, `tests/`
- Official documents: `tmp/official/BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.txt` and `tmp/official/BUP_CSE_FEST_2026_Participant_Guide_&_Evaluation_Rubric_GridWise_LLM.txt`

Stale nested review snapshot `tmp/review-main-7875710/` is removed. Public sample cases remain at `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`.

## 1) API contract

Endpoints:

- `GET /health` → HTTP 200 `{"status": "ok"}`
- `POST /optimize-energy` → HTTP 200 on success

HTTP status mapping (official BUP codes only):

| Status | JSON `error.code` | Meaning |
| --- | --- | --- |
| 400 | `invalid_request` | Malformed or structurally invalid request |
| 422 | `infeasible` | Well-formed request with no feasible schedule |
| 500 | `llm_unavailable`, `invalid_llm_output`, `llm_not_configured`, `request_timeout`, `invalid_solution`, `internal_error` | Provider/config/timeout/replay/internal failure |

`409`, `502`, `503`, and `504` are no longer used.

Malformed JSON and schema violations return JSON-safe 400 bodies. Tracebacks and secrets are not returned.

## 2) Time windows

Explicit clock ranges in the original note replace LLM-supplied `hours` before hour-list validation.

Same-day `[start, end)`:

- `6 PM to 10 PM` → `[18, 19, 20, 21]`
- `2 PM to 5 PM` → `[14, 15, 16]`
- `noon to 2 PM` → `[12, 13]`

Overnight ranges wrap, then sort (optimizer treats the list as a set of hour indices):

- `10 PM to 2 AM` → `[0, 1, 22, 23]`
- `11 PM to 1 AM` → `[0, 23]`
- `9 PM to midnight` → `[21, 22, 23]`

`and` is a range separator only in `between START and END`. Plain “6 PM and 10 PM” is not treated as a continuous window.

Final lists are sorted, unique, and in `0..23`. Directive type and numeric values are unchanged. SAMPLE-07 is covered by this path (`[18, 19, 20, 21]`, cost `38550.0`).

## 3) Pipeline

1. LLM interprets notes (OpenRouter, `openai/gpt-4o-mini`).
2. Deterministic validation and explicit-window canonicalization.
3. Constraint normalization and LP solve (event loop not blocked; sync route).
4. Independent replay of the 24-hour plan.

## 4) Tests

Offline:

```bash
pytest -q
```

Result: **94 passed**, 0 failed, 0 warnings.

Coverage includes the 10 public cases, same-day and overnight windows, full validator integration, API status-code contract, timeouts, overlap normalization, and paraphrases.

Live (local API, real OpenRouter, 2026-09-21):

```text
LIVE TESTED
10 PASSED / 0 FAILED
SAMPLE-07 cost 38550.0 (reference 38550, diff 0.0)
```

The live runner checked directive semantics, independent schedule replay, and totals for all 10 official public cases.

## 5) Documentation and deployment

README matches the current implementation: 94 tests, SAMPLE-07 fix, deterministic time windows, OpenRouter / `openai/gpt-4o-mini`, strict live validation, sync FastAPI route, official `[start, end)` semantics, and the 400/422/500 error table.

Docker and Render packaging remain as previously documented. Live Render was not re-checked after the HTTP status-code change; local live tests used `http://127.0.0.1:8000`.

## 6) Remaining risks

- Render must be redeployed before the public URL serves the new HTTP status mapping.
- `POST /optimize-energy` still requires valid `LLM_API_URL`, `LLM_API_KEY`, and `LLM_MODEL`.
- On this Windows machine, AVG HTTPS scanning can block Python TLS unless `python.exe` is excepted. That is an environment issue, not an application defect.

## Verdict

No blocking defect was found in the current implementation. Overnight windows, official HTTP codes, restored official docs, README, offline tests, and live public-case verification are aligned with the competition contract.
