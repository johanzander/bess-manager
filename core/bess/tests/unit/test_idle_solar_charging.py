"""
Tests for implicit solar charging during IDLE (load_first) periods.

The Growatt inverter in load_first mode charges the battery from excess solar
before exporting to grid. The DP algorithm must model this behavior so that
SOE increases, grid_exported decreases, and the optimizer can see the value
of free solar charging during IDLE periods.
"""

import pytest

from core.bess.dp_battery_algorithm import (
    _compute_idle_solar_charging,
    _create_idle_schedule,
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


class TestComputeIdleSolarCharging:
    """Unit tests for the _compute_idle_solar_charging helper."""

    def test_excess_solar_charges_battery(self, battery):
        """Excess solar should produce non-zero battery_charged."""
        charged, stored = _compute_idle_solar_charging(
            solar_production=3.0,
            home_consumption=1.0,
            soe=5.0,
            battery_settings=battery,
            dt=1.0,
        )
        assert charged == pytest.approx(2.0)
        assert stored == pytest.approx(2.0 * 0.95)

    def test_no_excess_solar_no_charging(self, battery):
        """When solar < consumption, no charging occurs."""
        charged, stored = _compute_idle_solar_charging(
            solar_production=1.0,
            home_consumption=3.0,
            soe=5.0,
            battery_settings=battery,
            dt=1.0,
        )
        assert charged == 0.0
        assert stored == 0.0

    def test_zero_solar_no_charging(self, battery):
        """When solar is zero, no charging occurs."""
        charged, stored = _compute_idle_solar_charging(
            solar_production=0.0,
            home_consumption=2.0,
            soe=5.0,
            battery_settings=battery,
            dt=1.0,
        )
        assert charged == 0.0
        assert stored == 0.0

    def test_respects_capacity_limit(self, battery):
        """Charging should be clamped when battery is nearly full."""
        # Battery at 9.5 kWh, max is 10.0 kWh → only 0.5 kWh capacity
        # Available capacity pre-efficiency = 0.5 / 0.95 ≈ 0.526
        charged, stored = _compute_idle_solar_charging(
            solar_production=5.0,
            home_consumption=0.0,
            soe=9.5,
            battery_settings=battery,
            dt=1.0,
        )
        available_capacity = (10.0 - 9.5) / 0.95
        assert charged == pytest.approx(available_capacity)
        assert stored == pytest.approx(available_capacity * 0.95)
        assert stored <= 10.0 - 9.5 + 1e-10  # Must not exceed available capacity

    def test_respects_charge_rate(self, battery):
        """Charging should be clamped by max charge power * dt."""
        # max_charge_power_kw=5.0, dt=0.25 → limit = 1.25 kWh
        charged, stored = _compute_idle_solar_charging(
            solar_production=10.0,
            home_consumption=0.0,
            soe=5.0,
            battery_settings=battery,
            dt=0.25,
        )
        assert charged == pytest.approx(1.25)
        assert stored == pytest.approx(1.25 * 0.95)

    def test_efficiency_applied(self, battery):
        """Energy stored should be less than energy charged due to efficiency."""
        charged, stored = _compute_idle_solar_charging(
            solar_production=4.0,
            home_consumption=2.0,
            soe=5.0,
            battery_settings=battery,
            dt=1.0,
        )
        assert charged == pytest.approx(2.0)
        assert stored == pytest.approx(2.0 * battery.efficiency_charge)
        assert stored < charged

    def test_full_battery_no_charging(self, battery):
        """When battery is full, no charging occurs."""
        charged, stored = _compute_idle_solar_charging(
            solar_production=5.0,
            home_consumption=1.0,
            soe=battery.max_soe_kwh,
            battery_settings=battery,
            dt=1.0,
        )
        assert charged == 0.0
        assert stored == 0.0


class TestIdleSolarChargingInOptimization:
    """Integration tests verifying the DP algorithm models IDLE solar charging."""

    def test_idle_charges_battery_from_excess_solar(self, battery):
        """IDLE periods with excess solar should show battery charging and reduced export."""
        # Single period scenario: high solar, low consumption
        # Flat prices so the optimizer has no reason to actively charge/discharge
        n = 4  # 4 quarter-hour periods = 1 hour
        buy_price = [0.5] * n
        sell_price = [0.3] * n
        home_consumption = [0.25] * n  # 1 kWh/h → 0.25 per quarter
        solar_production = [0.75] * n  # 3 kWh/h → 0.75 per quarter, excess = 0.5 per q

        results = optimize_battery_schedule(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=battery.min_soe_kwh,
            battery_settings=battery,
            period_duration_hours=0.25,
        )

        total_charged = sum(p.energy.battery_charged for p in results.period_data)
        total_exported = sum(p.energy.grid_exported for p in results.period_data)
        total_excess = sum(s - c for s, c in zip(solar_production, home_consumption))

        # Battery should have charged from excess solar
        assert total_charged > 0, "IDLE should charge battery from excess solar"
        # Grid export should be less than total excess solar
        assert total_exported < total_excess, (
            "Grid export should be reduced by solar charging"
        )

    def test_idle_no_solar_excess_no_charging(self, battery):
        """When solar < consumption during IDLE, no battery charging should occur."""
        n = 4
        buy_price = [0.5] * n
        sell_price = [0.3] * n
        home_consumption = [1.0] * n  # 4 kWh/h
        solar_production = [0.5] * n  # 2 kWh/h, all consumed by home

        results = optimize_battery_schedule(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=battery.min_soe_kwh,
            battery_settings=battery,
            period_duration_hours=0.25,
        )

        # With flat prices and no excess solar, battery should stay idle
        # Check that no phantom charging occurred
        for p in results.period_data:
            if p.energy.solar_production <= p.energy.home_consumption:
                assert p.energy.battery_charged == pytest.approx(0.0, abs=1e-10), (
                    "No charging should occur when solar <= consumption"
                )

    def test_idle_solar_charging_respects_capacity_limit(self, battery):
        """Battery nearly full — solar charging should be clamped to available capacity."""
        n = 4
        buy_price = [0.5] * n
        sell_price = [0.3] * n
        home_consumption = [0.25] * n
        solar_production = [2.0] * n  # Lots of excess solar

        # Start at 95% SOE
        initial_soe = battery.max_soe_kwh * 0.95

        results = optimize_battery_schedule(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=initial_soe,
            battery_settings=battery,
            period_duration_hours=0.25,
        )

        # SOE should not exceed max
        for p in results.period_data:
            assert p.energy.battery_soe_end <= battery.max_soe_kwh + 1e-10

    def test_idle_solar_charging_applies_efficiency(self, battery):
        """Energy stored should reflect charging efficiency losses."""
        charged, stored = _compute_idle_solar_charging(
            solar_production=3.0,
            home_consumption=1.0,
            soe=5.0,
            battery_settings=battery,
            dt=1.0,
        )
        assert stored == pytest.approx(charged * battery.efficiency_charge)
        assert stored < charged


class TestCreateIdleSchedule:
    """Tests for _create_idle_schedule with solar charging and SOE propagation."""

    def test_idle_schedule_propagates_soe(self, battery):
        """SOE should increase period-over-period when excess solar is available."""
        n = 8  # 2 hours of quarter-hour periods
        buy_price = [0.5] * n
        sell_price = [0.3] * n
        home_consumption = [0.25] * n  # 1 kWh/h
        solar_production = [0.75] * n  # 3 kWh/h, 2 kWh/h excess

        result = _create_idle_schedule(
            horizon=n,
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=battery.min_soe_kwh,
            battery_settings=battery,
        )

        # SOE should increase across periods
        soe_values = [p.energy.battery_soe_end for p in result.period_data]
        for i in range(1, len(soe_values)):
            assert soe_values[i] >= soe_values[i - 1], (
                f"SOE should not decrease: period {i-1}={soe_values[i-1]:.3f}, "
                f"period {i}={soe_values[i]:.3f}"
            )

        # SOE should actually increase (not stay flat) with excess solar
        assert soe_values[-1] > soe_values[0], (
            "SOE should increase over time with excess solar"
        )

        # Verify continuity: soe_end of period N == soe_start of period N+1
        for i in range(len(result.period_data) - 1):
            assert result.period_data[i].energy.battery_soe_end == pytest.approx(
                result.period_data[i + 1].energy.battery_soe_start
            ), f"SOE discontinuity between periods {i} and {i+1}"

    def test_idle_schedule_no_solar_soe_unchanged(self, battery):
        """Without solar, SOE should remain unchanged across all periods."""
        n = 4
        buy_price = [0.5] * n
        sell_price = [0.3] * n
        home_consumption = [0.5] * n
        solar_production = [0.0] * n

        result = _create_idle_schedule(
            horizon=n,
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=5.0,
            battery_settings=battery,
        )

        for p in result.period_data:
            assert p.energy.battery_soe_start == pytest.approx(5.0)
            assert p.energy.battery_soe_end == pytest.approx(5.0)
            assert p.energy.battery_charged == 0.0

    def test_idle_schedule_grid_export_reduced(self, battery):
        """Grid export should be reduced by the amount charged into battery."""
        n = 4
        buy_price = [0.5] * n
        sell_price = [0.3] * n
        home_consumption = [0.25] * n
        solar_production = [0.75] * n  # 0.5 excess per quarter

        result = _create_idle_schedule(
            horizon=n,
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=battery.min_soe_kwh,
            battery_settings=battery,
        )

        for p in result.period_data:
            excess = p.energy.solar_production - p.energy.home_consumption
            if excess > 0:
                # Export = excess - what went to battery
                assert p.energy.grid_exported == pytest.approx(
                    excess - p.energy.battery_charged
                )


class TestDischargeOverriddenBySolar:
    """When solar >= consumption, discharge actions are overridden by hardware."""

    def test_no_discharge_when_solar_exceeds_consumption(self, battery):
        """Optimizer should not show battery discharge during periods with excess solar."""
        # Scenario with excess solar in every period — discharge should never appear
        n = 8
        buy_price = [0.50] * n
        sell_price = [0.30] * n
        home_consumption = [0.25] * n  # 1 kWh/h
        solar_production = [0.75] * n  # 3 kWh/h → 2 kWh/h excess

        results = optimize_battery_schedule(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=5.0,
            battery_settings=battery,
            period_duration_hours=0.25,
        )

        for p in results.period_data:
            if p.energy.solar_production > p.energy.home_consumption:
                assert p.energy.battery_discharged == pytest.approx(0.0, abs=1e-10), (
                    f"Period {p.period}: battery should not discharge when solar "
                    f"({p.energy.solar_production}) > consumption ({p.energy.home_consumption})"
                )

    def test_excess_solar_charges_battery_not_exported(self, battery):
        """During periods with excess solar, export should be reduced by solar charging."""
        n = 4
        buy_price = [0.50] * n
        sell_price = [0.30] * n
        home_consumption = [0.25] * n
        solar_production = [0.75] * n  # 0.5 excess per quarter

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
            excess = p.energy.solar_production - p.energy.home_consumption
            if excess > 0:
                # Some or all excess should go to battery, not all to grid
                assert p.energy.grid_exported < excess + 1e-10, (
                    f"Period {p.period}: grid export ({p.energy.grid_exported:.3f}) "
                    f"should be less than excess solar ({excess:.3f})"
                )


class TestIdlePreferredOverGridCharging:
    """Test that the optimizer prefers free solar charging over paid grid charging."""

    def test_idle_preferred_over_explicit_charging_when_solar_sufficient(self, battery):
        """When solar excess covers charging need, optimizer should not pay for grid charging."""
        # Scenario: cheap morning prices, expensive evening, lots of midday solar
        # The optimizer should prefer IDLE solar charging over grid charging
        n = 24  # 6 hours at quarter-hour resolution
        # Morning: cheap. Midday: moderate. Evening: expensive.
        buy_price = (
            [0.10] * 8  # hours 0-1: cheap
            + [0.50] * 8  # hours 2-3: moderate with solar
            + [2.00] * 8  # hours 4-5: expensive (discharge opportunity)
        )
        sell_price = [p * 0.7 for p in buy_price]
        home_consumption = [0.25] * n  # 1 kWh/h steady
        solar_production = (
            [0.0] * 8  # no solar hours 0-1
            + [1.5] * 8  # excess solar hours 2-3 (1.25 excess per quarter after home)
            + [0.0] * 8  # no solar hours 4-5
        )

        results = optimize_battery_schedule(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=battery.min_soe_kwh,
            battery_settings=battery,
            period_duration_hours=0.25,
        )

        # Check that grid imports for charging are minimized during solar hours
        # During periods 8-15 (solar hours), if battery charges, it should prefer
        # solar over grid
        solar_period_grid_imports = sum(
            p.energy.grid_imported for p in results.period_data[8:16]
        )
        solar_period_consumption = sum(home_consumption[8:16])

        # Grid imports during solar hours should not significantly exceed consumption
        # (i.e., the optimizer shouldn't be importing from grid to charge when solar
        # excess is available for free)
        assert solar_period_grid_imports <= solar_period_consumption + 0.1, (
            f"Grid imports during solar hours ({solar_period_grid_imports:.2f}) "
            f"should not exceed consumption ({solar_period_consumption:.2f})"
        )
