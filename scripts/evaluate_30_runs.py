"""Comprehensive evaluation script running 30 real LLM API calls (10 cases x 3 runs).

Measures:
- Strict directive interpretation accuracy against organizer ground truth
- Solution feasibility & optimal cost matching
- Real latency distribution: Median (p50), p95, Max, Min
"""

import json
import numpy as np
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.directives.normalizer import normalize_directives
from app.directives.validator import validate_directives
from app.llm.interpreter import LLMInterpreter
from app.optimizer.solver import solve_optimization
from app.optimizer.validator import validate_solution
from app.schemas import OptimizeRequest

SAMPLE_CASES_FILE = ROOT_DIR / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def compare_directive(returned: dict, expected: dict) -> tuple[bool, str]:
    """Strictly compares a returned directive interpretation against ground truth."""
    if returned.get("note_index") != expected.get("note_index"):
        return False, f"note_index mismatch: {returned.get('note_index')} != {expected.get('note_index')}"
    if returned.get("applies") != expected.get("applies"):
        return False, f"applies mismatch: {returned.get('applies')} != {expected.get('applies')}"
    if returned.get("directive_type") != expected.get("directive_type"):
        return False, f"directive_type mismatch: {returned.get('directive_type')} != {expected.get('directive_type')}"

    ret_adj = returned.get("structured_adjustment")
    exp_adj = expected.get("structured_adjustment")

    if exp_adj is None:
        if ret_adj is not None:
            return False, f"structured_adjustment expected None, got {ret_adj}"
        return True, "OK"

    if ret_adj is None:
        return False, f"structured_adjustment expected {exp_adj}, got None"

    if ret_adj.get("hours") != exp_adj.get("hours"):
        return False, f"hours mismatch: {ret_adj.get('hours')} != {exp_adj.get('hours')}"

    # Check numeric values
    for num_key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
        if num_key in exp_adj:
            ret_val = ret_adj.get(num_key)
            exp_val = exp_adj.get(num_key)
            if ret_val is None or abs(float(ret_val) - float(exp_val)) > 0.01:
                return False, f"{num_key} mismatch: {ret_val} != {exp_val}"

    return True, "OK"


