"""
Test module for minimum action profit threshold functionality.

Tests that fixed profit threshold correctly prevents low-profit actions
while preserving high-profit opportunities.
"""

import pytest  # type: ignore

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings


class TestActionThreshold:
    """Test minimum action profit threshold feature."""

    @pytest.fixture
    def base_battery_settings(self):
        """Create base battery settings for testing."""
        return BatterySettings(
            total_capacity=30.0,
            min_soc=10,
            max_soc=100,
            max_charge_power_kw=15.0,
            max_discharge_power_kw=15.0,
            cycle_cost_per_kwh=0.40,
            min_action_profit_threshold=0.0,  # Start with no threshold
            efficiency_charge=0.97,
            efficiency_discharge=0.95,
        )

    @pytest.fixture
    def marginal_profit_scenario(self):
        """Scenario with ~1.0 SEK hourly profits (should be blocked by 1.5 SEK threshold)."""
        return {
            "buy_prices": [0.50, 0.51, 0.50, 0.52, 0.50, 0.51, 0.50, 0.52] * 3,
            "sell_prices": [0.48, 0.49, 0.48, 0.50, 0.48, 0.49, 0.48, 0.50] * 3,
            "consumption": [2.0] * 24,
            "solar": [0.0] * 24,
            "initial_soe": 3.0,
        }

    @pytest.fixture
    def profitable_scenario(self):
        """Scenario with ~5.0 SEK hourly profits (should pass 1.5 SEK threshold)."""
        return {
            "buy_prices": [0.30] * 8 + [2.80] * 8 + [0.30] * 8,
            "sell_prices": [0.28] * 8 + [2.75] * 8 + [0.28] * 8,
            "consumption": [2.0] * 24,
            "solar": [0.0] * 24,
            "initial_soe": 3.0,
        }

    def test_no_threshold_baseline(
        self, marginal_profit_scenario, base_battery_settings
    ):
        """Test that profitability gate blocks money-losing operations even with threshold=0."""
        base_battery_settings.min_action_profit_threshold = 0.0

        result = optimize_battery_schedule(
            buy_price=marginal_profit_scenario["buy_prices"],
            sell_price=marginal_profit_scenario["sell_prices"],
            home_consumption=marginal_profit_scenario["consumption"],
            solar_production=marginal_profit_scenario["solar"],
            initial_soe=marginal_profit_scenario["initial_soe"],
            battery_settings=base_battery_settings,
            period_duration_hours=1.0,  # Hourly resolution for 24-hour test
        )

        # With threshold=0, profitability gate should still reject money-losing operations
        # The marginal_profit_scenario results in -0.18 SEK savings (loses money)
        # So profitability gate should reject it and use all-IDLE schedule
        assert result.economic_summary is not None, "Economic summary should not be None"
        total_savings = result.economic_summary.grid_to_battery_solar_savings

        # Verify profitability gate worked: should have 0 or positive savings (IDLE fallback)
        assert (
            total_savings >= 0
        ), f"Profitability gate should prevent losses, got {total_savings:.2f} SEK"

        # Should have no battery actions (all-IDLE schedule)
        significant_actions = sum(
            1
            for hour in result.period_data
            if hour.decision.battery_action is not None
            and abs(hour.decision.battery_action) > 0.1
        )

        assert (
            significant_actions == 0
        ), "Money-losing operations should be rejected even with threshold=0"

    def test_profitability_gate_blocks_below_threshold(
        self, marginal_profit_scenario, base_battery_settings
    ):
        """Test that profitability gate blocks optimization when savings < threshold."""
        base_battery_settings.min_action_profit_threshold = 1.5

        result = optimize_battery_schedule(
            buy_price=marginal_profit_scenario["buy_prices"],
            sell_price=marginal_profit_scenario["sell_prices"],
            home_consumption=marginal_profit_scenario["consumption"],
            solar_production=marginal_profit_scenario["solar"],
            initial_soe=marginal_profit_scenario["initial_soe"],
            battery_settings=base_battery_settings,
            period_duration_hours=1.0,  # Hourly resolution for 24-hour test
        )

        # Profitability gate should reject optimization with savings below threshold
        # marginal_profit_scenario produces negative or very low savings
        # With threshold=1.5, it should be rejected and IDLE schedule used
        assert result.economic_summary is not None, "Economic summary should not be None"
        savings = result.economic_summary.grid_to_battery_solar_savings

        # Verify profitability gate blocked the optimization
        assert (
            savings < 1.5
        ), f"Optimization should have been blocked (savings={savings:.2f} < threshold=1.5)"

        # Should result in all-IDLE schedule (no battery actions)
        significant_actions = sum(
            1
            for hour in result.period_data
            if hour.decision.battery_action is not None
            and abs(hour.decision.battery_action) > 0.1
        )

        assert (
            significant_actions == 0
        ), f"Below-threshold optimization should result in IDLE schedule, got {significant_actions} actions"

    def test_threshold_preserves_profitable_actions(
        self, profitable_scenario, base_battery_settings
    ):
        """Test that threshold doesn't block clearly profitable actions."""
        base_battery_settings.min_action_profit_threshold = 1.5

        result = optimize_battery_schedule(
            buy_price=profitable_scenario["buy_prices"],
            sell_price=profitable_scenario["sell_prices"],
            home_consumption=profitable_scenario["consumption"],
            solar_production=profitable_scenario["solar"],
            initial_soe=profitable_scenario["initial_soe"],
            battery_settings=base_battery_settings,
            period_duration_hours=1.0,  # Hourly resolution for 24-hour test
        )

        # Should still have significant savings despite threshold
        assert result.economic_summary is not None, "Economic summary should not be None"
        savings = result.economic_summary.grid_to_battery_solar_savings
        assert (
            savings > 15.0
        ), f"High-profit scenario should still be profitable, got {savings:.2f} SEK"

        # Should still have significant battery actions
        total_cycling = sum(
            abs(hour.decision.battery_action)
            for hour in result.period_data
            if hour.decision.battery_action is not None
        )
        assert (
            total_cycling > 15.0
        ), f"High-profit scenario should still use battery, got {total_cycling:.1f}kW"

    def test_threshold_only_affects_charging(self, base_battery_settings):
        """Test that threshold penalty only applies to charging, never to discharging."""
        base_battery_settings.min_action_profit_threshold = 1.5

        # Scenario: prices that create small charging profit but still allow discharging
        # Small spread between buy/sell makes charging marginally profitable but below threshold
        discharge_scenario = {
            "buy_prices": [1.00] * 24,  # Fixed buy price
            "sell_prices": [0.95] * 24,  # Slightly lower export prices (typical)
            "consumption": [2.0] * 24,
            "solar": [0.0] * 24,
            "initial_soe": 25.0,  # Start with high SOE to enable discharging
        }

        result = optimize_battery_schedule(
            buy_price=discharge_scenario["buy_prices"],
            sell_price=discharge_scenario["sell_prices"],
            home_consumption=discharge_scenario["consumption"],
            solar_production=discharge_scenario["solar"],
            initial_soe=discharge_scenario["initial_soe"],
            battery_settings=base_battery_settings,
            period_duration_hours=1.0,  # Hourly resolution for 24-hour test
        )

        # Count charging vs discharging actions
        charging_actions = sum(
            1
            for hour in result.period_data
            if hour.decision.battery_action is not None
            and hour.decision.battery_action > 0.1
        )
        discharging_actions = sum(
            1
            for hour in result.period_data
            if hour.decision.battery_action is not None
            and hour.decision.battery_action < -0.1
        )

        # With threshold, charging should be blocked (low profit scenario)
        # Discharging should be allowed (stored energy always usable)

        # In this scenario: buying at 1.00, selling at 0.95 means discharging saves money
        # (avoid buying expensive grid power) but charging loses money (efficiency losses + spread)
        assert (
            charging_actions <= 2
        ), f"Threshold should block unprofitable charging, got {charging_actions} charging actions"
        assert (
            discharging_actions > 0
        ), f"Should discharge to save on expensive grid purchases, got {discharging_actions} discharging actions"
