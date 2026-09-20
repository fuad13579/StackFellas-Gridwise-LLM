"""Comprehensive Final Verification Suite for Deployed Production Endpoint.

Executes Sections 1-7 against https://stackfellas-gridwise-llm.onrender.com
"""

import json
import sys
import time
from pathlib import Path

import httpx
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.directives.normalizer import normalize_directives
from app.directives.validator import validate_directives
from app.optimizer.validator import validate_solution
from app.schemas import OptimizeRequest

DEPLOYED_URL = "https://stackfellas-gridwise-llm.onrender.com"
SAMPLE_CASES_FILE = ROOT_DIR / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def compare_directive(returned: dict, expected: dict) -> tuple[bool, str]:
    if returned.get("note_index") != expected.get("note_index"):
        return False, f"note_index mismatch: actual {returned.get('note_index')} vs expected {expected.get('note_index')}"
    if returned.get("applies") != expected.get("applies"):
        return False, f"applies mismatch: actual {returned.get('applies')} vs expected {expected.get('applies')}"
    if returned.get("directive_type") != expected.get("directive_type"):
        return False, f"directive_type mismatch: actual '{returned.get('directive_type')}' vs expected '{expected.get('directive_type')}'"

    ret_adj = returned.get("structured_adjustment")
    exp_adj = expected.get("structured_adjustment")

    if exp_adj is None:
        if ret_adj is not None:
            return False, f"structured_adjustment expected None, got {ret_adj}"
        return True, "OK"

    if ret_adj is None:
        return False, f"structured_adjustment expected {exp_adj}, got None"

    if ret_adj.get("hours") != exp_adj.get("hours"):
        return False, f"hours mismatch: actual {ret_adj.get('hours')} vs expected {exp_adj.get('hours')}"

    for num_key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
        if num_key in exp_adj:
            ret_val = ret_adj.get(num_key)
            exp_val = exp_adj.get(num_key)
            if ret_val is None or abs(float(ret_val) - float(exp_val)) > 0.01:
                return False, f"{num_key} mismatch: actual {ret_val} vs expected {exp_val}"

    return True, "OK"


