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
- Profitability checks to prevent unprofitable discharging
- Multi-objective optimization: cost minimization + battery longevity
- Simultaneous energy flow optimization across multiple sources/destinations
- Strategic intent capture at decision time for transparency and hardware control

STRATEGIC INTENT CAPTURE:
The algorithm now captures the strategic reasoning behind each decision:
- GRID_CHARGING: Storing cheap grid energy for arbitrage
- SOLAR_STORAGE: Storing excess solar for later use
- LOAD_SUPPORT: Discharging to meet home load
- EXPORT_ARBITRAGE: Discharging to grid for profit
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
    "CostScenarios",
    "EnergyFlows",
    "calculate_hourly_costs",
    "optimize_battery_schedule",
    "print_results_table",
]


import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from core.bess.settings import BatterySettings

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Algorithm parameters
SOC_STEP_KWH = 0.1
POWER_STEP_KW = 0.2


@dataclass
class EnergyFlows:
    """Standardized energy flow data structure."""
    home_consumption: float
    solar_production: float
    grid_import: float
    grid_export: float
    battery_charged: float
    battery_discharged: float

@dataclass
class CostScenarios:
    """All cost scenarios for one hour."""
    base_case_cost: float
    solar_only_cost: float
    battery_solar_cost: float
    solar_savings: float
    battery_savings: float
    total_savings: float
    battery_wear_cost: float

def calculate_hourly_costs(
    flows: EnergyFlows,
    buy_price: float,
    sell_price: float,
    battery_cycle_cost_per_kwh: float = 0.0,
    charge_efficiency: float = 1.0,
    discharge_efficiency: float = 1.0
) -> CostScenarios:
    """Single source of truth for hourly cost calculations - matches original DP algorithm logic."""
    
    # Base case: Grid-only (no solar, no battery)
    base_case_cost = flows.home_consumption * buy_price
    
    # Solar-only case: Solar + grid (no battery) 
    direct_solar = min(flows.solar_production, flows.home_consumption)
    solar_excess = max(0, flows.solar_production - direct_solar)
    grid_needed = max(0, flows.home_consumption - direct_solar)
    
    solar_only_cost = grid_needed * buy_price - solar_excess * sell_price
    
    # Battery+solar case: Full optimization
    # Apply cycle cost only to charging (actual energy stored)
    battery_wear_cost = flows.battery_charged * charge_efficiency * battery_cycle_cost_per_kwh
    
    battery_solar_cost = flows.grid_import * buy_price - flows.grid_export * sell_price + battery_wear_cost
    
    # Calculate savings
    solar_savings = base_case_cost - solar_only_cost
    battery_savings = solar_only_cost - battery_solar_cost
    total_savings = base_case_cost - battery_solar_cost
    
    return CostScenarios(
        base_case_cost=base_case_cost,
        solar_only_cost=solar_only_cost,
        battery_solar_cost=battery_solar_cost,
        solar_savings=solar_savings,
        battery_savings=battery_savings,
        total_savings=total_savings,
        battery_wear_cost=battery_wear_cost
    )

class StrategicIntent(Enum):
    """Strategic intents for battery actions, determined at decision time."""

    # Primary intents (mutually exclusive)
    GRID_CHARGING = "GRID_CHARGING"  # Storing cheap grid energy for arbitrage
    SOLAR_STORAGE = "SOLAR_STORAGE"  # Storing excess solar for later use
    LOAD_SUPPORT = "LOAD_SUPPORT"  # Discharging to meet home load
    EXPORT_ARBITRAGE = "EXPORT_ARBITRAGE"  # Discharging to grid for profit
    IDLE = "IDLE"  # No significant action (includes natural solar export)


def _determine_action_intent(
    power: float, home_consumption: float, solar_production: float
) -> StrategicIntent:
    """
    Determine the strategic intent for a specific battery action.

    This simply classifies the existing decision without changing the algorithm logic.

    Args:
        power: Battery power action (kW, positive=charge, negative=discharge)
        home_consumption: Home energy consumption for this hour (kWh)
        solar_production: Solar energy production for this hour (kWh)

    Returns:
        StrategicIntent: The primary strategic intent for this action
    """

    # Thresholds for decision classification
    CHARGE_THRESHOLD = 0.1  # kW
    DISCHARGE_THRESHOLD = 0.1  # kW

    if power > CHARGE_THRESHOLD:  # Charging
        # Calculate available solar vs consumption
        solar_for_home = min(solar_production, home_consumption)
        solar_excess = max(0, solar_production - solar_for_home)

        if solar_excess >= power * 0.8:  # At least 80% of charging comes from solar
            return StrategicIntent.SOLAR_STORAGE
        else:
            # Primarily grid charging - this is arbitrage
            return StrategicIntent.GRID_CHARGING

    elif power < -DISCHARGE_THRESHOLD:  # Discharging
        discharge_energy = abs(power)

        # Calculate home load after solar
        solar_for_home = min(solar_production, home_consumption)
        remaining_home_load = max(0, home_consumption - solar_for_home)

        if discharge_energy <= remaining_home_load * 1.2:  # Within 20% of home load
            # Primarily supporting home consumption
            return StrategicIntent.LOAD_SUPPORT
        else:
            # Excess discharge beyond home load - likely export arbitrage
            return StrategicIntent.EXPORT_ARBITRAGE

    else:  # No significant battery action - combine SOLAR_EXPORT and IDLE
        return StrategicIntent.IDLE


def _discretize_state_action_space(
    battery_settings: BatterySettings,
) -> tuple[np.ndarray, np.ndarray]:
    """Create discretized state and action spaces for the DP algorithm.

    Returns:
        Tuple[np.ndarray, np.ndarray]: SoC levels and power levels
    """
    # Discretize SoC into steps
    soc_levels = np.round(
        np.arange(
            battery_settings.min_soc_kwh,
            battery_settings.max_soc_kwh + SOC_STEP_KWH,
            SOC_STEP_KWH,
        ),
        2,
    )

    # Discretize power into steps (negative for discharge, positive for charge)
    power_levels = np.round(
        np.arange(
            -battery_settings.max_discharge_power_kw,
            battery_settings.max_charge_power_kw + POWER_STEP_KW,
            POWER_STEP_KW,
        ),
        2,
    )

    return soc_levels, power_levels


