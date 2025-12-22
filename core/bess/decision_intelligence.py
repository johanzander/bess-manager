"""
Decision Intelligence Generator.

Generates enhanced decision data with pattern analysis, economic chains,
and user-friendly explanations for battery optimization decisions.

This module enhances the existing DecisionData fields without creating new classes,
maintaining compatibility with the existing software architecture.
"""

from core.bess.models import DecisionData, EnergyData, determine_strategic_intent


def generate_advanced_flow_pattern_name(energy_data: EnergyData) -> str:
    """
    Generate detailed flow-based pattern name from energy flow analysis.

    Implements the comprehensive flow pattern naming convention from decisionframework.md:
    - Single-source patterns: SOLAR_TO_HOME, GRID_TO_BATTERY, etc.
    - Multi-destination patterns: SOLAR_TO_HOME_AND_BATTERY, BATTERY_TO_HOME_AND_GRID
    - Multi-source patterns: SOLAR_TO_HOME_PLUS_GRID_TO_BATTERY

    Args:
        energy_data: Complete energy flow data

    Returns:
        Detailed flow pattern name based on significant energy flows (>0.1 kWh)

    Examples:
        - "SOLAR_TO_HOME_AND_BATTERY"
        - "GRID_TO_HOME_AND_BATTERY"
        - "BATTERY_TO_HOME_AND_GRID"
        - "SOLAR_TO_HOME_PLUS_BATTERY_TO_GRID"
        - "SOLAR_TO_GRID_PLUS_BATTERY_TO_HOME"
    """
    threshold = 0.1  # kWh threshold for significant flows
    patterns = []

    # Solar source patterns
    solar_destinations = []
    if energy_data.solar_to_home > threshold:
        solar_destinations.append("HOME")
    if energy_data.solar_to_battery > threshold:
        solar_destinations.append("BATTERY")
    if energy_data.solar_to_grid > threshold:
        solar_destinations.append("GRID")

    if solar_destinations:
        if len(solar_destinations) == 1:
            patterns.append(f"SOLAR_TO_{solar_destinations[0]}")
        else:
            patterns.append(f"SOLAR_TO_{'_AND_'.join(solar_destinations)}")

    # Grid source patterns (imports only)
    grid_destinations = []
    if energy_data.grid_to_home > threshold:
        grid_destinations.append("HOME")
    if energy_data.grid_to_battery > threshold:
        grid_destinations.append("BATTERY")

    if grid_destinations:
        if len(grid_destinations) == 1:
            patterns.append(f"GRID_TO_{grid_destinations[0]}")
        else:
            patterns.append(f"GRID_TO_{'_AND_'.join(grid_destinations)}")

    # Battery source patterns (discharge only)
    battery_destinations = []
    if energy_data.battery_to_home > threshold:
        battery_destinations.append("HOME")
    if energy_data.battery_to_grid > threshold:
        battery_destinations.append("GRID")

    if battery_destinations:
        if len(battery_destinations) == 1:
            patterns.append(f"BATTERY_TO_{battery_destinations[0]}")
        else:
            patterns.append(f"BATTERY_TO_{'_AND_'.join(battery_destinations)}")

    # Combine patterns with PLUS for multi-source scenarios
    if len(patterns) == 0:
        return "NO_SIGNIFICANT_FLOWS"
    elif len(patterns) == 1:
        return patterns[0]
    else:
        return "_PLUS_".join(patterns)


def generate_strategic_pattern_name(
    strategic_intent: str, energy_data: EnergyData
) -> str:
    """
    Generate high-level strategic pattern name based on action and intent.

    This provides the high-level strategy while generate_advanced_flow_pattern_name
    provides the detailed flow analysis.

    Args:
        strategic_intent: Strategic intent (GRID_CHARGING, SOLAR_STORAGE, etc.)
        energy_data: Complete energy flow data

    Returns:
        User-friendly strategic pattern name

    Examples:
        - "Grid Charging Strategy"
        - "Solar Storage Strategy"
        - "Peak Export Arbitrage"
        - "Home Load Support"
        - "Optimal Idle"
    """
    if strategic_intent == "GRID_CHARGING":
        return "Grid Charging Strategy"
    elif strategic_intent == "SOLAR_STORAGE":
        return "Solar Storage Strategy"
    elif strategic_intent == "EXPORT_ARBITRAGE":
        if energy_data.battery_to_grid > energy_data.battery_to_home:
            return "Peak Export Arbitrage"
        else:
            return "Mixed Export Strategy"
    elif strategic_intent == "LOAD_SUPPORT":
        return "Home Load Support"
    else:  # IDLE
        if energy_data.solar_production > 0.1 and energy_data.grid_imported < 0.1:
            return "Solar Self-Sufficiency"
        elif energy_data.grid_imported > 0.1 and energy_data.solar_production < 0.1:
            return "Grid Supply Mode"
        else:
            return "Optimal Idle"