def run_full_suite():
    print("=" * 80)
    print("      FINAL VERIFICATION AUDIT SUITE - DEPLOYED PRODUCTION SERVICE      ")
    print("=" * 80)
    print(f"Target Service URL: {DEPLOYED_URL}\n")

    results = {}

    # --- SECTION 1: PUBLIC HEALTH ENDPOINT ---
    print("--- 1. VERIFY PUBLIC HEALTH ENDPOINT ---")
    try:
        r_health = httpx.get(f"{DEPLOYED_URL}/health", timeout=15)
        health_status = r_health.status_code
        health_body = r_health.json() if health_status == 200 else {}
        health_pass = health_status == 200 and health_body == {"status": "ok"}
        print(f"  GET /health: HTTP {health_status} -> {health_body} [{ 'PASS' if health_pass else 'FAIL' }]")
    except Exception as exc:
        health_pass = False
        print(f"  GET /health FAIL: {exc}")
    results["health"] = health_pass

    # --- SECTION 2: FASTAPI DOCS & OPENAPI JSON ---
    print("\n--- 2. VERIFY FASTAPI DOCS & OPENAPI SCHEMA ---")
    docs_pass = False
    try:
        r_openapi = httpx.get(f"{DEPLOYED_URL}/openapi.json", timeout=15)
        if r_openapi.status_code == 200:
            schema = r_openapi.json()
            paths = schema.get("paths", {})
            has_health = "/health" in paths
            has_optimize = "/optimize-energy" in paths
            no_debug = not any(p.startswith("/debug") or p.startswith("/admin") for p in paths)
            docs_pass = has_health and has_optimize and no_debug
            print(f"  openapi.json: HTTP 200 | /health: {has_health} | /optimize-energy: {has_optimize} | Clean routes: {no_debug}")
        else:
            print(f"  openapi.json HTTP {r_openapi.status_code}")
    except Exception as exc:
        print(f"  openapi.json check exception: {exc}")
    results["docs"] = docs_pass

    # --- SECTION 3 & 4: STRICT PUBLIC-CASE TESTS & SAMPLE-07 REGRESSION ---
    print("\n--- 3 & 4. STRICT PUBLIC-CASE TESTS AGAINST DEPLOYED API ---")
    with open(SAMPLE_CASES_FILE, "r", encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    case_passed_count = 0
    exact_cost_count = 0
    directive_correct_notes = 0
    total_notes_count = 0
    s7_passed = False

    for c in cases:
        case_id = c["id"]
        label = c.get("label", "")
        exp_output = c["expected_output"]
        exp_directives = exp_output["directive_interpretation"]
        ref_cost = exp_output["total_cost_bdt"]
        input_data = c["input"]
        req = OptimizeRequest.model_validate(input_data)

        try:
            t0 = time.perf_counter()
            resp = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=input_data, timeout=30)
            t_lat = time.perf_counter() - t0

            if resp.status_code != 200:
                print(f"  [{case_id}] FAIL: HTTP {resp.status_code} -> {resp.text}")
                continue

            data = resp.json()
            ret_directives = data.get("directive_interpretation", [])
            ret_plan = data.get("hourly_plan", [])
            ret_cost = data.get("total_cost_bdt", 0.0)

            # Check top level
            sec_match = data.get("scenario_id") == case_id
            plan_len_match = len(ret_plan) == 24

            # Check directives strictly
            all_dirs_correct = True
            for note_i, exp_d in enumerate(exp_directives):
                total_notes_count += 1
                if note_i < len(ret_directives):
                    match, reason = compare_directive(ret_directives[note_i], exp_d)
                else:
                    match, reason = False, "Missing directive"

                if match:
                    directive_correct_notes += 1
                else:
                    all_dirs_correct = False
                    print(f"    [{case_id}] Directive Mismatch note {note_i}: {reason}")

            cost_diff = abs(ret_cost - ref_cost)
            exact_cost = cost_diff <= 0.01

            # Validate returned plan physically
            interps = validate_directives(json.dumps({"directive_interpretation": ret_directives}), req)
            norm = normalize_directives(req, interps)

            # Run physical replay validation
            try:
                from app.optimizer.validator import validate_solution
                from app.schemas import OptimizeResponse
                opt_resp = OptimizeResponse.model_validate(data)
                validate_solution(req, norm, opt_resp)
                replay_valid = True
            except Exception as val_exc:
                replay_valid = False
                print(f"    [{case_id}] Replay Validation FAIL: {val_exc}")

            case_ok = sec_match and plan_len_match and all_dirs_correct and exact_cost and replay_valid
            if case_ok:
                case_passed_count += 1
            if exact_cost:
                exact_cost_count += 1

            if case_id == "SAMPLE-07":
                s7_passed = case_ok

            status_str = "PASS (EXACT MATCH)" if case_ok else f"FAIL/PARTIAL (cost={ret_cost}, diff={cost_diff:.2f})"
            print(f"  [{case_id:9s}] {label[:35]:35s} | Latency: {t_lat:.3f}s | {status_str}")

        except Exception as exc:
            print(f"  [{case_id}] EXCEPTION: {exc}")

    results["case_passed_count"] = case_passed_count
    results["exact_cost_count"] = exact_cost_count
    results["directive_accuracy"] = (directive_correct_notes / total_notes_count * 100) if total_notes_count else 0
    results["sample_07"] = s7_passed

    # --- SECTION 5: TEST EDGE CASES ---
    print("\n--- 5. TEST EDGE CASES AGAINST DEPLOYED SERVICE ---")
    edge_results = {}

    def build_base_payload(notes):
        return {
            "scenario_id": "EDGE-TEST",
            "operator_notes": notes,
            "hours": [
                {"hour": h, "demand_kwh": 100, "solar_kwh": 50, "tariff_bdt_per_kwh": 5}
                for h in range(24)
            ],
            "battery": {
                "capacity_kwh": 200,
                "initial_energy_kwh": 100,
                "minimum_energy_kwh": 20,
                "max_charge_kwh_per_hour": 50,
                "max_discharge_kwh_per_hour": 50,
            },
        }

    # 5.1 No-op case
    try:
        r_noop = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=build_base_payload(["The cafeteria will serve noodles tomorrow."]), timeout=25)
        d_noop = r_noop.json()["directive_interpretation"][0]
        noop_pass = d_noop["directive_type"] == "no_op" and d_noop["applies"] is False and d_noop["structured_adjustment"] is None
        print(f"  No-op test: type={d_noop['directive_type']} applies={d_noop['applies']} [{ 'PASS' if noop_pass else 'FAIL' }]")
        edge_results["noop"] = noop_pass
    except Exception as exc:
        print(f"  No-op test FAIL: {exc}")
        edge_results["noop"] = False

    # 5.2 Solar reduction BY 25% (factor 0.75)
    try:
        r_by = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=build_base_payload(["Solar will be reduced by 25% from noon to 2 PM."]), timeout=25)
        d_by = r_by.json()["directive_interpretation"][0]
        factor_by = d_by["structured_adjustment"]["factor"]
        hours_by = d_by["structured_adjustment"]["hours"]
        by_pass = d_by["directive_type"] == "solar_reduction" and abs(factor_by - 0.75) <= 0.01 and hours_by == [12, 13]
        print(f"  Solar 'reduced by 25%' test: factor={factor_by} hours={hours_by} [{ 'PASS' if by_pass else 'FAIL' }]")
        edge_results["solar_by"] = by_pass
    except Exception as exc:
        print(f"  Solar 'reduced by 25%' test FAIL: {exc}")
        edge_results["solar_by"] = False

    # 5.3 Solar reduction TO 25% (factor 0.25)
    try:
        r_to = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=build_base_payload(["Solar will be reduced to 25% from noon to 2 PM."]), timeout=25)
        d_to = r_to.json()["directive_interpretation"][0]
        factor_to = d_to["structured_adjustment"]["factor"]
        hours_to = d_to["structured_adjustment"]["hours"]
        to_pass = d_to["directive_type"] == "solar_reduction" and abs(factor_to - 0.25) <= 0.01 and hours_to == [12, 13]
        print(f"  Solar 'reduced to 25%' test: factor={factor_to} hours={hours_to} [{ 'PASS' if to_pass else 'FAIL' }]")
        edge_results["solar_to"] = to_pass
    except Exception as exc:
        print(f"  Solar 'reduced to 25%' test FAIL: {exc}")
        edge_results["solar_to"] = False

    # 5.4 Time window "2 PM until 5 PM" -> [14, 15, 16]
    try:
        r_win = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=build_base_payload(["Do not charge from 2 PM until 5 PM."]), timeout=25)
        d_win = r_win.json()["directive_interpretation"][0]
        hours_win = d_win["structured_adjustment"]["hours"]
        win_pass = d_win["directive_type"] == "no_charge_window" and hours_win == [14, 15, 16]
        print(f"  Time window '2 PM until 5 PM' test: hours={hours_win} [{ 'PASS' if win_pass else 'FAIL' }]")
        edge_results["time_window"] = win_pass
    except Exception as exc:
        print(f"  Time window test FAIL: {exc}")
        edge_results["time_window"] = False

    results["edge_cases"] = edge_results

    # --- SECTION 6: MALFORMED REQUEST HANDLING ---
    print("\n--- 6. TEST MALFORMED REQUEST HANDLING ---")
    malformed_tests = []

    # 6.1 Missing scenario_id
    payload_bad1 = build_base_payload(["Note"])
    del payload_bad1["scenario_id"]
    r_b1 = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=payload_bad1, timeout=15)
    b1_ok = r_b1.status_code == 400 and "error" in r_b1.json() and r_b1.json()["error"]["code"] == "invalid_request"
    malformed_tests.append(("Missing scenario_id", r_b1.status_code, b1_ok))

    # 6.2 Duplicate hours
    payload_bad2 = build_base_payload(["Note"])
    payload_bad2["hours"][1]["hour"] = 0
    r_b2 = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=payload_bad2, timeout=15)
    b2_ok = r_b2.status_code == 400 and "error" in r_b2.json() and r_b2.json()["error"]["code"] == "invalid_request"
    malformed_tests.append(("Duplicate hours", r_b2.status_code, b2_ok))

    # 6.3 Invalid hour 24
    payload_bad3 = build_base_payload(["Note"])
    payload_bad3["hours"][23]["hour"] = 24
    r_b3 = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=payload_bad3, timeout=15)
    b3_ok = r_b3.status_code == 400 and "error" in r_b3.json() and r_b3.json()["error"]["code"] == "invalid_request"
    malformed_tests.append(("Invalid hour 24", r_b3.status_code, b3_ok))

    # 6.4 Whitespace-only note
    payload_bad4 = build_base_payload(["   "])
    r_b4 = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=payload_bad4, timeout=15)
    b4_ok = r_b4.status_code == 400 and "error" in r_b4.json() and r_b4.json()["error"]["code"] == "invalid_request"
    malformed_tests.append(("Whitespace-only note", r_b4.status_code, b4_ok))

    # 6.5 Malformed battery value (initial > capacity)
    payload_bad5 = build_base_payload(["Note"])
    payload_bad5["battery"]["initial_energy_kwh"] = 500
    r_b5 = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=payload_bad5, timeout=15)
    b5_ok = r_b5.status_code == 400 and "error" in r_b5.json() and r_b5.json()["error"]["code"] == "invalid_request"
    malformed_tests.append(("Malformed battery values", r_b5.status_code, b5_ok))

    for name, code, is_ok in malformed_tests:
        print(f"  {name:25s}: HTTP {code} [{ 'PASS' if is_ok else 'FAIL' }]")

    malformed_pass = all(item[2] for item in malformed_tests)
    results["malformed"] = malformed_pass

    # Post-malformed health check
    r_post_health = httpx.get(f"{DEPLOYED_URL}/health", timeout=15)
    post_health_pass = r_post_health.status_code == 200 and r_post_health.json() == {"status": "ok"}
    print(f"  Post-malformed server health check: HTTP {r_post_health.status_code} [{ 'PASS' if post_health_pass else 'FAIL' }]")

    # --- SECTION 7: LLM PROVIDER RELIABILITY & DEPLOYED LATENCY STATS ---
    print("\n--- 7. PROVIDER RELIABILITY & DEPLOYED LATENCY BENCHMARK ---")
    latencies = []
    successes = 0
    failures = 0

    for i in range(10):
        c = cases[i % len(cases)]
        try:
            t0 = time.perf_counter()
            r_rep = httpx.post(f"{DEPLOYED_URL}/optimize-energy", json=c["input"], timeout=30)
            t_elapsed = time.perf_counter() - t0
            if r_rep.status_code == 200:
                successes += 1
                latencies.append(t_elapsed)
            else:
                failures += 1
        except Exception:
            failures += 1

    p50_lat = float(np.median(latencies)) if latencies else 0
    p95_lat = float(np.percentile(latencies, 95)) if latencies else 0
    max_lat = float(np.max(latencies)) if latencies else 0
    min_lat = float(np.min(latencies)) if latencies else 0

    print(f"  Total Calls: {successes + failures} | Successful: {successes} | Failures: {failures}")
    print(f"  Min: {min_lat:.3f}s | Median (p50): {p50_lat:.3f}s | p95: {p95_lat:.3f}s | Max: {max_lat:.3f}s")

    results["reliability"] = {
        "successes": successes,
        "failures": failures,
        "min": min_lat,
        "p50": p50_lat,
        "p95": p95_lat,
        "max": max_lat,
    }

    print("\n" + "=" * 80)
    print("                     VERIFICATION SUITE COMPLETED")
    print("=" * 80)
    return results


if __name__ == "__main__":
    run_full_suite()