def _state_transition(
    soc: float, power: float, battery_settings: BatterySettings, dt: float = 1.0
) -> float:
    """
    Calculate the next state of charge based on the current SoC and power action.

    Args:
        soc: Current state of charge (kWh)
        power: Power action (kW), positive for charging, negative for discharging
        battery_settings: BatterySettings instance containing battery parameters
        dt: Time step (hour)

    Returns:
        float: Next state of charge (kWh)
    """
    if power > 0:  # Charging
        # Calculate energy with efficiency
        charge_energy = power * dt * battery_settings.efficiency_charge

        # Apply charge but don't exceed max SoC
        next_soc = min(battery_settings.max_soc_kwh, soc + charge_energy)

    elif power < 0:  # Discharging
        # Calculate discharge energy considering efficiency
        discharge_energy = abs(power) * dt / battery_settings.efficiency_discharge

        # Ensure we don't discharge below MIN_SOC
        available_energy = soc - battery_settings.min_soc_kwh
        actual_discharge = min(discharge_energy, available_energy)

        # Apply discharge
        next_soc = soc - actual_discharge

    else:  # Hold (no action)
        next_soc = soc

    # Double-check bounds for safety
    next_soc = min(
        battery_settings.max_soc_kwh, max(battery_settings.min_soc_kwh, next_soc)
    )

    return next_soc


def _calculate_detailed_energy_flows(
    power: float, home_consumption: float, solar_production: float, dt: float = 1.0
) -> dict[str, float]:
    """
    Calculate detailed energy flows showing exactly where each kWh comes from and goes to.

    This function provides the complete breakdown of energy flows for one time step,
    revealing the strategic decisions made by the optimization algorithm.

    Args:
        power: Battery power (kW), positive for charging, negative for discharging
        home_consumption: Home energy consumption (kWh)
        solar_production: Solar energy production (kWh)
        dt: Time step (hour)

    Returns:
        Dict containing detailed energy flows:

        Energy Sources → Destinations:
        - solar_to_home: Direct solar consumption (kWh)
        - solar_to_battery: Solar energy stored in battery (kWh)
        - solar_to_grid: Solar energy exported to grid (kWh)
        - battery_to_home: Battery energy used for home load (kWh)
        - battery_to_grid: Battery energy exported to grid (kWh)
        - grid_to_home: Grid energy used for home load (kWh)
        - grid_to_battery: Grid energy used to charge battery (kWh)

        Totals (for validation):
        - grid_import: Total grid import (grid_to_home + grid_to_battery)
        - grid_export: Total grid export (solar_to_grid + battery_to_grid)
    """
    # Initialize all flows to zero
    flows = {
        "solar_to_home": 0.0,
        "solar_to_battery": 0.0,
        "solar_to_grid": 0.0,
        "battery_to_home": 0.0,
        "battery_to_grid": 0.0,
        "grid_to_home": 0.0,
        "grid_to_battery": 0.0,
        "grid_import": 0.0,
        "grid_export": 0.0,
    }

    # Calculate energy values for this timestep
    charge_energy = max(0, power) * dt
    discharge_energy = max(0, -power) * dt

    # Step 1: Solar first supplies home load (highest priority)
    flows["solar_to_home"] = min(solar_production, home_consumption)
    solar_excess = max(0, solar_production - flows["solar_to_home"])
    remaining_home_consumption = max(0, home_consumption - flows["solar_to_home"])

    # Step 2: Handle battery actions
    if power > 0:  # Charging
        # Solar excess goes to battery first, then grid supplements if needed
        flows["solar_to_battery"] = min(solar_excess, charge_energy)
        flows["grid_to_battery"] = max(0, charge_energy - flows["solar_to_battery"])

        # Remaining solar excess exports to grid
        flows["solar_to_grid"] = max(0, solar_excess - flows["solar_to_battery"])

        # Grid must supply any remaining home consumption
        flows["grid_to_home"] = remaining_home_consumption

    elif power < 0:  # Discharging
        # Battery first supports remaining home load, then exports excess
        flows["battery_to_home"] = min(discharge_energy, remaining_home_consumption)
        flows["battery_to_grid"] = max(0, discharge_energy - flows["battery_to_home"])

        # Grid supplies any remaining home consumption after battery
        flows["grid_to_home"] = max(
            0, remaining_home_consumption - flows["battery_to_home"]
        )

        # All solar excess exports to grid (battery not charging)
        flows["solar_to_grid"] = solar_excess

    else:  # Hold (no battery action)
        # Grid supplies remaining home consumption
        flows["grid_to_home"] = remaining_home_consumption

        # All solar excess exports to grid
        flows["solar_to_grid"] = solar_excess

    # Calculate totals for compatibility with existing code
    flows["grid_import"] = flows["grid_to_home"] + flows["grid_to_battery"]
    flows["grid_export"] = flows["solar_to_grid"] + flows["battery_to_grid"]

    return flows


def _calculate_grid_flows(
    power: float, home_consumption: float, solar_production: float, dt: float = 1.0
) -> tuple[float, float]:
    """
    Calculate grid import and export flows (legacy compatibility function).

    This function maintains compatibility with existing code while the detailed
    flow analysis is handled by _calculate_detailed_energy_flows().

    Args:
        power: Battery power (kW), positive for charging, negative for discharging
        home_consumption: Home energy consumption (kWh)
        solar_production: Solar energy production (kWh)
        dt: Time step (hour)

    Returns:
        Tuple[float, float]: Grid import and export (kWh)
    """
    flows = _calculate_detailed_energy_flows(
        power, home_consumption, solar_production, dt
    )
    return flows["grid_import"], flows["grid_export"]


