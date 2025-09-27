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
- Minimum profit threshold system to prevent excessive cycling for low-profit actions
- Multi-objective optimization: cost minimization + battery longevity
- Simultaneous energy flow optimization across multiple sources/destinations
- Strategic intent capture at decision time for transparency and hardware control

MINIMUM PROFIT THRESHOLD SYSTEM:
The minimum profit threshold prevents unprofitable battery cycling by raising the cost threshold for charging decisions:
The threshold doesn't require immediate profit, but ensures the complete charge/discharge strategy provides meaningful profit above the penalty level. This prevents excessive cycling for marginal gains while preserving clearly profitable arbitrage opportunities.

Adds fixed penalty (min_action_profit_threshold) to charging actions only during optimization
No penalty on discharging actions - stored energy is always usable without additional threshold costs
Creates minimum profit barrier: charging only occurs when total future benefits exceed all costs (grid + cycle + threshold)
Threshold penalty only affects optimization decisions, not user-facing cost calculations
Default: 1.5 SEK - configurable via battery.min_action_profit_threshold_sek in config.yaml
Example: 1.5 SEK threshold means charging strategies must provide net benefits >1.5 SEK above normal costs to be selected by the optimizer

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
    "optimize_battery_schedule",
    "print_optimization_results",
]


import logging
from datetime import datetime
from enum import Enum

import numpy as np

from core.bess.decision_intelligence import create_decision_data
from core.bess.models import (
    DecisionData,
    EconomicData,
    EconomicSummary,
    EnergyData,
    HourlyData,
    OptimizationResult,
)
from core.bess.settings import BatterySettings

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Algorithm parameters
SOE_STEP_KWH = 0.1
POWER_STEP_KW = 0.2


class StrategicIntent(Enum):
    """Strategic intents for battery actions, determined at decision time."""

    # Primary intents (mutually exclusive)
    GRID_CHARGING = "GRID_CHARGING"  # Storing cheap grid energy for arbitrage
    SOLAR_STORAGE = "SOLAR_STORAGE"  # Storing excess solar for later use
    LOAD_SUPPORT = "LOAD_SUPPORT"  # Discharging to meet home load
    EXPORT_ARBITRAGE = "EXPORT_ARBITRAGE"  # Discharging to grid for profit
    IDLE = "IDLE"  # No significant action (includes natural solar export)


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

    return soe_levels, power_levels


def _state_transition(
    soe: float, power: float, battery_settings: BatterySettings, dt: float = 1.0
) -> float:
    """
    Calculate the next state of energy based on current SOE and power action.

    EFFICIENCY HANDLING:
    - Charging: power x dt x efficiency = energy actually stored
    - Discharging: power x dt / efficiency = energy removed from storage
    This ensures that efficiency losses are properly accounted for in energy balance.
    """
    if power > 0:  # Charging
        # Energy stored = power throughput x charging efficiency
        charge_energy = power * dt * battery_settings.efficiency_charge
        next_soe = min(battery_settings.max_soe_kwh, soe + charge_energy)

    elif power < 0:  # Discharging
        # Energy removed from storage = power throughput ÷ discharging efficiency
        discharge_energy = abs(power) * dt / battery_settings.efficiency_discharge
        available_energy = soe - battery_settings.min_soe_kwh
        actual_discharge = min(discharge_energy, available_energy)
        next_soe = soe - actual_discharge

    else:  # Hold
        next_soe = soe

    # Ensure SOE stays within physical bounds
    next_soe = min(
        battery_settings.max_soe_kwh, max(battery_settings.min_soe_kwh, next_soe)
    )

    return next_soe


