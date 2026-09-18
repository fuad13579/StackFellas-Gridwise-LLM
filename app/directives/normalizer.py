"""Convert validated directive interpretations into normalized numerical LP constraints."""

from dataclasses import dataclass, field

from app.schemas import (
    DirectiveInterpretation,
    DirectiveType,
    MaxGridWindowAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    OptimizeRequest,
    SolarReductionAdjustment,
)


@dataclass
class NormalizedConstraints:
    effective_solar: list[float]
    min_battery_reserve: list[float]
    no_charge_hours: set[int] = field(default_factory=set)
    no_discharge_hours: set[int] = field(default_factory=set)
    max_grid_kwh: list[float | None] = field(default_factory=lambda: [None] * 24)


def normalize_directives(
    request: OptimizeRequest, interpretations: list[DirectiveInterpretation]
) -> NormalizedConstraints:
    base_solar = [h.solar_kwh for h in request.hours]
    effective_solar = list(base_solar)

    base_min_reserve = request.battery.minimum_energy_kwh
    min_battery_reserve = [base_min_reserve] * 24

    no_charge_hours: set[int] = set()
    no_discharge_hours: set[int] = set()
    max_grid_kwh: list[float | None] = [None] * 24

    for item in interpretations:
        if not item.applies or item.directive_type == DirectiveType.NO_OP:
            continue

        adj = item.structured_adjustment
        if adj is None:
            continue

        if item.directive_type == DirectiveType.SOLAR_REDUCTION:
            for h in adj.hours:
                effective_solar[h] = min(effective_solar[h], base_solar[h] * adj.factor)

        elif item.directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE:
            for h in adj.hours:
                min_battery_reserve[h] = max(min_battery_reserve[h], adj.minimum_energy_kwh)

        elif item.directive_type == DirectiveType.NO_CHARGE_WINDOW:
            for h in adj.hours:
                no_charge_hours.add(h)

        elif item.directive_type == DirectiveType.NO_DISCHARGE_WINDOW:
            for h in adj.hours:
                no_discharge_hours.add(h)

        elif item.directive_type == DirectiveType.MAX_GRID_WINDOW:
            for h in adj.hours:
                current = max_grid_kwh[h]
                if current is None or adj.max_grid_kwh < current:
                    max_grid_kwh[h] = adj.max_grid_kwh

    return NormalizedConstraints(
        effective_solar=effective_solar,
        min_battery_reserve=min_battery_reserve,
        no_charge_hours=no_charge_hours,
        no_discharge_hours=no_discharge_hours,
        max_grid_kwh=max_grid_kwh,
    )
