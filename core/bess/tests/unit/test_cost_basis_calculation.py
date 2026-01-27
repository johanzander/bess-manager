"""Tests for cost basis calculation in BatterySystemManager.

These tests verify that _calculate_initial_cost_basis() correctly tracks
the marginal cost of energy in the battery, including pre-existing energy
at the start of the day.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core.bess.models import DecisionData, EconomicData, EnergyData, PeriodData

TIMEZONE = ZoneInfo("Europe/Stockholm")


def make_period_data(
    period: int,
    battery_soe_start: float,
    battery_soe_end: float,
    battery_charged: float = 0.0,
    battery_discharged: float = 0.0,
    solar_production: float = 0.0,
    buy_price: float = 1.0,
) -> PeriodData:
    """Create PeriodData for testing."""
    return PeriodData(
        period=period,
        energy=EnergyData(
            solar_production=solar_production,
            home_consumption=0.5,
            battery_charged=battery_charged,
            battery_discharged=battery_discharged,
            grid_imported=battery_charged if battery_charged > 0 else 0.0,
            grid_exported=0.0,
            battery_soe_start=battery_soe_start,
            battery_soe_end=battery_soe_end,
        ),
        economic=EconomicData(buy_price=buy_price, sell_price=buy_price * 0.4),
        timestamp=datetime.now(tz=TIMEZONE),
        data_source="actual",
        decision=DecisionData(),
    )


class TestCostBasisCalculation:
    """Tests for _calculate_initial_cost_basis method."""

    def test_preexisting_energy_included_in_cost_basis(self, base_system):
        """Pre-existing battery energy should be included in cost basis calculation.

        This is the bug that caused negative savings on 2026-01-27:
        - Battery started with 4.2 kWh at midnight
        - At 02:15, 0.6 kWh was charged at ~3.0 SEK/kWh effective cost
        - Bug: cost_basis = 3.0 / 0.6 = 3.0 SEK/kWh (ignoring 4.2 kWh)
        - Fix: cost_basis = (4.2*0.5 + 0.6*3.0) / 4.8 = 0.81 SEK/kWh
        """
        cycle_cost = base_system.battery_settings.cycle_cost_per_kwh

        # Period 0: Battery starts with 4.2 kWh (pre-existing from overnight)
        # No charging or discharging in this period
        base_system.historical_store.record_period(
            0,
            make_period_data(
                period=0,
                battery_soe_start=4.2,
                battery_soe_end=4.2,
            ),
        )

        # Period 8 (02:00-02:15): Charge 0.6 kWh from grid at 2.5 SEK/kWh
        grid_price = 2.5
        base_system.historical_store.record_period(
            8,
            make_period_data(
                period=8,
                battery_soe_start=4.2,
                battery_soe_end=4.8,
                battery_charged=0.6,
                buy_price=grid_price,
            ),
        )

        # Calculate cost basis at period 9
        cost_basis = base_system._calculate_initial_cost_basis(current_period=9)

        # Expected calculation:
        # Pre-existing: 4.2 kWh at cycle_cost (0.5 SEK/kWh) = 2.1 SEK
        # New charge: 0.6 kWh at (2.5 + 0.5) SEK/kWh = 1.8 SEK
        # Total: 3.9 SEK / 4.8 kWh = 0.8125 SEK/kWh
        expected_cost = (4.2 * cycle_cost + 0.6 * (grid_price + cycle_cost)) / 4.8

        assert cost_basis == pytest.approx(expected_cost, rel=0.01)
        # Must be much less than 3.0 (the bug value)
        assert cost_basis < 1.0

    def test_cost_basis_without_charging_equals_cycle_cost(self, base_system):
        """When no charging occurs, cost basis should be cycle cost."""
        cycle_cost = base_system.battery_settings.cycle_cost_per_kwh

        # Period 0: Battery has 5 kWh, no charging
        base_system.historical_store.record_period(
            0,
            make_period_data(
                period=0,
                battery_soe_start=5.0,
                battery_soe_end=5.0,
            ),
        )

        cost_basis = base_system._calculate_initial_cost_basis(current_period=1)

        # Only pre-existing energy at cycle cost
        assert cost_basis == pytest.approx(cycle_cost, rel=0.01)

    def test_cost_basis_after_discharge_maintains_average(self, base_system):
        """Discharging should reduce energy but maintain weighted average cost."""
        cycle_cost = base_system.battery_settings.cycle_cost_per_kwh

        # Period 0: Start with 10 kWh
        base_system.historical_store.record_period(
            0,
            make_period_data(
                period=0,
                battery_soe_start=10.0,
                battery_soe_end=10.0,
            ),
        )

        # Period 4: Charge 2 kWh at expensive price (3.0 SEK/kWh)
        base_system.historical_store.record_period(
            4,
            make_period_data(
                period=4,
                battery_soe_start=10.0,
                battery_soe_end=12.0,
                battery_charged=2.0,
                buy_price=3.0,
            ),
        )

        # Period 8: Discharge 4 kWh
        base_system.historical_store.record_period(
            8,
            make_period_data(
                period=8,
                battery_soe_start=12.0,
                battery_soe_end=8.0,
                battery_discharged=4.0,
            ),
        )

        cost_basis = base_system._calculate_initial_cost_basis(current_period=12)

        # Initial: 10 kWh at 0.5 = 5.0 SEK
        # Charge: 2 kWh at 3.5 = 7.0 SEK
        # Total before discharge: 12 SEK / 12 kWh = 1.0 SEK/kWh
        # After discharge: 8 SEK / 8 kWh = 1.0 SEK/kWh (average preserved)
        # But with weighted average removal: (5.0 + 7.0) / 12 = 1.0, then 4*1.0 removed
        # Remaining: 8 kWh, 8 SEK, cost_basis = 1.0 SEK/kWh
        expected = (10 * cycle_cost + 2 * (3.0 + cycle_cost)) / 12

        assert cost_basis == pytest.approx(expected, rel=0.01)

    def test_cost_basis_with_solar_charging(self, base_system):
        """Solar charging should only add cycle cost, not buy price."""
        cycle_cost = base_system.battery_settings.cycle_cost_per_kwh

        # Period 0: Start with 5 kWh
        base_system.historical_store.record_period(
            0,
            make_period_data(
                period=0,
                battery_soe_start=5.0,
                battery_soe_end=5.0,
            ),
        )

        # Period 20: Charge 3 kWh from solar (solar_production >= battery_charged)
        base_system.historical_store.record_period(
            20,
            make_period_data(
                period=20,
                battery_soe_start=5.0,
                battery_soe_end=8.0,
                battery_charged=3.0,
                solar_production=5.0,  # Plenty of solar
                buy_price=2.0,  # Should not be used
            ),
        )

        cost_basis = base_system._calculate_initial_cost_basis(current_period=24)

        # Initial: 5 kWh at 0.5 = 2.5 SEK
        # Solar charge: 3 kWh at 0.5 (cycle cost only) = 1.5 SEK
        # Total: 4.0 SEK / 8 kWh = 0.5 SEK/kWh
        expected = (5 * cycle_cost + 3 * cycle_cost) / 8

        assert cost_basis == pytest.approx(expected, rel=0.01)
        assert cost_basis == pytest.approx(cycle_cost, rel=0.01)

    def test_empty_history_returns_cycle_cost(self, base_system):
        """With no historical data, should return cycle_cost_per_kwh."""
        cycle_cost = base_system.battery_settings.cycle_cost_per_kwh

        cost_basis = base_system._calculate_initial_cost_basis(current_period=10)

        assert cost_basis == cycle_cost

    def test_cost_basis_resets_when_battery_fully_discharged(self, base_system):
        """When battery drains to near-zero, cost basis should reset to cycle cost."""
        cycle_cost = base_system.battery_settings.cycle_cost_per_kwh

        # Period 0: Start with 5 kWh
        base_system.historical_store.record_period(
            0,
            make_period_data(
                period=0,
                battery_soe_start=5.0,
                battery_soe_end=5.0,
            ),
        )

        # Period 4: Charge 2 kWh at expensive price
        base_system.historical_store.record_period(
            4,
            make_period_data(
                period=4,
                battery_soe_start=5.0,
                battery_soe_end=7.0,
                battery_charged=2.0,
                buy_price=3.0,
            ),
        )

        # Period 8: Discharge almost everything (6.95 kWh, leaving 0.05 kWh)
        base_system.historical_store.record_period(
            8,
            make_period_data(
                period=8,
                battery_soe_start=7.0,
                battery_soe_end=0.05,
                battery_discharged=6.95,
            ),
        )

        cost_basis = base_system._calculate_initial_cost_basis(current_period=12)

        # When running_energy <= 0.1, it resets to 0, so cycle_cost is returned
        assert cost_basis == cycle_cost
