"""Canonical Pydantic v2 schemas for request, directives, and response."""

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class BatteryAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


class HourInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hour: Annotated[int, Field(ge=0, le=23)]
    demand_kwh: Annotated[float, Field(ge=0)]
    solar_kwh: Annotated[float, Field(ge=0)]
    tariff_bdt_per_kwh: Annotated[float, Field(ge=0)]


class BatteryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    capacity_kwh: Annotated[float, Field(gt=0)]
    initial_energy_kwh: Annotated[float, Field(ge=0)]
    minimum_energy_kwh: Annotated[float, Field(ge=0)]
    max_charge_kwh_per_hour: Annotated[float, Field(ge=0)]
    max_discharge_kwh_per_hour: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def validate_bounds(self) -> "BatteryInput":
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        if self.minimum_energy_kwh > self.initial_energy_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed initial_energy_kwh")
        return self


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    scenario_id: Annotated[str, Field(min_length=1)]
    operator_notes: Annotated[list[str], Field(min_length=1, max_length=3)]
    hours: Annotated[list[HourInput], Field(min_length=24, max_length=24)]
    battery: BatteryInput

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("scenario_id cannot be empty or whitespace only")
        return cleaned

    @field_validator("operator_notes")
    @classmethod
    def validate_notes(cls, notes: list[str]) -> list[str]:
        cleaned = [note.strip() for note in notes]
        if any(not note for note in cleaned):
            raise ValueError("Operator notes cannot be empty or whitespace only")
        return cleaned

    @field_validator("hours")
    @classmethod
    def validate_and_sort_hours(cls, hours: list[HourInput]) -> list[HourInput]:
        hour_numbers = [h.hour for h in hours]

        # The request may provide the 24 hourly entries in any order.
        # Validate coverage/uniqueness first, then normalize to ascending order
        # so downstream code can safely use list index == hour.
        if len(hour_numbers) != 24:
            raise ValueError("hours array must contain exactly 24 entries")
        if set(hour_numbers) != set(range(24)):
            raise ValueError("hours array must contain each hour from 0 through 23 exactly once")

        return sorted(hours, key=lambda h: h.hour)


class SolarReductionAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hours: list[Annotated[int, Field(ge=0, le=23)]]
    factor: Annotated[float, Field(ge=0.0, le=1.0)]


class MinimumBatteryReserveAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hours: list[Annotated[int, Field(ge=0, le=23)]]
    minimum_energy_kwh: Annotated[float, Field(ge=0.0)]


class NoChargeWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hours: list[Annotated[int, Field(ge=0, le=23)]]


class NoDischargeWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hours: list[Annotated[int, Field(ge=0, le=23)]]


class MaxGridWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hours: list[Annotated[int, Field(ge=0, le=23)]]
    max_grid_kwh: Annotated[float, Field(ge=0.0)]


StructuredAdjustment = Union[
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment,
    None,
]


class DirectiveInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    note_index: Annotated[int, Field(ge=0)]
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: StructuredAdjustment = None
    explanation: Annotated[str, Field(min_length=1)]

    @field_validator("explanation")
    @classmethod
    def validate_explanation(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("explanation cannot be empty or whitespace only")
        return cleaned

    @model_validator(mode="after")
    def validate_applies_and_adjustment(self) -> "DirectiveInterpretation":
        if self.directive_type == DirectiveType.NO_OP:
            if self.applies is not False:
                raise ValueError("applies must be false for no_op directive")
            if self.structured_adjustment is not None:
                raise ValueError("structured_adjustment must be null for no_op directive")
        else:
            if self.applies is not True:
                raise ValueError(f"applies must be true for non-no_op directive {self.directive_type.value}")
            if self.structured_adjustment is None:
                raise ValueError(f"structured_adjustment cannot be null for directive {self.directive_type.value}")
        return self


class LLMInterpretationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    directive_interpretation: list[DirectiveInterpretation]


class HourlyPlanRow(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    hour: Annotated[int, Field(ge=0, le=23)]
    grid_kwh: Annotated[float, Field(ge=0.0)]
    solar_used_kwh: Annotated[float, Field(ge=0.0)]
    battery_action: BatteryAction
    battery_kwh: Annotated[float, Field(ge=0.0)]
    battery_energy_after_kwh: Annotated[float, Field(ge=0.0)]


class OptimizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    scenario_id: str
    directive_interpretation: list[DirectiveInterpretation]
    hourly_plan: list[HourlyPlanRow]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
