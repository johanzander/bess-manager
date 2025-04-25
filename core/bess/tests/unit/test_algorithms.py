"""Unit tests for battery optimization algorithms."""

import logging

import pytest
from bess.algorithms import optimize_battery
from bess.schedule import Schedule

logger = logging.getLogger(__name__)


def test_basic_optimization():
    """Test basic optimization with simple price pattern."""

    total_capacity = 10.0
    reserved_capacity = 2.0

    prices = [1.0, 2.0, 0.5, 3.0, 1.5, 0.7, 2.5]
    result = optimize_battery(
        prices=prices,
        total_capacity=10.0,
        reserved_capacity=2.0,
        cycle_cost=0.1,
        hourly_consumption=[1.0] * len(prices),
        max_charge_power_kw=3.0,
        min_profit_threshold=0.1,
    )

    schedule = Schedule()
    schedule.set_optimization_results(
        actions=result["actions"],
        state_of_energy=result["state_of_energy"],
        prices=prices,
        cycle_cost=0.1,
        hourly_consumption=[1.0] * len(prices),
        solar_charged=result["solar_charged"],
    )
    schedule.optimization_results["total_capacity"] = total_capacity
    schedule.optimization_results["reserved_capacity"] = reserved_capacity
    schedule.log_schedule()

    # Verify we have positive savings
    assert result["cost_savings"] > 0

    # Verify charge and discharge are balanced
    total_charge = sum(action for action in result["actions"] if action > 0)
    total_discharge = abs(sum(action for action in result["actions"] if action < 0))
    assert pytest.approx(total_charge, 0.1) == total_discharge

    # Verify battery stayed within capacity
    for soe in result["state_of_energy"]:
        assert 2.0 <= soe <= 10.0


def test_no_viable_trades():
    """Test behavior when there are no profitable trades."""
    prices = [1.0] * 24
    result = optimize_battery(
        prices=prices,
        total_capacity=10.0,
        reserved_capacity=2.0,
        cycle_cost=0.1,
        hourly_consumption=[1.0] * len(prices),
        max_charge_power_kw=3.0,
        min_profit_threshold=0.1,
    )

    # Should have no charge or discharge actions
    assert all(action == 0 for action in result["actions"])

    # Base cost should equal optimized cost (no savings)
    assert pytest.approx(result["base_cost"], 0.01) == result["optimized_cost"]


def test_respect_capacity_limits():
    """Test that optimization respects capacity limits."""
    prices = [0.1, 0.2, 0.8, 0.3, 0.1]
    result = optimize_battery(
        prices=prices,
        total_capacity=10.0,
        reserved_capacity=2.0,
        cycle_cost=0.1,
        hourly_consumption=[1.0] * len(prices),
        max_charge_power_kw=5.0,  # Allow high charging power
        min_profit_threshold=0.1,
        initial_soc=80.0,  # Start high - only 2.0 kWh to full
    )

    # Verify SOE stays within limits
    for soe in result["state_of_energy"]:
        assert 2.0 <= soe <= 10.0

    # Verify charging is limited by remaining capacity
    charging_actions = [a for a in result["actions"] if a > 0]
    if charging_actions:
        # No individual charge should exceed available capacity
        assert max(charging_actions) <= 2.0


def test_soe_consistency_basic():
    """Test that SOE calculations are consistent with actions."""
    prices = [0.1, 0.2, 0.8, 0.3, 0.1]
    initial_soc = 50.0  # 50% of capacity
    total_capacity = 10.0

    result = optimize_battery(
        prices=prices,
        total_capacity=total_capacity,
        reserved_capacity=2.0,
        cycle_cost=0.1,
        hourly_consumption=[1.0] * len(prices),
        max_charge_power_kw=3.0,
        min_profit_threshold=0.1,
        initial_soc=initial_soc,
    )

    # Manually track SOE based on actions
    expected_soe = [initial_soc / 100.0 * total_capacity]  # Initial SOE

    for hour in range(1, len(prices)):
        previous_soe = expected_soe[-1]
        action = result["actions"][hour - 1]

        next_soe = previous_soe
        if action > 0:  # Charging
            next_soe += action
        elif action < 0:  # Discharging
            next_soe += action  # action is negative

        # Enforce limits
        next_soe = min(next_soe, total_capacity)
        next_soe = max(next_soe, 2.0)  # reserved_capacity

        expected_soe.append(next_soe)

    # Compare expected SOE with actual SOE
    for hour in range(len(prices)):
        assert (
            pytest.approx(result["state_of_energy"][hour], 0.01) == expected_soe[hour]
        )
