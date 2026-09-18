"""CLI script to test public sample cases against a running API server with a REAL LLM.

Usage:
    python scripts/test_live_llm.py [--url http://localhost:8000] [--case SAMPLE-01]
        [--request-timeout 35] [--health-timeout 10]
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

SAMPLE_CASES_FILE = (
    Path(__file__).resolve().parents[1] / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
)


def _response_body(response: httpx.Response) -> str:
    try:
        body = response.json()
        return json.dumps(body, separators=(",", ":"))
    except ValueError:
        return response.text[:1000]


def run_live_tests(
    base_url: str,
    target_case_id: str | None = None,
    request_timeout: float = 45.0,
    health_timeout: float = 10.0,
) -> int:
    endpoint = f"{base_url.rstrip('/')}/optimize-energy"
    health_endpoint = f"{base_url.rstrip('/')}/health"

    print(f"Checking health at {health_endpoint}...")
    try:
        health_response = httpx.get(health_endpoint, timeout=health_timeout)
        health_response.raise_for_status()
        health_json = health_response.json()
        if health_json != {"status": "ok"}:
            print(f"ERROR: Unexpected health response: {_response_body(health_response)}")
            return 1
        print(f"Health OK: {health_json}\n")
    except Exception as exc:
        print(f"ERROR: Failed to reach health endpoint: {exc}")
        return 1

    with open(SAMPLE_CASES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data["cases"]
    if target_case_id:
        cases = [c for c in cases if c["id"] == target_case_id]
        if not cases:
            print(f"ERROR: Case ID {target_case_id} not found in sample file.")
            return 1

    passed = 0
    failed = 0

    print(f"Running live tests for {len(cases)} case(s) against {endpoint}...\n")

    with httpx.Client(timeout=request_timeout) as client:
        for c in cases:
            case_id = c["id"]
            label = c.get("label", "")
            input_data = c["input"]
            ref_cost = c["expected_output"]["total_cost_bdt"]

            print(f"--- [Testing {case_id}] {label} ---")
            try:
                response = client.post(endpoint, json=input_data)
                if response.status_code != 200:
                    print(f"  [FAIL] HTTP {response.status_code}: {_response_body(response)}")
                    failed += 1
                    continue

                result = response.json()
                required_fields = {
                    "scenario_id",
                    "directive_interpretation",
                    "hourly_plan",
                    "total_grid_kwh",
                    "total_cost_bdt",
                    "peak_grid_kwh",
                    "plan_summary",
                }
                missing_fields = required_fields - result.keys()
                if missing_fields or len(result["hourly_plan"]) != 24:
                    missing = ", ".join(sorted(missing_fields)) or "hourly_plan must contain 24 entries"
                    print(f"  [FAIL] Invalid optimization response: {missing}")
                    failed += 1
                    continue

                returned_cost = float(result["total_cost_bdt"])
                cost_diff = abs(returned_cost - ref_cost)

                print(
                    f"  Returned Cost: {returned_cost} BDT "
                    f"(Reference: {ref_cost} BDT, Diff: {round(cost_diff, 4)})"
                )
                print(f"  Plan Summary:  {result['plan_summary']}")

                if cost_diff <= 0.01:
                    print(f"  [PASS] {case_id} optimal cost matched within tolerance.")
                    passed += 1
                else:
                    print(
                        f"  [FAIL] {case_id} cost difference {round(cost_diff, 4)} BDT exceeds tolerance."
                    )
                    failed += 1

            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                print(f"  [FAIL] Invalid live response: {exc}")
                failed += 1

    print(f"\n==========================================")
    print(f"Live LLM Test Results: {passed} PASSED / {failed} FAILED out of {len(cases)}")
    print(f"==========================================")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test live LLM GridWise API endpoint")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of running API")
    parser.add_argument("--case", default=None, help="Specific sample case ID to test")
    parser.add_argument("--request-timeout", type=float, default=45.0, help="Per-case timeout in seconds")
    parser.add_argument("--health-timeout", type=float, default=10.0, help="Health-check timeout in seconds")
    args = parser.parse_args()

    sys.exit(run_live_tests(args.url, args.case, args.request_timeout, args.health_timeout))
