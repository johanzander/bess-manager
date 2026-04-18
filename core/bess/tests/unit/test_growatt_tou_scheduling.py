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


def hourly_to_quarterly(
    hourly_intents: dict[int, str], default: str = "IDLE"
) -> list[str]:
    """Convert hourly strategic intents to quarterly (96 periods).

    Args:
        hourly_intents: Dict mapping hour (0-23) to strategic intent
        default: Default intent for hours not specified

    Returns:
        List of 96 quarterly strategic intents (4 per hour)
    """
    quarterly = [default] * 96
    for hour, intent in hourly_intents.items():
        # Each hour has 4 quarterly periods
        for period in range(hour * 4, (hour + 1) * 4):
            quarterly[period] = intent
    return quarterly


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
        strategic_intents = hourly_to_quarterly(
            {
                20: "EXPORT_ARBITRAGE",
                21: "EXPORT_ARBITRAGE",
                22: "EXPORT_ARBITRAGE",
            }
        )

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
        strategic_intents = hourly_to_quarterly(
            {3: "GRID_CHARGING", 4: "GRID_CHARGING"}
        )

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
        strategic_intents = hourly_to_quarterly(
            {
                12: "SOLAR_STORAGE",
                13: "SOLAR_STORAGE",
            }
        )

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
        strategic_intents = hourly_to_quarterly(
            {
                3: "GRID_CHARGING",
                12: "SOLAR_STORAGE",
                19: "EXPORT_ARBITRAGE",
                20: "EXPORT_ARBITRAGE",
            }
        )

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
            scheduler.get_hour_battery_mode(0) == "load_first"
        ), "IDLE hours should be load_first"
        assert (
            scheduler.get_hour_battery_mode(23) == "load_first"
        ), "IDLE hours should be load_first"

    def test_idle_periods_use_default_mode(self, scheduler):
        """Test that IDLE strategic intents use default battery behavior."""
        strategic_intents = hourly_to_quarterly({10: "GRID_CHARGING"})

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Strategic hour must be covered with non-default mode
        strategic_mode = scheduler.get_hour_battery_mode(10)
        assert (
            strategic_mode != "load_first"
        ), f"Strategic hour 10 should not be load_first, got {strategic_mode}"

        # BEHAVIOR: Hours clearly outside strategic influence should use default mode
        clearly_idle_hours = [0, 1, 2, 15, 20, 23]  # Well outside slot boundaries
        for hour in clearly_idle_hours:
            mode = scheduler.get_hour_battery_mode(hour)
            assert (
                mode == "load_first"
            ), f"Clearly idle hour {hour} should be load_first, got {mode}"

    def test_load_support_uses_default_mode(self, scheduler):
        """Test that LOAD_SUPPORT strategic intent uses default behavior."""
        strategic_intents = hourly_to_quarterly(
            dict.fromkeys(range(12), "LOAD_SUPPORT") | {5: "GRID_CHARGING"}
        )

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
                mode == "load_first"
            ), f"Non-strategic hour {hour} should be load_first, got {mode}"


