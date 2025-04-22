"""Battery optimization algorithm for maximizing profit from electricity price variations.

The algorithm finds and executes profitable charge/discharge cycles by identifying optimal
trading opportunities based on hourly electricity prices. It respects battery constraints
and household consumption limits while maximizing potential savings.

Algorithm Overview:
1. Trade Discovery:
   - For each hour pair (charge_hour, discharge_hour), calculate potential profit
   - Profit = discharge_price - charge_price - cycle_cost
   - Keep trades above minimum (configurable) profit threshold
   - Sort trades by profit per kWh (most profitable first)

2. Trade Execution (iterating through profitable trades):
   a) Charge Planning:
      - Calculate maximum possible charge at charge_hour
      - Limited by max_charge_power_kw (e.g., 6 kW) and remaining battery capacity

   b) Discharge Planning:
      - First try primary discharge at most profitable hour
      - Limited by hourly_consumption (e.g., 3.5 kWh)
      - If energy remains, look for secondary discharge opportunities in other profitable hours
      - Trade is only executed if we can find discharge opportunities for at least 80% of
        the charged amount (e.g., for a 6 kWh charge, must find at least 4.8 kWh of discharge)
        Note: This 80% threshold is a legacy parameter that should be reviewed in future updates

   c) Trade Execution:
      - If discharge plan meets the 80% threshold, apply both charge and discharges
      - Update battery state (state_of_energy) and available discharge capacities
      - Continue until battery capacity is full or no profitable trades remain

Key Features:
- Takes advantage of price variations within the same day
- Handles partial discharges when profitable (above threshold)
- Prioritizes most profitable trades first
- Considers battery cycle costs
- Sophisticated handling of solar vs. grid energy with different cost bases
- Separate processing of solar trades with priority over grid trades

The algorithm implements an advanced approach to solar vs. grid energy optimization:
1. Separates energy by source - Treats solar-charged energy and grid-charged energy
   as separate "pools" with different cost bases
2. Creates dedicated solar trades - Generates specific trade opportunities for solar
   energy with lower cost basis (only wear cost, no acquisition cost)
3. Prioritizes discharge order - Discharges solar-charged energy at lower price thresholds
   while saving grid-charged energy for higher-priced hours
4. Uses solar-priority trade executor - Processes solar trades first before grid trades

Limitations:
- Does not support potential export to grid profits
- Limited to 24-hour optimization horizon

Configurable System Parameters:
- Battery Capacity:
    * total_capacity: Maximum battery level (kWh)
    * reserved_capacity: Minimum battery level (kWh)
- Power Limits:
    * max_charge_power_kw: Maximum charging power (kW) - converted to hourly energy (kWh)
- Home Energy Consumption:
    * hourly_consumption: Maximum discharge rate, based on home usage (kWh)
- Cost/Profit Parameters:
    * cycle_cost: Battery wear cost per kWh charged (SEK)
    * min_profit_threshold: Minimum profit required per kWh for charge/discharge consideration

Constraints:
- Discharge threshold: Must find profitable discharge plan for at least 80% of charged energy
  (Note: This threshold should be reviewed for alignment with current optimization strategy)
- State management: Battery level must always stay between reserved_capacity and total_capacity
- Profitable trades: Each executed trade must have positive profit after cycle costs
- Consumption limit: Cannot discharge more than hourly_consumption in any hour

Usage:
The optimize_battery function takes hourly prices and system parameters, returning a schedule
of charge/discharge actions and their expected cost impact. The schedule ensures all battery
and consumption constraints are met while maximizing potential savings.
"""

import logging

from .savings_calculator import SavingsCalculator, calculate_trade_profitability

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


