"""Tests for terminal value parameter in DP optimization."""

import statistics

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings

pytestmark = pytest.mark.slow


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


class TestTerminalValueCapRegression:
    """Scenario-level regression tests for the arbitrage-consistency cap (#246).

    Both scenarios apply the same terminal-value formula the production code
    uses in `BatterySystemManager._calculate_terminal_value`:
    ``min(buy-median-based, sell-max-based)``. Reusing real numbers from
    #126/#244 (Belgian) and the ordinary/Nordic-shaped counter-scenario
    bess-analyst used to reject #245's straight sell-swap fix.
    """

    def test_belgian_shaped_market_exports_at_evening_peak(self):
        """Wide buy/sell spread: an uncapped buy-median terminal value exceeds
        the real evening export price and makes the DP hold charge instead of
        exporting (#126/#244's actual bug). The cap must collapse the
        terminal value below that real peak so the DP exports."""
        settings = BatterySettings(
            total_capacity=15.0,
            min_soc=10,
            max_soc=100,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            cycle_cost_per_kwh=0.04,
        )

        # Mirrors #244's evidence: horizon=38 (14:30 to midnight), buy prices
        # ~0.21-0.38 (median ~0.30), real achievable export peak ~0.13-0.16
        # around 20:00-22:00, otherwise low sell prices.
        buy = [0.21] * 10 + [0.30] * 18 + [0.38] * 10
        sell = [0.10] * 22 + [0.16] * 8 + [0.12] * 8
        consumption = [0.3] * 38
        solar = [0.0] * 38

        buy_based = max(
            0.0,
            statistics.median(buy) * settings.efficiency_discharge
            - settings.cycle_cost_per_kwh,
        )
        sell_cap = max(
            0.0,
            max(sell) * settings.efficiency_discharge - settings.cycle_cost_per_kwh,
        )
        assert sell_cap < buy_based, "scenario must exercise the binding cap"
        capped_terminal_value = min(buy_based, sell_cap)

        result_uncapped = optimize_battery_schedule(
            buy_price=buy,
            sell_price=sell,
            home_consumption=consumption,
            battery_settings=settings,
            solar_production=solar,
            initial_soe=14.0,
            terminal_value_per_kwh=buy_based,  # old, buggy (#244) behavior
        )
        result_capped = optimize_battery_schedule(
            buy_price=buy,
            sell_price=sell,
            home_consumption=consumption,
            battery_settings=settings,
            solar_production=solar,
            initial_soe=14.0,
            terminal_value_per_kwh=capped_terminal_value,  # fixed (#246) behavior
        )

        peak_price = max(sell)
        peak_period_indices = {i for i, p in enumerate(sell) if p == peak_price}

        def total_export(result):
            return sum(
                abs(pd.decision.battery_action)
                for i, pd in enumerate(result.period_data)
                if i in peak_period_indices
                and pd.decision.battery_action is not None
                and pd.decision.battery_action < -consumption[i]
            )

        export_uncapped = total_export(result_uncapped)
        export_capped = total_export(result_capped)

        assert export_capped > 0.0, (
            "capped terminal value should let the DP export during the real "
            "evening peak instead of holding for a fictitious bonus"
        )
        assert export_capped > export_uncapped, (
            "sanity check: capping the terminal value should still export "
            "strictly more at the peak than the uncapped (buggy) value -- "
            "at fine DP discretization (docs/superpowers/specs/2026-07-12-"
            "dp-continuous-path-reconstruction-fix-design.md, Option B) the "
            "uncapped case no longer holds through the peak with exactly zero "
            "export (a side effect of the same fix reducing Step 2's general "
            "reconstruction error), but the cap must still measurably help"
        )

    def test_fixed_export_tariff_stores_surplus_solar(self):
        """Fixed export tariff with a large midday solar surplus (#359).

        Mirrors a real UK Octopus day: import varies 0.19-0.40, export is a
        flat 0.12. The cap then sits below the round-trip breakeven
        (sell / efficiency_charge), so storing surplus solar loses to
        exporting it for *any* future price and the battery coasts to its
        floor overnight. Skipping the cap on a flat sell curve must let the
        DP bank the free surplus instead.
        """
        settings = BatterySettings(
            total_capacity=10.0,
            min_soc=10,
            max_soc=100,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            cycle_cost_per_kwh=0.02,
        )

        # 63 periods (07:15 to midnight): flat daytime import, evening peak,
        # a solar bell curve well above load, and load-only after dark.
        buy = [0.21] * 36 + [0.35] * 8 + [0.26] * 19
        sell = [0.12] * 63
        solar = [0.3] * 4 + [0.9] * 12 + [1.25] * 16 + [0.6] * 8 + [0.0] * 23
        consumption = [0.25] * 63

        buy_based = max(
            0.0,
            statistics.median(buy) * settings.efficiency_discharge
            - settings.cycle_cost_per_kwh,
        )
        sell_cap = max(
            0.0,
            max(sell) * settings.efficiency_discharge - settings.cycle_cost_per_kwh,
        )
        assert (
            sell_cap < max(sell) / settings.efficiency_charge
        ), "test fixture must exercise the degenerate flat-export case"

        def peak_soe(terminal_value):
            result = optimize_battery_schedule(
                buy_price=buy,
                sell_price=sell,
                home_consumption=consumption,
                battery_settings=settings,
                solar_production=solar,
                initial_soe=4.2,
                terminal_value_per_kwh=terminal_value,
            )
            return max(pd.energy.battery_soe_end for pd in result.period_data)

        soe_capped = peak_soe(min(buy_based, sell_cap))  # pre-#359 behavior
        soe_fixed = peak_soe(buy_based)  # cap skipped on flat sell curve

        assert soe_fixed > soe_capped, (
            "skipping the degenerate cap must let the DP store surplus solar "
            "rather than exporting all of it at the flat tariff"
        )
        assert soe_fixed > settings.max_soe_kwh * 0.9, (
            "with free surplus solar and an evening/overnight import price "
            "well above the export price, the battery should fill"
        )

    def test_nordic_shaped_market_retains_reserve(self):
        """Ordinary/Nordic-shaped market with a genuine narrow evening peak:
        the best in-horizon sell price is already above the buy-median
        estimate, so the cap must not bind and the battery should still
        retain a substantial reserve at horizon end (the exact regression
        #245's straight sell-swap fix introduced, left untested there)."""
        settings = BatterySettings(
            total_capacity=15.0,
            min_soc=10,
            max_soc=100,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            cycle_cost_per_kwh=0.04,
        )

        # 0.6 baseline, narrow 1-hour peak at 1.4, sell = 0.85x buy throughout.
        # No home consumption: isolates the pure hold-vs-export arbitrage
        # decision the terminal value governs, since discharging to serve
        # real consumption is rational whenever its value beats the buy
        # price regardless of terminal value, which would confound the
        # reserve check below.
        buy = [0.6] * 30 + [1.4] * 4 + [0.6] * 6
        sell = [round(p * 0.85, 4) for p in buy]
        consumption = [0.0] * 40
        solar = [0.0] * 40

        buy_based = max(
            0.0,
            statistics.median(buy) * settings.efficiency_discharge
            - settings.cycle_cost_per_kwh,
        )
        sell_cap = max(
            0.0,
            max(sell) * settings.efficiency_discharge - settings.cycle_cost_per_kwh,
        )
        assert buy_based < sell_cap, "scenario must exercise the non-binding cap"
        capped_terminal_value = min(buy_based, sell_cap)
        assert capped_terminal_value == pytest.approx(buy_based), (
            "cap should not alter the terminal value on an ordinary/Nordic-"
            "shaped market"
        )

        result = optimize_battery_schedule(
            buy_price=buy,
            sell_price=sell,
            home_consumption=consumption,
            battery_settings=settings,
            solar_production=solar,
            initial_soe=14.9,
            terminal_value_per_kwh=capped_terminal_value,
        )

        final_soe = result.period_data[-1].energy.battery_soe_end
        usable_capacity = settings.total_capacity - settings.min_soe_kwh
        final_reserve_fraction = (final_soe - settings.min_soe_kwh) / usable_capacity

        assert final_reserve_fraction > 0.5, (
            f"DP should retain a substantial reserve at horizon end on an "
            f"ordinary market, got {final_reserve_fraction:.1%} of usable capacity"
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