def _calculate_reward(
    power: float,
    soc: float,
    next_soc: float,
    hour: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    solar_production: float = 0.0,
    dt: float = 1.0,
    charge_bonus: float = 0.0,
    discharge_bonus: float = 0.0,
    buy_price: list[float] | None = None,
    sell_price: list[float] | None = None,
    cost_basis: float = 0.0,
) -> tuple[float, float]:
    """
    Calculate the reward (negative cost) for a given action, including cost basis tracking.

    Returns:
        Tuple of (reward, new_cost_basis) where new_cost_basis is the updated average cost
        of energy in the battery after this action.
    """
    # Calculate grid flows
    grid_import, grid_export = _calculate_grid_flows(
        power, home_consumption, solar_production, dt
    )

    # Calculate battery wear cost
    delta_soc = abs(next_soc - soc)
    battery_wear_cost = delta_soc * battery_settings.cycle_cost_per_kwh

    # Calculate cost basis updates
    if power > 0:  # Charging
        # Determine source of charging energy
        charge_energy = power * dt * battery_settings.efficiency_charge

        # How much comes from solar vs grid?
        solar_available = max(0, solar_production - home_consumption)
        solar_to_battery = min(solar_available, power)
        grid_to_battery = max(0, power - solar_to_battery)

        # Calculate cost of new energy
        # Solar energy only has cycle cost
        solar_energy_cost = (
            solar_to_battery
            * dt
            * battery_settings.efficiency_charge
            * battery_settings.cycle_cost_per_kwh
        )
        # Grid energy has buy price + cycle cost
        grid_energy_cost = (
            grid_to_battery
            * dt
            * battery_settings.efficiency_charge
            * (buy_price[hour] + battery_settings.cycle_cost_per_kwh)
        )

        total_new_cost = solar_energy_cost + grid_energy_cost
        total_new_energy = charge_energy

        # Update weighted average cost basis
        if next_soc > battery_settings.min_soc_kwh:
            new_cost_basis = (soc * cost_basis + total_new_cost) / next_soc
        else:
            # If battery was empty, new cost is just the cost of new energy
            new_cost_basis = (
                (total_new_cost / total_new_energy)
                if total_new_energy > 0
                else cost_basis
            )

    elif power < 0:  # Discharging
        # Check profitability using cost basis
        effective_sell_price = sell_price[hour]

        # Key insight: only discharge if we make a profit
        if (
            effective_sell_price
            <= cost_basis + battery_settings.cycle_cost_per_kwh * 0.5
        ):
            # Not profitable - return very negative reward
            return float("-inf"), cost_basis

        # Cost basis doesn't change on discharge (FIFO would be more accurate but this is simpler)
        new_cost_basis = cost_basis

    else:  # No action
        new_cost_basis = cost_basis

    # Calculate total cost
    import_cost = grid_import * buy_price[hour]
    export_revenue = grid_export * sell_price[hour]
    total_cost = import_cost - export_revenue + battery_wear_cost

    # Reward is negative cost, plus any strategic bonuses
    reward = -total_cost
    if power > 0:
        reward += charge_bonus * abs(power)
    elif power < 0:
        reward += discharge_bonus * abs(power)

    return reward, new_cost_basis


