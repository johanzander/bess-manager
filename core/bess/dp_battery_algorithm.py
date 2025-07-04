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
    "OptimizationResult",
    "calculate_hourly_costs",
    "optimize_battery_schedule",
    "print_optimization_results",
    "print_results_table",
]


import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import numpy as np

from core.bess.models import (
    EconomicData,
    EconomicSummary,
    EnergyData,
    HourlyData,
    OptimizationResult,
    StrategyData,
)
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
    hour_data: HourlyData,
    battery_cycle_cost_per_kwh: float = 0.0,
    charge_efficiency: float = 1.0,
    discharge_efficiency: float = 1.0,
) -> CostScenarios:
    """Calculate cost scenarios."""
    
    # Base case: Grid-only (no solar, no battery)
    base_case_cost = hour_data.energy.home_consumed * hour_data.economic.buy_price
    
    # Solar-only case: Solar + grid (no battery)
    direct_solar = min(hour_data.energy.solar_generated, hour_data.energy.home_consumed)
    solar_excess = max(0, hour_data.energy.solar_generated - direct_solar)
    grid_needed = max(0, hour_data.energy.home_consumed - direct_solar)
    solar_only_cost = grid_needed * hour_data.economic.buy_price - solar_excess * hour_data.economic.sell_price
    
    # Battery+solar case: Full optimization
    # EXACT from original: Apply cycle cost only to charging (actual energy stored)
    battery_wear_cost = (
        hour_data.energy.battery_charged * charge_efficiency * battery_cycle_cost_per_kwh
    )
    
    battery_solar_cost = (
        hour_data.energy.grid_imported * hour_data.economic.buy_price
        - hour_data.energy.grid_exported * hour_data.economic.sell_price
        + battery_wear_cost
    )
    
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
        battery_wear_cost=battery_wear_cost,
    )

class StrategicIntent(Enum):
    """Strategic intents for battery actions, determined at decision time."""

    # Primary intents (mutually exclusive)
    GRID_CHARGING = "GRID_CHARGING"  # Storing cheap grid energy for arbitrage
    SOLAR_STORAGE = "SOLAR_STORAGE"  # Storing excess solar for later use
    LOAD_SUPPORT = "LOAD_SUPPORT"  # Discharging to meet home load
    EXPORT_ARBITRAGE = "EXPORT_ARBITRAGE"  # Discharging to grid for profit
    IDLE = "IDLE"  # No significant action (includes natural solar export)


def _discretize_state_action_space(battery_settings: BatterySettings) -> tuple[np.ndarray, np.ndarray]:
    """Discretize state and action spaces - FIXED to return SOE levels."""
    # State space: State of Energy (kWh)
    soe_levels = np.arange(
        battery_settings.min_soc_kwh,
        battery_settings.max_soc_kwh + SOC_STEP_KWH,  # TODO: Rename to SOE_STEP_KWH
        SOC_STEP_KWH,  # TODO: Rename to SOE_STEP_KWH
    )
    
    # Action space: power levels (kW)
    max_power = max(
        battery_settings.max_charge_power_kw,
        battery_settings.max_discharge_power_kw
    )
    power_levels = np.arange(
        -max_power,
        max_power + POWER_STEP_KW,
        POWER_STEP_KW,
    )
    
    return soe_levels, power_levels

    
def _state_transition(
    soe: float,  
    power: float, 
    battery_settings: BatterySettings, 
    dt: float = 1.0
) -> float:
    """
    Calculate the next state of energy based on the current SOE and power action.
    
    Args:
        soe: Current state of energy (kWh) - RENAMED from soc for clarity
        power: Power action (kW), positive for charging, negative for discharging
        battery_settings: BatterySettings instance containing battery parameters
        dt: Time step (hour)

    Returns:
        float: Next state of energy (kWh)
    """
    if power > 0:  # Charging
        charge_energy = power * dt * battery_settings.efficiency_charge
        next_soe = min(battery_settings.max_soc_kwh, soe + charge_energy)
    elif power < 0:  # Discharging
        discharge_energy = abs(power) * dt / battery_settings.efficiency_discharge
        available_energy = soe - battery_settings.min_soc_kwh
        actual_discharge = min(discharge_energy, available_energy)
        next_soe = soe - actual_discharge
    else:  # Hold
        next_soe = soe

    # Double-check bounds for safety
    next_soe = min(
        battery_settings.max_soc_kwh, max(battery_settings.min_soc_kwh, next_soe)
    )
    return next_soe



