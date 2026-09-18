"""Edge-case tests for the LP optimizer (app.optimizer.solver)."""

import pytest

from app.config import get_settings
from app.directives.normalizer import NormalizedConstraints
from app.errors import AppError
from app.optimizer.solver import solve_optimization
from app.optimizer.validator import validate_solution
from app.schemas import BatteryInput, HourInput, OptimizeRequest


def make_request(
    demand: float = 100.0,
    solar: float = 30.0,
    capacity: float = 200.0,
    initial: float = 100.0,
    minimum: float = 30.0,
    max_c: float = 50.0,
    max_d: float = 50.0,
) -> OptimizeRequest:
    hours = [
        HourInput(
            hour=h,
            demand_kwh=demand,
            solar_kwh=solar if 8 <= h <= 16 else 0.0,
            tariff_bdt_per_kwh=5.0 if h < 17 else 15.0,
        )
        for h in range(24)
    ]
    battery = BatteryInput(
        capacity_kwh=capacity,
        initial_energy_kwh=initial,
        minimum_energy_kwh=minimum,
        max_charge_kwh_per_hour=max_c,
        max_discharge_kwh_per_hour=max_d,
    )
    return OptimizeRequest(
        scenario_id="SOLVER-TEST",
        operator_notes=["Optimize"],
        hours=hours,
        battery=battery,
    )


def test_solver_infeasible_scenario_raises_409():
    # Demand is 100, solar is 0, battery cannot discharge, grid cap is 0
    req = make_request(demand=100.0, solar=0.0, max_d=0.0)
    constraints = NormalizedConstraints(
        effective_solar=[0.0] * 24,
        min_battery_reserve=[req.battery.minimum_energy_kwh] * 24,
        no_charge_hours=set(),
        no_discharge_hours=set(),
        max_grid_kwh=[0.0] * 24,  # Islanded with 0 generation & 0 discharge
    )
    settings = get_settings()

    with pytest.raises(AppError) as excinfo:
        solve_optimization(req, constraints, settings, [])
    assert excinfo.value.code == "infeasible"
    assert excinfo.value.status_code == 409


def test_solver_zero_demand_all_hours():
    req = make_request(demand=0.0, solar=20.0)
    constraints = NormalizedConstraints(
        effective_solar=[h.solar_kwh for h in req.hours],
        min_battery_reserve=[req.battery.minimum_energy_kwh] * 24,
        no_charge_hours=set(),
        no_discharge_hours=set(),
        max_grid_kwh=[None] * 24,
    )
    settings = get_settings()

    response = solve_optimization(req, constraints, settings, [])
    validate_solution(req, constraints, response)

    assert response.total_grid_kwh == 0.0
    assert response.total_cost_bdt == 0.0
    assert response.peak_grid_kwh == 0.0


def test_solver_zero_solar_all_hours():
    req = make_request(demand=80.0, solar=0.0)
    constraints = NormalizedConstraints(
        effective_solar=[0.0] * 24,
        min_battery_reserve=[req.battery.minimum_energy_kwh] * 24,
        no_charge_hours=set(),
        no_discharge_hours=set(),
        max_grid_kwh=[None] * 24,
    )
    settings = get_settings()

    response = solve_optimization(req, constraints, settings, [])
    validate_solution(req, constraints, response)

    assert response.total_grid_kwh > 0.0
    assert all(row.solar_used_kwh == 0.0 for row in response.hourly_plan)


def test_solver_battery_cannot_cycle():
    # max_charge = 0, max_discharge = 0
    req = make_request(max_c=0.0, max_d=0.0)
    constraints = NormalizedConstraints(
        effective_solar=[h.solar_kwh for h in req.hours],
        min_battery_reserve=[req.battery.minimum_energy_kwh] * 24,
        no_charge_hours=set(),
        no_discharge_hours=set(),
        max_grid_kwh=[None] * 24,
    )
    settings = get_settings()

    response = solve_optimization(req, constraints, settings, [])
    validate_solution(req, constraints, response)

    assert all(row.battery_action.value == "idle" for row in response.hourly_plan)
    assert all(row.battery_kwh == 0.0 for row in response.hourly_plan)
    assert all(row.battery_energy_after_kwh == 100.0 for row in response.hourly_plan)


def test_solver_initial_energy_at_minimum_reserve():
    # Battery starts at minimum reserve
    req = make_request(capacity=200.0, initial=30.0, minimum=30.0)
    constraints = NormalizedConstraints(
        effective_solar=[h.solar_kwh for h in req.hours],
        min_battery_reserve=[30.0] * 24,
        no_charge_hours=set(),
        no_discharge_hours=set(),
        max_grid_kwh=[None] * 24,
    )
    settings = get_settings()

    response = solve_optimization(req, constraints, settings, [])
    validate_solution(req, constraints, response)

    assert response.hourly_plan[23].battery_energy_after_kwh == 30.0


def test_solver_initial_energy_at_capacity():
    # Battery starts at full capacity
    req = make_request(capacity=200.0, initial=200.0, minimum=50.0)
    constraints = NormalizedConstraints(
        effective_solar=[h.solar_kwh for h in req.hours],
        min_battery_reserve=[50.0] * 24,
        no_charge_hours=set(),
        no_discharge_hours=set(),
        max_grid_kwh=[None] * 24,
    )
    settings = get_settings()

    response = solve_optimization(req, constraints, settings, [])
    validate_solution(req, constraints, response)

    assert response.hourly_plan[23].battery_energy_after_kwh == 200.0