def _run_dynamic_programming(
    horizon: int,
    buy_price: list[float] | None,
    sell_price: list[float] | None,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soc: float | None = None,
    initial_cost_basis: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[list[StrategicIntent]]]:
    """
    Run the dynamic programming optimization algorithm with strategic intent capture.

    Returns:
        Tuple of (V, policy, C, intents) where intents[t][i] is the strategic intent
        for time t and state i.
    """
    logger.debug(
        "Starting dynamic programming optimization with strategic intent capture"
    )

    # Set defaults if not provided
    if solar_production is None:
        solar_production = [0.0] * horizon

    if initial_soc is None:
        initial_soc = battery_settings.min_soc_kwh

    # Define time step (1 hour)
    dt = 1.0

    # Discretize state and action spaces
    soc_levels, power_levels = _discretize_state_action_space(battery_settings)
    logger.debug(
        "State space: %d SOC levels from %.2f to %.2f kWh",
        len(soc_levels),
        soc_levels[0],
        soc_levels[-1],
    )
    logger.debug(
        "Action space: %d power levels from %.2f to %.2f kW",
        len(power_levels),
        power_levels[0],
        power_levels[-1],
    )

    # Create value function array: V[t, i] = expected reward from time t onwards if in state i
    V = np.zeros((horizon + 1, len(soc_levels)))

    # Create policy array: policy[t, i] = optimal action at time t if in state i
    policy = np.zeros((horizon, len(soc_levels)))

    # Create cost basis array: C[t, i] = average cost per kWh at time t in state i
    C = np.full((horizon + 1, len(soc_levels)), initial_cost_basis)

    # Create intent array: intents[t][i] = strategic intent at time t in state i
    intents = [
        [StrategicIntent.IDLE for _ in range(len(soc_levels))] for _ in range(horizon)
    ]

    # Initialize policy with safe values
    policy.fill(0.0)  # Start with no action (hold)

    # Backward induction: from horizon to initial time
    for t in reversed(range(horizon)):
        hour_actions = []

        for i, soc in enumerate(soc_levels):
            best_value = float("-inf")
            best_action = 0
            best_cost_basis = C[t, i]  # Current cost basis
            best_intent = StrategicIntent.IDLE

            # Try all possible actions
            for power in power_levels:
                # Skip physically impossible actions early
                if power < 0:  # Discharging
                    available_energy = soc - battery_settings.min_soc_kwh
                    max_discharge_power = (
                        available_energy / dt * battery_settings.efficiency_discharge
                    )
                    if abs(power) > max_discharge_power:
                        continue

                elif power > 0:  # Charging
                    available_capacity = battery_settings.max_soc_kwh - soc
                    max_charge_power = (
                        available_capacity / dt / battery_settings.efficiency_charge
                    )
                    if power > max_charge_power:
                        continue

                # Calculate next state
                next_soc = _state_transition(soc, power, battery_settings)

                # Skip if transition is invalid
                if (
                    next_soc < battery_settings.min_soc_kwh
                    or next_soc > battery_settings.max_soc_kwh
                ):
                    continue

                # Calculate immediate reward WITH cost basis tracking
                reward, new_cost_basis = _calculate_reward(
                    power=power,
                    soc=soc,
                    next_soc=next_soc,
                    hour=t,
                    home_consumption=home_consumption[t],
                    solar_production=solar_production[t],
                    battery_settings=battery_settings,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    cost_basis=C[t, i],  # Pass current cost basis
                )

                # Skip if reward is -inf (unprofitable discharge)
                if reward == float("-inf"):
                    continue

                # Determine strategic intent for this action
                action_intent = _determine_action_intent(
                    power=power,
                    home_consumption=home_consumption[t],
                    solar_production=solar_production[t],
                )

                # Find index of next state in discretized space
                next_i = round((next_soc - battery_settings.min_soc_kwh) / SOC_STEP_KWH)
                next_i = min(max(0, next_i), len(soc_levels) - 1)

                # Calculate total value (current reward + future value)
                value = reward + V[t + 1, next_i]

                # Update if better
                if value > best_value:
                    best_value = value
                    best_action = power
                    best_cost_basis = new_cost_basis
                    best_intent = action_intent  # Capture the intent at decision time!

            # Ensure best_action is within physical limits
            best_action = np.clip(
                best_action,
                -battery_settings.max_discharge_power_kw,
                battery_settings.max_charge_power_kw,
            )

            # Store best value, action, cost basis, and intent
            V[t, i] = best_value
            policy[t, i] = best_action
            intents[t][i] = best_intent  # Store the strategic intent

            # Propagate cost basis to next time step
            if best_action != 0:
                next_soc = _state_transition(soc, best_action, battery_settings)
                next_i = round((next_soc - battery_settings.min_soc_kwh) / SOC_STEP_KWH)
                next_i = min(max(0, next_i), len(soc_levels) - 1)
                C[t + 1, next_i] = best_cost_basis

            # Record non-zero actions for logging
            if abs(best_action) > 0.01:
                hour_actions.append((i, best_action, best_intent.value))

        # Log significant actions for this hour
        if hour_actions:
            logger.debug(
                "Hour %d (price: %.4f): Found %d profitable actions with intents",
                t,
                buy_price[t],
                len(hour_actions),
            )

    # Trace policy execution for debugging
    trace_soc = initial_soc
    trace_cost_basis = initial_cost_basis
    logger.debug(
        "Tracing policy execution from initial SOC=%.1f kWh, cost basis=%.3f:",
        trace_soc,
        trace_cost_basis,
    )

    for t in range(horizon):
        i = round((trace_soc - battery_settings.min_soc_kwh) / SOC_STEP_KWH)
        i = min(max(0, i), len(soc_levels) - 1)
        action = policy[t, i]
        intent = intents[t][i]

        if abs(action) > 0.01:
            logger.debug(
                "  Hour %d: SOC=%.1f kWh, Action=%.2f kW, Intent=%s, Price=%.4f, Cost basis=%.3f",
                t,
                trace_soc,
                action,
                intent.value,
                buy_price[t],
                trace_cost_basis,
            )

        # Update SOC and cost basis for next hour
        next_soc = _state_transition(trace_soc, action, battery_settings)
        _, trace_cost_basis = _calculate_reward(
            power=action,
            soc=trace_soc,
            next_soc=next_soc,
            hour=t,
            home_consumption=home_consumption[t],
            solar_production=solar_production[t] if solar_production else 0,
            battery_settings=battery_settings,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=trace_cost_basis,
        )
        trace_soc = next_soc

    # Final safety check on policy bounds
    policy = np.clip(
        policy,
        -battery_settings.max_discharge_power_kw,
        battery_settings.max_charge_power_kw,
    )

    max_val = policy.max()
    min_val = policy.min()
    logger.info("Policy bounds check - Max: %.2f, Min: %.2f", max_val, min_val)

    return V, policy, C, intents


