"""Growatt MIN inverter controller.

This module converts strategic intents from the DP algorithm into Growatt MIN-specific
Time of Use (TOU) intervals while meeting strict inverter hardware requirements.

PROBLEM STATEMENT & REQUIREMENTS:

Growatt inverters have strict hardware requirements that create operational challenges:
1. TOU segments must be in chronological order without overlaps (hardware requirement)
2. Maximum 9 TOU segments supported by inverter hardware
3. Frequent inverter writes should be minimized to reduce hardware stress
4. Past and future strategic periods can change dynamically throughout the day, but we only update future segments
5. Past time intervals should not be modified (unnecessary writes)
6. All segments must have unique, sequential segment IDs (1, 2, 3...)
7. Segment durations must align with full hour boundaries (e.g., 20:00-20:59)
8. Inverter default behavior is load_first - only create TOU segments to override this default
9. Only strategic periods (battery_first, grid_first) need explicit TOU segments
10. IDLE periods automatically use load_first behavior (no TOU segment required)

OBJECTIVES:

1. ZERO OVERLAPS: Guarantee no overlapping time intervals
2. CHRONOLOGICAL ORDER: Ensure segments are always in time sequence (1,2,3...)
3. MINIMAL WRITES: Only update future segments, preserve past segments unchanged
4. HARDWARE COMPATIBILITY: Respect 9-segment limit and ID requirements
5. DP ALIGNMENT: Use full hour boundaries to align with DP algorithm output

APPROACH:

Strategic intents (from DP algorithm) are converted to battery modes:
- GRID_CHARGING → battery_first (AC charging enabled)
- SOLAR_STORAGE → load_first (solar serves home first, excess to battery)
- LOAD_SUPPORT → load_first (discharging priority)
- BATTERY_EXPORT → grid_first (export priority)
- IDLE → load_first (normal operation)

ALGORITHM:

1. Group consecutive hours by battery mode
2. Create TOU intervals only for non-"load_first" modes (battery_first, grid_first)
3. Use full hour boundaries (e.g., 20:00-20:59) to align with DP algorithm output
4. Preserve past intervals to minimize inverter writes
5. Assign sequential segment IDs to avoid conflicts

IMPLEMENTATION VALIDATION:

Requirements compliance check:
✓ Zero overlaps: Uses hour boundaries (20:00-20:59, 21:00-21:59) - no overlap possible
✓ Chronological order: Final intervals sorted by start_time, sequential IDs assigned 1,2,3...
✓ Minimal writes: Preserves past intervals unchanged
✓ Hardware compatibility: Limits to max 9 segments, ensures unique sequential IDs
✓ DP alignment: Uses exact hour boundaries from DP algorithm
✓ Disabled segments are load_first: Time periods without TOU segments default to load_first
✓ Corruption recovery: Nuclear reset approach when chaos detected

CORRECT APPROACH: Only create TOU segments for strategic periods (battery_first, grid_first).
All other time periods automatically use load_first as inverter default behavior.

ROBUST RECOVERY: When TOU corruption detected (overlaps, wrong order, duplicates):
1. Log corrupted state for debugging
2. Clear all corrupted TOU intervals immediately
3. If strategic intents available, rebuild schedule immediately
4. System instantly returns to clean, working state

"""

import io
import logging
from typing import ClassVar

from . import time_utils
from .dp_schedule import DPSchedule
from .health_check import perform_health_check
from .inverter_controller import InverterController
from .settings import BatterySettings

logger = logging.getLogger(__name__)

# TOU segment times are capped at 23:59 (_groups_to_tou_intervals), so a mode
# timeline over the segment table is exactly this long on every day, including
# the DST ones where the schedule itself is not.
TOU_PERIODS = time_utils.PERIODS_PER_DAY_NORMAL