def optimize_battery(
    prices: list[float],
    total_capacity: float,
    reserved_capacity: float,
    cycle_cost: float,
    hourly_consumption: list[float],
    max_charge_power_kw: float,
    min_profit_threshold: float,
    initial_soc: float | None = None,
    solar_charged: list[float] | None = None,
    virtual_stored_energy: dict | None = None,
) -> dict:
    """Battery optimization using max charge rate with split discharges."""
    n_hours = len(prices)

    if len(hourly_consumption) != n_hours:
        raise ValueError(f"Expected {n_hours} consumption values")

    if solar_charged is None:
        solar_charged = [0.0] * n_hours
    if len(solar_charged) != n_hours:
        raise ValueError(f"Expected {n_hours} solar values")

    # Initialize with current SOC if provided, otherwise use reserved capacity
    initial_energy = (
        (initial_soc / 100.0 * total_capacity)
        if initial_soc is not None
        else reserved_capacity
    )

    # Initialize state tracking arrays - SOE at the START of each hour
    state_of_energy = [initial_energy] * n_hours
    actions = [0.0] * n_hours

    logger.debug(
        "Initial SOC: %s%%, Initial energy: %.1f kWh",
        initial_soc,
        initial_energy,
    )

    # Apply solar charging
    _apply_solar_charging(
        state_of_energy, solar_charged, total_capacity, reserved_capacity, n_hours
    )

    # Execute optimization algorithm to determine battery actions
    _run_battery_optimization(
        prices,
        state_of_energy,
        actions,
        hourly_consumption,
        total_capacity,
        reserved_capacity,
        max_charge_power_kw,
        solar_charged,
        cycle_cost,
        min_profit_threshold,
        n_hours,
        virtual_stored_energy,
    )

    # Reconcile SOE with actions before calculating costs
    _reconcile_soe_with_actions(
        state_of_energy,
        actions,
        solar_charged,
        total_capacity,
        reserved_capacity,
        n_hours,
    )

    total_solar_energy = sum(solar_charged)
    total_virtual_energy = 0.0
    if virtual_stored_energy:
        total_virtual_energy = virtual_stored_energy.get("amount", 0.0)

    total_charging = 0.0
    total_discharging = 0.0
    for action in actions:
        if action > 0:
            total_charging += action
        elif action < 0:
            total_discharging += -action

    total_energy_in = total_solar_energy + total_charging + total_virtual_energy
    total_energy_out = total_discharging

    # Check for significant imbalance (more than 5%)
    if total_energy_out > 0 and total_energy_out > total_energy_in * 1.05:
        logger.warning(
            "Physical constraint violation: Total energy out (%.1f kWh) exceeds input (%.1f kWh) by more than 5%%",
            total_energy_out,
            total_energy_in,
        )
        # Scale back discharge to maintain physical constraints
        scale_factor = total_energy_in / total_energy_out
        logger.info(
            "Scaling discharge by factor %.2f to maintain energy balance", scale_factor
        )

        # Apply scaling to actions and state_of_energy
        for hour in range(n_hours):
            if actions[hour] < 0:  # Discharge action
                actions[hour] *= scale_factor

        # Re-reconcile battery state
        _reconcile_soe_with_actions(
            state_of_energy,
            actions,
            solar_charged,
            total_capacity,
            reserved_capacity,
            n_hours,
        )

    # Calculate costs and savings using the original algorithm's approach
    result = _calculate_costs_and_savings(
        prices,
        actions,
        solar_charged,
        hourly_consumption,
        cycle_cost,
        state_of_energy,
        n_hours,
    )

    # IMPORTANT: Pre-verify with SavingsCalculator to ensure we detect negative savings
    # Create an instance of SavingsCalculator (used by Schedule)
    calc = SavingsCalculator(cycle_cost, hourly_consumption)

    # Calculate results as the Schedule would
    hourly_results = calc.calculate_hourly_results(
        prices=prices,
        actions=actions,
        state_of_energy=state_of_energy,
        solar_charged_kwh=solar_charged,
    )

    # Get summary as Schedule would calculate it
    schedule_data = calc.format_schedule_data(hourly_results)
    schedule_base_cost = schedule_data["summary"]["baseCost"]
    schedule_optimized_cost = schedule_data["summary"]["optimizedCost"]
    schedule_savings = schedule_data["summary"]["savings"]

    # Log the difference if it exists
    if abs(result["cost_savings"] - schedule_savings) > 0.01:
        logger.warning(
            "Savings calculation mismatch: Algorithm: %.2f, Schedule: %.2f",
            result["cost_savings"],
            schedule_savings,
        )

    # Use the Schedule's calculation to determine if we should keep battery actions
    # as this is what will be displayed to users
    if schedule_savings < 0:
        logger.info(
            "Schedule calculation shows negative savings (%.2f SEK). "
            "Reverting to base case with no battery actions.",
            schedule_savings,
        )

        # Reset actions to no battery activity
        for hour in range(n_hours):
            actions[hour] = 0.0

        # Recalculate state of energy based on solar only (keep initial SOC)
        state_of_energy = [initial_energy] * n_hours
        _apply_solar_charging(
            state_of_energy, solar_charged, total_capacity, reserved_capacity, n_hours
        )

        # Recalculate costs with no actions using the Schedule's method
        hourly_results = calc.calculate_hourly_results(
            prices=prices,
            actions=actions,
            state_of_energy=state_of_energy,
            solar_charged_kwh=solar_charged,
        )

        schedule_data = calc.format_schedule_data(hourly_results)
        schedule_base_cost = schedule_data["summary"]["baseCost"]
        schedule_optimized_cost = schedule_data["summary"]["optimizedCost"]
        schedule_savings = schedule_data["summary"]["savings"]

        # Update result
        result = _calculate_costs_and_savings(
            prices,
            actions,
            solar_charged,
            hourly_consumption,
            cycle_cost,
            state_of_energy,
            n_hours,
        )

        # Override with schedule's values for consistency
        result["base_cost"] = schedule_base_cost
        result["optimized_cost"] = schedule_optimized_cost
        result["cost_savings"] = schedule_savings

    # Calculate battery contribution for logging
    total_charged = 0.0
    total_discharged = 0.0
    for action in actions:
        if action > 0:
            total_charged += action
        elif action < 0:
            total_discharged += -action

    # Add additional solar info to log
    total_solar = 0.0
    for solar in solar_charged:
        if solar > 0:
            total_solar += solar

    # Comprehensive optimization summary with solar info
    logger.info(
        "Optimization complete: Base cost: %.2f SEK, "
        "Optimized cost: %.2f SEK, "
        "Total savings: %.2f SEK, "
        "Solar generation: %.1f kWh, "
        "Battery: %.1f kWh charged, %.1f kWh discharged",
        schedule_base_cost,
        schedule_optimized_cost,
        schedule_savings,
        total_solar,
        total_charged,
        total_discharged,
    )

    return result