def _calculate_reward(
    power: float,
    soe: float,  # State of Energy in kWh
    next_soe: float,  # State of Energy in kWh
    hour: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    solar_production: float = 0.0,
    dt: float = 1.0,
    buy_price: list[float] | None = None,
    sell_price: list[float] | None = None,
    cost_basis: float = 0.0,
    future_prices: list[float] | None = None,
) -> tuple[float, float, HourlyData]:
    """
    Calculate reward with proper cycle cost accounting and CORRECTED discharge profitability checks.

    CYCLE COST POLICY:
    - Applied only to charging operations (not discharging)
    - Applied to energy actually stored (after efficiency losses)
    - Grid costs applied to energy throughput (what you draw from grid)
    - Cost basis includes BOTH grid costs AND cycle costs for profitability analysis

    PROFITABILITY CHECK - CORRECTED:
    - For any discharge, calculate the value of the discharged energy
    - Value = max(avoiding grid purchases, grid export revenue)
    - Discharge only profitable if this value > cost_basis
    - CRITICAL: Must account for discharge efficiency losses

    Example for stored energy costing 2.61 SEK/kWh:
    - If buy_price = 2.58, sell_price = 1.81
    - Avoid purchase value: 2.58 x 0.95 = 2.45 SEK/kWh stored
    - Export value: 1.81 x 0.95 = 1.72 SEK/kWh stored
    - Best value: max(2.45, 1.72) = 2.45 SEK/kWh stored
    - 2.45 < 2.61 → UNPROFITABLE (correctly blocked)
    """

    # Get prices for this hour
    current_buy_price = buy_price[hour] if buy_price and hour < len(buy_price) else 0.0
    current_sell_price = (
        sell_price[hour] if sell_price and hour < len(sell_price) else 0.0
    )

    # Calculate battery flows from power
    battery_charged = max(0, power * dt) if power > 0 else 0.0
    battery_discharged = max(0, -power * dt) if power < 0 else 0.0
    
    # Simple energy balance for grid flows
    energy_balance = solar_production + battery_discharged - home_consumption - battery_charged
    grid_imported = max(0, -energy_balance)
    grid_exported = max(0, energy_balance)
    
    # EnergyData calculates ALL detailed flows automatically
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

    # ============================================================================
    # BATTERY CYCLE COST CALCULATION
    # ============================================================================
    # Apply cycle cost ONLY to charging operations, ONLY to energy actually stored
    energy_stored = 0.0  # Initialize for use in cost basis calculation
    if power > 0:  # Charging
        # Energy actually stored in battery (after efficiency losses)
        energy_stored = power * dt * battery_settings.efficiency_charge
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh

        # Sanity check: energy_stored should equal (next_soe - soe)
        expected_stored = next_soe - soe
        if abs(energy_stored - expected_stored) > 0.01:
            logger.warning(
                f"Energy stored mismatch: calculated={energy_stored:.3f}, "
                f"SOE delta={expected_stored:.3f}"
            )
    else:  # Discharging or idle
        battery_wear_cost = 0.0

    # MINIMUM ACTION PROFIT THRESHOLD
    # ============================================================================
    # Apply fixed penalty ONLY to charging actions (like cycle cost)
    # This prevents low-profit charging while never penalizing use of stored energy
    if power > 0:  # Only charging actions
        action_threshold_penalty = battery_settings.min_action_profit_threshold
    else:
        action_threshold_penalty = 0.0

    # ============================================================================
    # COST BASIS CALCULATION
    # ============================================================================
    # Cost basis includes ALL costs (grid + cycle) for proper profitability analysis
    new_cost_basis = cost_basis

    if power > 0:  # Charging - update cost basis with new energy costs
        # Calculate costs by energy source
        solar_available = max(0, solar_production - home_consumption)
        solar_to_battery = min(
            solar_available, power * dt
        )  # Energy throughput from solar
        grid_to_battery = max(
            0, (power * dt) - solar_to_battery
        )  # Energy throughput from grid

        # Cost components:
        # - Solar energy: "free" in terms of grid cost (but still has cycle cost)
        # - Grid energy: pay buy price for energy drawn from grid
        grid_energy_cost = (
            grid_to_battery * current_buy_price
        )  # Pay for grid throughput

        # Include cycle cost in cost basis for proper profitability analysis
        total_new_cost = (
            grid_energy_cost + battery_wear_cost
        )  # Include both grid and cycle costs
        total_new_energy = energy_stored  # Use actual stored energy for cost basis

        # Update weighted average cost basis
        if next_soe > battery_settings.min_soe_kwh:
            # Weighted average: (existing_energy x old_cost + new_energy x new_cost) / total_energy
            existing_cost = soe * cost_basis
            new_cost_basis = (existing_cost + total_new_cost) / next_soe
        else:
            # Battery was empty, cost basis is just the cost of new energy
            new_cost_basis = (
                (total_new_cost / total_new_energy)
                if total_new_energy > 0
                else cost_basis
            )

    elif power < 0:  # Discharging

        # Discharged energy can be used for:
        # 1. Avoiding grid purchases (saves buy_price per kWh delivered)
        # 2. Grid export (earns sell_price per kWh delivered)
        #
        # The value per kWh of stored energy is the HIGHER of these two options,
        # accounting for discharge efficiency losses.

        # Option 1: Value from avoiding grid purchases
        avoid_purchase_value = current_buy_price * battery_settings.efficiency_discharge

        # Option 2: Value from grid export
        export_value = current_sell_price * battery_settings.efficiency_discharge

        # Take the better option
        effective_value_per_kwh_stored = max(avoid_purchase_value, export_value)

        # Profitability check: only discharge if value exceeds cost
        if effective_value_per_kwh_stored <= cost_basis:
            # This discharge is unprofitable - prevent it
            logger.debug(
                f"Hour {hour}: Unprofitable discharge blocked. "
                f"Buy: {current_buy_price:.3f}, Sell: {current_sell_price:.3f}, "
                f"Avoid value: {avoid_purchase_value:.3f}, Export value: {export_value:.3f}, "
                f"Best value: {effective_value_per_kwh_stored:.3f} <= "
                f"Cost basis: {cost_basis:.3f} SEK/kWh stored"
            )

            # Return negative infinity to prevent this action in optimization
            economic_data = EconomicData(
                buy_price=current_buy_price,
                sell_price=current_sell_price,
                battery_cycle_cost=battery_wear_cost,
                hourly_cost=float("inf"),  # Infinite cost to prevent this action
                grid_only_cost=home_consumption * current_buy_price,
                solar_only_cost=max(0, home_consumption - solar_production)
                * current_buy_price
                - max(0, solar_production - home_consumption) * current_sell_price,
            )
            decision_data = DecisionData(
                strategic_intent="IDLE", battery_action=power, cost_basis=cost_basis
            )
            hour_data = HourlyData(
                hour=hour,
                energy=energy_data,
                timestamp=datetime.now().replace(
                    hour=hour, minute=0, second=0, microsecond=0
                ),
                data_source="predicted",
                economic=economic_data,
                decision=decision_data,
            )
            return float("-inf"), cost_basis, hour_data

    # ============================================================================
    # REWARD CALCULATION
    # ============================================================================

    # Calculate immediate economic reward (negative of total cost)
    import_cost = energy_data.grid_imported * current_buy_price
    export_revenue = energy_data.grid_exported * current_sell_price

    # Total cost = grid costs + battery degradation costs + action threshold penalty
    total_cost = (
        import_cost - export_revenue + battery_wear_cost + action_threshold_penalty
    )
    reward = -total_cost  # Negative cost = positive reward

    # ============================================================================
    # DECISION DATA CREATION
    # ============================================================================

    decision_data = create_decision_data(
        power=power,
        energy_data=energy_data,
        hour=hour,
        cost_basis=new_cost_basis,
        reward=reward,
        import_cost=import_cost,
        export_revenue=export_revenue,
        battery_wear_cost=battery_wear_cost,
        buy_price=current_buy_price,
        sell_price=current_sell_price,
    )

    # ============================================================================
    # ECONOMIC DATA CREATION
    # ============================================================================

    grid_cost = import_cost - export_revenue
    hourly_cost = grid_cost + battery_wear_cost
    grid_only_cost = home_consumption * current_buy_price
    solar_only_cost = (
        max(0, home_consumption - solar_production) * current_buy_price
        - max(0, solar_production - home_consumption) * current_sell_price
    )
    hourly_savings = solar_only_cost - hourly_cost

    economic_data = EconomicData(
        buy_price=current_buy_price,
        sell_price=current_sell_price,
        grid_cost=grid_cost,
        battery_cycle_cost=battery_wear_cost,  # This matches what we calculated above
        hourly_cost=hourly_cost,
        grid_only_cost=grid_only_cost,
        solar_only_cost=solar_only_cost,
        hourly_savings=hourly_savings,
    )

    # ============================================================================
    # CREATE HOURLY DATA OBJECT
    # ============================================================================

    new_hourly_data = HourlyData(
        hour=hour,
        energy=energy_data,
        timestamp=datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0),
        data_source="predicted",
        economic=economic_data,
        decision=decision_data,
    )

    return reward, new_cost_basis, new_hourly_data


