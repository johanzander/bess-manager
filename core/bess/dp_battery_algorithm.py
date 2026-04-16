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
The minimum profit threshold prevents unprofitable battery operations through a post-optimization profitability gate.
After optimization completes, the total savings are compared against an effective threshold derived from the configured
value scaled proportionally to the remaining horizon fraction:

    effective_threshold = min_action_profit_threshold * max(THRESHOLD_HORIZON_FLOOR, horizon / total_periods)

- If total_savings >= effective_threshold: Execute the optimized schedule
- If total_savings < effective_threshold: Reject optimization and use all-IDLE schedule (do nothing)

The scaling ensures the bar is proportional to how much of the day remains. A run at midnight faces the full threshold;
a run at 20:00 with only 4 hours left faces roughly 1/6 of it. Without scaling, late-day runs are held to an
unreachable standard and legitimate evening discharge opportunities get blocked.

THRESHOLD_HORIZON_FLOOR (0.15) prevents the effective threshold from collapsing to near-zero at end of day, which
would allow the battery to cycle for trivially small gains in the final hour or two.

Configurable via battery.min_action_profit_threshold in config.yaml (in your currency).
Example: a threshold of 8.0 at 16:00 (8/24 remaining) becomes an effective threshold of 8.0 * 0.33 = 2.67

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
from enum import Enum

import numpy as np

from core.bess.decision_intelligence import create_decision_data
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


def _compute_idle_solar_charging(
    solar_production: float,
    home_consumption: float,
    soe: float,
    battery_settings: BatterySettings,
    dt: float,
) -> tuple[float, float]:
    """Compute implicit solar charging from excess solar production.

    In all Growatt operating modes (load_first, battery_first), excess solar
    charges the battery before exporting to grid. This function computes the
    minimum solar charging that occurs regardless of the DP's power action:

    - IDLE (power=0) / load_first: excess solar charges battery automatically.
    - Discharge (power<0) with solar >= consumption: hardware overrides discharge,
      charges from excess solar instead.
    - Charging (power>0) / battery_first: hardware charges from at least all
      excess solar. The DP's power determines any additional grid charging.

    Args:
        solar_production: Solar energy produced this period (kWh).
        home_consumption: Home energy consumed this period (kWh).
        soe: Current state of energy (kWh).
        battery_settings: Battery configuration.
        dt: Period duration in hours.

    Returns:
        (battery_charged, actual_energy_stored) where battery_charged is the
        energy drawn from solar (pre-efficiency) and actual_energy_stored is
        the energy added to the battery (post-efficiency).
    """
    excess_solar = max(0.0, solar_production - home_consumption)
    charge_rate_limit = battery_settings.max_charge_power_kw * dt
    available_capacity = max(
        0.0,
        (battery_settings.max_soe_kwh - soe) / battery_settings.efficiency_charge,
    )
    battery_charged = min(excess_solar, charge_rate_limit, available_capacity)
    actual_energy_stored = battery_charged * battery_settings.efficiency_charge
    return battery_charged, actual_energy_stored