def _run_battery_optimization(
    prices,
    state_of_energy,
    actions,
    hourly_consumption,
    total_capacity,
    reserved_capacity,
    max_charge_power_kw,
    solar_charged,
    cycle_cost,
    min_profit_threshold,
    n_hours,
    virtual_stored_energy=None,
):
    """Run the core battery optimization algorithm."""
    # Create virtual "solar trades" based on detected solar charging
    all_trades = []

    # First, generate trades for solar energy
    # Assign a very low virtual "charging price" to solar energy
    solar_price = 0.0

    for hour in range(n_hours):
        if solar_charged[hour] > 0:
            # For each hour with solar charging, find future hours for profitable discharge
            for discharge_hour in range(hour + 1, n_hours):
                discharge_price = prices[discharge_hour]

                profit_per_kwh = discharge_price - solar_price - cycle_cost

                # Only consider profitable discharges
                if profit_per_kwh > min_profit_threshold:
                    solar_trade = {
                        "charge_hour": hour,
                        "discharge_hour": discharge_hour,
                        "charge_price": solar_price,
                        "discharge_price": discharge_price,
                        "cycle_cost": cycle_cost,
                        "profit_per_kwh": profit_per_kwh,
                        "is_solar": True,  # Mark as solar trade for special handling
                        # The amount available
                        "solar_amount": solar_charged[hour],
                    }
                    all_trades.append(solar_trade)

    # Add virtual trades for energy already stored in the battery
    if virtual_stored_energy is not None and virtual_stored_energy.get("amount", 0) > 0:
        stored_energy = virtual_stored_energy["amount"]
        stored_price = virtual_stored_energy["price"]

        # Get solar ratio if available
        solar_ratio = virtual_stored_energy.get("solar_ratio", 0.0)
        logger.debug(
            "Virtual stored energy: %.1f kWh with solar ratio %.1f%%",
            stored_energy,
            solar_ratio * 100,
        )

        # Create trades from virtual stored energy to all future hours
        for discharge_hour in range(n_hours):
            discharge_price = prices[discharge_hour]

            # CRITICAL FIX: Skip hours where price is below stored energy cost
            if discharge_price <= stored_price:
                logger.debug(
                    "Skipping virtual trade hour %d - price %.3f below stored energy cost %.3f",
                    discharge_hour,
                    discharge_price,
                    stored_price,
                )
                continue

            # If is_blended_cost is true, the cost already includes wear
            if virtual_stored_energy.get("is_blended_cost", False):
                discharge_cycle_cost = 0  # Cost already included
            else:
                # Adjust discharge cost based on solar ratio
                discharge_cycle_cost = cycle_cost * 0.5 * (1 - solar_ratio * 0.5)

            profit_per_kwh = discharge_price - stored_price - discharge_cycle_cost

            if profit_per_kwh >= min_profit_threshold:
                virtual_trade = {
                    "charge_hour": -1,  # Special marker for virtual energy
                    "discharge_hour": discharge_hour,
                    "charge_price": stored_price,
                    "discharge_price": discharge_price,
                    "cycle_cost": discharge_cycle_cost,
                    "profit_per_kwh": profit_per_kwh,
                    "is_virtual": True,
                    "virtual_amount": stored_energy,
                    "solar_ratio": solar_ratio,
                }
                all_trades.append(virtual_trade)
                logger.debug(
                    "Added virtual trade: Discharge at hour %d, profit: %.3f per kWh",
                    discharge_hour,
                    profit_per_kwh,
                )

    # Then, find regular grid charging trades
    grid_trades = _find_profitable_trades(prices, cycle_cost, min_profit_threshold)
    all_trades.extend(grid_trades)

    # Sort all trades by profit per kWh (most profitable first)
    all_trades = _sort_trades_by_profit(all_trades)

    # Execute trades
    _execute_trades_with_solar_priority(
        all_trades,
        state_of_energy,
        actions,
        hourly_consumption,
        total_capacity,
        reserved_capacity,
        max_charge_power_kw,
        solar_charged,
        prices,
        cycle_cost,
        n_hours,
    )


def _execute_trades_with_solar_priority(
    trades,
    state_of_energy,
    actions,
    hourly_consumption,
    total_capacity,
    reserved_capacity,
    max_charge_power_kw,
    solar_charged,
    prices,
    cycle_cost,
    n_hours,
):
    """Execute profitable trades and update battery state, with priority for solar energy."""
    logger.debug("Executing trades with solar priority")

    # Initialize tracking data
    discharge_capacities = {}
    for h in range(n_hours):
        discharge_capacities[h] = hourly_consumption[h]

    # Calculate initial energy
    total_energy_in = 0.0
    for solar in solar_charged:
        if solar > 0:
            total_energy_in += solar

    # Track total solar energy from all sources
    total_solar_energy = total_energy_in

    # Calculate available capacity for charging
    energy_for_discharge = total_capacity - state_of_energy[0]

    logger.debug(
        "Initial energy: %.1f kWh (including %.1f kWh from solar)",
        total_energy_in,
        total_solar_energy,
    )
    logger.debug("Available capacity for charging: %.1f kWh", energy_for_discharge)

    # Process virtual stored energy trades (energy already in battery)
    virtual_trades = []
    for t in trades:
        if t.get("is_virtual", False):
            virtual_trades.append(t)  # noqa: PERF401

    if virtual_trades:
        virtual_energy_out = _process_virtual_trades(
            virtual_trades,
            state_of_energy,
            actions,
            discharge_capacities,
            prices,
            cycle_cost,
            total_capacity,
            reserved_capacity,
            n_hours,
            total_energy_out=0.0,
        )
        # Update total energy tracking
        total_energy_in += virtual_trades[0].get("virtual_amount", 0)
        total_energy_out = virtual_energy_out
    else:
        total_energy_out = 0.0

    # Process solar trades with high priority
    solar_trades = []
    for t in trades:
        if t.get("is_solar", False):
            solar_trades.append(t)  # noqa: PERF401

    if solar_trades:
        solar_energy_out = _process_solar_trades(
            solar_trades,
            state_of_energy,
            actions,
            discharge_capacities,
            prices,
            cycle_cost,
            total_capacity,
            reserved_capacity,
            n_hours,
            total_energy_in,
            total_energy_out,
        )
        # Update total energy tracking
        total_energy_out += solar_energy_out

    # Process regular grid trades
    grid_trades = []
    for t in trades:
        if not t.get("is_solar", False) and not t.get("is_virtual", False):
            grid_trades.append(t)  # noqa: PERF401

    if grid_trades:
        grid_energy_in, grid_energy_out = _process_grid_trades(
            grid_trades,
            trades,
            state_of_energy,
            actions,
            discharge_capacities,
            prices,
            cycle_cost,
            max_charge_power_kw,
            total_capacity,
            reserved_capacity,
            n_hours,
            total_energy_in,
            total_energy_out,
            energy_for_discharge,
            virtual_stored_energy=None,  # No virtual stored energy by default
        )
        # Update tracking
        total_energy_in += grid_energy_in
        total_energy_out += grid_energy_out

    # Validate final state
    _validate_final_state(actions, state_of_energy, total_capacity, n_hours)

    # Log final energy balance
    logger.debug(
        "Final energy balance - In: %.1f kWh, Out: %.1f kWh",
        total_energy_in,
        total_energy_out,
    )

    # Verify energy balance
    max_imbalance = 0.1  # Small tolerance for floating-point errors
    if total_energy_out > total_energy_in + max_imbalance:
        logger.warning(
            "Energy balance violation! In: %.1f kWh, Out: %.1f kWh",
            total_energy_in,
            total_energy_out,
        )

        # Fix by scaling back actions to maintain energy balance
        # This is critical to ensure physical feasibility
        scale_factor = (
            total_energy_in / total_energy_out if total_energy_out > 0 else 0.0
        )

        # Only scale if significant imbalance (more than just rounding error)
        if scale_factor < 0.99:
            logger.info(
                "Scaling back discharge actions by factor %.2f to maintain energy balance",
                scale_factor,
            )

            # Scale all discharge actions
            for hour in range(n_hours):
                if actions[hour] < 0:  # Discharge action
                    actions[hour] *= scale_factor

            # Recalculate total energy out
            total_energy_out = 0.0
            for hour in range(n_hours):
                if actions[hour] < 0:  # Discharge action
                    total_energy_out -= actions[hour]

            logger.info(
                "After scaling: Energy Out = %.1f kWh (should be close to %.1f kWh)",
                total_energy_out,
                total_energy_in,
            )


