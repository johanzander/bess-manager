"""
Decision Intelligence Generator.

Generates enhanced decision data with pattern analysis, economic chains,
and user-friendly explanations for battery optimization decisions.

This module enhances the existing DecisionData fields without creating new classes,
maintaining compatibility with the existing software architecture.
"""

from core.bess.models import DecisionData, EnergyData


def determine_strategic_intent(power: float, energy_data: EnergyData) -> str:
    """
    Determine strategic intent based on battery action and energy flows.

    This moves the strategic intent logic from dp_algorithm to decision framework
    for better separation of concerns.

    Args:
        power: Battery power in kW (+ charging, - discharging)
        energy_data: Complete energy flow data

    Returns:
        Strategic intent string
    """
    if power > 0.1:  # CHARGING
        if energy_data.grid_to_battery > 0.1:  # ANY grid charging needs capability
            return "GRID_CHARGING"  # Enable grid charging capability
        else:
            return "SOLAR_STORAGE"  # Pure solar charging
    elif power < -0.1:  # DISCHARGING
        if energy_data.battery_to_grid > 0.1:  # ANY export needs capability
            return "EXPORT_ARBITRAGE"  # Enable export capability
        else:
            return "LOAD_SUPPORT"  # Pure home support
    else:
        return "IDLE"


def generate_strategic_pattern_name(
    strategic_intent: str, energy_data: EnergyData
) -> str:
    """
    Generate high-level strategic pattern name based on action and intent.

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
) -> DecisionData:
    """
    Create enhanced DecisionData with rich pattern analysis and economic reasoning.

    Now determines strategic intent in the decision framework for better separation of concerns.
    Uses meaningful economic variables from _calculate_reward (excludes technical optimization details).

    Args:
        power: Battery power action (+ charge, - discharge)
        energy_data: Complete energy flow data
        hour: Current hour (0-23)
        cost_basis: Cost basis of stored energy (SEK/kWh)
        reward: Total reward from DP calculation
        import_cost: Grid import cost (energy_data.grid_imported * current_buy_price)
        export_revenue: Grid export revenue (energy_data.grid_exported * current_sell_price)
        battery_wear_cost: Battery degradation cost

    Returns:
        Enhanced DecisionData with all fields populated
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

    # Create enhanced DecisionData using existing model fields
    return DecisionData(
        strategic_intent=strategic_intent,
        battery_action=power,
        cost_basis=cost_basis,
        # Enhanced fields (existing but previously unused)
        pattern_name=pattern_name,
        description=description,
        economic_chain=economic_chain,
        immediate_value=immediate_value,
        future_value=future_value,
        net_strategy_value=net_strategy_value,
    )
