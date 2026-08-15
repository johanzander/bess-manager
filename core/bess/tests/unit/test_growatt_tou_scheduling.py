"""
Behavioral tests for Growatt TOU scheduling system.

These tests verify WHAT the system does (behavior) rather than HOW it does it (implementation).
They should remain stable even if the internal algorithm changes (fixed slots, tiny segments, etc.)
as long as the business requirements are met.

Key Principles:
- Test strategic intent execution (does BATTERY_EXPORT enable battery discharge?)
- Test hardware constraints (no overlaps, chronological order)
- Test operational efficiency (minimal writes)
- Test business logic (IDLE uses default mode)
- Do NOT test internal data structures, field names, or algorithm-specific details
"""

import logging
from types import SimpleNamespace

import pytest  # type: ignore

from core.bess import time_utils
from core.bess.growatt_min_controller import GrowattMinController
from core.bess.settings import BatterySettings
from core.bess.tests.helpers import empty_slot_table


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
    return GrowattMinController(battery_settings)


class TestBuildCandidate:
    """_build_candidate must not mutate self.tou_intervals/self.strategic_intents —
    it's the shared computation both evaluate_intents and apply_intents call."""

    def test_does_not_mutate_self_state(self, scheduler):
        scheduler.strategic_intents = hourly_to_quarterly({2: "GRID_CHARGING"})
        scheduler.tou_intervals = ["sentinel"]

        candidate_intents = hourly_to_quarterly({5: "BATTERY_EXPORT"})
        new_intervals, new_active = scheduler._build_candidate(
            candidate_intents, current_period=0
        )

        assert scheduler.tou_intervals == ["sentinel"]
        assert scheduler.strategic_intents == hourly_to_quarterly({2: "GRID_CHARGING"})
        assert new_intervals != ["sentinel"]
        assert isinstance(new_active, list)

    def test_matches_consolidate_and_convert_output(self, scheduler):
        """The extracted candidate builder must produce byte-identical output
        to the existing (untouched) mutator, for the same intents."""
        intents = hourly_to_quarterly(
            {2: "GRID_CHARGING", 10: "BATTERY_EXPORT", 18: "LOAD_SUPPORT"}
        )
        scheduler.strategic_intents = intents
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=0)
        expected_intervals = [i.copy() for i in scheduler.tou_intervals]
        expected_active = [i.copy() for i in scheduler.active_tou_intervals]

        # Reset and rebuild via the new pure path
        scheduler.tou_intervals = []
        scheduler.active_tou_intervals = []
        candidate_intervals, candidate_active = scheduler._build_candidate(
            intents, current_period=0
        )

        assert candidate_intervals == expected_intervals
        assert candidate_active == expected_active