class GrowattMinController(InverterController):
    """Creates Growatt MIN inverter schedules using strategic intents from DP algorithm.

    This class manages the conversion between strategic intents and Growatt MIN-specific
    Time of Use (TOU) intervals. It uses the strategic reasoning captured at decision
    time in the DP algorithm rather than analyzing energy flows afterward.

    Strategic Intent → Inverter Behavior:

    GRID_CHARGING (battery_first, grid_charge=True, charge=100, discharge=0):
      Purpose: Charge battery from grid during cheap hours for later arbitrage.
      Flow: Grid → battery (AC charging). Grid → home. Battery does not discharge.

    SOLAR_STORAGE (load_first, grid_charge=False, charge=100, discharge=0):
      Purpose: Store excess solar for expensive evening hours.
      Flow: Solar → home first, excess solar → battery. Grid covers any shortfall.
      Battery does not discharge — energy preserved for later LOAD_SUPPORT.
      Uses load_first so solar serves home directly, avoiding unnecessary grid import
      that battery_first would cause by routing solar to battery first.

    LOAD_SUPPORT (load_first, grid_charge=False, charge=0, discharge=100):
      Purpose: Discharge stored energy to offset expensive grid consumption.
      Flow: Battery → home. Solar → home. Grid covers remainder if needed.
      Battery does not charge — energy is being spent, not accumulated.

    BATTERY_EXPORT (grid_first, grid_charge=False, charge=0, discharge=100):
      Purpose: Export stored energy to grid during high sell-price hours.
      Flow: Battery → grid (export). Solar → grid. Grid may still serve home.

    IDLE (load_first, grid_charge=False, charge=100, discharge=0):
      Purpose: Normal operation when no active strategy is needed.
      Flow: Solar → home, excess solar → battery. Grid covers shortfall.
      Battery does not discharge. Similar to SOLAR_STORAGE but without
      active optimization intent.

    Design rationale — why SOLAR_STORAGE and IDLE use the same inverter settings:

    SOLAR_STORAGE and IDLE produce identical inverter behavior (load_first, charge
    enabled, no discharge). The distinction is semantic: the DP algorithm uses
    SOLAR_STORAGE when it actively decides to accumulate energy, and IDLE when no
    strategy is needed. At the inverter level, load_first is correct for both because:

    1. Solar energy serving the home directly is always >= the value of routing it
       through the battery (which incurs cycle cost and conversion losses).
    2. If prices are cheap enough to justify prioritizing battery over home load,
       the DP algorithm should use GRID_CHARGING instead (battery_first + grid_charge),
       which charges from both solar and grid simultaneously.
    3. battery_first without grid_charge causes the inverter to route solar to the
       battery first, forcing unnecessary grid import to serve the home — a strictly
       worse outcome when there is excess solar.

    Therefore only GRID_CHARGING uses battery_first mode. All other intents that
    allow charging (SOLAR_STORAGE, IDLE) use load_first to ensure solar serves the
    home before excess flows to the battery.
    """

    # How far ahead of its start time a TOU segment becomes eligible to be
    # written to hardware. Cycles run at :00/:15/:30/:45, so at 45 minutes a
    # segment is eligible on four of them before it takes effect.
    #
    # Those are opportunities to repair, not four attempts: the segment is
    # written on the first of them and the rest are no-ops while the plan and
    # the inverter agree. A write that raises is retried via
    # _hardware_write_pending; one that vanishes without raising is caught by
    # reconcile_hardware, which re-runs the sync on every quiet cycle and is
    # what makes the remaining cycles worth having. Lowering this shrinks the
    # window for both, so do not lower it without re-checking those two paths.
    #
    # It also caps how many segments can be eligible at once, floor(45/15) + 1
    # = 4, comfortably under the 9 hardware slots.
    WRITE_HORIZON_MINUTES = 45

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the MIN controller with required battery settings for power calculations."""
        super().__init__(battery_settings)

        self.max_intervals = 9  # Growatt supports up to 9 TOU intervals
        self.detailed_intervals = []  # For overview display
        self._active_tou_intervals: list[dict] = (
            []
        )  # Subset of tou_intervals written to hardware (max 9)
        self.current_hour = 0  # Track current hour (0-23) for TOU schedule boundaries

        # Fixed time slots configuration (9 slots, ~2h40m each)

    @property
    def active_tou_intervals(self) -> list[dict]:
        """Return the subset of TOU intervals currently written to hardware (max 9)."""
        return self._active_tou_intervals

    @active_tou_intervals.setter
    def active_tou_intervals(self, value: list[dict]) -> None:
        self._active_tou_intervals = value

    def _group_periods_by_mode(
        self, intents: list[str], start_period: int = 0
    ) -> list[dict]:
        """Group consecutive 15-min periods by their battery mode.

        This is the core of the new 15-minute resolution TOU scheduling.
        Instead of aggregating to hours, we work directly with periods.

        Args:
            intents: Strategic intents to group (the candidate being built —
                may be self.strategic_intents, or a different candidate's
                intents when called from _build_candidate for comparison).
            start_period: Period to start from (0-95), typically current_period

        The group covering start_period is reported from its *true* start, not
        from start_period. A segment that is already running keeps the same
        start_time on every cycle, so the differential update recognises it as
        unchanged. Clamping it to "now" instead renamed it every 15 minutes,
        and each rename cost a disable plus a write for no behavioural
        difference — 16 writes for a stable two-hour window (issue #554).

        Returns:
            List of period groups:
            [
                {
                    'mode': 'battery_first'|'grid_first'|'load_first',
                    'start_period': int,
                    'end_period': int (inclusive),
                    'intents': list[str],  # Original intents for debugging
                },
                ...
            ]
        """
        if not intents:
            return []

        # current_period is derived from the wall clock, so on a spring-forward
        # day it reaches 95 while the schedule holds only 92 periods. There is
        # nothing left to group past the end of the day.
        if start_period >= len(intents):
            return []

        def mode_at(period: int) -> str:
            return self.INTENT_TO_MODE.get(intents[period], "load_first")

        # Walk back over periods the running segment already covers.
        #
        # This relies on past periods carrying forward the intents that were
        # actually planned for them (battery_system_manager.py). On the first
        # cycle after a restart there is no previous schedule to carry, so past
        # periods are initialised to IDLE -> load_first and the walk-back stops
        # immediately: a window already running is truncated to "now" for that
        # one cycle, costing a disable plus a rewrite. It is stable from the
        # next cycle on, because that cycle carries forward this one's intents.
        # Reconstructing the missing past from actuals is deliberately not done
        # — inferring intent from measured export feeds back into the plan.
        while start_period > 0 and mode_at(start_period - 1) == mode_at(start_period):
            start_period -= 1

        groups = []
        current_mode = None
        group_start = None
        group_intents = []

        num_periods = len(intents)

        for period in range(start_period, num_periods):
            intent = intents[period]
            mode = self.INTENT_TO_MODE.get(intent, "load_first")

            if mode != current_mode:
                # Save previous group if exists
                if current_mode is not None:
                    groups.append(
                        {
                            "mode": current_mode,
                            "start_period": group_start,
                            "end_period": period - 1,
                            "intents": group_intents,
                        }
                    )

                # Start new group
                current_mode = mode
                group_start = period
                group_intents = [intent]
            else:
                group_intents.append(intent)

        # Add final group
        if current_mode is not None and group_start is not None:
            groups.append(
                {
                    "mode": current_mode,
                    "start_period": group_start,
                    "end_period": num_periods - 1,
                    "intents": group_intents,
                }
            )

        return groups

    def _groups_to_tou_intervals(self, groups: list[dict]) -> list[dict]:
        """Convert period groups to Growatt TOU intervals.

        Only creates intervals for non-default modes (battery_first, grid_first).
        load_first is the inverter default and doesn't need explicit TOU segments.

        Args:
            groups: List of period groups from _group_periods_by_mode()

        Returns:
            List of TOU intervals ready for Growatt
        """
        intervals = []
        segment_id = 1

        for group in groups:
            # Skip load_first - it's the inverter default
            if group["mode"] == "load_first":
                continue

            start_hour, start_minute = self._period_to_time(group["start_period"])
            end_hour, end_minute = self._period_to_time(group["end_period"])
            # End minute should be the last minute of the period (14, 29, 44, or 59)
            end_minute = end_minute + 14

            # Handle DST fall-back: periods >= 96 produce hour >= 24
            # Skip segments that start beyond 23:59 (can't represent in TOU)
            if start_hour >= 24:
                logger.warning(
                    "Skipping DST fall-back segment starting at hour %d (beyond 23:59)",
                    start_hour,
                )
                continue

            # Cap end time to 23:59
            if end_hour >= 24:
                end_hour = 23
                end_minute = 59

            # Summarize intents for logging
            intent_counts: dict[str, int] = {}
            for intent in group["intents"]:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
            intent_summary = ", ".join(
                f"{intent}({count})"
                for intent, count in sorted(intent_counts.items(), key=lambda x: -x[1])
            )

            interval = {
                "segment_id": segment_id,
                "batt_mode": group["mode"],
                "start_time": f"{start_hour:02d}:{start_minute:02d}",
                "end_time": f"{end_hour:02d}:{end_minute:02d}",
                "enabled": True,
                "strategic_intent": intent_summary,
            }
            intervals.append(interval)
            segment_id += 1

            logger.info(
                "TOU segment #%d: %s-%s (%s) from %d periods: %s",
                interval["segment_id"],
                interval["start_time"],
                interval["end_time"],
                interval["batt_mode"],
                len(group["intents"]),
                intent_summary,
            )

        return intervals

    def _periods_of(self, interval: dict) -> range:
        """The 15-minute periods an interval covers, end inclusive."""
        return range(
            self._time_to_minutes(interval["start_time"]) // 15,
            self._time_to_minutes(interval["end_time"]) // 15 + 1,
        )

    def _programmed_baseline(self, current_minutes: int) -> list[dict]:
        """The segments we believe the inverter is currently running.

        Disabled entries are dropped, not carried: the inverter reports its
        unused slots as disabled ones, and initialize_from_tou_segments seeds
        active_tou_intervals straight from that read. Treating them as
        programmed would let a stale slot's mode be carried over in place of
        the plan's whenever a write is deferred — and since the carried entry
        lands back in active_tou_intervals, it would then be its own evidence
        on the next cycle and never wash out.

        Reading our own committed set rather than the hardware is deliberate:
        the write path already diffs against a real read (#552) and
        reconcile_hardware repairs a genuine divergence (#554), so a second
        read would only add load to the endpoint this gate exists to relieve.

        The write path and the dashboard both need this, and must not compute
        it two ways — a fix applied to one copy would silently put a segment
        back in the amber "Pending Write" state (#589).
        """
        return [
            segment
            for segment in self.active_tou_intervals
            if segment.get("enabled", True)
            and self._time_to_minutes(segment["end_time"]) >= current_minutes
        ]

    def _modes_by_period(self, intervals: list[dict]) -> list[str]:
        """Which mode each period of the day would execute under `intervals`.

        Periods no interval covers run the inverter default, which is what an
        absent TOU segment means — so this is directly comparable between the
        plan and what is programmed, including where one has a segment and the
        other has none.
        """
        modes = ["load_first"] * TOU_PERIODS
        for interval in intervals:
            if not interval.get("enabled", True):
                continue
            for period in self._periods_of(interval):
                if 0 <= period < TOU_PERIODS:
                    modes[period] = interval["batt_mode"]
        return modes

    def _first_divergence_period(
        self,
        interval: dict,
        plan_modes: list[str],
        programmed_modes: list[str],
        overlapping: list[dict],
        from_period: int,
    ) -> int | None:
        """The earliest period at or after `from_period` where the programmed
        table and the plan would execute different modes, over the stretch of
        day this interval is responsible for.

        That stretch is the interval's own span plus the span of every
        programmed segment it overlaps — because the disagreement an interval
        has to fix is not always inside it. A window whose end moved back from
        06:59 to 05:59 is identical to what is programmed everywhere it
        covers; the disagreement is the hour beyond it that the inverter still
        holds.

        None means the plan and the inverter already agree over that stretch,
        so there is nothing this interval needs to write.
        """
        periods = set(self._periods_of(interval))
        for segment in overlapping:
            periods |= set(self._periods_of(segment))

        for period in sorted(periods):
            if period < from_period or period >= TOU_PERIODS:
                continue
            if plan_modes[period] != programmed_modes[period]:
                return period
        return None

    def _write_is_due(
        self,
        interval: dict,
        plan_modes: list[str],
        programmed: list[dict],
        programmed_modes: list[str],
        current_period: int,
    ) -> tuple[bool, list[dict]]:
        """Is this planned interval's write due on this cycle?

        Due means the plan and the programmed table first disagree, over the
        stretch this interval is responsible for, no more than
        WRITE_HORIZON_MINUTES from now — or they do not disagree at all, in
        which case writing it is a no-op and there is nothing to postpone.

        Also returns the programmed segments this interval overlaps, which is
        what stays on the inverter while its write waits.

        The write path and the dashboard both ask this question, and they have
        to answer it the same way: a segment the write path deferred but the
        dashboard called pending is painted amber with a "Pending Write"
        warning for a segment that is simply not due yet.
        """
        covered = set(self._periods_of(interval))
        overlapping = [
            segment
            for segment in programmed
            if covered & set(self._periods_of(segment))
        ]
        divergence = self._first_divergence_period(
            interval, plan_modes, programmed_modes, overlapping, current_period
        )
        horizon_periods = self.WRITE_HORIZON_MINUTES // 15
        due = divergence is None or divergence <= current_period + horizon_periods
        return due, overlapping

    def _select_hardware_intervals(
        self,
        intervals: list[dict],
        current_period: int,
        previously_programmed: list[dict],
    ) -> list[dict]:
        """Select what the inverter's segment table should hold right now.

        This returns the *hardware target*: what we intend the inverter to be
        programmed with on this cycle, which is not simply the slice of the
        plan that fits. Two things keep a planned interval out of it:

        - the earliest period where the programmed table and the plan would
          execute different modes is more than WRITE_HORIZON_MINUTES away, or
        - the first 9 entries already fill the hardware slots.

        Gating on when a change takes *effect* rather than on when a segment
        *starts* (issue #589) strictly generalises #554's rule. A not-yet-
        started segment first diverges from an inverter that does not hold it
        at its own start, so far-future segments defer exactly as before. What
        it adds is the running window: the DP keeps nudging a live segment's
        end as it re-solves, and under the start-based rule each nudge was
        written at once even though it could not take effect for hours. On the
        four-window day measured for #589 that churn was the whole residual —
        12 writes against a floor of 4.

        Deferring an *update* means the previous version stays on the inverter,
        so that version is what this returns in its place. active_tou_intervals
        therefore keeps describing what hardware is meant to hold, which is
        what the disable path and reconciliation both read it as.

        Writing later than this would break correctness; writing earlier is
        only ever a bet that the plan will not change again. Every rewrite
        costs a cloud API call, and Growatt 500s on this endpoint under load.

        Args:
            intervals: All TOU intervals (may exceed max_intervals).
            current_period: Current 15-minute period (0-95).
            previously_programmed: What the inverter is believed to hold, from
                _programmed_baseline. Normally this function's own output from
                an earlier cycle, so the selection is a recurrence rather than
                a pure function of the plan — passed in rather than read off
                self so that is visible at the call site.

        Returns:
            List of up to 9 intervals for hardware, each either planned or the
            already-programmed version of a planned interval.
        """
        # Calculate current time in minutes from the period
        current_hour = current_period // 4
        current_minute = (current_period % 4) * 15
        current_minutes = current_hour * 60 + current_minute

        plan_modes = self._modes_by_period(intervals)
        programmed_modes = self._modes_by_period(previously_programmed)

        non_expired: list[dict] = []
        deferred: list[dict] = []
        for interval in intervals:
            if self._time_to_minutes(interval["end_time"]) < current_minutes:
                continue

            due, overlapping = self._write_is_due(
                interval,
                plan_modes,
                previously_programmed,
                programmed_modes,
                current_period,
            )
            if due:
                non_expired.append(interval)
            else:
                deferred.append(interval)
                # Keep what the inverter already holds over this stretch, so
                # the disable path does not read it as unplanned and clear a
                # window that is running correctly.
                #
                # Copied, not aliased: _assign_hardware_slots stamps
                # segment_id into whatever this returns, and these dicts are
                # still owned by the previous cycle's active_tou_intervals —
                # and, at startup, by tou_intervals as well.
                for segment in overlapping:
                    if segment not in non_expired:
                        non_expired.append(segment.copy())

        if deferred:
            logger.info(
                "TOU DEFERRED: %d interval(s) whose first difference from the "
                "programmed table is more than %d minutes out; each is written "
                "on the cycle that brings that difference within range",
                len(deferred),
                self.WRITE_HORIZON_MINUTES,
            )
            # Per-interval detail at DEBUG: deferral is the normal state on
            # every cycle, so at INFO this alone would be thousands of lines a
            # day in the logs and debug bundles this system is diagnosed from.
            for interval in deferred:
                logger.debug(
                    "  DEFERRED: %s-%s (%s)",
                    interval["start_time"],
                    interval["end_time"],
                    interval["batt_mode"],
                )

        # Sort chronologically and take first 9
        non_expired.sort(key=lambda x: x["start_time"])
        hardware_intervals = non_expired[: self.max_intervals]

        if len(non_expired) > self.max_intervals:
            pending_count = len(non_expired) - self.max_intervals
            logger.info(
                "TOU CASCADING: %d total non-expired intervals, "
                "programming %d to hardware, %d pending write",
                len(non_expired),
                len(hardware_intervals),
                pending_count,
            )
            for pending in non_expired[self.max_intervals :]:
                logger.info(
                    "  PENDING: %s-%s (%s) - will be programmed when a slot frees up",
                    pending["start_time"],
                    pending["end_time"],
                    pending["batt_mode"],
                )
        else:
            logger.info(
                "TOU hardware: %d intervals selected (all fit within %d-slot limit)",
                len(hardware_intervals),
                self.max_intervals,
            )

        return hardware_intervals

    def _assign_hardware_slots(
        self, new_tou: list[dict], current_tou: list[dict], planned_tou: list[dict]
    ) -> None:
        """Stamp each new_tou entry with a hardware slot id in 1..max_intervals.

        The Growatt MIN inverter addresses its TOU table by slot number (1-9).
        The slot id on a new interval must either match the slot that already
        holds the same content on hardware (so we skip a redundant write) or
        target a slot that is either unoccupied or being freed in this cycle.
        Otherwise the write would overwrite a still-needed segment.

        A slot counts as spoken for when it holds anything in planned_tou, not
        merely anything in new_tou. Since #554 those differ: new_tou is only
        the subset eligible to be written now, while the disable side spares
        every hardware segment the plan still wants. Reserving only new_tou's
        slots would hand a deferred-but-planned segment's slot to an imminent
        write, destroying that window with no disable ever issued.

        Mutates new_tou in place. current_tou and planned_tou are read-only.
        """

        def content_key(segment: dict) -> tuple:
            return (
                segment["start_time"],
                segment["end_time"],
                segment["batt_mode"],
                segment.get("enabled", True),
            )

        def start_minute(segment: dict) -> int:
            hours, minutes = segment["start_time"].split(":")
            return int(hours) * 60 + int(minutes)

        keep_keys = {content_key(s) for s in planned_tou}

        # Current segments the plan still wants keep their slot, whether or not
        # they are eligible to be written this cycle.
        preserved_slot_by_key: dict[tuple, int] = {}
        slot_start_minute: dict[int, int] = {}
        for current in current_tou:
            slot = current.get("segment_id")
            if not isinstance(slot, int) or not (1 <= slot <= self.max_intervals):
                continue
            key = content_key(current)
            if key in keep_keys and key not in preserved_slot_by_key:
                preserved_slot_by_key[key] = slot
                slot_start_minute[slot] = start_minute(current)

        needs_slot: list[dict] = []
        slots_in_use_by_new: set[int] = set()
        for segment in new_tou:
            key = content_key(segment)
            if key in preserved_slot_by_key:
                segment["segment_id"] = preserved_slot_by_key[key]
                slots_in_use_by_new.add(segment["segment_id"])
            else:
                needs_slot.append(segment)

        occupied_slots = set(slot_start_minute)
        free_slots = sorted(set(range(1, self.max_intervals + 1)) - occupied_slots)

        if len(needs_slot) > len(free_slots):
            # The table can be full of still-planned segments on the first
            # cycle after upgrading from the always-write behaviour. Reclaim
            # the furthest-out ones: they have the most cycles left to be
            # written again before they take effect. Slots already handed to a
            # segment being written now are never reclaimable.
            reclaimable = sorted(
                (slot for slot in occupied_slots if slot not in slots_in_use_by_new),
                key=lambda slot: slot_start_minute[slot],
                reverse=True,
            )
            shortfall = len(needs_slot) - len(free_slots)
            reclaimed = reclaimable[:shortfall]
            if len(reclaimed) < shortfall:
                raise RuntimeError(
                    f"Not enough hardware slots: need {len(needs_slot)}, "
                    f"have {len(free_slots)} free and {len(reclaimed)} "
                    f"reclaimable (occupied={sorted(occupied_slots)})"
                )
            for slot in reclaimed:
                logger.info(
                    "Reclaiming slot %d (holds a segment starting %02d:%02d) — "
                    "the table is full and a nearer segment needs a slot",
                    slot,
                    slot_start_minute[slot] // 60,
                    slot_start_minute[slot] % 60,
                )
            free_slots = sorted(free_slots + reclaimed)

        for segment, slot in zip(needs_slot, free_slots, strict=False):
            segment["segment_id"] = slot

    def apply_intents(self, schedule: DPSchedule, current_period: int = 0) -> None:
        """Adopt this cycle's DP intent list, rebuilding TOU intervals from it."""
        logger.info(
            "Creating Growatt schedule using strategic intents from DP algorithm"
        )

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]

        logger.info(
            f"Using {len(self.strategic_intents)} strategic intents from DP algorithm (quarterly resolution)"
        )

        for period in range(max(1, current_period), len(self.strategic_intents)):
            if self.strategic_intents[period] != self.strategic_intents[period - 1]:
                logger.info(
                    "Intent transition at period %d: %s → %s",
                    period,
                    self.strategic_intents[period - 1],
                    self.strategic_intents[period],
                )

        self.current_schedule = schedule
        self._consolidate_and_convert_with_strategic_intents(current_period)

        logger.info(
            "New Growatt schedule created with %d TOU intervals (%d active for hardware)",
            len(self.tou_intervals),
            len(self.active_tou_intervals),
        )

    def _build_candidate(
        self, intents: list[str], current_period: int = 0
    ) -> tuple[list[dict], list[dict]]:
        """Compute what tou_intervals/active_tou_intervals WOULD be for the
        given intents, without mutating self.tou_intervals/self.active_tou_intervals.

        Shared by apply_intents (commits the result onto self) and
        evaluate_intents (diffs the result against self's currently-applied
        state) -- one computation, so they can never silently drift apart.

        Exception to purity: reads self.tou_intervals (current committed
        state, unchanged by this call) to check for corruption, and DOES set
        self.corruption_detected as an accepted diagnostic side effect (see
        docs/superpowers/specs/2026-07-23-controller-lifecycle-refactor-design.md).
        """
        logger.info(
            "Converting %d strategic intents to TOU intervals using 15-minute resolution",
            len(intents),
        )

        # Check for corrupted existing intervals (self's real current state)
        if self.tou_intervals:
            intervals_valid = self.validate_tou_intervals_ordering(
                self.tou_intervals, "before_strategic_intent_conversion"
            )
            if not intervals_valid:
                logger.warning(
                    "TOU RECOVERY: Existing intervals are corrupted, clearing and rebuilding"
                )
                for interval in self.tou_intervals:
                    logger.warning(
                        "  Corrupted: Segment %s: %s-%s %s",
                        interval.get("segment_id", "?"),
                        interval.get("start_time", "?"),
                        interval.get("end_time", "?"),
                        interval.get("batt_mode", "?"),
                    )
                self.corruption_detected = True
                logger.warning("CORRUPTION FLAG SET - Hardware write will be FORCED")

        # Group periods by mode from current_period (rolling window)
        period_groups = self._group_periods_by_mode(intents, current_period)

        logger.info(
            "Grouped %d periods into %d mode groups",
            len(intents),
            len(period_groups),
        )

        for group in period_groups:
            start_h, start_m = self._period_to_time(group["start_period"])
            end_h, end_m = self._period_to_time(group["end_period"])
            end_m += 14
            logger.debug(
                "Mode group: %s from %02d:%02d to %02d:%02d (%d periods)",
                group["mode"],
                start_h,
                start_m,
                end_h,
                end_m,
                len(group["intents"]),
            )

        new_intervals = self._groups_to_tou_intervals(period_groups)
        new_intervals.sort(key=lambda x: x["start_time"])
        for i, interval in enumerate(new_intervals, 1):
            interval["segment_id"] = i

        active = self._select_hardware_intervals(
            new_intervals,
            current_period,
            self._programmed_baseline(current_period * 15),
        )

        logger.info(
            "TOU conversion complete: %d total intervals, %d selected for hardware",
            len(new_intervals),
            len(active),
        )

        return new_intervals, active

    def _consolidate_and_convert_with_strategic_intents(self, current_period: int = 0):
        """Unchanged public behavior: mutates self.tou_intervals/active_tou_intervals
        from self.strategic_intents. Delegates to _build_candidate, shared with
        apply_intents/evaluate_intents, so there is one computation, not two."""
        if not self.strategic_intents:
            raise ValueError(
                "No strategic intents available — cannot convert to TOU intervals"
            )
        new_intervals, active = self._build_candidate(
            self.strategic_intents, current_period
        )
        self.tou_intervals = new_intervals
        self.active_tou_intervals = active

    def _get_period_intent_summary(self, start_hour: int, end_hour: int) -> str:
        """Get a summary of intents for a period (aggregated from quarterly periods)."""
        if not self.strategic_intents:
            return "unknown"

        # Aggregate quarterly strategic intents for the hour range
        num_periods = len(self.strategic_intents)
        period_intents = []

        for hour in range(start_hour, end_hour + 1):
            # Get quarterly periods for this hour (4 periods per hour normally)
            start_period = hour * 4
            end_period = min(start_period + 4, num_periods)

            # Add all quarterly intents for this hour
            for period in range(start_period, end_period):
                if period < num_periods:
                    period_intents.append(self.strategic_intents[period])

        if not period_intents:
            return "unknown"

        # Return most common intent in period
        intent_counts = {}
        for intent in period_intents:
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

        most_common = max(intent_counts.items(), key=lambda x: x[1])
        if len(set(period_intents)) == 1:
            return most_common[0]
        else:
            return f"{most_common[0]} (+{len(set(period_intents))-1} others)"

    def _diff_tou_intervals(
        self, current_tou: list[dict], new_tou: list[dict], from_period: int
    ) -> tuple[bool, str]:
        """Compare two already-formatted TOU interval lists from a given period
        onwards. Pure — no reads/writes of self state. Used by evaluate_intents
        (candidate built via _build_candidate), so the actual comparison rules
        live in exactly one place.
        """
        logger.info(f"Current schedule has {len(current_tou)} TOU intervals")
        logger.info(f"New schedule has {len(new_tou)} TOU intervals")

        def interval_end_minute(interval: dict) -> int:
            parts = interval["end_time"].split(":")
            return int(parts[0]) * 60 + int(parts[1])

        from_minute = from_period * 15

        relevant_current = []
        relevant_new = []

        for interval in current_tou:
            end_minute = interval_end_minute(interval)
            if end_minute >= from_minute and interval.get("enabled", True):
                relevant_current.append(interval)

        for interval in new_tou:
            end_minute = interval_end_minute(interval)
            if end_minute >= from_minute and interval.get("enabled", True):
                relevant_new.append(interval)

        past_enabled_current = [
            i
            for i in current_tou
            if i.get("enabled", True) and interval_end_minute(i) < from_minute
        ]
        if past_enabled_current and not relevant_current and not relevant_new:
            past_summary = ", ".join(
                f"{i['start_time']}-{i['end_time']} {i['batt_mode']}"
                for i in past_enabled_current
            )
            logger.info(
                "DECISION: Schedules differ - %d past TOU interval(s) still on "
                "hardware need cleanup: %s",
                len(past_enabled_current),
                past_summary,
            )
            return (
                True,
                f"Stale hardware cleanup ({len(past_enabled_current)} past intervals)",
            )

        logger.info(
            f"Relevant intervals: Current={len(relevant_current)}, New={len(relevant_new)}"
        )

        if len(relevant_current) != len(relevant_new):
            logger.info(
                f"DECISION: Schedules differ - Different number of relevant intervals ({len(relevant_current)} vs {len(relevant_new)})"
            )
            return (
                True,
                f"Different number of relevant intervals ({len(relevant_current)} vs {len(relevant_new)})",
            )

        relevant_current.sort(key=lambda x: x["start_time"])
        relevant_new.sort(key=lambda x: x["start_time"])

        for i, (curr, new) in enumerate(
            zip(relevant_current, relevant_new, strict=False)
        ):
            if (
                curr["start_time"] != new["start_time"]
                or curr["end_time"] != new["end_time"]
                or curr["batt_mode"] != new["batt_mode"]
                or curr.get("enabled", True) != new.get("enabled", True)
            ):
                logger.info(f"DECISION: Schedules differ - TOU interval {i} differs:")
                return True, f"TOU interval {i} differs in mode or timing"

        logger.info("DECISION: Schedules match")
        return False, ""

    def evaluate_intents(
        self, schedule: DPSchedule, current_period: int = 0
    ) -> tuple[bool, str]:
        """Compare TOU intervals a candidate schedule would produce against
        what's currently applied, from a specific period onwards.

        "Currently applied" covers both the daily plan and the subset of it
        that is eligible for hardware right now. The two move independently:
        an interval deferred as far-future, or held back by the 9-slot limit,
        becomes eligible purely because time passed, with the daily plan
        unchanged. Comparing only the daily plan would report no change and
        skip the cycle that was supposed to write it (issue #554).

        Uses 15-minute period granularity to match TOU segment resolution.
        """
        from_period = current_period
        from_hour = from_period // 4
        from_min_in_hour = (from_period % 4) * 15

        logger.info(
            "Comparing TOU intervals from period %d (%02d:%02d) onwards",
            from_period,
            from_hour,
            from_min_in_hour,
        )

        candidate_intents = schedule.original_dp_results["strategic_intent"]
        candidate_intervals, candidate_active = self._build_candidate(
            candidate_intents, current_period
        )

        # CRITICAL: If corruption was detected (by the _build_candidate call
        # just above, reading self's real current tou_intervals), force
        # hardware write regardless of comparison.
        if self.corruption_detected:
            logger.warning(
                "⚠️  CORRUPTION DETECTED FLAG IS SET - FORCING HARDWARE WRITE"
            )
            logger.warning(
                "This overrides normal schedule comparison to ensure corrupted intervals are cleared"
            )
            return True, "Corruption detected - forcing hardware write to clear"

        # The candidate was built at from_period with expired intervals already
        # dropped, while the committed set was built on an earlier cycle and
        # still holds whatever has since ended. Both sides are filtered here so
        # the comparison cannot report a difference that is only the clock
        # moving — that fired on every segment's expiry and cost a hardware
        # read producing no writes.
        from_minute = from_period * 15

        def eligible_content(intervals: list[dict]) -> set[tuple]:
            return {
                (i["start_time"], i["end_time"], i["batt_mode"], i.get("enabled", True))
                for i in intervals
                if self._time_to_minutes(i["end_time"]) >= from_minute
            }

        if eligible_content(candidate_active) != eligible_content(
            self.active_tou_intervals
        ):
            logger.info(
                "DECISION: Schedules differ - hardware-eligible intervals changed "
                "(%d applied, %d eligible now)",
                len(self.active_tou_intervals),
                len(candidate_active),
            )
            return True, "Hardware-eligible TOU intervals changed"

        current_tou = self.get_daily_TOU_settings()
        new_tou = self._format_daily_tou(candidate_intervals)

        return self._diff_tou_intervals(current_tou, new_tou, from_period)

    def reconcile_hardware(self, controller, effective_period: int) -> tuple[int, int]:
        """Put the inverter back in line with the committed plan.

        Differential update means a segment is written once and then never
        looked at again while the plan holds steady. That leaves both halves
        of issue #551 uncovered on a quiet cycle: a write the inverter
        silently dropped, and a slot it restored that the plan does not
        contain — the second of which runs the battery on a window nobody
        planned.

        This is sync_to_hardware itself rather than a separate drift check,
        because sync already reads the inverter once and diffs both
        directions against that read. A bespoke check would need its own read
        (doubling the load on the endpoint this change exists to relieve) and
        its own comparison, which would then be a second place for the two to
        disagree. Deferral still applies, so a quiet cycle writes nothing.
        """
        return self.sync_to_hardware(controller, effective_period)

    def initialize_from_tou_segments(self, tou_segments, current_hour=0):
        """Initialize GrowattMinController with TOU intervals from the inverter."""
        self.current_hour = current_hour
        self.tou_intervals = []

        # Normalization is shared with the differential-diff path so the two
        # cannot disagree on field types or missing-key defaults (issue #551).
        for segment in self._normalize_segments(tou_segments):
            self.tou_intervals.append(
                {**segment, "strategic_intent": "existing_schedule"}
            )

        # Validate intervals read from inverter (log only, no recovery here).
        # Disabled slots retain stale times from previous schedules, so the
        # full set of 9 slots will typically not be in chronological order.
        # This is expected — log at INFO level.
        logger.info("Validating TOU intervals read from inverter...")
        raw_intervals_valid = self.validate_tou_intervals_ordering(
            self.tou_intervals, "read_from_inverter_raw", log_level=logging.INFO
        )

        if not raw_intervals_valid:
            logger.info(
                "TOU intervals from inverter are not in chronological order"
                " - will rebuild on next schedule update"
            )
        else:
            logger.info(
                "✅ TOU intervals from inverter are already in correct chronological order"
            )

        # NO INTENT INFERENCE - strategic intents come from the DP algorithm

        # At startup, all intervals from inverter are active hardware intervals
        self.active_tou_intervals = list(self.tou_intervals)

        enabled_intervals = [seg for seg in self.tou_intervals if seg["enabled"]]
        if enabled_intervals:
            self.log_current_TOU_schedule(
                "Creating schedule by reading time segments from inverter"
            )
        else:
            logger.info("No active TOU segments found in inverter")

    def _format_daily_tou(self, intervals: list[dict]) -> list[dict]:
        """Truncate to max_intervals and fill in segment_id where missing.
        Shared by get_daily_TOU_settings (self's committed intervals) and
        evaluate_intents (a candidate's intervals) -- one formatting rule."""
        if not intervals:
            return []

        result = []
        for interval in intervals[: self.max_intervals]:
            segment = interval.copy()
            if "segment_id" not in segment:
                segment["segment_id"] = len(result) + 1
            result.append(segment)

        return result

    def get_daily_TOU_settings(self):
        """Get Growatt-specific TOU settings for all battery modes."""
        return self._format_daily_tou(self.tou_intervals)

    def get_all_tou_segments(self, current_period: int | None = None):
        """Get all TOU segments with default intervals filling gaps for complete 24-hour coverage.

        Args:
            current_period: Quarterly period index (0-95) to use for expiry calculations.
                            Defaults to the current wall-clock time when not provided.
        """
        if not self.tou_intervals:
            # Return default load_first for entire day if no intervals configured
            return [
                {
                    "segment_id": 0,
                    "start_time": "00:00",
                    "end_time": "23:59",
                    "batt_mode": "load_first",
                    "enabled": False,
                    "is_default": True,
                }
            ]

        # Calculate current time in minutes for expiry checks. Floored to the
        # period so this matches _select_hardware_intervals, which measures the
        # write horizon from the period. An unfloored wall clock puts the two
        # up to 15 minutes apart, and a segment inside that band is deferred by
        # the write path while the display path calls it pending — the amber
        # "Pending Write" badge this change exists to clear.
        if current_period is not None:
            current_minutes = (current_period // 4) * 60 + (current_period % 4) * 15
        else:
            now = time_utils.now()
            current_minutes = ((now.hour * 60 + now.minute) // 15) * 15

        # Get only active/enabled intervals and sort by start time
        active_intervals = [
            interval
            for interval in self.tou_intervals
            if interval.get("enabled", False)
            and interval.get("start_time")
            and interval.get("end_time")
        ]

        # Sort by start time
        active_intervals.sort(key=lambda x: self._time_to_minutes(x["start_time"]))

        # The same two timelines the write path gates on, built once for the
        # whole loop rather than per segment.
        programmed = self._programmed_baseline(current_minutes)
        plan_modes = self._modes_by_period(self.tou_intervals)
        programmed_modes = self._modes_by_period(programmed)

        result = []
        current_time_minutes = 0  # Start at midnight (00:00)

        # Add intervals and fill gaps with defaults
        for interval in active_intervals:
            interval_start_minutes = self._time_to_minutes(interval["start_time"])
            interval_end_minutes = self._time_to_minutes(interval["end_time"])

            # Add default interval before this active interval if there's a gap
            if current_time_minutes < interval_start_minutes:
                result.append(
                    {
                        "segment_id": 0,
                        "start_time": self._minutes_to_time(current_time_minutes),
                        "end_time": self._minutes_to_time(interval_start_minutes - 1),
                        "batt_mode": "load_first",
                        "enabled": False,
                        "is_default": True,
                    }
                )

            # Add the active interval with expiry and pending_write status
            segment = interval.copy()
            if "segment_id" not in segment:
                segment["segment_id"] = len(result) + 1
            is_expired = interval_end_minutes < current_minutes
            segment["is_expired"] = is_expired
            # A segment whose write is not due is not "pending" — it will be
            # written on the cycle that brings its first difference from the
            # programmed table within range (issues #554, #589). Only a segment
            # that should already be on hardware and is not — the 9-slot
            # overflow this flag was added for — is worth surfacing, since the
            # dashboard paints it amber and replaces the mode badge with a
            # "Pending Write" warning. Asked through the same helper the write
            # path uses, so the two cannot answer it differently.
            is_due, _overlapping = self._write_is_due(
                interval,
                plan_modes,
                programmed,
                programmed_modes,
                current_minutes // 15,
            )
            segment["pending_write"] = (
                not is_expired
                and is_due
                and not any(
                    a["start_time"] == interval["start_time"]
                    and a["end_time"] == interval["end_time"]
                    and a["batt_mode"] == interval["batt_mode"]
                    for a in self.active_tou_intervals
                )
            )
            result.append(segment)
            current_time_minutes = interval_end_minutes + 1

        # Add final default interval if day isn't complete
        day_end_minutes = 24 * 60 - 1  # 23:59 in minutes
        if current_time_minutes <= day_end_minutes:
            result.append(
                {
                    "segment_id": 0,
                    "start_time": self._minutes_to_time(current_time_minutes),
                    "end_time": "23:59",
                    "batt_mode": "load_first",
                    "enabled": False,
                    "is_default": True,
                }
            )

        return result

    def _time_to_minutes(self, time_str: str) -> int:
        """Convert time string (HH:MM) to minutes since midnight."""
        try:
            hours, minutes = map(int, time_str.split(":"))
            return hours * 60 + minutes
        except (ValueError, AttributeError):
            return 0

    def _minutes_to_time(self, minutes: int) -> str:
        """Convert minutes since midnight to time string (HH:MM)."""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}"

    def validate_tou_intervals_ordering(
        self, intervals=None, source="unknown", log_level=logging.WARNING
    ):
        """Validate that TOU intervals are in chronological order and log issues if found.

        Args:
            intervals: List of intervals to validate (default: self.tou_intervals)
            source: Description of where intervals came from (for logging)
            log_level: Logging level for issues (default: WARNING)

        Returns:
            bool: True if intervals are properly ordered, False if issues found
        """
        if intervals is None:
            intervals = self.tou_intervals

        if not intervals or len(intervals) <= 1:
            return True

        issues_found = []

        # Extract start hours for analysis
        start_hours = []
        segment_ids = []

        for interval in intervals:
            try:
                start_hour = int(interval["start_time"].split(":")[0])
                segment_id = interval.get("segment_id", 0)
                start_hours.append(start_hour)
                segment_ids.append(segment_id)
            except (ValueError, KeyError) as e:
                issues_found.append(f"Invalid interval format: {interval} - {e}")
                continue

        # Check chronological ordering
        for i in range(len(start_hours) - 1):
            if start_hours[i] > start_hours[i + 1]:
                issues_found.append(
                    f"Out-of-order intervals: Segment #{segment_ids[i]} ({start_hours[i]:02d}:00) "
                    f"comes before Segment #{segment_ids[i + 1]} ({start_hours[i + 1]:02d}:00) "
                    f"but starts later"
                )

        # Check for overlapping intervals
        for i in range(len(intervals) - 1):
            try:
                curr_end_time = intervals[i]["end_time"].split(":")
                curr_end = int(curr_end_time[0]) * 60 + int(
                    curr_end_time[1]
                )  # Convert to minutes

                next_start_time = intervals[i + 1]["start_time"].split(":")
                next_start = int(next_start_time[0]) * 60 + int(
                    next_start_time[1]
                )  # Convert to minutes

                if curr_end >= next_start:
                    issues_found.append(
                        f"Overlapping intervals: Segment #{segment_ids[i]} ({intervals[i]['start_time']}-{intervals[i]['end_time']}) "
                        f"overlaps with Segment #{segment_ids[i + 1]} ({intervals[i + 1]['start_time']}-{intervals[i + 1]['end_time']})"
                    )
            except (ValueError, KeyError, IndexError):
                continue

        # Check segment ID ordering
        if len(segment_ids) > 1:
            sorted_by_time = sorted(enumerate(start_hours), key=lambda x: x[1])
            expected_segment_order = [segment_ids[i] for i, _ in sorted_by_time]

            if segment_ids != expected_segment_order:
                issues_found.append(
                    f"Segment IDs not in chronological order: {segment_ids} "
                    f"(expected: {expected_segment_order})"
                )

        # Log results
        if issues_found:
            logger.log(
                log_level,
                "TOU intervals not in chronological order (%s) - %d issue(s)",
                source.upper(),
                len(issues_found),
            )
            for issue in issues_found:
                logger.log(log_level, "  - %s", issue)

            logger.log(log_level, "Current intervals:")
            for interval in intervals:
                enabled_status = (
                    "Active" if interval.get("enabled", True) else "Disabled"
                )
                logger.log(
                    log_level,
                    "  Segment #%s: %s-%s %s %s",
                    interval.get("segment_id", "?"),
                    interval.get("start_time", "?"),
                    interval.get("end_time", "?"),
                    interval.get("batt_mode", "?"),
                    enabled_status,
                )
            return False
        else:
            logger.debug("✅ TOU intervals ordering validation passed (%s)", source)
            return True

    def log_current_TOU_schedule(self, header=None):
        """Log the current TOU schedule in a formatted table."""
        daily_settings = self.get_daily_TOU_settings()
        if not daily_settings:
            return

        if not header:
            header = " -= Growatt TOU Schedule =- "

        col_widths = {"segment": 8, "start": 9, "end": 8, "mode": 15, "enabled": 8}
        total_width = sum(col_widths.values()) + len(col_widths) - 1

        header_format = (
            "{:>" + str(col_widths["segment"]) + "} "
            "{:>" + str(col_widths["start"]) + "} "
            "{:>" + str(col_widths["end"]) + "} "
            "{:>" + str(col_widths["mode"]) + "} "
            "{:>" + str(col_widths["enabled"]) + "}"
        )

        lines = [
            "═" * total_width,
            header_format.format(
                "Segment", "StartTime", "EndTime", "BatteryMode", "Enabled"
            ),
            "─" * total_width,
        ]

        setting_format = (
            "{segment_id:>" + str(col_widths["segment"]) + "} "
            "{start_time:>" + str(col_widths["start"]) + "} "
            "{end_time:>" + str(col_widths["end"]) + "} "
            "{batt_mode:>" + str(col_widths["mode"]) + "} "
            "{enabled!s:>" + str(col_widths["enabled"]) + "}"
        )

        for setting in daily_settings:
            safe_setting = {k: ("" if v is None else v) for k, v in setting.items()}
            lines.append(setting_format.format(**safe_setting))

        if header:
            lines.insert(0, "\n" + header)
        lines.extend(["═" * total_width, "\n"])
        logger.info("\n".join(lines))

    def log_detailed_schedule(self, header=None):
        """Log comprehensive schedule view with 15-minute periods and all control parameters."""
        if header:
            logger.info(header)

        groups = self.get_detailed_period_groups()
        if not groups:
            logger.info("No schedule data available")
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        lines = [
            "\n╔═══════════════╦══════════╦══════════════════╦═══════════════╦═════════════╦═════════════╦═══════════════╗",
            "║  Time Period  ║ Duration ║ Strategic Intent ║ Battery Mode  ║ Grid Charge ║ Charge Rate ║Discharge Rate ║",
            "╠═══════════════╬══════════╬══════════════════╬═══════════════╬═════════════╬═════════════╬═══════════════╣",
        ]

        for group in groups:
            time_range = f"{group['start_time']}-{group['end_time']}"

            # Duration
            duration_mins = group["duration_minutes"]
            if duration_mins >= 60:
                duration = f"{duration_mins // 60}h{duration_mins % 60:02d}m"
            else:
                duration = f"{duration_mins}min"

            # Mark current period
            is_current = group["start_period"] <= current_period <= group["end_period"]
            marker = "*" if is_current else " "

            # get_detailed_period_groups() only populates "batt_mode" for
            # CONTROL_MODEL == "tou_register" groups; vpp_power groups carry
            # "vpp_power_pct"/"vpp_remote_control" instead (inverter_controller.py
            # _mode_display_fields).
            if self.CONTROL_MODEL == "vpp_power":
                remote = "ON" if group["vpp_remote_control"] else "OFF"
                mode_label = f"{group['vpp_power_pct']}%/{remote}"
            else:
                mode_label = group["batt_mode"]

            row = (
                f"║{marker}{time_range:13} ║ {duration:8} ║ {group['intent']:16} ║ {mode_label:13} ║"
                f" {group['grid_charge']!s:11} ║ {group['charge_rate']:11}% ║ {group['discharge_rate']:13}% ║"
            )
            lines.append(row)

        lines.append(
            "╚═══════════════╩══════════╩══════════════════╩═══════════════╩═════════════╩═════════════╩═══════════════╝"
        )
        lines.append("* indicates current period")
        lines.append(
            "Intent mapping: GRID_CHARGING→battery_first, BATTERY_EXPORT→grid_first, SOLAR_STORAGE/IDLE/LOAD_SUPPORT→load_first"
        )

        logger.info("\n".join(lines))

    def _send_segment_to_hardware(self, controller, segment: dict) -> None:
        """Write a single TOU segment to inverter hardware.

        Subclasses can override to use different write mechanisms
        (e.g. entity-based writes for solax_modbus).
        """
        controller.set_inverter_time_segment(
            segment_id=segment["segment_id"],
            batt_mode=segment["batt_mode"],
            start_time=segment["start_time"],
            end_time=segment["end_time"],
            enabled=segment["enabled"],
        )

    # Growatt reports batt_mode as an int on some firmware/API paths.
    _BATT_MODE_BY_CODE: ClassVar[dict[int, str]] = {
        0: "load_first",
        1: "battery_first",
        2: "grid_first",
    }

    @classmethod
    def _normalize_segments(cls, segments) -> list[dict]:
        """Put a vendor segment payload into this class's internal shape.

        Applied once at the read boundary so every consumer — the startup
        initializer and the differential diff — sees the same field types and
        the same defaults. When only the initializer normalized, the diff
        compared an int batt_mode against our strings, matched nothing, and
        rewrote every segment blind while echoing the raw int back to the
        inverter.
        """
        normalized = []
        for segment in segments:
            raw_mode = segment.get("batt_mode")
            if isinstance(raw_mode, int):
                batt_mode = cls._BATT_MODE_BY_CODE.get(raw_mode, "battery_first")
            else:
                batt_mode = raw_mode or "load_first"

            normalized.append(
                {
                    "segment_id": segment.get("segment_id"),
                    "batt_mode": batt_mode,
                    "start_time": segment.get("start_time", "00:00"),
                    "end_time": segment.get("end_time", "23:59"),
                    "enabled": segment.get("enabled", False),
                }
            )
        return normalized

    def _read_segments_from_hardware(self, controller) -> list[dict]:
        """Read current TOU segments from inverter hardware.

        Raises if the read fails; an empty list means the inverter genuinely
        holds no segments. Subclasses can override to use different read
        mechanisms (e.g. entity state reads for solax_modbus).
        """
        return self._normalize_segments(controller.read_inverter_time_segments())

    def sync_to_hardware(
        self,
        controller,
        effective_period: int,
    ) -> tuple[int, int]:
        """Apply MIN inverter TOU schedule to hardware using differential update.

        Args:
            controller: HomeAssistantAPIController instance
            effective_period: Period (0-95) from which to start applying changes

        Returns:
            Tuple of (segments_updated, segments_disabled)
        """
        # The differential update must be diffed against what the inverter
        # actually holds, read fresh every cycle. Diffing against our own
        # in-memory model instead let the two drift apart (issue #551): the
        # model was seeded once at startup and never corrected, so writes
        # started duplicating live segments — which the Growatt cloud rejects
        # with a 500 — while segments the plan had dropped stayed enabled on
        # the inverter and kept running.
        # A failed read raises out of here rather than arriving as an empty
        # list, so it cannot be mistaken for "the inverter holds nothing" and
        # trigger a blind rewrite. _hardware_write_pending then retries.
        current_tou = self._read_segments_from_hardware(controller)

        # Only the active (hardware-programmed) intervals are eligible to be
        # written. self.tou_intervals can hold more than the 9 slots the MIN
        # inverter supports; the overflow is pending_write and must not reach
        # set_inverter_time_segment, otherwise the Growatt service rejects the
        # out-of-range segment_id with 500.
        new_tou = self.active_tou_intervals

        effective_minute = effective_period * 15

        def start_minute(interval: dict) -> int:
            parts = interval["start_time"].split(":")
            return int(parts[0]) * 60 + int(parts[1])

        def end_minute(interval: dict) -> int:
            parts = interval["end_time"].split(":")
            return int(parts[0]) * 60 + int(parts[1])

        # Whether a segment should be ON is decided by the whole plan, not by
        # new_tou — that is only the subset eligible to be *written* now, and
        # since #554 it omits the plan's far-future segments. Diffing against
        # it would read a correctly-programmed future segment as unplanned and
        # clear it, then write it back once it came within range. Deferral
        # applies to updates only; disables stay prompt, so an unplanned
        # segment is still cleared immediately (issue #551).
        #
        # The hardware target is part of that, not merely a subset of the plan:
        # since #589 a deferred *update* keeps the previously-programmed
        # version of a planned interval, which the plan no longer contains
        # verbatim. Diffing against the plan alone would disable a window that
        # is running correctly, mid-run, to avoid rewriting it.
        planned_tou = [
            interval
            for interval in [*self.tou_intervals, *self.active_tou_intervals]
            if end_minute(interval) >= effective_minute
        ]

        # Assign hardware slot ids (segment_id 1..max_intervals) to new_tou.
        # Preserves the slot of any interval already on hardware (matched by
        # content) so still-needed segments are not overwritten when a
        # previously-pending interval is promoted into the active 9.
        self._assign_hardware_slots(new_tou, current_tou, planned_tou)

        logger.info(
            "TOU comparison: Current=%d intervals, New=%d intervals",
            len(current_tou),
            len(new_tou),
        )

        # Validate intervals before sending to inverter
        logger.info("Validating TOU intervals before sending to inverter...")
        self.validate_tou_intervals_ordering(new_tou, "before_sending_to_inverter")

        to_disable: list[dict] = []
        to_update: list[dict] = []

        logger.info(
            "Analyzing TOU changes from period %d (%02d:%02d) onwards...",
            effective_period,
            effective_period // 4,
            (effective_period % 4) * 15,
        )

        # When new schedule is empty, disable ALL currently-enabled segments.
        # Counting every slot read back would fire this on an idle plan against
        # any real inverter, which always reports all 9 (issue #551).
        enabled_now = [seg for seg in current_tou if seg.get("enabled")]
        if len(planned_tou) == 0 and enabled_now:
            logger.warning("=" * 80)
            logger.warning(
                "Empty TOU schedule detected - CLEARING ALL %d enabled TOU segments from inverter",
                len(enabled_now),
            )
            logger.warning(
                "This happens when optimization determines NO profitable charging/discharging"
            )
            logger.warning("=" * 80)

            for current in enabled_now:
                disabled_segment = current.copy()
                disabled_segment["enabled"] = False
                to_disable.append(disabled_segment)
                logger.info(
                    "Marking ALL segments for clearing: %s-%s %s (segment_id=%s)",
                    current["start_time"],
                    current["end_time"],
                    current["batt_mode"],
                    current.get("segment_id"),
                )

            logger.info("Total segments marked for clearing: %d", len(to_disable))
        else:
            # Normal case: differential update (only update future segments)
            for current in current_tou:
                if not current.get("enabled", True):
                    # The inverter reports its unused slots as disabled entries.
                    # There is nothing to turn off, and re-disabling them would
                    # spend a cloud API call per idle slot, every cycle.
                    continue
                if end_minute(current) >= effective_minute:
                    has_match = any(
                        segment["start_time"] == current["start_time"]
                        and segment["end_time"] == current["end_time"]
                        and segment["batt_mode"] == current["batt_mode"]
                        and segment.get("enabled", True) == current["enabled"]
                        for segment in planned_tou
                    )

                    if not has_match:
                        disabled_segment = current.copy()
                        disabled_segment["enabled"] = False
                        to_disable.append(disabled_segment)
                        logger.debug(
                            "Mark for disable: %s-%s %s",
                            current["start_time"],
                            current["end_time"],
                            current["batt_mode"],
                        )

        # Identify segments to add/update
        for segment in new_tou:
            if end_minute(segment) >= effective_minute:
                existing_match = any(
                    current["start_time"] == segment["start_time"]
                    and current["end_time"] == segment["end_time"]
                    and current["batt_mode"] == segment["batt_mode"]
                    and current["enabled"] == segment["enabled"]
                    for current in current_tou
                )

                if not existing_match:
                    to_update.append(segment)
                    logger.debug(
                        "Mark for update: %s-%s %s",
                        segment["start_time"],
                        segment["end_time"],
                        segment["batt_mode"],
                    )

        # Check for overlaps and add to disable list
        for update_segment in to_update:
            update_start = start_minute(update_segment)
            update_end = end_minute(update_segment)

            for current_segment in current_tou:
                if any(
                    d.get("segment_id") == current_segment.get("segment_id")
                    for d in to_disable
                ):
                    continue

                if not current_segment.get("enabled", True):
                    continue

                current_start = start_minute(current_segment)
                current_end = end_minute(current_segment)

                if update_start <= current_end and update_end >= current_start:
                    if not any(
                        d.get("segment_id") == current_segment.get("segment_id")
                        for d in to_disable
                    ):
                        disabled_segment = current_segment.copy()
                        disabled_segment["enabled"] = False
                        to_disable.append(disabled_segment)

        # Apply updates to hardware
        writes = 0
        disables = 0
        failures: list[str] = []

        if to_disable or to_update:
            logger.info(
                "Updating %d segments, disabling %d segments",
                len(to_update),
                len(to_disable),
            )

            # Disable first to avoid overlaps
            for segment in to_disable:
                try:
                    logger.info(
                        "HARDWARE: Disabling TOU segment %s: %s-%s %s",
                        segment.get("segment_id"),
                        segment["start_time"],
                        segment["end_time"],
                        segment["batt_mode"],
                    )
                    self._send_segment_to_hardware(controller, segment)
                    disables += 1
                    logger.debug("SUCCESS: Segment disabled")
                except Exception as e:
                    logger.error("FAILED: Failed to disable TOU segment: %s", e)
                    # Failure already recorded by _api_request via record_failure_once
                    failures.append(
                        f"disable segment {segment.get('segment_id')} "
                        f"({segment['start_time']}-{segment['end_time']}): {e}"
                    )

            # Then update/add
            for segment in to_update:
                try:
                    logger.info(
                        "HARDWARE: Setting TOU segment %s: %s-%s %s",
                        segment.get("segment_id"),
                        segment["start_time"],
                        segment["end_time"],
                        segment["batt_mode"],
                    )
                    self._send_segment_to_hardware(controller, segment)
                    writes += 1
                    logger.debug("SUCCESS: Segment updated")
                except Exception as e:
                    logger.error("FAILED: Failed to update TOU segment: %s", e)
                    # Failure already recorded by _api_request via record_failure_once
                    failures.append(
                        f"update segment {segment.get('segment_id')} "
                        f"({segment['start_time']}-{segment['end_time']}): {e}"
                    )
        else:
            logger.info("No TOU segment changes needed")

        if failures:
            # Propagate so the caller (battery_system_manager._apply_schedule)
            # sets _hardware_write_pending=True and retries next cycle instead
            # of silently treating the write as applied (issue: dashboard/UI
            # showed the intended schedule as active while these segments
            # never reached the inverter).
            raise RuntimeError(
                f"{len(failures)} TOU segment write(s) failed: {'; '.join(failures)}"
            )

        return writes, disables

    def sync_soc_limits(self, controller) -> None:
        """Sync SOC limits from config to inverter hardware via entity writes.

        Reads current charge/discharge stop SOC from the inverter and writes
        back only if they differ from the configured max_soc / min_soc.
        """
        configured_min_soc = self.battery_settings.min_soc
        configured_max_soc = self.battery_settings.max_soc

        actual_min_soc = controller.get_discharge_stop_soc()
        actual_max_soc = controller.get_charge_stop_soc()

        if (
            actual_min_soc == configured_min_soc
            and actual_max_soc == configured_max_soc
        ):
            logger.info(
                "SOC limits verified: min=%d%%, max=%d%%",
                actual_min_soc,
                actual_max_soc,
            )
            return

        logger.info(
            "SOC limit mismatch — configured: min=%d%%, max=%d%% | "
            "actual: min=%s%%, max=%s%% — syncing",
            configured_min_soc,
            configured_max_soc,
            actual_min_soc,
            actual_max_soc,
        )

        if actual_min_soc != configured_min_soc:
            controller.set_discharge_stop_soc(configured_min_soc)
            logger.info("Set discharge_stop_soc to %d%%", configured_min_soc)

        if actual_max_soc != configured_max_soc:
            controller.set_charge_stop_soc(configured_max_soc)
            logger.info("Set charge_stop_soc to %d%%", configured_max_soc)

    def initialize_hardware(self, controller) -> None:
        self.sync_soc_limits(controller)

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Read current TOU schedule from inverter and initialize this controller.

        Args:
            controller: HomeAssistantAPIController instance
            current_hour: Current hour (0-23)
        """
        inverter_segments = self._read_segments_from_hardware(controller)
        self.initialize_from_tou_segments(inverter_segments, current_hour)

    def check_health(self, controller) -> list:
        """Check battery control capabilities."""
        health_check = perform_health_check(
            component_name="Battery Control",
            description="Controls battery charging and discharging schedule",
            is_required=True,
            controller=controller,
            all_methods=[
                "get_charging_power_rate",
                "get_discharging_power_rate",
                "grid_charge_enabled",
                "get_charge_stop_soc",
                "get_discharge_stop_soc",
            ],
        )

        return [health_check]

    @staticmethod
    def _parse_time_range(
        start_time: str, end_time: str
    ) -> tuple[int, int, int, int] | None:
        """Parse "HH:MM" start/end strings into (sh, sm, eh, em) ints.

        Returns None if the strings are malformed.
        """
        try:
            sh_s, sm_s = start_time.split(":")
            eh_s, em_s = end_time.split(":")
            return int(sh_s), int(sm_s), int(eh_s), int(em_s)
        except (ValueError, AttributeError):
            logger.warning("Malformed TOU time range: %s-%s", start_time, end_time)
            return None

    # ===== BEHAVIOR TESTING METHODS =====
    # These methods test what the system DOES, not HOW it does it

    def is_hour_configured_for_export(self, hour: int) -> bool:
        """Test if a given hour is configured for battery discharge/export.

        Args:
            hour: Hour to check (0-23)

        Returns:
            bool: True if hour enables battery discharge to grid
        """
        if not self.tou_intervals:
            return False

        for interval in self.tou_intervals:
            if not interval.get("enabled", False):
                continue

            parsed = self._parse_time_range(
                interval["start_time"], interval["end_time"]
            )
            if parsed is None:
                continue
            start_hour, start_minute, end_hour, end_minute = parsed

            hour_start = hour * 60
            hour_end = (hour + 1) * 60 - 1
            interval_start = start_hour * 60 + start_minute
            interval_end = end_hour * 60 + end_minute

            if hour_start <= interval_end and hour_end >= interval_start:
                return interval.get("batt_mode") == "grid_first"

        return False

    def is_hour_configured_for_charging(self, hour: int) -> bool:
        """Test if a given hour is configured for battery charging.

        Args:
            hour: Hour to check (0-23)

        Returns:
            bool: True if hour enables battery charging
        """
        if not self.tou_intervals:
            return False

        for interval in self.tou_intervals:
            if not interval.get("enabled", False):
                continue

            parsed = self._parse_time_range(
                interval["start_time"], interval["end_time"]
            )
            if parsed is None:
                continue
            start_hour, start_minute, end_hour, end_minute = parsed

            hour_start = hour * 60
            hour_end = (hour + 1) * 60 - 1
            interval_start = start_hour * 60 + start_minute
            interval_end = end_hour * 60 + end_minute

            if hour_start <= interval_end and hour_end >= interval_start:
                return interval.get("batt_mode") == "battery_first"

        return False

    def get_hour_battery_mode(self, hour: int) -> str:
        """Get the battery mode for a specific hour.

        Args:
            hour: Hour to check (0-23)

        Returns:
            str: Battery mode ('battery_first', 'grid_first', 'load_first')
        """
        if not self.tou_intervals:
            return "load_first"

        for interval in self.tou_intervals:
            parsed = self._parse_time_range(
                interval["start_time"], interval["end_time"]
            )
            if parsed is None:
                continue
            start_hour, start_minute, end_hour, end_minute = parsed

            hour_start = hour * 60
            hour_end = (hour + 1) * 60 - 1
            interval_start = start_hour * 60 + start_minute
            interval_end = end_hour * 60 + end_minute

            if hour_start <= interval_end and hour_end >= interval_start:
                return interval.get("batt_mode", "load_first")

        return "load_first"  # Default mode

    def has_no_overlapping_intervals(self) -> bool:
        """Test that no intervals overlap in time (hardware requirement).

        Returns:
            bool: True if no overlaps exist
        """
        if not self.tou_intervals or len(self.tou_intervals) <= 1:
            return True

        def parse_time_to_minutes(time_str: str) -> int:
            """Convert HH:MM to minutes since midnight."""
            hour, minute = map(int, time_str.split(":"))
            return hour * 60 + minute

        # Convert intervals to time ranges
        time_ranges = []
        for interval in self.tou_intervals:
            start_min = parse_time_to_minutes(interval["start_time"])
            end_min = parse_time_to_minutes(interval["end_time"])
            time_ranges.append((start_min, end_min))

        # Check all pairs for overlap
        for i, (start1, end1) in enumerate(time_ranges):
            for start2, end2 in time_ranges[i + 1 :]:
                # Two ranges overlap if: not (end1 < start2 or end2 < start1)
                if not (end1 < start2 or end2 < start1):
                    return False

        return True

    def intervals_are_chronologically_ordered(self) -> bool:
        """Test that intervals are in chronological time order (hardware requirement).

        Returns:
            bool: True if intervals are chronologically ordered
        """
        if not self.tou_intervals or len(self.tou_intervals) <= 1:
            return True

        def parse_time_to_minutes(time_str: str) -> int:
            """Convert HH:MM to minutes since midnight."""
            hour, minute = map(int, time_str.split(":"))
            return hour * 60 + minute

        # Get start times in order they appear
        start_times = []
        for interval in self.tou_intervals:
            start_min = parse_time_to_minutes(interval["start_time"])
            start_times.append(start_min)

        # Check if they're sorted
        return start_times == sorted(start_times)

    def apply_schedule_and_count_writes(
        self, strategic_intents: list, current_hour: int = 0
    ) -> int:
        """Apply strategic intents and count how many hardware writes would occur.

        This simulates the behavior testing for minimal write optimization by monitoring
        the actual differential update logic in the Fixed Time Slots algorithm.

        Args:
            strategic_intents: List of 24 strategic intents
            current_hour: Current hour (for differential updates)

        Returns:
            int: Number of hardware writes that would occur (0 for identical schedules)
        """
        # Store original state (for potential rollback if needed)

        # Apply new schedule
        self.current_hour = current_hour
        self.strategic_intents = strategic_intents

        # For write counting, we need to intercept the differential update logic
        # The Fixed Time Slots algorithm logs the actual writes, so we can count those
        # Capture logs to count actual hardware writes
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        logger = logging.getLogger("core.bess.growatt_min_controller")
        logger.addHandler(handler)

        try:
            self._consolidate_and_convert_with_strategic_intents()

            # Parse logs to count "HARDWARE CREATE" messages (actual writes)
            log_contents = log_capture.getvalue()
            write_count = log_contents.count("HARDWARE CREATE")

            # If no changes message appears, that means 0 writes
            if "No slot changes needed" in log_contents:
                write_count = 0

        finally:
            logger.removeHandler(handler)

        return write_count
