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


def test_battery_minimum_exceeds_initial_energy():
    with pytest.raises(ValidationError):
        BatteryInput(
            capacity_kwh=200.0,
            initial_energy_kwh=30.0,
            minimum_energy_kwh=40.0,
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


@pytest.mark.parametrize("field", ["demand_kwh", "solar_kwh", "tariff_bdt_per_kwh"])
def test_hour_rejects_non_finite_values(field):
    values = {
        "hour": 0,
        "demand_kwh": 100.0,
        "solar_kwh": 50.0,
        "tariff_bdt_per_kwh": 5.0,
    }
    values[field] = float("nan")

    with pytest.raises(ValidationError):
        HourInput(**values)


def test_request_rejects_extra_fields():
    values = {
        "scenario_id": "TEST-06",
        "operator_notes": ["Note"],
        "hours": make_valid_hours(),
        "battery": make_valid_battery(),
        "unexpected": True,
    }

    with pytest.raises(ValidationError):
        OptimizeRequest(**values)


@pytest.mark.parametrize("bad_scenario_id", ["", "   ", "\t\n  "])
def test_empty_or_whitespace_scenario_id_is_rejected(bad_scenario_id):
    with pytest.raises(ValidationError):
        OptimizeRequest(
            scenario_id=bad_scenario_id,
            operator_notes=["Valid note"],
            hours=make_valid_hours(),
            battery=make_valid_battery(),
        )


def test_operator_notes_zero_or_exceeds_max():
    # 0 notes
    with pytest.raises(ValidationError):
        OptimizeRequest(
            scenario_id="TEST-NOTES-0",
            operator_notes=[],
            hours=make_valid_hours(),
            battery=make_valid_battery(),
        )

    # 4 notes (max is 3)
    with pytest.raises(ValidationError):
        OptimizeRequest(
            scenario_id="TEST-NOTES-4",
            operator_notes=["Note 1", "Note 2", "Note 3", "Note 4"],
            hours=make_valid_hours(),
            battery=make_valid_battery(),
        )


@pytest.mark.parametrize("capacity", [0.0, -10.0, -0.001])
def test_battery_capacity_must_be_strictly_positive(capacity):
    with pytest.raises(ValidationError):
        BatteryInput(
            capacity_kwh=capacity,
            initial_energy_kwh=0.0,
            minimum_energy_kwh=0.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0,
        )


@pytest.mark.parametrize(
    ("field", "bad_val"),
    [
        ("initial_energy_kwh", -1.0),
        ("minimum_energy_kwh", -1.0),
        ("max_charge_kwh_per_hour", -0.01),
        ("max_discharge_kwh_per_hour", -0.01),
    ],
)
def test_battery_rejects_negative_parameters(field, bad_val):
    params = {
        "capacity_kwh": 200.0,
        "initial_energy_kwh": 100.0,
        "minimum_energy_kwh": 30.0,
        "max_charge_kwh_per_hour": 50.0,
        "max_discharge_kwh_per_hour": 50.0,
    }
    params[field] = bad_val
    with pytest.raises(ValidationError):
        BatteryInput(**params)


@pytest.mark.parametrize(
    "field",
    [
        "capacity_kwh",
        "initial_energy_kwh",
        "minimum_energy_kwh",
        "max_charge_kwh_per_hour",
        "max_discharge_kwh_per_hour",
    ],
)
def test_battery_rejects_non_finite_values(field):
    params = {
        "capacity_kwh": 200.0,
        "initial_energy_kwh": 100.0,
        "minimum_energy_kwh": 30.0,
        "max_charge_kwh_per_hour": 50.0,
        "max_discharge_kwh_per_hour": 50.0,
    }
    params[field] = float("nan")
    with pytest.raises(ValidationError):
        BatteryInput(**params)

    params[field] = float("inf")
    with pytest.raises(ValidationError):
        BatteryInput(**params)


def test_battery_rejects_extra_fields():
    with pytest.raises(ValidationError):
        BatteryInput(
            capacity_kwh=200.0,
            initial_energy_kwh=100.0,
            minimum_energy_kwh=30.0,
            max_charge_kwh_per_hour=50.0,
            max_discharge_kwh_per_hour=50.0,
            extra_field=123,
        )


def test_battery_valid_boundary_cases():
    # minimum == initial == capacity
    b1 = BatteryInput(
        capacity_kwh=100.0,
        initial_energy_kwh=100.0,
        minimum_energy_kwh=100.0,
        max_charge_kwh_per_hour=0.0,
        max_discharge_kwh_per_hour=0.0,
    )
    assert b1.initial_energy_kwh == 100.0
    assert b1.minimum_energy_kwh == 100.0

    # minimum == 0, initial == 0
    b2 = BatteryInput(
        capacity_kwh=100.0,
        initial_energy_kwh=0.0,
        minimum_energy_kwh=0.0,
        max_charge_kwh_per_hour=50.0,
        max_discharge_kwh_per_hour=50.0,
    )
    assert b2.initial_energy_kwh == 0.0


@pytest.mark.parametrize("bad_hour", [-1, 24, 100])
def test_hour_out_of_range_rejected(bad_hour):
    with pytest.raises(ValidationError):
        HourInput(
            hour=bad_hour,
            demand_kwh=100.0,
            solar_kwh=50.0,
            tariff_bdt_per_kwh=5.0,
        )


@pytest.mark.parametrize(
    ("field", "bad_val"),
    [
        ("demand_kwh", -0.01),
        ("solar_kwh", -1.0),
        ("tariff_bdt_per_kwh", -5.0),
    ],
)
def test_hour_negative_values_rejected(field, bad_val):
    params = {
        "hour": 5,
        "demand_kwh": 100.0,
        "solar_kwh": 50.0,
        "tariff_bdt_per_kwh": 5.0,
    }
    params[field] = bad_val
    with pytest.raises(ValidationError):
        HourInput(**params)


def test_hour_rejects_extra_fields():
    with pytest.raises(ValidationError):
        HourInput(
            hour=0,
            demand_kwh=100.0,
            solar_kwh=50.0,
            tariff_bdt_per_kwh=5.0,
            unknown_metric=99.9,
        )


def test_hour_valid_zero_values():
    h = HourInput(
        hour=0,
        demand_kwh=0.0,
        solar_kwh=0.0,
        tariff_bdt_per_kwh=0.0,
    )
    assert h.demand_kwh == 0.0
    assert h.solar_kwh == 0.0
    assert h.tariff_bdt_per_kwh == 0.0

