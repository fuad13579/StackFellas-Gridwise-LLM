"""Automated tests for ALL 10 official public sample cases."""

import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.directives.normalizer import normalize_directives
from app.directives.validator import validate_directives
from app.optimizer.solver import solve_optimization
from app.optimizer.validator import validate_solution
from app.schemas import OptimizeRequest

SAMPLE_CASES_FILE = (
    Path(__file__).resolve().parents[1] / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
)


def load_public_sample_cases():
    with open(SAMPLE_CASES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


@pytest.mark.parametrize("case", load_public_sample_cases(), ids=lambda c: c["id"])
def test_public_sample_case(case):
    case_id = case["id"]
    input_data = case["input"]
    expected_output = case["expected_output"]

    # 1. Validate request schema
    request = OptimizeRequest.model_validate(input_data)
    assert request.scenario_id == case_id

    # 2. Mock LLM output using expected ground-truth directive interpretation
    raw_llm_output = json.dumps(
        {"directive_interpretation": expected_output["directive_interpretation"]}
    )

    # 3. Validate directives deterministically
    interpretations = validate_directives(raw_llm_output, request)
    assert len(interpretations) == len(request.operator_notes)

    # 4. Normalize constraints
    normalized_constraints = normalize_directives(request, interpretations)

    # 5. Solve optimization LP
    settings = get_settings()
    response = solve_optimization(request, normalized_constraints, settings, interpretations)

    # 6. Replay & verify solution independently
    validate_solution(request, normalized_constraints, response)

    # 7. Compare cost quality against official reference cost (tolerance <= 0.01 BDT)
    expected_cost = expected_output["total_cost_bdt"]
    assert abs(response.total_cost_bdt - expected_cost) <= 0.01, (
        f"Case {case_id} cost mismatch: solver returned {response.total_cost_bdt}, "
        f"reference expected {expected_cost}"
    )
