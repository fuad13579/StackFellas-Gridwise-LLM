"""CLI script to test public sample cases against a running API server with a REAL LLM.

Usage:
    python scripts/test_live_llm.py [--url http://localhost:8000] [--case SAMPLE-01]
        [--request-timeout 35] [--health-timeout 10]
"""

import argparse
import json
import math
import sys
from pathlib import Path

import httpx

SAMPLE_CASES_FILE = (
    Path(__file__).resolve().parents[1] / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
)
NUMERIC_TOLERANCE = 0.01


def _response_body(response: httpx.Response) -> str:
    try:
        body = response.json()
        return json.dumps(body, separators=(",", ":"))
    except ValueError:
        return response.text[:1000]


def _numeric_equal(actual: object, expected: object, tolerance: float = NUMERIC_TOLERANCE) -> bool:
    try:
        actual_value = float(actual)
        expected_value = float(expected)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(actual_value)
        and math.isfinite(expected_value)
        and abs(actual_value - expected_value) <= tolerance
    )


def _compare_interpretations(actual: object, expected: object) -> list[str]:
    """Return semantic mismatches for the structured directive interpretation."""
    errors: list[str] = []
    if not isinstance(actual, list):
        return ["directive_interpretation is not an array"]
    if not isinstance(expected, list):
        return ["reference directive_interpretation is not an array"]

    if len(actual) != len(expected):
        errors.append(f"directive count mismatch: got {len(actual)}, expected {len(expected)}")

    for position, expected_item in enumerate(expected):
        if position >= len(actual):
            errors.append(f"missing directive entry at position {position}")
            continue
        actual_item = actual[position]
        if not isinstance(actual_item, dict):
            errors.append(f"directive[{position}] is not an object")
            continue

        prefix = f"directive[{position}]"
        for field in ("note_index", "applies", "directive_type"):
            if actual_item.get(field) != expected_item.get(field):
                errors.append(
                    f"{prefix}.{field}: got {actual_item.get(field)!r}, "
                    f"expected {expected_item.get(field)!r}"
                )

        expected_type = expected_item.get("directive_type")
        actual_adjustment = actual_item.get("structured_adjustment")
        expected_adjustment = expected_item.get("structured_adjustment")
        if expected_type == "no_op":
            if actual_adjustment is not None:
                errors.append(f"{prefix}.structured_adjustment: expected null")
            continue
        if not isinstance(actual_adjustment, dict) or not isinstance(expected_adjustment, dict):
            errors.append(f"{prefix}.structured_adjustment: expected an object")
            continue

        if set(actual_adjustment) != set(expected_adjustment):
            errors.append(f"{prefix}.structured_adjustment keys differ")
        if actual_adjustment.get("hours") != expected_adjustment.get("hours"):
            errors.append(
                f"{prefix}.hours: got {actual_adjustment.get('hours')!r}, "
                f"expected {expected_adjustment.get('hours')!r}"
            )

        numeric_field = {
            "solar_reduction": "factor",
            "minimum_battery_reserve": "minimum_energy_kwh",
            "max_grid_window": "max_grid_kwh",
        }.get(expected_type)
        if numeric_field and not _numeric_equal(
            actual_adjustment.get(numeric_field), expected_adjustment.get(numeric_field)
        ):
            errors.append(f"{prefix}.{numeric_field}: numeric value differs")

    for position in range(len(expected), len(actual)):
        errors.append(f"unexpected extra directive entry at position {position}")
    return errors


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
            expected_output = c["expected_output"]
            expected_interpretations = expected_output["directive_interpretation"]
            ref_cost = float(expected_output["total_cost_bdt"])

            print(f"--- [Testing {case_id}] {label} ---")
            try:
                response = client.post(endpoint, json=input_data)
                if response.status_code != 200:
                    print(f"  [FAIL] HTTP {response.status_code}: {_response_body(response)}")
                    failed += 1
                    continue

                result = response.json()
                if not isinstance(result, dict):
                    print("  [FAIL] Optimization response must be a JSON object.")
                    failed += 1
                    continue
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
                if missing_fields or not isinstance(result.get("hourly_plan"), list) or len(result["hourly_plan"]) != 24:
                    missing = ", ".join(sorted(missing_fields)) or "hourly_plan must contain 24 entries"
                    print(f"  [FAIL] Invalid optimization response: {missing}")
                    failed += 1
                    continue

                returned_cost = float(result["total_cost_bdt"])
                cost_diff = abs(returned_cost - ref_cost)
                interpretation_errors = _compare_interpretations(
                    result["directive_interpretation"], expected_interpretations
                )

                print(
                    f"  Returned Cost: {returned_cost} BDT "
                    f"(Reference: {ref_cost} BDT, Diff: {round(cost_diff, 4)})"
                )
                print(f"  Plan Summary:  {result['plan_summary']}")
                if interpretation_errors:
                    print("  Interpretation mismatches:")
                    for error in interpretation_errors:
                        print(f"    - {error}")

                if not math.isfinite(returned_cost):
                    print("  [FAIL] total_cost_bdt must be finite.")
                    failed += 1
                elif not interpretation_errors and cost_diff <= NUMERIC_TOLERANCE:
                    print(f"  [PASS] {case_id} interpretation and optimal cost matched.")
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
