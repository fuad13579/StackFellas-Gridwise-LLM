"""Deterministic guardrails for LLM output directive interpretation validation."""

import json
from typing import Any

from pydantic import ValidationError

from app.errors import AppError
from app.schemas import (
    DirectiveInterpretation,
    DirectiveType,
    LLMInterpretationOutput,
    MaxGridWindowAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    OptimizeRequest,
    SolarReductionAdjustment,
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def validate_directive_hours(hours: list[int]) -> None:
    if not hours:
        raise ValueError("Directive hours list cannot be empty")
    if len(hours) != len(set(hours)):
        raise ValueError("Directive hours must be unique integers")
    if hours != sorted(hours):
        raise ValueError("Directive hours must be in strictly ascending order")
    if any(h < 0 or h > 23 for h in hours):
        raise ValueError("Directive hours must be integers between 0 and 23")


def validate_directives(raw_output: str, request: OptimizeRequest) -> list[DirectiveInterpretation]:
    """Deterministically validates LLM JSON output against strict official rules."""
    try:
        if not isinstance(raw_output, str) or len(raw_output) > 32_000:
            raise ValueError("Invalid output size")

        data = json.loads(
            raw_output,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )

        # Pre-validation normalization: hoist explanation if LLM placed it inside structured_adjustment
        if isinstance(data, dict) and isinstance(data.get("directive_interpretation"), list):
            for item in data["directive_interpretation"]:
                if isinstance(item, dict) and isinstance(item.get("structured_adjustment"), dict):
                    adj_dict = item["structured_adjustment"]
                    if "explanation" in adj_dict:
                        exp = adj_dict.pop("explanation")
                        if not item.get("explanation"):
                            item["explanation"] = exp

        parsed = LLMInterpretationOutput.model_validate(data)
        interpretations = parsed.directive_interpretation

        expected_count = len(request.operator_notes)
        if len(interpretations) != expected_count:
            raise ValueError(
                f"Expected exactly {expected_count} directive interpretations, got {len(interpretations)}"
            )

        note_indices = [item.note_index for item in interpretations]
        if note_indices != list(range(expected_count)):
            raise ValueError(
                f"directive_interpretation must be returned in note_index order 0..{expected_count-1}"
            )

        capacity = request.battery.capacity_kwh

        for item in interpretations:
            if item.directive_type == DirectiveType.NO_OP:
                if item.applies is not False or item.structured_adjustment is not None:
                    raise ValueError("no_op directive must have applies=false and structured_adjustment=null")
            else:
                if item.applies is not True or item.structured_adjustment is None:
                    raise ValueError(f"{item.directive_type.value} must have applies=true and non-null structured_adjustment")

                adj = item.structured_adjustment
                validate_directive_hours(adj.hours)

                if item.directive_type == DirectiveType.SOLAR_REDUCTION:
                    if not isinstance(adj, SolarReductionAdjustment):
                        raise ValueError("solar_reduction requires structured_adjustment with factor and hours")
                    if not (0.0 <= adj.factor <= 1.0):
                        raise ValueError(f"Solar reduction factor must be between 0.0 and 1.0, got {adj.factor}")

                elif item.directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE:
                    if not isinstance(adj, MinimumBatteryReserveAdjustment):
                        raise ValueError("minimum_battery_reserve requires structured_adjustment with minimum_energy_kwh and hours")
                    if adj.minimum_energy_kwh < 0.0 or adj.minimum_energy_kwh > capacity:
                        raise ValueError(
                            f"Minimum battery reserve {adj.minimum_energy_kwh} must be between 0 and battery capacity {capacity}"
                        )

                elif item.directive_type == DirectiveType.MAX_GRID_WINDOW:
                    if not isinstance(adj, MaxGridWindowAdjustment):
                        raise ValueError("max_grid_window requires structured_adjustment with max_grid_kwh and hours")
                    if adj.max_grid_kwh < 0.0:
                        raise ValueError(f"max_grid_kwh must be non-negative, got {adj.max_grid_kwh}")

                elif item.directive_type in (DirectiveType.NO_CHARGE_WINDOW, DirectiveType.NO_DISCHARGE_WINDOW):
                    if not isinstance(adj, (NoChargeWindowAdjustment, NoDischargeWindowAdjustment)):
                        raise ValueError(f"{item.directive_type.value} requires structured_adjustment with hours")

        return interpretations

    except (ValidationError, ValueError, TypeError, RecursionError, KeyError) as exc:
        raise AppError(
            "invalid_llm_output",
            f"The LLM output failed directive validation: {exc}",
            502,
        ) from exc
