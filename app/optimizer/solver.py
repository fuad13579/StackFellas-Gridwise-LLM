"""SciPy linprog LP optimizer for 24-hour minimum-cost energy scheduling."""

import logging
import time
import numpy as np
from scipy.optimize import linprog

from app.config import Settings
from app.directives.normalizer import NormalizedConstraints
from app.errors import AppError
from app.schemas import BatteryAction, HourlyPlanRow, OptimizeRequest, OptimizeResponse

logger = logging.getLogger(__name__)


def solve_optimization(
    request: OptimizeRequest,
    constraints: NormalizedConstraints,
    settings: Settings,
    interpretations: list,
    deadline: float | None = None,
) -> OptimizeResponse:
    """Solves the 24-hour energy cost minimization LP using scipy.optimize.linprog."""

    if deadline is not None and deadline <= time.monotonic():
        raise AppError("request_timeout", "The optimization request exceeded its time limit.", 504)

    # Decision variables (96 total):
    # 0..23: g_h (grid purchase)
    # 24..47: s_h (solar used)
    # 48..71: c_h (battery charge)
    # 72..95: d_h (battery discharge)

    n_hours = 24
    tariffs = [h.tariff_bdt_per_kwh for h in request.hours]
    demands = [h.demand_kwh for h in request.hours]
    initial_e = request.battery.initial_energy_kwh
    capacity = request.battery.capacity_kwh
    max_c_rate = request.battery.max_charge_kwh_per_hour
    max_d_rate = request.battery.max_discharge_kwh_per_hour

    # Variable bounds
    bounds = []

    # g_h: 0 <= g_h <= max_grid_kwh[h]
    for h in range(n_hours):
        grid_cap = constraints.max_grid_kwh[h]
        bounds.append((0.0, grid_cap if grid_cap is not None else None))

    # s_h: 0 <= s_h <= effective_solar[h]
    for h in range(n_hours):
        bounds.append((0.0, max(0.0, constraints.effective_solar[h])))

    # c_h: 0 <= c_h <= max_charge
    for h in range(n_hours):
        if h in constraints.no_charge_hours:
            bounds.append((0.0, 0.0))
        else:
            bounds.append((0.0, max_c_rate))

    # d_h: 0 <= d_h <= max_discharge
    for h in range(n_hours):
        if h in constraints.no_discharge_hours:
            bounds.append((0.0, 0.0))
        else:
            bounds.append((0.0, max_d_rate))

    # Objective Stage 1: minimize ONLY grid electricity cost.
    # Do not add battery-throughput penalties here; Stage 2 handles tie-breaking.
    c_stage1 = np.zeros(96)
    c_stage1[:24] = tariffs

    # Equality constraints A_eq * x = b_eq
    # 1. Energy balance per hour: g_h + s_h - c_h + d_h = demand_h  (24 rows)
    # 2. End-of-day battery neutrality: sum(c_h) - sum(d_h) = 0  (1 row)
    A_eq = np.zeros((25, 96))
    b_eq = np.zeros(25)

    for h in range(n_hours):
        A_eq[h, h] = 1.0       # g_h
        A_eq[h, 24 + h] = 1.0  # s_h
        A_eq[h, 48 + h] = -1.0 # -c_h
        A_eq[h, 72 + h] = 1.0  # d_h
        b_eq[h] = demands[h]

    # Neutrality: sum(c_h) - sum(d_h) = 0
    A_eq[24, 48:72] = 1.0
    A_eq[24, 72:96] = -1.0
    b_eq[24] = 0.0

    # Inequality constraints A_ub * x <= b_ub
    # For each hour h:
    # E_h = initial_e + sum_{i=0}^h (c_i - d_i)
    # 1. E_h >= min_battery_reserve[h] => sum(d_i) - sum(c_i) <= initial_e - min_battery_reserve[h]
    # 2. E_h <= capacity => sum(c_i) - sum(d_i) <= capacity - initial_e
    A_ub = np.zeros((48, 96))
    b_ub = np.zeros(48)

    row_idx = 0
    for h in range(n_hours):
        min_res = constraints.min_battery_reserve[h]
        # Reserve bound: sum_{i=0}^h d_i - sum_{i=0}^h c_i <= initial_e - min_res
        A_ub[row_idx, 72 : 72 + h + 1] = 1.0
        A_ub[row_idx, 48 : 48 + h + 1] = -1.0
        b_ub[row_idx] = initial_e - min_res
        row_idx += 1

        # Capacity bound: sum_{i=0}^h c_i - sum_{i=0}^h d_i <= capacity - initial_e
        A_ub[row_idx, 48 : 48 + h + 1] = 1.0
        A_ub[row_idx, 72 : 72 + h + 1] = -1.0
        b_ub[row_idx] = capacity - initial_e
        row_idx += 1

    solver_time_limit = settings.solver_time_limit_seconds
    if deadline is not None:
        solver_time_limit = min(solver_time_limit, deadline - time.monotonic())
        if solver_time_limit <= 0:
            raise AppError("request_timeout", "The optimization request exceeded its time limit.", 504)

    res = linprog(
        c_stage1,
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
        options={"time_limit": solver_time_limit},
    )

    if not res.success:
        logger.warning("Optimization failed or infeasible: %s", res.message)
        raise AppError(
            "infeasible",
            "No feasible energy schedule satisfies all constraints and directives.",
            409,
        )

    # Stage 2: among schedules with the same optimal grid cost, minimize
    # battery throughput to avoid unnecessary simultaneous charge/discharge.
    opt_grid_cost = float(np.sum(res.x[:24] * tariffs))
    A_ub_stage2 = np.vstack([A_ub, np.zeros((1, 96))])
    A_ub_stage2[-1, :24] = tariffs
    b_ub_stage2 = np.append(b_ub, opt_grid_cost + 1e-6)

    c_stage2 = np.zeros(96)
    c_stage2[48:96] = 1.0  # minimize charge + discharge throughput

    if deadline is not None:
        solver_time_limit = min(settings.solver_time_limit_seconds, deadline - time.monotonic())
        if solver_time_limit <= 0:
            raise AppError("request_timeout", "The optimization request exceeded its time limit.", 504)

    res_stage2 = linprog(
        c_stage2,
        A_ub=A_ub_stage2,
        b_ub=b_ub_stage2,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
        options={"time_limit": solver_time_limit},
    )

    x_sol = res_stage2.x if res_stage2.success else res.x

    # Extract the solver result directly. Do not clip values after optimization;
    # the independent replay validator should catch any actual bound violation.
    grid_sol = x_sol[:24]
    solar_sol = x_sol[24:48]
    charge_sol = x_sol[48:72]
    discharge_sol = x_sol[72:96]

    hourly_plan: list[HourlyPlanRow] = []
    current_e = initial_e

    for h in range(n_hours):
        g = float(grid_sol[h])
        s = float(solar_sol[h])
        c = float(charge_sol[h])
        d = float(discharge_sol[h])

        # Normalize only negligible floating-point residuals for clean JSON output.
        if abs(g) < 1e-6:
            g = 0.0
        if abs(s) < 1e-6:
            s = 0.0
        if abs(c) < 1e-6:
            c = 0.0
        if abs(d) < 1e-6:
            d = 0.0

        net_flow = c - d
        if net_flow > 1e-5:
            action = BatteryAction.CHARGE
            b_kwh = net_flow
        elif net_flow < -1e-5:
            action = BatteryAction.DISCHARGE
            b_kwh = -net_flow
        else:
            action = BatteryAction.IDLE
            b_kwh = 0.0

        # Report the state implied by the solver; do not repair/clip it.
        current_e += net_flow
        e_after = float(current_e)

        hourly_plan.append(
            HourlyPlanRow(
                hour=h,
                grid_kwh=round(g, 6),
                solar_used_kwh=round(s, 6),
                battery_action=action,
                battery_kwh=round(b_kwh, 6),
                battery_energy_after_kwh=round(e_after, 6),
            )
        )

    total_grid_kwh = float(sum(row.grid_kwh for row in hourly_plan))
    total_cost_bdt = float(
        sum(
            row.grid_kwh * request.hours[row.hour].tariff_bdt_per_kwh
            for row in hourly_plan
        )
    )
    peak_grid_kwh = float(max(row.grid_kwh for row in hourly_plan))

    applied_directives_count = sum(
        1
        for item in interpretations
        if item.applies and item.directive_type != "no_op"
    )
    plan_summary = (
        f"Optimized 24-hour schedule applying {applied_directives_count} operator directive(s). "
        f"Total grid import: {round(total_grid_kwh, 2)} kWh, cost: {round(total_cost_bdt, 2)} BDT, "
        f"peak grid: {round(peak_grid_kwh, 2)} kWh."
    )

    return OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=interpretations,
        hourly_plan=hourly_plan,
        total_grid_kwh=round(total_grid_kwh, 4),
        total_cost_bdt=round(total_cost_bdt, 4),
        peak_grid_kwh=round(peak_grid_kwh, 4),
        plan_summary=plan_summary,
    )