def _calculate_energy_flows(
    power: float, 
    home_consumption: float, 
    solar_production: float, 
    soe_start: float,  # RENAMED: State of Energy in kWh
    soe_end: float,    # RENAMED: State of Energy in kWh
    battery_settings: BatterySettings,  # ADDED: For SOE->SOC conversion
    dt: float = 1.0,
) -> EnergyData:
    """Calculate detailed energy flows with proper SOE->SOC conversion."""
    from core.bess.models import EnergyData
    
    # Calculate battery energy flows
    battery_charged = max(0, power * dt) if power > 0 else 0.0
    battery_discharged = max(0, -power * dt) if power < 0 else 0.0
    
    # Priority: Solar -> Home first, then remaining solar -> Battery/Grid
    solar_to_home = min(solar_production, home_consumption)
    remaining_solar = solar_production - solar_to_home
    remaining_consumption = home_consumption - solar_to_home
    
    # Solar allocation: battery charging takes priority over grid export
    solar_to_battery = min(remaining_solar, battery_charged) if battery_charged > 0 else 0.0
    solar_to_grid = max(0, remaining_solar - solar_to_battery)
    
    # Grid imports: fill remaining consumption and battery charging
    grid_to_home = max(0, remaining_consumption - battery_discharged) if battery_discharged > 0 else remaining_consumption
    grid_to_battery = max(0, battery_charged - solar_to_battery)
    
    # Battery discharge allocation
    battery_to_home = min(battery_discharged, remaining_consumption) if battery_discharged > 0 else 0.0
    battery_to_grid = max(0, battery_discharged - battery_to_home)
    
    # Calculate total grid flows
    grid_imported = grid_to_home + grid_to_battery
    grid_exported = solar_to_grid + battery_to_grid
    
    # CRITICAL FIX: Convert State of Energy (kWh) to State of Charge (%)
    battery_soc_start_percent = (soe_start / battery_settings.total_capacity) * 100.0
    battery_soc_end_percent = (soe_end / battery_settings.total_capacity) * 100.0
    
    return EnergyData(
        solar_generated=solar_production,
        home_consumed=home_consumption,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        battery_charged=battery_charged,
        battery_discharged=battery_discharged,
        battery_soc_start=battery_soc_start_percent,
        battery_soc_end=battery_soc_end_percent,
        solar_to_home=solar_to_home,
        solar_to_battery=solar_to_battery,
        solar_to_grid=solar_to_grid,
        grid_to_home=grid_to_home,
        grid_to_battery=grid_to_battery,
        battery_to_home=battery_to_home,
        battery_to_grid=battery_to_grid,
    )


