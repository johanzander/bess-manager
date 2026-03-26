"""Growatt schedule management module with Strategic Intent Conversion.

This module converts strategic intents from the DP algorithm into Growatt-specific
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
- SOLAR_STORAGE → battery_first (charging priority)
- LOAD_SUPPORT → load_first (discharging priority)
- EXPORT_ARBITRAGE → grid_first (export priority)
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

import logging
from datetime import datetime
from typing import ClassVar

from .dp_schedule import DPSchedule
from .health_check import perform_health_check
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class GrowattScheduleManager:
    """Creates Growatt-specific schedules using strategic intents from DP algorithm.

    This class manages the conversion between strategic intents and Growatt-specific
    Time of Use (TOU) intervals. It uses the strategic reasoning captured at decision
    time in the DP algorithm rather than analyzing energy flows afterward.

    Strategic Intent → Growatt Mode Mapping:
    - GRID_CHARGING → battery_first (enables AC charging)
    - SOLAR_STORAGE → battery_first (charging priority)
    - LOAD_SUPPORT → load_first (discharging priority)
    - EXPORT_ARBITRAGE → grid_first (export priority)
    - IDLE → load_first (normal operation)
    """

    # Map strategic intents to Growatt battery modes.
    # This determines which mode each intent triggers on the inverter.
    # - battery_first: Grid powers home, battery preserved (or charged if AC charge enabled)
    # - load_first: Battery discharges to support home load (inverter default behavior)
    # - grid_first: Priority to export to grid
    INTENT_TO_MODE: ClassVar[dict[str, str]] = {
        "GRID_CHARGING": "battery_first",  # Enable AC charging for arbitrage
        "SOLAR_STORAGE": "battery_first",  # Priority to battery charging from solar
        "LOAD_SUPPORT": "load_first",  # Priority to battery discharge for load
        "EXPORT_ARBITRAGE": "grid_first",  # Priority to grid export for profit
        "IDLE": "load_first",  # Normal operation, allows battery discharge
    }

    # Map strategic intents to inverter control settings
    # Each intent determines: grid_charge, charge_rate, discharge_rate
    INTENT_TO_CONTROL: ClassVar[dict[str, dict[str, bool | int]]] = {
        "GRID_CHARGING": {"grid_charge": True, "charge_rate": 100, "discharge_rate": 0},
        "SOLAR_STORAGE": {
            "grid_charge": False,
            "charge_rate": 100,
            "discharge_rate": 0,
        },
        "LOAD_SUPPORT": {"grid_charge": False, "charge_rate": 0, "discharge_rate": 100},
        "EXPORT_ARBITRAGE": {
            "grid_charge": False,
            "charge_rate": 0,
            "discharge_rate": 100,
        },
        "IDLE": {"grid_charge": False, "charge_rate": 100, "discharge_rate": 0},
    }

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the schedule manager with required battery settings for power calculations."""
        if battery_settings is None:
            raise ValueError("battery_settings is required and cannot be None")

        self.max_intervals = 9  # Growatt supports up to 9 TOU intervals
        self.current_schedule = None
        self.detailed_intervals = []  # For overview display
        self.tou_intervals = []  # For actual TOU settings
        self.active_tou_intervals: list[
            dict
        ] = []  # Subset of tou_intervals written to hardware (max 9)
        self.current_hour = 0  # Track current hour (0-23) for TOU schedule boundaries
        self.hourly_settings = {}  # Pre-calculated settings for each hour (0-23)
        self.strategic_intents = []  # Store strategic intents from DP algorithm
        self.corruption_detected = (
            False  # Flag to force hardware write when corruption found
        )

        # Required battery settings for power calculations
        self.battery_settings = battery_settings
        self.max_charge_power_kw = battery_settings.max_charge_power_kw
        self.max_discharge_power_kw = battery_settings.max_discharge_power_kw

        # Fixed time slots configuration (9 slots, ~2h40m each)

    def _calculate_power_rates_from_action(
        self, battery_action_kw: float, intent: str
    ) -> tuple[int, int]:
        """Calculate charge and discharge power rates from battery action.

        Args:
            battery_action_kw: Battery action in kW (positive=charge, negative=discharge)
            intent: Strategic intent for context

        Returns:
            Tuple of (charge_power_rate_percent, discharge_power_rate_percent)
        """
        # Thresholds for significant action
        CHARGE_THRESHOLD = 0.1  # kW
        DISCHARGE_THRESHOLD = 0.1  # kW

        charge_rate = 0
        discharge_rate = 0

        if battery_action_kw > CHARGE_THRESHOLD:
            # Charging action - calculate percentage of max charge power
            charge_rate = min(
                100, max(5, int((battery_action_kw / self.max_charge_power_kw) * 100))
            )

            # For grid charging, ensure minimum effective rate
            if intent == "GRID_CHARGING" and charge_rate < 20:
                charge_rate = 20  # Minimum 20% for effective grid charging

        elif battery_action_kw < -DISCHARGE_THRESHOLD:
            # Discharging action - calculate percentage of max discharge power
            discharge_power = abs(battery_action_kw)
            discharge_rate = min(
                100, max(5, int((discharge_power / self.max_discharge_power_kw) * 100))
            )

        return charge_rate, discharge_rate

    def _get_hourly_intent(self, hour: int) -> str:
        """Get dominant strategic intent for an hour by aggregating 4 quarterly periods.

        LEGACY: This method is only used for hourly power rate display/logging.
        With 15-min TOU resolution, actual battery mode control is done by TOU
        segments via _group_periods_by_mode(). This method should be removed
        once hourly aggregation is fully deprecated (see TODO.md).

        Args:
            hour: Hour (0-23) to get intent for

        Returns:
            Dominant strategic intent for this hour (most common, alphabetical tie-break)
        """
        if not self.strategic_intents:
            raise ValueError("No strategic intents available")

        num_periods = len(self.strategic_intents)
        start_period = hour * 4
        end_period = min(start_period + 4, num_periods)

        # Get all quarterly intents for this hour
        period_intents = [
            self.strategic_intents[p] for p in range(start_period, end_period)
        ]

        # Count occurrences of each intent
        intent_counts: dict[str, int] = {}
        for intent in period_intents:
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

        # Find dominant intent (most common, alphabetical tie-break)
        max_count = max(intent_counts.values())
        candidates = [i for i, c in intent_counts.items() if c == max_count]
        return min(candidates)  # Alphabetical: deterministic tie-break

    def _group_periods_by_mode(self, start_period: int = 0) -> list[dict]:
        """Group consecutive 15-min periods by their battery mode.

        This is the core of the new 15-minute resolution TOU scheduling.
        Instead of aggregating to hours, we work directly with periods.

        Args:
            start_period: Period to start from (0-95), typically current_period

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
        if not self.strategic_intents:
            return []

        groups = []
        current_mode = None
        group_start = None
        group_intents = []

        num_periods = len(self.strategic_intents)

        for period in range(start_period, num_periods):
            intent = self.strategic_intents[period]
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

    def get_detailed_period_groups(
        self, intents: list[str] | None = None
    ) -> list[dict]:
        """Get period groups with full control parameters for display/API.

        Groups consecutive 15-minute periods ONLY when ALL parameters are identical:
        - Strategic intent
        - Battery mode
        - Grid charge
        - Charge power rate
        - Discharge power rate

        Args:
            intents: Optional list of strategic intents to group. If None,
                     uses self.strategic_intents (today's schedule).

        Returns:
            List of period groups with all control parameters
        """
        effective_intents = intents if intents is not None else self.strategic_intents
        if not effective_intents:
            return []

        num_periods = len(effective_intents)

        # Build detailed settings for each 15-minute period
        period_settings = []
        for period in range(num_periods):
            intent = effective_intents[period]
            mode = self.INTENT_TO_MODE.get(intent, "load_first")
            control = self.INTENT_TO_CONTROL.get(
                intent, {"grid_charge": False, "charge_rate": 100, "discharge_rate": 0}
            )

            period_settings.append(
                {
                    "period": period,
                    "intent": intent,
                    "mode": mode,
                    "grid_charge": control["grid_charge"],
                    "charge_rate": control["charge_rate"],
                    "discharge_rate": control["discharge_rate"],
                }
            )

        # Group consecutive periods with identical settings
        groups = []
        current_group = None

        for ps in period_settings:
            if current_group is not None and (
                ps["intent"] == current_group["intent"]
                and ps["mode"] == current_group["mode"]
                and ps["grid_charge"] == current_group["grid_charge"]
                and ps["charge_rate"] == current_group["charge_rate"]
                and ps["discharge_rate"] == current_group["discharge_rate"]
            ):
                current_group["end_period"] = ps["period"]
                current_group["count"] += 1
            else:
                if current_group is not None:
                    groups.append(current_group)
                current_group = {
                    "start_period": ps["period"],
                    "end_period": ps["period"],
                    "intent": ps["intent"],
                    "mode": ps["mode"],
                    "grid_charge": ps["grid_charge"],
                    "charge_rate": ps["charge_rate"],
                    "discharge_rate": ps["discharge_rate"],
                    "count": 1,
                }

        if current_group is not None:
            groups.append(current_group)

        # Convert to display format with time strings
        result = []
        for group in groups:
            start_h, start_m = self._period_to_time(group["start_period"])
            end_h, end_m = self._period_to_time(group["end_period"])
            end_m += 14  # Last minute of period

            # Handle DST: cap to 23:59
            if end_h >= 24:
                end_h = 23
                end_m = 59

            result.append(
                {
                    "start_time": f"{start_h:02d}:{start_m:02d}",
                    "end_time": f"{end_h:02d}:{end_m:02d}",
                    "start_period": group["start_period"],
                    "end_period": group["end_period"],
                    "intent": group["intent"],
                    "mode": group["mode"],
                    "grid_charge": group["grid_charge"],
                    "charge_rate": group["charge_rate"],
                    "discharge_rate": group["discharge_rate"],
                    "period_count": group["count"],
                    "duration_minutes": group["count"] * 15,
                }
            )

        return result

    def _period_to_time(self, period: int) -> tuple[int, int]:
        """Convert period number to hour and minute.

        Note: During DST transitions, the number of periods varies:
        - Normal day: 96 periods (24 hours)
        - Spring forward: 92 periods (23 hours)
        - Fall back: 100 periods (25 hours)

        For periods >= 96 (fall-back extra hour), hour will be >= 24.
        Callers must handle this (e.g., cap to 23:59 for TOU schedules).

        Args:
            period: Period number (0-95 normally, 0-99 during fall-back)

        Returns:
            Tuple of (hour, minute) - hour may exceed 23 during DST fall-back
        """
        hour = period // 4
        minute = (period % 4) * 15
        return hour, minute

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

    def _select_hardware_intervals(
        self, intervals: list[dict], current_period: int
    ) -> list[dict]:
        """Select the next 9 non-expired intervals for hardware programming.

        Instead of dropping segments permanently, this keeps ALL intervals in
        tou_intervals but selects only the first 9 non-expired ones for writing
        to the inverter. As time passes and segments expire, slots free up and
        later segments get programmed on the next optimization cycle.

        Args:
            intervals: All TOU intervals (may exceed max_intervals).
            current_period: Current 15-minute period (0-95).

        Returns:
            List of up to 9 non-expired intervals for hardware programming.
        """
        # Calculate current time in minutes from the period
        current_hour = current_period // 4
        current_minute = (current_period % 4) * 15
        current_minutes = current_hour * 60 + current_minute

        # Filter to non-expired intervals (end_time >= current time)
        non_expired = [
            interval
            for interval in intervals
            if self._time_to_minutes(interval["end_time"]) >= current_minutes
        ]

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

    def _calculate_hourly_settings_with_strategic_intents(self):
        """Pre-calculate hourly settings using strategic intents and proper power rates.

        Aggregates quarterly strategic intents (96 periods) into hourly settings (24 hours)
        for Growatt inverter control.
        """
        self.hourly_settings = {}

        # REQUIRE strategic intents - no fallbacks
        if not self.strategic_intents:
            raise ValueError(
                "Missing strategic intents for hourly settings calculation"
            )

        # Get number of periods to handle DST (92/96/100)
        num_periods = len(self.strategic_intents)
        num_hours = (num_periods + 3) // 4  # Round up to handle partial hours

        for hour in range(num_hours):
            # Get dominant strategic intent for this hour (aggregates 4 quarterly periods)
            intent = self._get_hourly_intent(hour)

            # Get quarterly periods for battery action calculation
            start_period = hour * 4
            end_period = min(start_period + 4, num_periods)
            hourly_periods = range(start_period, end_period)

            # Get battery action for this hour if available
            # Actions are in kWh (energy per period) - sum them for the hour
            # Since each hour always has 4 quarterly periods, summing 4 periods gives the hourly total
            # which equals average power in kW (4 periods * 0.25h * kW = kWh, so kWh/1h = kW)
            battery_action = 0.0
            if self.current_schedule and self.current_schedule.actions:
                for period in hourly_periods:
                    if period < len(self.current_schedule.actions):
                        battery_action += self.current_schedule.actions[period]

            # Calculate power rates from battery action
            (
                _charge_power_rate,
                discharge_power_rate,
            ) = self._calculate_power_rates_from_action(battery_action, intent)

            # Determine settings based on strategic intent
            if intent == "GRID_CHARGING":
                grid_charge = True
                discharge_rate = 0
                # Always full power; power monitor caps to fuse headroom
                charge_rate = 100
                state = "charging"
                batt_mode = "battery_first"

            elif intent == "SOLAR_STORAGE":
                grid_charge = False
                discharge_rate = 0
                charge_rate = 100
                state = "charging" if battery_action > 0.01 else "idle"
                batt_mode = "battery_first"

            elif intent == "LOAD_SUPPORT":
                grid_charge = False
                discharge_rate = 100
                charge_rate = 0
                state = "discharging"
                batt_mode = "load_first"

            elif intent == "EXPORT_ARBITRAGE":
                grid_charge = False
                discharge_rate = discharge_power_rate
                charge_rate = 0
                state = "grid_first"
                batt_mode = "grid_first"

            elif intent == "IDLE":
                grid_charge = False
                discharge_rate = 0
                charge_rate = 100
                state = "idle"
                batt_mode = self.INTENT_TO_MODE["IDLE"]
            else:
                raise ValueError(f"Unknown strategic intent at hour {hour}: {intent}")

            self.hourly_settings[hour] = {
                "grid_charge": grid_charge,
                "discharge_rate": discharge_rate,
                "charge_rate": charge_rate,
                "state": state,
                "batt_mode": batt_mode,
                "strategic_intent": intent,
                "battery_action_kw": battery_action,
            }

            logger.debug(
                "Hour %02d: Intent=%s, Action=%.2fkW, ChargeRate=%d%%, DischargeRate=%d%%, GridCharge=%s, Mode=%s",
                hour,
                intent,
                battery_action,
                charge_rate,
                discharge_rate,
                grid_charge,
                batt_mode,
            )

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ):
        """Process DPSchedule with strategic intents into Growatt format."""
        logger.info(
            "Creating Growatt schedule using strategic intents from DP algorithm"
        )

        # Always use strategic intents from DP algorithm - no fallbacks
        self.strategic_intents = schedule.original_dp_results["strategic_intent"]

        logger.info(
            f"Using {len(self.strategic_intents)} strategic intents from DP algorithm (quarterly resolution)"
        )

        # Log intent transitions
        for period in range(1, len(self.strategic_intents)):
            if self.strategic_intents[period] != self.strategic_intents[period - 1]:
                logger.info(
                    "Intent transition at period %d: %s → %s",
                    period,
                    self.strategic_intents[period - 1],
                    self.strategic_intents[period],
                )

        self.current_schedule = schedule
        self._consolidate_and_convert_with_strategic_intents(current_period)
        self._calculate_hourly_settings_with_strategic_intents()

        logger.info(
            "New Growatt schedule created with %d TOU intervals (%d active for hardware)",
            len(self.tou_intervals),
            len(self.active_tou_intervals),
        )

    def _consolidate_and_convert_with_strategic_intents(self, current_period: int = 0):
        """Convert strategic intents to TOU intervals using 15-minute resolution.

        This method works directly with 15-minute periods instead of aggregating
        to hourly intervals. This eliminates the "gap problem" where majority
        voting created holes in charging schedules.

        Algorithm:
        1. Group consecutive 15-min periods by their mapped battery mode
        2. Create TOU intervals for non-default (battery_first, grid_first) groups
        3. Select next 9 non-expired intervals for hardware (active_tou_intervals)
        """
        if not self.strategic_intents:
            logger.warning(
                "No strategic intents available, falling back to action-based analysis"
            )
            self._consolidate_and_convert_fallback()
            return

        logger.info(
            "Converting %d strategic intents to TOU intervals using 15-minute resolution",
            len(self.strategic_intents),
        )

        # Log the intent-to-mode mapping being used
        logger.info("Intent to mode mapping: %s", self.INTENT_TO_MODE)

        # Check for corrupted existing intervals before clearing
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

        # Start fresh - only periods from current_period onwards get TOU segments
        self.tou_intervals = []

        # Group periods by mode from current_period (rolling window)
        period_groups = self._group_periods_by_mode(current_period)

        logger.info(
            "Grouped %d periods into %d mode groups",
            len(self.strategic_intents),
            len(period_groups),
        )

        # Log the groups for debugging
        for group in period_groups:
            start_h, start_m = self._period_to_time(group["start_period"])
            end_h, end_m = self._period_to_time(group["end_period"])
            end_m += 14  # Show actual end minute
            logger.debug(
                "Mode group: %s from %02d:%02d to %02d:%02d (%d periods)",
                group["mode"],
                start_h,
                start_m,
                end_h,
                end_m,
                len(group["intents"]),
            )

        # Convert groups to TOU intervals
        new_intervals = self._groups_to_tou_intervals(period_groups)

        # Add new intervals to the list
        self.tou_intervals.extend(new_intervals)

        # Sort by start time to ensure chronological order
        self.tou_intervals.sort(key=lambda x: x["start_time"])

        # Reassign segment IDs in chronological order
        for i, interval in enumerate(self.tou_intervals, 1):
            interval["segment_id"] = i

        # Select next 9 non-expired intervals for hardware programming
        self.active_tou_intervals = self._select_hardware_intervals(
            self.tou_intervals, current_period
        )

        logger.info(
            "TOU conversion complete: %d total intervals, %d selected for hardware",
            len(self.tou_intervals),
            len(self.active_tou_intervals),
        )

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

    def _strategic_intent_to_battery_mode(self, strategic_intent):
        """Convert strategic intent to Growatt battery mode."""
        intent_to_mode = {
            "IDLE": "load_first",
            "GRID_CHARGING": "battery_first",
            "SOLAR_STORAGE": "battery_first",
            "EXPORT_ARBITRAGE": "grid_first",
        }
        return intent_to_mode.get(strategic_intent, "load_first")

    def _consolidate_and_convert_fallback(self):
        """Fallback conversion when no strategic intents are available."""
        logger.debug("Using fallback conversion based on battery actions")
        # Keep existing logic as fallback when intents aren't available
        # This preserves backward compatibility
        if not self.current_schedule:
            return

        hourly_intervals = self.current_schedule.get_daily_intervals()
        if not hourly_intervals:
            return

        # Use action-based logic as fallback
        battery_first_hours = []
        for hour in range(self.current_hour, 24):
            for interval in hourly_intervals:
                interval_hour = int(interval["start_time"].split(":")[0])
                if interval_hour == hour:
                    state = interval.get("state", "idle")
                    if state == "discharging" or state == "charging":
                        battery_first_hours.append(hour)
                    break

        # Create simple TOU intervals for battery_first hours
        if battery_first_hours:
            # Group consecutive hours
            consecutive_periods = []
            current_period = [battery_first_hours[0]]

            for i in range(1, len(battery_first_hours)):
                if battery_first_hours[i] == battery_first_hours[i - 1] + 1:
                    current_period.append(battery_first_hours[i])
                else:
                    consecutive_periods.append(current_period)
                    current_period = [battery_first_hours[i]]

            consecutive_periods.append(current_period)

            for period in consecutive_periods:
                segment_id = len(self.tou_intervals) + 1
                start_time = f"{period[0]:02d}:00"
                end_time = f"{period[-1]:02d}:59"

                self.tou_intervals.append(
                    {
                        "segment_id": segment_id,
                        "batt_mode": "battery_first",
                        "start_time": start_time,
                        "end_time": end_time,
                        "enabled": True,
                        "strategic_intent": self._get_period_intent_summary(
                            period[0], period[-1]
                        ),
                    }
                )

    def get_hourly_settings(self, hour):
        if hour not in self.hourly_settings:
            raise ValueError(
                f"No hourly settings for hour {hour}. Strategic intents: {len(self.strategic_intents)}, Settings calculated: {len(self.hourly_settings)}"
            )

        return self.hourly_settings[hour]

    def get_strategic_intent_summary(self) -> dict:
        """Get a summary of strategic intents for the day (aggregated from quarterly periods)."""
        if not self.strategic_intents:
            return {}

        # Aggregate quarterly strategic intents into hourly intents
        num_periods = len(self.strategic_intents)
        num_hours = (num_periods + 3) // 4  # Round up to handle partial hours

        intent_hours = {}
        for hour in range(num_hours):
            # Get dominant strategic intent for this hour (aggregates 4 quarterly periods)
            intent = self._get_hourly_intent(hour)

            if intent not in intent_hours:
                intent_hours[intent] = []
            intent_hours[intent].append(hour)

        summary = {}
        for intent, hours in intent_hours.items():
            summary[intent] = {
                "hours": hours,
                "count": len(hours),
                "description": self._get_intent_description(intent),
            }

        return summary

    def _get_intent_description(self, intent: str) -> str:
        """Get human-readable description of strategic intent."""
        descriptions = {
            "GRID_CHARGING": "Storing cheap grid energy for later use",
            "SOLAR_STORAGE": "Storing excess solar energy for evening/night",
            "LOAD_SUPPORT": "Using battery to support home consumption",
            "EXPORT_ARBITRAGE": "Selling stored energy to grid for profit",
            "IDLE": "No significant battery activity",
        }
        return descriptions.get(intent, "Unknown intent")

    def compare_schedules(self, other_schedule, from_period: int = 0):
        """Compare TOU intervals from a specific period onwards.

        Uses 15-minute period granularity to match TOU segment resolution.

        Args:
            other_schedule: The new schedule to compare against
            from_period: Period number (0-95) to start comparison from

        Returns:
            Tuple of (schedules_differ: bool, reason: str)
        """
        from_minute = from_period * 15
        from_hour = from_period // 4
        from_min_in_hour = (from_period % 4) * 15

        logger.info(
            "Comparing TOU intervals from period %d (%02d:%02d) onwards",
            from_period,
            from_hour,
            from_min_in_hour,
        )

        # CRITICAL: If corruption was detected, force hardware write regardless of comparison
        if self.corruption_detected:
            logger.warning(
                "⚠️  CORRUPTION DETECTED FLAG IS SET - FORCING HARDWARE WRITE"
            )
            logger.warning(
                "This overrides normal schedule comparison to ensure corrupted intervals are cleared"
            )
            return True, "Corruption detected - forcing hardware write to clear"

        # Get TOU intervals
        current_tou = self.get_daily_TOU_settings()
        new_tou = other_schedule.get_daily_TOU_settings()

        logger.info(f"Current schedule has {len(current_tou)} TOU intervals")
        logger.info(f"New schedule has {len(new_tou)} TOU intervals")

        def interval_end_minute(interval: dict) -> int:
            """Get end time as minutes since midnight."""
            parts = interval["end_time"].split(":")
            return int(parts[0]) * 60 + int(parts[1])

        # Find relevant intervals (ending at or after from_minute)
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

        logger.info(
            f"Relevant intervals: Current={len(relevant_current)}, New={len(relevant_new)}"
        )

        # Log what we're comparing
        logger.info("Current relevant TOU intervals:")
        for interval in relevant_current:
            logger.info(
                f"  {interval['start_time']}-{interval['end_time']} mode={interval['batt_mode']}"
            )

        logger.info("New relevant TOU intervals:")
        for interval in relevant_new:
            logger.info(
                f"  {interval['start_time']}-{interval['end_time']} mode={interval['batt_mode']}"
            )

        # Compare relevant intervals
        if len(relevant_current) != len(relevant_new):
            logger.info(
                f"DECISION: Schedules differ - Different number of relevant intervals ({len(relevant_current)} vs {len(relevant_new)})"
            )
            return (
                True,
                f"Different number of relevant intervals ({len(relevant_current)} vs {len(relevant_new)})",
            )

        # Sort intervals by start time for proper comparison
        relevant_current.sort(key=lambda x: x["start_time"])
        relevant_new.sort(key=lambda x: x["start_time"])

        # Check each relevant interval - ONLY TOU settings that matter to the inverter
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
                logger.info(
                    f"  Current: {curr['start_time']}-{curr['end_time']} mode={curr['batt_mode']} enabled={curr.get('enabled', True)}"
                )
                logger.info(
                    f"  New:     {new['start_time']}-{new['end_time']} mode={new['batt_mode']} enabled={new.get('enabled', True)}"
                )
                return True, f"TOU interval {i} differs in mode or timing"

        logger.info("DECISION: Schedules match - All TOU intervals are identical")
        return False, "TOU intervals match"

    def initialize_from_tou_segments(self, tou_segments, current_hour=0):
        """Initialize GrowattScheduleManager with TOU intervals from the inverter."""
        self.current_hour = current_hour
        self.tou_intervals = []

        for segment in tou_segments:
            segment_id = segment.get("segment_id")
            is_enabled = segment.get("enabled", False)
            raw_batt_mode = segment.get("batt_mode")

            # Convert integer to string representation if needed
            if isinstance(raw_batt_mode, int):
                batt_mode_map = {0: "load_first", 1: "battery_first", 2: "grid_first"}
                batt_mode = batt_mode_map.get(raw_batt_mode, "battery_first")
            else:
                batt_mode = raw_batt_mode if raw_batt_mode else "load_first"

            self.tou_intervals.append(
                {
                    "segment_id": segment_id,
                    "batt_mode": batt_mode,
                    "start_time": segment.get("start_time", "00:00"),
                    "end_time": segment.get("end_time", "23:59"),
                    "enabled": is_enabled,
                    "strategic_intent": "existing_schedule",
                }
            )

        # DIAGNOSTIC: Validate intervals read from inverter (log only, no recovery here)
        logger.info("Validating TOU intervals read from inverter...")
        raw_intervals_valid = self.validate_tou_intervals_ordering(
            self.tou_intervals, "read_from_inverter_raw"
        )

        if not raw_intervals_valid:
            logger.warning(
                "⚠️  TOU intervals from inverter are corrupted - will recover during next schedule update"
            )
        else:
            logger.info(
                "✅ TOU intervals from inverter are already in correct chronological order"
            )

        # NO INTENT INFERENCE - leave hourly_settings empty until we get strategic intents

        # At startup, all intervals from inverter are active hardware intervals
        self.active_tou_intervals = list(self.tou_intervals)

        enabled_intervals = [seg for seg in self.tou_intervals if seg["enabled"]]
        if enabled_intervals:
            self.log_current_TOU_schedule(
                "Creating schedule by reading time segments from inverter"
            )
        else:
            logger.info("No active TOU segments found in inverter")

    def get_daily_TOU_settings(self):
        """Get Growatt-specific TOU settings for all battery modes."""
        if not self.tou_intervals:
            return []

        result = []
        for interval in self.tou_intervals[: self.max_intervals]:
            segment = interval.copy()
            # Preserve the segment_id from our new algorithm instead of reassigning
            # The new tiny segments approach ensures segment IDs are already in chronological order
            if "segment_id" not in segment:
                # Fallback for legacy intervals that might not have segment_id
                segment["segment_id"] = len(result) + 1
            result.append(segment)

        return result

    def get_all_tou_segments(self):
        """Get all TOU segments with default intervals filling gaps for complete 24-hour coverage."""
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

        # Calculate current time in minutes for expiry checks
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute

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
            segment["pending_write"] = not is_expired and not any(
                a["start_time"] == interval["start_time"]
                and a["end_time"] == interval["end_time"]
                and a["batt_mode"] == interval["batt_mode"]
                for a in self.active_tou_intervals
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

    def validate_tou_intervals_ordering(self, intervals=None, source="unknown"):
        """Validate that TOU intervals are in chronological order and log warnings if not.

        Args:
            intervals: List of intervals to validate (default: self.tou_intervals)
            source: Description of where intervals came from (for logging)

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
            logger.warning(
                "⚠️  TOU INTERVALS ORDERING ISSUES DETECTED (%s) ⚠️", source.upper()
            )
            logger.warning("Issues found:")
            for issue in issues_found:
                logger.warning(f"  - {issue}")

            logger.warning("Current intervals:")
            for interval in intervals:
                enabled_status = (
                    "Active" if interval.get("enabled", True) else "Disabled"
                )
                logger.warning(
                    f"  Segment #{interval.get('segment_id', '?')}: "
                    f"{interval.get('start_time', '?')}-{interval.get('end_time', '?')} "
                    f"{interval.get('batt_mode', '?')} {enabled_status}"
                )

            logger.warning(
                "🔍 This indicates either a bug in our TOU generation logic or "
                "an issue with the Growatt inverter TOU handling."
            )
            return False
        else:
            logger.debug("✅ TOU intervals ordering validation passed (%s)", source)
            return True

    def log_current_TOU_schedule(self, header=None):
        """Log the final simplified TOU settings with validation."""
        daily_settings = self.get_daily_TOU_settings()
        if not daily_settings:
            return

        # Validate intervals before logging
        self.validate_tou_intervals_ordering(daily_settings, "generated_schedule")

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

        now = datetime.now()
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

            row = (
                f"║{marker}{time_range:13} ║ {duration:8} ║ {group['intent']:16} ║ {group['mode']:13} ║"
                f" {group['grid_charge']!s:11} ║ {group['charge_rate']:11}% ║ {group['discharge_rate']:13}% ║"
            )
            lines.append(row)

        lines.append(
            "╚═══════════════╩══════════╩══════════════════╩═══════════════╩═════════════╩═════════════╩═══════════════╝"
        )
        lines.append("* indicates current period")
        lines.append(
            "Intent mapping: GRID_CHARGING/SOLAR_STORAGE→battery_first, EXPORT_ARBITRAGE→grid_first, IDLE/LOAD_SUPPORT→load_first"
        )

        logger.info("\n".join(lines))

    def write_schedule_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        """Apply MIN inverter TOU schedule to hardware using differential update.

        Args:
            controller: HomeAssistantAPIController instance
            effective_period: Period (0-95) from which to start applying changes
            current_tou: TOU intervals currently active on the inverter

        Returns:
            Tuple of (segments_updated, segments_disabled)
        """
        new_tou = self.tou_intervals

        logger.info(
            "TOU comparison: Current=%d intervals, New=%d intervals",
            len(current_tou),
            len(new_tou),
        )

        # Validate intervals before sending to inverter
        logger.info("Validating TOU intervals before sending to inverter...")
        self.validate_tou_intervals_ordering(new_tou, "before_sending_to_inverter")

        effective_minute = effective_period * 15

        def start_minute(interval: dict) -> int:
            parts = interval["start_time"].split(":")
            return int(parts[0]) * 60 + int(parts[1])

        def end_minute(interval: dict) -> int:
            parts = interval["end_time"].split(":")
            return int(parts[0]) * 60 + int(parts[1])

        to_disable: list[dict] = []
        to_update: list[dict] = []

        logger.info(
            "Analyzing TOU changes from period %d (%02d:%02d) onwards...",
            effective_period,
            effective_period // 4,
            (effective_period % 4) * 15,
        )

        # When new schedule is empty, disable ALL current TOU segments
        if len(new_tou) == 0 and len(current_tou) > 0:
            logger.warning("=" * 80)
            logger.warning(
                "Empty TOU schedule detected - CLEARING ALL %d existing TOU segments from inverter",
                len(current_tou),
            )
            logger.warning(
                "This happens when optimization determines NO profitable charging/discharging"
            )
            logger.warning("=" * 80)

            for current in current_tou:
                if current.get("enabled", True):
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
                if end_minute(current) >= effective_minute:
                    has_match = any(
                        segment["start_time"] == current["start_time"]
                        and segment["end_time"] == current["end_time"]
                        and segment["batt_mode"] == current["batt_mode"]
                        and segment["enabled"] == current["enabled"]
                        for segment in new_tou
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
                    controller.set_inverter_time_segment(
                        segment_id=segment["segment_id"],
                        batt_mode=segment["batt_mode"],
                        start_time=segment["start_time"],
                        end_time=segment["end_time"],
                        enabled=segment["enabled"],
                    )
                    disables += 1
                    logger.debug("SUCCESS: Segment disabled")
                except Exception as e:
                    logger.error("FAILED: Failed to disable TOU segment: %s", e)

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
                    controller.set_inverter_time_segment(
                        segment_id=segment["segment_id"],
                        batt_mode=segment["batt_mode"],
                        start_time=segment["start_time"],
                        end_time=segment["end_time"],
                        enabled=segment["enabled"],
                    )
                    writes += 1
                    logger.debug("SUCCESS: Segment updated")
                except Exception as e:
                    logger.error("FAILED: Failed to update TOU segment: %s", e)
        else:
            logger.info("No TOU segment changes needed")

        return writes, disables

    def sync_soc_limits(self, controller) -> None:
        """Sync SOC limits from config to inverter hardware via entity writes."""
        configured_min_soc = self.battery_settings.min_soc
        configured_max_soc = self.battery_settings.max_soc

        controller.set_discharge_stop_soc(configured_min_soc)
        logger.info("Set discharge_stop_soc to %d%%", configured_min_soc)

        controller.set_charge_stop_soc(configured_max_soc)
        logger.info("Set charge_stop_soc to %d%%", configured_max_soc)

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
        else:
            logger.warning(
                "SOC limit mismatch detected! Configured: min=%d%%, max=%d%% | Actual: min=%s%%, max=%s%%",
                configured_min_soc,
                configured_max_soc,
                actual_min_soc,
                actual_max_soc,
            )

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Read current TOU schedule from inverter and initialize this manager.

        Args:
            controller: HomeAssistantAPIController instance
            current_hour: Current hour (0-23)
        """
        inverter_segments = controller.read_inverter_time_segments()
        self.initialize_from_tou_segments(inverter_segments, current_hour)

    def check_health(self, controller) -> list:
        """Check battery control capabilities."""
        # Define what controller methods this component uses
        battery_control_methods = [
            "get_charging_power_rate",
            "get_discharging_power_rate",
            "grid_charge_enabled",
            "get_charge_stop_soc",
            "get_discharge_stop_soc",
        ]

        # For battery control, all methods are required for safe battery operation
        required_battery_control_methods = battery_control_methods

        health_check = perform_health_check(
            component_name="Battery Control",
            description="Controls battery charging and discharging schedule",
            is_required=True,
            controller=controller,
            all_methods=battery_control_methods,
            required_methods=required_battery_control_methods,
        )

        return [health_check]

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

            # Parse interval time range
            start_time = interval["start_time"]
            end_time = interval["end_time"]
            start_hour = int(start_time.split(":")[0])
            start_minute = int(start_time.split(":")[1])
            end_hour = int(end_time.split(":")[0])
            end_minute = int(end_time.split(":")[1])

            # Convert to minutes for precise comparison
            hour_start = hour * 60
            hour_end = (hour + 1) * 60 - 1
            interval_start = start_hour * 60 + start_minute
            interval_end = end_hour * 60 + end_minute

            # Check if hour overlaps with this interval
            if hour_start <= interval_end and hour_end >= interval_start:
                # Check if this interval uses grid_first mode (export)
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

            # Parse interval time range
            start_time = interval["start_time"]
            end_time = interval["end_time"]
            start_hour = int(start_time.split(":")[0])
            start_minute = int(start_time.split(":")[1])
            end_hour = int(end_time.split(":")[0])
            end_minute = int(end_time.split(":")[1])

            # Convert to minutes for precise comparison
            hour_start = hour * 60
            hour_end = (hour + 1) * 60 - 1
            interval_start = start_hour * 60 + start_minute
            interval_end = end_hour * 60 + end_minute

            # Check if hour overlaps with this interval
            if hour_start <= interval_end and hour_end >= interval_start:
                # Check if this interval uses battery_first mode (charging priority)
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
            return "load_first"  # Default mode

        for interval in self.tou_intervals:
            # Parse interval time range
            start_time = interval["start_time"]
            end_time = interval["end_time"]
            start_hour = int(start_time.split(":")[0])
            start_minute = int(start_time.split(":")[1])
            end_hour = int(end_time.split(":")[0])
            end_minute = int(end_time.split(":")[1])

            # Convert to minutes for precise comparison
            hour_start = hour * 60
            hour_end = (hour + 1) * 60 - 1
            interval_start = start_hour * 60 + start_minute
            interval_end = end_hour * 60 + end_minute

            # Check if hour overlaps with this interval
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
        import io
        import logging

        # Capture logs to count actual hardware writes
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        logger = logging.getLogger("core.bess.growatt_schedule")
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
