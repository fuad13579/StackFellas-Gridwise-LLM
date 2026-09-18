"""Unit tests for deterministic directive normalization."""

from app.directives.normalizer import normalize_directives
from app.schemas import (
    BatteryInput,
    DirectiveInterpretation,
    DirectiveType,
    HourInput,
    OptimizeRequest,
    SolarReductionAdjustment,
)


def test_overlapping_solar_reductions_keep_the_more_restrictive_limit():
    request = OptimizeRequest(
        scenario_id="S-OVERLAP",
        operator_notes=["Reduce solar during the morning.", "Reduce solar further."],
        hours=[
            HourInput(hour=h, demand_kwh=100.0, solar_kwh=100.0, tariff_bdt_per_kwh=5.0)
            for h in range(24)
        ],
        battery=BatteryInput(
            capacity_kwh=200.0,
            initial_energy_kwh=100.0,
            minimum_energy_kwh=20.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0,
        ),
    )
    interpretations = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type=DirectiveType.SOLAR_REDUCTION,
            structured_adjustment=SolarReductionAdjustment(hours=[10], factor=0.2),
            explanation="First reduction.",
        ),
        DirectiveInterpretation(
            note_index=1,
            applies=True,
            directive_type=DirectiveType.SOLAR_REDUCTION,
            structured_adjustment=SolarReductionAdjustment(hours=[10], factor=0.8),
            explanation="Second reduction.",
        ),
    ]

    constraints = normalize_directives(request, interpretations)

    assert constraints.effective_solar[10] == 20.0