def generate_flow_description(energy_data: EnergyData) -> str:
    """
    Generate human-readable flow description.

    Args:
        energy_data: Complete energy flow data

    Returns:
        Human-readable description of energy flows

    Examples:
        - "Solar 4.2kWh: 1.8kWh→Home, 2.4kWh→Battery"
        - "Grid 3.0kWh→Battery; Battery 5.2kWh→Home"
        - "Solar 8.0kWh: 3.0kWh→Home, 2.0kWh→Battery, 3.0kWh→Grid"
    """
    descriptions = []
    threshold = 0.1  # kWh threshold for reporting

    # Solar flows description
    if energy_data.solar_production > threshold:
        solar_flows = []
        if energy_data.solar_to_home > threshold:
            solar_flows.append(f"{energy_data.solar_to_home:.1f}kWh→Home")
        if energy_data.solar_to_battery > threshold:
            solar_flows.append(f"{energy_data.solar_to_battery:.1f}kWh→Battery")
        if energy_data.solar_to_grid > threshold:
            solar_flows.append(f"{energy_data.solar_to_grid:.1f}kWh→Grid")

        if solar_flows:
            solar_desc = (
                f"Solar {energy_data.solar_production:.1f}kWh: "
                f"{', '.join(solar_flows)}"
            )
            descriptions.append(solar_desc)

    # Grid import flows description
    grid_flows = []
    if energy_data.grid_to_home > threshold:
        grid_flows.append(f"{energy_data.grid_to_home:.1f}kWh→Home")
    if energy_data.grid_to_battery > threshold:
        grid_flows.append(f"{energy_data.grid_to_battery:.1f}kWh→Battery")

    if grid_flows:
        total_grid_import = energy_data.grid_to_home + energy_data.grid_to_battery
        grid_desc = f"Grid {total_grid_import:.1f}kWh: {', '.join(grid_flows)}"
        descriptions.append(grid_desc)

    # Battery discharge flows description
    battery_flows = []
    if energy_data.battery_to_home > threshold:
        battery_flows.append(f"{energy_data.battery_to_home:.1f}kWh→Home")
    if energy_data.battery_to_grid > threshold:
        battery_flows.append(f"{energy_data.battery_to_grid:.1f}kWh→Grid")

    if battery_flows:
        total_battery_discharge = (
            energy_data.battery_to_home + energy_data.battery_to_grid
        )
        battery_desc = (
            f"Battery {total_battery_discharge:.1f}kWh: " f"{', '.join(battery_flows)}"
        )
        descriptions.append(battery_desc)

    return "; ".join(descriptions) if descriptions else "No significant energy flows"


