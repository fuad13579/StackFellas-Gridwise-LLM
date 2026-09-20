"""Independent solution replay validator to ensure schedule correctness and safety."""

import logging

from app.directives.normalizer import NormalizedConstraints
from app.errors import AppError
from app.schemas import BatteryAction, OptimizeRequest, OptimizeResponse

logger = logging.getLogger(__name__)
TOLERANCE = 0.01  # Official numerical tolerance (0.01 kWh / BDT)


def validate_solution(
    request: OptimizeRequest,
    constraints: NormalizedConstraints,
    response: OptimizeResponse,
) -> None:
    """Independently replays and verifies the returned hourly_plan against all constraints."""

    plan = response.hourly_plan
    if len(plan) != 24:
        raise AppError("invalid_solution", "hourly_plan must contain exactly 24 entries.", 500)

    capacity = request.battery.capacity_kwh
    initial_e = request.battery.initial_energy_kwh
    max_c_rate = request.battery.max_charge_kwh_per_hour
    max_d_rate = request.battery.max_discharge_kwh_per_hour

    current_e = initial_e
    recalc_grid = 0.0
    recalc_cost = 0.0
    recalc_peak = 0.0

    for h in range(24):
        row = plan[h]
        if row.hour != h:
            raise AppError("invalid_solution", f"Expected hour {h}, got {row.hour}", 500)

        grid = row.grid_kwh
        solar = row.solar_used_kwh
        action = row.battery_action
        b_kwh = row.battery_kwh
        e_after = row.battery_energy_after_kwh

        if grid < -1e-6 or solar < -1e-6 or b_kwh < -1e-6 or e_after < -1e-6:
            raise AppError("invalid_solution", f"Negative value detected at hour {h}", 500)

        # Check effective solar limit
        eff_solar = constraints.effective_solar[h]
        if solar > eff_solar + TOLERANCE:
            raise AppError(
                "invalid_solution",
                f"Solar used ({solar}) exceeds effective solar ({eff_solar}) at hour {h}",
                500,
            )

        # Parse charge / discharge amounts
        if action == BatteryAction.IDLE:
            if abs(b_kwh) > 1e-4:
                raise AppError("invalid_solution", f"battery_kwh must be 0 for IDLE at hour {h}", 500)
            c = 0.0
            d = 0.0
        elif action == BatteryAction.CHARGE:
            c = b_kwh
            d = 0.0
            if c > max_c_rate + TOLERANCE:
                raise AppError("invalid_solution", f"Charge rate ({c}) exceeds limit ({max_c_rate}) at hour {h}", 500)
        elif action == BatteryAction.DISCHARGE:
            c = 0.0
            d = b_kwh
            if d > max_d_rate + TOLERANCE:
                raise AppError("invalid_solution", f"Discharge rate ({d}) exceeds limit ({max_d_rate}) at hour {h}", 500)
        else:
            raise AppError("invalid_solution", f"Invalid battery action {action} at hour {h}", 500)

        # Directive checks
        if h in constraints.no_charge_hours and c > 1e-4:
            raise AppError("invalid_solution", f"Charging forbidden by no_charge_window at hour {h}", 500)

        if h in constraints.no_discharge_hours and d > 1e-4:
            raise AppError("invalid_solution", f"Discharging forbidden by no_discharge_window at hour {h}", 500)

        grid_cap = constraints.max_grid_kwh[h]
        if grid_cap is not None and grid > grid_cap + TOLERANCE:
            raise AppError("invalid_solution", f"Grid import ({grid}) exceeds grid cap ({grid_cap}) at hour {h}", 500)

        # Energy balance check: grid + solar + discharge == demand + charge
        demand = request.hours[h].demand_kwh
        supply = grid + solar + d
        consumption = demand + c
        if abs(supply - consumption) > TOLERANCE:
            raise AppError(
                "invalid_solution",
                f"Energy balance violation at hour {h}: supply={supply}, consumption={consumption}",
                500,
            )

        # Battery transition check
        expected_e_after = current_e + c - d
        if abs(e_after - expected_e_after) > TOLERANCE:
            raise AppError(
                "invalid_solution",
                f"Battery state transition mismatch at hour {h}: expected {expected_e_after}, got {e_after}",
                500,
            )

        # Battery reserve / capacity bounds check
        min_res = constraints.min_battery_reserve[h]
        if e_after < min_res - TOLERANCE or e_after > capacity + TOLERANCE:
            raise AppError(
                "invalid_solution",
                f"Battery energy ({e_after}) out of bounds [{min_res}, {capacity}] at hour {h}",
                500,
            )

        current_e = e_after
        recalc_grid += grid
        tariff = request.hours[h].tariff_bdt_per_kwh
        recalc_cost += grid * tariff
        if grid > recalc_peak:
            recalc_peak = grid

    # End-of-day battery neutrality check
    if abs(current_e - initial_e) > TOLERANCE:
        raise AppError(
            "invalid_solution",
            f"End-of-day battery neutrality violated: started with {initial_e}, ended with {current_e}",
            500,
        )

    # Recalculated totals check
    if abs(response.total_grid_kwh - recalc_grid) > TOLERANCE:
        raise AppError(
            "invalid_solution",
            f"Reported total_grid_kwh ({response.total_grid_kwh}) disagrees with recalculated ({recalc_grid})",
            500,
        )

    if abs(response.total_cost_bdt - recalc_cost) > TOLERANCE:
        raise AppError(
            "invalid_solution",
            f"Reported total_cost_bdt ({response.total_cost_bdt}) disagrees with recalculated ({recalc_cost})",
            500,
        )

    if abs(response.peak_grid_kwh - recalc_peak) > TOLERANCE:
        raise AppError(
            "invalid_solution",
            f"Reported peak_grid_kwh ({response.peak_grid_kwh}) disagrees with recalculated ({recalc_peak})",
            500,
        )
