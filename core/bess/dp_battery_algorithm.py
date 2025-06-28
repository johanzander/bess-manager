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
    "HourlyData",
    "OptimizationResult",
    "calculate_hourly_costs",
    "optimize_battery_schedule",
    "print_optimization_results",
    "print_results_table",
]


import bisect
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

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
class HourlyData:
    """
    UNIFIED hourly data structure - consolidates all energy data representations.
    
    Used by:
    - DP algorithm internal calculations
    - Daily view builder
    - API responses  
    - Historical storage
    - Cost calculations
    """
    
    hour: int
    data_source: str = "predicted"  # "actual" or "predicted"
    timestamp: datetime | None = None  # Optional - only set when it makes sense

    # Core energy flows (kWh) - standardized field names
    solar_generated: float = 0.0  # Use consistent naming from historical store
    home_consumed: float = 0.0    # Use consistent naming from historical store  
    grid_imported: float = 0.0    # Use consistent naming from historical store
    grid_exported: float = 0.0    # Use consistent naming from historical store
    battery_charged: float = 0.0
    battery_discharged: float = 0.0

    # Detailed energy flows (kWh) - for enhanced flow analysis
    solar_to_home: float = 0.0
    solar_to_battery: float = 0.0
    solar_to_grid: float = 0.0
    grid_to_home: float = 0.0
    grid_to_battery: float = 0.0
    battery_to_home: float = 0.0
    battery_to_grid: float = 0.0

    # Battery state - ALWAYS stored as percentage (0-100%)
    battery_soc_start: float = 0.0  # State of Charge as percentage (0-100%)
    battery_soc_end: float = 0.0    # State of Charge as percentage (0-100%)

    # Economic data
    buy_price: float = 0.0  # SEK/kWh
    sell_price: float = 0.0  # SEK/kWh
    hourly_cost: float = 0.0  # SEK - Cost of solar+battery scenario
    hourly_savings: float = 0.0  # SEK - Total savings: base_cost - optimized_cost
    battery_cycle_cost: float = 0.0  # SEK

    # Battery action (for predicted hours from DP algorithm)
    battery_action: float | None = None  # kW (from optimization)

    # Strategic intent for this hour
    strategic_intent: str = "IDLE"

    # Cost basis tracking (for DP algorithm)
    cost_basis: float = 0.0  # SEK/kWh

    # Enhanced flows intelligence (optional)
    pattern_name: str = ""
    description: str = ""
    economic_chain: str = ""
    flow_values: dict[str, float] = field(default_factory=dict)
    immediate_value: float = 0.0
    future_value: float = 0.0
    net_strategy_value: float = 0.0
    risk_factors: list[str] = field(default_factory=list)

    @property
    def battery_net_change(self) -> float:
        """Net battery energy change (positive = charged, negative = discharged)."""
        return self.battery_charged - self.battery_discharged

    @property
    def soc_change_kwh(self) -> float:
        """SOC change during this hour in kWh."""
        return self.battery_soc_end - self.battery_soc_start

    @property
    def solar_production(self) -> float:
        """Alias for solar_generated for DP algorithm compatibility."""
        return self.solar_generated

    @property
    def home_consumption(self) -> float:
        """Alias for home_consumed for DP algorithm compatibility."""
        return self.home_consumed

    @property
    def grid_import(self) -> float:
        """Alias for grid_imported for DP algorithm compatibility."""
        return self.grid_imported

    @property
    def grid_export(self) -> float:
        """Alias for grid_exported for DP algorithm compatibility."""
        return self.grid_exported

    def _generate_pattern_name(self) -> str:
        """Generate a descriptive pattern name based on energy flows and strategic intent."""
        significant_flows = self.get_significant_flows(threshold=0.1)
        
        # Special case for IDLE with no flows
        if len(significant_flows) == 0:
            return "Minimal Activity"
            
        # Extract flow directions for naming
        sources = set()
        destinations = set()
        
        for flow_name in significant_flows:
            parts = flow_name.split('_to_')
            if len(parts) == 2:
                sources.add(parts[0])
                destinations.add(parts[1])
        
        # Generate pattern name based on strategic intent
        if self.strategic_intent == "GRID_CHARGING":
            return "Grid Price Arbitrage"
        elif self.strategic_intent == "SOLAR_STORAGE":
            return "Solar Energy Storage"
        elif self.strategic_intent == "LOAD_SUPPORT":
            return "Self Consumption"
        elif self.strategic_intent == "EXPORT_ARBITRAGE":
            return "Grid Export"
        else:
            # Generate based on flow directions
            if 'solar' in sources and 'grid' in destinations:
                return "Solar Export"
            elif 'solar' in sources and len(destinations) > 1:
                return "Solar Distribution"
            elif 'grid' in sources and 'home' in destinations:
                return "Grid Consumption"
            elif 'battery' in sources:
                return "Battery Discharge"
            elif 'battery' in destinations:
                return "Battery Charging"
                
        # Fallback
        return "Mixed Energy Flow"

    def _generate_flow_description(self) -> str:
        """Generate a detailed human-readable description of the energy flows."""
        significant_flows = self.get_significant_flows(threshold=0.1)
        
        if not significant_flows:
            return "No significant energy flows"
            
        # Group flow descriptions
        flow_groups = {}
        
        for flow_name in significant_flows:
            flow_value = getattr(self, flow_name, 0.0)
            
            # Skip insignificant flows
            if abs(flow_value) < 0.1:
                continue
                
            parts = flow_name.split('_to_')
            if len(parts) != 2:
                continue
                
            source, destination = parts
            
            # Friendly names
            source_name = source.capitalize()
            dest_name = destination.capitalize()
            
            # Add to flow groups
            if source not in flow_groups:
                flow_groups[source] = {}
            
            if destination not in flow_groups[source]:
                flow_groups[source][destination] = 0.0
                
            flow_groups[source][destination] = flow_value
        
        # Build description
        descriptions = []
        
        for source, destinations in flow_groups.items():
            source_total = sum(destinations.values())
            source_name = source.capitalize()
            
            if source_total < 0.1:
                continue
                
            # For single destination
            if len(destinations) == 1:
                destination, value = next(iter(destinations.items()))
                dest_name = destination.capitalize()
                descriptions.append(f"{source_name} {value:.1f}kWh→{dest_name}")
            else:
                # For multiple destinations
                dest_parts = []
                for destination, value in destinations.items():
                    if value < 0.1:
                        continue
                    dest_name = destination.capitalize()
                    dest_parts.append(f"{value:.1f}kWh→{dest_name}")
                
                if dest_parts:
                    dest_str = ", ".join(dest_parts)
                    descriptions.append(f"{source_name} {source_total:.1f}kWh: {dest_str}")
        
        if descriptions:
            return ", ".join(descriptions)
        else:
            return "No significant energy flows"

    def _analyze_future_opportunity(self, future_prices: list[float] | None) -> tuple[str, float]:
        """Analyze future market opportunities based on current state and future prices.
        
        Returns:
            tuple[str, float]: Description of opportunity and expected value
        """
        # Default values
        description = "Unknown future opportunity"
        value = 0.0
        
        # Can't analyze without future prices
        if not future_prices or len(future_prices) == 0:
            return "Insufficient future price data", 0.0
        
        avg_price = sum(future_prices) / len(future_prices)
        max_price = max(future_prices)
        min_price = min(future_prices)
        price_range = max_price - min_price
        
        # Calculate price percentiles and find relevant future hour indexes
        sorted_prices = sorted(future_prices)
        current_price_percentile = bisect.bisect_left(sorted_prices, self.buy_price) / len(sorted_prices) * 100
        
        # Find next high-price and low-price periods
        next_high_idx = next((i for i, p in enumerate(future_prices) if p > self.buy_price * 1.3), -1)
        next_low_idx = next((i for i, p in enumerate(future_prices) if p < self.buy_price * 0.7), -1)
        
        # Battery is charged - looking for discharge opportunity
        battery_charge = self.battery_soc_end
        if battery_charge > 30 and self.strategic_intent in ["GRID_CHARGING", "SOLAR_STORAGE"]:
            if next_high_idx >= 0:
                high_price = future_prices[next_high_idx]
                discharge_value = battery_charge * 0.01 * high_price  # Assuming 1% SOC
                description = f"Discharge opportunity in {next_high_idx+1}h at price {high_price:.2f}"
                value = discharge_value
            else:
                description = "Holding charge for upcoming price peaks"
                value = battery_charge * 0.01 * avg_price  # Estimated future value
                
        # Battery is discharged - looking for charging opportunity
        elif battery_charge < 70 and self.strategic_intent in ["LOAD_SUPPORT", "EXPORT_ARBITRAGE", "IDLE"]:
            if next_low_idx >= 0:
                low_price = future_prices[next_low_idx]
                charging_cost = battery_charge * 0.01 * low_price  # Assuming 1% SOC
                description = f"Charging opportunity in {next_low_idx+1}h at price {low_price:.2f}"
                value = -charging_cost  # Cost is negative value
            else:
                description = "Waiting for lower prices to recharge"
                value = -battery_charge * 0.01 * min(avg_price, self.buy_price) 
                
        # General market trend description
        elif price_range > 0.5:  # Significant price variation
            if current_price_percentile < 30:
                description = "Current price is low - favorable for charging"
                value = price_range * 0.5  # Rough estimate of opportunity value
            elif current_price_percentile > 70:
                description = "Current price is high - favorable for discharging"
                value = price_range * 0.5
            else:
                description = "Moderate price period - waiting for better opportunities"
                value = price_range * 0.25
        else:
            description = "Stable price period - limited arbitrage opportunities" 
            value = price_range * 0.1
            
        return description, value

    def _generate_economic_chain(self) -> str:
        """Generate a concise description of the economic value chain for this hour."""
        if self.strategic_intent == "GRID_CHARGING":
            return f"Buy @ {self.buy_price:.2f} → Store → Use/Sell later at higher price"
            
        elif self.strategic_intent == "SOLAR_STORAGE":
            return f"Free solar → Store → Avoid future purchase @ ~{self.buy_price:.2f}/kWh"
            
        elif self.strategic_intent == "LOAD_SUPPORT":
            return f"Use stored energy → Avoid purchase @ {self.buy_price:.2f}/kWh"
            
        elif self.strategic_intent == "EXPORT_ARBITRAGE":
            return f"Use stored energy → Sell @ {self.sell_price:.2f}/kWh"
            
        elif self.grid_imported > 0.1:
            return f"Buy from grid @ {self.buy_price:.2f}/kWh"
            
        elif self.grid_exported > 0.1:
            return f"Sell to grid @ {self.sell_price:.2f}/kWh"
            
        # Fallback for other cases
        return ""

    def add_intelligence(
        self, 
        buy_price: float, 
        sell_price: float, 
        hour: int, 
        future_prices: list[float] | None = None,
        power: float = 0.0
    ):
        """Add enhanced intelligence/analytics to hourly data.
        
        This function analyzes the hour data and adds valuable insights about:
        - The economic pattern being followed
        - The immediate vs. future value of the action
        - Risk factors associated with the decision
        - Detailed flow descriptions
        
        Args:
            buy_price: The current hour's buy price
            sell_price: The current hour's sell price
            hour: The current hour (0-23)
            future_prices: List of buy prices for future hours
            power: Battery power action (kW, positive=charge, negative=discharge)
        """
        # Skip if already has intelligence
        if self.has_intelligence():
            return
            
        # Define price thresholds for analysis
        if future_prices and len(future_prices) > 0:
            avg_future_price = sum(future_prices) / len(future_prices)
            min_future_price = min(future_prices) if future_prices else buy_price
            max_future_price = max(future_prices) if future_prices else buy_price
            price_range = max_future_price - min_future_price if future_prices else 0
            
            # Calculate price percentile for current hour
            higher_prices = sum(1 for p in future_prices if p > buy_price)
            price_percentile = (higher_prices / len(future_prices)) * 100 if future_prices else 50
        else:
            avg_future_price = buy_price
            min_future_price = buy_price
            max_future_price = buy_price
            price_range = 0
            price_percentile = 50
        
        # Initialize intelligence data
        self.risk_factors = []
        
        # Generate pattern name and description
        self.pattern_name = self._generate_pattern_name()
        self.description = self._generate_flow_description()
        
        # Calculate some metrics
        excess_solar = max(0, self.solar_generated - self.home_consumed)
        remaining_load = max(0, self.home_consumed - self.solar_generated)
        
        # Calculate immediate value
        if self.strategic_intent == "GRID_CHARGING":
            # Grid charging - immediate cost
            self.immediate_value = -self.grid_to_battery * buy_price
            
        elif self.strategic_intent == "SOLAR_STORAGE":
            # Solar storage - opportunity cost
            self.immediate_value = -self.solar_to_battery * sell_price
            
        elif self.strategic_intent == "LOAD_SUPPORT":
            # Load support - avoided cost
            self.immediate_value = self.battery_to_home * buy_price
            
        elif self.strategic_intent == "EXPORT_ARBITRAGE":
            # Export - immediate revenue
            self.immediate_value = self.battery_to_grid * sell_price
            
        else:
            # IDLE - calculate direct flows
            grid_cost = self.grid_imported * buy_price
            grid_revenue = self.grid_exported * sell_price
            self.immediate_value = grid_revenue - grid_cost
            
        # Calculate future opportunity value
        future_description, expected_value = self._analyze_future_opportunity(future_prices)
        self.future_value = expected_value
        
        # Calculate net strategy value
        self.net_strategy_value = self.immediate_value + self.future_value - self.battery_cycle_cost
        
        # Generate economic chain description
        self.economic_chain = self._generate_economic_chain()
        
        # Check for risk factors
        # 1. High price charging
        if self.strategic_intent == "GRID_CHARGING" and price_percentile > 70:
            self.risk_factors.append("HIGH_PRICE_CHARGING")
            
        # 2. Low price discharging
        if (self.strategic_intent == "LOAD_SUPPORT" or self.strategic_intent == "EXPORT_ARBITRAGE") and price_percentile < 30:
            self.risk_factors.append("LOW_PRICE_DISCHARGING")
            
        # 3. Low arbitrage potential
        if price_range < 0.3 and self.strategic_intent == "GRID_CHARGING":
            self.risk_factors.append("LOW_ARBITRAGE_POTENTIAL")
            
        # 4. Excessive discharge depth
        if self.battery_soc_end < 15:
            self.risk_factors.append("EXCESSIVE_DISCHARGE_DEPTH")
            
        # 5. Insufficient solar energy
        if self.strategic_intent == "SOLAR_STORAGE" and excess_solar < self.solar_to_battery:
            self.risk_factors.append("INSUFFICIENT_SOLAR_ENERGY")
        
        # Store key value flows for reference
        self.flow_values = {
            "current_price": buy_price,
            "avg_future_price": avg_future_price,
            "price_percentile": price_percentile,
            "price_range": price_range,
            "excess_solar": excess_solar,
            "remaining_load": remaining_load
        }

    def has_intelligence(self) -> bool:
        """Check if intelligence data is already available."""
        return self.pattern_name != ""
        
    def get_significant_flows(self, threshold: float = 0.1) -> list[str]:
        """Return a list of significant flow field names and their values."""
        flow_fields = [
            "solar_to_home", "solar_to_battery", "solar_to_grid",
            "grid_to_home", "grid_to_battery",
            "battery_to_home", "battery_to_grid"
        ]
        
        return [field for field in flow_fields if getattr(self, field, 0) > threshold]


