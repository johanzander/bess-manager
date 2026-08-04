"""
Dynamic Programming Algorithm for Battery Energy Storage System (BESS) Optimization.

This module implements a sophisticated dynamic programming approach to optimize battery
dispatch decisions over a 24-hour horizon, considering time-varying electricity prices,
solar production forecasts, and home consumption patterns.

UPDATED: Now captures strategic intent at decision time rather than analyzing flows afterward.

ALGORITHM OVERVIEW:
The optimization uses backward induction dynamic programming to find the globally optimal
battery charging and discharging schedule. At each hour, the algorithm evaluates all
possible battery actions (charge/discharge/hold) and selects the one that minimizes
total cost over the remaining time horizon.

KEY FEATURES:
- 24-hour optimization horizon with perfect foresight
- Cost basis tracking for stored energy (FIFO accounting)
- Multi-objective optimization: cost minimization + battery longevity
- Simultaneous energy flow optimization across multiple sources/destinations
- Strategic intent capture at decision time for transparency and hardware control

STRATEGIC INTENT CAPTURE:
The algorithm now captures the strategic reasoning behind each decision:
- GRID_CHARGING: Storing cheap grid energy for arbitrage
- SOLAR_STORAGE: Storing excess solar for later use
- LOAD_SUPPORT: Discharging to meet home load
- BATTERY_EXPORT: Discharging to grid for profit
- IDLE: No significant activity

ENERGY FLOW MODELING:
The algorithm models complex energy flows where multiple sources can serve multiple
destinations simultaneously:
- Solar → {Home, Battery, Grid Export}
- Battery → {Home, Grid Export}
- Grid → {Home, Battery Charging}

OPTIMIZATION OBJECTIVES:
1. Primary: Minimize total electricity costs over 24-hour period
2. Secondary: Minimize battery degradation through cycle cost modeling
3. Constraints: Physical battery limits, efficiency losses, minimum SOC

RETURN STRUCTURE:
The algorithm returns comprehensive results including:
- Optimal battery actions for each hour
- Strategic intent for each decision
- Detailed energy flow breakdowns showing where each kWh flows
- Economic analysis comparing different scenarios
- All data needed for hardware implementation and performance analysis
"""

__all__ = [
    "optimize_battery_schedule",
    "print_optimization_results",
]


import logging
from enum import Enum

import numpy as np

