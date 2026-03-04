"""Tests for terminal value parameter in DP optimization."""

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings


@pytest.fixture
def battery_settings():
    """Standard battery settings for terminal value tests."""
    return BatterySettings(
        total_capacity=10.0,
        min_soc=10,
        max_soc=100,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        cycle_cost_per_kwh=0.30,
    )


@pytest.fixture
def low_evening_prices():
    """Price scenario: moderate day, low evening - optimizer would dump energy without terminal value.

    16 periods (4 hours) at quarterly resolution.
    """
    return {
        "buy": [1.0] * 8 + [0.3] * 8,
        "sell": [0.7] * 8 + [0.2] * 8,
        "consumption": [0.25] * 16,
        "solar": [0.0] * 16,
    }


class TestTerminalValueZero:
    """Terminal value of 0.0 should produce identical results to current behavior."""

    def test_zero_terminal_value_matches_default(
        self, battery_settings, low_evening_prices
    ):
        """With terminal_value=0.0, results should be identical to no terminal value."""
        result_default = optimize_battery_schedule(
            buy_price=low_evening_prices["buy"],
            sell_price=low_evening_prices["sell"],
            home_consumption=low_evening_prices["consumption"],
            battery_settings=battery_settings,
            solar_production=low_evening_prices["solar"],
            initial_soe=5.0,
        )

        result_zero = optimize_battery_schedule(
            buy_price=low_evening_prices["buy"],
            sell_price=low_evening_prices["sell"],
            home_consumption=low_evening_prices["consumption"],
            battery_settings=battery_settings,
            solar_production=low_evening_prices["solar"],
            initial_soe=5.0,
            terminal_value_per_kwh=0.0,
        )

        # Actions should be identical
        for i in range(len(result_default.period_data)):
            assert (
                result_default.period_data[i].decision.battery_action
                == result_zero.period_data[i].decision.battery_action
            ), f"Period {i}: actions differ with terminal_value=0.0"


class TestTerminalValueHoldsEnergy:
    """Positive terminal value should cause optimizer to hold energy when sell prices are low."""

    def test_positive_terminal_value_retains_energy(
        self, battery_settings, low_evening_prices
    ):
        """With high terminal value, optimizer should prefer holding energy over selling at low price."""
        # Without terminal value - optimizer may dump energy at end
        result_no_tv = optimize_battery_schedule(
            buy_price=low_evening_prices["buy"],
            sell_price=low_evening_prices["sell"],
            home_consumption=low_evening_prices["consumption"],
            battery_settings=battery_settings,
            solar_production=low_evening_prices["solar"],
            initial_soe=5.0,
            terminal_value_per_kwh=0.0,
        )

        # With terminal value higher than sell price (0.2) - should hold energy
        result_with_tv = optimize_battery_schedule(
            buy_price=low_evening_prices["buy"],
            sell_price=low_evening_prices["sell"],
            home_consumption=low_evening_prices["consumption"],
            battery_settings=battery_settings,
            solar_production=low_evening_prices["solar"],
            initial_soe=5.0,
            terminal_value_per_kwh=0.8,
        )

        # Calculate total discharge in second half (low price periods)
        def total_discharge_second_half(result):
            total = 0.0
            for pd in result.period_data[8:]:
                if pd.decision.battery_action < 0:
                    total += abs(pd.decision.battery_action)
            return total

        discharge_no_tv = total_discharge_second_half(result_no_tv)
        discharge_with_tv = total_discharge_second_half(result_with_tv)

        # Terminal value should reduce discharge during low-price periods
        assert discharge_with_tv <= discharge_no_tv, (
            f"Terminal value should reduce low-price discharge: "
            f"without={discharge_no_tv:.2f}, with={discharge_with_tv:.2f}"
        )


class TestTerminalValueDoesNotOverride:
    """Terminal value should not prevent profitable exports."""

    def test_high_sell_price_still_exports(self, battery_settings):
        """When sell price exceeds terminal value, optimizer should still export."""
        # Sell prices much higher than terminal value
        high_sell = [2.0] * 16
        buy = [2.5] * 16
        consumption = [0.25] * 16
        solar = [0.0] * 16

        result = optimize_battery_schedule(
            buy_price=buy,
            sell_price=high_sell,
            home_consumption=consumption,
            battery_settings=battery_settings,
            solar_production=solar,
            initial_soe=5.0,
            terminal_value_per_kwh=0.5,  # Much lower than sell price of 2.0
        )

        # Should still discharge when profitable (sell=2.0 > terminal=0.5 + cycle_cost=0.30)
        total_discharge = 0.0
        for pd in result.period_data:
            action = pd.decision.battery_action
            if action is not None and action < 0:
                total_discharge += abs(action)

        assert (
            total_discharge > 0
        ), "Optimizer should still export when sell price exceeds terminal value + cycle cost"