def _sort_trades_by_profit(trades):
    """Sort trades by profit per kWh in descending order."""
    # Manual sort for pyscript compatibility
    result = trades.copy()
    for i in range(len(result)):
        for j in range(i + 1, len(result)):
            profit_i = result[i].get("profit_per_kwh", 0)
            profit_j = result[j].get("profit_per_kwh", 0)
            if profit_j > profit_i:
                # Swap
                result[i], result[j] = result[j], result[i]
    return result


"""Patch for the _process_virtual_trades function in optimize_battery."""


def _process_virtual_trades(
    virtual_trades,
    state_of_energy,
    actions,
    discharge_capacities,
    prices,
    cycle_cost,
    total_capacity,
    reserved_capacity,
    n_hours,
    total_energy_out=0.0,
):
    """Process virtual stored energy trades (energy already in battery).

    This improved implementation ensures that energy already in the battery
    is appropriately discharged during all profitable hours, not just the
    hours with absolute highest prices.

    Key changes:
    1. Evaluates discharge opportunities for all hours, not just those in virtual_trades
    2. Prioritizes profitable discharge opportunities by profit per kWh
    3. Adds detailed logging of discharge opportunities for better visibility

    Args:
        virtual_trades: List of trades for virtual stored energy
        state_of_energy: Array of battery energy states
        actions: Array of battery actions to update
        discharge_capacities: Dict of remaining discharge capacity by hour
        prices: List of hourly electricity prices
        cycle_cost: Battery wear cost per kWh
        total_capacity: Maximum battery capacity (kWh)
        reserved_capacity: Minimum battery capacity (kWh)
        n_hours: Number of hours
        total_energy_out: Total energy output so far (kWh)

    Returns:
        float: Total virtual energy discharged
    """
    # Skip if no virtual trades
    if not virtual_trades:
        return 0.0

    # Get total available virtual energy and its cost basis
    available_virtual_energy = virtual_trades[0].get("virtual_amount", 0)
    stored_price = virtual_trades[0].get("charge_price", 0)
    logger.debug("Processing virtual stored energy: %.1f kWh", available_virtual_energy)

    # IMPROVEMENT: Evaluate ALL hours for potential discharge
    # Not just those in virtual_trades (which might be incomplete)
    discharge_opportunities = []

    for hour in range(n_hours):
        # Skip hours with no discharge capacity
        if discharge_capacities.get(hour, 0) <= 0:
            continue

        # Skip if SOE is insufficient
        if hour > 0 and state_of_energy[hour] <= reserved_capacity + 0.1:
            continue

        # Skip if price is too low (unprofitable)
        discharge_price = prices[hour]
        if discharge_price <= stored_price:
            logger.debug(
                "Hour %d: Price %.3f below stored energy cost %.3f - skipping",
                hour,
                discharge_price,
                stored_price,
            )
            continue

        # Determine cycle cost application (already included in some cases)
        cycle_cost_value = 0.0
        if not virtual_trades[0].get("is_blended_cost", False):
            cycle_cost_value = cycle_cost * 0.5  # Only discharge portion

        profit_per_kwh = discharge_price - stored_price - cycle_cost_value

        # Skip if unprofitable
        if profit_per_kwh <= 0:
            continue

        # Calculate maximum discharge amount
        max_discharge = min(
            available_virtual_energy,
            discharge_capacities[hour],
            state_of_energy[hour] - reserved_capacity
            if hour > 0
            else available_virtual_energy,
        )

        # Skip if amount is too small
        if max_discharge < 0.1:
            continue

        # Add to opportunities
        discharge_opportunities.append(
            {
                "hour": hour,
                "price": discharge_price,
                "profit_per_kwh": profit_per_kwh,
                "max_discharge": max_discharge,
            }
        )

    # Sort opportunities by profit per kWh (highest first)
    discharge_opportunities.sort(key=lambda x: x["profit_per_kwh"], reverse=True)

    # Log the opportunities found
    if discharge_opportunities:
        logger.debug(
            "Found %d discharge opportunities for virtual energy:",
            len(discharge_opportunities),
        )
        for opp in discharge_opportunities:
            logger.debug(
                "Hour %d: Price %.3f, Profit %.3f/kWh, Max discharge: %.1f kWh",
                opp["hour"],
                opp["price"],
                opp["profit_per_kwh"],
                opp["max_discharge"],
            )
    else:
        logger.debug("No profitable discharge opportunities found for virtual energy")
        return 0.0

    # Process discharge opportunities in order of profitability
    virtual_energy_planned = 0.0
    virtual_energy_out = 0.0

    for opp in discharge_opportunities:
        hour = opp["hour"]
        max_discharge = opp["max_discharge"]

        # Skip if we've planned all virtual energy
        if virtual_energy_planned >= available_virtual_energy:
            break

        # Calculate discharge amount
        discharge_amount = min(
            available_virtual_energy - virtual_energy_planned, max_discharge
        )

        # Skip if amount is too small
        if discharge_amount < 0.1:
            continue

        # Calculate profit
        discharge_price = opp["price"]
        profit = discharge_amount * opp["profit_per_kwh"]

        logger.debug(
            "Virtual energy trade: Discharge %.1f kWh at hour %d (profit: %.2f)",
            discharge_amount,
            hour,
            profit,
        )

        # Apply discharge action
        if actions[hour] != 0:
            actions[hour] -= discharge_amount
        else:
            actions[hour] = -discharge_amount

        # Update tracking variables
        discharge_capacities[hour] -= discharge_amount
        virtual_energy_planned += discharge_amount
        virtual_energy_out += discharge_amount

        # Update SOE for future hours
        _update_soe_after_action(
            state_of_energy,
            hour,
            discharge_amount,
            total_capacity,
            reserved_capacity,
            n_hours,
            is_charging=False,
        )

    logger.debug(
        "Planned discharge of %.1f kWh from virtual stored energy",
        virtual_energy_planned,
    )
    return virtual_energy_out