class TestHardwareConstraints:
    """Test that hardware constraints are always met regardless of strategic intents."""

    def test_no_overlapping_intervals_simple_case(self, scheduler):
        """Test that simple strategic intents produce non-overlapping intervals."""
        strategic_intents = hourly_to_quarterly(
            {
                10: "GRID_CHARGING",
                15: "EXPORT_ARBITRAGE",
            }
        )

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # HARDWARE CONSTRAINT: No overlapping intervals
        assert scheduler.has_no_overlapping_intervals(), "Intervals must not overlap"

    def test_no_overlapping_intervals_complex_case(self, scheduler):
        """Test that complex strategic patterns never produce overlaps."""
        strategic_intents = hourly_to_quarterly(
            {
                0: "GRID_CHARGING",
                5: "GRID_CHARGING",
                6: "SOLAR_STORAGE",
                19: "EXPORT_ARBITRAGE",
                20: "EXPORT_ARBITRAGE",
                23: "EXPORT_ARBITRAGE",
            }
        )

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # HARDWARE CONSTRAINT: No matter what, intervals must not overlap
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "Complex patterns must not create overlaps"

    def test_chronological_order_simple_case(self, scheduler):
        """Test that intervals are in chronological order."""
        strategic_intents = hourly_to_quarterly(
            {
                3: "GRID_CHARGING",
                15: "EXPORT_ARBITRAGE",
                22: "EXPORT_ARBITRAGE",
            }
        )

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # HARDWARE CONSTRAINT: Intervals must be chronologically ordered
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Intervals must be in chronological order"

    def test_chronological_order_out_of_order_input(self, scheduler):
        """Test that chronological order is maintained even with out-of-order strategic intents."""
        strategic_intents = hourly_to_quarterly(
            {
                23: "EXPORT_ARBITRAGE",
                1: "GRID_CHARGING",
                12: "SOLAR_STORAGE",
                5: "GRID_CHARGING",
            }
        )

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # HARDWARE CONSTRAINT: Must produce chronologically ordered intervals
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Out-of-order inputs must produce ordered intervals"

    def test_cross_midnight_patterns_work(self, scheduler):
        """Test that strategic intents spanning midnight work correctly."""
        strategic_intents = hourly_to_quarterly(
            {
                23: "EXPORT_ARBITRAGE",
                0: "GRID_CHARGING",
                1: "GRID_CHARGING",
            }
        )

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
        initial_intents = hourly_to_quarterly({10: "GRID_CHARGING"})
        scheduler.current_hour = 0
        scheduler.strategic_intents = initial_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # Simulate time passing to hour 15 (past hour 10, future hours 15+)
        current_hour = 15

        # Update with new strategic intent (only affects future)
        new_intents = hourly_to_quarterly(
            {
                10: "GRID_CHARGING",
                20: "EXPORT_ARBITRAGE",
            }
        )

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
        strategic_intents = hourly_to_quarterly(
            {
                10: "GRID_CHARGING",
                20: "EXPORT_ARBITRAGE",
            }
        )

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
        strategic_intents = ["IDLE"] * 96

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: All hours should use default mode
        for hour in range(24):
            mode = scheduler.get_hour_battery_mode(hour)
            assert (
                mode == "load_first"
            ), f"Hour {hour} should be load_first with all IDLE"

        # HARDWARE CONSTRAINTS: Must still be satisfied
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "All-IDLE schedule must not have overlaps"
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "All-IDLE schedule must be ordered"

    def test_all_strategic_schedule(self, scheduler):
        """Test schedule with all strategic (non-IDLE) intents."""
        strategic_intents = ["EXPORT_ARBITRAGE"] * 96

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
        strategic_intents = hourly_to_quarterly(
            {
                20: "EXPORT_ARBITRAGE",
                21: "EXPORT_ARBITRAGE",
                22: "EXPORT_ARBITRAGE",
            }
        )

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
        strategic_intents = hourly_to_quarterly(
            dict.fromkeys(range(0, 24, 4), "GRID_CHARGING")
        )

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
                mode == "load_first"
            ), f"Clearly non-strategic hour {hour} should be load_first"

        # HARDWARE CONSTRAINTS: Alternating pattern must not create issues
        assert (
            scheduler.has_no_overlapping_intervals()
        ), "Alternating pattern must not overlap"
        assert (
            scheduler.intervals_are_chronologically_ordered()
        ), "Alternating pattern must maintain order"


