"""Unit tests for independent solution replay validator (app.optimizer.validator)."""

import pytest

from app.directives.normalizer import NormalizedConstraints
from app.errors import AppError
from app.optimizer.validator import validate_solution
from app.schemas import (
    BatteryAction,
    BatteryInput,
    HourInput,
    HourlyPlanRow,
    OptimizeRequest,
    OptimizeResponse,
)


def make_valid_scenario():
    hours = [
        HourInput(
            hour=h,
            demand_kwh=100.0,
            solar_kwh=20.0,
            tariff_bdt_per_kwh=5.0,
        )
        for h in range(24)
    ]
    battery = BatteryInput(
        capacity_kwh=200.0,
        initial_energy_kwh=100.0,
        minimum_energy_kwh=30.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )
    request = OptimizeRequest(
        scenario_id="TEST-SOL-01",
        operator_notes=["Note 1"],
        hours=hours,
        battery=battery,
    )
    constraints = NormalizedConstraints(
        effective_solar=[20.0] * 24,
        min_battery_reserve=[30.0] * 24,
        no_charge_hours=set(),
        no_discharge_hours=set(),
        max_grid_kwh=[None] * 24,
    )
    # A simple valid plan: solar=20, grid=80, battery idle, energy=100
    hourly_plan = [
        HourlyPlanRow(
            hour=h,
            grid_kwh=80.0,
            solar_used_kwh=20.0,
            battery_action=BatteryAction.IDLE,
            battery_kwh=0.0,
            battery_energy_after_kwh=100.0,
        )
        for h in range(24)
    ]
    response = OptimizeResponse(
        scenario_id="TEST-SOL-01",
        directive_interpretation=[],
        hourly_plan=hourly_plan,
        total_grid_kwh=80.0 * 24,
        total_cost_bdt=80.0 * 24 * 5.0,
        peak_grid_kwh=80.0,
        plan_summary="Valid schedule summary.",
    )
    return request, constraints, response


def test_valid_solution_passes():
    request, constraints, response = make_valid_scenario()
    validate_solution(request, constraints, response)


def test_hourly_plan_length_invalid():
    request, constraints, response = make_valid_scenario()
    response.hourly_plan = response.hourly_plan[:20]
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "24 entries" in excinfo.value.message


def test_hourly_plan_hour_order_mismatch():
    request, constraints, response = make_valid_scenario()
    response.hourly_plan[0].hour = 1
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "Expected hour 0" in excinfo.value.message


def test_negative_values_rejected():
    request, constraints, response = make_valid_scenario()
    response.hourly_plan[0].grid_kwh = -1.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "Negative value" in excinfo.value.message


def test_solar_used_exceeds_effective_solar():
    request, constraints, response = make_valid_scenario()
    response.hourly_plan[0].solar_used_kwh = 25.0  # effective is 20.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "exceeds effective solar" in excinfo.value.message


def test_idle_battery_with_non_zero_kwh_rejected():
    request, constraints, response = make_valid_scenario()
    response.hourly_plan[0].battery_action = BatteryAction.IDLE
    response.hourly_plan[0].battery_kwh = 5.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "battery_kwh must be 0 for IDLE" in excinfo.value.message


def test_charge_rate_exceeds_maximum():
    request, constraints, response = make_valid_scenario()
    response.hourly_plan[0].battery_action = BatteryAction.CHARGE
    response.hourly_plan[0].battery_kwh = 60.0  # max is 50.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "Charge rate" in excinfo.value.message


def test_discharge_rate_exceeds_maximum():
    request, constraints, response = make_valid_scenario()
    response.hourly_plan[0].battery_action = BatteryAction.DISCHARGE
    response.hourly_plan[0].battery_kwh = 60.0  # max is 50.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "Discharge rate" in excinfo.value.message


def test_charge_during_no_charge_window_rejected():
    request, constraints, response = make_valid_scenario()
    constraints.no_charge_hours = {0}
    response.hourly_plan[0].battery_action = BatteryAction.CHARGE
    response.hourly_plan[0].battery_kwh = 10.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "Charging forbidden" in excinfo.value.message


def test_discharge_during_no_discharge_window_rejected():
    request, constraints, response = make_valid_scenario()
    constraints.no_discharge_hours = {0}
    response.hourly_plan[0].battery_action = BatteryAction.DISCHARGE
    response.hourly_plan[0].battery_kwh = 10.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "Discharging forbidden" in excinfo.value.message