class TestStrategicIntentExecution:
    """Test that strategic intents are executed correctly in terms of battery behavior."""

    def test_export_arbitrage_enables_battery_discharge(self, scheduler):
        """Test that BATTERY_EXPORT strategic intent enables battery discharge during target hours."""
        strategic_intents = hourly_to_quarterly(
            {
                20: "BATTERY_EXPORT",
                21: "BATTERY_EXPORT",
                22: "BATTERY_EXPORT",
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

    def test_solar_storage_uses_default_mode(self, scheduler):
        """Test that SOLAR_STORAGE uses load_first (inverter default).

        SOLAR_STORAGE uses load_first so solar serves the home first and excess
        charges the battery. This is the inverter's default behavior, so no TOU
        segment is needed — the inverter handles it naturally.
        """
        strategic_intents = hourly_to_quarterly(
            {
                12: "SOLAR_STORAGE",
                13: "SOLAR_STORAGE",
            }
        )

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: SOLAR_STORAGE should use load_first (default mode, no TOU segment needed)
        assert (
            scheduler.get_hour_battery_mode(12) == "load_first"
        ), "SOLAR_STORAGE hours should use load_first"
        assert (
            scheduler.get_hour_battery_mode(13) == "load_first"
        ), "SOLAR_STORAGE hours should use load_first"

    def test_mixed_strategic_intents_execute_correctly(self, scheduler):
        """Test that different strategic intents in the same schedule work correctly."""
        strategic_intents = hourly_to_quarterly(
            {
                3: "GRID_CHARGING",
                12: "SOLAR_STORAGE",
                19: "BATTERY_EXPORT",
                20: "BATTERY_EXPORT",
            }
        )

        scheduler.current_hour = 0
        scheduler.strategic_intents = strategic_intents
        scheduler._consolidate_and_convert_with_strategic_intents()

        # BEHAVIOR: Each strategic intent should configure battery correctly
        assert scheduler.is_hour_configured_for_charging(
            3
        ), "Hour 3 should enable grid charging"
        assert (
            scheduler.get_hour_battery_mode(12) == "load_first"
        ), "Hour 12 (SOLAR_STORAGE) should use load_first"
        assert scheduler.is_hour_configured_for_export(
            19
        ), "Hour 19 should enable export"
        assert scheduler.is_hour_configured_for_export(
            20
        ), "Hour 20 should enable export"

        # BEHAVIOR: IDLE and SOLAR_STORAGE hours should use default mode
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
                15: "BATTERY_EXPORT",
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
                19: "BATTERY_EXPORT",
                20: "BATTERY_EXPORT",
                23: "BATTERY_EXPORT",
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
                15: "BATTERY_EXPORT",
                22: "BATTERY_EXPORT",
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
                23: "BATTERY_EXPORT",
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
                23: "BATTERY_EXPORT",
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
                20: "BATTERY_EXPORT",
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
                20: "BATTERY_EXPORT",
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

    def test_dst_fall_back_never_writes_an_invalid_end_time(self, scheduler):
        """#302 (Frank-Leysen): a runtime 500 from HA's select_option while
        setting `tou_time_1_end`, on the DST fall-back day.

        That day has 25 hours, so the schedule carries 100 quarterly periods
        instead of 96 and the final period converts to hour 24 — a time no
        TOU register can hold. `_groups_to_tou_intervals` caps it at 23:59;
        without the cap the interval is written as `24:59` and the inverter
        entity rejects it.

        Found unguarded during the 2026-08-11 pre-release audit: deleting the
        cap left all 1714 fast tests green, so this crash could return in a
        release without any signal. Asserted on the emitted interval — the
        value that reaches hardware — rather than on the capping branch.
        """
        scheduler.current_hour = 0
        scheduler.strategic_intents = ["BATTERY_EXPORT"] * 100  # 25-hour day
        scheduler._consolidate_and_convert_with_strategic_intents()

        assert scheduler.tou_intervals, "no interval produced to check"
        for interval in scheduler.tou_intervals:
            for field in ("start_time", "end_time"):
                hour, minute = (int(part) for part in interval[field].split(":"))
                assert 0 <= hour <= 23, (
                    f"{field}={interval[field]} is not a valid wall-clock time; "
                    "HA's select_option rejects it (#302)"
                )
                assert 0 <= minute <= 59, f"{field}={interval[field]} is invalid"

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
        strategic_intents = ["BATTERY_EXPORT"] * 96

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
                20: "BATTERY_EXPORT",
                21: "BATTERY_EXPORT",
                22: "BATTERY_EXPORT",
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
                20: "BATTERY_EXPORT",
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
                14: "BATTERY_EXPORT",
                17: "BATTERY_EXPORT",
                20: "BATTERY_EXPORT",
                23: "BATTERY_EXPORT",
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


# 01:00, the first strategic hour below, as a period. Cycles run from here so
# that segment is already active: since #554 a segment is only eligible for
# hardware once its start is within the write horizon, and an active segment
# (start <= now) qualifies under any horizon. Tests about slot ids, failure
# propagation and idempotency would otherwise depend on the horizon's value.
_ACTIVE_SEGMENT_PERIOD = 4

# 10 alternating strategic hours — enough to exceed the 9-slot hardware limit.
_OVERCAPACITY_INTENTS = hourly_to_quarterly(
    {
        1: "GRID_CHARGING",
        3: "GRID_CHARGING",
        5: "GRID_CHARGING",
        7: "GRID_CHARGING",
        9: "GRID_CHARGING",
        11: "BATTERY_EXPORT",
        13: "BATTERY_EXPORT",
        15: "BATTERY_EXPORT",
        17: "BATTERY_EXPORT",
        19: "BATTERY_EXPORT",
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

    def test_intervals_not_yet_on_hardware_are_not_dropped(self, scheduler):
        """Intervals not yet written are retained in the plan, not discarded."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=0)

        all_segments = scheduler.get_all_tou_segments(current_period=0)
        real_segments = [s for s in all_segments if not s.get("is_default")]

        assert (
            len(scheduler.active_tou_intervals) <= 9
        ), "Hardware-eligible intervals must fit within the slot limit"
        # Total recorded segments must equal all 10 strategic time blocks
        assert (
            len(real_segments) == 10
        ), f"All 10 segments must be retained in memory, got {len(real_segments)}"

    def test_due_but_unwritten_interval_is_flagged_pending(self, scheduler):
        """pending_write must still fire for a segment that IS due.

        Since #554 a far-future segment is deferred rather than pending, so
        the flag is set up here directly: an interval inside the write horizon
        that the hardware-eligible set does not contain.
        """
        scheduler.active_tou_intervals = []
        scheduler.tou_intervals = [
            {
                "segment_id": 1,
                "start_time": "00:15",
                "end_time": "00:59",
                "batt_mode": "battery_first",
                "enabled": True,
            }
        ]

        segments = scheduler.get_all_tou_segments(current_period=0)
        real_segments = [s for s in segments if not s.get("is_default")]

        assert len(real_segments) == 1
        assert real_segments[0]["pending_write"] is True, (
            "A segment due within the write horizon but absent from hardware "
            "must be flagged pending"
        )

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

    def test_deferred_intervals_become_eligible_as_their_start_approaches(
        self, scheduler
    ):
        """Deferred segments must reach hardware, not be stranded.

        Since #554 the binding constraint is the write horizon rather than the
        9 slots. Asserted on hardware eligibility rather than the pending_write
        flag, which now covers only segments that are due and still missing.
        """
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS

        def is_eligible(period, start_time):
            scheduler._consolidate_and_convert_with_strategic_intents(
                current_period=period
            )
            return any(
                i["start_time"] == start_time for i in scheduler.active_tou_intervals
            )

        # The 09:00 segment: still deferred at 06:00, eligible by 08:30.
        assert not is_eligible(
            24, "09:00"
        ), "09:00 segment should still be deferred at 06:00"
        assert is_eligible(
            34, "09:00"
        ), "09:00 segment must be eligible by 08:30, before it starts"

    def test_slot_cap_still_applies_when_many_intervals_are_eligible(self, scheduler):
        """The 9-slot hardware cap must survive independently of the horizon.

        Tested directly on _select_hardware_intervals: since #554 no realistic
        plan can put more than ~5 intervals inside the write horizon, so the
        cap is no longer reachable end-to-end. It still guards the inverter
        contract (segment_id must be 1..9), so it is exercised here rather
        than deleted.
        """
        eligible = [
            {
                "segment_id": i,
                "start_time": "00:00",
                "end_time": "00:59",
                "batt_mode": "battery_first",
                "enabled": True,
            }
            for i in range(1, 13)
        ]

        selected = scheduler._select_hardware_intervals(eligible, current_period=0)

        assert len(selected) == scheduler.max_intervals

    def test_pending_write_flag_considers_mode_not_only_time(self, scheduler):
        """pending_write must be True when mode differs, even if time range matches.

        Regression test: before the batt_mode fix, an interval in tou_intervals whose
        time range matched an active interval with a *different* mode was incorrectly
        marked pending_write=False (i.e., "already on hardware").

        Evaluated at 09:30 so the interval is inside the write horizon: since
        #554 a deferred interval is never flagged pending, which would make the
        mode comparison below unreachable.
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

        # Period 38 = 09:30, inside the write horizon for a 10:00 interval.
        segments = scheduler.get_all_tou_segments(current_period=38)
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

    def read_inverter_time_segments(self) -> list[dict]:
        return empty_slot_table()

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
    return 500. These tests verify that sync_to_hardware never
    issues such a call regardless of how many TOU intervals were generated.
    """

    def test_no_segment_id_above_nine_is_ever_written(self, scheduler):
        """Even with overcapacity intents, every write uses a segment_id in 1..9."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(
            current_period=_ACTIVE_SEGMENT_PERIOD
        )

        controller = _CapturingController()
        scheduler.sync_to_hardware(controller, effective_period=_ACTIVE_SEGMENT_PERIOD)

        assert controller.calls, "Expected at least one hardware write"
        for call in controller.calls:
            assert (
                1 <= call["segment_id"] <= 9
            ), f"segment_id {call['segment_id']} exceeds hardware slot range 1-9"

    def test_write_count_never_exceeds_hardware_slot_count(self, scheduler):
        """sync_to_hardware must not push more than 9 segments."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(
            current_period=_ACTIVE_SEGMENT_PERIOD
        )

        controller = _CapturingController()
        scheduler.sync_to_hardware(controller, effective_period=_ACTIVE_SEGMENT_PERIOD)

        assert controller.calls, "Expected at least one hardware write"
        assert (
            len(controller.calls) <= 9
        ), f"Wrote {len(controller.calls)} segments, exceeds hardware limit of 9"

    def test_segment_ids_remain_in_range_after_earlier_segments_expire(self, scheduler):
        """Mid-day rebuild (some segments expired) must still produce ids 1..9.

        Regression for the case where _select_hardware_intervals previously
        preserved inherited ids like 10..18 from the renumbered tou_intervals.
        """
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        # period 12 = 03:00 — the 01:00 segment has expired, leaving 9 candidates.
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=12)

        controller = _CapturingController()
        scheduler.sync_to_hardware(controller, effective_period=12)

        for call in controller.calls:
            assert (
                1 <= call["segment_id"] <= 9
            ), f"segment_id {call['segment_id']} exceeds hardware slot range 1-9"


class _FailingController(_CapturingController):
    """Controller stub whose writes raise, simulating a 500 from HA core."""

    def set_inverter_time_segment(self, **kwargs) -> None:
        raise RuntimeError("500 Server Error: Internal Server Error")


class TestHardwareWriteFailurePropagates:
    """Regression: a failed segment write must raise, not be swallowed.

    Previously sync_to_hardware caught per-segment write
    exceptions and only logged them, returning normally. The caller
    (BatterySystemManager._apply_schedule) treated that as success and
    cleared _hardware_write_pending, so a failed write was never retried
    and the dashboard kept showing the intended schedule as if it had
    reached the inverter.
    """

    def test_failed_segment_write_raises(self, scheduler):
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(
            current_period=_ACTIVE_SEGMENT_PERIOD
        )

        controller = _FailingController()
        with pytest.raises(RuntimeError):
            scheduler.sync_to_hardware(
                controller, effective_period=_ACTIVE_SEGMENT_PERIOD
            )


class _SimulatingController(_CapturingController):
    """Controller stub that also models the inverter's TOU slot table.

    Writes with enabled=True occupy the slot; enabled=False clears it.
    `hardware_segments()` returns the currently programmed segments, and
    `read_inverter_time_segments()` reports the full 9-slot table the way the
    real inverter does — occupied slots plus disabled entries for the rest.
    """

    def __init__(self):
        super().__init__()
        self.slots: dict[int, dict] = {}

    def set_inverter_time_segment(
        self,
        segment_id: int,
        batt_mode: str,
        start_time: str,
        end_time: str,
        enabled: bool,
    ) -> None:
        super().set_inverter_time_segment(
            segment_id, batt_mode, start_time, end_time, enabled
        )
        if enabled:
            self.slots[segment_id] = {
                "segment_id": segment_id,
                "batt_mode": batt_mode,
                "start_time": start_time,
                "end_time": end_time,
                "enabled": True,
            }
        else:
            self.slots.pop(segment_id, None)

    def hardware_segments(self) -> list[dict]:
        return [dict(s) for s in self.slots.values()]

    def read_inverter_time_segments(self) -> list[dict]:
        return [
            dict(self.slots.get(slot["segment_id"], slot))
            for slot in empty_slot_table()
        ]


class TestSlotAssignmentPreservesActiveSegments:
    """When a previously-pending segment promotes to active across cycles, the
    write logic must place it in a freed slot — not overwrite a slot that
    still holds a needed segment.
    """

    def _content_set(self, segments) -> set[tuple]:
        return {(s["start_time"], s["end_time"], s["batt_mode"]) for s in segments}

    def test_promoted_pending_segment_does_not_evict_still_needed_segments(
        self, scheduler
    ):
        """Segments entering the write horizon must take a free slot.

        Since #554 promotion is driven by a segment's start coming within the
        horizon rather than by a slot freeing up, so the plan below alternates
        mode every 15 minutes: each cycle brings a new segment into range while
        earlier ones are still live and must not be overwritten.
        """
        scheduler.strategic_intents = [
            "GRID_CHARGING" if period % 2 == 0 else "BATTERY_EXPORT"
            for period in range(96)
        ]
        controller = _SimulatingController()

        for period in range(0, 12):
            scheduler._consolidate_and_convert_with_strategic_intents(
                current_period=period
            )
            scheduler.sync_to_hardware(controller, effective_period=period)

            hardware = self._content_set(controller.hardware_segments())
            wanted = self._content_set(scheduler.active_tou_intervals)

            # Every interval the scheduler considers active must actually be on
            # hardware — none silently evicted by a slot collision.
            missing = wanted - hardware
            assert not missing, (
                f"Active intervals missing from hardware at period {period}: "
                f"{sorted(missing)}"
            )

            # And every slot id used is still in the legal 1..9 range.
            for slot_id in controller.slots:
                assert 1 <= slot_id <= 9

    def test_unchanged_segments_are_not_rewritten_across_cycles(self, scheduler):
        """Idempotency: if nothing changes between cycles, no hardware write
        should be emitted in the second cycle."""
        scheduler.strategic_intents = _OVERCAPACITY_INTENTS
        scheduler._consolidate_and_convert_with_strategic_intents(
            current_period=_ACTIVE_SEGMENT_PERIOD
        )

        controller = _SimulatingController()
        scheduler.sync_to_hardware(controller, effective_period=_ACTIVE_SEGMENT_PERIOD)
        cycle1_call_count = len(controller.calls)
        assert cycle1_call_count > 0

        # Re-run the same conversion at the same period — no state has changed.
        scheduler._consolidate_and_convert_with_strategic_intents(
            current_period=_ACTIVE_SEGMENT_PERIOD
        )
        scheduler.sync_to_hardware(
            controller,
            effective_period=_ACTIVE_SEGMENT_PERIOD,
        )
        assert (
            len(controller.calls) == cycle1_call_count
        ), "Cycle 2 with identical state should not issue any new writes"


# ── Regression: issue #551 — TOU diff must be computed against real hardware ──
#
# The data below is real, from the 2026-08-12 07:30 production failure:
#   - _LIVE_HARDWARE_SLOTS: the growatt_server.read_time_segments response read
#     off the inverter while the add-on was failing.
#   - _intents_at_0730(): the strategic intent list rebuilt from that cycle's
#     "Intent transition at period N" lines in the debug bundle.
#
# Replaying that cycle against the pre-fix code reproduces the production log
# exactly: "Current=5 intervals, New=4", "Disabling TOU segment 2: 08:00-08:29",
# then "Setting TOU segment 1: 08:00-08:14" — the write Growatt 500s on.


def _seg(segment_id, start, end, mode, enabled=True):
    return {
        "segment_id": segment_id,
        "start_time": start,
        "end_time": end,
        "batt_mode": mode,
        "enabled": enabled,
    }


_LIVE_HARDWARE_SLOTS = [
    _seg(1, "07:00", "07:14", "grid_first"),
    _seg(2, "08:00", "08:29", "grid_first", enabled=False),
    _seg(3, "08:00", "08:14", "grid_first"),
    _seg(4, "09:00", "09:14", "grid_first"),
    _seg(5, "19:30", "20:29", "grid_first"),
    _seg(6, "11:45", "11:59", "battery_first"),
    _seg(7, "13:45", "14:14", "battery_first"),
    _seg(8, "16:00", "16:14", "battery_first"),
    _seg(9, "23:45", "23:59", "battery_first", enabled=False),
]

# Ranges enabled on the inverter that the optimizer's plan does not contain.
# The battery really did run these unplanned; they are leftovers from earlier
# cycles whose disable calls returned 500.
_ORPHAN_RANGES = {
    ("09:00", "09:14"),
    ("11:45", "11:59"),
    ("16:00", "16:14"),
}

# 13:45-14:14 is deliberately not in the set above. The plan holds
# 13:45-13:59, so it is the same window with a later end rather than a
# segment nobody planned, and the two behave identically until 14:00. Since
# #589 that write waits until the difference is imminent; the deadline is
# covered by test_a_shortened_window_is_cleared_before_the_cut_takes_effect.


def _intents_at_0730() -> list[str]:
    """Rebuild the 07:30 cycle's 96-period intent list from the debug bundle."""
    intents = ["LOAD_SUPPORT"] * 96
    for start, end, intent in [
        (30, 32, "SOLAR_EXPORT"),
        (32, 33, "BATTERY_EXPORT"),
        (33, 37, "SOLAR_EXPORT"),
        (37, 52, "SOLAR_STORAGE"),
        (52, 53, "GRID_CHARGING"),
        (53, 55, "SOLAR_STORAGE"),
        (55, 56, "GRID_CHARGING"),
        (56, 63, "SOLAR_STORAGE"),
        (63, 64, "SOLAR_EXPORT"),
        (64, 66, "SOLAR_STORAGE"),
        (66, 68, "SOLAR_EXPORT"),
        (68, 70, "IDLE"),
        (70, 78, "LOAD_SUPPORT"),
        (78, 82, "BATTERY_EXPORT"),
    ]:
        for period in range(start, end):
            intents[period] = intent
    return intents


class _PreloadedController(_CapturingController):
    """Controller stub modelling an inverter whose 9 slots are already
    populated, readable the way growatt_server.read_time_segments reads them."""

    def __init__(self, segments):
        super().__init__()
        self.segments = [dict(s) for s in segments]

    def read_inverter_time_segments(self):
        return [dict(s) for s in self.segments]

    def set_inverter_time_segment(
        self, segment_id, batt_mode, start_time, end_time, enabled
    ):
        super().set_inverter_time_segment(
            segment_id, batt_mode, start_time, end_time, enabled
        )
        for seg in self.segments:
            if seg["segment_id"] == segment_id:
                seg.update(
                    start_time=start_time,
                    end_time=end_time,
                    batt_mode=batt_mode,
                    enabled=enabled,
                )
                return
        self.segments.append(_seg(segment_id, start_time, end_time, batt_mode, enabled))

    def enabled_ranges(self) -> set[tuple[str, str]]:
        return {
            (seg["start_time"], seg["end_time"])
            for seg in self.segments
            if seg["enabled"]
        }


class _UnreadableController(_CapturingController):
    """Controller whose segment read fails the way a transport error does."""

    def read_inverter_time_segments(self):
        raise RuntimeError("500 Server Error: Internal Server Error")


class TestWriteDiffsAgainstRealHardware:
    """Regression for issue #551.

    The add-on read hardware TOU once at startup and diffed every later cycle
    against its own in-memory model. Once those diverged it wrote segments that
    duplicated live ones — which Growatt's cloud rejects with a 500 — and left
    unplanned segments enabled on the inverter.
    """

    def _run_0730_cycle(self, scheduler, controller):
        scheduler.strategic_intents = _intents_at_0730()
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=30)
        scheduler.sync_to_hardware(controller, effective_period=30)

    def test_does_not_rewrite_a_range_already_enabled_on_hardware(self, scheduler):
        controller = _PreloadedController(_LIVE_HARDWARE_SLOTS)
        self._run_0730_cycle(scheduler, controller)

        duplicated = [
            call
            for call in controller.calls
            if call["enabled"]
            and (call["start_time"], call["end_time"]) == ("08:00", "08:14")
        ]
        assert not duplicated, (
            "Wrote 08:00-08:14 grid_first, which slot 3 already holds enabled — "
            f"Growatt rejects this with a 500. Calls: {duplicated}"
        )

    def test_unplanned_segments_left_on_hardware_are_disabled(self, scheduler):
        controller = _PreloadedController(_LIVE_HARDWARE_SLOTS)
        self._run_0730_cycle(scheduler, controller)

        still_enabled = controller.enabled_ranges() & _ORPHAN_RANGES
        assert not still_enabled, (
            "Segments left enabled on the inverter that the plan does not "
            f"contain: {sorted(still_enabled)}"
        )

    def test_a_shortened_window_is_cleared_before_the_cut_takes_effect(self, scheduler):
        """13:45-14:14 on hardware against 13:45-13:59 in the plan.

        Not an orphan: same start, same mode, and identical behaviour until
        14:00. Since #589 the write waits, because issuing it at 07:30 is
        churn — six hours before the only quarter-hour that differs. What must
        not slip is the deadline: the cut has to reach the inverter before
        14:00, or the battery runs a quarter-hour the plan does not want.

        Asserted at 13:15 rather than 07:30 for that reason — the earlier
        cycle deliberately writes nothing here, so asserting there would pin
        the churn this change removes.
        """
        controller = _PreloadedController(_LIVE_HARDWARE_SLOTS)
        scheduler.strategic_intents = _intents_at_0730()

        # 13:15 — 45 minutes before the difference at 14:00 takes effect.
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=53)
        scheduler.sync_to_hardware(controller, effective_period=53)

        assert ("13:45", "14:14") not in controller.enabled_ranges(), (
            "The over-long window is still enabled 45 minutes before its "
            "extra quarter-hour would run: "
            f"{sorted(controller.enabled_ranges())}"
        )

    def test_slots_already_disabled_on_hardware_are_not_rewritten(self, scheduler):
        """Real hardware reports its unused slots as disabled entries.

        The in-memory model only ever held enabled intervals, so the diff never
        saw a disabled one. Reading the inverter surfaces them, and re-issuing
        a disable for a slot that is already disabled is a wasted write against
        a cloud API that rejects them under load.
        """
        controller = _PreloadedController(_LIVE_HARDWARE_SLOTS)
        self._run_0730_cycle(scheduler, controller)

        already_disabled = {
            seg["segment_id"] for seg in _LIVE_HARDWARE_SLOTS if not seg["enabled"]
        }
        redundant = [
            call
            for call in controller.calls
            if not call["enabled"] and call["segment_id"] in already_disabled
        ]
        assert not redundant, f"Re-disabled already-disabled slots: {redundant}"

    def test_read_failure_aborts_the_write(self, scheduler):
        """An unreadable inverter must abort rather than write blind.

        Diffing against nothing would rewrite every segment and reproduce the
        very duplicate-write 500s this fix removes. The failure has to arrive
        as an exception — emptiness cannot carry it, because an inverter with
        no segments programmed is a legitimate, different state.
        """
        controller = _UnreadableController()
        scheduler.strategic_intents = _intents_at_0730()
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=30)

        with pytest.raises(Exception):  # noqa: B017 - transport error propagates
            scheduler.sync_to_hardware(controller, effective_period=30)

        assert not controller.calls, "No segment may be written after a failed read"

    def test_inverter_with_no_segments_is_not_a_read_failure(self, scheduler):
        """An empty segment list is a blank inverter, not a broken read.

        The mock-HA scenarios ship `"time_segments": []` to mean "nothing
        programmed". Treating that as a failure pinned _hardware_write_pending
        forever and broke every MIN E2E run.
        """
        controller = _PreloadedController([])
        scheduler.strategic_intents = _intents_at_0730()
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=30)

        scheduler.sync_to_hardware(controller, effective_period=30)

        written = {
            (call["start_time"], call["end_time"])
            for call in controller.calls
            if call["enabled"]
        }
        assert written, "A blank inverter must receive the whole plan"

    def test_hardware_segments_are_normalized_before_diffing(self, scheduler):
        """The vendor payload is not already in our internal shape.

        growatt_server can report batt_mode as an int. Unnormalized, no segment
        ever matches (so everything is rewritten blind) and the int gets echoed
        straight back to the inverter.
        """
        raw = [
            # 08:00-08:14 grid_first, exactly what the plan wants — as the
            # vendor API can report it, with an int mode.
            {
                "segment_id": 3,
                "start_time": "08:00",
                "end_time": "08:14",
                "batt_mode": 2,
                "enabled": True,
            },
            {
                "segment_id": 5,
                "start_time": "19:30",
                "end_time": "20:29",
                "batt_mode": 2,
                "enabled": True,
            },
        ]
        controller = _PreloadedController(raw)
        self._run_0730_cycle(scheduler, controller)

        rewritten = [
            call
            for call in controller.calls
            if (call["start_time"], call["end_time"]) == ("08:00", "08:14")
        ]
        assert not rewritten, (
            "Rewrote a segment the inverter already holds — the int batt_mode "
            f"was not normalized before comparing. Calls: {rewritten}"
        )

        int_modes = [
            call for call in controller.calls if isinstance(call["batt_mode"], int)
        ]
        assert not int_modes, f"Echoed a raw int batt_mode back: {int_modes}"

    def test_segment_missing_the_enabled_flag_does_not_break_the_diff(self, scheduler):
        """A payload without `enabled` must not blow up mid-diff.

        The diff read it two ways — `.get("enabled", True)` on one line and
        `current["enabled"]` on the next — so an absent key let the entry
        through the first and raised KeyError on the second. Normalizing at the
        read boundary settles it on one default (absent = not programmed, the
        convention the startup path has always used).
        """
        raw = [
            {
                "segment_id": 1,
                "start_time": "19:30",
                "end_time": "20:29",
                "batt_mode": "grid_first",
            },
        ]
        controller = _PreloadedController(raw)

        self._run_0730_cycle(scheduler, controller)  # must not raise

        assert controller.calls, "Diff ran to completion and wrote the plan"

    def test_no_clear_all_banner_when_nothing_is_enabled(self, scheduler, caplog):
        """The clear-everything banner must mean something was cleared.

        Its guard counted all segments read back, and a real read always
        returns 9 slots — so an idle plan logged "CLEARING ALL 9 existing TOU
        segments" immediately followed by "No TOU segment changes needed",
        in the logs this subsystem is diagnosed from.
        """
        controller = _PreloadedController(empty_slot_table())
        scheduler.strategic_intents = ["IDLE"] * 96
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=30)

        with caplog.at_level(logging.WARNING):
            scheduler.sync_to_hardware(controller, effective_period=30)

        assert "CLEARING ALL" not in caplog.text, (
            "Announced clearing segments while none were enabled:\n" f"{caplog.text}"
        )
        assert not controller.calls, "Nothing to clear means nothing to write"


