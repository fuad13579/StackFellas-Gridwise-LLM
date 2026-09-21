"""Regression tests for the API request deadline."""

import time

import pytest

from app.config import Settings
from app.directives.normalizer import NormalizedConstraints
from app.errors import AppError
from app.llm.interpreter import LLMInterpreter
from app.optimizer.solver import solve_optimization


def test_llm_interpreter_not_configured_is_http_500():
    with pytest.raises(AppError) as excinfo:
        LLMInterpreter(Settings()).interpret(None)

    assert excinfo.value.code == "llm_not_configured"
    assert excinfo.value.status_code == 500


def test_llm_interpreter_rejects_an_expired_request_deadline():
    settings = Settings(
        llm_api_url="https://example.com/v1/chat/completions",
        llm_api_key="test-key",
        llm_model="test-model",
    )

    with pytest.raises(AppError, match="exceeded its time limit") as excinfo:
        LLMInterpreter(settings).interpret(None, deadline=time.monotonic() - 1)

    assert excinfo.value.code == "request_timeout"
    assert excinfo.value.status_code == 500


def test_solver_rejects_an_expired_request_deadline():
    with pytest.raises(AppError, match="exceeded its time limit") as excinfo:
        solve_optimization(
            request=None,
            constraints=NormalizedConstraints(effective_solar=[], min_battery_reserve=[]),
            settings=Settings(),
            interpretations=[],
            deadline=time.monotonic() - 1,
        )

    assert excinfo.value.code == "request_timeout"
    assert excinfo.value.status_code == 500
