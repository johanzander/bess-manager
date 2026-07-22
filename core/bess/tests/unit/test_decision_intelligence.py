"""Tests for issue #353: future_value always 0.0 for every period."""

from core.bess.dp_battery_algorithm import _build_period_data
from core.bess.tests.helpers import make_battery_settings


class TestBuildPeriodDataFutureValue:
    """_build_period_data must report the real DP continuation value as
    future_value, not always 0.0."""

    def test_future_value_reflects_continuation_value(self):
        bs = make_battery_settings(
            total_capacity=10.0,
            min_soc=20.0,
            max_soc=100.0,
            cycle_cost_per_kwh=0.40,
        )
        period_data = _build_period_data(
            power=-1.0,
            soe=5.0,
            next_soe=4.0,
            period=0,
            home_consumption=0.2,
            battery_settings=bs,
            dt=0.25,
            buy_price=[2.0],
            sell_price=[1.5],
            solar_production=0.0,
            new_cost_basis=0.5,
            currency="SEK",
            continuation_value=3.7,
        )
        assert period_data.decision.future_value == 3.7

    def test_future_value_defaults_to_zero(self):
        """Omitting continuation_value must not change existing behavior for
        any caller that doesn't yet pass it."""
        bs = make_battery_settings(
            total_capacity=10.0,
            min_soc=20.0,
            max_soc=100.0,
            cycle_cost_per_kwh=0.40,
        )
        period_data = _build_period_data(
            power=-1.0,
            soe=5.0,
            next_soe=4.0,
            period=0,
            home_consumption=0.2,
            battery_settings=bs,
            dt=0.25,
            buy_price=[2.0],
            sell_price=[1.5],
            solar_production=0.0,
            new_cost_basis=0.5,
            currency="SEK",
        )
        assert period_data.decision.future_value == 0.0
