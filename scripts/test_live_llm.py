"""CLI script to test public sample cases against a running API server with a REAL LLM.

Usage:
  python scripts/test_live_llm.py [--url http://localhost:8000] [--case SAMPLE-01]
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

SAMPLE_CASES_FILE = (
    Path(__file__).resolve().parents[1] / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
)


def run_live_tests(base_url: str, target_case_id: str | None = None) -> None:
    endpoint = f"{base_url.rstrip('/')}/optimize-energy"
    health_endpoint = f"{base_url.rstrip('/')}/health"

    print(f"Checking health at {health_endpoint}...")
    try:
        r = httpx.get(health_endpoint, timeout=10)
        r.raise_for_status()
        print(f"Health OK: {r.json()}\n")
    except Exception as exc:
        print(f"ERROR: Failed to reach health endpoint: {exc}")
        sys.exit(1)

    with open(SAMPLE_CASES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data["cases"]
    if target_case_id:
        cases = [c for c in cases if c["id"] == target_case_id]
        if not cases:
            print(f"ERROR: Case ID {target_case_id} not found in sample file.")
            sys.exit(1)

    passed = 0
    failed = 0

    print(f"Running live tests for {len(cases)} case(s) against {endpoint}...\n")

    for c in cases:
        case_id = c["id"]
        label = c.get("label", "")
        input_data = c["input"]
        ref_cost = c["expected_output"]["total_cost_bdt"]

        print(f"--- [Testing {case_id}] {label} ---")
        try:
            resp = httpx.post(endpoint, json=input_data, timeout=45)
            if resp.status_code != 200:
                print(f"  [FAIL] HTTP {resp.status_code}: {resp.text}")
                failed += 1
                continue

            res_json = resp.json()
            returned_cost = res_json["total_cost_bdt"]
            cost_diff = abs(returned_cost - ref_cost)

            print(f"  Returned Cost: {returned_cost} BDT (Reference: {ref_cost} BDT, Diff: {round(cost_diff, 4)})")
            print(f"  Plan Summary:  {res_json.get('plan_summary')}")

            if cost_diff <= 0.01:
                print(f"  [PASS] {case_id} optimal cost matched within tolerance.")
                passed += 1
            else:
                print(f"  [FAIL] {case_id} cost difference {round(cost_diff, 4)} BDT exceeds tolerance.")
                failed += 1

        except Exception as exc:
            print(f"  [FAIL] Exception during request: {exc}")
            failed += 1

    print(f"\n==========================================")
    print(f"Live LLM Test Results: {passed} PASSED / {failed} FAILED out of {len(cases)}")
    print(f"==========================================")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test live LLM GridWise API endpoint")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of running API")
    parser.add_argument("--case", default=None, help="Specific sample case ID to test")
    args = parser.parse_args()

    run_live_tests(args.url, args.case)