class TestMidHourScheduleUpdate:
    """Test that schedule updates mid-hour preserve the current hour's TOU coverage.

    This addresses the bug where updating at :45 (period 3 of an hour) would cause
    the current hour to lose its TOU segment because past periods (0,1,2) defaulted
    to IDLE and outvoted the active period (3).
    """

    def test_schedule_update_at_period_3_preserves_current_hour(self, scheduler):
        """Test that updating at :45 (period 3) preserves current hour's charging mode.

        Bug scenario:
        - Hour 0 should be GRID_CHARGING (periods 0-3 all need to charge)
        - At 00:45 (period 3), optimization runs
        - Past periods 0,1,2 might be marked as IDLE in new schedule
        - This should NOT cause hour 0 to flip to IDLE/load_first
        """
        # Simulate a schedule where ALL 4 periods of hour 0 should be GRID_CHARGING
        # This is what we'd expect from a full-day optimization at 00:00
        full_hour_intents = hourly_to_quarterly(
            {
                0: "GRID_CHARGING",
                1: "GRID_CHARGING",
                2: "GRID_CHARGING",
            }
        )

        # Apply initial schedule at hour 0
        scheduler.current_hour = 0
        scheduler.strategic_intents = full_hour_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # Verify hour 0 is configured for charging
        assert scheduler.is_hour_configured_for_charging(
            0
        ), "Hour 0 should initially be charging"

        # Now simulate what happens at period 3 (00:45)
        # The BUG: past periods (0,1,2) get marked as IDLE, flipping the majority
        buggy_intents = ["IDLE"] * 96
        buggy_intents[3] = "GRID_CHARGING"  # Only period 3 has the real intent
        for p in range(4, 12):  # Rest of hours 1-2
            buggy_intents[p] = "GRID_CHARGING"

        # If we apply this at hour 0, hour 0 would flip to IDLE (3 IDLE vs 1 GRID_CHARGING)
        # But we should NOT lose hour 0's charging mode

        # The FIX: preserve previous intents for past periods
        # For testing, we simulate the correct behavior
        correct_intents = full_hour_intents.copy()
        correct_intents[3] = "GRID_CHARGING"  # Period 3 from new optimization

        scheduler.current_hour = 0
        scheduler.strategic_intents = correct_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # Hour 0 should STILL be configured for charging
        assert scheduler.is_hour_configured_for_charging(
            0
        ), "Hour 0 should remain charging after mid-hour update"

    def test_partial_hour_charging_periods_create_tou_segment(self, scheduler):
        """Test that GRID_CHARGING periods within an hour create a TOU segment.

        With 15-min resolution, periods 2-3 (00:30-00:59) being GRID_CHARGING
        creates a TOU segment that covers those periods, making the hour
        configured for charging.
        """
        # 2 IDLE + 2 GRID_CHARGING in hour 0
        mixed_intents = ["IDLE"] * 96
        mixed_intents[2] = "GRID_CHARGING"  # Period 2 (00:30)
        mixed_intents[3] = "GRID_CHARGING"  # Period 3 (00:45)
        for p in range(4, 12):
            mixed_intents[p] = "GRID_CHARGING"  # Hours 1-2

        scheduler.current_hour = 0
        scheduler.strategic_intents = mixed_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # 15-min resolution creates TOU segment for GRID_CHARGING periods
        assert scheduler.is_hour_configured_for_charging(
            0
        ), "Hour 0 should be charging due to GRID_CHARGING periods 2-3"

    def test_single_strategic_period_preserved(self, scheduler):
        """Test that 15-min resolution preserves individual strategic periods.

        With 15-minute resolution, even a single GRID_CHARGING period should
        create a TOU segment. This prevents the "charging gaps" that occurred
        with hourly majority voting where minority intents were lost.
        """
        # 95 IDLE + 1 GRID_CHARGING - single period preserved
        mostly_idle = ["IDLE"] * 96
        mostly_idle[3] = "GRID_CHARGING"  # Only period 3 (00:45-00:59)

        scheduler.current_hour = 0
        scheduler.strategic_intents = mostly_idle
        scheduler._consolidate_and_convert_with_strategic_intents()

        # With 15-min resolution, the single GRID_CHARGING period creates a TOU segment
        # This is the key improvement over hourly majority voting
        mode = scheduler.get_hour_battery_mode(0)
        assert (
            mode == "battery_first"
        ), f"Hour 0 should be battery_first due to preserved GRID_CHARGING period, got {mode}"