def _process_solar_trades(
    trades,
    state_of_energy,
    actions,
    discharge_capacities,
    prices,
    cycle_cost,
    total_capacity,
    reserved_capacity,
    n_hours,
    total_energy_in,
    total_energy_out,
):
    """Process solar trades to discharge solar energy."""
    solar_energy_out = 0.0

    # Create a running energy balance tracker
    available_energy = total_energy_in - total_energy_out

    # Log initial energy balance
    logger.debug(
        "Processing solar trades with initial energy balance: In=%.1f, Out=%.1f, Available=%.1f",
        total_energy_in,
        total_energy_out,
        available_energy,
    )

    for trade in trades:
        solar_amount = trade["solar_amount"]
        discharge_hour = trade["discharge_hour"]
        solar_price = trade.get(
            "charge_price", min(prices) * 0.1
        )  # Virtual price for solar
        discharge_price = prices[discharge_hour]

        # Get stored price from the trade itself
        stored_price = trade.get("charge_price", 0)

        # Check if discharge price exceeds stored price
        if discharge_price <= stored_price:
            logger.debug(
                "Skipping solar discharge at hour %d - price %.3f below stored energy cost %.3f",
                discharge_hour,
                discharge_price,
                stored_price,
            )
            continue

        # Check discharge capacity availability
        available_capacity = discharge_capacities[discharge_hour]
        if available_capacity <= 0:
            continue

        # Determine discharge amount - limited by available energy balance
        discharge_amount = min(
            solar_amount,
            available_capacity,
            available_energy,  # This is the key fix
        )

        # Calculate profit - use cycle cost from the trade
        discharge_cycle_cost = trade.get("cycle_cost", cycle_cost * 0.5)
        discharge_profit = discharge_amount * (
            discharge_price - solar_price - discharge_cycle_cost
        )

        # Skip if unprofitable or minimal
        if discharge_profit <= 0:
            logger.debug(
                "Skipping unprofitable solar discharge at hour %d: profit=%.2f",
                discharge_hour,
                discharge_profit,
            )
            continue
        if discharge_amount < 0.5:
            continue

        # Check SOE availability
        if state_of_energy[discharge_hour] - reserved_capacity < discharge_amount:
            continue

        # Check energy balance constraint - redundant but safety check
        if total_energy_out + discharge_amount > total_energy_in:
            logger.debug(
                "Energy balance would be violated at hour %d - limiting discharge",
                discharge_hour,
            )
            discharge_amount = total_energy_in - total_energy_out
            if discharge_amount < 0.5:  # Skip if too small
                continue

        logger.debug(
            "Solar trade: Discharge %.1f kWh at hour %d",
            discharge_amount,
            discharge_hour,
        )

        # Apply discharge action
        if actions[discharge_hour] != 0:
            actions[discharge_hour] -= discharge_amount
        else:
            actions[discharge_hour] = -discharge_amount

        # Update tracking
        discharge_capacities[discharge_hour] -= discharge_amount
        solar_energy_out += discharge_amount
        total_energy_out += discharge_amount
        available_energy = total_energy_in - total_energy_out

        # Update SOE for future hours
        _update_soe_after_action(
            state_of_energy,
            discharge_hour,
            discharge_amount,
            total_capacity,
            reserved_capacity,
            n_hours,
            is_charging=False,
        )

    logger.debug(
        "Completed solar trades: discharged %.1f kWh, remaining energy balance: %.1f kWh",
        solar_energy_out,
        available_energy,
    )
    return solar_energy_out