def _calculate_reward(
    power: float,
    soe: float,      # RENAMED: State of Energy in kWh
    next_soe: float, # RENAMED: State of Energy in kWh
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
    """Calculate reward with HourlyData and proper SOE->SOC conversion."""
    
    # Get prices for this hour
    current_buy_price = buy_price[hour] if buy_price and hour < len(buy_price) else 0.0
    current_sell_price = sell_price[hour] if sell_price and hour < len(sell_price) else 0.0
    
    # Calculate energy flows with proper SOE->SOC conversion
    energy_data = _calculate_energy_flows(
        power=power,
        home_consumption=home_consumption,
        solar_production=solar_production,
        soe_start=soe,
        soe_end=next_soe,
        battery_settings=battery_settings,
        dt=dt,
    )
    
    # Battery wear cost calculation
    delta_soe = abs(next_soe - soe)
    battery_wear_cost = delta_soe * battery_settings.cycle_cost_per_kwh

    # Cost basis calculation
    new_cost_basis = cost_basis
    
    if power > 0:  # Charging
        charge_energy = power * dt * battery_settings.efficiency_charge
        solar_available = max(0, solar_production - home_consumption)
        solar_to_battery = min(solar_available, power)
        grid_to_battery = max(0, power - solar_to_battery)

        solar_energy_cost = (
            solar_to_battery * dt * battery_settings.efficiency_charge 
            * battery_settings.cycle_cost_per_kwh
        )
        grid_energy_cost = (
            grid_to_battery * dt * battery_settings.efficiency_charge
            * (current_buy_price + battery_settings.cycle_cost_per_kwh)
        )

        total_new_cost = solar_energy_cost + grid_energy_cost
        total_new_energy = charge_energy

        if next_soe > battery_settings.min_soc_kwh:
            new_cost_basis = (soe * cost_basis + total_new_cost) / next_soe
        else:
            new_cost_basis = (
                (total_new_cost / total_new_energy) if total_new_energy > 0 else cost_basis
            )

    elif power < 0:  # Discharging
        if current_sell_price <= cost_basis:
            # Unprofitable discharge
            economic_data = EconomicData(
                buy_price=current_buy_price,
                sell_price=current_sell_price,
                battery_cycle_cost=battery_wear_cost,
                hourly_cost=float("inf"),
                base_case_cost=home_consumption * current_buy_price - max(0, solar_production - home_consumption) * current_sell_price
            )
            strategy_data = StrategyData(
                strategic_intent="IDLE",
                battery_action=power,
                cost_basis=cost_basis
            )
            hour_data = HourlyData(
                hour=hour,
                energy=energy_data,
                timestamp=datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0),
                data_source="predicted",
                economic=economic_data,
                strategy=strategy_data
            )
            return float("-inf"), cost_basis, hour_data

    # Calculate reward
    import_cost = energy_data.grid_imported * current_buy_price
    export_revenue = energy_data.grid_exported * current_sell_price
    reward = -(import_cost - export_revenue + battery_wear_cost)

    # Determine strategic intent
    if power > 0.1:
        if energy_data.grid_to_battery > energy_data.solar_to_battery:
            strategic_intent = "GRID_CHARGING"
        else:
            strategic_intent = "SOLAR_STORAGE"
    elif power < -0.1:
        if energy_data.battery_to_grid > energy_data.battery_to_home:
            strategic_intent = "EXPORT_ARBITRAGE"
        else:
            strategic_intent = "LOAD_SUPPORT"
    else:
        strategic_intent = "IDLE"

    # Create economic and strategy data
    grid_cost = import_cost - export_revenue
    hourly_cost = grid_cost + battery_wear_cost
    base_case_cost = home_consumption * current_buy_price - max(0, solar_production - home_consumption) * current_sell_price
    hourly_savings = base_case_cost - hourly_cost

    economic_data = EconomicData(
        buy_price=current_buy_price,
        sell_price=current_sell_price,
        grid_cost=grid_cost,
        battery_cycle_cost=battery_wear_cost,
        hourly_cost=hourly_cost,
        base_case_cost=base_case_cost,
        hourly_savings=hourly_savings
    )

    strategy_data = StrategyData(
        strategic_intent=strategic_intent,
        battery_action=power,
        cost_basis=new_cost_basis
    )

    new_hourly_data = HourlyData(
        hour=hour,
        energy=energy_data,
        timestamp=datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0),
        data_source="predicted",
        economic=economic_data,
        strategy=strategy_data
    )

    return reward, new_cost_basis, new_hourly_data