def _simulate_battery(
    horizon: int,
    buy_price: list[float] | None,
    sell_price: list[float] | None,
    policy: np.ndarray,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soc: float | None = None,
    V: np.ndarray | None = None,
    C: np.ndarray | None = None,
    initial_cost_basis: float = 0.0,
    intents: list[list[StrategicIntent]] | None = None,
) -> tuple[
    pd.DataFrame,
    list[float],
    list[float],
    dict[str, float],
    list[float],
    dict[str, list],
    list[str],
]:
    """
    Simulate battery behavior using the computed policy with strategic intent tracking.

    This function executes the optimal policy computed by the dynamic programming algorithm,
    tracking all energy flows and strategic decisions to provide comprehensive results
    for analysis and hardware implementation.

    Args:
        horizon: Number of hours to simulate (typically 24)
        buy_price: Electricity purchase prices for each hour (SEK/kWh)
        sell_price: Electricity export prices for each hour (SEK/kWh)
        policy: Optimal battery actions from DP algorithm [horizon x soc_levels]
        home_consumption: Home energy consumption for each hour (kWh)
        battery_settings: Battery physical and economic parameters
        solar_production: Solar energy production for each hour (kWh)
        initial_soc: Starting battery state of charge (kWh)
        V: Value function from DP algorithm (optional)
        C: Cost basis array from DP algorithm (optional)
        initial_cost_basis: Initial average cost per kWh in battery (SEK/kWh)
        intents: Strategic intents from DP algorithm (optional)

    Returns:
        Tuple containing:
        - DataFrame: Complete simulation results with all hourly data
        - List[float]: Battery SOC trace over time (kWh)
        - List[float]: Battery action trace (kW, positive=charge, negative=discharge)
        - Dict[str, float]: Economic analysis results and savings breakdown
        - List[float]: Cost basis evolution over time (SEK/kWh)
        - Dict[str, List]: Detailed energy flows for each hour
        - List[str]: Strategic intent for each hour
    """
    logger.debug("Starting battery simulation with strategic intent tracking")

    # Set defaults if not provided
    if solar_production is None:
        solar_production = [0.0] * horizon

    if initial_soc is None:
        initial_soc = battery_settings.min_soc_kwh

    # Discretize state space (needed to interpret policy)
    soc_levels, _ = _discretize_state_action_space(battery_settings)

    # Initialize tracking arrays
    soc_trace = [initial_soc]
    action_trace = []
    cost_basis_trace = [initial_cost_basis]

    # Initialize detailed energy flow tracking
    energy_flows = {
        "solar_to_home": [],
        "solar_to_battery": [],
        "solar_to_grid": [],
        "battery_to_home": [],
        "battery_to_grid": [],
        "grid_to_home": [],
        "grid_to_battery": [],
    }
    strategic_intents = []

    # Arrays for grid totals (compatibility)
    grid_imports = []
    grid_exports = []

    # Arrays for economic comparison scenarios
    base_case_grid_imports = []
    base_case_grid_exports = []
    base_case_costs = []

    solar_only_grid_imports = []
    solar_only_grid_exports = []
    solar_only_costs = []

    battery_solar_costs = []
    b_costs = []

    # Run forward simulation
    soc = initial_soc
    cost_basis = initial_cost_basis

    for t in range(horizon):
        # Determine action from policy
        if policy.ndim == 2:
            i = round((soc - battery_settings.min_soc_kwh) / SOC_STEP_KWH)
            i = min(max(0, i), len(soc_levels) - 1)
            power = policy[t, i]

            # Get strategic intent if available
            if intents and t < len(intents) and i < len(intents[t]):
                intent = intents[t][i]
            else:
                # Fallback: determine intent from action
                intent = _determine_action_intent(
                    power=power,
                    home_consumption=home_consumption[t],
                    solar_production=solar_production[t],
                )
        else:
            power = policy[t]
            # Determine intent from action for 1D policy
            intent = _determine_action_intent(
                power=power,
                home_consumption=home_consumption[t],
                solar_production=solar_production[t],
            )

        # Apply physical constraints
        if power < 0:  # Discharging
            available_energy = soc - battery_settings.min_soc_kwh
            max_discharge_power = (
                available_energy * battery_settings.efficiency_discharge
            )
            if abs(power) > max_discharge_power:
                power = -max_discharge_power if max_discharge_power > 0 else 0
        elif power > 0:  # Charging
            available_capacity = battery_settings.max_soc_kwh - soc
            max_charge_power = available_capacity / battery_settings.efficiency_charge
            if power > max_charge_power:
                power = max_charge_power if max_charge_power > 0 else 0

        action_trace.append(power)
        strategic_intents.append(intent.value)

        # Calculate next SOC and update cost basis
        next_soc = _state_transition(soc, power, battery_settings)

        # Update cost basis using the same logic as in _calculate_reward
        if power > 0:  # Charging
            # Determine source
            solar_available = max(0, solar_production[t] - home_consumption[t])
            solar_to_battery = min(solar_available, power)
            grid_to_battery = max(0, power - solar_to_battery)

            # Calculate weighted average
            solar_energy = solar_to_battery * battery_settings.efficiency_charge
            grid_energy = grid_to_battery * battery_settings.efficiency_charge

            solar_cost = solar_energy * battery_settings.cycle_cost_per_kwh
            grid_cost = grid_energy * (
                buy_price[t] + battery_settings.cycle_cost_per_kwh
            )

            if next_soc > battery_settings.min_soc_kwh:
                cost_basis = (soc * cost_basis + solar_cost + grid_cost) / next_soc
        # Cost basis doesn't change on discharge or hold

        cost_basis_trace.append(cost_basis)

        # Calculate detailed energy flows for this hour
        hourly_flows = _calculate_detailed_energy_flows(
            power, home_consumption[t], solar_production[t]
        )

        # Store detailed flows
        for flow_key in energy_flows:
            energy_flows[flow_key].append(hourly_flows[flow_key])

        # Store grid totals for compatibility
        grid_imports.append(hourly_flows["grid_import"])
        grid_exports.append(hourly_flows["grid_export"])

        # NEW: Use shared cost calculation function
        flows = EnergyFlows(
            home_consumption=home_consumption[t],
            solar_production=solar_production[t],
            grid_import=hourly_flows["grid_import"],
            grid_export=hourly_flows["grid_export"],
            battery_charged=max(0, power),
            battery_discharged=max(0, -power)
        )
        
        costs = calculate_hourly_costs(
            flows=flows,
            buy_price=buy_price[t],
            sell_price=sell_price[t],
            battery_cycle_cost_per_kwh=battery_settings.cycle_cost_per_kwh,
            charge_efficiency=battery_settings.efficiency_charge,
            discharge_efficiency=battery_settings.efficiency_discharge
        )

        # Store results (preserving existing interface)
        base_case_grid_imports.append(flows.home_consumption)
        base_case_grid_exports.append(0.0)
        base_case_costs.append(costs.base_case_cost)

        solar_only_grid_imports.append(max(0, flows.home_consumption - flows.solar_production))
        solar_only_grid_exports.append(max(0, flows.solar_production - flows.home_consumption))
        solar_only_costs.append(costs.solar_only_cost)

        b_costs.append(costs.battery_wear_cost)
        battery_solar_costs.append(costs.battery_solar_cost)

        # Update SOC for next hour
        soc = next_soc
        soc_trace.append(soc)

        if power != 0:
            logger.debug(
                "Hour %d: Action=%.2f kW, SOC=%.2f kWh, Intent=%s, Cost basis=%.3f SEK/kWh",
                t,
                power,
                soc,
                intent.value,
                cost_basis,
            )

    # Calculate total costs for economic analysis
    base_case_cost = sum(base_case_costs)
    solar_only_cost = sum(solar_only_costs)
    battery_solar_cost = sum(battery_solar_costs)

    # Calculate savings breakdown
    base_to_solar_savings = base_case_cost - solar_only_cost
    base_to_battery_solar_savings = base_case_cost - battery_solar_cost
    solar_to_battery_solar_savings = solar_only_cost - battery_solar_cost

    # Calculate battery activity totals
    total_charged = sum(max(0, action) for action in action_trace)
    total_discharged = sum(max(0, -action) for action in action_trace)

    # Create comprehensive DataFrame with all data
    df = pd.DataFrame(
        {
            "Hour": np.arange(horizon),
            "Buy Price": buy_price,
            "Sell Price": sell_price,
            "Battery Action (kW)": action_trace,
            "Home Consumption": home_consumption,
            "Solar Production": solar_production,
            "Grid Import": grid_imports,
            "Grid Export": grid_exports,
            "State of Charge (SoC)": soc_trace[:-1],
            "Cost Basis (SEK/kWh)": cost_basis_trace[:-1],
            "Strategic Intent": strategic_intents,
            "Base Case Grid Import": base_case_grid_imports,
            "Base Case Grid Export": base_case_grid_exports,
            "Solar Only Grid Import": solar_only_grid_imports,
            "Solar Only Grid Export": solar_only_grid_exports,
            "Base Case Hourly Cost": base_case_costs,
            "Solar Only Hourly Cost": solar_only_costs,
            "Battery+Solar Hourly Cost": battery_solar_costs,
            "B.Cost": b_costs,
            # Add detailed energy flows to DataFrame
            "Solar to Home": energy_flows["solar_to_home"],
            "Solar to Battery": energy_flows["solar_to_battery"],
            "Solar to Grid": energy_flows["solar_to_grid"],
            "Battery to Home": energy_flows["battery_to_home"],
            "Battery to Grid": energy_flows["battery_to_grid"],
            "Grid to Home": energy_flows["grid_to_home"],
            "Grid to Battery": energy_flows["grid_to_battery"],
        }
    )

    # Create economic results dictionary
    economic_results = {
        "base_cost": base_case_cost,
        "solar_only_cost": solar_only_cost,
        "battery_solar_cost": battery_solar_cost,
        "base_to_solar_savings": base_to_solar_savings,
        "base_to_battery_solar_savings": base_to_battery_solar_savings,
        "solar_to_battery_solar_savings": solar_to_battery_solar_savings,
        "percent_savings_from_base_to_solar": (
            (base_to_solar_savings / base_case_cost) * 100 if base_case_cost > 0 else 0
        ),
        "percent_savings_from_base_to_battery_solar": (
            (base_to_battery_solar_savings / base_case_cost) * 100
            if base_case_cost > 0
            else 0
        ),
        "percent_savings_from_solar_to_battery_solar": (
            (solar_to_battery_solar_savings / solar_only_cost) * 100
            if solar_only_cost > 0
            else 0
        ),
        "base_to_battery_solar_savings_pct": (
            (base_to_battery_solar_savings / base_case_cost) * 100
            if base_case_cost > 0
            else 0
        ),
        "total_charged": total_charged,
        "total_discharged": total_discharged,
    }

    logger.debug(
        "Simulation complete: Base cost: %.2f SEK, Battery+Solar cost: %.2f SEK, "
        "Savings: %.2f SEK (%.1f%%), Final cost basis: %.3f SEK/kWh",
        base_case_cost,
        battery_solar_cost,
        base_to_battery_solar_savings,
        economic_results["base_to_battery_solar_savings_pct"],
        cost_basis_trace[-1],
    )

    return (
        df,
        soc_trace,
        action_trace,
        economic_results,
        cost_basis_trace,
        energy_flows,
        strategic_intents,
    )