def generate_economic_chain(
    hour: int,
    energy_data: EnergyData,
    strategic_intent: str,
    immediate_value: float,
    future_value: float,
    cost_basis: float,
) -> str:
    """
    Generate economic chain explanation.

    Shows immediate action → future opportunity → net value.

    Args:
        hour: Current hour (0-23)
        energy_data: Complete energy flow data
        strategic_intent: Strategic intent
        immediate_value: Immediate economic value
        future_value: Future economic value
        cost_basis: Cost basis of stored energy (SEK/kWh)

    Returns:
        Economic chain explanation string

    Examples:
        - "Hour 02: Store grid energy (-2.84 SEK) → Future discharge opportunity
          (+7.23 SEK) → Net strategy: +4.39 SEK"
        - "Hour 19: Export arbitrage (+5.12 SEK) ← Previous storage at 1.2 SEK/kWh
          → Arbitrage profit: +3.92 SEK"
    """
    # Build context-specific economic explanations
    if strategic_intent == "GRID_CHARGING":
        if energy_data.grid_to_battery > 0.1:
            storage_amount = energy_data.grid_to_battery
            return (
                f"Hour {hour:02d}: Store {storage_amount:.1f}kWh grid energy "
                f"({immediate_value:+.2f} SEK) → Future discharge opportunity "
                f"(+{future_value:.2f} SEK) → Net strategy: "
                f"{immediate_value + future_value:+.2f} SEK"
            )
        else:
            return (
                f"Hour {hour:02d}: Grid charging strategy "
                f"({immediate_value:+.2f} SEK) → Expected future value "
                f"(+{future_value:.2f} SEK) → Net: "
                f"{immediate_value + future_value:+.2f} SEK"
            )

    elif strategic_intent == "SOLAR_STORAGE":
        if energy_data.solar_to_battery > 0.1:
            storage_amount = energy_data.solar_to_battery
            return (
                f"Hour {hour:02d}: Store {storage_amount:.1f}kWh free solar "
                f"({immediate_value:+.2f} SEK) → Future value realization "
                f"(+{future_value:.2f} SEK) → Net strategy: "
                f"{immediate_value + future_value:+.2f} SEK"
            )
        else:
            return (
                f"Hour {hour:02d}: Solar storage strategy "
                f"({immediate_value:+.2f} SEK) → Future opportunity "
                f"(+{future_value:.2f} SEK) → Net: "
                f"{immediate_value + future_value:+.2f} SEK"
            )

    elif strategic_intent == "EXPORT_ARBITRAGE":
        if energy_data.battery_to_grid > 0.1:
            export_amount = energy_data.battery_to_grid
            return (
                f"Hour {hour:02d}: Export {export_amount:.1f}kWh for arbitrage "
                f"(+{immediate_value:.2f} SEK) ← Previous storage at "
                f"{cost_basis:.2f} SEK/kWh → Arbitrage profit: "
                f"{immediate_value:+.2f} SEK"
            )
        else:
            return (
                f"Hour {hour:02d}: Export arbitrage execution "
                f"(+{immediate_value:.2f} SEK) ← Strategic storage "
                f"→ Net profit: {immediate_value:+.2f} SEK"
            )

    elif strategic_intent == "LOAD_SUPPORT":
        if energy_data.battery_to_home > 0.1:
            support_amount = energy_data.battery_to_home
            return (
                f"Hour {hour:02d}: Battery supplies {support_amount:.1f}kWh to home "
                f"({immediate_value:+.2f} SEK saved) ← Previous strategic storage at "
                f"{cost_basis:.2f} SEK/kWh → Net value: {immediate_value:+.2f} SEK"
            )
        else:
            # Edge case: LOAD_SUPPORT intent but no significant battery_to_home
            # This could happen with very small discharge amounts or calculation edge cases
            return (
                f"Hour {hour:02d}: Minimal battery home support "
                f"({immediate_value:+.2f} SEK) ← Battery available but minimal "
                f"discharge needed → Net value: {immediate_value:+.2f} SEK"
            )

    else:  # IDLE
        return (
            f"Hour {hour:02d}: Optimal idle - no beneficial battery action available "
            f"→ Net value: {immediate_value:+.2f} SEK"
        )


def calculate_detailed_flow_values(
    energy_data: EnergyData, buy_price: float, sell_price: float
) -> dict[str, float]:
    """
    Calculate economic value for each individual energy flow.

    Implements detailed flow value analysis from decisionframework.md showing
    the economic impact of each energy pathway.

    Args:
        energy_data: Complete energy flow data
        buy_price: Current electricity purchase price (SEK/kWh)
        sell_price: Current electricity sale price (SEK/kWh)

    Returns:
        Dict mapping flow names to economic values (SEK)

    Examples:
        {
            "solar_to_home": +2.34,  # Avoided grid cost
            "battery_to_home": +1.89,  # Avoided grid cost
            "battery_to_grid": +0.87,  # Export revenue
            "grid_to_home": -1.45,  # Import cost
            "grid_to_battery": -0.67  # Import cost
        }
    """
    flow_values = {}
    threshold = 0.1  # kWh threshold for reporting

    # Solar flows (always positive - free energy or avoided costs)
    if energy_data.solar_to_home > threshold:
        # Solar to home avoids grid purchase
        flow_values["solar_to_home"] = energy_data.solar_to_home * buy_price

    if energy_data.solar_to_battery > threshold:
        # Solar to battery stores free energy (value realized when discharged)
        # For immediate calculation, use average of buy/sell as storage value
        storage_value = (buy_price + sell_price) / 2
        flow_values["solar_to_battery"] = energy_data.solar_to_battery * storage_value

    if energy_data.solar_to_grid > threshold:
        # Solar to grid earns export revenue
        flow_values["solar_to_grid"] = energy_data.solar_to_grid * sell_price

    # Grid flows
    if energy_data.grid_to_home > threshold:
        # Grid to home is import cost (negative)
        flow_values["grid_to_home"] = -(energy_data.grid_to_home * buy_price)

    if energy_data.grid_to_battery > threshold:
        # Grid to battery is import cost for storage (negative)
        flow_values["grid_to_battery"] = -(energy_data.grid_to_battery * buy_price)

    # Battery flows (discharge - realizing stored value)
    if energy_data.battery_to_home > threshold:
        # Battery to home avoids grid purchase (positive)
        flow_values["battery_to_home"] = energy_data.battery_to_home * buy_price

    if energy_data.battery_to_grid > threshold:
        # Battery to grid earns export revenue (positive)
        flow_values["battery_to_grid"] = energy_data.battery_to_grid * sell_price

    return flow_values