def _process_grid_trades(
    grid_trades,
    all_trades,
    state_of_energy,
    actions,
    discharge_capacities,
    prices,
    cycle_cost,
    max_charge_power_kw,  # Renamed to clarify this is power in kW
    total_capacity,
    reserved_capacity,
    n_hours,
    total_energy_in,
    total_energy_out,
    energy_for_discharge,
    virtual_stored_energy=None,
):
    """Process regular grid trades for charging and discharging.

    Note:
        max_charge_power_kw is in kW (power), but since we're working with
        hourly intervals, it directly converts to kWh (energy) for each hour.

    Args:
        grid_trades: List of grid-based trade opportunities
        all_trades: List of all trades (including solar and virtual)
        state_of_energy: Array of battery energy states (kWh)
        actions: Array of battery actions (kWh)
        discharge_capacities: Dict of remaining discharge capacity by hour
        prices: List of hourly electricity prices
        cycle_cost: Battery wear cost per kWh
        max_charge_power_kw: Maximum charge power in kW (converts to kWh per hour)
        total_capacity: Maximum battery capacity (kWh)
        reserved_capacity: Minimum battery capacity (kWh)
        n_hours: Number of hours
        total_energy_in: Total energy input so far (kWh)
        total_energy_out: Total energy output so far (kWh)
        energy_for_discharge: Remaining energy for discharge (kWh)
        virtual_stored_energy: Optional info about energy already in battery

    Returns:
        tuple: (grid_energy_in, grid_energy_out) - Energy charged/discharged

    """
    grid_energy_in = 0.0
    grid_energy_out = 0.0

    # Extract stored energy cost basis if available
    stored_energy_cost = None
    if virtual_stored_energy is not None:
        stored_energy_cost = virtual_stored_energy.get("price")
        logger.debug("Using stored energy cost basis: %.3f SEK/kWh", stored_energy_cost)

    for trade in grid_trades:
        charge_hour = trade["charge_hour"]
        charge_price = prices[charge_hour]

        # Skip if we've already planned a grid action for this hour
        if actions[charge_hour] != 0:
            continue

        # Check battery capacity at charge hour
        current_soe = state_of_energy[charge_hour]
        if current_soe >= total_capacity - 0.01:
            logger.debug(
                "Skipping trade at hour %d: Battery already full (SOE: %.1f kWh)",
                charge_hour,
                current_soe,
            )
            continue

        # Calculate charge amount - convert max power (kW) to energy (kWh) for the hour
        # Since we're working with 1-hour intervals, kW directly translates to kWh
        charge_amount = min(max_charge_power_kw, total_capacity - current_soe - 0.01)
        charge_amount = min(charge_amount, energy_for_discharge)

        # Skip if minimal charge
        if charge_amount < 0.1:
            logger.debug(
                "Skipping trade at hour %d: Charge amount too small (%.2f kWh)",
                charge_hour,
                charge_amount,
            )
            continue

        logger.debug(
            "Evaluating trade at hour %d, charge amount: %.1f kWh",
            charge_hour,
            charge_amount,
        )

        # Plan discharges
        discharge_plan = _plan_discharges(
            trade, all_trades, discharge_capacities, charge_amount
        )

        # Check if discharge plan meets requirements
        is_viable, plan = _validate_discharge_plan(
            discharge_plan,
            charge_amount,
            total_energy_in + charge_amount,
            total_energy_out,
        )

        if not is_viable:
            continue

        # Check profitability - pass stored energy cost basis if available
        is_profitable, profit = _check_trade_profitability(
            charge_hour, charge_amount, charge_price, plan, prices, cycle_cost
        )

        # Execute if viable and profitable
        if is_profitable:
            logger.debug("Executing profitable trade with gain: %.2f", profit)

            # Final capacity check
            if current_soe + charge_amount > total_capacity:
                logger.debug(
                    "Final capacity check failed at hour %d: %.1f + %.1f > %.1f",
                    charge_hour,
                    current_soe,
                    charge_amount,
                    total_capacity,
                )
                # Adjust charge amount
                charge_amount = max(0, total_capacity - current_soe - 0.01)
                logger.debug("Adjusted charge amount to %.1f kWh", charge_amount)
                if charge_amount < 0.1:
                    continue

            # Apply charge action
            logger.debug(
                "Executing trade: charge %.1f kWh at hour %d",
                charge_amount,
                charge_hour,
            )
            actions[charge_hour] = charge_amount
            grid_energy_in += charge_amount

            # Update SOE after charging
            _update_soe_after_action(
                state_of_energy,
                charge_hour,
                charge_amount,
                total_capacity,
                reserved_capacity,
                n_hours,
                is_charging=True,
            )

            # Apply discharges
            for discharge_hour, discharge_amount in sorted(plan):
                # IMPORTANT FIX: Skip discharges where price is below stored energy cost
                if (
                    stored_energy_cost is not None
                    and prices[discharge_hour] <= stored_energy_cost
                ):
                    logger.debug(
                        "Skipping discharge at hour %d - price %.3f below stored energy cost %.3f",
                        discharge_hour,
                        prices[discharge_hour],
                        stored_energy_cost,
                    )
                    continue

                # Check SOE availability again
                discharge_soe = state_of_energy[discharge_hour]
                actual_discharge = min(
                    discharge_amount, discharge_soe - reserved_capacity
                )

                if actual_discharge < discharge_amount:
                    logger.debug(
                        "Reducing discharge at hour %d from %.1f kWh "
                        "to %.1f kWh due to insufficient SOE",
                        discharge_hour,
                        discharge_amount,
                        actual_discharge,
                    )
                    discharge_amount = actual_discharge

                if discharge_amount <= 0:
                    continue

                logger.debug(
                    "Discharge at hour %d: %.1f kWh",
                    discharge_hour,
                    discharge_amount,
                )

                # Update actions
                if actions[discharge_hour] != 0:
                    actions[discharge_hour] -= discharge_amount
                else:
                    actions[discharge_hour] = -discharge_amount

                discharge_capacities[discharge_hour] -= discharge_amount
                grid_energy_out += discharge_amount

                # Update SOE after discharging
                _update_soe_after_action(
                    state_of_energy,
                    discharge_hour,
                    discharge_amount,
                    total_capacity,
                    reserved_capacity,
                    n_hours,
                    is_charging=False,
                )

            # Update remaining energy for discharge
            energy_for_discharge -= charge_amount
            logger.debug(
                "Remaining energy for discharge: %.1f kWh",
                energy_for_discharge,
            )

    return grid_energy_in, grid_energy_out


