"""
Tests for implicit solar charging during battery_first (charging) periods.

When the DP selects a positive charge action (power > 0), the Growatt inverter
enters battery_first mode. In this mode, the hardware charges from ALL excess
solar before using grid power. The DP algorithm must model this by ensuring
battery_charged = max(dp_power * dt, implicit_solar_charge).

Without this, the optimizer could plan a small grid charge (e.g., 0.4 kW) and
assume the rest of the solar gets exported — but the hardware would actually
absorb all excess solar, making the DP's energy balance incorrect.
"""

import pytest

from core.bess.dp_battery_algorithm import (
    _compute_idle_solar_charging,
    _state_transition,
    optimize_battery_schedule,
)
from core.bess.settings import BatterySettings


@pytest.fixture
def battery():
    """Small battery for focused testing."""
    return BatterySettings(
        total_capacity=10.0,
        min_soc=10,
        max_soc=100,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        efficiency_charge=0.95,
        efficiency_discharge=0.95,
        cycle_cost_per_kwh=0.40,
    )


class TestStateTransitionChargingAbsorbsSolar:
    """_state_transition must reflect that battery_first absorbs all excess solar."""

    def test_small_charge_absorbs_all_excess_solar(self, battery):
        """A small DP charge action should still absorb all excess solar in SOE."""
        # 3 kW solar, 1 kW home → 2 kW excess solar
        # DP requests 0.4 kW charge → dp_stored = 0.4 * 1.0 * 0.95 = 0.38
        # But solar_stored = 2.0 * 0.95 = 1.9, so charge_energy = max(0.38, 1.9) = 1.9
        next_soe = _state_transition(
            power=0.4,
            soe=5.0,
            solar_production=3.0,
            home_consumption=1.0,
            battery_settings=battery,
            dt=1.0,
        )
        _, solar_stored = _compute_idle_solar_charging(
            solar_production=3.0,
            home_consumption=1.0,
            soe=5.0,
            battery_settings=battery,
            dt=1.0,
        )
        expected_soe = 5.0 + solar_stored
        assert next_soe == pytest.approx(expected_soe)

    def test_large_charge_exceeds_solar(self, battery):
        """When DP charge exceeds solar, the DP power determines SOE change."""
        # 2 kW solar, 1 kW home → 1 kW excess solar
        # DP requests 3.0 kW charge → dp_stored = 3.0 * 1.0 * 0.95 = 2.85
        # solar_stored = 1.0 * 0.95 = 0.95, so charge_energy = max(2.85, 0.95) = 2.85
        next_soe = _state_transition(
            power=3.0,
            soe=5.0,
            solar_production=2.0,
            home_consumption=1.0,
            battery_settings=battery,
            dt=1.0,
        )
        expected_soe = 5.0 + 3.0 * 1.0 * battery.efficiency_charge
        assert next_soe == pytest.approx(expected_soe)

    def test_charge_with_no_solar_uses_dp_power(self, battery):
        """Without solar, charging follows DP power exactly."""
        next_soe = _state_transition(
            power=2.0,
            soe=5.0,
            solar_production=0.0,
            home_consumption=1.0,
            battery_settings=battery,
            dt=1.0,
        )
        expected_soe = 5.0 + 2.0 * 1.0 * battery.efficiency_charge
        assert next_soe == pytest.approx(expected_soe)


class TestChargingEnergyBalance:
    """Verify energy balance when charging absorbs all excess solar."""

    def test_small_charge_with_excess_solar_no_export(self, battery):
        """A small charge with excess solar should show zero export in period data."""
        # Single period: 3 kW solar, 1 kW home → 2 kW excess
        # Even a small charge action should absorb all excess solar
        n = 1
        results = optimize_battery_schedule(
            buy_price=[0.5],
            sell_price=[0.3],
            home_consumption=[1.0],
            solar_production=[3.0],
            initial_soe=5.0,
            battery_settings=battery,
            period_duration_hours=1.0,
        )

        p = results.period_data[0]
        if p.energy.battery_charged > 0:
            # When charging with excess solar, export should be zero or near-zero
            # because battery_first absorbs all excess solar
            excess = p.energy.solar_production - p.energy.home_consumption
            assert p.energy.battery_charged >= excess - 0.01, (
                f"Battery charged {p.energy.battery_charged:.3f} but excess solar "
                f"was {excess:.3f} — should absorb all of it"
            )

    def test_charge_with_no_excess_solar_uses_grid(self, battery):
        """When consumption exceeds solar, charging requires grid import."""
        n = 4
        # Force charging by making evening prices very expensive
        buy_price = [0.10] * 2 + [3.00] * 2
        sell_price = [0.05] * 2 + [1.50] * 2
        home_consumption = [0.75] * n  # 3 kWh/h, exceeds solar
        solar_production = [0.25] * n  # 1 kWh/h

        results = optimize_battery_schedule(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=battery.min_soe_kwh,
            battery_settings=battery,
            period_duration_hours=0.25,
        )

        # During cheap periods with charging, grid should be imported
        for p in results.period_data[:2]:
            if p.energy.battery_charged > 0.01:
                assert p.energy.grid_imported > 0, (
                    f"Period {p.period}: charging without excess solar should need grid"
                )


