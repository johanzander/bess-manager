"""Growatt schedule management module with strategic intent support.

Updated to use strategic intents from the DP algorithm for TOU and hourly controls.
"""

import logging

from .dp_schedule import DPSchedule
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class GrowattScheduleManager:
    """Creates Growatt-specific schedules using strategic intents from DP algorithm.

    This class manages the conversion between strategic intents and Growatt-specific
    Time of Use (TOU) intervals. It uses the strategic reasoning captured at decision
    time in the DP algorithm rather than analyzing energy flows afterward.

    Strategic Intent → Growatt Mode Mapping:
    - GRID_CHARGING → battery-first (enables AC charging)
    - SOLAR_STORAGE → battery-first (charging priority)
    - LOAD_SUPPORT → load-first (discharging priority)
    - EXPORT_ARBITRAGE → grid-first (export priority)
    - IDLE → load-first (normal operation)
    """

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the schedule manager with required battery settings for power calculations."""
        if battery_settings is None:
            raise ValueError("battery_settings is required and cannot be None")
        
        self.max_intervals = 9  # Growatt supports up to 9 TOU intervals
        self.current_schedule = None
        self.detailed_intervals = []  # For overview display
        self.tou_intervals = []  # For actual TOU settings
        self.current_hour = 0  # Track current hour
        self.hourly_settings = {}  # Pre-calculated settings for each hour (0-23)
        self.strategic_intents = []  # Store strategic intents from DP algorithm
        
        # Required battery settings for power calculations
        self.battery_settings = battery_settings
        self.max_charge_power_kw = battery_settings.max_charge_power_kw
        self.max_discharge_power_kw = battery_settings.max_discharge_power_kw

    def _calculate_power_rates_from_action(self, battery_action_kw: float, intent: str) -> tuple[int, int]:
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
            charge_rate = min(100, max(5, int((battery_action_kw / self.max_charge_power_kw) * 100)))
            
            # For grid charging, ensure minimum effective rate
            if intent == "GRID_CHARGING" and charge_rate < 20:
                charge_rate = 20  # Minimum 20% for effective grid charging
                
        elif battery_action_kw < -DISCHARGE_THRESHOLD:
            # Discharging action - calculate percentage of max discharge power
            discharge_power = abs(battery_action_kw)
            discharge_rate = min(100, max(5, int((discharge_power / self.max_discharge_power_kw) * 100)))
            
            # For export arbitrage, ensure high discharge rate
            if intent == "EXPORT_ARBITRAGE" and discharge_rate < 50:
                discharge_rate = max(50, discharge_rate)  # Minimum 50% for effective export
        
        return charge_rate, discharge_rate

    def _calculate_hourly_settings_with_strategic_intents(self):
        """Pre-calculate hourly settings using strategic intents and proper power rates."""
        self.hourly_settings = {}

        # REQUIRE strategic intents - no fallbacks
        if not self.strategic_intents or len(self.strategic_intents) < 24:
            raise ValueError(f"Missing strategic intents for hourly settings calculation. "
                            f"Expected 24, got {len(self.strategic_intents) if self.strategic_intents else 0}")

        for hour in range(24):
            intent = self.strategic_intents[hour]

            # Get battery action for this hour if available
            battery_action = 0.0
            if (
                self.current_schedule
                and self.current_schedule.actions
                and hour < len(self.current_schedule.actions)
            ):
                battery_action = self.current_schedule.actions[hour]

            # Calculate power rates from battery action
            charge_power_rate, discharge_power_rate = self._calculate_power_rates_from_action(
                battery_action, intent
            )

            # Determine settings based on strategic intent
            if intent == "GRID_CHARGING":
                grid_charge = True
                discharge_rate = 0
                charge_rate = charge_power_rate
                state = "charging"
                batt_mode = "battery-first" 

            elif intent == "SOLAR_STORAGE":
                grid_charge = False
                discharge_rate = 0
                charge_rate = 100
                state = "charging" if battery_action > 0.01 else "idle"
                batt_mode = "battery-first"

            elif intent == "LOAD_SUPPORT":
                grid_charge = False
                discharge_rate = 100
                charge_rate = 0
                state = "discharging"
                batt_mode = "load-first" 

            elif intent == "EXPORT_ARBITRAGE":
                grid_charge = False
                discharge_rate = discharge_power_rate
                charge_rate = 0
                state = "grid-first"
                batt_mode = "grid-first"

            elif intent == "IDLE":
                grid_charge = False
                discharge_rate = 0
                charge_rate = 100
                state = "idle"
                batt_mode = "load-first"
            else:
                raise ValueError(f"Unknown strategic intent at hour {hour}: {intent}")

            self.hourly_settings[hour] = {
                "grid_charge": grid_charge,
                "discharge_rate": discharge_rate,
                "charge_rate": charge_rate,
                "state": state,
                "batt_mode": batt_mode,
                "strategic_intent": intent,
                "battery_action": battery_action,
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

    def create_schedule(self, schedule: DPSchedule):
        """Process DPSchedule with strategic intents into Growatt format."""
        logger.info("Creating Growatt schedule using strategic intents from DP algorithm")

        # Always use strategic intents from DP algorithm - no fallbacks
        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        
        if len(self.strategic_intents) != 24:
            raise ValueError(f"Expected 24 strategic intents, got {len(self.strategic_intents)}")

        logger.info(f"Using {len(self.strategic_intents)} strategic intents from DP algorithm")

        # Log intent transitions
        for hour in range(1, len(self.strategic_intents)):
            if self.strategic_intents[hour] != self.strategic_intents[hour - 1]:
                logger.info(
                    "Intent transition at hour %02d: %s → %s",
                    hour,
                    self.strategic_intents[hour - 1],
                    self.strategic_intents[hour],
                )

        self.current_schedule = schedule
        self._consolidate_and_convert_with_strategic_intents()
        self._calculate_hourly_settings_with_strategic_intents()

        logger.info(
            "New Growatt schedule created with %d TOU intervals based on strategic intents",
            len(self.tou_intervals),
        )

    def _consolidate_and_convert_with_strategic_intents(self):
        """Convert strategic intents to TOU intervals."""
        logger.info("=== TOU CONVERSION START ===")

        if not self.strategic_intents:
            logger.warning(
                "No strategic intents available, falling back to action-based analysis"
            )
            self._consolidate_and_convert_fallback()
            return

        logger.info(
            "Converting %d strategic intents to TOU intervals from hour %d",
            len(self.strategic_intents),
            self.current_hour,
        )

        # Map strategic intents to battery modes
        intent_to_mode = {
            "GRID_CHARGING": "battery-first",  # Enable AC charging for arbitrage
            "SOLAR_STORAGE": "battery-first",  # Priority to battery charging from solar
            "LOAD_SUPPORT": "load-first",  # Priority to battery discharge for load
            "EXPORT_ARBITRAGE": "grid-first",  # Priority to grid export for profit
            "IDLE": "load-first",  # Normal load-first operation
        }

        # Initialize new TOU intervals
        old_intervals = getattr(self, "tou_intervals", []).copy()
        self.tou_intervals = []

        # Copy past intervals (completely in the past)
        past_intervals_copied = 0
        for interval in old_intervals:
            end_hour = int(interval["end_time"].split(":")[0])
            if end_hour < self.current_hour and interval["enabled"]:
                logger.debug(
                    "Keeping past interval: %s-%s",
                    interval["start_time"],
                    interval["end_time"],
                )
                self.tou_intervals.append(interval.copy())
                past_intervals_copied += 1

        logger.info("Copied %d past intervals", past_intervals_copied)

        # Group consecutive hours by battery mode
        mode_periods = []
        current_mode = None
        current_period_start = None

        for hour in range(self.current_hour, 24):
            if hour < len(self.strategic_intents):
                intent = self.strategic_intents[hour]
                hour_mode = intent_to_mode.get(intent, "load-first")

                logger.debug("Hour %02d: intent=%s → mode=%s", hour, intent, hour_mode)

                if hour_mode != current_mode:
                    # Save previous period if exists
                    if current_mode is not None and current_period_start is not None:
                        mode_periods.append(
                            {
                                "mode": current_mode,
                                "start_hour": current_period_start,
                                "end_hour": hour - 1,
                                "intent_summary": self._get_period_intent_summary(
                                    current_period_start, hour - 1
                                ),
                            }
                        )

                    # Start new period
                    current_mode = hour_mode
                    current_period_start = hour

        # Add final period
        if current_mode is not None and current_period_start is not None:
            mode_periods.append(
                {
                    "mode": current_mode,
                    "start_hour": current_period_start,
                    "end_hour": 23,
                    "intent_summary": self._get_period_intent_summary(
                        current_period_start, 23
                    ),
                }
            )

        logger.info("Strategic intent-based mode periods: %s", mode_periods)

        # Create TOU intervals for non-load-first modes
        for period in mode_periods:
            if period["mode"] in ["battery-first", "grid-first"]:
                # Find next available segment ID
                used_ids = {interval["segment_id"] for interval in self.tou_intervals}
                segment_id = 1
                while segment_id in used_ids:
                    segment_id += 1

                start_time = f"{period['start_hour']:02d}:00"
                end_time = f"{period['end_hour']:02d}:59"

                self.tou_intervals.append(
                    {
                        "segment_id": segment_id,
                        "batt_mode": period["mode"],
                        "start_time": start_time,
                        "end_time": end_time,
                        "enabled": True,
                    }
                )

                logger.info(
                    "Created TOU interval #%d: %s-%s (%s) based on strategic intents: %s",
                    segment_id,
                    start_time,
                    end_time,
                    period["mode"],
                    period["intent_summary"],
                )

        # Apply max intervals limit
        if len(self.tou_intervals) > self.max_intervals:
            logger.warning(
                "Too many TOU intervals (%d), truncating to maximum (%d)",
                len(self.tou_intervals),
                self.max_intervals,
            )
            self.tou_intervals = self.tou_intervals[: self.max_intervals]

        logger.info(
            "TOU conversion complete: %d total intervals", len(self.tou_intervals)
        )
        logger.info("=== TOU CONVERSION END ===")

    def _get_period_intent_summary(self, start_hour: int, end_hour: int) -> str:
        """Get a summary of intents for a period."""
        if not self.strategic_intents:
            return "unknown"

        period_intents = []
        for hour in range(start_hour, min(end_hour + 1, len(self.strategic_intents))):
            if hour < len(self.strategic_intents):
                period_intents.append(self.strategic_intents[hour])

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

        # Create simple TOU intervals for battery-first hours
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
                        "batt_mode": "battery-first",
                        "start_time": start_time,
                        "end_time": end_time,
                        "enabled": True,
                    }
                )

    def get_hourly_settings(self, hour):
        if hour not in self.hourly_settings:
            raise ValueError(f"No hourly settings for hour {hour}. Strategic intents: {len(self.strategic_intents)}, Settings calculated: {len(self.hourly_settings)}")
        
        return self.hourly_settings[hour]

    def get_strategic_intent_summary(self) -> dict:
        """Get a summary of strategic intents for the day."""
        if not self.strategic_intents:
            return {}

        intent_hours = {}
        for hour, intent in enumerate(self.strategic_intents):
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

    def compare_schedules(self, other_schedule, from_hour=0):
        """Enhanced schedule comparison - TOU intervals only (what's actually in the inverter)."""
        logger.info(f"Comparing TOU intervals from hour {from_hour:02d}:00 onwards")

        # Get TOU intervals
        current_tou = self.get_daily_TOU_settings()
        new_tou = other_schedule.get_daily_TOU_settings()

        logger.info(f"Current schedule has {len(current_tou)} TOU intervals")
        logger.info(f"New schedule has {len(new_tou)} TOU intervals")

        # Find relevant intervals (from current hour onwards)
        relevant_current = []
        relevant_new = []

        for interval in current_tou:
            start_hour = int(interval["start_time"].split(":")[0])
            end_hour = int(interval["end_time"].split(":")[0])
            if (start_hour >= from_hour or end_hour >= from_hour) and interval.get(
                "enabled", True
            ):
                relevant_current.append(interval)

        for interval in new_tou:
            start_hour = int(interval["start_time"].split(":")[0])
            end_hour = int(interval["end_time"].split(":")[0])
            if (start_hour >= from_hour or end_hour >= from_hour) and interval.get(
                "enabled", True
            ):
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
                batt_mode_map = {0: "load-first", 1: "battery-first", 2: "grid-first"}
                batt_mode = batt_mode_map.get(raw_batt_mode, "battery-first")
            else:
                batt_mode = raw_batt_mode

            self.tou_intervals.append(
                {
                    "segment_id": segment_id,
                    "batt_mode": batt_mode,
                    "start_time": segment.get("start_time", "00:00"),
                    "end_time": segment.get("end_time", "23:59"),
                    "enabled": is_enabled,
                }
            )

        self.tou_intervals.sort(key=lambda x: x["segment_id"])
        # NO INTENT INFERENCE - leave hourly_settings empty until we get strategic intents

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
        for i, interval in enumerate(self.tou_intervals[: self.max_intervals]):
            segment = interval.copy()
            segment["segment_id"] = i + 1
            result.append(segment)

        return result

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
        """Log comprehensive schedule view with strategic intents and power rates."""
        if header:
            logger.info(header)

        if not self.current_schedule:
            logger.info("No schedule available")
            return

        lines = [
            "\n╔════╦══════════════════╦═══════════════╦═════════════╦═══════════════╦═══════════════╦═══════════════════════════════╗",
            "║ Hr ║ Strategic Intent ║ Battery Mode  ║ Grid Charge ║ Charge Rate % ║Discharge Rate%║         Description           ║",
            "╠════╬══════════════════╬═══════════════╬═════════════╬═══════════════╬═══════════════╬═══════════════════════════════╣",
        ]

        for hour in range(24):
            settings = self.get_hourly_settings(hour)
            intent = settings.get("strategic_intent", "IDLE")
            batt_mode = settings.get("batt_mode", "load-first")
            grid_charge = settings.get("grid_charge", False)
            charge_rate = settings.get("charge_rate", 0)
            discharge_rate = settings.get("discharge_rate", 0)
            battery_action_kw = settings.get("battery_action_kw", 0.0)
            description = self._get_intent_description(intent)

            # Mark current hour
            hour_marker = "*" if hour == self.current_hour else " "

            # Add battery action info to description showing both rates
            if abs(battery_action_kw) > 0.01:
                if battery_action_kw > 0:
                    description += f" ({battery_action_kw:.1f}kW→{charge_rate}%C)"
                else:
                    description += f" ({abs(battery_action_kw):.1f}kW→{discharge_rate}%D)"
            elif charge_rate > 0 or discharge_rate > 0:
                # Show rates even if no significant action (edge cases)
                if charge_rate > 0:
                    description += f" (C:{charge_rate}%)"
                if discharge_rate > 0:
                    description += f" (D:{discharge_rate}%)"

            row = (
                f"║{hour:02d}{hour_marker}║ {intent:17} ║ {batt_mode:13} ║"
                f" {grid_charge!s:11} ║ {charge_rate:13} ║ {discharge_rate:13} ║ {description[:29]:29} ║"
            )
            lines.append(row)

        lines.append(
            "╚═══╩═══════════════════╩═══════════════╩═════════════╩═══════════════╩═══════════════╩═══════════════════════════════╝"
        )
        lines.append("* indicates current hour")
        lines.append("C=Charge%, D=Discharge% (kW→% shows DP action converted to hardware percentage)")

        logger.info("\n".join(lines))
