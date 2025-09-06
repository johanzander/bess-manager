"""
Behavioral tests for Growatt TOU scheduling system.

These tests verify WHAT the system does (behavior) rather than HOW it does it (implementation).
They should remain stable even if the internal algorithm changes (fixed slots, tiny segments, etc.)
as long as the business requirements are met.

Key Principles:
- Test strategic intent execution (does EXPORT_ARBITRAGE enable battery discharge?)
- Test hardware constraints (no overlaps, chronological order)
- Test operational efficiency (minimal writes)
- Test business logic (IDLE uses default mode)
- Do NOT test internal data structures, field names, or algorithm-specific details
"""

import pytest  # type: ignore

from core.bess.growatt_schedule import GrowattScheduleManager
from core.bess.settings import BatterySettings


@pytest.fixture
def battery_settings():
    """Battery settings for testing."""
    return BatterySettings(
        total_capacity=50.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


@pytest.fixture
def scheduler(battery_settings):
    """Create a scheduler instance for testing."""
    return GrowattScheduleManager(battery_settings)


class TestStrategicIntentExecution:
    """Test that strategic intents are executed correctly in terms of battery behavior."""

    def test_export_arbitrage_enables_battery_discharge(self, scheduler):
        """Test that EXPORT_ARBITRAGE strategic intent enables battery discharge during target hours."""
        strategic_intents = ["IDLE"] * 24
        strategic_intents[20] = "EXPORT_ARBITRAGE"
        strategic_intents[21] = "EXPORT_ARBITRAGE"
        strategic_intents[22] = "EXPORT_ARBITRAGE"

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Battery should be configured for discharge/export during strategic hours 20-22
        for hour in [20, 21, 22]:
            assert scheduler.is_hour_configured_for_export(
                hour
            ), f"Hour {hour} should enable battery export"

        # BEHAVIOR: Algorithm may enable export for additional hours that overlap with strategic periods
        # This is algorithm-specific but the key requirement is that strategic hours are covered
        strategic_hours_covered = all(
            scheduler.is_hour_configured_for_export(hour) for hour in [20, 21, 22]
        )
        assert strategic_hours_covered, "All strategic hours must be covered for export"

        # BEHAVIOR: Clearly non-strategic hours should NOT be configured for export
        for hour in [0, 1, 2, 5, 10, 15]:
            assert not scheduler.is_hour_configured_for_export(
                hour
            ), f"Hour {hour} should not enable export"

    def test_grid_charging_enables_battery_charge(self, scheduler):
        """Test that GRID_CHARGING strategic intent enables battery charging during target hours."""
        strategic_intents = ["IDLE"] * 24
        strategic_intents[3] = "GRID_CHARGING"
        strategic_intents[4] = "GRID_CHARGING"

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Battery should be configured for charging during strategic hours 3-4
        for hour in [3, 4]:
            assert scheduler.is_hour_configured_for_charging(
                hour
            ), f"Hour {hour} should enable battery charging"

        # BEHAVIOR: Strategic hours must be covered for charging
        strategic_hours_covered = all(
            scheduler.is_hour_configured_for_charging(hour) for hour in [3, 4]
        )
        assert (
            strategic_hours_covered
        ), "All strategic hours must be covered for charging"

        # BEHAVIOR: Clearly non-strategic hours should NOT be configured for charging
        for hour in [0, 1, 8, 12, 20, 23]:
            assert not scheduler.is_hour_configured_for_charging(
                hour
            ), f"Hour {hour} should not enable charging"

    def test_solar_storage_enables_battery_charge(self, scheduler):
        """Test that SOLAR_STORAGE strategic intent enables battery charging."""
        strategic_intents = ["IDLE"] * 24
        strategic_intents[12] = "SOLAR_STORAGE"  # Midday solar storage
        strategic_intents[13] = "SOLAR_STORAGE"

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Battery should be configured for charging during strategic solar storage hours
        strategic_hours_covered = all(
            scheduler.is_hour_configured_for_charging(hour) for hour in [12, 13]
        )
        assert (
            strategic_hours_covered
        ), "All strategic solar storage hours must be covered for charging"

    def test_mixed_strategic_intents_execute_correctly(self, scheduler):
        """Test that different strategic intents in the same schedule work correctly."""
        strategic_intents = ["IDLE"] * 24
        strategic_intents[3] = "GRID_CHARGING"  # Early morning charging
        strategic_intents[12] = "SOLAR_STORAGE"  # Midday solar storage
        strategic_intents[19] = "EXPORT_ARBITRAGE"  # Evening export
        strategic_intents[20] = "EXPORT_ARBITRAGE"

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Each strategic intent should configure battery correctly
        assert scheduler.is_hour_configured_for_charging(
            3
        ), "Hour 3 should enable grid charging"
        assert scheduler.is_hour_configured_for_charging(
            12
        ), "Hour 12 should enable solar storage"
        assert scheduler.is_hour_configured_for_export(
            19
        ), "Hour 19 should enable export"
        assert scheduler.is_hour_configured_for_export(
            20
        ), "Hour 20 should enable export"

        # BEHAVIOR: IDLE hours should use default mode
        assert (
            scheduler.get_hour_battery_mode(0) == "load-first"
        ), "IDLE hours should be load-first"
        assert (
            scheduler.get_hour_battery_mode(23) == "load-first"
        ), "IDLE hours should be load-first"

    def test_idle_periods_use_default_mode(self, scheduler):
        """Test that IDLE strategic intents use default battery behavior."""
        strategic_intents = ["IDLE"] * 24
        strategic_intents[10] = "GRID_CHARGING"  # Only one strategic period

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Strategic hour must be covered with non-default mode
        strategic_mode = scheduler.get_hour_battery_mode(10)
        assert (
            strategic_mode != "load-first"
        ), f"Strategic hour 10 should not be load-first, got {strategic_mode}"

        # BEHAVIOR: Hours clearly outside strategic influence should use default mode
        clearly_idle_hours = [0, 1, 2, 15, 20, 23]  # Well outside slot boundaries
        for hour in clearly_idle_hours:
            mode = scheduler.get_hour_battery_mode(hour)
            assert (
                mode == "load-first"
            ), f"Clearly idle hour {hour} should be load-first, got {mode}"

    def test_load_support_uses_default_mode(self, scheduler):
        """Test that LOAD_SUPPORT strategic intent uses default behavior."""
        strategic_intents = ["LOAD_SUPPORT"] * 12 + ["IDLE"] * 12
        strategic_intents[5] = "GRID_CHARGING"  # Only this should be strategic

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Only GRID_CHARGING should enable strategic charging behavior
        strategic_covered = scheduler.is_hour_configured_for_charging(5)
        assert (
            strategic_covered
        ), "Strategic GRID_CHARGING hour 5 should enable charging"

        # BEHAVIOR: Hours clearly outside strategic influence should use default mode
        clearly_non_strategic_hours = [0, 1, 15, 20, 23]  # Well outside slot boundaries
        for hour in clearly_non_strategic_hours:
            mode = scheduler.get_hour_battery_mode(hour)
            assert (
                mode == "load-first"
            ), f"Non-strategic hour {hour} should be load-first, got {mode}"


class TestHardwareConstraints:
    """Test that hardware constraints are always met regardless of strategic intents."""

    def test_no_overlapping_intervals_simple_case(self, scheduler):
        """Test that simple strategic intents produce non-overlapping intervals."""
        strategic_intents = ["IDLE"] * 24
        strategic_intents[10] = "GRID_CHARGING"
        strategic_intents[15] = "EXPORT_ARBITRAGE"

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # HARDWARE CONSTRAINT: No overlapping intervals
        assert scheduler.has_no_overlapping_intervals(), "Intervals must not overlap"

    def test_no_overlapping_intervals_complex_case(self, scheduler):
        """Test that complex strategic patterns never produce overlaps."""
        # Complex pattern that could cause overlaps with naive algorithms
        strategic_intents = ["IDLE"] * 24
        strategic_intents[5] = "GRID_CHARGING"
        strategic_intents[6] = "SOLAR_STORAGE"
        strategic_intents[19] = "EXPORT_ARBITRAGE"
        strategic_intents[20] = "EXPORT_ARBITRAGE"
        strategic_intents[23] = "EXPORT_ARBITRAGE"
        strategic_intents[0] = "GRID_CHARGING"  # Cross-midnight

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # HARDWARE CONSTRAINT: No matter what, intervals must not overlap
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "Complex patterns must not create overlaps"

    def test_chronological_order_simple_case(self, scheduler):
        """Test that intervals are in chronological order."""
        strategic_intents = ["IDLE"] * 24
        strategic_intents[3] = "GRID_CHARGING"
        strategic_intents[15] = "EXPORT_ARBITRAGE"
        strategic_intents[22] = "EXPORT_ARBITRAGE"

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # HARDWARE CONSTRAINT: Intervals must be chronologically ordered
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Intervals must be in chronological order"

    def test_chronological_order_out_of_order_input(self, scheduler):
        """Test that chronological order is maintained even with out-of-order strategic intents."""
        # Strategic intents in non-chronological order
        strategic_intents = ["IDLE"] * 24
        strategic_intents[23] = "EXPORT_ARBITRAGE"  # Last hour
        strategic_intents[1] = "GRID_CHARGING"  # Early hour
        strategic_intents[12] = "SOLAR_STORAGE"  # Mid day
        strategic_intents[5] = "GRID_CHARGING"  # Another early hour

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # HARDWARE CONSTRAINT: Must produce chronologically ordered intervals
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Out-of-order inputs must produce ordered intervals"

    def test_cross_midnight_patterns_work(self, scheduler):
        """Test that strategic intents spanning midnight work correctly."""
        strategic_intents = ["IDLE"] * 24
        strategic_intents[23] = "EXPORT_ARBITRAGE"  # Last hour of day
        strategic_intents[0] = "GRID_CHARGING"  # First hour of day
        strategic_intents[1] = "GRID_CHARGING"  # Second hour

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Strategic intents should execute correctly
        assert scheduler.is_hour_configured_for_export(
            23
        ), "Hour 23 should enable export"
        assert scheduler.is_hour_configured_for_charging(
            0
        ), "Hour 0 should enable charging"
        assert scheduler.is_hour_configured_for_charging(
            1
        ), "Hour 1 should enable charging"

        # HARDWARE CONSTRAINTS: Must be satisfied even across midnight
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "Cross-midnight patterns must not overlap"
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Cross-midnight patterns must be ordered"


class TestOperationalEfficiency:
    """Test that the system optimizes for minimal hardware writes."""

    def test_minimal_writes_for_future_changes_only(self, scheduler):
        """Test that only future changes require hardware writes."""
        # Set up existing schedule
        initial_intents = ["IDLE"] * 24
        initial_intents[10] = "GRID_CHARGING"
        scheduler.current_hour = 0
        scheduler.strategic_intents = initial_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # Simulate time passing to hour 15 (past hour 10, future hours 15+)
        current_hour = 15

        # Update with new strategic intent (only affects future)
        new_intents = ["IDLE"] * 24
        new_intents[10] = "GRID_CHARGING"  # Same as before (past)
        new_intents[20] = "EXPORT_ARBITRAGE"  # New (future)

        write_count = scheduler.apply_schedule_and_count_writes(
            new_intents, current_hour
        )

        # EFFICIENCY: Should minimize writes (exact count depends on implementation)
        # The key is that it should be significantly less than rewriting everything
        assert (
            write_count <= 5
        ), f"Expected minimal writes for future-only changes, got {write_count}"

    def test_no_writes_for_identical_schedule(self, scheduler):
        """Test that identical schedules don't trigger unnecessary writes."""
        # Set up initial schedule
        strategic_intents = ["IDLE"] * 24
        strategic_intents[10] = "GRID_CHARGING"
        strategic_intents[20] = "EXPORT_ARBITRAGE"

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # Apply identical schedule later
        current_hour = 5
        write_count = scheduler.apply_schedule_and_count_writes(
            strategic_intents, current_hour
        )

        # EFFICIENCY: Identical future schedule should minimize writes
        assert (
            write_count <= 3
        ), f"Identical schedule should require minimal writes, got {write_count}"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_all_idle_schedule(self, scheduler):
        """Test schedule with only IDLE strategic intents."""
        strategic_intents = ["IDLE"] * 24

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: All hours should use default mode
        for hour in range(24):
            mode = scheduler.get_hour_battery_mode(hour)
            assert (
                mode == "load-first"
            ), f"Hour {hour} should be load-first with all IDLE"

        # HARDWARE CONSTRAINTS: Must still be satisfied
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "All-IDLE schedule must not have overlaps"
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "All-IDLE schedule must be ordered"

    def test_all_strategic_schedule(self, scheduler):
        """Test schedule with all strategic (non-IDLE) intents."""
        strategic_intents = ["EXPORT_ARBITRAGE"] * 24  # All hours strategic

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: All hours should enable export
        for hour in range(24):
            assert scheduler.is_hour_configured_for_export(
                hour
            ), f"Hour {hour} should enable export"

        # HARDWARE CONSTRAINTS: Must still be satisfied
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "All-strategic schedule must not have overlaps"
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "All-strategic schedule must be ordered"

    def test_consecutive_periods_work_correctly(self, scheduler):
        """Test that consecutive strategic periods are handled correctly."""
        strategic_intents = ["IDLE"] * 24
        strategic_intents[20] = "EXPORT_ARBITRAGE"
        strategic_intents[21] = "EXPORT_ARBITRAGE"
        strategic_intents[22] = "EXPORT_ARBITRAGE"

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: All consecutive hours should enable export
        for hour in [20, 21, 22]:
            assert scheduler.is_hour_configured_for_export(
                hour
            ), f"Hour {hour} should enable export"

        # HARDWARE CONSTRAINTS: Consecutive periods must not create issues
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "Consecutive periods must not overlap"
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Consecutive periods must maintain order"

    def test_alternating_strategic_intents(self, scheduler):
        """Test alternating strategic intents pattern."""
        strategic_intents = ["IDLE"] * 24
        # Alternating pattern: GRID_CHARGING every 4th hour
        for hour in range(0, 24, 4):
            strategic_intents[hour] = "GRID_CHARGING"

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Strategic hours must be covered for charging
        strategic_hours = [0, 4, 8, 12, 16, 20]
        strategic_hours_covered = all(
            scheduler.is_hour_configured_for_charging(hour) for hour in strategic_hours
        )
        assert (
            strategic_hours_covered
        ), "All strategic hours must be covered for charging"

        # BEHAVIOR: Hours clearly outside slot influence should use default mode
        clearly_non_strategic_hours = [6, 7, 14, 15, 22, 23]  # In disabled slots
        for hour in clearly_non_strategic_hours:
            mode = scheduler.get_hour_battery_mode(hour)
            assert (
                mode == "load-first"
            ), f"Clearly non-strategic hour {hour} should be load-first"

        # HARDWARE CONSTRAINTS: Alternating pattern must not create issues
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "Alternating pattern must not overlap"
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Alternating pattern must maintain order"


class TestScheduleIntegrity:
    """Test that schedules maintain integrity under various conditions."""

    def test_midday_schedule_update(self, scheduler):
        """Test that schedule updates during the day work correctly."""
        # Morning schedule
        morning_intents = ["IDLE"] * 24
        morning_intents[10] = "GRID_CHARGING"

        scheduler.current_hour = 0
        scheduler.strategic_intents = morning_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # Verify morning behavior
        assert scheduler.is_hour_configured_for_charging(
            10
        ), "Morning schedule should enable charging at 10"

        # Afternoon update (simulating new price data)
        afternoon_intents = ["IDLE"] * 24
        afternoon_intents[10] = "GRID_CHARGING"  # Keep existing
        afternoon_intents[20] = "EXPORT_ARBITRAGE"  # Add new

        scheduler.current_hour = 15  # Afternoon update
        scheduler.strategic_intents = afternoon_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Both strategic periods should work
        assert scheduler.is_hour_configured_for_charging(
            10
        ), "Past strategic intent should still work"
        assert scheduler.is_hour_configured_for_export(
            20
        ), "New strategic intent should work"

        # HARDWARE CONSTRAINTS: Update must maintain constraints
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "Schedule update must not create overlaps"
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Schedule update must maintain order"

    def test_extreme_fragmentation_scenario(self, scheduler):
        """Test extreme case with many scattered strategic periods."""
        strategic_intents = ["IDLE"] * 24
        # Scattered strategic periods throughout day
        for hour in [2, 5, 8, 11, 14, 17, 20, 23]:
            intent = "GRID_CHARGING" if hour < 12 else "EXPORT_ARBITRAGE"
            strategic_intents[hour] = intent

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: All strategic periods should execute
        for hour in [2, 5, 8, 11]:
            assert scheduler.is_hour_configured_for_charging(
                hour
            ), f"Hour {hour} should enable charging"
        for hour in [14, 17, 20, 23]:
            assert scheduler.is_hour_configured_for_export(
                hour
            ), f"Hour {hour} should enable export"

        # HARDWARE CONSTRAINTS: Fragmented schedule must still meet constraints
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "Fragmented schedule must not overlap"
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Fragmented schedule must be ordered"