def _validate_discharge_plan(
    discharge_plan, charge_amount, potential_total_in, total_energy_out
):
    """Validate and potentially scale the discharge plan.

    Ensures the discharge plan meets minimum requirements and energy balance constraints.

    Args:
        discharge_plan: List of (hour, amount) tuples for planned discharges
        charge_amount: Amount of energy charged (kWh)
        potential_total_in: Total energy input including this charge (kWh)
        total_energy_out: Total energy output already accounted for (kWh)
        state_of_energy: Array of battery energy states (kWh)
        reserved_capacity: Minimum battery capacity (kWh)

    Returns:
        tuple: (is_viable, plan) - Whether plan is viable and possibly modified plan

    Note:
        Uses a legacy 80% threshold that requires at least 80% of charged energy
        to have profitable discharge opportunities. This threshold should be
        reviewed in future updates as it may not align with current optimization strategy.

    """
    # Calculate total discharge in the plan
    plan_total_discharge = 0.0
    for _, amount in discharge_plan:
        plan_total_discharge += amount

    # Check if plan meets minimum discharge requirement (80% of charge)
    # NOTE: This 80% threshold is a legacy parameter that should be reviewed
    # It requires finding discharge opportunities for at least 80% of charged energy
    DISCHARGE_THRESHOLD_PCT = 0.8  # Consider making this a configurable parameter
    if plan_total_discharge < charge_amount * DISCHARGE_THRESHOLD_PCT:
        return False, discharge_plan

    # Check energy balance constraint
    potential_total_out = total_energy_out + plan_total_discharge

    if potential_total_out > potential_total_in and plan_total_discharge > 0:
        logger.debug(
            "Energy balance would be violated: in=%.1f, out=%.1f - adjusting plan",
            potential_total_in,
            potential_total_out,
        )
        # Scale down discharge plan
        scale_factor = (potential_total_in - total_energy_out) / plan_total_discharge
        scaled_plan = []
        for hour, amount in discharge_plan:
            scaled_amount = amount * scale_factor
            if scaled_amount >= 0.1:  # Only keep meaningful amounts
                scaled_plan.append((hour, scaled_amount))

        # Calculate total of scaled plan
        scaled_plan_total = 0.0
        for _, amount in scaled_plan:
            scaled_plan_total += amount

        logger.debug(
            "Adjusted discharge plan total: %.1f kWh",
            scaled_plan_total,
        )
        return True, scaled_plan

    return True, discharge_plan


def _validate_final_state(actions, state_of_energy, total_capacity, n_hours):
    """Perform final validation of battery state and actions."""
    for hour in range(n_hours):
        if actions[hour] > 0:  # Only check charging actions
            soe = state_of_energy[hour]
            if soe >= total_capacity - 0.01:
                logger.warning(
                    "Capacity constraint violation at hour %d: SOE=%.1f, action=%.1f",
                    hour,
                    soe,
                    actions[hour],
                )
                # Zero out the charge action if battery is already full
                actions[hour] = 0.0


def _reconcile_soe_with_actions(
    state_of_energy, actions, solar_charged, total_capacity, reserved_capacity, n_hours
):
    """Ensure SOE array is consistent with actions array.

    This function reconciles the state of energy (SOE) array with the actions array
    to ensure consistency between battery actions and their effect on battery state.
    It reconstructs the SOE array by starting with the initial SOE and applying
    each hour's action and solar charging to calculate the next hour's SOE.

    Args:
        state_of_energy: Array of battery energy levels for each hour
        actions: Array of charge/discharge actions for each hour
        solar_charged: Array of solar charging amounts for each hour
        total_capacity: Maximum battery capacity in kWh
        reserved_capacity: Minimum battery capacity in kWh
        n_hours: Number of hours

    """
    # Start with the initial SOE
    initial_soe = state_of_energy[0]

    # Reconstruct SOE array based on actions and solar
    new_soe = [initial_soe]
    for hour in range(n_hours - 1):
        current_soe = new_soe[hour]
        action = actions[hour]
        solar = solar_charged[hour]

        # Calculate next SOE
        next_soe = current_soe + action + solar
        next_soe = min(next_soe, total_capacity)
        next_soe = max(next_soe, reserved_capacity)

        new_soe.append(next_soe)
        logger.debug(
            "Reconciled SOE[%d] = %.2f kWh (from SOE[%d]=%.2f + action=%.2f + solar=%.2f)",
            hour + 1,
            next_soe,
            hour,
            current_soe,
            action,
            solar,
        )

    # Update the original SOE array
    for hour in range(n_hours):
        state_of_energy[hour] = new_soe[hour]

    logger.debug("Reconciled SOE array to match actions and solar charging")


def _check_trade_profitability(
    charge_hour,
    charge_amount,
    charge_price,
    discharge_plan,
    prices,
    cycle_cost,
):
    """Check if a trade is truly profitable after accounting for all costs."""
    total_profit = 0.0

    for discharge_hour, discharge_amount in discharge_plan:
        discharge_price = prices[discharge_hour]

        # Use the shared function for consistent calculations
        is_profitable, profit = calculate_trade_profitability(
            charge_price=charge_price,
            discharge_price=discharge_price,
            charge_amount=discharge_amount,
            cycle_cost=cycle_cost,
        )

        total_profit += profit

    is_profitable = total_profit > 0

    if not is_profitable:
        logger.debug(
            "Trade rejected - not profitable: "
            "Charge %.1f kWh @ %.3f, "
            "Discharge plan: %s, "
            "Net profit: %.2f",
            charge_amount,
            charge_price,
            discharge_plan,
            total_profit,
        )
    else:
        logger.debug(
            "Trade is profitable: "
            "Charge %.1f kWh @ %.3f, "
            "Discharge plan: %s, "
            "Net profit: %.2f",
            charge_amount,
            charge_price,
            discharge_plan,
            total_profit,
        )

    return is_profitable, total_profit


def _apply_solar_charging(
    state_of_energy, solar_charged, total_capacity, reserved_capacity, n_hours
):
    """Apply solar charging to battery state of energy."""
    logger.debug("Applying solar charging")

    for hour in range(n_hours):
        if solar_charged[hour] > 0:
            logger.debug("Hour %d: Adding %.1f kWh solar", hour, solar_charged[hour])

            # ONLY update future hours, NOT current hour
            for future_hour in range(hour + 1, n_hours):
                old_soe = state_of_energy[future_hour]
                new_soe = min(old_soe + solar_charged[hour], total_capacity)
                new_soe = max(new_soe, reserved_capacity)
                state_of_energy[future_hour] = new_soe


def _create_trade(
    charge_hour, discharge_hour, charge_price, discharge_price, cycle_cost
):
    """Create a trade dictionary with profit calculation."""
    return {
        "charge_hour": charge_hour,
        "discharge_hour": discharge_hour,
        "charge_price": charge_price,
        "discharge_price": discharge_price,
        "cycle_cost": cycle_cost,
        "profit_per_kwh": discharge_price - charge_price - cycle_cost,
    }