def _state_transition(
    soe: float,
    power: float,
    battery_settings: BatterySettings,
    dt: float,
    solar_production: float = 0.0,
    home_consumption: float = 0.0,
) -> float:
    """
    Calculate the next state of energy based on current SOE and power action.

    EFFICIENCY HANDLING:
    - Charging: power x dt x efficiency = energy actually stored
    - Discharging: power x dt / efficiency = energy removed from storage
    This ensures that efficiency losses are properly accounted for in energy balance.

    IMPLICIT SOLAR CHARGING:
    In all Growatt modes, excess solar charges the battery. When solar >= consumption,
    discharge commands are overridden by hardware. When power > 0 (battery_first mode),
    the hardware charges from at least all excess solar regardless of the DP's power
    setting — the DP's power only determines additional grid charging.
    """
    if power > 0:  # Charging (battery_first mode on hardware)
        # In battery_first mode, hardware charges from at least all excess solar.
        # The DP's power determines any additional grid charging beyond solar.
        _, solar_stored = _compute_idle_solar_charging(
            solar_production, home_consumption, soe, battery_settings, dt
        )
        dp_stored = power * dt * battery_settings.efficiency_charge
        charge_energy = max(dp_stored, solar_stored)
        next_soe = min(battery_settings.max_soe_kwh, soe + charge_energy)

    elif power < 0 and solar_production < home_consumption:  # Discharging (no excess solar)
        # Energy removed from storage = power throughput ÷ discharging efficiency
        discharge_energy = abs(power) * dt / battery_settings.efficiency_discharge
        available_energy = soe - battery_settings.min_soe_kwh
        actual_discharge = min(discharge_energy, available_energy)
        next_soe = soe - actual_discharge

    else:  # Hold / discharge overridden by solar — implicit solar charging
        _, actual_energy_stored = _compute_idle_solar_charging(
            solar_production, home_consumption, soe, battery_settings, dt
        )
        next_soe = soe + actual_energy_stored

    # Ensure SOE stays within physical bounds
    next_soe = min(
        battery_settings.max_soe_kwh, max(battery_settings.min_soe_kwh, next_soe)
    )

    return next_soe


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

    PROFITABILITY CHECK:
    - For any discharge, calculate the value of the discharged energy
    - Value = max(avoiding grid purchases, grid export revenue)
    - Discharge only profitable if this value > cost_basis
    - Must account for discharge efficiency losses

    Example for stored energy costing 2.61/kWh:
    - If buy_price = 2.58, sell_price = 1.81
    - Avoid purchase value: 2.58 x 0.95 = 2.45/kWh stored
    - Export value: 1.81 x 0.95 = 1.72/kWh stored
    - Best value: max(2.45, 1.72) = 2.45/kWh stored
    - 2.45 < 2.61 → UNPROFITABLE (correctly blocked)

    Returns:
        (reward, new_cost_basis) or (float("-inf"), cost_basis) if discharge is unprofitable.
    """
    current_buy_price = buy_price[period]
    current_sell_price = sell_price[period]

    # Use same tolerance as main DP loop to handle floating-point imprecision from np.arange
    # (e.g., intended 0.0 may be -5.33e-14, which must be treated as IDLE, not discharge)
    _power_tolerance = 0.001  # kW

    # Battery flows
    # In load_first mode, solar covers home first. When solar >= consumption,
    # excess solar charges battery — any discharge command is overridden by hardware.
    _discharge_effective = (
        power < -_power_tolerance and solar_production < home_consumption
    )

    if power > _power_tolerance:
        # In battery_first mode, hardware charges from at least all excess solar.
        solar_charged_implicit, _ = _compute_idle_solar_charging(
            solar_production, home_consumption, soe, battery_settings, dt
        )
        battery_charged = max(power * dt, solar_charged_implicit)
        battery_discharged = 0.0
    elif _discharge_effective:
        battery_charged = 0.0
        battery_discharged = abs(power) * dt
    else:
        # IDLE or discharge overridden by solar: implicit solar charging
        battery_charged, _ = _compute_idle_solar_charging(
            solar_production, home_consumption, soe, battery_settings, dt
        )
        battery_discharged = 0.0

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

    if power > _power_tolerance:  # Charging
        energy_stored = battery_charged * battery_settings.efficiency_charge
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh

        solar_available = max(0, solar_production - home_consumption)
        solar_to_battery = min(solar_available, battery_charged)
        grid_to_battery = max(0, battery_charged - solar_to_battery)
        grid_energy_cost = grid_to_battery * current_buy_price
        total_new_cost = grid_energy_cost + battery_wear_cost

        if next_soe > battery_settings.min_soe_kwh:
            existing_cost = soe * cost_basis
            new_cost_basis = (existing_cost + total_new_cost) / next_soe
        else:
            new_cost_basis = (
                (total_new_cost / energy_stored) if energy_stored > 0 else cost_basis
            )

    elif _discharge_effective:  # Discharging (solar < consumption)
        battery_wear_cost = 0.0

        # Profitability check: only discharge if value exceeds cost basis
        avoid_purchase_value = current_buy_price * battery_settings.efficiency_discharge
        export_value = current_sell_price * battery_settings.efficiency_discharge
        effective_value_per_kwh_stored = max(avoid_purchase_value, export_value)

        if effective_value_per_kwh_stored <= cost_basis:
            return float("-inf"), cost_basis

    else:  # Idle / discharge overridden by solar — cycle wear on solar charging
        actual_energy_stored = battery_charged * battery_settings.efficiency_charge
        battery_wear_cost = actual_energy_stored * battery_settings.cycle_cost_per_kwh

        if actual_energy_stored > 0 and next_soe > battery_settings.min_soe_kwh:
            existing_cost = soe * cost_basis
            # Solar energy has zero marginal cost; only cycle wear contributes
            new_cost_basis = (existing_cost + battery_wear_cost) / next_soe

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

    # In load_first mode, when solar >= consumption, discharge is overridden —
    # excess solar charges battery instead. Same logic as _compute_reward.
    _discharge_effective = power < 0 and solar_production < home_consumption

    if power > 0:
        # In battery_first mode, hardware charges from at least all excess solar.
        solar_charged_implicit, _ = _compute_idle_solar_charging(
            solar_production, home_consumption, soe, battery_settings, dt
        )
        battery_charged = max(power * dt, solar_charged_implicit)
        battery_discharged = 0.0
    elif _discharge_effective:
        battery_charged = 0.0
        battery_discharged = abs(power) * dt
    else:
        # IDLE or discharge overridden by solar: implicit solar charging
        battery_charged, _ = _compute_idle_solar_charging(
            solar_production, home_consumption, soe, battery_settings, dt
        )
        battery_discharged = 0.0

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

    if power > 0:  # Charging
        energy_stored = battery_charged * battery_settings.efficiency_charge
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh

        expected_stored = next_soe - soe
        if abs(energy_stored - expected_stored) > 0.01:
            logger.warning(
                f"Energy stored mismatch: calculated={energy_stored:.3f}, "
                f"SOE delta={expected_stored:.3f}"
            )
    elif not _discharge_effective and battery_charged > 0:  # Solar charging (IDLE or overridden discharge)
        actual_energy_stored = battery_charged * battery_settings.efficiency_charge
        battery_wear_cost = actual_energy_stored * battery_settings.cycle_cost_per_kwh
    else:
        battery_wear_cost = 0.0

    import_cost = grid_imported * current_buy_price
    export_revenue = grid_exported * current_sell_price
    total_cost = import_cost - export_revenue + battery_wear_cost
    reward = -total_cost

    decision_data = create_decision_data(
        power=power,
        energy_data=energy_data,
        hour=period,
        cost_basis=new_cost_basis,
        reward=reward,
        import_cost=import_cost,
        export_revenue=export_revenue,
        battery_wear_cost=battery_wear_cost,
        buy_price=current_buy_price,
        sell_price=current_sell_price,
        dt=dt,
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
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """
    Enhanced DP that stores the PeriodData objects calculated during optimization.
    This eliminates the need for reward recalculation in simulation.
    """

    logger.debug("Starting DP optimization with PeriodData storage")

    # Set defaults if not provided
    if solar_production is None:
        solar_production = [0.0] * horizon
    if initial_soe is None:
        initial_soe = battery_settings.min_soe_kwh

    # Discretize state and action spaces (same as before)
    soe_levels, power_levels = _discretize_state_action_space(battery_settings)

    # Initialize DP arrays (same as before)
    V = np.zeros((horizon + 1, len(soe_levels)))

    # Terminal value: assign value to usable energy remaining at end of horizon
    if terminal_value_per_kwh > 0.0:
        for i, soe in enumerate(soe_levels):
            usable_energy = soe - battery_settings.min_soe_kwh
            V[horizon, i] = max(0.0, usable_energy) * terminal_value_per_kwh

    policy = np.zeros((horizon, len(soe_levels)))
    C = np.full((horizon + 1, len(soe_levels)), initial_cost_basis)

    # Store PeriodData objects calculated during DP
    stored_period_data = {}  # Key: (t, i), Value: PeriodData

    # Backward induction (same structure as before)
    for t in reversed(range(horizon)):
        for i, soe in enumerate(soe_levels):
            best_value = float("-inf")
            best_action = 0
            best_new_cost_basis = C[t, i]
            best_next_soe = soe  # tracked for _build_period_data after inner loop

            # Per-period charge power limit (from temperature derating or None)
            period_max_charge = (
                max_charge_power_per_period[t]
                if max_charge_power_per_period is not None
                else None
            )

            # Try all possible actions
            for power in power_levels:
                # Skip physically impossible actions (same as before)
                # Use tolerance for near-zero power due to floating-point precision in np.arange
                # (e.g., "0.0" might be 2.2e-16 which would incorrectly match "power > 0")
                power_tolerance = 0.001  # kW
                if power < -power_tolerance:  # Discharging
                    available_energy = soe - battery_settings.min_soe_kwh
                    max_discharge_power = (
                        available_energy / dt * battery_settings.efficiency_discharge
                    )
                    if abs(power) > max_discharge_power:
                        continue
                elif power > power_tolerance:  # Charging
                    # Apply temperature derating limit if provided
                    if period_max_charge is not None and power > period_max_charge:
                        continue

                    available_capacity = battery_settings.max_soe_kwh - soe
                    max_charge_power = (
                        available_capacity / dt / battery_settings.efficiency_charge
                    )
                    if power > max_charge_power:
                        continue
                # else: IDLE (near-zero power) - no physical constraints to check

                # Calculate next state
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

                # Compute reward scalars only — no dataclass allocation in hot path
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
                    best_new_cost_basis = new_cost_basis
                    best_next_soe = next_soe

            # Store results
            V[t, i] = best_value
            policy[t, i] = best_action

            # Build PeriodData once for the winning action (not in the hot path)
            if best_value > float("-inf"):
                stored_period_data[(t, i)] = _build_period_data(
                    power=best_action,
                    soe=soe,
                    next_soe=best_next_soe,
                    period=t,
                    home_consumption=home_consumption[t],
                    battery_settings=battery_settings,
                    dt=dt,
                    solar_production=solar_production[t],
                    buy_price=buy_price,
                    sell_price=sell_price,
                    new_cost_basis=best_new_cost_basis,
                    currency=currency,
                )
            else:
                # No valid action found - create a default IDLE PeriodData
                # This can happen at boundary states (e.g., max SOE with unprofitable discharge)
                logger.warning(
                    f"No valid action found for period {t}, state {i} (SOE={soe:.1f}). "
                    f"Creating default IDLE state."
                )
                # Calculate IDLE scenario with implicit solar charging
                idle_charged, idle_stored = _compute_idle_solar_charging(
                    solar_production[t], home_consumption[t], soe, battery_settings, dt
                )
                idle_soe_end = soe + idle_stored
                idle_grid_imported = max(
                    0, home_consumption[t] - solar_production[t]
                )
                idle_grid_exported = max(
                    0, solar_production[t] - home_consumption[t] - idle_charged
                )
                idle_wear_cost = idle_stored * battery_settings.cycle_cost_per_kwh
                idle_energy = EnergyData(
                    solar_production=solar_production[t],
                    home_consumption=home_consumption[t],
                    battery_charged=idle_charged,
                    battery_discharged=0.0,
                    grid_imported=idle_grid_imported,
                    grid_exported=idle_grid_exported,
                    battery_soe_start=soe,
                    battery_soe_end=idle_soe_end,
                )
                idle_economic = EconomicData.from_energy_data(
                    energy_data=idle_energy,
                    buy_price=buy_price[t],
                    sell_price=sell_price[t],
                    battery_cycle_cost=idle_wear_cost,
                )
                # Update cost basis for solar charging (zero input cost, cycle wear only)
                idle_cost_basis = C[t, i]
                if idle_stored > 0 and idle_soe_end > battery_settings.min_soe_kwh:
                    existing_cost = soe * C[t, i]
                    idle_cost_basis = (existing_cost + idle_wear_cost) / idle_soe_end
                idle_decision = DecisionData(
                    strategic_intent="IDLE",
                    battery_action=0.0,
                    cost_basis=idle_cost_basis,
                )
                idle_period_data = PeriodData(
                    period=t,
                    energy=idle_energy,
                    timestamp=None,
                    data_source="predicted",
                    economic=idle_economic,
                    decision=idle_decision,
                )
                stored_period_data[(t, i)] = idle_period_data
                # Also update V[t, i] to the actual IDLE cost (not -inf),
                # including future value to preserve backward propagation.
                # Without V[t+1, i], export profits beyond this state are lost
                # and the optimizer cannot distinguish cheap vs expensive charging paths.
                # Use the next state index matching idle_soe_end for future value lookup
                idle_next_i = round(
                    (idle_soe_end - battery_settings.min_soe_kwh) / SOE_STEP_KWH
                )
                idle_next_i = min(max(0, idle_next_i), len(soe_levels) - 1)
                V[t, i] = (
                    -(
                        idle_grid_imported * buy_price[t]
                        - idle_grid_exported * sell_price[t]
                        + idle_wear_cost
                    )
                    + V[t + 1, idle_next_i]
                )

            # Update cost basis for next time step (includes IDLE solar charging
            # which changes SOE even though best_action == 0)
            if best_next_soe != soe and t + 1 < horizon:
                next_i = round(
                    (best_next_soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH
                )
                next_i = min(max(0, next_i), len(soe_levels) - 1)
                C[t + 1, next_i] = best_new_cost_basis

    # Final safety check
    if max_charge_power_per_period is not None:
        # Apply per-period charge limits
        for t in range(horizon):
            policy[t] = np.clip(
                policy[t],
                -battery_settings.max_discharge_power_kw,
                max_charge_power_per_period[t],
            )
    else:
        policy = np.clip(
            policy,
            -battery_settings.max_discharge_power_kw,
            battery_settings.max_charge_power_kw,
        )

    return V, policy, C, stored_period_data


def _create_idle_schedule(
    horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    initial_soe: float,
    battery_settings: BatterySettings,
    dt: float = 0.25,
) -> OptimizationResult:
    """
    Create an all-IDLE schedule where battery does nothing except implicit solar charging.

    Used as fallback when optimization doesn't meet minimum profit threshold.
    In load_first mode, excess solar still charges the battery before exporting to grid.
    """
    period_data_list = []
    current_soe = initial_soe

    for t in range(horizon):
        # IDLE with implicit solar charging from excess solar (load_first mode)
        idle_charged, idle_stored = _compute_idle_solar_charging(
            solar_production[t], home_consumption[t], current_soe, battery_settings, dt
        )
        next_soe = current_soe + idle_stored
        idle_wear_cost = idle_stored * battery_settings.cycle_cost_per_kwh

        energy_data = EnergyData(
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
            battery_charged=idle_charged,
            battery_discharged=0.0,
            grid_imported=max(0, home_consumption[t] - solar_production[t]),
            grid_exported=max(
                0, solar_production[t] - home_consumption[t] - idle_charged
            ),
            battery_soe_start=current_soe,
            battery_soe_end=next_soe,
        )

        economic_data = EconomicData.from_energy_data(
            energy_data=energy_data,
            buy_price=buy_price[t],
            sell_price=sell_price[t],
            battery_cycle_cost=idle_wear_cost,
        )

        decision_data = DecisionData(
            strategic_intent="IDLE",
            battery_action=0.0,
            cost_basis=battery_settings.cycle_cost_per_kwh,
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
        current_soe = next_soe  # Propagate SOE for next period

    # Calculate economic summary for idle schedule
    total_base_cost = sum(home_consumption[i] * buy_price[i] for i in range(horizon))
    total_optimized_cost = sum(h.economic.hourly_cost for h in period_data_list)

    total_charged = sum(h.energy.battery_charged for h in period_data_list)
    total_discharged = sum(h.energy.battery_discharged for h in period_data_list)
    idle_savings = total_base_cost - total_optimized_cost

    economic_summary = EconomicSummary(
        grid_only_cost=total_base_cost,
        solar_only_cost=total_base_cost,
        battery_solar_cost=total_optimized_cost,
        grid_to_solar_savings=0.0,
        grid_to_battery_solar_savings=idle_savings,
        solar_to_battery_solar_savings=idle_savings,
        grid_to_battery_solar_savings_pct=(
            (idle_savings / total_base_cost) * 100 if total_base_cost > 0 else 0.0
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

    # Step 1: Run DP with PeriodData storage
    _, _, _, stored_period_data = _run_dynamic_programming(
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

        # Get the PeriodData from DP results - should always exist with valid inputs
        if (t, i) not in stored_period_data:
            raise RuntimeError(
                f"Missing DP result for hour {t}, state {i} (SOE={current_soe:.1f}). "
                f"This indicates a bug in the DP algorithm or invalid inputs."
            )

        period_data = stored_period_data[(t, i)]
        hourly_results.append(period_data)
        current_soe = period_data.energy.battery_soe_end

    # Step 3: Calculate economic summary directly from PeriodData
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
        f"Savings: {grid_to_battery_solar_savings:.2f} {currency} ({economic_summary.grid_to_battery_solar_savings_pct:.1f}%)"
    )

    # ============================================================================
    # PROFITABILITY GATE: Reject optimization if savings below effective threshold
    # ============================================================================
    # Scale the threshold proportionally to the remaining horizon so that mid-day
    # and late-day runs are not held to a full-day savings bar.
    # A floor of 15% prevents the threshold from collapsing to near-zero at end of day.
    THRESHOLD_HORIZON_FLOOR = 0.15
    total_periods = round(24.0 / dt)
    horizon_fraction = max(THRESHOLD_HORIZON_FLOOR, horizon / total_periods)
    effective_threshold = (
        battery_settings.min_action_profit_threshold * horizon_fraction
    )
    if grid_to_battery_solar_savings < effective_threshold:
        logger.warning(
            f"Optimization savings ({grid_to_battery_solar_savings:.2f} {currency}) below "
            f"effective threshold ({effective_threshold:.2f} {currency}) "
            f"(configured: {battery_settings.min_action_profit_threshold:.2f}, "
            f"horizon: {horizon}/{total_periods} periods, scale: {horizon_fraction:.2f}). "
            f"Using all-IDLE schedule instead."
        )
        return _create_idle_schedule(
            horizon=horizon,
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=initial_soe,
            battery_settings=battery_settings,
            dt=dt,
        )

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