@dataclass
class OptimizationResult:
    """Result structure returned by optimize_battery_schedule."""
    hourly_data: list[HourlyData]
    economic_summary: dict[str, float]
    strategic_intent_summary: dict[str, int]
    input_data: dict
    # Keep all existing fields for backward compatibility
    soc_trace: list[float] = field(default_factory=list)
    action_trace: list[float] = field(default_factory=list)
    cost_basis_trace: list[float] = field(default_factory=list)
    energy_flows: dict[str, list[float]] = field(default_factory=dict)
    enhanced_flows: list = field(default_factory=list)
    battery_params: dict = field(default_factory=dict)
    final_cost_basis: float = 0.0
    summary: dict = field(default_factory=dict)
    flow_summary: dict = field(default_factory=dict)
    optimization_context: dict = field(default_factory=dict)
    total_energy_flows: dict[str, float] = field(default_factory=dict)
    hourly_savings: list[float] = field(default_factory=list)



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
    hour_data: "HourlyData",
    battery_cycle_cost_per_kwh: float = 0.0,
    charge_efficiency: float = 1.0,
    discharge_efficiency: float = 1.0,
) -> CostScenarios:
    """Calculate cost scenarios - EXACT match to working original logic."""
    
    # Base case: Grid-only (no solar, no battery)
    base_case_cost = hour_data.home_consumed * hour_data.buy_price
    
    # Solar-only case: Solar + grid (no battery)
    direct_solar = min(hour_data.solar_generated, hour_data.home_consumed)
    solar_excess = max(0, hour_data.solar_generated - direct_solar)
    grid_needed = max(0, hour_data.home_consumed - direct_solar)
    solar_only_cost = grid_needed * hour_data.buy_price - solar_excess * hour_data.sell_price
    
    # Battery+solar case: Full optimization
    # EXACT from original: Apply cycle cost only to charging (actual energy stored)
    battery_wear_cost = (
        hour_data.battery_charged * charge_efficiency * battery_cycle_cost_per_kwh
    )
    
    battery_solar_cost = (
        hour_data.grid_imported * hour_data.buy_price
        - hour_data.grid_exported * hour_data.sell_price
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


def _calculate_cost_basis_after_action(
    power: float,
    soc: float,
    next_soc: float,
    cost_basis: float,
    buy_price_hour: float,
    battery_settings: BatterySettings,
    dt: float = 1.0
) -> float:
    """
    Calculate the new cost basis after a battery action.
    
    Args:
        power: Battery power (kW), positive for charging, negative for discharging
        soc: Current state of charge (kWh)
        next_soc: Next state of charge after action (kWh)
        cost_basis: Current average cost per kWh in battery (SEK/kWh)
        buy_price_hour: Buy price for this hour (SEK/kWh)
        battery_settings: Battery configuration
        dt: Time step (hour)
    
    Returns:
        Updated cost basis (SEK/kWh)
    """
    
    if power > 0:  # Charging
        # Calculate actual charge energy accounting for efficiency
        charge_energy = power * dt * battery_settings.efficiency_charge
        
        # Calculate cost of new energy (buy price + cycle cost)
        new_energy_cost = charge_energy * (buy_price_hour + battery_settings.cycle_cost_per_kwh)
        
        # Calculate weighted average cost basis
        if next_soc > battery_settings.min_soc_kwh:
            # Weighted average of existing energy and new energy
            existing_energy_cost = soc * cost_basis
            total_cost = existing_energy_cost + new_energy_cost
            new_cost_basis = total_cost / next_soc
        else:
            # Battery was empty, new cost is just the cost of new energy
            new_cost_basis = (new_energy_cost / charge_energy) if charge_energy > 0 else cost_basis
            
        return new_cost_basis
        
    elif power < 0:  # Discharging
        # Cost basis doesn't change on discharge (FIFO would be more accurate but simpler this way)
        return cost_basis
        
    else:  # No action
        return cost_basis
    
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


def _calculate_energy_flows(
    power: float, 
    home_consumption: float, 
    solar_production: float, 
    dt: float = 1.0,
    hour: int = 0, 
    buy_price: float = 0.0, 
    sell_price: float = 0.0
) -> HourlyData:
    """Calculate detailed energy flows returning HourlyData directly."""
    
    # Calculate energy values for this timestep
    charge_energy = max(0, power) * dt
    discharge_energy = max(0, -power) * dt

    # Step 1: Solar first supplies home load (highest priority)
    solar_to_home = min(solar_production, home_consumption)
    solar_excess = max(0, solar_production - solar_to_home)
    remaining_home_consumption = max(0, home_consumption - solar_to_home)

    # Initialize all flows
    solar_to_battery = 0.0
    solar_to_grid = 0.0
    battery_to_home = 0.0
    battery_to_grid = 0.0
    grid_to_home = 0.0
    grid_to_battery = 0.0

    # Step 2: Handle battery actions
    if power > 0:  # Charging
        solar_to_battery = min(solar_excess, charge_energy)
        grid_to_battery = max(0, charge_energy - solar_to_battery)
        solar_to_grid = max(0, solar_excess - solar_to_battery)
        grid_to_home = remaining_home_consumption

    elif power < 0:  # Discharging
        battery_to_home = min(discharge_energy, remaining_home_consumption)
        battery_to_grid = max(0, discharge_energy - battery_to_home)
        grid_to_home = max(0, remaining_home_consumption - battery_to_home)
        solar_to_grid = solar_excess

    else:  # Hold (no battery action)
        grid_to_home = remaining_home_consumption
        solar_to_grid = solar_excess

    # Calculate totals
    grid_import = grid_to_home + grid_to_battery
    grid_export = solar_to_grid + battery_to_grid

    # Return HourlyData object directly
    return HourlyData(
        hour=hour,
        data_source="predicted",
        solar_generated=solar_production,
        home_consumed=home_consumption,
        grid_imported=grid_import,
        grid_exported=grid_export,
        battery_charged=charge_energy,
        battery_discharged=discharge_energy,
        solar_to_home=solar_to_home,
        solar_to_battery=solar_to_battery,
        solar_to_grid=solar_to_grid,
        grid_to_home=grid_to_home,
        grid_to_battery=grid_to_battery,
        battery_to_home=battery_to_home,
        battery_to_grid=battery_to_grid,
        buy_price=buy_price,
        sell_price=sell_price,
        battery_action=power,
    )


def _calculate_reward(
    power: float,
    soc: float,
    next_soc: float,
    hour: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    solar_production: float = 0.0,
    dt: float = 1.0,
    buy_price: list[float] | None = None,
    sell_price: list[float] | None = None,
    cost_basis: float = 0.0,
    future_prices: list[float] | None = None,
) -> tuple[float, float, "HourlyData"]:
    """Calculate reward with HourlyData - EXACT cost basis logic from working version."""

    # Calculate energy flows
    hour_data = _calculate_energy_flows(
        power=power,
        home_consumption=home_consumption,
        solar_production=solar_production,
        dt=dt,
        hour=hour,
        buy_price=buy_price[hour],  # Direct access like original
        sell_price=sell_price[hour],  # Direct access like original
    )
    
    # Extract grid values from the detailed flows
    grid_import = hour_data.grid_imported
    grid_export = hour_data.grid_exported
    
    # Battery wear cost calculation - EXACT from original
    delta_soc = abs(next_soc - soc)
    battery_wear_cost = delta_soc * battery_settings.cycle_cost_per_kwh

    # FIX #2: EXACT cost basis calculation from working original
    if power > 0:  # Charging
        charge_energy = power * dt * battery_settings.efficiency_charge
        
        # EXACT solar vs grid split logic from original
        solar_available = max(0, solar_production - home_consumption)
        solar_to_battery = min(solar_available, power)
        grid_to_battery = max(0, power - solar_to_battery)

        # EXACT cost calculation from original
        solar_energy_cost = (
            solar_to_battery * dt * battery_settings.efficiency_charge 
            * battery_settings.cycle_cost_per_kwh
        )
        grid_energy_cost = (
            grid_to_battery * dt * battery_settings.efficiency_charge
            * (buy_price[hour] + battery_settings.cycle_cost_per_kwh)
        )

        total_new_cost = solar_energy_cost + grid_energy_cost
        total_new_energy = charge_energy

        if next_soc > battery_settings.min_soc_kwh:
            new_cost_basis = (soc * cost_basis + total_new_cost) / next_soc
        else:
            new_cost_basis = (
                (total_new_cost / total_new_energy) if total_new_energy > 0 else cost_basis
            )

    elif power < 0:  # Discharging
        effective_sell_price = sell_price[hour]
        
        # Profitability check from original
        if effective_sell_price <= cost_basis:
            return float("-inf"), cost_basis, hour_data

        new_cost_basis = cost_basis

    else:  # No action
        new_cost_basis = cost_basis

    # FIX #3: EXACT reward calculation from working original
    import_cost = grid_import * buy_price[hour]
    export_revenue = grid_export * sell_price[hour]
    total_cost = import_cost - export_revenue + battery_wear_cost
    reward = -total_cost

    # Update HourlyData with calculated values (this part is new for HourlyData compatibility)
    costs = calculate_hourly_costs(
        hour_data=hour_data,
        battery_cycle_cost_per_kwh=battery_settings.cycle_cost_per_kwh,
        charge_efficiency=battery_settings.efficiency_charge,
        discharge_efficiency=battery_settings.efficiency_discharge,
    )
    
    hour_data.hourly_cost = costs.battery_solar_cost
    hour_data.hourly_savings = costs.total_savings
    hour_data.battery_cycle_cost = costs.battery_wear_cost
    
    return reward, new_cost_basis, hour_data


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
                reward, new_cost_basis, _ = _calculate_reward(
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
        reward, new_cost_basis, enhanced_flow = _calculate_reward(
            power=power,
            soc=trace_soc,
            next_soc=next_soc,
            hour=t,
            home_consumption=home_consumption[t],
            solar_production=solar_production[t] if solar_production else 0,
            battery_settings=battery_settings,
            buy_price=buy_price,
            sell_price=sell_price,
            cost_basis=C[t, i],
            future_prices=buy_price[t+1:] if buy_price and t+1 < len(buy_price) else []
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
    list[HourlyData],  # CHANGED: HourlyData instead of DetailedEnergyFlows
]:
    """Simulate battery behavior creating HourlyData objects directly."""
    
    logger.debug("Starting battery simulation with HourlyData objects")

    # Discretize state space (needed to interpret policy)
    soc_levels, _ = _discretize_state_action_space(battery_settings)

    # Initialize simulation
    enhanced_flows = []  # NOW: list[HourlyData]
    soc = initial_soc or battery_settings.min_soc_kwh
    cost_basis = initial_cost_basis
    dt = 1.0

    # Initialize tracking lists
    soc_trace = [soc]
    action_trace = []
    cost_basis_trace = [cost_basis]
    strategic_intents = []
    
    # Initialize energy flows dict for backward compatibility
    energy_flows = {
        "solar_to_home": [],
        "solar_to_battery": [],
        "solar_to_grid": [],
        "grid_to_home": [],
        "grid_to_battery": [],
        "battery_to_home": [],
        "battery_to_grid": [],
    }
    
    # Initialize cost tracking
    base_case_costs = []
    solar_only_costs = []
    battery_solar_costs = []
    b_costs = []
    
    # Run forward simulation (YOUR ORIGINAL SIMULATION LOGIC!)
    for t in range(horizon):
        # Determine action from policy (YOUR ORIGINAL LOGIC!)
        i = round((soc - battery_settings.min_soc_kwh) / SOC_STEP_KWH)
        i = min(max(0, i), len(soc_levels) - 1)
        power = policy[t, i]
        
        # Get strategic intent
        if intents and t < len(intents) and i < len(intents[t]):
            strategic_intent = intents[t][i].value
        else:
            strategic_intent = "IDLE"
        
        # Calculate next SOC
        next_soc = _state_transition(soc, power, battery_settings, dt)
        
        # Get prices for this hour
        current_buy_price = buy_price[t] if buy_price and t < len(buy_price) else 0.5
        current_sell_price = sell_price[t] if sell_price and t < len(sell_price) else 0.35
        current_consumption = home_consumption[t]
        current_solar = solar_production[t] if solar_production and t < len(solar_production) else 0.0
        
        # CREATE HourlyData object
        hour_data = _calculate_energy_flows(
            power=power,
            home_consumption=current_consumption,
            solar_production=current_solar,
            dt=dt,
            hour=t,
            buy_price=current_buy_price,
            sell_price=current_sell_price,
        )
        
        # Update battery state information
        hour_data.battery_soc_start = soc
        hour_data.battery_soc_end = next_soc
        hour_data.strategic_intent = strategic_intent
        hour_data.cost_basis = cost_basis
        
        # Calculate costs directly from HourlyData
        costs = calculate_hourly_costs(
            hour_data=hour_data,
            battery_cycle_cost_per_kwh=battery_settings.cycle_cost_per_kwh,
            charge_efficiency=battery_settings.efficiency_charge,
            discharge_efficiency=battery_settings.efficiency_discharge,
        )
        
        # Update HourlyData with cost information
        hour_data.hourly_cost = costs.battery_solar_cost
        hour_data.hourly_savings = costs.total_savings
        hour_data.battery_cycle_cost = costs.battery_wear_cost
        
        # Add intelligence if needed
        future_prices = buy_price[t+1:] if buy_price and t+1 < len(buy_price) else []
        hour_data.add_intelligence(
            buy_price=current_buy_price,
            sell_price=current_sell_price,
            hour=t,
            future_prices=future_prices,
            power=power
        )
        
        # Add to enhanced_flows list as HourlyData
        enhanced_flows.append(hour_data)
        
        # Store detailed flows for legacy compatibility
        for flow_key in energy_flows.keys():
            energy_flows[flow_key].append(getattr(hour_data, flow_key))
        
        # Store cost information for legacy compatibility
        base_case_costs.append(costs.base_case_cost)
        solar_only_costs.append(costs.solar_only_cost)
        battery_solar_costs.append(costs.battery_solar_cost)
        b_costs.append(costs.battery_wear_cost)
        
        # Update cost basis for next iteration
        if power > 0:  # Charging
            if next_soc > battery_settings.min_soc_kwh:
                cost_basis = (soc * cost_basis + hour_data.battery_charged * current_buy_price) / next_soc
            # else: cost_basis stays the same
        # For discharging or idle, cost_basis stays the same
        
        # Update state for next iteration
        soc = next_soc
        soc_trace.append(soc)
        action_trace.append(power)
        cost_basis_trace.append(cost_basis)
        strategic_intents.append(strategic_intent)
        
        if abs(power) > 0.01:
            logger.debug(
                "Hour %d: SOC=%.1f kWh, Action=%.2f kW, Intent=%s, Cost=%.2f SEK",
                t, soc, power, strategic_intent, hour_data.hourly_cost
            )
    
    # Create DataFrame for backward compatibility (if needed)
    df_data = {
        "Hour": list(range(horizon)),
        "Buy Price": [buy_price[t] if buy_price else 0.5 for t in range(horizon)],
        "Sell Price": [sell_price[t] if sell_price else 0.35 for t in range(horizon)],
        "Home Consumption": home_consumption,
        "Solar Production": [solar_production[t] if solar_production else 0.0 for t in range(horizon)],
        "Battery Action (kW)": action_trace,
        "State of Charge (SoC)": soc_trace[:-1],  # Exclude last element
        "Grid Import": [h.grid_imported for h in enhanced_flows],
        "Grid Export": [h.grid_exported for h in enhanced_flows],
        "Base Case Hourly Cost": base_case_costs,
        "Solar Only Hourly Cost": solar_only_costs,
        "Battery+Solar Hourly Cost": battery_solar_costs,
        "B.Cost": b_costs,
    }
    df = pd.DataFrame(df_data)
    
    # Calculate economic results
    total_base_cost = sum(base_case_costs)
    total_solar_only_cost = sum(solar_only_costs)
    total_battery_solar_cost = sum(battery_solar_costs)
    total_charged = sum(h.battery_charged for h in enhanced_flows)
    total_discharged = sum(h.battery_discharged for h in enhanced_flows)
    
    base_to_solar_savings = total_base_cost - total_solar_only_cost
    base_to_battery_solar_savings = total_base_cost - total_battery_solar_cost
    solar_to_battery_solar_savings = total_solar_only_cost - total_battery_solar_cost
    
    economic_results = {
        "base_cost": total_base_cost,
        "solar_only_cost": total_solar_only_cost,
        "battery_solar_cost": total_battery_solar_cost,
        "base_to_solar_savings": base_to_solar_savings,
        "base_to_battery_solar_savings": base_to_battery_solar_savings,
        "solar_to_battery_solar_savings": solar_to_battery_solar_savings,
        "base_to_battery_solar_savings_pct": (
            (base_to_battery_solar_savings / total_base_cost) * 100 
            if total_base_cost > 0 else 0
        ),
        "total_charged": total_charged,
        "total_discharged": total_discharged,
    }
    
    logger.debug(
        "Simulation complete: Base cost: %.2f SEK, Battery+Solar cost: %.2f SEK, "
        "Savings: %.2f SEK (%.1f%%), Final cost basis: %.3f SEK/kWh",
        total_base_cost,
        total_battery_solar_cost,
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
        enhanced_flows,  # NOW: list[HourlyData] instead of list[DetailedEnergyFlows]
    )


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
    
    # Your existing DP setup code...
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

    # Step 1: Run dynamic programming (YOUR ALGORITHM UNCHANGED!)
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

    # Step 2: Simulate battery behavior (UPDATED to return HourlyData)
    logger.debug("Simulating battery behavior with HourlyData objects...")
    (
        df,
        soc_trace,
        action_trace,
        economic_results,
        cost_basis_trace,
        energy_flows,
        strategic_intents,
        enhanced_flows,  # NOW: list[HourlyData]
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

    # Step 3: Return OptimizationResult directly (NO conversion needed!)
    strategic_intent_summary = {}
    for hour_data in enhanced_flows:
        intent = hour_data.strategic_intent
        strategic_intent_summary[intent] = strategic_intent_summary.get(intent, 0) + 1

    return OptimizationResult(
        hourly_data=enhanced_flows,  # DIRECT usage of HourlyData objects!
        economic_summary=economic_results,
        strategic_intent_summary=strategic_intent_summary,
        input_data={
            "buy_price": buy_price,
            "sell_price": sell_price,
            "home_consumption": home_consumption,
            "solar_production": solar_production,
            "initial_soc": initial_soc,
            "initial_cost_basis": initial_cost_basis,
            "horizon": horizon,
        },
        soc_trace=soc_trace,
        action_trace=action_trace,
        cost_basis_trace=cost_basis_trace,
        energy_flows=energy_flows,
        enhanced_flows=enhanced_flows,  # Same as hourly_data
        final_cost_basis=cost_basis_trace[-1] if cost_basis_trace else initial_cost_basis,
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
        
        # Calculate costs exactly like original
        grid_cost = hour_data.grid_imported * buy_prices[i] - hour_data.grid_exported * sell_prices[i] if i < len(buy_prices) else 0
        battery_cost = hour_data.battery_cycle_cost
        combined_cost = hour_data.hourly_cost
        savings = base_cost - combined_cost

        # Update totals exactly like original
        total_consumption += consumption
        total_base_cost += base_cost
        total_solar += solar
        total_solar_to_bat += solar_to_battery
        total_grid_to_bat += grid_to_battery
        total_grid_cost += grid_cost
        total_battery_cost += battery_cost
        total_combined_cost += combined_cost
        total_savings += savings
        
        if action > 0:
            total_charging += action
        else:
            total_discharging += abs(action)

        # Format intent to fit column width exactly like original
        intent_short = intent[:14] if len(intent) <= 14 else intent[:11] + "..."

        # Use exact same formatting as original
        buy_price_val = buy_prices[i] if i < len(buy_prices) else hour_data.buy_price
        sell_price_val = sell_prices[i] if i < len(sell_prices) else hour_data.sell_price
        
        output.append(
            f"║{hour:3d} ║{buy_price_val:5.3f}/{sell_price_val:5.3f}║{consumption:5.1f}║{base_cost:6.2f}║║{solar:5.1f}║{solar_to_battery:6.1f}║{grid_to_battery:6.1f}║{soc_percent:3.0f} ║{action:6.1f}║{intent_short:16s}║{grid_cost:6.2f}║{battery_cost:6.2f}║{savings:6.2f}║"
        )

    # Add totals row exactly like original
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

    # Append summary stats exactly like original
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

    # Log all output in a single call exactly like original
    logger.info("\n".join(output))