def _run_dynamic_programming(
    horizon: int,
    buy_price: list[float] | None,
    sell_price: list[float] | None,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soc: float | None = None,  # NOTE: Actually SOE but kept for compatibility
    initial_cost_basis: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[list[StrategicIntent]]]:
    """Run DP optimization with strategic intent capture - FIXED for SOE/SOC."""
    logger.debug("Starting dynamic programming optimization with strategic intent capture")

    if solar_production is None:
        solar_production = [0.0] * horizon

    if initial_soc is None:
        initial_soe = battery_settings.min_soc_kwh
    else:
        initial_soe = initial_soc  # Parameter name is misleading but value is SOE

    dt = 1.0

    # Discretize state and action spaces
    soe_levels, power_levels = _discretize_state_action_space(battery_settings)
    logger.debug(
        "State space: %d SOE levels from %.2f to %.2f kWh",
        len(soe_levels), soe_levels[0], soe_levels[-1],
    )

    # Create arrays
    V = np.zeros((horizon + 1, len(soe_levels)))
    policy = np.zeros((horizon, len(soe_levels)))
    C = np.full((horizon + 1, len(soe_levels)), initial_cost_basis)
    intents = [
        [StrategicIntent.IDLE for _ in range(len(soe_levels))] for _ in range(horizon)
    ]

    policy.fill(0.0)

    # Backward induction
    for t in reversed(range(horizon)):
        for i, soe in enumerate(soe_levels):
            best_value = float("-inf")
            best_action = 0
            best_cost_basis = C[t, i]
            best_intent = StrategicIntent.IDLE

            for power in power_levels:
                # Skip physically impossible actions
                if power < 0:  # Discharging
                    available_energy = soe - battery_settings.min_soc_kwh
                    max_discharge_power = (
                        available_energy / dt * battery_settings.efficiency_discharge
                    )
                    if abs(power) > max_discharge_power:
                        continue

                elif power > 0:  # Charging
                    available_capacity = battery_settings.max_soc_kwh - soe
                    max_charge_power = (
                        available_capacity / dt / battery_settings.efficiency_charge
                    )
                    if power > max_charge_power:
                        continue

                # Calculate next state
                next_soe = _state_transition(soe, power, battery_settings)

                if (
                    next_soe < battery_settings.min_soc_kwh
                    or next_soe > battery_settings.max_soc_kwh
                ):
                    continue

                # Calculate reward
                reward, new_cost_basis, _ = _calculate_reward(
                    power=power,
                    soe=soe,
                    next_soe=next_soe,
                    hour=t,
                    home_consumption=home_consumption[t],
                    solar_production=solar_production[t] if solar_production else 0,
                    battery_settings=battery_settings,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    cost_basis=C[t, i],
                )

                # Find next state index
                next_i = round((next_soe - battery_settings.min_soc_kwh) / SOC_STEP_KWH)
                next_i = min(max(0, next_i), len(soe_levels) - 1)

                # Total value = immediate reward + future value
                future_value = V[t + 1, next_i] if t + 1 <= horizon else 0
                total_value = reward + future_value

                # Update best action
                if total_value > best_value:
                    best_value = total_value
                    best_action = power
                    best_cost_basis = new_cost_basis

                    # Determine strategic intent
                    if power > 0.1:
                        solar_available = max(0, solar_production[t] - home_consumption[t]) if solar_production else 0
                        if power > solar_available:
                            best_intent = StrategicIntent.GRID_CHARGING
                        else:
                            best_intent = StrategicIntent.SOLAR_STORAGE
                    elif power < -0.1:
                        current_sell_price = sell_price[t] if sell_price and t < len(sell_price) else 0.0
                        if current_sell_price > C[t, i]:
                            best_intent = StrategicIntent.EXPORT_ARBITRAGE
                        else:
                            best_intent = StrategicIntent.LOAD_SUPPORT
                    else:
                        best_intent = StrategicIntent.IDLE

            # Store results
            V[t, i] = best_value
            policy[t, i] = best_action
            if 'next_i' in locals():
                C[t + 1, next_i] = best_cost_basis # type: ignore
            intents[t][i] = best_intent

    # Final safety check
    policy = np.clip(
        policy,
        -battery_settings.max_discharge_power_kw,
        battery_settings.max_charge_power_kw,
    )

    logger.info("Policy bounds check - Max: %.2f, Min: %.2f", policy.max(), policy.min())
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
) -> list[HourlyData]:
    """Simulate battery behavior - FIXED for SOE/SOC conversion."""
    if initial_soc is None:
        initial_soe = battery_settings.min_soc_kwh
    else:
        initial_soe = initial_soc  # Parameter name misleading but value is SOE
        
    if solar_production is None:
        solar_production = [0.0] * horizon

    soe_levels = np.arange(
        battery_settings.min_soc_kwh,
        battery_settings.max_soc_kwh + SOC_STEP_KWH,
        SOC_STEP_KWH,
    )

    simulation_results = []
    current_soe = initial_soe
    current_cost_basis = initial_cost_basis

    logger.debug("Starting battery simulation with initial SOE=%.1f kWh", initial_soe)

    for t in range(horizon):
        # Get policy action
        i = round((current_soe - battery_settings.min_soc_kwh) / SOC_STEP_KWH)
        i = min(max(0, i), len(soe_levels) - 1)
        action = policy[t, i]
        
        # Calculate next SOE
        next_soe = _state_transition(current_soe, action, battery_settings)
        
        # Get HourlyData with proper SOE->SOC conversion
        reward, new_cost_basis, new_hourly_data = _calculate_reward(
            power=action,
            soe=current_soe,
            next_soe=next_soe,
            hour=t,
            home_consumption=home_consumption[t],
            solar_production=solar_production[t],
            battery_settings=battery_settings,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=current_cost_basis,
        )

        simulation_results.append(new_hourly_data)
        current_soe = next_soe
        current_cost_basis = new_cost_basis

        logger.debug(
            "Hour %d: SOE %.1f -> %.1f kWh, Action %.2f kW, Intent %s",
            t, current_soe, next_soe, action,
            new_hourly_data.strategy.strategic_intent,
        )

    logger.debug("Simulation complete with %d HourlyData objects", len(simulation_results))
    return simulation_results

