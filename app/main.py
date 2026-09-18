"""FastAPI application entry point for GridWise SmartGrid AI backend."""

import logging
import time
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.directives.normalizer import normalize_directives
from app.directives.validator import validate_directives
from app.errors import AppError
from app.llm.interpreter import LLMInterpreter
from app.optimizer.solver import solve_optimization
from app.optimizer.validator import validate_solution
from app.schemas import OptimizeRequest, OptimizeResponse

_startup_settings = get_settings()
logging.basicConfig(
    level=getattr(logging, _startup_settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gridwise")

app = FastAPI(
    title="StackFellas GridWise SmartGrid AI Backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Official contract specifies HTTP 400 for malformed JSON or structurally invalid requests
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {
                "code": "invalid_request",
                "message": "The request body is malformed or structurally invalid.",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_error",
                "message": "An internal server error occurred.",
                "details": [],
            }
        },
    )


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/optimize-energy", status_code=status.HTTP_200_OK, response_model=OptimizeResponse)
async def optimize_energy(req: OptimizeRequest) -> OptimizeResponse:
    settings = get_settings()
    deadline = time.monotonic() + settings.request_timeout_seconds

    # 1. LLM Interpretation
    interpreter = LLMInterpreter(settings)
    raw_llm_output = interpreter.interpret(req, deadline=deadline)

    # 2. Deterministic Validation
    interpretations = validate_directives(raw_llm_output, req)

    # 3. Constraint Normalization
    normalized_constraints = normalize_directives(req, interpretations)

    # 4. LP Optimization
    response = solve_optimization(
        req, normalized_constraints, settings, interpretations, deadline=deadline
    )

    # 5. Independent Solution Replay Verification
    validate_solution(req, normalized_constraints, response)

    return response
