"""HTTP LLM client for chat-completions-compatible API endpoints."""

import logging
import time

import httpx

from app.config import Settings
from app.errors import AppError
from app.llm.prompt import build_messages
from app.schemas import OptimizeRequest

logger = logging.getLogger(__name__)
MAX_OUTPUT_CHARS = 32_000


class LLMInterpreter:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def interpret(self, request: OptimizeRequest, deadline: float | None = None) -> str:
        settings = self.settings
        if not (
            settings.llm_api_url
            and settings.llm_model
            and settings.llm_api_key.get_secret_value().strip()
        ):
            raise AppError(
                "llm_not_configured",
                "Set LLM_API_URL, LLM_API_KEY, and LLM_MODEL before optimizing.",
                503,
            )
        timeout = settings.llm_timeout_seconds
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
            if timeout <= 0:
                raise AppError("request_timeout", "The optimization request exceeded its time limit.", 504)
        try:
            with httpx.Client(
                timeout=timeout,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    settings.llm_api_url,
                    headers={"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"},
                    json={
                        "model": settings.llm_model,
                        "messages": build_messages(request),
                        "temperature": 0,
                        "max_tokens": 4096,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("LLM provider request failed: %s", type(exc).__name__)
            raise AppError("llm_unavailable", "The LLM provider request failed.", 502) from exc

        try:
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") not in {"stop", "length", None}:
                raise ValueError(f"Unexpected finish_reason: {choice.get('finish_reason')}")
            message = choice["message"]
            if message.get("refusal") or message.get("tool_calls"):
                raise ValueError("Unexpected completion format")
            content = message["content"]
            if not isinstance(content, str) or not content.strip() or len(content) > MAX_OUTPUT_CHARS:
                raise ValueError("Invalid completion content length")
            return content
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            raise AppError(
                "invalid_llm_output", "The LLM provider returned an invalid completion.", 502
            ) from exc