# ── Issue #554: far-future TOU segments must not be rewritten every cycle ─────
#
# Every cycle wrote the whole upcoming plan, so a marginal period flipping in
# and out of the plan rewrote a segment hours before it started. From the
# 2026-08-12 bundle: the 13:45 battery_first window was rewritten 11 times
# between 08:16 and 13:45, and the value finally in effect was the one written
# at 08:16. A segment has no effect on the inverter until it starts, so the
# write can wait until the segment is imminent.
#
# The flip below is that exact one: GRID_CHARGING at period 55 (13:45-13:59)
# vs periods 55-56 (13:45-14:14), as a marginal 15-minute period crosses the
# economic boundary back and forth.


def _grid_charging_at(periods: list[int]) -> list[str]:
    """96-period intent list whose only TOU-producing periods are `periods`.

    LOAD_SUPPORT maps to load_first, the inverter default, which produces no
    TOU segment — so the plan is exactly one battery_first window.
    """
    intents = ["LOAD_SUPPORT"] * 96
    for period in periods:
        intents[period] = "GRID_CHARGING"
    return intents


def _schedule_with(intents: list[str]) -> SimpleNamespace:
    """DPSchedule stand-in exposing only what evaluate_intents reads."""
    return SimpleNamespace(original_dp_results={"strategic_intent": intents})


