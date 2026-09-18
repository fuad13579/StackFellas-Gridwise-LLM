"""Benchmark script for measuring pipeline, LLM, and LP solver latency."""

import json
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

SAMPLE_CASES_FILE = (
    Path(__file__).resolve().parents[1] / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
)


def benchmark():
    settings = get_settings()
    with open(SAMPLE_CASES_FILE, "r", encoding="utf-8") as f:
        cases = json.load(f)["cases"]

    print("=" * 60)
    print("      GRIDWISE END-TO-END LATENCY BENCHMARK REPORT      ")
    print("=" * 60)
    print(f"Model/Provider : {settings.llm_model} @ {settings.llm_api_url}")
    print(f"Number of Cases: {len(cases)} sample cases\n")

    total_times = []
    llm_times = []
    opt_times = []
    cost_matches = 0

    for c in cases:
        case_id = c["id"]
        ref_cost = c["expected_output"]["total_cost_bdt"]
        req = OptimizeRequest.model_validate(c["input"])

        t0 = time.perf_counter()

        # 1. LLM Interpretation
        interpreter = LLMInterpreter(settings)
        raw_llm = interpreter.interpret(req)
        t_llm = time.perf_counter() - t0

        # 2. Validation & Normalization
        interps = validate_directives(raw_llm, req)
        norm = normalize_directives(req, interps)

        # 3. SciPy LP Optimization
        t_opt_start = time.perf_counter()
        resp = solve_optimization(req, norm, settings, interps)
        t_opt = time.perf_counter() - t_opt_start

        # 4. Independent Replay Validation
        validate_solution(req, norm, resp)

        t_total = time.perf_counter() - t0

        total_times.append(t_total)
        llm_times.append(t_llm)
        opt_times.append(t_opt)

        cost_diff = abs(resp.total_cost_bdt - ref_cost)
        match_str = "EXACT COST MATCH" if cost_diff <= 0.01 else f"FEASIBLE (diff={cost_diff:.2f})"
        if cost_diff <= 0.01:
            cost_matches += 1

        print(
            f"Case {case_id:10s} | Total: {t_total:.3f}s | LLM: {t_llm:.3f}s | LP: {t_opt * 1000:5.2f}ms | Cost: {resp.total_cost_bdt:8.2f} BDT ({match_str})"
        )

    avg_total = sum(total_times) / len(total_times)
    avg_llm = sum(llm_times) / len(llm_times)
    avg_opt = sum(opt_times) / len(opt_times)

    print("-" * 60)
    print(f"Average Total Latency : {avg_total:.3f} seconds")
    print(f"Average LLM Latency   : {avg_llm:.3f} seconds ({round((avg_llm/avg_total)*100, 1)}% of total)")
    print(f"Average LP Solver Time: {avg_opt * 1000:.2f} milliseconds")
    print("-" * 60)

    # Participant rubric evaluation threshold check
    print("\n--- Evaluation Rubric Latency Scoring ---")
    if avg_total <= 5.0:
        print(f"p95 / Average <= 5.0s  =>  PERFECT SCORE (3 / 3 Performance points)")
    elif avg_total <= 15.0:
        print(f"Average <= 15.0s      =>  GOOD SCORE (2 / 3 Performance points)")
    elif avg_total <= 30.0:
        print(f"Average <= 30.0s      =>  PASSING SCORE (1 / 3 Performance points)")
    else:
        print(f"Average > 30.0s       =>  TIMEOUT VIOLATION (0 / 3 Performance points)")
    print("=" * 60)


if __name__ == "__main__":
    benchmark()
