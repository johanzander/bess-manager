"""Growatt schedule management module for TOU (Time of Use) and hourly controls."""

import logging

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


def create_tou_interval(
    segment_id: int,
    start_time: str,
    end_time: str,
) -> dict:
    """Create a simplified Growatt TOU interval dictionary."""
    return {
        "segment_id": segment_id,
        "batt_mode": "battery-first",
        "start_time": start_time,
        "end_time": end_time,
        "enabled": True,
    }


class GrowattScheduleManager:
    """Creates Growatt-specific schedules from generic battery schedule."""

    def __init__(self) -> None:
        """Initialize the schedule manager."""
        self.max_intervals = 8  # Growatt supports up to 8 TOU intervals
        self.current_schedule = None
        self.detailed_intervals = []  # For overview display
        self.tou_intervals = []  # For actual TOU settings
        self.current_hour = 0  # Track current hour

    def create_schedule(self, schedule, current_hour=0):
        """Convert generic schedule to Growatt-specific intervals.

        Args:
            schedule: Generic battery schedule
            current_hour: Current hour (0-23) to filter past hours

        """
        self.current_schedule = schedule
        self.current_hour = current_hour
        self._consolidate_and_convert()

    def initialize_from_tou_segments(self, tou_segments, current_hour=0):
        """Initialize GrowattScheduleManager with TOU intervals from the inverter.

        Args:
            tou_segments: List of TOU segments from the inverter
            current_hour: Current hour (0-23)

        """
        # Store current hour
        self.current_hour = current_hour

        # Store ALL TOU intervals exactly as they are, not just enabled ones
        self.tou_intervals = []

        for segment in tou_segments:
            # Get original segment ID
            segment_id = segment.get("segment_id")

            # Extract enabled status
            is_enabled = segment.get("enabled", False)

            # Process the batt_mode value which might be integer or string
            raw_batt_mode = segment.get("batt_mode")

            # Convert integer to string representation if needed
            if isinstance(raw_batt_mode, int):
                # Map integer values to string modes
                batt_mode_map = {0: "load-first", 1: "battery-first", 2: "grid-first"}
                batt_mode = batt_mode_map.get(raw_batt_mode, "battery-first")
            else:
                batt_mode = raw_batt_mode

            # Create TOU interval with original properties
            self.tou_intervals.append(
                {
                    "segment_id": segment_id,  # Keep original segment ID
                    "batt_mode": batt_mode,
                    "start_time": segment.get("start_time", "00:00"),
                    "end_time": segment.get("end_time", "23:59"),
                    "enabled": is_enabled,
                }
            )

        # Sort intervals by segment_id to maintain original order
        self.tou_intervals.sort(key=lambda x: x["segment_id"])

        # For logging display, we'll show only enabled intervals
        enabled_intervals = [seg for seg in self.tou_intervals if seg["enabled"]]

        # Log the TOU settings (showing only enabled ones for clarity)
        if enabled_intervals:
            self.log_current_TOU_schedule(
                "Creating schedule by reading time segments from inverter"
            )
        else:
            logger.info("No active TOU segments found in inverter")

    def compare_schedules(self, other_schedule, from_hour=0):
        """Compare this schedule with another GrowattScheduleManager.

        Args:
            other_schedule: Another GrowattScheduleManager to compare with
            from_hour: Hour to start comparison from (defaults to 0)

        Returns:
            (bool, str): (True if schedules differ, reason for difference)

        """
        # Get TOU settings from both schedules
        current_tou = self.tou_intervals
        new_tou = other_schedule.tou_intervals

        # Filter for TOU intervals that affect future hours
        current_future_tou = [
            segment
            for segment in current_tou
            if int(segment["start_time"].split(":")[0]) >= from_hour
        ]

        new_future_tou = [
            segment
            for segment in new_tou
            if int(segment["start_time"].split(":")[0]) >= from_hour
        ]

        # Compare number of intervals
        logger.debug(
            "Comparing schedules: current has %d future intervals, new has %d future intervals",
            len(current_future_tou),
            len(new_future_tou),
        )

        if len(current_future_tou) != len(new_future_tou):
            logger.info(
                "Schedules differ: current has %d future intervals, new has %d future intervals",
                len(current_future_tou),
                len(new_future_tou),
            )
            return (
                True,
                f"Different number of TOU intervals ({len(current_future_tou)} vs {len(new_future_tou)})",
            )

        # Compare TOU intervals
        for i, current_segment in enumerate(current_future_tou):
            if i >= len(new_future_tou):
                return True, "More current TOU intervals than new"

            new_segment = new_future_tou[i]

            # Compare detailed segment properties
            if current_segment["start_time"] != new_segment["start_time"]:
                logger.info(
                    "TOU interval %d start time differs: %s vs %s",
                    i,
                    current_segment["start_time"],
                    new_segment["start_time"],
                )
                return (
                    True,
                    f"TOU interval {i} start time differs: {current_segment['start_time']} -> {new_segment['start_time']}",
                )

            if current_segment["end_time"] != new_segment["end_time"]:
                logger.info(
                    "TOU interval %d end time differs: %s vs %s",
                    i,
                    current_segment["end_time"],
                    new_segment["end_time"],
                )
                return (
                    True,
                    f"TOU interval {i} end time differs: {current_segment['end_time']} -> {new_segment['end_time']}",
                )

            if current_segment["batt_mode"] != new_segment["batt_mode"]:
                logger.info(
                    "TOU interval %d battery mode differs: %s vs %s",
                    i,
                    current_segment["batt_mode"],
                    new_segment["batt_mode"],
                )
                return (
                    True,
                    f"TOU interval {i} battery mode differs: {current_segment['batt_mode']} -> {new_segment['batt_mode']}",
                )

        # Compare hourly settings for future hours
        hourly_differences = []
        for hour in range(from_hour, 24):
            current_settings = self.get_hourly_settings(hour)
            new_settings = other_schedule.get_hourly_settings(hour)

            if (
                current_settings["grid_charge"] != new_settings["grid_charge"]
                or current_settings["discharge_rate"] != new_settings["discharge_rate"]
            ):
                hourly_differences.append(hour)
                logger.info(
                    "Hour %d settings differ - grid_charge: %s->%s, discharge_rate: %d->%d",
                    hour,
                    current_settings["grid_charge"],
                    new_settings["grid_charge"],
                    current_settings["discharge_rate"],
                    new_settings["discharge_rate"],
                )

        if hourly_differences:
            return True, f"Hourly settings differ for hours: {hourly_differences}"

        return False, "Schedules match"

    def _consolidate_and_convert(self):
        """Convert hourly schedule to consolidated Growatt intervals."""
        if not self.current_schedule:
            return

        # Get hourly intervals from schedule
        hourly_intervals = self.current_schedule.get_daily_intervals()
        if not hourly_intervals:
            return

        logger.debug("Starting _consolidate_and_convert at hour %d", self.current_hour)

        # Log current intervals for debugging
        if hasattr(self, "tou_intervals"):
            logger.debug("Current TOU intervals before conversion:")
            for i, interval in enumerate(self.tou_intervals):
                logger.debug(
                    "  Interval %d: %s-%s, enabled=%s",
                    i,
                    interval["start_time"],
                    interval["end_time"],
                    interval["enabled"],
                )

        # Identify battery-first hours for FUTURE hours only
        battery_first_hours = []

        for hour in range(24):
            # Skip past hours completely - we only care about future
            if hour < self.current_hour:
                continue

            # Default to battery-first if no data
            is_battery_first = True

            # Check if we have interval data for this hour
            for interval in hourly_intervals:
                interval_hour = int(interval["start_time"].split(":")[0])
                if interval_hour == hour:
                    state = interval["state"]
                    is_battery_first = state != "discharging"
                    break

            if is_battery_first:
                battery_first_hours.append(hour)

        logger.debug("Battery-first hours for future: %s", battery_first_hours)

        # Critical fix: Don't override existing tou_intervals, create a new list
        # First, directly copy existing intervals
        old_intervals = []
        if hasattr(self, "tou_intervals"):
            old_intervals = self.tou_intervals.copy()

        # Initialize new tou_intervals list
        self.tou_intervals = []

        # Copy past intervals (completely in the past)
        for interval in old_intervals:
            end_hour = int(interval["end_time"].split(":")[0])
            if end_hour < self.current_hour and interval["enabled"]:
                logger.debug(
                    "Keeping past interval: %s-%s",
                    interval["start_time"],
                    interval["end_time"],
                )
                self.tou_intervals.append(interval.copy())

        logger.debug(
            "After copying past intervals, tou_intervals has %d intervals",
            len(self.tou_intervals),
        )

        # Process future battery-first hours
        if battery_first_hours:
            # Process consecutive periods
            consecutive_periods = []
            if battery_first_hours:
                current_period = [battery_first_hours[0]]

                for i in range(1, len(battery_first_hours)):
                    if battery_first_hours[i] == battery_first_hours[i - 1] + 1:
                        # Continue current period
                        current_period.append(battery_first_hours[i])
                    else:
                        # Start a new period
                        consecutive_periods.append(current_period)
                        current_period = [battery_first_hours[i]]

                # Add the last period
                consecutive_periods.append(current_period)

            logger.debug("Consecutive periods: %s", consecutive_periods)

            # Check which existing intervals contain or overlap with current hour
            active_intervals = []
            for interval in old_intervals:
                if not interval["enabled"]:
                    continue

                start_hour = int(interval["start_time"].split(":")[0])
                end_hour = int(interval["end_time"].split(":")[0])

                # Check if interval contains current hour
                if start_hour <= self.current_hour <= end_hour:
                    active_intervals.append(interval)
                    logger.debug(
                        "Found active interval for hour %d: %s-%s",
                        self.current_hour,
                        interval["start_time"],
                        interval["end_time"],
                    )

            # Now process each consecutive period, checking for overlaps with existing intervals
            for i, period in enumerate(consecutive_periods):
                if not period:
                    continue

                # Default settings for a new interval
                next_id = len(self.tou_intervals) + 1
                segment_id = next_id
                start_time = f"{period[0]:02d}:00"
                end_time = f"{period[-1]:02d}:59"

                # Check for overlaps with existing intervals from old_intervals
                has_overlap = False
                for interval in old_intervals:
                    if not interval["enabled"]:
                        continue

                    existing_start_hour = int(interval["start_time"].split(":")[0])
                    existing_end_hour = int(interval["end_time"].split(":")[0])

                    # Case 1: New period overlaps with start of existing interval
                    if (
                        period[0] <= existing_start_hour
                        and period[-1] >= existing_start_hour
                    ):
                        has_overlap = True
                        # Extend existing interval to start at period start
                        if period[0] < existing_start_hour:
                            segment_id = interval["segment_id"]
                            # We'll use the period's start and extend to the existing interval's end
                            end_time = interval["end_time"]
                            logger.debug(
                                "Extending interval %d backwards: now %s-%s",
                                segment_id,
                                start_time,
                                end_time,
                            )
                            break

                    # Case 2: New period overlaps with end of existing interval
                    if (
                        period[0] <= existing_end_hour
                        and period[-1] >= existing_end_hour
                    ):
                        has_overlap = True
                        # Extend existing interval to end at period end
                        if period[-1] > existing_end_hour:
                            segment_id = interval["segment_id"]
                            # We'll use the existing interval's start and extend to the period's end
                            start_time = interval["start_time"]
                            logger.debug(
                                "Extending interval %d forwards: now %s-%s",
                                segment_id,
                                start_time,
                                end_time,
                            )
                            break

                    # Case 3: New period is contained entirely within existing interval
                    if (
                        existing_start_hour <= period[0]
                        and existing_end_hour >= period[-1]
                    ):
                        has_overlap = True
                        # Just reuse the existing interval
                        segment_id = interval["segment_id"]
                        start_time = interval["start_time"]
                        end_time = interval["end_time"]
                        logger.debug(
                            "Reusing interval %d that contains period: %s-%s",
                            segment_id,
                            start_time,
                            end_time,
                        )
                        break

                    # Case 4: New period contains existing interval entirely
                    if (
                        period[0] <= existing_start_hour
                        and period[-1] >= existing_end_hour
                    ):
                        has_overlap = True
                        # Use the new larger boundaries but keep the segment ID
                        segment_id = interval["segment_id"]
                        logger.debug(
                            "Expanding interval %d to contain: now %s-%s",
                            segment_id,
                            start_time,
                            end_time,
                        )
                        break

                # If we have a current hour and it's in this period, prioritize using an active interval
                if self.current_hour in period and active_intervals:
                    # Use the first one if multiple
                    active_interval = active_intervals[0]
                    segment_id = active_interval["segment_id"]

                    # If the period starts earlier than the active interval, extend backward
                    if period[0] < int(active_interval["start_time"].split(":")[0]):
                        start_time = f"{period[0]:02d}:00"
                    else:
                        start_time = active_interval["start_time"]

                    # If the period ends later than the active interval, extend forward
                    if period[-1] > int(active_interval["end_time"].split(":")[0]):
                        end_time = f"{period[-1]:02d}:59"
                    else:
                        end_time = active_interval["end_time"]

                    logger.debug(
                        "Using active interval %d for current hour: now %s-%s",
                        segment_id,
                        start_time,
                        end_time,
                    )
                    has_overlap = True

                # Now create or add this interval
                if not has_overlap or not self.tou_intervals:
                    # This is a brand new non-overlapping interval or first interval
                    logger.debug(
                        "Creating new interval: id=%d, %s-%s",
                        segment_id,
                        start_time,
                        end_time,
                    )

                    self.tou_intervals.append(
                        {
                            "segment_id": segment_id,
                            "batt_mode": "battery-first",
                            "start_time": start_time,
                            "end_time": end_time,
                            "enabled": True,
                        }
                    )
                else:
                    # Check if this interval overlaps with any already in the new list
                    existing_index = None
                    for j, existing in enumerate(self.tou_intervals):
                        existing_start_hour = int(existing["start_time"].split(":")[0])
                        existing_end_hour = int(existing["end_time"].split(":")[0])

                        period_start_hour = int(start_time.split(":")[0])
                        period_end_hour = int(end_time.split(":")[0])

                        # Check for any kind of overlap
                        if (
                            period_start_hour <= existing_end_hour
                            and period_end_hour >= existing_start_hour
                        ):
                            existing_index = j
                            break

                    if existing_index is not None:
                        # Merge with existing interval
                        existing = self.tou_intervals[existing_index]

                        # Create the merged interval with the widest span
                        merged_start_hour = min(
                            int(start_time.split(":")[0]),
                            int(existing["start_time"].split(":")[0]),
                        )
                        merged_end_hour = max(
                            int(end_time.split(":")[0]),
                            int(existing["end_time"].split(":")[0]),
                        )

                        merged_interval = {
                            "segment_id": existing["segment_id"],
                            "batt_mode": "battery-first",
                            "start_time": f"{merged_start_hour:02d}:00",
                            "end_time": f"{merged_end_hour:02d}:59",
                            "enabled": True,
                        }

                        logger.debug(
                            "Merging intervals: %s-%s and %s-%s into %s-%s",
                            existing["start_time"],
                            existing["end_time"],
                            start_time,
                            end_time,
                            merged_interval["start_time"],
                            merged_interval["end_time"],
                        )

                        self.tou_intervals[existing_index] = merged_interval
                    else:
                        # Add as a separate non-overlapping interval
                        self.tou_intervals.append(
                            {
                                "segment_id": segment_id,
                                "batt_mode": "battery-first",
                                "start_time": start_time,
                                "end_time": end_time,
                                "enabled": True,
                            }
                        )

            logger.debug("Final tou_intervals count: %d", len(self.tou_intervals))

            # Apply max intervals limit if needed
            if len(self.tou_intervals) > self.max_intervals:
                logger.warning(
                    "Too many TOU intervals (%d), truncating to maximum (%d)",
                    len(self.tou_intervals),
                    self.max_intervals,
                )
                self.tou_intervals = self.tou_intervals[: self.max_intervals]

    def get_daily_TOU_settings(self):
        """Get Growatt-specific TOU settings (battery-first intervals only)."""
        if not self.tou_intervals:
            return []

        # Return only battery-first intervals up to max_intervals
        # Ensure segment_id values are sequential from 1
        result = []
        for i, interval in enumerate(self.tou_intervals[: self.max_intervals]):
            # Create a copy to avoid modifying the original
            segment = interval.copy()
            segment["segment_id"] = i + 1  # Sequential numbering from 1
            result.append(segment)

        return result

    def get_hourly_settings(self, hour):
        """Get Growatt-specific settings for a given hour."""
        if not self.current_schedule:
            return {"grid_charge": False, "discharge_rate": 0}

        settings = self.current_schedule.get_hour_settings(hour)
        discharge_rate = 100 if settings["state"] == "discharging" else 0

        return {
            "grid_charge": settings["state"] == "charging",
            "discharge_rate": discharge_rate,
        }

    def _log_growatt_schedule(self):
        """Log the current Growatt schedule with full details."""
        if not self.detailed_intervals:
            return

        col_widths = {
            "segment": 8,
            "start": 9,
            "end": 8,
            "mode": 15,
            "enabled": 8,
            "grid": 10,
            "discharge": 10,
        }
        total_width = (
            sum(col_widths.values()) + len(col_widths) - 1
        )  # -1 for last space

        header_format = (
            "{:>" + str(col_widths["segment"]) + "} "
            "{:>" + str(col_widths["start"]) + "} "
            "{:>" + str(col_widths["end"]) + "} "
            "{:>" + str(col_widths["mode"]) + "} "
            "{:>" + str(col_widths["enabled"]) + "} "
            "{:>" + str(col_widths["grid"]) + "} "
            "{:>" + str(col_widths["discharge"]) + "}"
        )

        lines = [
            "\n\nGrowatt Daily Schedule Overview:",
            "═" * total_width,
            header_format.format(
                "Segment",
                "StartTime",
                "EndTime",
                "BatteryMode",
                "Enabled",
                "GridChrg",
                "DischRate",
            ),
            "─" * total_width,
        ]

        interval_format = (
            "{segment_id:>" + str(col_widths["segment"]) + "} "
            "{start_time:>" + str(col_widths["start"]) + "} "
            "{end_time:>" + str(col_widths["end"]) + "} "
            "{batt_mode:>" + str(col_widths["mode"]) + "} "
            "{enabled!s:>" + str(col_widths["enabled"]) + "} "
            "{grid_charge!s:>" + str(col_widths["grid"]) + "} "
            "{discharge_rate:>" + str(col_widths["discharge"]) + "}"
        )
        formatted_intervals = [
            interval_format.format(**interval) for interval in self.detailed_intervals
        ]
        lines.extend(formatted_intervals)
        lines.append("═" * total_width)
        logger.info("\n".join(lines))

    def log_detailed_schedule(self, header=None):
        """Log a comprehensive view of the schedule with intervals and actions.

        Args:
            header: Optional header text to display before the schedule
        """
        if header:
            logger.info(header)

        if not self.current_schedule:
            logger.info("No schedule available")
            return

        # First, get all TOU intervals
        tou_settings = self.get_daily_TOU_settings()

        # Create hour-to-interval mapping
        hour_intervals = {}
        for interval in tou_settings:
            start_hour = int(interval["start_time"].split(":")[0])
            end_hour = int(interval["end_time"].split(":")[0])

            for hour in range(start_hour, end_hour + 1):
                hour_intervals[hour] = (
                    interval["batt_mode"] if interval["enabled"] else "load-first"
                )

        # Create a table with consolidated intervals based on settings
        lines = [
            "Consolidated Schedule:",
            "╔══════════════╦════════════════╦═════════════╦═══════════════╦════════════╗",
            "║    Period    ║  Battery Mode  ║ Grid Charge ║ Discharge Rate║   Action   ║",
            "╠══════════════╬════════════════╬═════════════╬═══════════════╬════════════╣",
        ]

        # Group hours by their settings
        consolidated_periods = []
        current_period = {
            "start_hour": 0,
            "batt_mode": hour_intervals.get(0, "load-first"),
            "settings": self.get_hourly_settings(0),
        }

        for hour in range(1, 24):
            batt_mode = hour_intervals.get(hour, "load-first")
            settings = self.get_hourly_settings(hour)

            # Check if settings have changed
            if (
                batt_mode != current_period["batt_mode"]
                or settings["grid_charge"] != current_period["settings"]["grid_charge"]
                or settings["discharge_rate"]
                != current_period["settings"]["discharge_rate"]
            ):
                # Save the completed period
                consolidated_periods.append(
                    {
                        "start_hour": current_period["start_hour"],
                        "end_hour": hour - 1,
                        "batt_mode": current_period["batt_mode"],
                        "settings": current_period["settings"],
                    }
                )

                # Start a new period
                current_period = {
                    "start_hour": hour,
                    "batt_mode": batt_mode,
                    "settings": settings,
                }

        # Add the last period
        consolidated_periods.append(
            {
                "start_hour": current_period["start_hour"],
                "end_hour": 23,
                "batt_mode": current_period["batt_mode"],
                "settings": current_period["settings"],
            }
        )

        # Display each consolidated period
        for period in consolidated_periods:
            start_hour = period["start_hour"]
            end_hour = period["end_hour"]
            batt_mode = period["batt_mode"]
            grid_charge = period["settings"]["grid_charge"]
            discharge_rate = period["settings"]["discharge_rate"]

            # Determine action
            if grid_charge:
                action = "CHARGE"
            elif discharge_rate > 0:
                action = "DISCHARGE"
            else:
                action = "IDLE"

            # Mark period containing current hour
            period_display = f"{start_hour:02d}:00-{end_hour:02d}:59"
            if start_hour <= self.current_hour <= end_hour:
                period_display += "*"

            # Format row
            row = (
                f"║ {period_display:12} ║"
                f" {batt_mode:14} ║"
                f" {str(grid_charge):11} ║"
                f" {discharge_rate:13} ║"
                f" {action:10} ║"
            )
            lines.append(row)

        lines.append(
            "╚══════════════╩════════════════╩═════════════╩═══════════════╩════════════╝"
        )
        lines.append("* indicates period containing current hour")

        logger.info("\n".join(lines))

    def log_current_TOU_schedule(self, header=None):
        """Log the final simplified TOU settings."""
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
                "Segment",
                "StartTime",
                "EndTime",
                "BatteryMode",
                "Enabled",
            ),
            "─" * total_width,
        ]

        # Ensure none of the values are None before formatting
        setting_format = (
            "{segment_id:>" + str(col_widths["segment"]) + "} "
            "{start_time:>" + str(col_widths["start"]) + "} "
            "{end_time:>" + str(col_widths["end"]) + "} "
            "{batt_mode:>" + str(col_widths["mode"]) + "} "
            "{enabled!s:>" + str(col_widths["enabled"]) + "}"
        )
        
        formatted_settings = []
        for setting in daily_settings:
            # Create a copy with None values replaced with empty strings
            safe_setting = {}
            for key, value in setting.items():
                safe_setting[key] = "" if value is None else value
            
            formatted_settings.append(setting_format.format(**safe_setting))
        
        if header:
            lines.insert(0, "\n" + header)
        lines.extend(formatted_settings)
        lines.append("═" * total_width)
        lines.append("\n")
        logger.info("\n".join(lines))

    def _log_hourly_settings(self):
        """Log the hourly settings for the current schedule."""
        if not self.current_schedule:
            logger.warning("No schedule available")
            return

        output = "\n -= Growatt Hourly Schedule =- \n"
        for h in range(24):
            settings = self.current_schedule.get_hour_settings(h)
            grid_charge_enabled = settings["state"] == "charging"
            discharge_rate = 100 if settings["state"] == "discharging" else 0
            output += f"Hour: {h:2d}, Grid Charge: {grid_charge_enabled}, Discharge Rate: {discharge_rate}\n"

        logger.info(output)