def optimize_battery_schedule(
    buy_price: list[float] | None,
    sell_price: list[float] | None,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soc: float | None = None,
    initial_cost_basis: float | None = None,
) -> dict[str, Any]:
    """
    Optimize battery dispatch schedule using dynamic programming with strategic intent capture.

    This is the main public interface for the battery optimization algorithm.
    It finds the globally optimal battery charging and discharging schedule
    that minimizes total electricity costs over a 24-hour horizon.

    The algorithm considers:
    - Time-varying electricity buy/sell prices
    - Solar production forecasts
    - Home consumption patterns
    - Battery physical constraints and efficiency losses
    - Battery degradation costs through cycle cost modeling
    - Cost basis tracking for stored energy

    UPDATED: Now captures strategic intent at decision time for transparency and control.

    Args:
        buy_price: Electricity purchase prices for each hour (SEK/kWh)
        sell_price: Electricity export prices for each hour (SEK/kWh)
        home_consumption: Home energy consumption for each hour (kWh)
        battery_settings: Battery physical and economic parameters
        solar_production: Solar energy production for each hour (kWh).
                         If None, assumes no solar generation.
        initial_soc: Initial battery state of charge (kWh).
                    If None, uses minimum SOC from battery_settings.
        initial_cost_basis: Average cost per kWh of energy already in battery (SEK/kWh).
                           If None, assumes solar-charged energy if SOC > min_SOC.

    Returns:
        Dictionary containing comprehensive optimization results:

        'hourly_data': Dict with arrays for each hour containing:
            - 'battery_action': Optimal charge/discharge decisions (kW)
            - 'strategic_intent': Strategic reasoning for each decision
            - 'home_consumption': Home energy consumption (kWh)
            - 'solar_production': Solar energy generation (kWh)
            - 'grid_import': Total grid energy imported (kWh)
            - 'grid_export': Total grid energy exported (kWh)
            - 'state_of_charge': Battery SOC evolution (kWh)
            - Plus economic analysis data for different scenarios

        'energy_flows': Dict with detailed flow breakdowns:
            - 'solar_to_home': Direct solar consumption (kWh)
            - 'solar_to_battery': Solar energy stored (kWh)
            - 'solar_to_grid': Solar energy exported (kWh)
            - 'battery_to_home': Battery energy for home (kWh)
            - 'battery_to_grid': Battery energy exported (kWh)
            - 'grid_to_home': Grid energy for home (kWh)
            - 'grid_to_battery': Grid energy for charging (kWh)

        'strategic_intent': List of strategic intents for each hour:
            - 'GRID_CHARGING': Storing cheap grid energy
            - 'SOLAR_STORAGE': Storing excess solar
            - 'LOAD_SUPPORT': Battery supporting home consumption
            - 'EXPORT_ARBITRAGE': Profitable battery export
            - 'IDLE': No significant activity

        'economic_results': Dict with cost analysis:
            - 'base_cost': Cost with grid-only (no solar/battery)
            - 'solar_only_cost': Cost with solar but no battery
            - 'battery_solar_cost': Cost with optimized solar+battery
            - Savings breakdowns and percentages

        'soc_trace': Battery SOC evolution over time (kWh)
        'action_trace': Battery actions over time (kW)
        'final_cost_basis': Final cost basis for next optimization
        'input_data': All input parameters for reference
    """
    logger.debug(
        "Starting unified battery optimization process with strategic intent capture"
    )

    horizon = len(buy_price)

    # Set defaults if not provided
    if solar_production is None:
        solar_production = [0.0] * horizon

    if initial_soc is None:
        initial_soc = battery_settings.min_soc_kwh

    # Handle initial cost basis
    if initial_cost_basis is None:
        # If no cost basis provided and battery has energy, assume it's solar-charged
        if initial_soc > battery_settings.min_soc_kwh:
            # Assume energy is from solar (only cycle cost, no grid acquisition cost)
            initial_cost_basis = battery_settings.cycle_cost_per_kwh
            logger.warning(
                f"No initial cost basis provided, assuming solar-charged energy: {initial_cost_basis:.3f} SEK/kWh"
            )
        else:
            initial_cost_basis = 0.0

    # Step 1: Run dynamic programming with strategic intent capture
    logger.debug("Running dynamic programming with horizon=%d hours...", horizon)
    V, policy, C, intents = _run_dynamic_programming(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soc=initial_soc,
        battery_settings=battery_settings,
        initial_cost_basis=initial_cost_basis,
    )

    # Step 2: Simulate battery behavior with strategic intent tracking
    logger.debug("Simulating battery behavior with optimized policy...")
    (
        df,
        soc_trace,
        action_trace,
        economic_results,
        cost_basis_trace,
        energy_flows,
        strategic_intents,
    ) = _simulate_battery(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        policy=policy,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soc=initial_soc,
        V=V,
        C=C,
        battery_settings=battery_settings,
        initial_cost_basis=initial_cost_basis,
        intents=intents,
    )

    # Battery parameters for reference
    battery_params = {
        "capacity": battery_settings.total_capacity,
        "min_soc": battery_settings.min_soc_kwh,
        "max_soc": battery_settings.max_soc_kwh,
        "max_charge_power": battery_settings.max_charge_power_kw,
        "max_discharge_power": battery_settings.max_discharge_power_kw,
        "charge_efficiency": battery_settings.efficiency_charge,
        "discharge_efficiency": battery_settings.efficiency_discharge,
        "cycle_cost": battery_settings.cycle_cost_per_kwh,
    }

    # Calculate hourly cost savings
    hourly_savings = df["Base Case Hourly Cost"] - df["Battery+Solar Hourly Cost"]

    # Calculate comprehensive energy flows for easy access
    total_energy_flows = {
        "grid_imports": df["Grid Import"].sum(),
        "grid_exports": df["Grid Export"].sum(),
        "solar_production": sum(solar_production),
        "home_consumption": sum(home_consumption),
        "battery_charged": economic_results["total_charged"],
        "battery_discharged": economic_results["total_discharged"],
        "solar_to_home": sum(energy_flows["solar_to_home"]),
        "solar_to_battery": sum(energy_flows["solar_to_battery"]),
        "solar_to_grid": sum(energy_flows["solar_to_grid"]),
        "battery_to_home": sum(energy_flows["battery_to_home"]),
        "battery_to_grid": sum(energy_flows["battery_to_grid"]),
        "grid_to_home": sum(energy_flows["grid_to_home"]),
        "grid_to_battery": sum(energy_flows["grid_to_battery"]),
    }

    # Extract hourly data from the dataframe for easy access
    hourly_data = {
        "hour": df["Hour"].tolist(),
        "buy_price": df["Buy Price"].tolist(),
        "sell_price": df["Sell Price"].tolist(),
        "battery_action": df["Battery Action (kW)"].tolist(),
        "strategic_intent": strategic_intents,  # Strategic intent for each hour
        "home_consumption": df["Home Consumption"].tolist(),
        "solar_production": df["Solar Production"].tolist(),
        "grid_import": df["Grid Import"].tolist(),
        "grid_export": df["Grid Export"].tolist(),
        "state_of_charge": df["State of Charge (SoC)"].tolist(),
        "base_case_grid_import": df["Base Case Grid Import"].tolist(),
        "base_case_grid_export": df["Base Case Grid Export"].tolist(),
        "solar_only_grid_import": df["Solar Only Grid Import"].tolist(),
        "solar_only_grid_export": df["Solar Only Grid Export"].tolist(),
        "base_case_hourly_cost": df["Base Case Hourly Cost"].tolist(),
        "solar_only_hourly_cost": df["Solar Only Hourly Cost"].tolist(),
        "battery_solar_hourly_cost": df["Battery+Solar Hourly Cost"].tolist(),
        "battery_cost": df["B.Cost"].tolist(),
        "cost_basis": cost_basis_trace[:-1],  # Exclude last value for hourly data
    }

    # Construct comprehensive results dictionary
    results = {
        "hourly_data": hourly_data,
        "energy_flows": energy_flows,
        "strategic_intent": strategic_intents,
        "economic_results": economic_results,
        "soc_trace": soc_trace,
        "action_trace": action_trace,
        "hourly_savings": hourly_savings.tolist(),
        "total_energy_flows": total_energy_flows,
        "final_cost_basis": cost_basis_trace[-1],
        "input_data": {
            "battery_params": battery_params,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "home_consumption": home_consumption,
            "solar_production": solar_production,
            "initial_soc": initial_soc,
            "initial_cost_basis": initial_cost_basis,
            "horizon": horizon,
        },
    }

    # Construct summary dict for compatibility
    summary = {
        "baseCost": economic_results.get("base_cost", 0),
        "optimizedCost": economic_results.get("battery_solar_cost", 0),
        "gridCosts": economic_results.get("base_cost", 0)
        - economic_results.get("base_to_solar_savings", 0),
        "batteryCosts": 0,
        "savings": economic_results.get("solar_to_battery_solar_savings", 0),
        "solarOnlyCost": economic_results.get("solar_only_cost", 0),
        "solarOnlySavings": economic_results.get("base_to_solar_savings", 0),
        "batterySavings": economic_results.get("solar_to_battery_solar_savings", 0),
        "solarSavings": economic_results.get("base_to_solar_savings", 0),
        "arbitrageSavings": economic_results.get("base_to_battery_solar_savings", 0),
        "totalSolarProduction": total_energy_flows.get("solar_production", 0),
        "totalBatteryCharge": economic_results.get("total_charged", 0),
        "totalBatteryDischarge": economic_results.get("total_discharged", 0),
        "totalGridImport": total_energy_flows.get("grid_imports", 0),
        "totalGridExport": total_energy_flows.get("grid_exports", 0),
        "cycleCount": (
            (economic_results.get("total_charged", 0) / battery_settings.total_capacity)
            if battery_settings.total_capacity
            else 0
        ),
    }
    results["summary"] = summary

    # Log strategic intent summary
    intent_counts = {}
    for intent in strategic_intents:
        intent_counts[intent] = intent_counts.get(intent, 0) + 1

    logger.info("Strategic intent summary: %s", intent_counts)
    logger.info("Battery optimization process completed successfully")

    return results


