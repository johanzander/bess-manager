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
from core.bess.dp_constants import POWER_STEP_KW, SOE_STEP_KWH
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
    # When soe is already below the minimum floor, _state_transition clamps
    # next_soe up to min_soe_kwh. That delta is a floor artefact, not solar
    # production — treating it as charging would misclassify the period as
    # SOLAR_STORAGE even at 2 am with no sun.
    if soe < battery_settings.min_soe_kwh:
        return 0.0, 0.0
    passive_energy_stored = next_soe - soe
    battery_charged = (
        passive_energy_stored / battery_settings.efficiency_charge
        if passive_energy_stored > 0
        else 0.0
    )
    return battery_charged, 0.0


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

    # Ensure SOE stays within physical bounds
    next_soe = min(
        battery_settings.max_soe_kwh, max(battery_settings.min_soe_kwh, next_soe)
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

    next_soe = np.minimum(max_soe, np.maximum(min_soe, next_soe))
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
) -> np.ndarray:
    """Vectorized form of `_compute_reward`'s reward calculation.

    Only the reward is needed by the DP backward pass (it discards
    `new_cost_basis`), so this omits the cost-basis bookkeeping entirely --
    same simplification the caller already applies to the scalar path
    (`reward, _ = _compute_reward(...)`). Formulas mirror `_compute_reward`
    exactly, branch for branch, for numerical parity. See #236.
    """
    max_soe = battery_settings.max_soe_kwh
    min_soe = battery_settings.min_soe_kwh
    eff_charge = battery_settings.efficiency_charge
    cycle_cost = battery_settings.cycle_cost_per_kwh

    is_charge = power > POWER_TOLERANCE_KW
    is_discharge = power < -POWER_TOLERANCE_KW

    # Battery flows
    battery_charged_active = power * dt
    battery_discharged_active = np.abs(power) * dt

    idle_below_min = soe < min_soe
    passive_energy_stored = next_soe - soe
    idle_battery_charged = np.where(
        (~idle_below_min) & (passive_energy_stored > 0),
        passive_energy_stored / eff_charge,
        0.0,
    )

    battery_charged = np.where(
        is_charge,
        battery_charged_active,
        np.where(is_discharge, 0.0, idle_battery_charged),
    )
    battery_discharged = np.where(is_discharge, battery_discharged_active, 0.0)

    energy_balance = (
        solar_production + battery_discharged - home_consumption - battery_charged
    )
    grid_imported = np.maximum(0.0, -energy_balance)
    grid_exported = np.maximum(0.0, energy_balance)

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
    surplus_exported = np.maximum(0.0, surplus - solar_to_battery)
    grid_imported_store = grid_to_battery + max(
        0.0, home_consumption - solar_production
    )
    grid_exported_store = surplus_exported
    total_cost_store = (
        grid_imported_store * current_buy_price
        - grid_exported_store * current_sell_price
        + battery_wear_cost_store
    )
    reward_store = -total_cost_store

    # Discharging reward -- self-throttling fix (#240): overshoot below
    # BATTERY_EXPORT_THRESHOLD_KWH gets no export credit.
    grid_exported_discharge = np.where(
        grid_exported <= BATTERY_EXPORT_THRESHOLD_KWH, 0.0, grid_exported
    )
    total_cost_discharge = (
        grid_imported * current_buy_price - grid_exported_discharge * current_sell_price
    )
    reward_discharge = -total_cost_discharge

    # IDLE reward
    energy_stored_idle = next_soe - soe
    battery_wear_cost_idle = energy_stored_idle * cycle_cost
    total_cost_idle = (
        grid_imported * current_buy_price
        - grid_exported * current_sell_price
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

    # Battery flows
    if power > POWER_TOLERANCE_KW:  # Active charging
        battery_charged = power * dt
        battery_discharged = 0.0
    elif power < -POWER_TOLERANCE_KW:  # Active discharging
        battery_charged = 0.0
        battery_discharged = abs(power) * dt
    else:  # IDLE — passive solar charging
        battery_charged, battery_discharged = _idle_battery_flows(
            soe, next_soe, battery_settings
        )

    # Grid flows from energy balance
    energy_balance = (
        solar_production + battery_discharged - home_consumption - battery_charged
    )
    grid_imported = max(0, -energy_balance)
    grid_exported = max(0, energy_balance)

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
        surplus_exported = max(0.0, surplus - solar_to_battery)
        grid_imported = grid_to_battery + max(0.0, home_consumption - solar_production)
        grid_exported = surplus_exported

        solar_opportunity_cost = solar_to_battery * current_sell_price
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

        # Self-throttling fix (#240): load-first hardware never actually
        # exports a small discharge overshoot beyond home_consumption -- it
        # delivers only what the home needs. Below BATTERY_EXPORT_THRESHOLD_KWH
        # (the same battery_to_grid boundary decision_intelligence.
        # classify_strategic_intent uses to call something BATTERY_EXPORT vs
        # LOAD_SUPPORT), treat the overshoot as self-throttled: no export
        # credit. At or above it, it's a genuine deliberate export.
        if grid_exported <= BATTERY_EXPORT_THRESHOLD_KWH:
            grid_exported = 0.0

    else:  # IDLE — passive solar charging
        energy_stored = next_soe - soe  # kWh stored in battery after efficiency
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh
        if energy_stored > 0 and next_soe > battery_settings.min_soe_kwh:
            solar_opportunity_cost = battery_charged * current_sell_price
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
) -> PeriodData:
    """Build full PeriodData for the winning action of a DP cell.

    Called once per (t, i) cell after the inner power loop identifies the best action.
    Separated from _compute_reward to eliminate dataclass allocation in the hot path.
    """
    current_buy_price = buy_price[period]
    current_sell_price = sell_price[period]

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
    else:  # IDLE — EXPORT disposition: battery holds, surplus exported
        battery_charged, battery_discharged = _idle_battery_flows(
            soe, next_soe, battery_settings
        )
        battery_action_kwh = power * dt

    energy_balance = (
        solar_production + battery_discharged - home_consumption - battery_charged
    )
    grid_imported = max(0, -energy_balance)
    grid_exported = max(0, energy_balance)

    energy_data = EnergyData(
        solar_production=solar_production,
        home_consumption=home_consumption,
        battery_charged=battery_charged,
        battery_discharged=battery_discharged,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        battery_soe_start=soe,
        battery_soe_end=next_soe,
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
        reward=reward,
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
) -> np.ndarray:
    """
    Run backward induction DP to compute optimal battery control policy.
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

        next_soe = _state_transition_grid(
            soe_col,
            power_row,
            battery_settings,
            dt,
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
        )
        feasible &= (next_soe >= min_soe_kwh) & (next_soe <= max_soe_kwh)

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
        )

        next_i = np.round((next_soe - min_soe_kwh) / SOE_STEP_KWH).astype(np.int64)
        next_i = np.clip(next_i, 0, n_states - 1)

        value = reward + V[t + 1][next_i]
        value = np.where(feasible, value, -np.inf)

        # IDLE is always a feasible, finite-reward action (no physical
        # constraint check applies to it, and _compute_reward_grid never
        # returns -inf), so the max over actions can never remain -inf here.
        V[t, :] = np.max(value, axis=1)

    return V


def _interpolate_value(
    V_row: np.ndarray, soe: float, battery_settings: BatterySettings
) -> float:
    """Linearly interpolate a value-function row (V[t, :]) at a continuous
    SoE, rather than snapping to the nearest discretized grid point."""
    idx = (soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH
    idx = min(max(0.0, idx), len(V_row) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(V_row) - 1)
    frac = idx - lo
    return V_row[lo] * (1 - frac) + V_row[hi] * frac


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
) -> tuple[float, float, float, float]:
    """One-step Bellman recompute at a true continuous SoE, using the
    already-known V[t+1, :] (linearly interpolated) as the continuation
    value -- the same reward+max(V) logic as _run_dynamic_programming's
    backward pass, applied at the true replay state instead of one snapped
    to the nearest grid index. Used by optimize_battery_schedule's Step 2 to
    reconstruct the continuous path without trusting a policy table computed
    for a slightly different state. See
    docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md.

    Returns (best_action, best_next_soe, best_new_cost_basis, best_reward).
    """
    period_max_charge = (
        max_charge_power_per_period[t]
        if max_charge_power_per_period is not None
        else None
    )
    best_value = float("-inf")
    best_action = 0.0
    best_next_soe = soe
    best_new_cost_basis = cost_basis
    best_reward = 0.0
    for power in power_levels:
        if power < -POWER_TOLERANCE_KW:
            available_energy = soe - battery_settings.min_soe_kwh
            max_discharge_power = (
                available_energy / dt * battery_settings.efficiency_discharge
            )
            if abs(power) > max_discharge_power:
                continue
        elif power > POWER_TOLERANCE_KW:
            if period_max_charge is not None and power > period_max_charge:
                continue
            available_capacity = battery_settings.max_soe_kwh - soe
            max_charge_power = (
                available_capacity / dt / battery_settings.efficiency_charge
            )
            if power > max_charge_power:
                continue

        next_soe = _state_transition(
            soe,
            power,
            battery_settings,
            dt,
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
        )
        if (
            next_soe < battery_settings.min_soe_kwh
            or next_soe > battery_settings.max_soe_kwh
        ):
            continue

        reward, new_cost_basis = _compute_reward(
            power=power,
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar_production[t],
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=cost_basis,
        )
        value = reward + _interpolate_value(V_next, next_soe, battery_settings)
        if value > best_value:
            best_value = value
            best_action = power
            best_next_soe = next_soe
            best_new_cost_basis = new_cost_basis
            best_reward = reward
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

    Used as fallback when optimization doesn't meet minimum profit threshold.
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

        energy_balance = solar_production[t] - home_consumption[t] - battery_charged
        energy_data = EnergyData(
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
            battery_charged=battery_charged,
            battery_discharged=0.0,
            grid_imported=max(0, -energy_balance),
            grid_exported=max(0, energy_balance),
            battery_soe_start=current_soe,
            battery_soe_end=next_soe,
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

    # Step 1: Run DP to compute the value-to-go array V. Step 2 recomputes
    # each replay action directly from V (interpolated at the true
    # continuous SoE) rather than looking up a grid-snapped policy table.
    V = _run_dynamic_programming(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        initial_cost_basis=initial_cost_basis,
        dt=dt,
        terminal_value_per_kwh=terminal_value_per_kwh,
        currency=currency,
        max_charge_power_per_period=max_charge_power_per_period,
    )

    # Step 2: Reconstruct the optimal path with continuous SoE propagation.
    # The old approach read period_data from stored_period_data[(t, i)], which
    # reported grid-snapped SoE values (battery_soe_end = soe_levels[next_i]).
    # Here we carry the exact floating-point SoE forward each period so the
    # reported trajectory matches what the simulator will produce (R == P).
    hourly_results = []
    current_soe = initial_soe
    current_cost_basis = initial_cost_basis
    soe_levels = np.arange(
        battery_settings.min_soe_kwh,
        battery_settings.max_soe_kwh + SOE_STEP_KWH,
        SOE_STEP_KWH,
    )
    _, power_levels = _discretize_state_action_space(battery_settings)

    for t in range(horizon):
        # Recompute the action directly at the true continuous SoE using the
        # already-known V[t+1, :] (linearly interpolated) as the continuation
        # value -- the same reward+max(V) logic as the backward pass, applied
        # at the true state instead of one snapped to the nearest grid index.
        action, next_soe, new_cost_basis, _ = _best_action_at_continuous_state(
            soe=current_soe,
            t=t,
            V_next=V[t + 1],
            power_levels=power_levels,
            home_consumption=home_consumption,
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar_production,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=current_cost_basis,
            max_charge_power_per_period=max_charge_power_per_period,
        )

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
    if idle_schedule.economic_summary.battery_solar_cost < total_optimized_cost:
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
