"""Unit tests for deterministic directive normalization."""

from app.directives.normalizer import normalize_directives
from app.schemas import (
    BatteryInput,
    DirectiveInterpretation,
    DirectiveType,
    HourInput,
    MaxGridWindowAdjustment,
    NoChargeWindowAdjustment,
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


def test_overlapping_windows_keep_restrictions_and_zero_solar():
    request = OptimizeRequest(
        scenario_id="S-EDGE",
        operator_notes=["Do not charge at hour 5.", "Limit grid import further."],
        hours=[
            HourInput(hour=h, demand_kwh=100.0, solar_kwh=80.0, tariff_bdt_per_kwh=5.0)
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
            directive_type=DirectiveType.NO_CHARGE_WINDOW,
            structured_adjustment=NoChargeWindowAdjustment(hours=[5]),
            explanation="Charging is unavailable at hour 5.",
        ),
        DirectiveInterpretation(
            note_index=1,
            applies=True,
            directive_type=DirectiveType.MAX_GRID_WINDOW,
            structured_adjustment=MaxGridWindowAdjustment(hours=[5, 6], max_grid_kwh=0.0),
            explanation="Grid import is unavailable during the window.",
        ),
    ]

    constraints = normalize_directives(request, interpretations)

    assert constraints.no_charge_hours == {5}
    assert constraints.max_grid_kwh[5] == 0.0
    assert constraints.max_grid_kwh[6] == 0.0


def test_overlapping_minimum_battery_reserves_keeps_higher_reserve():
    request = OptimizeRequest(
        scenario_id="S-RESERVE",
        operator_notes=["Reserve 60 kWh.", "Reserve 120 kWh."],
        hours=[
            HourInput(hour=h, demand_kwh=100.0, solar_kwh=50.0, tariff_bdt_per_kwh=5.0)
            for h in range(24)
        ],
        battery=BatteryInput(
            capacity_kwh=200.0,
            initial_energy_kwh=100.0,
            minimum_energy_kwh=30.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0,
        ),
    )
    interpretations = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE,
            structured_adjustment={"hours": [15], "minimum_energy_kwh": 60.0},
            explanation="First reserve.",
        ),
        DirectiveInterpretation(
            note_index=1,
            applies=True,
            directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE,
            structured_adjustment={"hours": [15], "minimum_energy_kwh": 120.0},
            explanation="Second reserve.",
        ),
    ]

    constraints = normalize_directives(request, interpretations)
    assert constraints.min_battery_reserve[15] == 120.0
    # Other hours should remain at base minimum_energy_kwh (30.0)
    assert constraints.min_battery_reserve[0] == 30.0


def test_overlapping_max_grid_windows_keeps_stricter_cap():
    request = OptimizeRequest(
        scenario_id="S-GRID-CAP",
        operator_notes=["Cap grid at 100", "Cap grid at 50", "Zero grid import"],
        hours=[
            HourInput(hour=h, demand_kwh=100.0, solar_kwh=50.0, tariff_bdt_per_kwh=5.0)
            for h in range(24)
        ],
        battery=BatteryInput(
            capacity_kwh=200.0,
            initial_energy_kwh=100.0,
            minimum_energy_kwh=30.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0,
        ),
    )
    interpretations = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type=DirectiveType.MAX_GRID_WINDOW,
            structured_adjustment={"hours": [18], "max_grid_kwh": 100.0},
            explanation="Cap 100.",
        ),
        DirectiveInterpretation(
            note_index=1,
            applies=True,
            directive_type=DirectiveType.MAX_GRID_WINDOW,
            structured_adjustment={"hours": [18], "max_grid_kwh": 50.0},
            explanation="Cap 50.",
        ),
        DirectiveInterpretation(
            note_index=2,
            applies=True,
            directive_type=DirectiveType.MAX_GRID_WINDOW,
            structured_adjustment={"hours": [18], "max_grid_kwh": 0.0},
            explanation="Cap 0.",
        ),
    ]

    constraints = normalize_directives(request, interpretations)
    assert constraints.max_grid_kwh[18] == 0.0
    assert constraints.max_grid_kwh[0] is None


def test_no_charge_and_no_discharge_simultaneous_windows():
    request = OptimizeRequest(
        scenario_id="S-SIMULTANEOUS",
        operator_notes=["No charge at 12", "No discharge at 12"],
        hours=[
            HourInput(hour=h, demand_kwh=100.0, solar_kwh=50.0, tariff_bdt_per_kwh=5.0)
            for h in range(24)
        ],
        battery=BatteryInput(
            capacity_kwh=200.0,
            initial_energy_kwh=100.0,
            minimum_energy_kwh=30.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0,
        ),
    )
    interpretations = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type=DirectiveType.NO_CHARGE_WINDOW,
            structured_adjustment={"hours": [12]},
            explanation="No charge.",
        ),
        DirectiveInterpretation(
            note_index=1,
            applies=True,
            directive_type=DirectiveType.NO_DISCHARGE_WINDOW,
            structured_adjustment={"hours": [12]},
            explanation="No discharge.",
        ),
    ]

    constraints = normalize_directives(request, interpretations)
    assert 12 in constraints.no_charge_hours
    assert 12 in constraints.no_discharge_hours


def test_no_op_and_empty_directives_preserve_base_constraints():
    request = OptimizeRequest(
        scenario_id="S-NOOP",
        operator_notes=["Menu note"],
        hours=[
            HourInput(hour=h, demand_kwh=100.0, solar_kwh=50.0, tariff_bdt_per_kwh=5.0)
            for h in range(24)
        ],
        battery=BatteryInput(
            capacity_kwh=200.0,
            initial_energy_kwh=100.0,
            minimum_energy_kwh=30.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0,
        ),
    )
    interpretations = [
        DirectiveInterpretation(
            note_index=0,
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation="Cafeteria menu note.",
        ),
    ]

    constraints = normalize_directives(request, interpretations)
    assert constraints.effective_solar == [50.0] * 24
    assert constraints.min_battery_reserve == [30.0] * 24
    assert constraints.no_charge_hours == set()
    assert constraints.no_discharge_hours == set()
    assert constraints.max_grid_kwh == [None] * 24

    # Empty list
    empty_constraints = normalize_directives(request, [])
    assert empty_constraints.effective_solar == [50.0] * 24
    assert empty_constraints.min_battery_reserve == [30.0] * 24