def print_optimization_results(results, buy_prices, sell_prices):
    """Log a detailed results table with strategic intents - new format version.

    Args:
        results: OptimizationResult object with hourly_data and economic_summary
        buy_prices: List of buy prices
        sell_prices: List of sell prices
    """
    hourly_data_list = results.hourly_data
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
        "╔════╦════════════╦═════╦══════╦╦═════╦══════╦══════╦═════╦══════╦════════════════╦══════╦══════╦══════╗"
    )
    output.append(
        "║ Hr ║  Buy/Sell  ║Cons.║Cost  ║║Sol. ║Sol→B ║Gr→B  ║ SoE ║Act.  ║ Strategic      ║ Grid ║ Batt ║ Save ║"
    )
    output.append(
        "║    ║   (SEK)    ║(kWh)║(SEK) ║║(kWh)║(kWh) ║(kWh) ║(kWh)║(kW)  ║ Intent         ║(SEK) ║(SEK) ║(SEK) ║"
    )
    output.append(
        "╠════╬════════════╬═════╬══════╬╬═════╬══════╬══════╬════╬══════╬════════════════╬══════╬══════╬══════╣"
    )

    # Process each hour - replicating original logic exactly
    for i, hour_data in enumerate(hourly_data_list):
        hour = hour_data.hour
        consumption = hour_data.energy.home_consumption
        solar = hour_data.energy.solar_production
        action = hour_data.decision.battery_action or 0.0
        soe_kwh = hour_data.energy.battery_soe_end
        intent = hour_data.decision.strategic_intent

        # Calculate values exactly like original function
        base_cost = (
            consumption * buy_prices[i]
            if i < len(buy_prices)
            else consumption * hour_data.economic.buy_price
        )

        # Extract solar flows - try to get from detailed flows if available
        solar_to_battery = 0.0
        grid_to_battery = 0.0

        # If we have detailed flow data, use it
        if hasattr(hour_data, "solar_to_battery"):
            solar_to_battery = hour_data.solar_to_battery
            grid_to_battery = hour_data.grid_to_battery
        else:
            # Fallback: estimate from battery_charged
            solar_to_battery = (
                hour_data.energy.battery_charged
                if hour_data.energy.battery_charged > 0
                else 0
            )
            grid_to_battery = max(
                0,
                hour_data.energy.battery_charged
                - min(solar, hour_data.energy.battery_charged),
            )

        # Calculate costs using original logic - FIXED: use property accessor for battery_cycle_cost
        grid_cost = (
            hour_data.energy.grid_imported * hour_data.economic.buy_price
            - hour_data.energy.grid_exported * hour_data.economic.sell_price
        )
        battery_cost = (
            hour_data.economic.battery_cycle_cost
        )  # FIXED: access via economic component
        combined_cost = grid_cost + battery_cost
        hourly_savings = base_cost - combined_cost

        # Update totals
        total_consumption += consumption
        total_base_cost += base_cost
        total_solar += solar
        total_solar_to_bat += solar_to_battery
        total_grid_to_bat += grid_to_battery
        total_grid_cost += grid_cost
        total_battery_cost += battery_cost
        total_combined_cost += combined_cost
        total_savings += hourly_savings
        total_charging += hour_data.energy.battery_charged
        total_discharging += hour_data.energy.battery_discharged

        # Format intent to fit column width
        intent_display = intent[:15] if len(intent) > 15 else intent

        # Format hour row - preserving original formatting exactly
        buy_sell_str = f"{buy_prices[i] if i < len(buy_prices) else hour_data.buy_price:.2f}/{sell_prices[i] if i < len(sell_prices) else hour_data.sell_price:.2f}"

        output.append(
            f"║{hour:3d} ║ {buy_sell_str:10s} ║{consumption:4.1f} ║{base_cost:5.2f} ║║{solar:4.1f} ║{solar_to_battery:5.1f} ║{grid_to_battery:5.1f} ║{soe_kwh:3.0f} ║{action:5.1f} ║{intent_display:15s} ║{grid_cost:5.2f} ║{battery_cost:5.2f} ║{hourly_savings:5.2f} ║"
        )

    # Add separator and total row
    output.append(
        "╠════╬════════════╬═════╬══════╬╬═════╬══════╬══════╬════╬══════╬════════════════╬══════╬══════╬══════╣"
    )
    output.append(
        f"║Tot ║            ║{total_consumption:4.1f} ║{total_base_cost:5.2f} ║║{total_solar:4.1f} ║{total_solar_to_bat:5.1f} ║{total_grid_to_bat:5.1f} ║    ║C:{total_charging:3.1f} ║                ║{total_grid_cost:5.2f} ║{total_battery_cost:5.2f} ║{total_savings:5.2f} ║"
    )
    output.append(
        f"║    ║            ║     ║      ║║     ║      ║      ║    ║D:{total_discharging:3.1f} ║                ║      ║      ║      ║"
    )
    output.append(
        "╚════╩════════════╩═════╩══════╩╩═════╩══════╩══════╩════╩══════╩════════════════╩══════╩══════╩══════╝"
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


def _run_dynamic_programming_with_storage(
    horizon: int,
    buy_price: list[float] | None,
    sell_price: list[float] | None,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soe: float | None = None,
    initial_cost_basis: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[list[StrategicIntent]], dict]:
    """
    Enhanced DP that stores the HourlyData objects calculated during optimization.
    This eliminates the need for reward recalculation in simulation.
    """

    logger.debug("Starting DP optimization with HourlyData storage")

    # Set defaults if not provided
    if solar_production is None:
        solar_production = [0.0] * horizon
    if initial_soe is None:
        initial_soe = battery_settings.min_soe_kwh

    # Discretize state and action spaces (same as before)
    soe_levels, power_levels = _discretize_state_action_space(battery_settings)

    # Initialize DP arrays (same as before)
    V = np.zeros((horizon + 1, len(soe_levels)))
    policy = np.zeros((horizon, len(soe_levels)))
    C = np.full((horizon + 1, len(soe_levels)), initial_cost_basis)
    intents = [
        [StrategicIntent.IDLE for _ in range(len(soe_levels))] for _ in range(horizon)
    ]

    # NEW: Store HourlyData objects calculated during DP
    stored_hourly_data = {}  # Key: (t, i), Value: HourlyData

    # Backward induction (same structure as before)
    for t in reversed(range(horizon)):
        for i, soe in enumerate(soe_levels):
            best_value = float("-inf")
            best_action = 0
            best_cost_basis = C[t, i]
            best_intent = StrategicIntent.IDLE
            best_hourly_data = None  # NEW: Store the HourlyData from best action

            # Try all possible actions
            for power in power_levels:
                # Skip physically impossible actions (same as before)
                if power < 0:
                    available_energy = soe - battery_settings.min_soe_kwh
                    max_discharge_power = (
                        available_energy / 1.0 * battery_settings.efficiency_discharge
                    )
                    if abs(power) > max_discharge_power:
                        continue
                elif power > 0:
                    available_capacity = battery_settings.max_soe_kwh - soe
                    max_charge_power = (
                        available_capacity / 1.0 / battery_settings.efficiency_charge
                    )
                    if power > max_charge_power:
                        continue

                # Calculate next state
                next_soe = _state_transition(soe, power, battery_settings)
                if (
                    next_soe < battery_settings.min_soe_kwh
                    or next_soe > battery_settings.max_soe_kwh
                ):
                    continue

                # Calculate reward WITH HourlyData creation
                reward, new_cost_basis, hourly_data = _calculate_reward(
                    power=power,
                    soe=soe,
                    next_soe=next_soe,
                    hour=t,
                    home_consumption=home_consumption[t],
                    solar_production=solar_production[t],
                    battery_settings=battery_settings,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    cost_basis=C[t, i],
                )

                # Skip if unprofitable
                if reward == float("-inf"):
                    continue

                # Find next state index
                next_i = round((next_soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH)
                next_i = min(max(0, next_i), len(soe_levels) - 1)

                # Calculate total value
                value = reward + V[t + 1, next_i]

                # Update if better
                if value > best_value:
                    best_value = value
                    best_action = power
                    best_cost_basis = new_cost_basis
                    best_hourly_data = hourly_data  # NEW: Store the HourlyData

                    # Determine strategic intent
                    if power > 0.1:
                        solar_available = max(
                            0, solar_production[t] - home_consumption[t]
                        )
                        if power > solar_available:
                            best_intent = StrategicIntent.GRID_CHARGING
                        else:
                            best_intent = StrategicIntent.SOLAR_STORAGE
                    elif power < -0.1:
                        best_intent = StrategicIntent.LOAD_SUPPORT  # Simplified for now
                    else:
                        best_intent = StrategicIntent.IDLE

            # Store results
            V[t, i] = best_value
            policy[t, i] = best_action
            intents[t][i] = best_intent

            # NEW: Store the HourlyData for this optimal decision
            if best_hourly_data is not None:
                stored_hourly_data[(t, i)] = best_hourly_data

            # Update cost basis for next time step
            if best_action != 0 and t + 1 < horizon:
                next_soe = _state_transition(soe, best_action, battery_settings)
                next_i = round((next_soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH)
                next_i = min(max(0, next_i), len(soe_levels) - 1)
                C[t + 1, next_i] = best_cost_basis

    # Final safety check
    policy = np.clip(
        policy,
        -battery_settings.max_discharge_power_kw,
        battery_settings.max_charge_power_kw,
    )

    return V, policy, C, intents, stored_hourly_data


def optimize_battery_schedule(
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soe: float | None = None,
    initial_cost_basis: float | None = None,
) -> OptimizationResult:
    """
    Battery optimization that eliminates dual cost calculation by using
    DP-calculated HourlyData directly in simulation.
    """

    horizon = len(buy_price)

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
    if initial_soe < battery_settings.min_soe_kwh:
        raise ValueError(
            f"Invalid initial_soe={initial_soe:.1f}kWh below minimum SOE={battery_settings.min_soe_kwh:.1f}kWh"
        )
    
    logger.info(
        f"Starting direct optimization: horizon={horizon}, initial_soe={initial_soe:.1f}, initial_cost_basis={initial_cost_basis:.3f}"
    )

    # Step 1: Run DP with HourlyData storage
    _, _, _, _, stored_hourly_data = _run_dynamic_programming_with_storage(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        initial_cost_basis=initial_cost_basis,
    )

    # Step 2: Extract optimal path results directly from stored DP data
    hourly_results = []
    current_soe = initial_soe
    soe_levels = np.arange(
        battery_settings.min_soe_kwh,
        battery_settings.max_soe_kwh + SOE_STEP_KWH,
        SOE_STEP_KWH,
    )
    
    for t in range(horizon):
        # Find current state index (same logic as simulation)
        i = round((current_soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH)
        i = min(max(0, i), len(soe_levels) - 1)
        
        # Get the HourlyData from DP results - should always exist with valid inputs
        if (t, i) not in stored_hourly_data:
            raise RuntimeError(
                f"Missing DP result for hour {t}, state {i} (SOE={current_soe:.1f}). "
                f"This indicates a bug in the DP algorithm or invalid inputs."
            )
            
        hourly_data = stored_hourly_data[(t, i)]
        hourly_results.append(hourly_data)
        current_soe = hourly_data.energy.battery_soe_end

    # Step 3: Calculate economic summary directly from HourlyData
    total_base_cost = sum(
        home_consumption[i] * buy_price[i] for i in range(len(buy_price))
    )

    total_optimized_cost = sum(h.economic.hourly_cost for h in hourly_results)
    total_charged = sum(h.energy.battery_charged for h in hourly_results)
    total_discharged = sum(h.energy.battery_discharged for h in hourly_results)

    # Calculate savings directly - renamed variables for clarity
    grid_to_battery_solar_savings = total_base_cost - total_optimized_cost

    economic_summary = EconomicSummary(
        grid_only_cost=total_base_cost,
        solar_only_cost=total_base_cost,  # Simplified - no solar in this scenario
        battery_solar_cost=total_optimized_cost,
        grid_to_solar_savings=0.0,  # No solar
        grid_to_battery_solar_savings=grid_to_battery_solar_savings,
        solar_to_battery_solar_savings=grid_to_battery_solar_savings,
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
        f"Savings: {grid_to_battery_solar_savings:.2f} SEK ({economic_summary.grid_to_battery_solar_savings_pct:.1f}%)"
    )

    return OptimizationResult(
        hourly_data=hourly_results,
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