def _find_profitable_trades(prices, cycle_cost, min_profit_threshold):
    """Find all profitable trades keeping chronological order."""
    n_hours = len(prices)
    profitable_trades = []

    for charge_hour in range(n_hours):
        charge_price = prices[charge_hour]
        for discharge_hour in range(charge_hour + 1, n_hours):
            discharge_price = prices[discharge_hour]
            trade = _create_trade(
                charge_hour=charge_hour,
                discharge_hour=discharge_hour,
                charge_price=charge_price,
                discharge_price=discharge_price,
                cycle_cost=cycle_cost,
            )
            if trade["profit_per_kwh"] >= min_profit_threshold:
                profitable_trades.append(trade)

    # Sort trades by profit per kWh (most profitable first)
    profitable_trades.sort(key=lambda x: x.get("profit_per_kwh", 0), reverse=True)
    return profitable_trades


def _plan_discharges(primary_trade, trades, discharge_capacities, energy_to_discharge):
    """Plan discharge opportunities for a charge amount."""
    discharge_plan = []

    # Primary discharge
    discharge_hour = primary_trade["discharge_hour"]
    remaining_capacity = discharge_capacities.get(discharge_hour, 0)

    if remaining_capacity > 0:
        primary_discharge = min(remaining_capacity, energy_to_discharge)
        if primary_discharge > 0:
            discharge_plan.append((discharge_hour, primary_discharge))
            energy_to_discharge -= primary_discharge
            logger.debug(
                "Primary discharge: %.1f kWh at hour %d",
                primary_discharge,
                discharge_hour,
            )

    # Look for secondary discharge opportunities
    if energy_to_discharge > 0:
        for secondary_trade in trades:
            if energy_to_discharge <= 0:
                break
            if (
                secondary_trade["discharge_hour"] != primary_trade["discharge_hour"]
                and secondary_trade.get("charge_hour", -99)
                # Handle virtual trades
                == primary_trade.get("charge_hour", -98)
                and discharge_capacities.get(secondary_trade["discharge_hour"], 0) > 0
                and secondary_trade.get("profit_per_kwh", 0) > 0
            ):
                secondary_discharge = min(
                    discharge_capacities.get(secondary_trade["discharge_hour"], 0),
                    energy_to_discharge,
                )
                if secondary_discharge > 0:
                    discharge_plan.append(
                        (secondary_trade["discharge_hour"], secondary_discharge)
                    )
                    energy_to_discharge -= secondary_discharge
                    logger.debug(
                        "Secondary discharge: %.1f kWh at hour %d",
                        secondary_discharge,
                        secondary_trade["discharge_hour"],
                    )

    # Even if we couldn't plan any discharges, return an empty plan (not None)
    return discharge_plan


def _update_soe_after_action(
    state_of_energy,
    action_hour,
    amount,
    total_capacity,
    reserved_capacity,
    n_hours,
    is_charging,
):
    """Update state of energy after a charge or discharge action."""
    if action_hour < n_hours - 1:
        for future_hour in range(action_hour + 1, n_hours):
            old_soe = state_of_energy[future_hour]

            if is_charging:
                # When charging, add energy (but don't exceed capacity)
                new_soe = min(old_soe + amount, total_capacity)
            else:
                # When discharging, subtract energy (but don't go below reserve)
                new_soe = max(old_soe - amount, reserved_capacity)

            # Ensure the update is actually applied
            state_of_energy[future_hour] = new_soe

            # Debug log to verify updates are happening
            logger.debug(
                "Updated SOE[%d] = %.2f kWh after %s of %.2f kWh at hour %d",
                future_hour,
                new_soe,
                "charge" if is_charging else "discharge",
                amount,
                action_hour,
            )


def _calculate_costs_and_savings(
    prices,
    actions,
    solar_charged,
    hourly_consumption,
    cycle_cost,
    state_of_energy,
    n_hours,
):
    """Calculate costs and savings from battery optimization using SavingsCalculator.

    This function delegates all cost calculation logic to the SavingsCalculator to ensure
    consistency across the system.
    """
    logger.debug("Calculating costs and savings")

    # IMPORTANT: Use SavingsCalculator for all cost calculations
    # This ensures consistency between algorithm cost calculations and schedule display
    calc = SavingsCalculator(cycle_cost, hourly_consumption)

    # Calculate results for all hours
    hourly_results = calc.calculate_hourly_results(
        prices=prices,
        actions=actions,
        state_of_energy=state_of_energy,
        solar_charged_kwh=solar_charged,
    )

    # Get summary from SavingsCalculator
    schedule_data = calc.format_schedule_data(hourly_results)

    # Extract values from the computed summary
    base_cost = schedule_data["summary"]["baseCost"]
    optimized_cost = schedule_data["summary"]["optimizedCost"]
    cost_savings = schedule_data["summary"]["savings"]

    # Format hourly costs in the format expected by the original function
    hourly_costs = []
    for result in hourly_results:
        hour_costs = {
            "base_cost": result.base_cost,
            "grid_cost": result.grid_cost,
            "battery_cost": result.battery_cost,
            "total_cost": result.total_cost,
            "savings": result.savings,
        }
        hourly_costs.append(hour_costs)

    # Calculate total solar using loop (avoid list comprehension for pyscript compatibility)
    total_solar = 0.0
    for h in range(len(solar_charged)):
        total_solar += solar_charged[h]

    # Calculate solar value using loop (avoid generator expression for pyscript compatibility)
    solar_value = 0.0
    for h in range(n_hours):
        min_value = min(solar_charged[h], hourly_consumption[h])
        solar_value += min_value * prices[h]

    # Create the result dictionary
    result = {
        "state_of_energy": state_of_energy,  # SOE at START of each hour
        "actions": actions,
        "base_cost": base_cost,
        "optimized_cost": optimized_cost,
        "cost_savings": cost_savings,
        "hourly_costs": hourly_costs,
        "solar_charged": solar_charged,
        "total_solar": total_solar,
        "solar_value": solar_value,
    }

    # Log the final costs to ensure consistency across all displays
    logger.debug(
        "Optimization complete: Base cost: %.2f, Optimized: %.2f, Savings: %.2f",
        result["base_cost"],
        result["optimized_cost"],
        result["cost_savings"],
    )

    return result