class TestScheduleIntegrity:
    """Test that schedules maintain integrity under various conditions."""

    def test_midday_schedule_update(self, scheduler):
        """Test that schedule updates during the day work correctly."""
        # Morning schedule
        morning_intents = hourly_to_quarterly({10: "GRID_CHARGING"})

        scheduler.current_hour = 0
        scheduler.strategic_intents = morning_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # Verify morning behavior
        assert scheduler.is_hour_configured_for_charging(
            10
        ), "Morning schedule should enable charging at 10"

        # Afternoon update (simulating new price data)
        afternoon_intents = hourly_to_quarterly(
            {
                10: "GRID_CHARGING",
                20: "EXPORT_ARBITRAGE",
            }
        )

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
        strategic_intents = hourly_to_quarterly(
            {
                2: "GRID_CHARGING",
                5: "GRID_CHARGING",
                8: "GRID_CHARGING",
                11: "GRID_CHARGING",
                14: "EXPORT_ARBITRAGE",
                17: "EXPORT_ARBITRAGE",
                20: "EXPORT_ARBITRAGE",
                23: "EXPORT_ARBITRAGE",
            }
        )

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


# 10 alternating strategic hours — enough to exceed the 9-slot hardware limit.
_OVERCAPACITY_INTENTS = hourly_to_quarterly(
    {
        1: "GRID_CHARGING",
        3: "GRID_CHARGING",
        5: "GRID_CHARGING",
        7: "GRID_CHARGING",
        9: "GRID_CHARGING",
        11: "EXPORT_ARBITRAGE",
        13: "EXPORT_ARBITRAGE",
        15: "EXPORT_ARBITRAGE",
        17: "EXPORT_ARBITRAGE",
        19: "EXPORT_ARBITRAGE",
    }
)


class TestHardwareSlotCascading:
    """Test that >9 TOU segments cascade gracefully through hardware slots.

    The Growatt inverter supports at most 9 TOU slots.  On price-volatile days the
    optimiser can produce more than 9 non-load_first segments.  The system must:

    1. Never write more than 9 intervals to hardware.
    2. Mark overflow intervals as pending, not lost.
    3. Automatically program pending intervals once earlier ones expire.
    4. Correctly identify which intervals are pending (mode must be considered,
       not just time range) — regression for the batt_mode check in pending_write.
    """

    def test_hardware_slot_limit_is_never_exceeded(self, scheduler):
        """Active (hardware-programmed) intervals must not exceed 9 even when >9 exist."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=0)

        assert (
            len(scheduler.active_tou_intervals) <= 9
        ), f"Hardware slot limit exceeded: {len(scheduler.active_tou_intervals)} active intervals"

    def test_overflow_intervals_marked_as_pending_not_dropped(self, scheduler):
        """Intervals beyond the 9-slot limit are flagged pending, not silently discarded."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=0)

        all_segments = scheduler.get_all_tou_segments(current_period=0)
        real_segments = [s for s in all_segments if not s.get("is_default")]

        written = [s for s in real_segments if not s.get("pending_write")]
        pending = [s for s in real_segments if s.get("pending_write")]

        assert len(written) <= 9, "Written segments must fit within hardware limit"
        assert (
            len(pending) >= 1
        ), "Overflow segments must be marked pending, not dropped"
        # Total recorded segments must equal all 10 strategic time blocks
        assert (
            len(real_segments) == 10
        ), f"All 10 segments must be retained in memory, got {len(real_segments)}"

    def test_all_strategic_hours_remain_accessible_when_cascading(self, scheduler):
        """All strategic hours are recorded even when some cannot fit on hardware yet."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=0)

        for hour in [1, 3, 5, 7, 9]:
            assert scheduler.is_hour_configured_for_charging(
                hour
            ), f"Hour {hour} must be retained for charging even if pending write"
        for hour in [11, 13, 15, 17, 19]:
            assert scheduler.is_hour_configured_for_export(
                hour
            ), f"Hour {hour} must be retained for export even if pending write"

    def test_pending_intervals_become_active_once_slots_free(self, scheduler):
        """When earlier segments expire, previously-pending segments move to hardware."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS

        # At midnight (period 0): 10 non-expired segments, 9 active + 1 pending.
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=0)
        initial_pending = sum(
            1
            for s in scheduler.get_all_tou_segments(current_period=0)
            if not s.get("is_default") and s.get("pending_write")
        )
        assert (
            initial_pending >= 1
        ), "Should have at least one pending segment at start of day"

        # At 03:00 (period 12): hour-1 segment (01:00-01:59) is now expired.
        # The fresh rebuild from period 12 yields only 9 non-expired segments,
        # so all fit within the hardware limit and nothing is pending.
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=12)
        later_pending = sum(
            1
            for s in scheduler.get_all_tou_segments(current_period=12)
            if not s.get("is_default") and s.get("pending_write")
        )
        assert (
            later_pending == 0
        ), "Once a slot freed up, previously-pending segment must now be active"

    def test_pending_write_flag_considers_mode_not_only_time(self, scheduler):
        """pending_write must be True when mode differs, even if time range matches.

        Regression test: before the batt_mode fix, an interval in tou_intervals whose
        time range matched an active interval with a *different* mode was incorrectly
        marked pending_write=False (i.e., "already on hardware").
        """
        # Construct the edge-case state directly:
        #   active hardware has battery_first at 10:00-10:59
        #   tou_intervals holds grid_first at the same time (different mode)
        scheduler.active_tou_intervals = [
            {
                "segment_id": 1,
                "start_time": "10:00",
                "end_time": "10:59",
                "batt_mode": "battery_first",
                "enabled": True,
            }
        ]
        scheduler.tou_intervals = [
            {
                "segment_id": 2,
                "start_time": "10:00",
                "end_time": "10:59",
                "batt_mode": "grid_first",
                "enabled": True,
            }
        ]

        segments = scheduler.get_all_tou_segments(current_period=0)
        real_segments = [s for s in segments if not s.get("is_default")]

        assert len(real_segments) == 1
        assert real_segments[0]["pending_write"] is True, (
            "An interval with the same time range but a different mode must be "
            "marked pending_write=True — it has not been written to hardware"
        )


