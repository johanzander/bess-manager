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
from core.bess.models import (
    DecisionData,
    EconomicData,
    EconomicSummary,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.settings import BatterySettings, HomeSettings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Algorithm parameters. SOE_STEP_KWH/POWER_STEP_KW live in dp_constants.py
# (shared with decision_intelligence.py -- see that module's docstring for why).
POWER_TOLERANCE_KW = 0.001  # Threshold to distinguish IDLE from charge/discharge
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


def _effective_import_cap_kwh(
    home_settings: HomeSettings | None, dt: float
) -> float | None:
    """Per-period grid-import energy cap (kWh) derived from the house's fuse
    service limit, or None when power monitoring is disabled (issue #429).

    Multiplied by `phase_count`: each phase is an independent fuse, so a
    balanced 3-phase house can import up to `phase_count` times a single
    phase's ceiling before any individual phase is stressed. `HomePowerMonitor`
    (`core/bess/power_monitor.py`) already relies on this same assumption at
    runtime -- on a fully unloaded 3-phase house it authorizes the battery up
    to its full `max_charge_power_w` (not a single phase's worth), since
    `available_pct` is computed relative to `max_charge_power_w / phase_count`
    per phase. `HomePowerMonitor` remains the real-time backstop against
    unbalanced loads (it measures actual per-phase current and throttles
    battery charging against the single worst-loaded phase, commit 37201cb9,
    #11); the DP has no per-phase forecast to reproduce that live check, so it
    caps against the balanced-load assumption instead of the unbalanced
    worst case.
    """
    if home_settings is None or not home_settings.power_monitoring_enabled:
        return None
    return (
        home_settings.voltage
        * home_settings.max_fuse_current
        * home_settings.safety_margin
        * home_settings.phase_count
        / 1000.0
    ) * dt


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


def _ac_flows_grid(
    solar_to_battery: np.ndarray,
    battery_discharged: np.ndarray | float,
    solar_production: float,
    home_consumption: float,
    ac_cap_kwh: float | None,
) -> tuple[np.ndarray, np.ndarray]:
    """np mirror of `_ac_flows` — same formulas, broadcast-friendly.

    Returns (grid_imported, grid_exported), omitting `clipped_solar` (unused
    by any vectorized caller so far).
    """
    residual_solar = solar_production - solar_to_battery
    if ac_cap_kwh is None:
        ac_solar = residual_solar
    else:
        ac_solar = np.minimum(residual_solar, ac_cap_kwh)
    ac_output = ac_solar + battery_discharged
    home_served = np.minimum(ac_output, home_consumption)
    return home_consumption - home_served, ac_output - home_served


def _state_transition(
    soe: float,
    power: float,
    battery_settings: BatterySettings,
    dt: float,
    solar_production: float,
    home_consumption: float,
    ac_cap_kwh: float | None = None,
    import_cap_kwh: float | None = None,
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
        if import_cap_kwh is not None:
            # Grid charging must not push total import (load + charging)
            # over the house fuse's import cap (#429) -- throttle the
            # grid-charge component to whatever headroom the load leaves.
            load_import, _, _ = _ac_flows(
                solar_production, home_consumption, solar_to_battery, 0.0, ac_cap_kwh
            )
            grid_to_battery = min(
                grid_to_battery, max(0.0, import_cap_kwh - load_import)
            )
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
    ac_cap_kwh: float | None = None,
    import_cap_kwh: float | None = None,
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
    if import_cap_kwh is not None:
        load_import, _ = _ac_flows_grid(
            solar_to_battery, 0.0, solar_production, home_consumption, ac_cap_kwh
        )
        grid_to_battery = np.minimum(
            grid_to_battery, np.maximum(0.0, import_cap_kwh - load_import)
        )
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
    import_cap_kwh: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized form of `_compute_reward`'s reward calculation.

    Only the reward (and, for the import-cap feasibility mask, total
    grid_imported) is needed by the DP backward pass -- it discards
    `new_cost_basis`, same simplification the caller already applies to the
    scalar path (`reward, _ = _compute_reward(...)`). Formulas mirror
    `_compute_reward` exactly, branch for branch, for numerical parity. See
    #236.

    Returns (reward, grid_imported).
    """
    max_soe = battery_settings.max_soe_kwh
    eff_charge = battery_settings.efficiency_charge
    cycle_cost = battery_settings.cycle_cost_per_kwh
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    is_charge = power > POWER_TOLERANCE_KW
    is_discharge = power < -POWER_TOLERANCE_KW

    def ac_flows_grid(solar_to_battery, battery_discharged):
        return _ac_flows_grid(
            solar_to_battery,
            battery_discharged,
            solar_production,
            home_consumption,
            ac_cap_kwh,
        )

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
    grid_imported_store, grid_exported_store = ac_flows_grid(solar_to_battery, 0.0)
    if import_cap_kwh is not None:
        # Grid charging must not push total import (load + charging) over
        # the house fuse's import cap (#429).
        grid_to_battery = np.minimum(
            grid_to_battery, np.maximum(0.0, import_cap_kwh - grid_imported_store)
        )
    energy_stored_store = (solar_to_battery + grid_to_battery) * eff_charge
    battery_wear_cost_store = energy_stored_store * cycle_cost
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
    grid_imported = np.where(
        is_charge,
        grid_imported_store,
        np.where(is_discharge, grid_imported_d, grid_imported_idle),
    )
    return reward, grid_imported


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
    import_cap_kwh: float | None = None,
) -> tuple[float, float, float]:
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
        (reward, new_cost_basis, grid_imported). `grid_imported` is exposed
        so callers can enforce the import-cap feasibility constraint (#429)
        without recomputing these flows.
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

        # genuine excess solar (above rate/room) is exported; deliberate grid top-up imported
        grid_imported, grid_exported, _ = _ac_flows(
            solar_production, home_consumption, solar_to_battery, 0.0, ac_cap_kwh
        )
        if import_cap_kwh is not None:
            # Grid charging must not push total import (load + charging)
            # over the house fuse's import cap (#429).
            grid_to_battery = min(
                grid_to_battery, max(0.0, import_cap_kwh - grid_imported)
            )

        energy_stored = (
            solar_to_battery + grid_to_battery
        ) * battery_settings.efficiency_charge
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh
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
        return -total_cost, new_cost_basis, grid_imported

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
    return -total_cost, new_cost_basis, grid_imported


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
    import_cap_kwh: float | None = None,
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
        if import_cap_kwh is not None:
            # Grid charging must not push total import (load + charging)
            # over the house fuse's import cap (#429).
            load_import, _, _ = _ac_flows(
                solar_production, home_consumption, solar_to_battery, 0.0, ac_cap_kwh
            )
            grid_to_battery = min(
                grid_to_battery, max(0.0, import_cap_kwh - load_import)
            )
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
    import_cap_kwh: float | None = None,
) -> np.ndarray:
    """
    Run backward induction DP to compute optimal battery control policy.

    Also considers, at every state, a distinct SOLAR_EXPORT-below-max
    candidate (#313) -- battery SOE held exactly unchanged (no passive
    charge) while this period's own solar surplus exports directly -- as an
    alternative to IDLE's forced full passive charge. Without this, IDLE's
    mandatory charge conflates "let solar bypass the battery" with "how much
    room to keep" into one decision, forcing a genuinely necessary
    headroom-creating action into whichever period first needs the room
    even when a better-priced, side-effect-free slot for it existed earlier
    in the same horizon. See
    docs/superpowers/specs/2026-07-16-issue-313-root-cause-investigation.md.
    """

    # Set defaults if not provided
    if solar_production is None:
        solar_production = [0.0] * horizon
    if initial_soe is None:
        initial_soe = battery_settings.min_soe_kwh

    # Discretize state and action spaces
    soe_levels, power_levels = _discretize_state_action_space(battery_settings)

    V = np.zeros((horizon + 1, len(soe_levels)))

    # Terminal value: assign value to usable energy remaining at end of horizon
    if terminal_value_per_kwh > 0.0:
        for i, soe in enumerate(soe_levels):
            usable_energy = soe - battery_settings.min_soe_kwh
            V[horizon, i] = max(0.0, usable_energy) * terminal_value_per_kwh

    min_soe_kwh = battery_settings.min_soe_kwh
    max_soe_kwh = battery_settings.max_soe_kwh
    n_states = len(soe_levels)

    # (S, 1) and (1, A) broadcast columns/rows for the vectorized state x
    # action grid -- same discretized values _run_dynamic_programming's
    # scalar loop iterated over, just evaluated all at once per period.
    soe_col = soe_levels.reshape(-1, 1)
    power_row = power_levels.reshape(1, -1)

    is_discharge = power_row < -POWER_TOLERANCE_KW
    is_charge = power_row > POWER_TOLERANCE_KW

    # Charging feasibility depends only on soe (not on the period), so the
    # non-derating part of the mask is period-invariant and can be
    # precomputed once instead of recomputed every backward-induction step.
    available_capacity = max_soe_kwh - soe_col
    max_charge_power = available_capacity / dt / battery_settings.efficiency_charge
    charge_feasible_base = ~is_charge | (power_row <= max_charge_power)

    available_energy = soe_col - min_soe_kwh
    max_discharge_power = available_energy / dt * battery_settings.efficiency_discharge
    discharge_feasible = ~is_discharge | (np.abs(power_row) <= max_discharge_power)

    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    # Backward induction
    for t in reversed(range(horizon)):
        period_max_charge = (
            max_charge_power_per_period[t]
            if max_charge_power_per_period is not None
            else None
        )
        if period_max_charge is not None:
            charge_feasible = charge_feasible_base & (
                ~is_charge | (power_row <= period_max_charge)
            )
        else:
            charge_feasible = charge_feasible_base

        feasible = charge_feasible & discharge_feasible
        if ac_cap_kwh is not None:
            # Battery discharge shares the inverter's AC stage with PV
            # conversion — only the headroom the (possibly clipped) solar
            # leaves is deliverable.
            ac_headroom_kwh = max(
                0.0, ac_cap_kwh - min(solar_production[t], ac_cap_kwh)
            )
            feasible &= ~is_discharge | (np.abs(power_row) * dt <= ac_headroom_kwh)

        next_soe = _state_transition_grid(
            soe_col,
            power_row,
            battery_settings,
            dt,
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
            ac_cap_kwh=ac_cap_kwh,
            import_cap_kwh=import_cap_kwh,
        )
        feasible &= (next_soe >= min_soe_kwh) & (next_soe <= max_soe_kwh)

        reward, grid_imported = _compute_reward_grid(
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
            import_cap_kwh=import_cap_kwh,
        )

        effective_import_cap = None
        if import_cap_kwh is not None:
            # Constrain, don't raise (#429): an action pushing total import
            # over the cap is infeasible UNLESS no feasible action can meet
            # it (e.g. load alone exceeds the cap even at max discharge) --
            # then the least-bad (minimum-import) action(s) remain the
            # feasible floor, same convention as the AC-output cap and
            # temperature derating (mask, never except).
            floor_grid_imported = np.min(
                np.where(feasible, grid_imported, np.inf), axis=1, keepdims=True
            )
            effective_import_cap = np.maximum(import_cap_kwh, floor_grid_imported)
            feasible &= grid_imported <= effective_import_cap + 1e-9

        next_i = np.round((next_soe - min_soe_kwh) / SOE_STEP_KWH).astype(np.int64)
        next_i = np.clip(next_i, 0, n_states - 1)

        value = reward + V[t + 1][next_i]
        value = np.where(feasible, value, -np.inf)

        # IDLE is always a feasible, finite-reward action (no physical
        # constraint check applies to it, and _compute_reward_grid never
        # returns -inf), so the max over actions can never remain -inf here.
        V[t, :] = np.max(value, axis=1)

        # SOLAR_EXPORT-below-max candidate (#313): soe held exactly
        # unchanged (next_soe == soe, same grid index), solar surplus
        # exports directly instead of passively charging. Reusing
        # _compute_reward_grid with next_soe == soe already produces the
        # correct economics (see _idle_battery_flows: zero SOE delta ->
        # battery_charged=0, so grid_exported reflects the full surplus) --
        # the same reward shape IDLE gets when the battery happens to be
        # full, just made reachable below max_soe too. One extra
        # O(n_states) column, not O(n_states x n_actions).
        # With the AC cap set, this candidate is also what defers charging
        # to preserve headroom for above-cap solar: ac_flows_grid caps the
        # exported surplus and the DP weighs the clipped remainder against
        # the value of keeping the room (no separate HOLD action needed).
        zeros_col = np.zeros_like(soe_col)
        reward_bypass, grid_imported_bypass = _compute_reward_grid(
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
            import_cap_kwh=import_cap_kwh,
        )
        value_bypass = reward_bypass.reshape(-1) + V[t + 1][np.arange(n_states)]
        if effective_import_cap is not None:
            bypass_feasible = (
                grid_imported_bypass.reshape(-1)
                <= effective_import_cap.reshape(-1) + 1e-9
            )
            value_bypass = np.where(bypass_feasible, value_bypass, -np.inf)
        V[t, :] = np.maximum(V[t, :], value_bypass)

    return V


def _interpolate_value(
    V_row: np.ndarray, soe: float, battery_settings: BatterySettings
) -> float:
    """Linearly interpolate a value-function row (V[t, :]) at a continuous
    SoE, rather than snapping to the nearest discretized grid point.

    `V_row` has no grid points below `min_soe_kwh` (#233's below-floor
    tolerance lets `soe` itself go below it). Clamping those states to
    `V_row[0]` made every below-floor state look identically worthless,
    masking real differences in how close each was to the floor (#336).
    Extrapolate the V_row[0]->V_row[1] gradient instead."""
    idx = (soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH
    if idx < 0.0:
        gradient = V_row[1] - V_row[0] if len(V_row) > 1 else 0.0
        return V_row[0] + idx * gradient
    idx = min(idx, len(V_row) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(V_row) - 1)
    frac = idx - lo
    return V_row[lo] * (1 - frac) + V_row[hi] * frac


def _local_value_slope(
    V_row: np.ndarray, soe: float, battery_settings: BatterySettings
) -> float:
    """dV/dSoE of a value-function row at a continuous SoE, taken across the
    grid cell containing it -- the marginal value of stored energy the grid
    DP itself sees at that state (its local shadow price).

    Used by the hybrid tie detector (#450) to convert the DP's SOE_STEP_KWH
    grid-snapping into a value-noise magnitude in currency units, which is
    what a decision margin has to be compared against. Same index arithmetic
    as _interpolate_value, so the slope reported is exactly the one that
    interpolation uses at `soe`.
    """
    idx = (soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH
    idx = min(max(idx, 0.0), len(V_row) - 1)
    lo = min(int(idx), len(V_row) - 2)
    return float((V_row[lo + 1] - V_row[lo]) / SOE_STEP_KWH)


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


# Minimum SOE separation at which two candidate actions count as different
# *decisions* rather than two power levels of the same decision, when
# measuring how ambiguous a period's choice is (#450). See _tie_margin.
#
# This is a behavioural-DISTINCTNESS threshold, empirically calibrated --
# not a duplicate-removal tolerance, despite the duplicate candidates
# (IDLE vs the SOLAR_EXPORT-below-max bypass, which land on the identical
# next_soe) being what first exposed the problem. Removing literal
# duplicates needs only ~SOE_STEP_KWH (0.05 kWh); 1.0 kWh is 20x that, and
# per the calibration sweep it is the DOMINANT lever on the trigger rate,
# not a safety margin around a smaller principled value. Sweeping it over
# 0.05 -> 1.5 kWh moves suite-wide flagging from 15.6% of periods to 0.4%.
#
# It is set where it is because #450's own reproduction fixture has its
# genuine alternative 1.25-1.5 kWh away from the chosen action's next_soe
# -- charging in a different window -- while the mass of spurious
# near-ties across every other fixture sits below 1 kWh, i.e. nudging the
# same plan's power level. #450's case is still caught the whole way up to
# 1.25 kWh, so 1.0 kWh keeps margin on both sides.
#
# Two consequences worth knowing before touching this:
#
# 1. It suppresses the charge side almost entirely. _charge_candidate
#    returns a single POWER_STEP_KW (0.2 kW) gradient probe, which moves
#    SOE by only ~0.05 kWh at dt=0.25h (~0.19 kWh at dt=1h) -- always well
#    under this threshold. So the charge candidate can essentially never
#    be the runner-up, and "charge now vs charge later" (the case the
#    _tie_margin docstring names as the target) can only register as a tie
#    when the CHOSEN action is a large discharge and the alternative is
#    the far-away no-discharge state, never when the chosen action is
#    itself a charge.
# 2. TODO: it is an absolute kWh figure that scales with neither battery
#    capacity nor dt. Every fixture in the suite uses a similar-sized
#    battery, so no test can catch this. On a much smaller battery (say
#    5 kWh usable) a 1.0 kWh separation is a fifth of the whole range and
#    the detector would likely go silent -- and silently, since a missed
#    tie reproduces #450's bug rather than raising. Making it relative to
#    usable capacity needs a fixture with a small battery to calibrate
#    against.
TIE_DEDUP_SOE_KWH = 1.0


def _tie_margin(
    candidates: list[tuple[float, float, float, float, float, float]],
    best_index: int,
) -> float:
    """Value gap between the chosen candidate and the best *behaviourally
    distinct* alternative (#450).

    `candidates` are `(value, power, next_soe, new_cost_basis, reward,
    grid_imported)` tuples as built by `_best_action_at_continuous_state`,
    already filtered against the import cap (#429) so every entry here is an
    action the house's fuse can actually support.

    A raw best-minus-second-best gap over the full candidate list is not a
    usable ambiguity signal, because several of those candidates are the
    same decision expressed twice:

    - IDLE and the SOLAR_EXPORT-below-max candidate coincide exactly
      whenever there is no solar surplus to route differently (both hold
      soe, both score identically) -- a margin of 0.0 that says nothing
      about ambiguity;
    - adjacent discharge breakpoints can sit a fraction of a grid step
      apart, which the grid DP's SOE_STEP_KWH-resolution value table cannot
      even distinguish.

    The alternatives that matter for #450 are ones landing at a materially
    different SOE -- e.g. charging in this window versus a later one. So a
    candidate only counts as a runner-up if its next_soe differs from the
    chosen candidate's by more than TIE_DEDUP_SOE_KWH.

    Returns float("inf") when no distinct alternative is feasible ("not
    tied, no comparison possible").
    """
    best_value, _, best_next_soe, _, _, _ = candidates[best_index]
    runner_up = float("-inf")
    for index, (value, _power, next_soe, _cb, _reward, _gi) in enumerate(candidates):
        if index == best_index:
            continue
        if abs(next_soe - best_next_soe) <= TIE_DEDUP_SOE_KWH:
            continue
        if value > runner_up:
            runner_up = value
    if runner_up == float("-inf"):
        return float("inf")
    return best_value - runner_up


def _best_action_at_continuous_state(
    soe: float,
    t: int,
    V_next: np.ndarray,
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
    import_cap_kwh: float | None = None,
) -> tuple[float, float, float, float, float]:
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

    Returns (best_action, best_next_soe, best_new_cost_basis, best_reward,
    tie_margin), where tie_margin is the gap between the chosen action's
    value and the best *behaviourally distinct* runner-up's value --
    float("inf") if no distinct alternative was feasible, meaning "not
    tied, no comparison possible". Used by the hybrid PWL tie detector
    (#450) to find near-tied periods without re-deriving this comparison.

    "Behaviourally distinct" means landing more than TIE_DEDUP_SOE_KWH away
    in next_soe (see _tie_margin): several candidates evaluated here are
    duplicates of each other in outcome -- most notably IDLE and the
    SOLAR_EXPORT-below-max candidate whenever there is no solar surplus to
    route differently, which land on the identical next_soe with the
    identical value. Ranking those against each other reports margin 0.0
    for a period with no ambiguity at all, which is not the situation #450
    is about (two genuinely different battery actions being close enough
    that the grid-snapped continuation-value lookup could flip the choice).
    """
    period_max_charge = (
        max_charge_power_per_period[t]
        if max_charge_power_per_period is not None
        else None
    )
    home = home_consumption[t]
    solar = solar_production[t]
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    # Candidates are gathered first, then filtered against the import cap
    # (#429), so the cap's "constrain, don't raise" floor -- the minimum
    # grid_imported any candidate in this set actually achieves -- can be
    # computed before any candidate is discarded. Each entry is
    # (value, power, next_soe, new_cost_basis, reward, grid_imported),
    # appended in the original consideration order so that exact value ties
    # still resolve to the first-considered candidate exactly as before.
    candidates: list[tuple[float, float, float, float, float, float]] = []

    def consider(power: float, forced_next_soe: float | None = None) -> None:
        next_soe = (
            forced_next_soe
            if forced_next_soe is not None
            else _state_transition(
                soe,
                power,
                battery_settings,
                dt,
                solar_production=solar,
                home_consumption=home,
                ac_cap_kwh=ac_cap_kwh,
                import_cap_kwh=import_cap_kwh,
            )
        )
        # See _soe_floor's docstring (#233): the feasible floor for this
        # candidate is soe itself until real charging crosses back above
        # min_soe_kwh.
        if (
            next_soe < _soe_floor(soe, battery_settings)
            or next_soe > battery_settings.max_soe_kwh
        ):
            return
        reward, new_cost_basis, grid_imported = _compute_reward(
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
            import_cap_kwh=import_cap_kwh,
        )
        value = reward + _interpolate_value(V_next, next_soe, battery_settings)
        candidates.append(
            (value, power, next_soe, new_cost_basis, reward, grid_imported)
        )

    # IDLE -- always a feasible candidate.
    consider(0.0)

    # SOLAR_EXPORT-below-max (#313): soe held exactly unchanged, this
    # period's own solar surplus exports directly instead of passively
    # charging -- see _run_dynamic_programming's matching backward-pass
    # candidate for the full rationale. Bypasses _state_transition (whose
    # power=0 branch always charges as much as room/rate permit) to force
    # next_soe == soe directly, then reuses the same _compute_reward call
    # every other candidate uses.
    consider(0.0, forced_next_soe=soe)

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

    # Import-cap filtering (#429) runs BEFORE the argmax and before the tie
    # margin is measured: a candidate the fuse cannot actually support is not
    # a runner-up, so letting it into _tie_margin would report ambiguity
    # against an action that was never on the table.
    if import_cap_kwh is not None and candidates:
        floor_grid_imported = min(c[5] for c in candidates)
        effective_import_cap = max(import_cap_kwh, floor_grid_imported)
        candidates = [c for c in candidates if c[5] <= effective_import_cap + 1e-9]

    # The SOLAR_EXPORT-below-max candidate holds soe exactly unchanged, so it
    # is feasible at every state, and the import-cap filter above cannot empty
    # a non-empty list (its threshold is floored at the minimum grid_imported
    # any candidate achieves, so that candidate always survives) --
    # `candidates` is never empty and an IndexError below would be a real bug,
    # not a case to defend against.
    best_index = 0
    best_value = float("-inf")
    for index, candidate in enumerate(candidates):
        if candidate[0] > best_value:
            best_value = candidate[0]
            best_index = index

    _, best_action, best_next_soe, best_new_cost_basis, best_reward, _ = candidates[
        best_index
    ]
    return (
        best_action,
        best_next_soe,
        best_new_cost_basis,
        best_reward,
        _tie_margin(candidates, best_index),
    )


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


def _replay_accounting_pass(
    horizon: int,
    actions: list[float],
    soe_trajectory: list[float],
    initial_cost_basis: float,
    V: np.ndarray,
    soe_levels: np.ndarray,
    buy_price: list[float],
    sell_price: list[float],
    reward_sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings: BatterySettings,
    dt: float,
    currency: str,
    self_throttle_export_threshold_kwh: float,
    import_cap_kwh: float | None = None,
) -> tuple[list[PeriodData], float]:
    """Rebuild PeriodData (and the reward-objective cost) for a given
    (action, SOE) trajectory.

    Only used by the hybrid PWL path (#450): once a tied window's actions have
    been re-solved exactly and spliced in, the accounting produced inline by
    optimize_battery_schedule's selection loop describes the *pre-splice*
    trajectory and must be recomputed. The no-tie path never calls this, so its
    output is bit-for-bit whatever the selection loop produced.

    Rewards are recomputed with the same `_compute_reward` call the selection
    loop's `_best_action_at_continuous_state` makes internally (same explicit
    next_soe, so the SOLAR_EXPORT-below-max bypass replays exactly), against
    `reward_sell_price` -- the DP's own objective -- while the reported
    PeriodData still carries the real `sell_price`.

    `import_cap_kwh` is the same fuse-derived grid-import cap (#429) the
    selection loop optimized against, so the replayed flows describe the same
    throttled grid charging the schedule actually plans.
    """
    hourly_results: list[PeriodData] = []
    reward_objective_cost = 0.0
    cost_basis = initial_cost_basis

    for t in range(horizon):
        soe = soe_trajectory[t]
        next_soe = soe_trajectory[t + 1]
        action_reward, new_cost_basis, _grid_imported = _compute_reward(
            power=actions[t],
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=reward_sell_price,
            solar_production=solar_production[t],
            cost_basis=cost_basis,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
            import_cap_kwh=import_cap_kwh,
        )

        period_data = _build_period_data(
            power=actions[t],
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            new_cost_basis=new_cost_basis,
            currency=currency,
            import_cap_kwh=import_cap_kwh,
            continuation_value=_interpolate_value(V[t + 1], next_soe, battery_settings),
        )

        i = round((soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH)
        i = min(max(0, i), len(soe_levels) - 1)
        if i > 0:
            period_data.decision.shadow_price = float(
                (V[t, i] - V[t, i - 1]) / SOE_STEP_KWH
            )

        hourly_results.append(period_data)
        cost_basis = new_cost_basis
        reward_objective_cost -= action_reward

    return hourly_results, reward_objective_cost


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
    home_settings: HomeSettings | None = None,
    tie_diagnostics: dict | None = None,
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
        home_settings: Home electrical settings (fuse limit, voltage, phases). When
            `power_monitoring_enabled` is set, the DP derives a per-period grid-import
            energy cap and treats it as a hard physical constraint (#429): total import
            (house load + battery charging) may not exceed it, constraining rather than
            excluding a period whose load alone exceeds the cap. Defaults to None (no
            import cap, matching power_monitoring_enabled's own default of False).
        tie_diagnostics: Optional mutable dict. When provided, populated with the
            internal tie-margin/value-slope/window/SoE-trajectory data this
            function already computes, for offline measurement tooling (#450).
            Never passed by production callers; a pure no-op when omitted.

    Returns:
        OptimizationResult with optimal battery schedule
    """

    horizon = len(buy_price)
    dt = period_duration_hours
    import_cap_kwh = _effective_import_cap_kwh(home_settings, dt)

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
    # sell price of 0.0 for the DP's own reward/action-selection calculation
    # only -- backward induction propagates a later period's reward into
    # every earlier period's decision via the continuation value, so leaving
    # this unfixed would make the DP refuse a genuinely profitable earlier
    # action just to avoid a loss that curtailment neutralizes in reality.
    # The real sell_price list (unchanged) is still what gets reported on
    # PeriodData.economic.sell_price below and fed to _build_period_data --
    # BSM's execution-time curtailment trigger reads that field directly, and
    # the displayed plan should show the honest physics-only cost, not the
    # actuation override.
    if export_curtailment_active:
        floor = battery_settings.export_curtailment_price_floor
        reward_sell_price = [0.0 if p < floor else p for p in sell_price]
    else:
        reward_sell_price = sell_price

    # Step 1: Run DP to compute the value-to-go array V. Step 2 recomputes
    # each replay action directly from V (interpolated at the true
    # continuous SoE) rather than looking up a grid-snapped policy table.
    V = _run_dynamic_programming(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=reward_sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        initial_cost_basis=initial_cost_basis,
        dt=dt,
        terminal_value_per_kwh=terminal_value_per_kwh,
        currency=currency,
        max_charge_power_per_period=max_charge_power_per_period,
        self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
        import_cap_kwh=import_cap_kwh,
    )

    # Step 2: Reconstruct the optimal path with continuous SoE propagation.
    # The old approach read period_data from stored_period_data[(t, i)], which
    # reported grid-snapped SoE values (battery_soe_end = soe_levels[next_i]).
    # Here we carry the exact floating-point SoE forward each period so the
    # reported trajectory matches what the simulator will produce (R == P).
    hourly_results = []
    current_soe = initial_soe
    current_cost_basis = initial_cost_basis
    reward_objective_cost = 0.0
    soe_levels = np.arange(
        battery_settings.min_soe_kwh,
        battery_settings.max_soe_kwh + SOE_STEP_KWH,
        SOE_STEP_KWH,
    )
    _, power_levels = _discretize_state_action_space(battery_settings)

    tie_margins: list[float] = []
    # Local marginal value of stored energy (dV/dSoE) at each period's chosen
    # next state -- the scale factor that turns the DP's SOE_STEP_KWH
    # grid-snapping into a value error in currency, which is what the tie
    # detector compares the margins against (#450).
    value_slopes: list[float] = []
    # Trajectory recorded alongside the inline accounting so the hybrid PWL
    # path (#450) can re-solve a tied window and splice it back in. Recording
    # is three list appends per period; nothing downstream reads them unless a
    # tie is actually detected.
    actions: list[float] = []
    soe_trajectory: list[float] = [initial_soe]
    cost_basis_trajectory: list[float] = []
    for t in range(horizon):
        # Recompute the action directly at the true continuous SoE using the
        # already-known V[t+1, :] (linearly interpolated) as the continuation
        # value -- the same reward+max(V) logic as the backward pass, applied
        # at the true state instead of one snapped to the nearest grid index.
        action, next_soe, new_cost_basis, action_reward, tie_margin = (
            _best_action_at_continuous_state(
                soe=current_soe,
                t=t,
                V_next=V[t + 1],
                power_levels=power_levels,
                home_consumption=home_consumption,
                battery_settings=battery_settings,
                dt=dt,
                solar_production=solar_production,
                buy_price=buy_price,
                sell_price=reward_sell_price,
                cost_basis=current_cost_basis,
                max_charge_power_per_period=max_charge_power_per_period,
                discharge_resolution_kw=discharge_resolution_kw,
                self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
                import_cap_kwh=import_cap_kwh,
            )
        )
        tie_margins.append(tie_margin)
        value_slopes.append(_local_value_slope(V[t + 1], next_soe, battery_settings))
        cost_basis_trajectory.append(current_cost_basis)
        actions.append(action)
        soe_trajectory.append(next_soe)

        period_data = _build_period_data(
            power=action,
            soe=current_soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            new_cost_basis=new_cost_basis,
            currency=currency,
            import_cap_kwh=import_cap_kwh,
            # Same continuation-value term _best_action_at_continuous_state
            # added internally to choose this action (dp_battery_algorithm.py
            # _best_action_at_continuous_state's `value = reward +
            # _interpolate_value(...)`), reported here as future_value (#353)
            # instead of being discarded.
            continuation_value=_interpolate_value(V[t + 1], next_soe, battery_settings),
        )

        # Shadow price = marginal opportunity value of stored energy (dV/dSoE),
        # by backward difference at the nearest grid level i (the kWh we
        # would remove by discharging). Unchanged from the previous
        # implementation -- this task only changes action selection, not
        # shadow_price reporting.
        i = round((current_soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH)
        i = min(max(0, i), len(soe_levels) - 1)
        if i > 0:
            period_data.decision.shadow_price = float(
                (V[t, i] - V[t, i - 1]) / SOE_STEP_KWH
            )

        hourly_results.append(period_data)
        current_soe = next_soe
        current_cost_basis = new_cost_basis
        reward_objective_cost -= action_reward

    # Step 2b (#450): hybrid exact resolution of near-tied decisions. The grid
    # DP snaps continuation-value lookups to SOE_STEP_KWH, which is noise on
    # the order of the tie margins recorded above -- so where two actions are
    # near-tied, the grid DP's pick can be an artifact of that snapping rather
    # than economics. Those windows (and only those) are re-solved with the
    # exact continuous-SOE PWL DP, pinned to the grid DP's own SOE at both
    # ends so everything outside the window is untouched.
    #
    # When no window is flagged, nothing below this point runs and the
    # schedule built above is returned bit-for-bit unchanged. That is rare
    # per period (1% of periods flag across the fixture suite) but NOT rare
    # per solve: 8 of 32 fixtures -- a quarter of runs -- flag at least one
    # window, and those runs pay roughly 20-40x the grid DP's latency (e.g.
    # 0.05s -> 1.6s on the #450 fixture). Budget for the slow path being hit
    # on a meaningful fraction of real optimizations, not for it being
    # exceptional. Imported here rather than at module scope because
    # pwl_window_dp imports this module (it reuses this file's reward and
    # transition primitives), so a top-level import would be circular.
    from core.bess.pwl_window_dp import (
        resolve_pwl_window,
        run_pwl_window_backward_induction,
    )
    from core.bess.schedule_splicer import splice_schedule
    from core.bess.tie_detection import detect_tie_windows

    windows = detect_tie_windows(
        tie_margins,
        value_slopes,
        soe_step_kwh=SOE_STEP_KWH,
    )

    if tie_diagnostics is not None:
        tie_diagnostics["tie_margins"] = list(tie_margins)
        tie_diagnostics["value_slopes"] = list(value_slopes)
        tie_diagnostics["windows"] = list(windows)
        tie_diagnostics["soe_trajectory"] = list(soe_trajectory)
        tie_diagnostics["resolved_initial_cost_basis"] = initial_cost_basis

    if windows:
        logger.info(
            "Near-tied DP decisions detected (#450): re-solving %d window(s) "
            "%s with the exact PWL DP",
            len(windows),
            [(w.start, w.end) for w in windows],
        )
        window_resolutions: dict[int, list[tuple[float, float]]] = {}
        for window in windows:
            window_horizon = window.end - window.start
            sl = slice(window.start, window.end)
            window_max_charge = (
                max_charge_power_per_period[sl]
                if max_charge_power_per_period is not None
                else None
            )
            # End SOE is pinned to the grid DP's own SOE at the window's exit,
            # so the untouched schedule after the window stays valid. An
            # infeasible pin raises out of resolve_pwl_window, and a solve
            # that blew one of its accuracy budgets raises
            # PWLWindowUnderRefinedError out of the backward induction --
            # both deliberately not caught. Silently keeping the grid DP's
            # possibly-wrong choice, or splicing in a table whose accuracy the
            # solver itself could not certify, are both exactly the fallback
            # this project forbids.
            #
            # `import_cap_kwh` is the same fuse-derived grid-import cap (#429)
            # the grid DP optimized the rest of the schedule against. It has to
            # be passed here too: the windowed solver re-decides exactly the
            # periods where charging-vs-not is closest, so a window solved
            # without the cap could splice back a grid-charge action that
            # plans more import than the house's fuse can carry -- weakening
            # the constraint precisely where it is most likely to bind.
            V_window = run_pwl_window_backward_induction(
                window_horizon=window_horizon,
                buy_price=buy_price[sl],
                sell_price=reward_sell_price[sl],
                home_consumption=home_consumption[sl],
                solar_production=solar_production[sl],
                battery_settings=battery_settings,
                dt=dt,
                end_soe_target=soe_trajectory[window.end],
                max_charge_power_per_period=window_max_charge,
                self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
                discharge_resolution_kw=discharge_resolution_kw,
                import_cap_kwh=import_cap_kwh,
            )
            window_resolutions[window.start] = resolve_pwl_window(
                V_window,
                start_soe=soe_trajectory[window.start],
                window_horizon=window_horizon,
                buy_price=buy_price[sl],
                sell_price=reward_sell_price[sl],
                home_consumption=home_consumption[sl],
                solar_production=solar_production[sl],
                battery_settings=battery_settings,
                dt=dt,
                cost_basis=cost_basis_trajectory[window.start],
                max_charge_power_per_period=window_max_charge,
                self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
                discharge_resolution_kw=discharge_resolution_kw,
                import_cap_kwh=import_cap_kwh,
            )

        actions, soe_trajectory = splice_schedule(
            actions, soe_trajectory, windows, window_resolutions
        )
        hourly_results, reward_objective_cost = _replay_accounting_pass(
            horizon=horizon,
            actions=actions,
            soe_trajectory=soe_trajectory,
            initial_cost_basis=initial_cost_basis,
            V=V,
            soe_levels=soe_levels,
            buy_price=buy_price,
            sell_price=sell_price,
            reward_sell_price=reward_sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            battery_settings=battery_settings,
            dt=dt,
            currency=currency,
            self_throttle_export_threshold_kwh=self_throttle_export_threshold_kwh,
            import_cap_kwh=import_cap_kwh,
        )

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

    # When export_curtailment_active, the DP's action selection optimized
    # against reward_sell_price (floored), not the real sell_price used
    # above -- so comparing total_optimized_cost/idle_schedule at real
    # price here would be judging the DP's plan by a different objective
    # than the one it was asked to optimize, and could silently discard a
    # plan the DP correctly preferred (confirmed via a randomized sweep
    # against this optimizer, #459 review). Recompute both sides of the
    # guardrail comparison at reward_sell_price so it's internally
    # consistent with the actual objective; the RETURNED idle_schedule
    # (if the guardrail fires) still reports at the real price, unchanged.
    guardrail_optimized_cost = total_optimized_cost
    guardrail_idle_cost = idle_schedule.economic_summary.battery_solar_cost
    if export_curtailment_active:
        # reward_objective_cost is accumulated directly from each period's
        # action_reward (_best_action_at_continuous_state's own return
        # value) -- the exact objective the DP chose actions against, not a
        # reconstruction from reported PeriodData (which could drift from
        # the real per-action reward, e.g. self-throttle export-credit
        # zeroing applying to the reward calc but not to the raw
        # grid_exported energy field).
        guardrail_optimized_cost = reward_objective_cost
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
        reward_objective_cost=reward_objective_cost,
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