def test_grid_exceeds_grid_cap():
    request, constraints, response = make_valid_scenario()
    constraints.max_grid_kwh[0] = 50.0  # grid is 80.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "exceeds grid cap" in excinfo.value.message


def test_energy_balance_violation():
    request, constraints, response = make_valid_scenario()
    # supply: 50 grid + 20 solar = 70 != 100 demand
    response.hourly_plan[0].grid_kwh = 50.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "Energy balance violation" in excinfo.value.message


def test_battery_state_transition_mismatch():
    request, constraints, response = make_valid_scenario()
    # Action charge 10 kWh, but energy_after reported as 120 instead of 110
    response.hourly_plan[0].battery_action = BatteryAction.CHARGE
    response.hourly_plan[0].battery_kwh = 10.0
    response.hourly_plan[0].grid_kwh = 90.0  # demand 100 + charge 10 = supply 90 grid + 20 solar = 110
    response.hourly_plan[0].battery_energy_after_kwh = 120.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "Battery state transition mismatch" in excinfo.value.message


def test_battery_energy_below_reserve():
    request, constraints, response = make_valid_scenario()
    # At hour 0, discharge 10 kWh: initial 100 -> energy_after 90 kWh
    # But min_battery_reserve is set to 95 kWh
    response.hourly_plan[0].battery_action = BatteryAction.DISCHARGE
    response.hourly_plan[0].battery_kwh = 10.0
    response.hourly_plan[0].grid_kwh = 70.0  # 70 grid + 20 solar + 10 discharge = 100 demand
    response.hourly_plan[0].battery_energy_after_kwh = 90.0
    constraints.min_battery_reserve[0] = 95.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "out of bounds" in excinfo.value.message


def test_battery_energy_above_capacity():
    request, constraints, response = make_valid_scenario()
    # At hour 0, charge 10 kWh: initial 100 -> energy_after 110 kWh
    # But capacity is set to 105 kWh
    response.hourly_plan[0].battery_action = BatteryAction.CHARGE
    response.hourly_plan[0].battery_kwh = 10.0
    response.hourly_plan[0].grid_kwh = 90.0  # 90 grid + 20 solar = 100 demand + 10 charge
    response.hourly_plan[0].battery_energy_after_kwh = 110.0
    request.battery.capacity_kwh = 105.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "out of bounds" in excinfo.value.message


def test_end_of_day_neutrality_violation():
    request, constraints, response = make_valid_scenario()
    # Charge 10 kWh at hour 0, and remain at 110 kWh for the rest of the day
    # All transitions are consistent, but end of day is 110 != initial 100
    response.hourly_plan[0].battery_action = BatteryAction.CHARGE
    response.hourly_plan[0].battery_kwh = 10.0
    response.hourly_plan[0].grid_kwh = 90.0  # 90 + 20 = 100 + 10
    response.hourly_plan[0].battery_energy_after_kwh = 110.0

    for h in range(1, 24):
        response.hourly_plan[h].battery_action = BatteryAction.IDLE
        response.hourly_plan[h].battery_kwh = 0.0
        response.hourly_plan[h].grid_kwh = 80.0
        response.hourly_plan[h].battery_energy_after_kwh = 110.0

    # Match the totals so it doesn't fail on totals check first
    total_g = 90.0 + 80.0 * 23
    response.total_grid_kwh = total_g
    response.total_cost_bdt = total_g * 5.0
    response.peak_grid_kwh = 90.0

    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "neutrality violated" in excinfo.value.message


def test_totals_disagree_with_recalculated():
    request, constraints, response = make_valid_scenario()
    # Mismatch in total_grid_kwh
    response.total_grid_kwh = 9999.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "total_grid_kwh" in excinfo.value.message

    # Mismatch in total_cost_bdt
    response, _, _ = make_valid_scenario()
    _, _, response = make_valid_scenario()
    response.total_cost_bdt = 1.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "total_cost_bdt" in excinfo.value.message

    # Mismatch in peak_grid_kwh
    _, _, response = make_valid_scenario()
    response.peak_grid_kwh = 5.0
    with pytest.raises(AppError) as excinfo:
        validate_solution(request, constraints, response)
    assert excinfo.value.code == "invalid_solution"
    assert "peak_grid_kwh" in excinfo.value.message