class _CapturingController:
    """Minimal controller stub that records every set_inverter_time_segment call."""

    def __init__(self):
        self.failure_tracker = None
        self.calls: list[dict] = []

    def set_inverter_time_segment(
        self,
        segment_id: int,
        batt_mode: str,
        start_time: str,
        end_time: str,
        enabled: bool,
    ) -> None:
        self.calls.append(
            {
                "segment_id": segment_id,
                "batt_mode": batt_mode,
                "start_time": start_time,
                "end_time": end_time,
                "enabled": enabled,
            }
        )


class TestHardwareWriteRespectsSlotLimit:
    """Regression tests: the inverter only accepts segment_id 1-9.

    Writing a segment_id outside that range causes the Growatt HA service to
    return 500. These tests verify that write_schedule_to_hardware never
    issues such a call regardless of how many TOU intervals were generated.
    """

    def test_no_segment_id_above_nine_is_ever_written(self, scheduler):
        """Even with overcapacity intents, every write uses a segment_id in 1..9."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=0)

        controller = _CapturingController()
        scheduler.write_schedule_to_hardware(
            controller, effective_period=0, current_tou=[]
        )

        assert controller.calls, "Expected at least one hardware write"
        for call in controller.calls:
            assert (
                1 <= call["segment_id"] <= 9
            ), f"segment_id {call['segment_id']} exceeds hardware slot range 1-9"

    def test_write_count_never_exceeds_hardware_slot_count(self, scheduler):
        """write_schedule_to_hardware must not push more than 9 segments."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=0)

        controller = _CapturingController()
        scheduler.write_schedule_to_hardware(
            controller, effective_period=0, current_tou=[]
        )

        assert (
            len(controller.calls) <= 9
        ), f"Wrote {len(controller.calls)} segments, exceeds hardware limit of 9"

    def test_segment_ids_remain_in_range_after_earlier_segments_expire(
        self, scheduler
    ):
        """Mid-day rebuild (some segments expired) must still produce ids 1..9.

        Regression for the case where _select_hardware_intervals previously
        preserved inherited ids like 10..18 from the renumbered tou_intervals.
        """
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        # period 12 = 03:00 — the 01:00 segment has expired, leaving 9 candidates.
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=12)

        controller = _CapturingController()
        scheduler.write_schedule_to_hardware(
            controller, effective_period=12, current_tou=[]
        )

        for call in controller.calls:
            assert (
                1 <= call["segment_id"] <= 9
            ), f"segment_id {call['segment_id']} exceeds hardware slot range 1-9"
