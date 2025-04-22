"""Integration tests for battery optimization with various price patterns."""

from datetime import date
import logging

import pytest

# Create a clean system from scratch to avoid contamination
from bess import BatterySystemManager
from bess.price_manager import MockSource

logger = logging.getLogger(__name__)


class TestBatteryOptimization:
    """Tests for battery optimization with various price patterns."""

    @pytest.mark.parametrize(
        ("case_name", "test_case_fixture", "price_data_fixture", "expected"),
        [
            (
                "High spread 2024-08-16",
                "test_case_2024_08_16",
                "price_data_2024_08_16",
                {
                    "base_cost": 127.95,
                    "optimized_cost": 85.44,
                    "savings": 42.51,
                    "charge": 27.0,
                    "discharge": 27.0,
                },
            ),
            (
                "No spread 2025-01-05",
                "test_case_2025_01_05",
                "price_data_2025_01_05",
                {
                    "base_cost": 113.41,
                    "optimized_cost": 113.41,
                    "savings": 0.0,
                    "charge": 0.0,
                    "discharge": 0.0,
                },
            ),
            (
                "Evening peak 2025-01-12",
                "test_case_2025_01_12",
                "price_data_2025_01_12",
                {
                    "base_cost": 104.80,
                    "optimized_cost": 82.26,
                    "savings": 22.54,
                    "charge": 27.0,
                    "discharge": 27.0,
                },
            ),
            (
                "Night low 2025-01-13",
                "test_case_2025_01_13",
                "price_data_2025_01_13",
                {
                    "base_cost": 51.68,
                    "optimized_cost": 50.48,
                    "savings": 1.20,
                    "charge": 6.0,
                    "discharge": 5.2,
                },
            ),
        ],
    )
    def test_price_patterns(
        self,
        request,
        mock_controller_with_params,
        case_name,
        test_case_fixture,
        price_data_fixture,
        expected,
    ):
        """Test battery optimization with different price patterns.

        This test verifies that the battery optimization algorithm produces the expected
        results with various historical price patterns:

        1. High spread (2024-08-16): Large price difference between low and high periods
        2. No spread (2025-01-05): Insufficient price difference to justify battery cycling
        3. Evening peak (2025-01-12): Higher prices during evening hours
        4. Night low (2025-01-13): Very low prices during night hours
        """
        # Get fixtures dynamically
        test_case = request.getfixturevalue(test_case_fixture)
        price_data = request.getfixturevalue(price_data_fixture)

        # Setup controller with proper test parameters
        controller = mock_controller_with_params(
            consumption=test_case["consumption"], battery_soc=test_case["battery_soc"]
        )

        # Add required methods if not present
        if not hasattr(controller, "print_inverter_status"):
            controller.print_inverter_status = lambda: None
        if not hasattr(controller, "get_nordpool_prices_today"):
            controller.get_nordpool_prices_today = lambda: [1.0] * 24

        # Create system with clean controller
        system = BatterySystemManager(controller=controller)

        # Update system settings
        system.price_settings.use_actual_price = False

        # Explicitly set consumption predictions
        system._energy_manager.set_consumption_predictions(test_case["consumption"])  # noqa: SLF001

        # Create a mock price source with test data
        mock_source = MockSource(price_data)
        system._price_manager.source = mock_source  # noqa: SLF001

        # Format price entries directly to match what the system expects
        today = date.today()

        # Create price entries manually instead of using mock_source.get_prices
        price_entries = []
        for hour, price in enumerate(price_data):
            price_entries.append(
                {
                    "timestamp": f"{today} {hour:02d}:00",
                    "price": price,
                    "buyPrice": price,
                    "sellPrice": price,
                }
            )

        # Run the optimization using the public API
        schedule = system.create_schedule(price_entries=price_entries)
        schedule_data = schedule.get_schedule_data()

        # Calculate energy totals
        total_charge = sum(a for a in schedule.actions if a > 0)
        total_discharge = -sum(a for a in schedule.actions if a < 0)

        # Verify against expected values
        logger.info("Testing case: %s", case_name)

        # Verify costs and savings
        assert abs(schedule_data["summary"]
                   ["baseCost"] - expected["base_cost"]) < 1e-2
        assert (
            abs(schedule_data["summary"]["optimizedCost"] -
                expected["optimized_cost"])
            < 1e-2
        )
        assert abs(schedule_data["summary"]
                   ["savings"] - expected["savings"]) < 1e-2

        # Verify energy flows
        assert abs(total_charge - expected["charge"]) < 1e-1
        assert abs(total_discharge - expected["discharge"]) < 1e-1