def print_results_table(hourly_data, economic_results, buy_prices, sell_prices):
    """Log a detailed results table with strategic intents."""
    horizon = len(hourly_data["hour"])

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
        "╔════╦════════════╦═════╦══════╦╦═════╦══════╦══════╦════╦══════╦════════════════╦══════╦══════╦══════╗"
    )
    output.append(
        "║ Hr ║  Buy/Sell  ║Cons.║Cost  ║║Sol. ║Sol→B ║Gr→B  ║SoC ║Act.  ║Strategic Intent║G.Cst ║B.Cst ║ Save ║"
    )
    output.append(
        "╠════╬════════════╬═════╬══════╬╬═════╬══════╬══════╬════╬══════╬════════════════╬══════╬══════╬══════╣"
    )

    # Process each hour
    for t in range(horizon):
        hour_str = f"{hourly_data['hour'][t]:02d}"
        buy = buy_prices[t]
        sell = sell_prices[t]
        price_str = f"{buy:5.2f}/{sell:5.2f}"
        consumption = hourly_data["home_consumption"][t]
        base_cost = hourly_data["base_case_hourly_cost"][t]
        solar = hourly_data["solar_production"][t]
        action = hourly_data["battery_action"][t]
        soc = hourly_data["state_of_charge"][t]
        grid_import = hourly_data["grid_import"][t]
        grid_export = hourly_data["grid_export"][t]
        battery_cost = hourly_data["battery_cost"][t]
        grid_cost = grid_import * buy - grid_export * sell
        total_cost = hourly_data["battery_solar_hourly_cost"][t]
        intent = hourly_data.get("strategic_intent", ["IDLE"] * horizon)[t]

        # Calculate solar to battery and grid to battery
        solar_for_home = min(solar, consumption)
        solar_left = max(0, solar - solar_for_home)

        if action > 0:  # Charging
            solar_to_bat = min(solar_left, action)
            grid_to_bat = max(0, action - solar_to_bat)
            total_charging += action
        else:
            solar_to_bat = 0
            grid_to_bat = 0
            if action < 0:
                total_discharging -= action  # Convert to positive

        # Calculate savings
        savings = base_cost - total_cost

        # Update totals
        total_consumption += consumption
        total_base_cost += base_cost
        total_solar += solar
        total_solar_to_bat += solar_to_bat
        total_grid_to_bat += grid_to_bat
        total_grid_cost += grid_cost
        total_battery_cost += battery_cost
        total_combined_cost += total_cost
        total_savings += savings

        # Truncate intent for display
        intent_display = intent[:14] if len(intent) > 14 else intent

        # Append row to output
        output.append(
            f"║{hour_str:>3} ║{price_str:^10} ║{consumption:5.1f}║{base_cost:6.2f}║║{solar:5.1f}║{solar_to_bat:6.1f}║{grid_to_bat:6.1f}║{soc:4.1f}║{action:6.1f}║{intent_display:^16}║{grid_cost:6.2f}║{battery_cost:6.2f}║{savings:6.2f}║"
        )

    # Append totals to output
    output.append(
        "╠════╬════════════╬═════╬══════╬╬═════╬══════╬══════╬════╬══════╬════════════════╬══════╬══════╬══════╣"
    )
    output.append(
        f"║TOT ║            ║{total_consumption:5.1f}║{total_base_cost:6.2f}║║{total_solar:5.1f}║{total_solar_to_bat:6.1f}║{total_grid_to_bat:6.1f}║    ║C:{total_charging:4.1f}║                ║{total_grid_cost:6.2f}║{total_battery_cost:6.2f}║{total_savings:6.2f}║"
    )
    output.append(
        f"║    ║            ║     ║      ║║     ║      ║      ║    ║D:{total_discharging:4.1f}║                ║      ║      ║      ║"
    )
    output.append(
        "╚════╩════════════╩═════╩══════╩╩═════╩══════╩══════╩════╩══════╩════════════════╩══════╩══════╩══════╝"
    )

    # Append summary stats to output
    output.append("\n      Summary:")
    output.append(
        f"      Base case cost:           {economic_results['base_cost']:.2f} SEK"
    )
    output.append(
        f"      Optimized cost:           {economic_results['battery_solar_cost']:.2f} SEK"
    )
    output.append(
        f"      Total savings:            {economic_results['base_to_battery_solar_savings']:.2f} SEK"
    )
    savings_percentage = economic_results["base_to_battery_solar_savings_pct"]
    output.append(f"      Savings percentage:         {savings_percentage:.1f} %")

    # Log all output in a single call
    logger.info("\n".join(output))