def extract_economic_values_from_reward(
    reward: float,
    import_cost: float,
    export_revenue: float,
    battery_wear_cost: float,
) -> tuple[float, float]:
    """
    Extract immediate and future values from DP reward calculation.

    Uses the meaningful economic variables from _calculate_reward:
    - import_cost: energy_data.grid_imported * current_buy_price
    - export_revenue: energy_data.grid_exported * current_sell_price
    - battery_wear_cost: battery degradation cost

    Note: action_threshold_penalty is excluded as it's a technical optimization detail,
    not a meaningful economic component for user understanding.

    Args:
        reward: Total reward from DP calculation
        import_cost: Grid import cost this hour
        export_revenue: Grid export revenue this hour
        battery_wear_cost: Battery degradation cost

    Returns:
        Tuple of (immediate_value, future_value)
    """
    # Calculate immediate economic impact (meaningful economic components only)
    immediate_value = export_revenue - import_cost - battery_wear_cost

    # Future value is the remainder of the total reward
    # Note: This includes the action_threshold_penalty in the future value calculation,
    # but we don't expose it separately since it's a technical detail
    future_value = reward - immediate_value

    return immediate_value, future_value


def create_decision_data(
    power: float,
    energy_data: EnergyData,
    hour: int,
    cost_basis: float,
    reward: float,
    import_cost: float,
    export_revenue: float,
    battery_wear_cost: float,
    buy_price: float,
    sell_price: float,
    dt: float,
) -> DecisionData:
    """
    Create enhanced DecisionData with rich pattern analysis and economic reasoning.

    Now determines strategic intent in the decision framework for better separation of concerns.
    Uses meaningful economic variables from _calculate_reward (excludes technical optimization details).
    Implements advanced flow pattern analysis from decisionframework.md.

    Args:
        power: Battery power action (+ charge, - discharge) in kW
        energy_data: Complete energy flow data
        hour: Current hour (0-23)
        cost_basis: Cost basis of stored energy (SEK/kWh)
        reward: Total reward from DP calculation
        import_cost: Grid import cost (energy_data.grid_imported * current_buy_price)
        export_revenue: Grid export revenue (energy_data.grid_exported * current_sell_price)
        battery_wear_cost: Battery degradation cost
        buy_price: Current electricity purchase price (SEK/kWh)
        sell_price: Current electricity sale price (SEK/kWh)
        dt: Period duration in hours (e.g., 0.25 for quarterly, 1.0 for hourly)

    Returns:
        Enhanced DecisionData with all fields populated including advanced flow patterns
    """
    # Determine strategic intent in decision framework (moved from dp_algorithm)
    strategic_intent = determine_strategic_intent(power, energy_data)

    # Generate high-level strategic pattern name
    pattern_name = generate_strategic_pattern_name(strategic_intent, energy_data)

    # Generate detailed flow description (different from pattern name)
    description = generate_flow_description(energy_data)

    # Extract economic values from DP reward calculation using meaningful economic components
    immediate_value, future_value = extract_economic_values_from_reward(
        reward=reward,
        import_cost=import_cost,
        export_revenue=export_revenue,
        battery_wear_cost=battery_wear_cost,
    )

    # Calculate net strategy value
    net_strategy_value = immediate_value + future_value

    # Generate economic chain explanation
    economic_chain = generate_economic_chain(
        hour=hour,
        energy_data=energy_data,
        strategic_intent=strategic_intent,
        immediate_value=immediate_value,
        future_value=future_value,
        cost_basis=cost_basis,
    )

    # Advanced flow pattern analysis from decisionframework.md
    advanced_flow_pattern = generate_advanced_flow_pattern_name(energy_data)

    # Calculate detailed flow values
    detailed_flow_values = calculate_detailed_flow_values(
        energy_data=energy_data, buy_price=buy_price, sell_price=sell_price
    )

    # Simple heuristic for future target hours
    future_target_hours = []
    if strategic_intent in ["GRID_CHARGING", "SOLAR_STORAGE"]:
        # For charging strategies, target typical high-price evening hours
        future_target_hours = [18, 19, 20, 21]
    elif strategic_intent == "EXPORT_ARBITRAGE":
        # For export strategies, this is the realization hour
        future_target_hours = [hour]

    # Create DecisionData with only fields we can implement
    # Convert power (kW) to energy (kWh) for consistency with other period data
    battery_action_kwh = power * dt
    return DecisionData(
        strategic_intent=strategic_intent,
        battery_action=battery_action_kwh,
        cost_basis=cost_basis,
        pattern_name=pattern_name,
        description=description,
        economic_chain=economic_chain,
        immediate_value=immediate_value,
        future_value=future_value,
        net_strategy_value=net_strategy_value,
        advanced_flow_pattern=advanced_flow_pattern,
        detailed_flow_values=detailed_flow_values,
        future_target_hours=future_target_hours,
    )
