"""Environment configuration; importing the app never requires credentials."""

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    llm_api_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)
    solver_time_limit_seconds: float = Field(default=10, gt=0, le=120)
    request_timeout_seconds: float = Field(default=30, gt=0, le=30)
    log_level: str = "INFO"

    @field_validator("llm_api_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if value:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
            ):
                raise ValueError("LLM_API_URL must be an HTTP(S) endpoint without credentials")
        return value

    @field_validator("llm_model")
    @classmethod
    def strip_model(cls, value: str) -> str:
        return value.strip()

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Invalid LOG_LEVEL")
        return value


@lru_cache
def get_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    values = {
        field: os.environ[field.upper()]
        for field in Settings.model_fields
        if field.upper() in os.environ
    }
    return Settings(**values)