def optimize_battery_schedule(
    buy_price: list[float] | None,
    sell_price: list[float] | None,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soc: float | None = None,
    initial_cost_basis: float | None = None,
) -> OptimizationResult:
    """Optimize battery dispatch schedule using dynamic programming."""
    
    logger.debug("Starting battery optimization with enhanced energy flow analysis")

    # Handle inputs exactly as in original
    if buy_price is None:
        horizon = len(home_consumption)
        buy_price = [0.0] * horizon
    else:
        horizon = len(buy_price)

    if sell_price is None:
        sell_price = [p * 0.7 for p in buy_price]

    if solar_production is None:
        solar_production = [0.0] * horizon

    if initial_soc is None:
        initial_soc = battery_settings.min_soc_kwh

    if initial_cost_basis is None:
        if initial_soc > battery_settings.min_soc_kwh:
            initial_cost_basis = battery_settings.cycle_cost_per_kwh
            logger.warning(
                f"No initial cost basis provided, assuming solar-charged energy: {initial_cost_basis:.3f} SEK/kWh"
            )
        else:
            initial_cost_basis = 0.0

    # Step 1: Run dynamic programming
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

    # Step 2: Simulate battery behavior - get list of HourlyData objects (one per hour)
    logger.debug("Simulating battery behavior with HourlyData objects...")
    hourly_results = _simulate_battery(
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

    # Step 3: Calculate economic summary using the existing calculate_hourly_costs function
    total_base_cost = 0.0
    total_solar_only_cost = 0.0
    total_battery_solar_cost = 0.0
    total_base_to_solar_savings = 0.0
    total_base_to_battery_solar_savings = 0.0
    total_solar_to_battery_solar_savings = 0.0
    total_charged = 0.0
    total_discharged = 0.0

    for h in hourly_results:
        cost_scenarios = calculate_hourly_costs(
            hour_data=h,
            battery_cycle_cost_per_kwh=battery_settings.cycle_cost_per_kwh,
            charge_efficiency=battery_settings.efficiency_charge,
            discharge_efficiency=battery_settings.efficiency_discharge,
        )
        
        # Accumulate totals
        total_base_cost += cost_scenarios.base_case_cost
        total_solar_only_cost += cost_scenarios.solar_only_cost
        total_battery_solar_cost += cost_scenarios.battery_solar_cost
        total_base_to_solar_savings += cost_scenarios.solar_savings
        total_base_to_battery_solar_savings += cost_scenarios.total_savings
        total_solar_to_battery_solar_savings += cost_scenarios.battery_savings
        total_charged += h.energy.battery_charged
        total_discharged += h.energy.battery_discharged

    economic_summary = EconomicSummary(
        base_cost=total_base_cost,
        solar_only_cost=total_solar_only_cost,
        battery_solar_cost=total_battery_solar_cost,
        base_to_solar_savings=total_base_to_solar_savings,
        base_to_battery_solar_savings=total_base_to_battery_solar_savings,
        solar_to_battery_solar_savings=total_solar_to_battery_solar_savings,
        base_to_battery_solar_savings_pct=(
            (total_base_to_battery_solar_savings / total_base_cost) * 100 
            if total_base_cost > 0 else 0
        ),
        total_charged=total_charged,
        total_discharged=total_discharged,
    )

    # Step 4: Return clean OptimizationResult
    return OptimizationResult(
        hourly_data=hourly_results,  
        economic_summary=economic_summary,  
        input_data={
            "buy_price": buy_price,
            "sell_price": sell_price,
            "home_consumption": home_consumption,
            "solar_production": solar_production,
            "initial_soc": initial_soc,
            "initial_cost_basis": initial_cost_basis,
            "horizon": horizon,
        },
    )

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
        "╔════╦════════════╦═════╦══════╦╦═════╦══════╦══════╦════╦══════╦════════════════╦══════╦══════╦══════╗"
    )
    output.append(
        "║ Hr ║  Buy/Sell  ║Cons.║Cost  ║║Sol. ║Sol→B ║Gr→B  ║SoC ║Act.  ║ Strategic      ║ Grid ║ Batt ║ Save ║"
    )
    output.append(
        "║    ║   (SEK)    ║(kWh)║(SEK) ║║(kWh)║(kWh) ║(kWh) ║(%) ║(kW)  ║ Intent         ║(SEK) ║(SEK) ║(SEK) ║"
    )
    output.append(
        "╠════╬════════════╬═════╬══════╬╬═════╬══════╬══════╬════╬══════╬════════════════╬══════╬══════╬══════╣"
    )

    # Process each hour - replicating original logic exactly
    for i, hour_data in enumerate(hourly_data_list):
        hour = hour_data.hour
        consumption = hour_data.home_consumed
        solar = hour_data.solar_generated
        action = hour_data.battery_action or 0.0
        soc_percent = hour_data.battery_soc_end
        intent = hour_data.strategic_intent
        
        # Calculate values exactly like original function
        base_cost = consumption * buy_prices[i] if i < len(buy_prices) else consumption * hour_data.buy_price
        
        # Extract solar flows - try to get from detailed flows if available
        solar_to_battery = 0.0
        grid_to_battery = 0.0
        
        # If we have detailed flow data, use it
        if hasattr(hour_data, 'solar_to_battery'):
            solar_to_battery = hour_data.solar_to_battery
            grid_to_battery = hour_data.grid_to_battery
        else:
            # Fallback: estimate from battery_charged
            solar_to_battery = hour_data.battery_charged if hour_data.battery_charged > 0 else 0
            grid_to_battery = max(0, hour_data.battery_charged - min(solar, hour_data.battery_charged))
        
        # Calculate costs using original logic - FIXED: use property accessor for battery_cycle_cost
        grid_cost = hour_data.grid_imported * hour_data.buy_price - hour_data.grid_exported * hour_data.sell_price
        battery_cost = hour_data.economic.battery_cycle_cost  # FIXED: access via economic component
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
        total_charging += hour_data.battery_charged
        total_discharging += hour_data.battery_discharged

        # Format intent to fit column width
        intent_display = intent[:15] if len(intent) > 15 else intent
        
        # Format hour row - preserving original formatting exactly
        buy_sell_str = f"{buy_prices[i] if i < len(buy_prices) else hour_data.buy_price:.3f}/{sell_prices[i] if i < len(sell_prices) else hour_data.sell_price:.2f}"
        
        output.append(
            f"║{hour:3d} ║{buy_sell_str:10s} ║{consumption:4.1f} ║{base_cost:5.2f} ║║{solar:4.1f} ║{solar_to_battery:5.1f} ║{grid_to_battery:5.1f} ║{soc_percent:3.0f} ║{action:5.1f} ║{intent_display:15s} ║{grid_cost:5.2f} ║{battery_cost:5.2f} ║{hourly_savings:5.2f} ║"
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
        f"      Base case cost:           {economic_results.base_cost:.2f} SEK"
    )
    output.append(
        f"      Optimized cost:           {economic_results.battery_solar_cost:.2f} SEK"
    )
    output.append(
        f"      Total savings:            {economic_results.base_to_battery_solar_savings:.2f} SEK"
    )
    savings_percentage = economic_results.base_to_battery_solar_savings_pct
    output.append(f"      Savings percentage:         {savings_percentage:.1f} %")

    # Log all output in a single call
    logger.info("\n".join(output))