def run_evaluation():
    settings = get_settings()
    with open(SAMPLE_CASES_FILE, "r", encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    runs_per_case = 3
    total_calls = len(cases) * runs_per_case

    print("=" * 75)
    print(f"   STRICT EVALUATION BENCHMARK ({total_calls} REAL LLM CALLS: 10 CASES x {runs_per_case} RUNS)")
    print("=" * 75)
    print(f"Provider Endpoint : {settings.llm_api_url}")
    print(f"Model Identifier  : {settings.llm_model}\n")

    total_latencies = []
    llm_latencies = []
    solver_latencies = []

    total_notes_checked = 0
    correct_notes = 0

    total_requests = 0
    valid_schedules = 0
    exact_cost_matches = 0

    for c_idx, c in enumerate(cases, 1):
        case_id = c["id"]
        label = c.get("label", "")
        exp_output = c["expected_output"]
        exp_directives = exp_output["directive_interpretation"]
        ref_cost = exp_output["total_cost_bdt"]
        req = OptimizeRequest.model_validate(c["input"])

        print(f"--- [Case {c_idx:02d}/10: {case_id}] {label} ---")

        for run_idx in range(1, runs_per_case + 1):
            total_requests += 1
            t0 = time.perf_counter()

            # 1. Real LLM Call
            interpreter = LLMInterpreter(settings)
            try:
                raw_llm = interpreter.interpret(req)
                t_llm = time.perf_counter() - t0
            except Exception as exc:
                print(f"  Run {run_idx}: LLM FAIL - {exc}")
                continue

            # 2. Strict Directive Comparison
            try:
                raw_json = json.loads(raw_llm)
                ret_directives = raw_json.get("directive_interpretation", [])
            except Exception:
                ret_directives = []

            case_directive_correct = True
            mismatch_reasons = []

            for note_i, exp_d in enumerate(exp_directives):
                total_notes_checked += 1
                if note_i < len(ret_directives):
                    is_match, reason = compare_directive(ret_directives[note_i], exp_d)
                else:
                    is_match, reason = False, "Missing directive entry"

                if is_match:
                    correct_notes += 1
                else:
                    case_directive_correct = False
                    mismatch_reasons.append(f"Note {note_i}: {reason}")

            # 3. Validation & Normalization
            try:
                interps = validate_directives(raw_llm, req)
                norm = normalize_directives(req, interps)
            except Exception as exc:
                print(f"  Run {run_idx}: Guardrail Validation FAIL - {exc}")
                continue

            # 4. SciPy LP Solver
            t_opt_start = time.perf_counter()
            try:
                resp = solve_optimization(req, norm, settings, interps)
                t_opt = time.perf_counter() - t_opt_start
            except Exception as exc:
                print(f"  Run {run_idx}: LP Solver FAIL - {exc}")
                continue

            # 5. Independent Solution Replay Validator
            try:
                validate_solution(req, norm, resp)
                valid_schedules += 1
            except Exception as exc:
                print(f"  Run {run_idx}: Solution Replay FAIL - {exc}")
                continue

            t_total = time.perf_counter() - t0

            total_latencies.append(t_total)
            llm_latencies.append(t_llm)
            solver_latencies.append(t_opt)

            cost_diff = abs(resp.total_cost_bdt - ref_cost)
            if cost_diff <= 0.01:
                exact_cost_matches += 1
                cost_status = "EXACT MATCH"
            else:
                cost_status = f"FEASIBLE (diff={cost_diff:.2f} BDT)"

            dir_status = "STRICT MATCH" if case_directive_correct else f"MISMATCH ({'; '.join(mismatch_reasons)})"

            print(
                f"  Run {run_idx}: Total={t_total:.3f}s (LLM={t_llm:.3f}s, LP={t_opt*1000:4.1f}ms) | Directives: {dir_status} | Cost: {resp.total_cost_bdt} BDT ({cost_status})"
            )

    print("\n" + "=" * 75)
    print("                  FINAL BENCHMARK SUMMARY & METRICS")
    print("=" * 75)

    dir_acc = (correct_notes / total_notes_checked * 100) if total_notes_checked else 0
    cost_match_rate = (exact_cost_matches / total_requests * 100) if total_requests else 0
    success_rate = (valid_schedules / total_requests * 100) if total_requests else 0

    p50_tot = float(np.median(total_latencies)) if total_latencies else 0
    p95_tot = float(np.percentile(total_latencies, 95)) if total_latencies else 0
    max_tot = float(np.max(total_latencies)) if total_latencies else 0
    min_tot = float(np.min(total_latencies)) if total_latencies else 0

    p50_llm = float(np.median(llm_latencies)) if llm_latencies else 0
    p95_llm = float(np.percentile(llm_latencies, 95)) if llm_latencies else 0
    max_llm = float(np.max(llm_latencies)) if llm_latencies else 0

    p50_solver = float(np.median(solver_latencies)) * 1000 if solver_latencies else 0
    max_solver = float(np.max(solver_latencies)) * 1000 if solver_latencies else 0

    print(f"Total API Requests Evaluated : {total_requests}")
    print(f"Total Notes Checked          : {total_notes_checked}")
    print(f"Strict Directive Accuracy    : {correct_notes}/{total_notes_checked} ({dir_acc:.2f}%)")
    print(f"Exact Optimal Cost Match Rate: {exact_cost_matches}/{total_requests} ({cost_match_rate:.2f}%)")
    print(f"GridWise Schedule Success Rate: {valid_schedules}/{total_requests} ({success_rate:.2f}%)\n")

    print("--- Latency Metrics (Seconds) ---")
    print(f"Total Pipeline Latency : Median (p50)={p50_tot:.3f}s | p95={p95_tot:.3f}s | Max={max_tot:.3f}s | Min={min_tot:.3f}s")
    print(f"LLM Provider Network   : Median (p50)={p50_llm:.3f}s | p95={p95_llm:.3f}s | Max={max_llm:.3f}s")
    print(f"SciPy LP Solver Time   : Median (p50)={p50_solver:.2f}ms | Max={max_solver:.2f}ms\n")

    print("--- Competition Evaluation Rubric Rating ---")
    if p95_tot <= 5.0:
        print("Performance Score: 3 / 3 MAXIMUM POINTS (p95 <= 5.0s)")
    elif p95_tot <= 15.0:
        print("Performance Score: 2 / 3 POINTS (p95 <= 15.0s)")
    elif p95_tot <= 30.0:
        print("Performance Score: 1 / 3 POINTS (p95 <= 30.0s)")
    else:
        print("Performance Score: 0 / 3 POINTS (Timeout violation)")
    print("=" * 75)


if __name__ == "__main__":
    run_evaluation()