class TestFarFutureSegmentsAreDeferred:
    """Regression for issue #554."""

    def _cycle(self, scheduler, controller, periods, at_period):
        """One optimization cycle: rebuild the plan, then sync it to hardware."""
        scheduler.strategic_intents = _grid_charging_at(periods)
        scheduler._consolidate_and_convert_with_strategic_intents(
            current_period=at_period
        )
        scheduler.sync_to_hardware(controller, effective_period=at_period)

    def test_marginal_far_future_flip_issues_no_hardware_writes(self, scheduler):
        """The 08:16-12:30 flips all target a window starting at 13:45."""
        controller = _SimulatingController()

        # 08:15 — the plan first settles on the one-period 13:45 window.
        self._cycle(scheduler, controller, [55], 33)

        # 11:00 -> 12:30: the marginal 14:00 period flips in and out. Every
        # one of these cycles is more than an hour before 13:45 starts.
        for at_period, periods in [
            (44, [55, 56]),
            (45, [55]),
            (46, [55]),
            (47, [55, 56]),
            (49, [55]),
            (50, [55, 56]),
        ]:
            self._cycle(scheduler, controller, periods, at_period)

        assert (
            controller.calls == []
        ), "Wrote a segment that does not start for over an hour:\n" + "\n".join(
            f"  {c['start_time']}-{c['end_time']} {c['batt_mode']}"
            for c in controller.calls
        )

    def test_deferred_segment_reaches_hardware_before_it_starts(self, scheduler):
        """Deferral must not lose the write — only delay it.

        The outcome that matters is the inverter's segment table at the moment
        the window becomes active, not which cycle wrote it.
        """
        controller = _SimulatingController()

        for at_period in [33, 44, 47, 50, 52, 54]:  # 08:15 -> 13:30
            self._cycle(scheduler, controller, [55], at_period)

        programmed = {
            (s["start_time"], s["end_time"], s["batt_mode"])
            for s in controller.hardware_segments()
        }
        assert ("13:45", "13:59", "battery_first") in programmed, (
            "The 13:45 window is not on hardware at 13:30, 15 minutes before "
            f"it must take effect. Programmed: {sorted(programmed)}"
        )

    def test_imminent_segment_is_written_without_delay(self, scheduler):
        """Over-gating guard: a window starting now must reach hardware now."""
        controller = _SimulatingController()

        # 13:45 cycle, plan starts charging at 13:45 — already active.
        self._cycle(scheduler, controller, [55], 55)

        programmed = {
            (s["start_time"], s["end_time"], s["batt_mode"])
            for s in controller.hardware_segments()
        }
        assert (
            "13:45",
            "13:59",
            "battery_first",
        ) in programmed, (
            f"Active window never reached hardware. Programmed: {sorted(programmed)}"
        )

    def test_short_dst_day_does_not_raise_late_in_the_evening(self, scheduler):
        """current_period is wall-clock derived and outruns a 92-period day.

        On spring-forward the schedule holds 92 periods, but current_period
        still reaches 95 from 23:00 onwards. The walk-back that finds a
        running segment's true start must not index past the end — the raise
        escapes apply_intents outside _apply_schedule's try, aborting the
        whole optimization cycle rather than degrading.
        """
        spring_forward = ["IDLE"] * 92

        groups = scheduler._group_periods_by_mode(spring_forward, start_period=95)

        assert groups == [], f"Expected no groups past the end of the day: {groups}"

    def test_gate_does_not_fire_merely_because_a_segment_expired(self, scheduler):
        """Expiry alone must not force a cycle.

        The candidate is built at the current period, with expired intervals
        already dropped, while the committed set was built one period earlier
        and still holds the interval that just ended. Comparing them raw makes
        the gate fire on every segment's expiry, costing a hardware read on
        the very API this change exists to relieve.
        """
        # A window at 10:00 plus a later one, so the plan is not emptied by the
        # expiry — an empty remaining plan legitimately trips the separate
        # stale-hardware-cleanup branch, which would mask what is tested here.
        intents = _grid_charging_at([40, 80])  # 10:00-10:14 and 20:00-20:14

        # 10:00 — the window is active and gets committed.
        scheduler.strategic_intents = intents
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=40)
        assert scheduler.active_tou_intervals, "Window should be committed at 10:00"

        # 10:15 — same plan, the window has simply expired.
        should_apply, reason = scheduler.evaluate_intents(
            _schedule_with(intents), current_period=41
        )

        assert (
            not should_apply
        ), f"Gate fired for an expired window with an unchanged plan: {reason!r}"

    def test_gate_fires_when_a_deferred_segment_becomes_imminent(self, scheduler):
        """The write gate must track what actually reaches hardware.

        evaluate_intents decides whether _apply_schedule (and therefore
        sync_to_hardware) runs at all. It diffs the whole daily plan, which is
        unchanged here — so without also comparing the hardware-eligible set,
        a segment deferred at 08:15 is never pushed once the plan stabilises.
        """
        intents = _grid_charging_at([55])

        # 08:15 — plan committed, 13:45 window deferred (starts in 5.5 hours).
        scheduler.strategic_intents = intents
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=33)

        # 13:00 — identical plan, but the 13:45 window is now imminent and has
        # never been written.
        should_apply, reason = scheduler.evaluate_intents(
            _schedule_with(intents), current_period=52
        )

        assert should_apply, (
            "Gate reported no change, so the deferred 13:45 window would never "
            f"be written. Reason given: {reason!r}"
        )

    def test_running_window_is_not_rewritten_every_cycle(self, scheduler):
        """A segment that is already running must not be rewritten as it runs.

        The plan is rebuilt from the current period each cycle, which used to
        truncate an in-progress segment's start_time forward to "now" — so its
        content changed every 15 minutes and the differential update disabled
        and re-wrote it. A stable two-hour window cost 16 writes for zero
        behavioural difference.
        """
        controller = _SimulatingController()
        window = list(range(48, 56))  # 12:00-13:59, unchanged all the way

        # Cycles up to and including the window's start.
        for at_period in range(44, 49):
            self._cycle(scheduler, controller, window, at_period)
        writes_before = len(controller.calls)
        assert writes_before >= 1, "The window should have been programmed by 12:00"

        # 12:15 -> 13:45: the window is running and the plan has not changed.
        for at_period in range(49, 56):
            self._cycle(scheduler, controller, window, at_period)

        assert (
            len(controller.calls) == writes_before
        ), "Rewrote a running window whose plan never changed:\n" + "\n".join(
            f"  {c['start_time']}-{c['end_time']} {c['batt_mode']} "
            f"enabled={c['enabled']}"
            for c in controller.calls[writes_before:]
        )

    def test_running_window_still_reaches_hardware_after_a_restart(self, scheduler):
        """A restart mid-window must still cover the period it is inside.

        Modelled the way a restart actually looks: no previous schedule to
        carry forward, so past periods arrive as IDLE
        (battery_system_manager.py initialises them that way). The walk-back
        therefore stops at the current period and the window is programmed
        truncated to "now" — the accepted cost documented on
        _group_periods_by_mode. What must not happen is the running period
        going uncovered.

        Feeding past periods the intent they were planned with would let this
        pass for a reason the restart path cannot produce.
        """
        controller = _SimulatingController()

        restart_intents = ["IDLE"] * 96  # nothing known about the past
        for period in range(52, 56):  # 13:00-13:59, the rest of the window
            restart_intents[period] = "GRID_CHARGING"
        scheduler.strategic_intents = restart_intents
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=52)
        scheduler.sync_to_hardware(controller, effective_period=52)

        covering = [
            s
            for s in controller.hardware_segments()
            if s["batt_mode"] == "battery_first"
            and s["start_time"] <= "13:00"
            and s["end_time"] >= "13:00"
        ]
        assert covering, (
            "The period the restart landed inside is not covered by any "
            f"enabled segment: {controller.hardware_segments()}"
        )

    def _seeded_controller(self, start, end, mode):
        controller = _SimulatingController()
        controller.slots[1] = {
            "segment_id": 1,
            "batt_mode": mode,
            "start_time": start,
            "end_time": end,
            "enabled": True,
        }
        return controller

    def test_far_future_segment_already_on_hardware_is_left_alone(self, scheduler):
        """Deferral must not clear a far-future segment the plan agrees with.

        Deferring only the *update* side would make the diff read the segment
        as unplanned — because the plan's own copy is not eligible yet — and
        disable it, only to write it back later. That is the churn this change
        exists to remove, in the opposite direction.
        """
        controller = self._seeded_controller("20:00", "20:59", "battery_first")

        # 12:00, eight hours before the window starts. The plan contains it.
        self._cycle(scheduler, controller, [80, 81, 82, 83], 48)

        assert (
            controller.calls == []
        ), "Touched a correctly-programmed segment eight hours early:\n" + "\n".join(
            f"  {c['start_time']}-{c['end_time']} {c['batt_mode']} "
            f"enabled={c['enabled']}"
            for c in controller.calls
        )

    def test_unplanned_far_future_segment_is_cleared(self, scheduler):
        """A segment the plan does not contain must still be disabled.

        Deferral applies to updates only. The plan below is non-empty but
        omits the 20:00 window, so this exercises the differential branch —
        an empty plan would trip the clear-everything branch instead and prove
        nothing about it.
        """
        controller = self._seeded_controller("20:00", "20:59", "battery_first")

        # Plan has a 12:00 window and nothing at 20:00.
        self._cycle(scheduler, controller, [48, 49, 50, 51], 48)

        programmed = {
            (s["start_time"], s["end_time"]) for s in controller.hardware_segments()
        }
        assert ("20:00", "20:59") not in programmed, (
            "Unplanned window left enabled on hardware. "
            f"Programmed: {sorted(programmed)}"
        )

    def test_deferred_segment_is_not_flagged_pending_write(self, scheduler):
        """Deferral is the normal state, not a warning.

        pending_write means "should be on hardware by now, but is not" — the
        dashboard paints it amber and hides the mode badge. A segment that is
        merely too far out has nothing wrong with it, and flagging every one
        of them would leave most of the day looking broken.
        """
        scheduler.strategic_intents = _grid_charging_at([28, 52, 72])
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=8)

        flagged = [
            (s["start_time"], s["end_time"])
            for s in scheduler.get_all_tou_segments(current_period=8)
            if not s.get("is_default") and s.get("pending_write")
        ]

        assert (
            flagged == []
        ), f"Deferred segments flagged as pending write at 02:00: {flagged}"

    def test_display_and_write_paths_agree_on_what_is_deferred(self, scheduler):
        """Both sides must measure the horizon from the same instant.

        Eligibility is decided from the period floor, while get_all_tou_segments
        falls back to the raw wall clock when no period is passed (as the API
        does). A segment inside the band between the two is deferred by the
        write path but not by the display path, so it lands back in the amber
        "Pending Write" state this change exists to clear.

        Only reachable for a segment whose start is off the 15-minute grid —
        one read back from hardware rather than produced by the optimizer,
        since _period_to_time only ever yields :00/:15/:30/:45.
        """
        scheduler.active_tou_intervals = []
        scheduler.tou_intervals = [
            {
                "segment_id": 1,
                "start_time": "08:59",
                "end_time": "09:59",
                "batt_mode": "battery_first",
                "enabled": True,
            }
        ]

        # 08:14 — period 32 (08:00). Write path: 539 > 480 + 45, deferred.
        real_now = time_utils.now
        try:
            time_utils.now = lambda: real_now().replace(
                hour=8, minute=14, second=0, microsecond=0
            )
            flagged = [
                s["start_time"]
                for s in scheduler.get_all_tou_segments()
                if not s.get("is_default") and s.get("pending_write")
            ]
        finally:
            time_utils.now = real_now

        assert flagged == [], (
            "Segment the write path defers was flagged pending by the display "
            f"path: {flagged}"
        )

    def test_lost_segment_on_hardware_is_detected(self, scheduler):
        """A segment that vanishes from the inverter must be noticed.

        The write gate compares plan against plan, so once a segment is
        written and the plan stops changing, nothing looks at the inverter
        again. Before deferral the in-progress segment was renamed every
        cycle, which forced a read and repaired drift by accident; that is
        gone, and issue #551 showed this table really does drift.
        """
        controller = self._seeded_controller("03:00", "04:59", "battery_first")
        scheduler.strategic_intents = _grid_charging_at(list(range(12, 20)))
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=12)

        controller.calls.clear()
        scheduler.reconcile_hardware(controller, 13)
        assert controller.calls == [], "Wrote while hardware already matched the plan"

        controller.slots.clear()  # inverter loses the table mid-window
        scheduler.reconcile_hardware(controller, 14)

        programmed = {
            (s["start_time"], s["end_time"]) for s in controller.hardware_segments()
        }
        assert ("03:00", "04:59") in programmed, (
            "Lost segment stayed lost — the window would run load_first for "
            f"the rest of its life with nothing in the logs. Got {programmed}"
        )

    def test_orphan_segment_is_cleared_on_a_quiet_cycle(self, scheduler):
        """An unplanned segment the inverter holds must be turned off.

        Detecting only *missing* segments covers half of #551. The other half
        is the inverter restoring a slot the plan does not contain — and with
        writes now deferred, the cycle that would have disabled it may not run
        for hours, so the battery follows a window nobody planned.
        """
        controller = self._seeded_controller("18:00", "19:59", "grid_first")
        scheduler.strategic_intents = _grid_charging_at(list(range(12, 20)))
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=12)

        scheduler.reconcile_hardware(controller, 13)

        programmed = {
            (s["start_time"], s["end_time"]) for s in controller.hardware_segments()
        }
        assert (
            "18:00",
            "19:59",
        ) not in programmed, (
            f"Unplanned window left running on the battery: {sorted(programmed)}"
        )

    def test_reconciliation_reads_the_inverter_once(self, scheduler):
        """One read per cycle, and it is the one the writes are diffed against.

        A separate drift check with its own read doubles the load on the
        endpoint that #554 exists to relieve — the same endpoint the issue
        reports returning 500s under load.
        """
        controller = _SimulatingController()
        controller.reads = 0
        inner = controller.read_inverter_time_segments

        def counting():
            controller.reads += 1
            return inner()

        controller.read_inverter_time_segments = counting

        scheduler.strategic_intents = _grid_charging_at(list(range(12, 20)))
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=12)
        scheduler.reconcile_hardware(controller, 12)

        assert controller.reads == 1, f"Read the inverter {controller.reads} times"

    def test_reconciliation_leaves_a_deferred_segment_alone(self, scheduler):
        """A quiet cycle must stay quiet.

        Reconciliation runs on every cycle, so if it treated a deliberately
        unwritten far-future segment as something to repair it would rewrite
        on every cycle and undo the whole change.
        """
        controller = _SimulatingController()
        scheduler.strategic_intents = _grid_charging_at([48, 49, 50, 51, 80, 81])
        scheduler._consolidate_and_convert_with_strategic_intents(current_period=48)
        scheduler.sync_to_hardware(controller, effective_period=48)

        controller.calls.clear()
        scheduler.reconcile_hardware(controller, 48)

        assert controller.calls == [], (
            "Reconciliation rewrote on a quiet cycle: "
            f"{[(c['start_time'], c['end_time']) for c in controller.calls]}"
        )

    def test_deferred_planned_segment_keeps_its_hardware_slot(self, scheduler):
        """A planned segment spared by the disable diff must keep its slot.

        The disable side spares hardware segments the plan still wants, even
        when they are too far out to be rewritten. Slot assignment has to
        agree: if it treats that slot as free, the next eligible segment is
        written straight over the top and the window is lost with no disable
        ever issued — silent, and worse than the churn this change removes.
        """
        controller = self._seeded_controller("20:00", "20:59", "battery_first")

        # 12:00. The plan holds both windows; only 12:00 is eligible to write.
        self._cycle(scheduler, controller, [48, 49, 50, 51, 80, 81, 82, 83], 48)

        programmed = {
            (s["start_time"], s["end_time"]) for s in controller.hardware_segments()
        }
        assert ("20:00", "20:59") in programmed, (
            "Planned 20:00 window was evicted from its slot by an imminent "
            f"write. Programmed: {sorted(programmed)}"
        )
        assert (
            "12:00",
            "12:59",
        ) in programmed, (
            f"Imminent 12:00 window never reached hardware. {sorted(programmed)}"
        )

    def test_slots_are_reclaimed_furthest_first_when_hardware_is_full(self, scheduler):
        """Protecting planned slots must not deadlock a full slot table.

        On the first cycle after an upgrade the inverter can still hold nine
        segments written by the old always-write behaviour. If every one of
        them is protected, an imminent segment needing a slot would have none
        left. The furthest-out segment yields its slot: it has the most cycles
        remaining to be written again before it takes effect.
        """
        # Nine single-period windows, each separated by an idle period so they
        # stay distinct — consecutive periods of the same mode would merge into
        # one interval and never fill the slot table.
        far_future = [60, 62, 64, 66, 68, 70, 72, 74, 76]  # 15:00 .. 19:00

        def window(period):
            start = f"{period // 4:02d}:{(period % 4) * 15:02d}"
            end_minute = (period % 4) * 15 + 14
            return start, f"{period // 4:02d}:{end_minute:02d}"

        controller = _SimulatingController()
        for slot, period in enumerate(far_future, start=1):
            start, end = window(period)
            controller.slots[slot] = {
                "segment_id": slot,
                "batt_mode": "battery_first",
                "start_time": start,
                "end_time": end,
                "enabled": True,
            }

        # Plan keeps all nine of those windows and adds an imminent one.
        self._cycle(scheduler, controller, [48, 49, 50, 51, *far_future], 48)

        programmed = {
            (s["start_time"], s["end_time"]) for s in controller.hardware_segments()
        }
        assert ("12:00", "12:59") in programmed, (
            "Imminent window could not be programmed against a full slot "
            f"table. Programmed: {sorted(programmed)}"
        )
        assert window(76) not in programmed, (
            "Expected the furthest-out window (19:00) to yield its slot. "
            f"Programmed: {sorted(programmed)}"
        )
        assert window(60) in programmed, (
            "Nearest far-future window (15:00) should have been kept. "
            f"Programmed: {sorted(programmed)}"
        )