from core.bess.decision_intelligence import (
    classify_strategic_intent,
    create_decision_data,
)
from core.bess.dp_constants import (
    POWER_CLASSIFICATION_THRESHOLD_KW,
    POWER_STEP_KW,
    SOE_STEP_KWH,
)
from core.bess.milp_battery_algorithm import solve_milp_schedule
from core.bess.models import (
    DecisionData,
    EconomicData,
    EconomicSummary,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.settings import BatterySettings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Algorithm parameters. SOE_STEP_KWH/POWER_STEP_KW live in dp_constants.py
# (shared with decision_intelligence.py -- see that module's docstring for why).
POWER_TOLERANCE_KW = 0.001  # Threshold to distinguish IDLE from charge/discharge

# Piecewise-linear value-function representation (#450). The backward pass
# represents each V[t] as an adaptive breakpoint list instead of a uniform
# SOE grid, refined until the representation is within PWL_EPS_REFINE (SEK)
# of the true value function per period and pruned of breakpoints whose
# removal changes V by less than PWL_EPS_PRUNE. Total certified error over a
# 192-period horizon is bounded by 192 * (refine + prune) ~ 4e-4 SEK -- two
# orders of magnitude below the ~1e-2 SEK near-tie differentials this exists
# to resolve (#450's reported case: 0.0124 SEK). Tightening these further
# buys no better decisions: the exact discrete-action V carries a geometric
# cascade of real micro-kinks (winner-switches between adjacent
# integer-percent discharge levels), so breakpoint counts saturate rather
# than shrink (measured: ~10k at 1e-5 and 1e-6 alike).
PWL_EPS_REFINE = 1e-6
PWL_EPS_PRUNE = 1e-6
PWL_MAX_REFINE_ITERS = 100
# Intervals narrower than this are accepted without probing. Must sit at
# float-resolution scale, NOT at "small error" scale: V contains near-cliff
# features (steep ramps from feasibility boundaries propagating through
# action shifts) whose height is independent of their width, so a coarser
# floor abandons refinement exactly where the function moves fastest
# (measured: an 8e-3 SEK under-read inside a 1.3e-5-wide interval).
PWL_MIN_PROBE_WIDTH_KWH = 2e-9
# Kinks in V[t+1] with a slope change at least this large (SEK/kWh) get
# their preimages seeded under every discharge shift (see the
# seed-construction comment in _run_dynamic_programming); smaller kinks'
# shifted images have value amplitudes below the refinement tolerance and
# are left to probing. PWL_MAX_KINK_SEEDS caps the count as a guard.
PWL_KINK_SEED_MIN_SLOPE = 1e-3
PWL_MAX_KINK_SEEDS = 500
# Matches decision_intelligence.classify_strategic_intent's own
# battery_to_grid threshold for BATTERY_EXPORT classification -- keep these
# in sync: the DP's own reward search must value a discharge's export
# credit consistently with whether that discharge will actually be
# classified (and executed via grid_first) as a real export.
BATTERY_EXPORT_THRESHOLD_KWH = 0.01


class StrategicIntent(Enum):
    """Strategic intents for battery actions, determined at decision time."""

    # Primary intents (mutually exclusive)
    GRID_CHARGING = "GRID_CHARGING"  # Storing cheap grid energy for arbitrage
    SOLAR_STORAGE = "SOLAR_STORAGE"  # Storing excess solar for later use
    LOAD_SUPPORT = "LOAD_SUPPORT"  # Discharging to meet home load
    BATTERY_EXPORT = "BATTERY_EXPORT"  # Discharging battery to grid for profit
    SOLAR_EXPORT = "SOLAR_EXPORT"  # Solar surplus exporting to grid, battery idle
    IDLE = "IDLE"  # No significant action


def _discretize_state_action_space(
    battery_settings: BatterySettings,
) -> tuple[np.ndarray, np.ndarray]:
    """Discretize state and action spaces - FIXED to return SOE levels."""
    # State space: State of Energy (kWh)
    soe_levels = np.arange(
        battery_settings.min_soe_kwh,
        battery_settings.max_soe_kwh + SOE_STEP_KWH,
        SOE_STEP_KWH,
    )

    # Action space: power levels (kW)
    max_power = max(
        battery_settings.max_charge_power_kw, battery_settings.max_discharge_power_kw
    )
    power_levels = np.arange(
        -max_power,
        max_power + POWER_STEP_KW,
        POWER_STEP_KW,
    )

    # Guarantee IDLE (power=0) is an available action. The arange above is
    # offset so it never lands exactly on zero, and under the #146 binary-store
    # semantics ("any positive power charges at max rate") the smallest positive
    # grid power is a full-rate grid charge — not a hold. Without an explicit
    # IDLE action the value iteration cannot represent holding the battery, so
    # the always-achievable IDLE floor (V[t,i] >= idle_reward + V[t+1,i]) is
    # unreachable and V collapses below it.
    if not np.any(np.abs(power_levels) <= POWER_TOLERANCE_KW):
        power_levels = np.sort(np.append(power_levels, 0.0))

    return soe_levels, power_levels


def _idle_battery_flows(
    soe: float,
    next_soe: float,
    battery_settings: BatterySettings,
) -> tuple[float, float]:
    """Derive battery_charged/battery_discharged for an IDLE period.

    During IDLE, excess solar passively charges the battery. The SOE delta
    (computed by _state_transition) is already efficiency-adjusted, so we
    reverse the efficiency to get the solar throughput consumed.

    Returns:
        (battery_charged, battery_discharged) in kWh throughput.
    """
    # No below-floor special case needed: _soe_floor (#233) only clamps next_soe
    # up to min_soe_kwh when soe already started at/above it -- when soe is
    # below the floor, the floor is soe itself, so a zero-solar period already
    # yields next_soe == soe (delta 0) without help from this function. Below
    # the floor with real solar, the delta is genuine stored energy and must
    # be credited the same as any other IDLE period (#269).
    passive_energy_stored = next_soe - soe
    battery_charged = (
        passive_energy_stored / battery_settings.efficiency_charge
        if passive_energy_stored > 0
        else 0.0
    )
    return battery_charged, 0.0


def _soe_floor(soe: float, battery_settings: BatterySettings) -> float:
    """The feasible/reportable SOE floor for a period that *started* at
    `soe`: `min_soe_kwh` if the period started at/above it, otherwise `soe`
    itself. Recovering from a below-floor start (e.g. a live sensor reading
    under Min SOC in demo mode, see #233) must never fabricate a jump to
    the floor with zero real energy stored."""
    return battery_settings.min_soe_kwh if soe >= battery_settings.min_soe_kwh else soe


def _effective_ac_cap_kwh(battery_settings: BatterySettings, dt: float) -> float | None:
    """Per-period AC-output energy cap (kWh), or None when the feature is off.

    Models a hybrid inverter whose total AC output (PV DC→AC conversion plus
    battery discharge) is capped, while DC-coupled PV can charge the battery
    above the cap. The margin is a model-side haircut only — it compensates
    for hourly forecasts flattening sub-period peaks — and is never written
    to hardware.
    """
    if battery_settings.inverter_max_ac_power_kw <= 0.0:
        return None
    return (
        battery_settings.inverter_max_ac_power_kw
        * (1.0 - battery_settings.inverter_ac_power_margin)
        * dt
    )


def _ac_flows(
    solar_production: float,
    home_consumption: float,
    solar_to_battery: float,
    battery_discharged: float,
    ac_cap_kwh: float | None,
) -> tuple[float, float, float]:
    """AC-side grid flows for one period, shared by every disposition.

    Solar not stored DC-side must pass through the inverter's AC stage; with a
    cap, anything above it is clipped (lost, zero credit). Battery discharge
    shares the same AC stage — callers must pre-limit discharge to the cap
    headroom (`ac_cap_kwh - min(solar, ac_cap_kwh)`).

    Returns (grid_imported, grid_exported, clipped_solar) in kWh.
    """
    residual_solar = solar_production - solar_to_battery
    if ac_cap_kwh is None:
        ac_solar = residual_solar
    else:
        ac_solar = min(residual_solar, ac_cap_kwh)
    clipped_solar = residual_solar - ac_solar
    ac_output = ac_solar + battery_discharged
    home_served = min(ac_output, home_consumption)
    grid_exported = ac_output - home_served
    grid_imported = home_consumption - home_served
    return grid_imported, grid_exported, clipped_solar


def _state_transition(
    soe: float,
    power: float,
    battery_settings: BatterySettings,
    dt: float,
    solar_production: float,
    home_consumption: float,
) -> float:
    """
    Calculate the next state of energy based on current SOE and power action.

    EFFICIENCY HANDLING:
    - Charging: power x dt x efficiency = energy actually stored
    - Discharging: power x dt / efficiency = energy removed from storage
    This ensures that efficiency losses are properly accounted for in energy balance.

    PASSIVE SOLAR CHARGING (IDLE):
    When power=0, excess solar (production - consumption) passively charges the
    battery up to capacity, clamped by the inverter's max charge rate. This models
    the economically correct baseline: free solar energy is more valuable stored
    for later use than exported at the (typically lower) sell price.
    """
    if power > POWER_TOLERANCE_KW:  # STORE disposition (+ optional grid charge)
        surplus = max(0.0, solar_production - home_consumption)
        room_throughput = (
            battery_settings.max_soe_kwh - soe
        ) / battery_settings.efficiency_charge
        rate_throughput = battery_settings.max_charge_power_kw * dt
        solar_to_battery = min(surplus, rate_throughput, room_throughput)
        remaining_rate = max(
            0.0, min(rate_throughput, room_throughput) - solar_to_battery
        )
        grid_to_battery = remaining_rate  # solar fills first, grid tops up the rest
        charge_energy = (
            solar_to_battery + grid_to_battery
        ) * battery_settings.efficiency_charge
        next_soe = min(battery_settings.max_soe_kwh, soe + charge_energy)

    elif power < -POWER_TOLERANCE_KW:  # Discharging
        # Energy removed from storage = power throughput ÷ discharging efficiency
        discharge_energy = abs(power) * dt / battery_settings.efficiency_discharge
        available_energy = soe - battery_settings.min_soe_kwh
        actual_discharge = min(discharge_energy, available_energy)
        next_soe = soe - actual_discharge

    else:  # IDLE — passive solar charging (mirrors load_first hardware behavior)
        surplus = max(0.0, solar_production - home_consumption)
        room_throughput = (
            battery_settings.max_soe_kwh - soe
        ) / battery_settings.efficiency_charge
        rate_throughput = battery_settings.max_charge_power_kw * dt
        solar_to_battery = min(surplus, rate_throughput, room_throughput)
        charge_energy = solar_to_battery * battery_settings.efficiency_charge
        next_soe = min(battery_settings.max_soe_kwh, soe + charge_energy)

    # Ensure SOE stays within physical bounds (see _soe_floor).
    next_soe = min(
        battery_settings.max_soe_kwh, max(_soe_floor(soe, battery_settings), next_soe)
    )

    return next_soe


def _state_transition_grid(
    soe: np.ndarray,
    power: np.ndarray,
    battery_settings: BatterySettings,
    dt: float,
    solar_production: float,
    home_consumption: float,
) -> np.ndarray:
    """Vectorized form of `_state_transition` for the DP backward pass.

    `soe` is a column vector (S, 1) of SoE levels and `power` is a row
    vector (1, A) of candidate actions; the result broadcasts to (S, A).
    Every arithmetic step mirrors `_state_transition` exactly (same
    operations, same order) so results are bit-identical per cell -- this
    is what lets `_run_dynamic_programming` vectorize without changing the
    DP's numerics. See #236.
    """
    max_soe = battery_settings.max_soe_kwh
    min_soe = battery_settings.min_soe_kwh
    eff_charge = battery_settings.efficiency_charge
    eff_discharge = battery_settings.efficiency_discharge

    surplus = max(0.0, solar_production - home_consumption)
    rate_throughput = battery_settings.max_charge_power_kw * dt

    # STORE disposition (power > TOL): binary physics -- next_soe does not
    # depend on the exact positive power value, only on soe (see
    # _build_period_data's "STORE physics are binary" note).
    room_throughput = (max_soe - soe) / eff_charge
    solar_to_battery = np.minimum(np.minimum(surplus, rate_throughput), room_throughput)
    remaining_rate = np.maximum(
        0.0, np.minimum(rate_throughput, room_throughput) - solar_to_battery
    )
    grid_to_battery = remaining_rate
    store_charge_energy = (solar_to_battery + grid_to_battery) * eff_charge
    store_next_soe = np.minimum(max_soe, soe + store_charge_energy)

    # Discharging (power < -TOL)
    discharge_energy = np.abs(power) * dt / eff_discharge
    available_energy = soe - min_soe
    actual_discharge = np.minimum(discharge_energy, available_energy)
    discharge_next_soe = soe - actual_discharge

    # IDLE -- passive solar charging only, no grid top-up
    idle_charge_energy = solar_to_battery * eff_charge
    idle_next_soe = np.minimum(max_soe, soe + idle_charge_energy)

    next_soe = np.where(
        power > POWER_TOLERANCE_KW,
        store_next_soe,
        np.where(power < -POWER_TOLERANCE_KW, discharge_next_soe, idle_next_soe),
    )

    # See _soe_floor's docstring (#233) -- only raise to the floor when soe
    # started at/above it.
    floor = np.where(soe >= min_soe, min_soe, soe)
    next_soe = np.minimum(max_soe, np.maximum(floor, next_soe))
    return next_soe


def _compute_reward_grid(
    power: np.ndarray,
    soe: np.ndarray,
    next_soe: np.ndarray,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    current_buy_price: float,
    current_sell_price: float,
    solar_production: float,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> np.ndarray:
    """Vectorized form of `_compute_reward`'s reward calculation.

    Only the reward is needed by the DP backward pass (it discards
    `new_cost_basis`), so this omits the cost-basis bookkeeping entirely --
    same simplification the caller already applies to the scalar path
    (`reward, _ = _compute_reward(...)`). Formulas mirror `_compute_reward`
    exactly, branch for branch, for numerical parity. See #236.
    """
    max_soe = battery_settings.max_soe_kwh
    eff_charge = battery_settings.efficiency_charge
    cycle_cost = battery_settings.cycle_cost_per_kwh
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    is_charge = power > POWER_TOLERANCE_KW
    is_discharge = power < -POWER_TOLERANCE_KW

    def ac_flows_grid(solar_to_battery, battery_discharged):
        """np mirror of _ac_flows — same formulas, broadcast-friendly."""
        residual_solar = solar_production - solar_to_battery
        if ac_cap_kwh is None:
            ac_solar = residual_solar
        else:
            ac_solar = np.minimum(residual_solar, ac_cap_kwh)
        ac_output = ac_solar + battery_discharged
        home_served = np.minimum(ac_output, home_consumption)
        return home_consumption - home_served, ac_output - home_served

    # Idle passive-absorption flows. No below-floor special case needed --
    # see _idle_battery_flows's docstring (#269): the delta is already zero
    # below the floor when there's no real solar, and genuine when there is.
    passive_energy_stored = next_soe - soe
    idle_battery_charged = np.where(
        passive_energy_stored > 0,
        passive_energy_stored / eff_charge,
        0.0,
    )
    battery_discharged_active = np.abs(power) * dt

    # STORE disposition reward (mirrors the early-return branch in
    # _compute_reward, which redefines grid_imported/grid_exported locally)
    surplus = max(0.0, solar_production - home_consumption)
    rate_throughput = battery_settings.max_charge_power_kw * dt
    room_throughput = (max_soe - soe) / eff_charge
    solar_to_battery = np.minimum(np.minimum(surplus, rate_throughput), room_throughput)
    remaining_rate = np.maximum(
        0.0, np.minimum(rate_throughput, room_throughput) - solar_to_battery
    )
    grid_to_battery = remaining_rate
    energy_stored_store = (solar_to_battery + grid_to_battery) * eff_charge
    battery_wear_cost_store = energy_stored_store * cycle_cost
    grid_imported_store, grid_exported_store = ac_flows_grid(solar_to_battery, 0.0)
    grid_imported_store = grid_imported_store + grid_to_battery
    total_cost_store = (
        grid_imported_store * current_buy_price
        - grid_exported_store * current_sell_price
        + battery_wear_cost_store
    )
    reward_store = -total_cost_store

    # Discharging reward -- self-throttling fix (#240): overshoot below
    # BATTERY_EXPORT_THRESHOLD_KWH gets no export credit.
    grid_imported_d, grid_exported_d = ac_flows_grid(0.0, battery_discharged_active)
    grid_exported_discharge = np.where(
        grid_exported_d <= self_throttle_export_threshold_kwh, 0.0, grid_exported_d
    )
    total_cost_discharge = (
        grid_imported_d * current_buy_price
        - grid_exported_discharge * current_sell_price
    )
    reward_discharge = -total_cost_discharge

    # IDLE reward
    grid_imported_idle, grid_exported_idle = ac_flows_grid(idle_battery_charged, 0.0)
    energy_stored_idle = next_soe - soe
    battery_wear_cost_idle = energy_stored_idle * cycle_cost
    total_cost_idle = (
        grid_imported_idle * current_buy_price
        - grid_exported_idle * current_sell_price
        + battery_wear_cost_idle
    )
    reward_idle = -total_cost_idle

    reward = np.where(
        is_charge, reward_store, np.where(is_discharge, reward_discharge, reward_idle)
    )
    return reward


def _compute_reward(
    power: float,
    soe: float,
    next_soe: float,
    period: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    buy_price: list[float],
    sell_price: list[float],
    solar_production: float,
    cost_basis: float,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> tuple[float, float]:
    """Hot-path reward computation — returns scalars only, no dataclass allocation.

    CYCLE COST POLICY:
    - Applied only to charging operations (not discharging)
    - Applied to energy actually stored (after efficiency losses)
    - Grid costs applied to energy throughput (what you draw from grid)
    - Cost basis includes BOTH grid costs AND cycle costs for profitability analysis

    DISCHARGE ACCOUNTING:
    - No profitability veto: every physically valid discharge gets a finite
      reward. IDLE, competing in the same max() during backward induction,
      already makes the hold-vs-discharge call correctly via the
      forward-looking value function -- a separate floor on top of that is
      redundant at best (see docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md).
    - Self-throttling (#240): a discharge overshooting home_consumption by
      less than BATTERY_EXPORT_THRESHOLD_KWH is not credited as export
      revenue -- load-first hardware never actually delivers it to the grid.

    Returns:
        (reward, new_cost_basis).
    """
    current_buy_price = buy_price[period]
    current_sell_price = sell_price[period]
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    # ============================================================================
    # BATTERY CYCLE COST AND COST BASIS CALCULATION
    # ============================================================================
    new_cost_basis = cost_basis

    if power > POWER_TOLERANCE_KW:  # STORE disposition
        surplus = max(0.0, solar_production - home_consumption)
        room_throughput = (
            battery_settings.max_soe_kwh - soe
        ) / battery_settings.efficiency_charge
        rate_throughput = battery_settings.max_charge_power_kw * dt
        solar_to_battery = min(surplus, rate_throughput, room_throughput)
        remaining_rate = max(
            0.0, min(rate_throughput, room_throughput) - solar_to_battery
        )
        grid_to_battery = remaining_rate  # solar fills first, grid tops up the rest

        energy_stored = (
            solar_to_battery + grid_to_battery
        ) * battery_settings.efficiency_charge
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh

        # genuine excess solar (above rate/room) is exported; deliberate grid top-up imported
        grid_imported, grid_exported, _ = _ac_flows(
            solar_production, home_consumption, solar_to_battery, 0.0, ac_cap_kwh
        )
        grid_imported += grid_to_battery

        if ac_cap_kwh is None:
            solar_opportunity_cost = solar_to_battery * current_sell_price
        else:
            # Storing solar only forgoes the export it actually displaces —
            # absorbing energy that would have been clipped anyway is free.
            _, export_without_storing, _ = _ac_flows(
                solar_production, home_consumption, 0.0, 0.0, ac_cap_kwh
            )
            solar_opportunity_cost = (
                export_without_storing - grid_exported
            ) * current_sell_price
        grid_energy_cost = grid_to_battery * current_buy_price
        total_new_cost = grid_energy_cost + solar_opportunity_cost + battery_wear_cost
        if next_soe > battery_settings.min_soe_kwh:
            existing_cost = soe * cost_basis
            new_cost_basis = (existing_cost + total_new_cost) / next_soe
        else:
            new_cost_basis = (
                (total_new_cost / energy_stored) if energy_stored > 0 else cost_basis
            )

        total_cost = (
            grid_imported * current_buy_price
            - grid_exported * current_sell_price
            + battery_wear_cost
        )
        return -total_cost, new_cost_basis

    elif power < -POWER_TOLERANCE_KW:  # Discharging
        battery_wear_cost = 0.0
        battery_discharged = abs(power) * dt
        grid_imported, grid_exported, _ = _ac_flows(
            solar_production, home_consumption, 0.0, battery_discharged, ac_cap_kwh
        )

        # Self-throttling fix (#240): load-first hardware never actually
        # exports a small discharge overshoot beyond home_consumption -- it
        # delivers only what the home needs. Below BATTERY_EXPORT_THRESHOLD_KWH
        # (the same battery_to_grid boundary decision_intelligence.
        # classify_strategic_intent uses to call something BATTERY_EXPORT vs
        # LOAD_SUPPORT), treat the overshoot as self-throttled: no export
        # credit. At or above it, it's a genuine deliberate export.
        if grid_exported <= self_throttle_export_threshold_kwh:
            grid_exported = 0.0

    else:  # IDLE — passive solar charging
        battery_charged, _ = _idle_battery_flows(soe, next_soe, battery_settings)
        grid_imported, grid_exported, _ = _ac_flows(
            solar_production, home_consumption, battery_charged, 0.0, ac_cap_kwh
        )
        energy_stored = next_soe - soe  # kWh stored in battery after efficiency
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh
        if energy_stored > 0 and next_soe > battery_settings.min_soe_kwh:
            if ac_cap_kwh is None:
                solar_opportunity_cost = battery_charged * current_sell_price
            else:
                # Same clipping discount as the STORE branch: passively
                # absorbing energy that would have been clipped anyway
                # forgoes only the export it actually displaces.
                _, export_without_absorbing, _ = _ac_flows(
                    solar_production, home_consumption, 0.0, 0.0, ac_cap_kwh
                )
                solar_opportunity_cost = (
                    export_without_absorbing - grid_exported
                ) * current_sell_price
            new_cost_basis = (
                soe * cost_basis + solar_opportunity_cost + battery_wear_cost
            ) / next_soe

    # ============================================================================
    # REWARD CALCULATION
    # ============================================================================
    total_cost = (
        grid_imported * current_buy_price
        - grid_exported * current_sell_price
        + battery_wear_cost
    )
    return -total_cost, new_cost_basis


def _build_period_data(
    power: float,
    soe: float,
    next_soe: float,
    period: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    buy_price: list[float],
    sell_price: list[float],
    solar_production: float,
    new_cost_basis: float,
    currency: str,
    continuation_value: float = 0.0,
) -> PeriodData:
    """Build full PeriodData for the winning action of a DP cell.

    Called once per (t, i) cell after the inner power loop identifies the best action.
    Separated from _compute_reward to eliminate dataclass allocation in the hot path.

    continuation_value: the DP's actual value-to-go from the resulting state
    (_interpolate_value(V_next, next_soe, ...), the same term
    _best_action_at_continuous_state adds to reward when choosing this
    action) -- reported as decision.future_value. Defaults to 0.0 so this
    function's own reporting-only `reward` still equals immediate_value for
    any caller that hasn't been updated to pass the real continuation value
    (see issue #353).
    """
    current_buy_price = buy_price[period]
    current_sell_price = sell_price[period]
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    if power > POWER_TOLERANCE_KW:  # STORE disposition (+ optional grid charge)
        surplus = max(0.0, solar_production - home_consumption)
        room_throughput = (
            battery_settings.max_soe_kwh - soe
        ) / battery_settings.efficiency_charge
        rate_throughput = battery_settings.max_charge_power_kw * dt
        solar_to_battery = min(surplus, rate_throughput, room_throughput)
        remaining_rate = max(
            0.0, min(rate_throughput, room_throughput) - solar_to_battery
        )
        grid_to_battery = remaining_rate  # solar fills first, grid tops up the rest
        battery_charged = solar_to_battery + grid_to_battery
        battery_discharged = 0.0
        # STORE physics are binary (any positive power charges at rate_throughput),
        # so the DP's tie-break can report an arbitrary small `power`. Use the
        # achieved throughput instead — see #203.
        battery_action_kwh = battery_charged
    elif power < -POWER_TOLERANCE_KW:  # Active discharging
        battery_charged = 0.0
        battery_discharged = abs(power) * dt
        battery_action_kwh = power * dt
        solar_to_battery = 0.0
        grid_to_battery = 0.0
    else:  # IDLE — EXPORT disposition: battery holds, surplus exported
        battery_charged, battery_discharged = _idle_battery_flows(
            soe, next_soe, battery_settings
        )
        battery_action_kwh = power * dt
        solar_to_battery = battery_charged
        grid_to_battery = 0.0

    grid_imported, grid_exported, clipped_solar = _ac_flows(
        solar_production,
        home_consumption,
        solar_to_battery,
        battery_discharged,
        ac_cap_kwh,
    )
    grid_imported += grid_to_battery

    energy_data = EnergyData(
        solar_production=solar_production,
        home_consumption=home_consumption,
        battery_charged=battery_charged,
        battery_discharged=battery_discharged,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        battery_soe_start=soe,
        battery_soe_end=next_soe,
        clipped_solar=clipped_solar,
    )

    energy_stored = max(0.0, next_soe - soe)
    battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh

    import_cost = grid_imported * current_buy_price
    export_revenue = grid_exported * current_sell_price
    total_cost = import_cost - export_revenue + battery_wear_cost
    reward = -total_cost

    decision_data = create_decision_data(
        power=power,
        battery_action_kwh=battery_action_kwh,
        energy_data=energy_data,
        hour=period,
        cost_basis=new_cost_basis,
        # extract_economic_values_from_reward derives future_value as
        # reward - immediate_value; immediate_value is built from the same
        # import_cost/export_revenue/battery_wear_cost terms as `reward`
        # above, so adding continuation_value here is what makes
        # future_value equal it instead of always coming out 0.0 (#353).
        reward=reward + continuation_value,
        import_cost=import_cost,
        export_revenue=export_revenue,
        battery_wear_cost=battery_wear_cost,
        buy_price=current_buy_price,
        sell_price=current_sell_price,
        currency=currency,
    )

    economic_data = EconomicData.from_energy_data(
        energy_data=energy_data,
        buy_price=current_buy_price,
        sell_price=current_sell_price,
        battery_cycle_cost=battery_wear_cost,
    )

    # Timestamp is set to None - caller will add timestamps based on optimization_period
    # The algorithm is time-agnostic and operates on relative period indices (0 to horizon-1)
    return PeriodData(
        period=period,
        energy=energy_data,
        timestamp=None,
        data_source="predicted",
        economic=economic_data,
        decision=decision_data,
    )


def print_optimization_results(results, buy_prices, sell_prices):
    """Log a detailed results table with strategic intents - new format version.

    Args:
        results: OptimizationResult object with period_data and economic_summary
        buy_prices: List of buy prices
        sell_prices: List of sell prices
    """
    period_data_list = results.period_data
    economic_results = results.economic_summary

    # Initialize totals
    total_consumption = 0
    total_base_cost = 0
    total_solar = 0
    total_solar_to_bat = 0
    total_grid_to_bat = 0
    total_grid_cost = 0
    total_battery_cost = 0
    total_combined_cost = 0
    total_savings = 0
    total_charging = 0
    total_discharging = 0

    # Initialize output string
    output = []

    output.append("\nBattery Schedule:")
    output.append(
        "╔════╦═══════════╦══════╦═══════╦╦═════╦══════╦══════╦═════╦═══════╦═══════════════╦═══════╦══════╦══════╗"
    )
    output.append(
        "║ Hr ║  Buy/Sell ║Cons. ║ Cost  ║║Sol. ║Sol→B ║Gr→B  ║ SoE ║Action ║    Intent     ║  Grid ║ Batt ║ Save ║"
    )
    output.append(
        "║    ║   (SEK)   ║(kWh) ║ (SEK) ║║(kWh)║(kWh) ║(kWh) ║(kWh)║(kWh)  ║               ║ (SEK) ║(SEK) ║(SEK) ║"
    )
    output.append(
        "╠════╬═══════════╬══════╬═══════╬╬═════╬══════╬══════╬═════╬═══════╬═══════════════╬═══════╬══════╬══════╣"
    )

    # Process each hour - replicating original logic exactly
    for i, period_data in enumerate(period_data_list):
        period = period_data.period
        consumption = period_data.energy.home_consumption
        solar = period_data.energy.solar_production
        action = period_data.decision.battery_action or 0.0
        soe_kwh = period_data.energy.battery_soe_end
        intent = period_data.decision.strategic_intent

        # Calculate values exactly like original function
        base_cost = (
            consumption * buy_prices[i]
            if i < len(buy_prices)
            else consumption * period_data.economic.buy_price
        )

        # Extract solar flows from detailed flow data (always available from EnergyData)
        solar_to_battery = period_data.energy.solar_to_battery
        grid_to_battery = period_data.energy.grid_to_battery

        # Calculate costs using original logic - FIXED: use property accessor for battery_cycle_cost
        grid_cost = (
            period_data.energy.grid_imported * period_data.economic.buy_price
            - period_data.energy.grid_exported * period_data.economic.sell_price
        )
        battery_cost = (
            period_data.economic.battery_cycle_cost
        )  # FIXED: access via economic component
        combined_cost = grid_cost + battery_cost
        period_savings = base_cost - combined_cost

        # Update totals
        total_consumption += consumption
        total_base_cost += base_cost
        total_solar += solar
        total_solar_to_bat += solar_to_battery
        total_grid_to_bat += grid_to_battery
        total_grid_cost += grid_cost
        total_battery_cost += battery_cost
        total_combined_cost += combined_cost
        total_savings += period_savings
        total_charging += period_data.energy.battery_charged
        total_discharging += period_data.energy.battery_discharged

        # Format intent to fit column width
        intent_display = intent[:15] if len(intent) > 15 else intent

        # Format period row - preserving original formatting exactly
        buy_sell_str = f"{buy_prices[i] if i < len(buy_prices) else period_data.economic.buy_price:.2f}/{sell_prices[i] if i < len(sell_prices) else period_data.economic.sell_price:.2f}"

        output.append(
            f"║{period:3d} ║ {buy_sell_str:9s} ║{consumption:5.1f} ║{base_cost:6.2f} ║║{solar:4.1f} ║{solar_to_battery:5.1f} ║{grid_to_battery:5.1f} ║{soe_kwh:4.0f} ║{action:6.1f} ║ {intent_display:13s} ║{grid_cost:6.2f} ║{battery_cost:5.2f} ║{period_savings:5.2f} ║"
        )

    # Add separator and total row
    output.append(
        "╠════╬═══════════╬══════╬═══════╬╬═════╬══════╬══════╬═════╬═══════╬═══════════════╬═══════╬══════╬══════╣"
    )
    output.append(
        f"║Tot ║           ║{total_consumption:5.1f} ║{total_base_cost:6.2f} ║║{total_solar:4.1f} ║{total_solar_to_bat:5.1f} ║{total_grid_to_bat:5.1f} ║     ║C:{total_charging:4.1f} ║               ║{total_grid_cost:6.2f} ║{total_battery_cost:5.2f} ║{total_savings:5.2f} ║"
    )
    output.append(
        f"║    ║           ║      ║       ║║     ║      ║      ║     ║D:{total_discharging:4.1f} ║               ║       ║      ║      ║"
    )
    output.append(
        "╚════╩═══════════╩══════╩═══════╩╩═════╩══════╩══════╩═════╩═══════╩═══════════════╩═══════╩══════╩══════╝"
    )

    # Append summary stats to output
    output.append("\n      Summary:")
    output.append(
        f"      Grid-only cost:           {economic_results.grid_only_cost:.2f} SEK"
    )
    output.append(
        f"      Optimized cost:           {economic_results.battery_solar_cost:.2f} SEK"
    )
    output.append(
        f"      Total savings:            {economic_results.grid_to_battery_solar_savings:.2f} SEK"
    )
    savings_percentage = economic_results.grid_to_battery_solar_savings_pct
    output.append(f"      Savings percentage:         {savings_percentage:.1f} %")

    # Log all output in a single call
    logger.info("\n".join(output))


def _pwl_prune(xs: np.ndarray, vs: np.ndarray, eps: float = PWL_EPS_PRUNE):
    """Drop interior breakpoints whose removal changes the PWL function by
    at most `eps` (collinearity within tolerance). Non-adjacent removals per
    pass so each removal's error stays measured against surviving points."""
    while len(xs) > 2:
        x0, x1, x2 = xs[:-2], xs[1:-1], xs[2:]
        v0, v1, v2 = vs[:-2], vs[1:-1], vs[2:]
        frac = (x1 - x0) / (x2 - x0)
        chord = v0 + frac * (v2 - v0)
        removable = np.abs(v1 - chord) <= eps
        if not removable.any():
            break
        keep = np.ones(len(xs), dtype=bool)
        last_removed = -2
        for i in np.nonzero(removable)[0]:
            idx = i + 1
            if idx - last_removed >= 2:
                keep[idx] = False
                last_removed = idx
        xs, vs = xs[keep], vs[keep]
    return xs, vs


def _backward_discharge_levels(
    battery_settings: BatterySettings,
    discharge_resolution_kw: float | None,
) -> np.ndarray:
    """Discharge power levels (kW, positive) for the backward pass: the same
    hardware-true integer-percent grid `_discharge_candidates` enumerates at
    replay, including its classification-threshold floor. Using one action
    set in both passes is what makes the replayed schedule achieve exactly
    the value the backward pass promised (no snap/interpolation residual for
    replay to fall short of)."""
    rate_step = (
        discharge_resolution_kw
        if discharge_resolution_kw is not None
        else battery_settings.max_discharge_power_kw / 100
    )
    max_pct = int(np.floor(battery_settings.max_discharge_power_kw / rate_step + 1e-9))
    min_pct = int(np.floor(POWER_CLASSIFICATION_THRESHOLD_KW / rate_step)) + 1
    return np.array([pct * rate_step for pct in range(min_pct, max_pct + 1)])


def _candidate_values_at(
    X: np.ndarray,
    t: int,
    V_next: tuple[np.ndarray, np.ndarray],
    power_row: np.ndarray,
    horizon_inputs,
    battery_settings: BatterySettings,
    dt: float,
    period_max_charge: float | None,
    self_throttle_export_threshold_kwh: float,
) -> np.ndarray:
    """Best achievable value at each SOE in `X` for period `t`: max over the
    shared action set (IDLE, STORE, discharge grid) plus the
    SOLAR_EXPORT-below-max bypass (#313), with V[t+1] evaluated exactly at
    each candidate's true (continuous) next_soe -- no state snapping."""
    buy_price, sell_price, home_consumption, solar_production = horizon_inputs
    min_soe = battery_settings.min_soe_kwh
    max_soe = battery_settings.max_soe_kwh
    soe_col = X.reshape(-1, 1)

    is_charge = power_row > POWER_TOLERANCE_KW
    is_discharge = power_row < -POWER_TOLERANCE_KW

    next_soe = _state_transition_grid(
        soe_col,
        power_row,
        battery_settings,
        dt,
        solar_production=solar_production[t],
        home_consumption=home_consumption[t],
    )
    reward = _compute_reward_grid(
        power_row,
        soe_col,
        next_soe,
        home_consumption=home_consumption[t],
        battery_settings=battery_settings,
        dt=dt,
        current_buy_price=buy_price[t],
        current_sell_price=sell_price[t],
        solar_production=solar_production[t],
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    )

    # STORE feasibility: the same rule replay's _charge_candidate applies
    # (binary store physics -- one representative positive power stands in
    # for every feasible charge action).
    max_charge_power = (max_soe - soe_col) / dt / battery_settings.efficiency_charge
    if period_max_charge is not None:
        max_charge_power = np.minimum(max_charge_power, period_max_charge)
    feasible = ~is_charge | (max_charge_power > POWER_CLASSIFICATION_THRESHOLD_KW)

    max_discharge_power = (
        (soe_col - min_soe) / dt * battery_settings.efficiency_discharge
    )
    feasible &= ~is_discharge | (np.abs(power_row) <= max_discharge_power)
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)
    if ac_cap_kwh is not None:
        # Battery discharge shares the inverter's AC stage with PV
        # conversion — only the headroom the (possibly clipped) solar
        # leaves is deliverable.
        ac_headroom_kwh = max(0.0, ac_cap_kwh - min(solar_production[t], ac_cap_kwh))
        feasible &= ~is_discharge | (np.abs(power_row) * dt <= ac_headroom_kwh)
    feasible &= (next_soe >= min_soe) & (next_soe <= max_soe)

    value = reward + _pwl_eval_array(V_next, next_soe)
    value = np.where(feasible, value, -np.inf)

    # SOLAR_EXPORT-below-max candidate (#313): soe held exactly unchanged
    # (next_soe == soe), solar surplus exports directly instead of passively
    # charging. Reusing _compute_reward_grid with next_soe == soe already
    # produces the correct economics (see _idle_battery_flows: zero SOE
    # delta -> battery_charged=0, so grid_exported reflects the full
    # surplus). With the AC cap set, this candidate is also what defers
    # charging to preserve headroom for above-cap solar.
    zeros_col = np.zeros_like(soe_col)
    reward_bypass = _compute_reward_grid(
        zeros_col,
        soe_col,
        soe_col,
        home_consumption=home_consumption[t],
        battery_settings=battery_settings,
        dt=dt,
        current_buy_price=buy_price[t],
        current_sell_price=sell_price[t],
        solar_production=solar_production[t],
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    )
    value_bypass = reward_bypass + _pwl_eval_array(V_next, soe_col)

    # IDLE and bypass are always feasible with finite reward, so the max
    # over actions can never remain -inf.
    return np.maximum(value.max(axis=1), value_bypass.reshape(-1))


def _run_dynamic_programming(
    horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    battery_settings: BatterySettings,
    dt: float,
    solar_production: list[float] | None = None,
    initial_soe: float | None = None,
    initial_cost_basis: float = 0.0,
    terminal_value_per_kwh: float = 0.0,
    currency: str = "SEK",
    max_charge_power_per_period: list[float] | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
    discharge_resolution_kw: float | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """
    Run backward induction DP, representing each V[t] as an adaptive
    piecewise-linear function of continuous SOE (#450) instead of a
    uniform-grid table.

    Returns a list of `horizon + 1` PWL rows, each an `(xs, vs)` breakpoint
    pair evaluable via `_interpolate_value`.

    Why not a grid: the true V's kinks live on the data-dependent reachable
    lattice (initial_soe plus sums of charge/discharge increments), not on
    any uniform grid. A grid table read by ANY scheme must therefore choose
    between rounding noise (nearest-snap: up to SOE_STEP_KWH/2 x shadow
    price per lookup, enough to flip genuinely near-tied decisions -- the
    #450 bug) and one-signed chord bias (linear interpolation of a concave
    V systematically underestimates it between grid points, compounding
    across every backward step -- the failure mode that broke 19 fixtures
    when tried). Representing V by its own breakpoints eliminates the
    tradeoff: every candidate's continuation value is evaluated at its true
    continuous next_soe.

    The representation is epsilon-certified, not literally exact: intervals
    are refined until the PWL row is within PWL_EPS_REFINE of the true
    value function (probed at two asymmetric points per interval) and
    pruned at PWL_EPS_PRUNE. See the constants' comment block for the
    error budget and why tighter tolerances buy nothing.

    Also considers, at every state, a distinct SOLAR_EXPORT-below-max
    candidate (#313) -- battery SOE held exactly unchanged (no passive
    charge) while this period's own solar surplus exports directly -- as an
    alternative to IDLE's forced full passive charge. See
    docs/superpowers/specs/2026-07-16-issue-313-root-cause-investigation.md.
    """

    # Set defaults if not provided
    if solar_production is None:
        solar_production = [0.0] * horizon
    if initial_soe is None:
        initial_soe = battery_settings.min_soe_kwh

    min_soe = battery_settings.min_soe_kwh
    max_soe = battery_settings.max_soe_kwh
    horizon_inputs = (buy_price, sell_price, home_consumption, solar_production)

    # Action set: IDLE + one representative STORE power (binary store
    # physics) + the replay-aligned integer-percent discharge grid.
    discharge_levels = _backward_discharge_levels(
        battery_settings, discharge_resolution_kw
    )
    power_row = np.concatenate([[0.0, POWER_STEP_KW], -discharge_levels]).reshape(1, -1)

    # Terminal value: linear in usable energy above the floor.
    V: list[tuple[np.ndarray, np.ndarray] | None] = [None] * (horizon + 1)
    xs_T = np.array([min_soe, max_soe])
    V[horizon] = (xs_T, terminal_value_per_kwh * (xs_T - min_soe))

    rate_throughput = battery_settings.max_charge_power_kw * dt
    seed_grid = np.arange(min_soe, max_soe + 4 * SOE_STEP_KWH, 4 * SOE_STEP_KWH)
    e_d = discharge_levels * dt / battery_settings.efficiency_discharge

    # Backward induction
    for t in reversed(range(horizon)):
        period_max_charge = (
            max_charge_power_per_period[t]
            if max_charge_power_per_period is not None
            else None
        )
        xs_next = V[t + 1][0]

        # Seed breakpoints: V[t+1]'s breakpoints and their preimages under
        # the translation-like actions (bypass: identity; STORE/IDLE: shift
        # by the charge increment), the transition/reward kinks (room/rate/
        # surplus crossovers near capacity), each discharge level's
        # feasibility onset, and a SOE_STEP_KWH safety-net grid. Kinks whose
        # preimages this misses (e.g. under the 99 discharge shifts) are
        # found by the probe-refinement loop below.
        surplus = max(0.0, solar_production[t] - home_consumption[t])
        c_store = rate_throughput * battery_settings.efficiency_charge
        c_idle = min(surplus, rate_throughput) * battery_settings.efficiency_charge
        # Preimages of V[t+1]'s significant kinks under every action shift.
        # A kink pair narrower than a probe interval forms a value "bump"
        # the probe loop can one-shot-miss (certification samples a single
        # interior point per interval); seeding the shifted positions of
        # the largest slope changes makes those bumps representable by
        # construction instead of by luck. Bounded to the top
        # PWL_MAX_KINK_SEEDS kinks so the seed set stays O(kinks x levels).
        vs_next = V[t + 1][1]
        if len(xs_next) > 2:
            slopes = np.diff(vs_next) / np.diff(xs_next)
            kink_mag = np.abs(np.diff(slopes))
            significant = kink_mag >= PWL_KINK_SEED_MIN_SLOPE
            if significant.sum() > PWL_MAX_KINK_SEEDS:
                cutoff = np.partition(kink_mag, -PWL_MAX_KINK_SEEDS)[
                    -PWL_MAX_KINK_SEEDS
                ]
                significant = kink_mag >= cutoff
            sig = xs_next[1:-1][significant]
        else:
            sig = xs_next
        seeds = [
            xs_next,
            xs_next - c_store,
            seed_grid,
            min_soe + e_d,
            # Left companions: a feasibility onset is a jump-like feature;
            # a point just below it pins the lower branch so the cliff is
            # represented by a steep two-point segment instead of being
            # interpolated away.
            min_soe + e_d - 2e-9,
            (sig[None, :] + e_d[:, None]).ravel(),
            np.array(
                [
                    max_soe - c_store,
                    max_soe - surplus * battery_settings.efficiency_charge,
                    max_soe - c_idle,
                ]
            ),
        ]
        if c_idle > 0.0:
            seeds.append(xs_next - c_idle)
        X = np.unique(np.clip(np.concatenate(seeds), min_soe, max_soe))
        X = X[np.concatenate([[True], np.diff(X) > 1e-9])]

        def eval_at(
            points: np.ndarray,
            _t: int = t,
            _V_next: tuple[np.ndarray, np.ndarray] = V[t + 1],
            _period_max_charge: float | None = period_max_charge,
        ) -> np.ndarray:
            return _candidate_values_at(
                points,
                _t,
                _V_next,
                power_row,
                horizon_inputs,
                battery_settings,
                dt,
                _period_max_charge,
                self_throttle_export_threshold_kwh,
            )

        VX = eval_at(X)

        # Probe-refinement: one asymmetric (golden-ratio) probe per dirty
        # interval; insert only probes where the true value deviates from
        # the current chord by more than PWL_EPS_REFINE. Each point is
        # evaluated exactly once (existing points' values never change
        # within a period), and an interval whose probe sits on the chord
        # is marked clean and never re-probed; inserting a point splits an
        # interval into two dirty children. Robustness against features a
        # single interior probe could miss comes from the seeds above:
        # significant-kink preimages and feasibility-onset companions make
        # bumps and cliffs representable by construction, so probing only
        # has to certify the smooth remainder.
        dirty = np.diff(X) > PWL_MIN_PROBE_WIDTH_KWH
        for _ in range(PWL_MAX_REFINE_ITERS):
            if not dirty.any():
                break
            idx = np.nonzero(dirty)[0]
            x0, x1 = X[idx], X[idx + 1]
            # One asymmetric probe per interval (the golden-ratio offset):
            # a hidden kink whose chord happens to pass exactly through
            # this interior point is a measure-zero coincidence, and the
            # kink would still be caught from the neighboring interval
            # after any adjacent split.
            probes = x0 + 0.381966 * (x1 - x0)
            pv = eval_at(probes)
            lin = VX[idx] + 0.381966 * (VX[idx + 1] - VX[idx])
            deviation = np.abs(pv - lin)
            interval_bad = deviation > PWL_EPS_REFINE
            # Certified intervals: probe on the chord -> clean.
            dirty[idx[~interval_bad]] = False
            if not interval_bad.any():
                break
            split_idx = idx[interval_bad]
            new_x = probes[interval_bad]
            new_v = pv[interval_bad]
            deviation = deviation[interval_bad]
            # Steep features (near-cliffs) bisect painfully slowly one
            # probe at a time -- ~25 rounds to pin a jump from 0.05 kWh
            # down to the probe-width floor, and each round costs a full
            # python/numpy pass. When the probe deviation is far above
            # tolerance, add a geometric point pair hugging the interval's
            # ends so the containing interval shrinks by ~1e3 per round
            # instead of ~2.6.
            steep = deviation > PWL_EPS_REFINE * 1e3
            if steep.any():
                s_idx = split_idx[steep]
                sw = X[s_idx + 1] - X[s_idx]
                extra_x = np.concatenate(
                    [X[s_idx] + sw * 1e-3, X[s_idx + 1] - sw * 1e-3]
                )
                extra_v = eval_at(extra_x)
                new_x = np.concatenate([new_x, extra_x])
                new_v = np.concatenate([new_v, extra_v])
                split_idx = np.concatenate([split_idx, s_idx, s_idx])
            order = np.lexsort((new_x, split_idx))
            new_x, new_v, split_idx = new_x[order], new_v[order], split_idx[order]
            n_old = len(dirty)
            X = np.insert(X, split_idx + 1, new_x)
            VX = np.insert(VX, split_idx + 1, new_v)
            # Rebuild the dirty map: old interval k shifts right by the
            # number of points inserted into intervals before it; an
            # interval that received m inserts becomes m+1 children, all
            # dirty.
            counts = np.bincount(split_idx, minlength=n_old)
            prefix = np.concatenate([[0], np.cumsum(counts)[:-1]])
            new_left = np.arange(n_old) + prefix
            new_dirty = np.zeros(len(X) - 1, dtype=bool)
            new_dirty[new_left] = dirty
            was_split = counts > 0
            child_parents = np.repeat(new_left[was_split], counts[was_split] + 1)
            child_offsets = np.concatenate(
                [np.arange(c + 1) for c in counts[was_split]]
            )
            new_dirty[child_parents + child_offsets] = True
            dirty = new_dirty & (np.diff(X) > PWL_MIN_PROBE_WIDTH_KWH)

        V[t] = _pwl_prune(X, VX, PWL_EPS_PRUNE)

    return V


def _pwl_eval_array(
    V_row: tuple[np.ndarray, np.ndarray], soe: np.ndarray
) -> np.ndarray:
    """Evaluate a PWL value-function row `(xs, vs)` at an array of SOE
    values. Between breakpoints this is exact (the representation IS
    piecewise linear); below the first breakpoint the first segment's
    gradient is extrapolated -- see `_interpolate_value`'s #336 note."""
    xs, vs = V_row
    result = np.interp(soe, xs, vs)
    if len(xs) > 1:
        first_slope = (vs[1] - vs[0]) / (xs[1] - xs[0])
        result = np.where(soe < xs[0], vs[0] + (soe - xs[0]) * first_slope, result)
    return result


def _interpolate_value(
    V_row: tuple[np.ndarray, np.ndarray],
    soe: float,
    battery_settings: BatterySettings,
) -> float:
    """Evaluate a PWL value-function row `(xs, vs)` at a continuous SoE.

    With the #450 PWL representation this is exact between breakpoints --
    the interpolate-vs-snap tension of the old uniform-grid table (each
    correct in a different regime, see the 2026-07-12 design doc) no longer
    exists, because the breakpoints are the function's own kinks.

    The row has no breakpoints below `min_soe_kwh` (#233's below-floor
    tolerance lets `soe` itself go below it). Clamping those states to
    `vs[0]` made every below-floor state look identically worthless,
    masking real differences in how close each was to the floor (#336).
    Extrapolate the first segment's gradient instead. `battery_settings`
    is retained for call-site compatibility."""
    return float(_pwl_eval_array(V_row, np.asarray(soe)))


def _discharge_candidates(
    soe: float,
    battery_settings: BatterySettings,
    dt: float,
    home_consumption: float,
    solar_production: float,
    discharge_resolution_kw: float | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
    ac_cap_kwh: float | None = None,
) -> list[float]:
    """Candidate discharge magnitudes (kW, positive) to evaluate for the
    single-period objective (reward + interpolated continuation value) --
    see docs/superpowers/specs/2026-07-12-dp-continuous-action-reformulation-design.md,
    Findings 1/2/3/5.

    Real hardware executes discharge as an integer percent (0-100) of
    `max_discharge_power_kw`
    (core/bess/simulation/inverter_simulator.py::_map_rates) -- it cannot
    apply an arbitrary continuous kW value. So the actually-achievable
    action space is that discrete percent grid, not the real line
    (postmortem, #282: an earlier version of this function returned exact
    analytic breakpoints like -7.505 kW out of a 10 kW max, which
    percent-rounds to 7.5 kW on real hardware -- a planned action execution
    silently can't reproduce, breaking plan-faithfulness/R==P). Enumerating
    that percent grid directly is both exact with respect to the true
    (discrete) action space and guarantees every candidate is executable
    exactly as planned.

    Second postmortem (#282): `classify_strategic_intent` treats any
    discharge magnitude at or below `POWER_CLASSIFICATION_THRESHOLD_KW`
    (derived from the fixed `POWER_STEP_KW`, not from
    `max_discharge_power_kw`) as noise, falling through to a different
    classification branch. That was safe by construction under the old
    fixed grid (smallest nonzero action, `POWER_STEP_KW`, always exceeded
    it), but 1% of `max_discharge_power_kw` can land at or below it for any
    battery with `max_discharge_power_kw <= 10 kW` -- so candidates at or
    below the threshold are excluded here too, not just candidates at or
    below zero.
    """
    available_energy = soe - battery_settings.min_soe_kwh
    p_max = min(
        battery_settings.max_discharge_power_kw,
        available_energy / dt * battery_settings.efficiency_discharge,
    )
    if ac_cap_kwh is not None:
        # Discharge shares the inverter's AC stage with PV conversion — see
        # the matching feasibility mask in _run_dynamic_programming.
        ac_headroom_kwh = max(0.0, ac_cap_kwh - min(solar_production, ac_cap_kwh))
        p_max = min(p_max, ac_headroom_kwh / dt)
    if p_max <= POWER_TOLERANCE_KW:
        return []

    rate_step = (
        discharge_resolution_kw
        if discharge_resolution_kw is not None
        else battery_settings.max_discharge_power_kw / 100
    )
    max_pct = int(np.floor(p_max / rate_step + 1e-9))
    min_pct = int(np.floor(POWER_CLASSIFICATION_THRESHOLD_KW / rate_step)) + 1
    if min_pct > max_pct:
        return []
    candidates = {pct * rate_step for pct in range(min_pct, max_pct + 1)}

    # Finding 5: reward(p) has two immediate-reward breakpoints -- where
    # energy_balance crosses 0 (import stops) and where it crosses
    # self_throttle_export_threshold_kwh (self-throttle ends, real export
    # starts). Snap each to its nearest achievable step so the reward
    # plateau's edge is represented too.
    balance_zero_p = (home_consumption - solar_production) / dt
    export_starts_p = balance_zero_p + self_throttle_export_threshold_kwh / dt
    for p in (balance_zero_p, export_starts_p):
        if 0.0 < p < p_max:
            pct = min(max_pct, max(min_pct, round(p / rate_step)))
            candidates.add(pct * rate_step)

    return sorted(candidates)


def _charge_candidate(
    soe: float,
    battery_settings: BatterySettings,
    dt: float,
    period_max_charge: float | None,
) -> float | None:
    """The single representative STORE (charge) candidate power, or `None`
    if no genuine charge is possible -- see Finding 4 in
    docs/superpowers/specs/2026-07-12-dp-continuous-action-reformulation-design.md:
    any power above `POWER_TOLERANCE_KW` produces an identical reward
    (binary store physics; actual throughput is governed by
    `max_charge_power_kw`/solar/room, not the chosen power value), so a
    single feasible positive power fully represents the action.

    Same classification-threshold guard as `_discharge_candidates`: a
    candidate at or below `POWER_CLASSIFICATION_THRESHOLD_KW` would be
    misclassified as noise by `classify_strategic_intent` rather than as a
    genuine charge (reachable when very little room remains near a full
    battery), so treat that case as no charge available rather than
    returning a candidate the classifier can't recognize.
    """
    available_capacity = battery_settings.max_soe_kwh - soe
    max_charge_power = available_capacity / dt / battery_settings.efficiency_charge
    if period_max_charge is not None:
        max_charge_power = min(max_charge_power, period_max_charge)
    if max_charge_power <= POWER_CLASSIFICATION_THRESHOLD_KW:
        return None
    return min(POWER_STEP_KW, max_charge_power)


def _best_action_at_continuous_state(
    soe: float,
    t: int,
    V_next: tuple[np.ndarray, np.ndarray],
    power_levels: np.ndarray,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    dt: float,
    solar_production: list[float],
    buy_price: list[float],
    sell_price: list[float],
    cost_basis: float,
    max_charge_power_per_period: list[float] | None,
    discharge_resolution_kw: float | None = None,
    self_throttle_export_threshold_kwh: float = BATTERY_EXPORT_THRESHOLD_KWH,
) -> tuple[float, float, float, float]:
    """One-step Bellman recompute at a true continuous SoE, using the
    already-known V[t+1, :] (linearly interpolated) as the continuation
    value -- the same reward+max(V) logic as _run_dynamic_programming's
    backward pass, applied at the true replay state instead of one snapped
    to the nearest grid index. Used by optimize_battery_schedule's Step 2 to
    reconstruct the continuous path without trusting a policy table computed
    for a slightly different state. See
    docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md.

    Candidate actions are the exact breakpoints of the piecewise-linear
    reward+continuation objective (see
    docs/superpowers/specs/2026-07-12-dp-continuous-action-reformulation-design.md)
    rather than a fixed power grid -- `power_levels` is unused for the
    search itself, kept only for call-site compatibility with
    `_discretize_state_action_space`.

    Returns (best_action, best_next_soe, best_new_cost_basis, best_reward).
    """
    period_max_charge = (
        max_charge_power_per_period[t]
        if max_charge_power_per_period is not None
        else None
    )
    home = home_consumption[t]
    solar = solar_production[t]
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    best_value = float("-inf")
    best_action = 0.0
    best_next_soe = soe
    best_new_cost_basis = cost_basis
    best_reward = 0.0

    def consider(power: float) -> None:
        nonlocal best_value, best_action, best_next_soe, best_new_cost_basis
        nonlocal best_reward
        next_soe = _state_transition(
            soe,
            power,
            battery_settings,
            dt,
            solar_production=solar,
            home_consumption=home,
        )
        # See _soe_floor's docstring (#233): the feasible floor for this
        # candidate is soe itself until real charging crosses back above
        # min_soe_kwh.
        if (
            next_soe < _soe_floor(soe, battery_settings)
            or next_soe > battery_settings.max_soe_kwh
        ):
            return
        reward, new_cost_basis = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home,
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=cost_basis,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
        value = reward + _interpolate_value(V_next, next_soe, battery_settings)
        if value > best_value:
            best_value = value
            best_action = power
            best_next_soe = next_soe
            best_new_cost_basis = new_cost_basis
            best_reward = reward

    # IDLE -- always a feasible candidate.
    consider(0.0)

    # SOLAR_EXPORT-below-max (#313): soe held exactly unchanged, this
    # period's own solar surplus exports directly instead of passively
    # charging -- see _run_dynamic_programming's matching backward-pass
    # candidate for the full rationale. Bypasses _state_transition (whose
    # power=0 branch always charges as much as room/rate permit) to force
    # next_soe == soe directly, then reuses the same _compute_reward call
    # every other candidate uses.
    reward, new_cost_basis = _compute_reward(
        power=0.0,
        soe=soe,
        next_soe=soe,
        period=t,
        home_consumption=home,
        battery_settings=battery_settings,
        dt=dt,
        solar_production=solar,
        buy_price=buy_price,
        sell_price=sell_price,
        cost_basis=cost_basis,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    )
    value = reward + _interpolate_value(V_next, soe, battery_settings)
    if value > best_value:
        best_value = value
        best_action = 0.0
        best_next_soe = soe
        best_new_cost_basis = new_cost_basis
        best_reward = reward

    # Discharge -- exact breakpoint enumeration (Finding 1/2/3/5).
    for p in _discharge_candidates(
        soe,
        battery_settings,
        dt,
        home,
        solar,
        discharge_resolution_kw=discharge_resolution_kw,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        ac_cap_kwh=ac_cap_kwh,
    ):
        consider(-p)

    # Charge (STORE) -- Finding 4: no grid search needed on this side at
    # all, a single representative candidate fully covers it.
    charge_candidate = _charge_candidate(soe, battery_settings, dt, period_max_charge)
    if charge_candidate is not None:
        consider(charge_candidate)

    return best_action, best_next_soe, best_new_cost_basis, best_reward


def _create_idle_schedule(
    horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    initial_soe: float,
    battery_settings: BatterySettings,
    dt: float,
) -> OptimizationResult:
    """
    Create an all-IDLE schedule where battery passively charges from excess solar.

    Used by the all-IDLE safety net, which swaps this in only when it is
    strictly cheaper than the DP's own schedule (there is no profit gate).
    Excess solar charges the battery up to capacity; only overflow exports to grid.
    """
    period_data_list = []
    current_soe = initial_soe
    current_cost_basis = battery_settings.cycle_cost_per_kwh

    for t in range(horizon):
        # Passive solar charging: excess solar goes to battery, overflow to grid
        next_soe = _state_transition(
            current_soe,
            0.0,
            battery_settings,
            dt=dt,
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
        )
        passive_stored = next_soe - current_soe
        battery_charged, _ = _idle_battery_flows(
            current_soe, next_soe, battery_settings
        )
        battery_wear_cost = passive_stored * battery_settings.cycle_cost_per_kwh
        solar_opportunity_cost = battery_charged * sell_price[t]

        # Update cost basis for passively stored solar
        if passive_stored > 0 and next_soe > battery_settings.min_soe_kwh:
            existing_cost = current_soe * current_cost_basis
            current_cost_basis = (
                existing_cost + solar_opportunity_cost + battery_wear_cost
            ) / next_soe

        grid_imported, grid_exported, clipped_solar = _ac_flows(
            solar_production[t],
            home_consumption[t],
            battery_charged,
            0.0,
            _effective_ac_cap_kwh(battery_settings, dt),
        )
        energy_data = EnergyData(
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
            battery_charged=battery_charged,
            battery_discharged=0.0,
            grid_imported=grid_imported,
            grid_exported=grid_exported,
            battery_soe_start=current_soe,
            battery_soe_end=next_soe,
            clipped_solar=clipped_solar,
        )

        economic_data = EconomicData.from_energy_data(
            energy_data=energy_data,
            buy_price=buy_price[t],
            sell_price=sell_price[t],
            battery_cycle_cost=battery_wear_cost,
        )

        decision_data = DecisionData(
            strategic_intent=classify_strategic_intent(0.0, energy_data),
            battery_action=0.0,
            cost_basis=current_cost_basis,
        )

        period_data = PeriodData(
            period=t,
            energy=energy_data,
            timestamp=None,
            data_source="predicted",
            economic=economic_data,
            decision=decision_data,
        )

        period_data_list.append(period_data)
        current_soe = next_soe

    # Calculate economic summary for idle schedule
    total_base_cost = sum(home_consumption[i] * buy_price[i] for i in range(horizon))
    solar_only_cost = sum(h.economic.solar_only_cost for h in period_data_list)
    total_optimized_cost = sum(h.economic.hourly_cost for h in period_data_list)

    total_charged = sum(h.energy.battery_charged for h in period_data_list)
    total_discharged = sum(h.energy.battery_discharged for h in period_data_list)

    economic_summary = EconomicSummary(
        grid_only_cost=total_base_cost,
        solar_only_cost=solar_only_cost,
        battery_solar_cost=total_optimized_cost,
        grid_to_solar_savings=total_base_cost - solar_only_cost,
        grid_to_battery_solar_savings=total_base_cost - total_optimized_cost,
        solar_to_battery_solar_savings=solar_only_cost - total_optimized_cost,
        grid_to_battery_solar_savings_pct=(
            (total_base_cost - total_optimized_cost) / total_base_cost * 100
            if total_base_cost > 0
            else 0.0
        ),
        total_charged=total_charged,
        total_discharged=total_discharged,
    )

    return OptimizationResult(
        period_data=period_data_list,
        economic_summary=economic_summary,
        input_data={
            "buy_price": buy_price,
            "sell_price": sell_price,
            "home_consumption": home_consumption,
            "solar_production": solar_production,
            "initial_soe": initial_soe,
            "initial_cost_basis": battery_settings.cycle_cost_per_kwh,
            "horizon": horizon,
        },
    )


def optimize_battery_schedule(
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soe: float | None = None,
    initial_cost_basis: float | None = None,
    period_duration_hours: float = 0.25,
    terminal_value_per_kwh: float = 0.0,
    currency: str = "SEK",
    max_charge_power_per_period: list[float] | None = None,
    discharge_resolution_kw: float | None = None,
    self_throttle_export_threshold_kwh: float | None = None,
    export_curtailment_active: bool = False,
) -> OptimizationResult:
    """
    Battery optimization that eliminates dual cost calculation by using
    DP-calculated PeriodData directly in simulation.

    Args:
        buy_price: List of electricity buy prices for each period
        sell_price: List of electricity buy prices for each period
        home_consumption: List of home consumption for each period (kWh)
        battery_settings: Battery configuration and limits
        solar_production: List of solar production for each period (kWh), defaults to 0
        initial_soe: Initial battery state of energy (kWh), defaults to min_soe
        initial_cost_basis: Initial cost basis for battery cycling, defaults to cycle_cost
        period_duration_hours: Duration of each period in hours (always 0.25 for quarterly resolution)
        terminal_value_per_kwh: Value assigned to each kWh of usable energy remaining at
            end of horizon. Used to prevent end-of-day battery dumping when tomorrow's
            prices aren't available yet. Defaults to 0.0 (no terminal value).
        max_charge_power_per_period: Per-period max charge power limits (kW), typically
            from temperature derating. When provided, charging actions exceeding the
            limit for each period are excluded from the optimization. Defaults to None
            (no per-period limits, uses battery_settings.max_charge_power_kw).
        export_curtailment_active: Caller-computed, capability-aware flag for
            whether export-limit curtailment (#269) will actually execute --
            battery_settings.export_curtailment_enabled AND the platform
            supports it AND the entities are configured. Deliberately NOT
            read from battery_settings.export_curtailment_enabled directly:
            that's just the user's opt-in preference, and planning as if
            curtailment will happen on a platform/config that can't actually
            do it would make outcomes worse than leaving the feature off
            (the plan forgoes real defenses against a loss that never gets
            neutralized). Same call-site pattern as discharge_resolution_kw
            below. Defaults to False.

    Returns:
        OptimizationResult with optimal battery schedule
    """

    horizon = len(buy_price)
    dt = period_duration_hours

    logger.info(f"Optimization using dt={dt} hours for horizon={horizon} periods")

    # Handle defaults
    if solar_production is None:
        solar_production = [0.0] * horizon
    if initial_soe is None:
        initial_soe = battery_settings.min_soe_kwh
    if initial_cost_basis is None:
        initial_cost_basis = battery_settings.cycle_cost_per_kwh
    if self_throttle_export_threshold_kwh is None:
        self_throttle_export_threshold_kwh = BATTERY_EXPORT_THRESHOLD_KWH

    # Validate inputs to prevent impossible scenarios
    if initial_soe > battery_settings.max_soe_kwh:
        raise ValueError(
            f"Invalid initial_soe={initial_soe:.1f}kWh exceeds battery capacity={battery_settings.max_soe_kwh:.1f}kWh"
        )

    # Allow optimization to start from below minimum SOC (can happen after restart or deep discharge)
    # The optimizer will naturally work to bring SOE back above minimum through charging
    if initial_soe < battery_settings.min_soe_kwh:
        logger.warning(
            f"Starting optimization with initial_soe={initial_soe:.1f}kWh below minimum SOE={battery_settings.min_soe_kwh:.1f}kWh. "
            f"Optimizer will work to restore battery charge."
        )

    logger.info(
        f"Starting direct optimization: horizon={horizon}, initial_soe={initial_soe:.1f}, initial_cost_basis={initial_cost_basis:.3f}"
    )

    # Reward-facing sell price only (#269): when export curtailment is
    # enabled, periods priced below the curtailment floor get an effective
    # sell price of 0.0 for the MILP's own objective/action-selection only
    # -- leaving this unfixed would make the solver refuse a genuinely
    # profitable action just to avoid a loss that curtailment neutralizes
    # in reality. The real sell_price list (unchanged) is still what gets
    # reported on PeriodData.economic.sell_price below and fed to
    # _build_period_data -- BSM's execution-time curtailment trigger reads
    # that field directly, and the displayed plan should show the honest
    # physics-only cost, not the actuation override.
    if export_curtailment_active:
        floor = battery_settings.export_curtailment_price_floor
        reward_sell_price = [0.0 if p < floor else p for p in sell_price]
    else:
        reward_sell_price = sell_price

    # Step 1: Solve the MILP for the globally optimal, hardware-executable
    # schedule (#450 pivot -- replaces the DP backward induction, which
    # could mis-pick between financially near-tied windows under SOE-grid
    # discretization noise). See
    # docs/superpowers/specs/2026-08-03-milp-optimizer-pivot-450.md and
    # core/bess/milp_battery_algorithm.py.
    battery_dict = {
        "initial_soe": initial_soe,
        "min_soe_kwh": battery_settings.min_soe_kwh,
        "max_soe_kwh": battery_settings.max_soe_kwh,
        "efficiency_charge": battery_settings.efficiency_charge,
        "efficiency_discharge": battery_settings.efficiency_discharge,
        "cycle_cost_per_kwh": battery_settings.cycle_cost_per_kwh,
        "max_charge_power_kw": battery_settings.max_charge_power_kw,
        "max_discharge_power_kw": battery_settings.max_discharge_power_kw,
        "inverter_max_ac_power_kw": battery_settings.inverter_max_ac_power_kw,
        "inverter_ac_power_margin": battery_settings.inverter_ac_power_margin,
    }
    milp_result = solve_milp_schedule(
        buy_price=buy_price,
        sell_price=reward_sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        battery=battery_dict,
        dt=dt,
        terminal_value_per_kwh=terminal_value_per_kwh,
        integer_rates=True,
        compute_shadow_price_array=True,
        max_charge_power_per_period=max_charge_power_per_period,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
    )
    if milp_result.status != "optimal":
        raise RuntimeError(
            f"MILP battery schedule optimization failed: status={milp_result.status}"
        )

    def _milp_action_power(t: int) -> float:
        """Translate the MILP's mode+discharge_pct decision for period t
        into dp_battery_algorithm.py's power-based action convention: a
        single signed float where positive=STORE (physics are binary --
        any positive value charges at rate_throughput, see #203),
        negative=DISCHARGE at that exact rate, and zero=IDLE/BYPASS
        (both collapse to the same power=0 case downstream, distinguished
        by the SOE delta via _idle_battery_flows)."""
        mode = milp_result.mode[t]
        if mode == "STORE":
            return battery_settings.max_charge_power_kw
        if mode == "DISCHARGE":
            return (
                -(milp_result.discharge_pct[t] / 100.0)
                * battery_settings.max_discharge_power_kw
            )
        return 0.0

    # Step 2: Replay the MILP's own SOE trajectory through the SAME
    # reward/period-data machinery the DP itself uses (_compute_reward,
    # _build_period_data) -- this reuses the DP's already-validated cost
    # basis (FIFO), wear cost, AC-flow, and self-throttle accounting
    # unchanged; only WHICH action is chosen each period comes from the
    # MILP now, not backward induction.
    rewards = []
    cost_basis_after: list[float] = []
    cost_basis_walk = initial_cost_basis
    soe_walk = initial_soe
    for t in range(horizon):
        next_soe = float(milp_result.soe[t + 1])
        reward, cost_basis_walk = _compute_reward(
            power=_milp_action_power(t),
            soe=soe_walk,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            cost_basis=cost_basis_walk,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        )
        rewards.append(reward)
        cost_basis_after.append(cost_basis_walk)
        soe_walk = next_soe

    # continuation_value (#353): the sum of every later period's reward,
    # the same quantity the DP's own V[t+1] represents for its chosen
    # path, just computed directly from the already-solved schedule
    # instead of a value-to-go table.
    remaining_reward_from = [0.0] * (horizon + 1)
    for t in range(horizon - 1, -1, -1):
        remaining_reward_from[t] = rewards[t] + remaining_reward_from[t + 1]

    hourly_results = []
    current_soe = initial_soe
    for t in range(horizon):
        next_soe = float(milp_result.soe[t + 1])
        period_data = _build_period_data(
            power=_milp_action_power(t),
            soe=current_soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            new_cost_basis=cost_basis_after[t],
            currency=currency,
            continuation_value=remaining_reward_from[t + 1],
        )
        period_data.decision.shadow_price = float(milp_result.shadow_prices[t])
        hourly_results.append(period_data)
        current_soe = next_soe

    # Step 3: Calculate economic summary directly from PeriodData
    total_base_cost = sum(
        home_consumption[i] * buy_price[i] for i in range(len(buy_price))
    )

    # Cost with solar but no battery — the correct baseline for judging whether
    # the battery adds value beyond what solar alone already provides. Reuses
    # each period's already-computed EconomicData.solar_only_cost rather than
    # re-deriving the formula (see EconomicData.from_energy_data).
    solar_only_cost = sum(h.economic.solar_only_cost for h in hourly_results)

    total_optimized_cost = sum(h.economic.hourly_cost for h in hourly_results)
    total_charged = sum(h.energy.battery_charged for h in hourly_results)
    total_discharged = sum(h.energy.battery_discharged for h in hourly_results)

    # Calculate savings directly - renamed variables for clarity
    grid_to_battery_solar_savings = total_base_cost - total_optimized_cost
    solar_to_battery_solar_savings = solar_only_cost - total_optimized_cost

    economic_summary = EconomicSummary(
        grid_only_cost=total_base_cost,
        solar_only_cost=solar_only_cost,
        battery_solar_cost=total_optimized_cost,
        grid_to_solar_savings=total_base_cost - solar_only_cost,
        grid_to_battery_solar_savings=grid_to_battery_solar_savings,
        solar_to_battery_solar_savings=solar_to_battery_solar_savings,
        grid_to_battery_solar_savings_pct=(
            (grid_to_battery_solar_savings / total_base_cost) * 100
            if total_base_cost > 0
            else 0
        ),
        total_charged=total_charged,
        total_discharged=total_discharged,
    )

    logger.info(
        f"Direct Results: Grid-only cost: {total_base_cost:.2f}, "
        f"Optimized cost: {total_optimized_cost:.2f}, "
        f"Savings: {grid_to_battery_solar_savings:.2f} {currency} ({economic_summary.grid_to_battery_solar_savings_pct:.1f}%)"
    )

    # ============================================================================
    # NUMERICAL SAFETY NET: guard against SoE-grid discretization residual
    # ============================================================================
    # Bellman's principle of optimality guarantees the DP's own schedule is
    # never worse than doing nothing: IDLE is always a feasible action every
    # period, so backward induction already picks it whenever it's the best
    # available option. The only way the realized schedule can still cost
    # slightly more than an all-IDLE schedule is SoE-grid discretization
    # residual (see docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md)
    # -- a numerical artifact, not an economic one. This is a trivial O(1)
    # comparison, not a configurable threshold.
    idle_schedule = _create_idle_schedule(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        dt=dt,
    )

    # When export_curtailment_active, the MILP's own objective optimized
    # against reward_sell_price (floored), not the real sell_price used
    # above -- so comparing total_optimized_cost/idle_schedule at real
    # price here would be judging the MILP's plan by a different objective
    # than the one it was asked to optimize, and could silently discard a
    # plan the MILP correctly preferred (same reasoning as the DP's
    # pre-#450 guardrail, #459 review). Recompute both sides of the
    # guardrail comparison at reward_sell_price so it's internally
    # consistent with the actual objective; the RETURNED idle_schedule
    # (if the guardrail fires) still reports at the real price, unchanged.
    guardrail_optimized_cost = total_optimized_cost
    guardrail_idle_cost = idle_schedule.economic_summary.battery_solar_cost
    if export_curtailment_active:
        # milp_result.cost is the solver's own objective value, computed
        # directly against reward_sell_price (it was passed as `sell_price`
        # to solve_milp_schedule above) -- the exact objective the MILP
        # chose actions against, not a reconstruction from reported
        # PeriodData (which could drift from the real per-action reward,
        # e.g. self-throttle export-credit zeroing applying to the reward
        # calc but not to the raw grid_exported energy field).
        guardrail_optimized_cost = milp_result.cost
        guardrail_idle_cost = _create_idle_schedule(
            horizon=horizon,
            buy_price=buy_price,
            sell_price=reward_sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=initial_soe,
            battery_settings=battery_settings,
            dt=dt,
        ).economic_summary.battery_solar_cost

    if guardrail_idle_cost < guardrail_optimized_cost:
        return idle_schedule

    return OptimizationResult(
        period_data=hourly_results,
        economic_summary=economic_summary,
        input_data={
            "buy_price": buy_price,
            "sell_price": sell_price,
            "home_consumption": home_consumption,
            "solar_production": solar_production,
            "initial_soe": initial_soe,
            "initial_cost_basis": initial_cost_basis,
            "horizon": horizon,
        },
    )