class TestOptimizationChargingAbsorbsSolar:
    """End-to-end optimization tests for battery_first solar absorption."""

    def test_optimizer_does_not_export_while_charging(self, battery):
        """When optimizer chooses to charge, it should not simultaneously export solar."""
        # Scenario: moderate solar with price spread encouraging charge→discharge
        n = 8
        buy_price = [0.20] * 4 + [1.50] * 4  # cheap morning, expensive evening
        sell_price = [0.10] * 4 + [0.80] * 4
        home_consumption = [0.25] * n  # 1 kWh/h
        solar_production = [0.75] * 4 + [0.0] * 4  # solar in morning only

        results = optimize_battery_schedule(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=battery.min_soe_kwh,
            battery_settings=battery,
            period_duration_hours=0.25,
        )

        for p in results.period_data:
            if p.energy.battery_charged > 0.01:
                excess = p.energy.solar_production - p.energy.home_consumption
                if excess > 0:
                    # Battery should absorb at least the excess solar.
                    # Export should only be whatever exceeds battery capacity/rate limits.
                    assert p.energy.battery_charged >= excess - 0.01, (
                        f"Period {p.period}: battery charged {p.energy.battery_charged:.3f} "
                        f"but excess solar was {excess:.3f} — should absorb all of it"
                    )

    def test_cross_temporal_arbitrage_prevented(self, battery):
        """Optimizer should not export solar at low price to buy grid at same/higher price."""
        # This was the original bug: optimizer exported solar at sell_price and
        # bought grid at buy_price, even when buy_price > sell_price
        n = 12
        buy_price = [0.50] * n
        sell_price = [0.12] * n  # sell price much lower than buy
        home_consumption = [0.25] * n
        solar_production = [0.75] * 6 + [0.0] * 6  # solar first half

        results = optimize_battery_schedule(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=battery.min_soe_kwh,
            battery_settings=battery,
            period_duration_hours=0.25,
        )

        # During solar periods, any charging action should absorb all excess solar
        # rather than exporting it at 0.12 and importing from grid at 0.50
        for p in results.period_data[:6]:
            excess = p.energy.solar_production - p.energy.home_consumption
            if excess > 0 and p.energy.battery_charged > 0.01:
                # Battery should absorb at least as much as the excess solar
                assert p.energy.battery_charged >= excess - 0.01, (
                    f"Period {p.period}: battery charged {p.energy.battery_charged:.3f} "
                    f"but excess solar was {excess:.3f} — should absorb all of it"
                )

    def test_solar_charging_improves_savings(self, battery):
        """Battery_first solar absorption should yield better savings than exporting."""
        # With expensive evening prices and free solar, storing solar should beat exporting
        n = 16
        buy_price = [0.30] * 8 + [2.00] * 8
        sell_price = [0.10] * 8 + [1.00] * 8
        home_consumption = [0.25] * n
        solar_production = [1.0] * 8 + [0.0] * 8  # 3 kWh excess per quarter in morning

        results = optimize_battery_schedule(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=battery.min_soe_kwh,
            battery_settings=battery,
            period_duration_hours=0.25,
        )

        # Battery should have charged from solar and discharged in expensive periods
        total_charged = sum(p.energy.battery_charged for p in results.period_data)
        total_discharged = sum(p.energy.battery_discharged for p in results.period_data)
        assert total_charged > 0, "Battery should charge from solar"
        assert total_discharged > 0, "Battery should discharge during expensive periods"

        # Total cost with battery should be less than without
        assert results.economic_summary.battery_solar_cost < results.economic_summary.grid_only_cost, (
            f"Battery should reduce cost: {results.economic_summary.battery_solar_cost:.2f} "
            f">= {results.economic_summary.grid_only_cost:.2f}"
        )
