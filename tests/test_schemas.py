"""Unit tests for Pydantic schema validation."""

import pytest
from pydantic import ValidationError

from app.schemas import BatteryInput, HourInput, OptimizeRequest


def make_valid_hours():
    return [
        HourInput(
            hour=h,
            demand_kwh=100.0,
            solar_kwh=50.0 if 8 <= h <= 16 else 0.0,
            tariff_bdt_per_kwh=5.0 if h < 18 else 10.0,
        )
        for h in range(24)
    ]


def make_valid_battery():
    return BatteryInput(
        capacity_kwh=200.0,
        initial_energy_kwh=100.0,
        minimum_energy_kwh=30.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )


def test_valid_request():
    req = OptimizeRequest(
        scenario_id="TEST-01",
        operator_notes=["Do not charge battery between 2 PM and 4 PM."],
        hours=make_valid_hours(),
        battery=make_valid_battery(),
    )
    assert req.scenario_id == "TEST-01"
    assert len(req.hours) == 24


def test_invalid_hours_count():
    hours = make_valid_hours()[:20]
    with pytest.raises(ValidationError):
        OptimizeRequest(
            scenario_id="TEST-02",
            operator_notes=["Note"],
            hours=hours,
            battery=make_valid_battery(),
        )


def test_empty_operator_notes():
    with pytest.raises(ValidationError):
        OptimizeRequest(
            scenario_id="TEST-03",
            operator_notes=["   "],
            hours=make_valid_hours(),
            battery=make_valid_battery(),
        )


def test_battery_initial_exceeds_capacity():
    with pytest.raises(ValidationError):
        BatteryInput(
            capacity_kwh=100.0,
            initial_energy_kwh=150.0,
            minimum_energy_kwh=10.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0,
        )


def test_unsorted_hours_are_accepted_and_sorted():
    hours = list(reversed(make_valid_hours()))

    req = OptimizeRequest(
        scenario_id="TEST-04",
        operator_notes=["Note"],
        hours=hours,
        battery=make_valid_battery(),
    )

    assert [entry.hour for entry in req.hours] == list(range(24))


def test_duplicate_hour_is_rejected():
    hours = make_valid_hours()
    hours[-1] = HourInput(
        hour=22,
        demand_kwh=100.0,
        solar_kwh=0.0,
        tariff_bdt_per_kwh=10.0,
    )

    with pytest.raises(ValidationError):
        OptimizeRequest(
            scenario_id="TEST-05",
            operator_notes=["Note"],
            hours=hours,
            battery=make_valid_battery(),
        )