# ── Issue #589: gate on when a change takes effect, not on when it starts ─────
#
# #554 gates eligibility on a segment's *start*, so a window that is already
# running is eligible on every cycle forever. The DP keeps nudging its *end* as
# it re-solves — 02:00-05:59, then 06:59, then back — and each nudge is written
# at once even though it cannot take effect for hours. That is the residual
# overhead measured on #554: +8 writes against a floor of 4 on a four-window
# day, all of it end-boundary churn.
#
# The rule below generalises #554's rather than replacing it: write when the
# earliest period at which the programmed table and the plan would execute
# different modes falls within the horizon. A not-yet-started segment first
# diverges at its start, so #554's behaviour is unchanged by construction.


class TestRunningWindowEndChangesWait:
    """Regression for issue #589."""

    def _cycle(self, scheduler, controller, periods, at_period):
        """One optimization cycle: rebuild the plan, then sync it to hardware."""
        scheduler.strategic_intents = _grid_charging_at(periods)
        scheduler._consolidate_and_convert_with_strategic_intents(
            current_period=at_period
        )
        scheduler.sync_to_hardware(controller, effective_period=at_period)

    def test_moving_the_end_of_a_running_window_issues_no_writes(self, scheduler):
        """The end moves hours ahead of where it can matter, so it can wait.

        02:00-05:59 is running from 02:00. The marginal 06:00-06:59 hour flips
        in and out of the plan across the 02:15-03:45 cycles. Every one of
        those flips first takes effect at 06:00, more than two hours out.
        """
        controller = _SimulatingController()
        short = list(range(8, 24))  # 02:00-05:59
        long = list(range(8, 28))  # 02:00-06:59

        # 02:00 — the window is running and gets programmed.
        self._cycle(scheduler, controller, short, 8)
        writes_after_start = len(controller.calls)
        assert writes_after_start >= 1, "The running window should be programmed"

        # 02:15 -> 03:45 — the end flips back and forth, always hours away.
        for at_period, periods in [
            (9, long),
            (10, short),
            (11, long),
            (12, short),
            (13, long),
            (14, short),
            (15, long),
        ]:
            self._cycle(scheduler, controller, periods, at_period)

        assert len(controller.calls) == writes_after_start, (
            "Rewrote a running window for an end change that cannot take "
            "effect for hours:\n"
            + "\n".join(
                f"  {c['start_time']}-{c['end_time']} {c['batt_mode']} "
                f"enabled={c['enabled']}"
                for c in controller.calls[writes_after_start:]
            )
        )

    def test_moved_end_reaches_hardware_before_it_takes_effect(self, scheduler):
        """Deferral must delay the write, never lose it.

        The outcome that matters is the inverter's table at the moment the
        extension would start running, not which cycle wrote it.
        """
        controller = _SimulatingController()
        long = list(range(8, 28))  # 02:00-06:59

        # 02:00 committed short, then extended and left extended. Cycles run
        # up to 05:30, half an hour before the extension takes effect.
        self._cycle(scheduler, controller, list(range(8, 24)), 8)
        for at_period in range(9, 23):  # 02:15 -> 05:30
            self._cycle(scheduler, controller, long, at_period)

        programmed = {
            (s["start_time"], s["end_time"], s["batt_mode"])
            for s in controller.hardware_segments()
        }
        assert ("02:00", "06:59", "battery_first") in programmed, (
            "The extended window is not on hardware at 05:30, 30 minutes "
            f"before its new end must take effect. Programmed: "
            f"{sorted(programmed)}"
        )

    def test_a_deferred_end_change_leaves_the_running_window_programmed(
        self, scheduler
    ):
        """Deferring the update must not clear what is already running.

        The plan wants 02:00-06:59 while hardware holds 02:00-05:59. The
        disable side sees a programmed segment the plan no longer contains
        verbatim — it must recognise it as the version deferral chose to keep,
        not clear it and leave the battery unmanaged for the rest of the hour.
        """
        controller = _SimulatingController()

        self._cycle(scheduler, controller, list(range(8, 24)), 8)
        self._cycle(scheduler, controller, list(range(8, 28)), 9)

        programmed = {
            (s["start_time"], s["end_time"], s["batt_mode"])
            for s in controller.hardware_segments()
        }
        assert ("02:00", "05:59", "battery_first") in programmed, (
            "Disabled the running window while deferring its end change. "
            f"Programmed: {sorted(programmed)}"
        )

    def test_a_mode_change_inside_a_running_window_is_written_at_once(self, scheduler):
        """Over-gating guard: divergence *now* is not deferrable.

        A running window whose mode the plan changes diverges at the current
        period, so the horizon is satisfied immediately and the write must go
        out on this cycle.
        """
        controller = _SimulatingController()

        # 02:00-05:59 battery_first, running.
        self._cycle(scheduler, controller, list(range(8, 24)), 8)

        # 02:15 — the plan drops charging from here on. The remaining window
        # is gone from the plan, so the programmed segment now disagrees with
        # the plan at 02:15 itself.
        self._cycle(scheduler, controller, [], 9)

        programmed = {
            (s["start_time"], s["end_time"], s["batt_mode"])
            for s in controller.hardware_segments()
        }
        assert not programmed, (
            "A window the plan abandoned mid-run stayed on hardware. "
            f"Programmed: {sorted(programmed)}"
        )
