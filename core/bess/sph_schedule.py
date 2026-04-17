"""SPH inverter schedule management module.

Growatt SPH inverters use a fundamentally different scheduling model from MIN inverters.
Instead of 9 TOU segments with per-segment modes, SPH uses separate charge and discharge
period lists (max 3 each) with global power and SOC settings per call.

SPH Intent Mapping:
- GRID_CHARGING   → charge period (mains_enabled=True)
- SOLAR_STORAGE   → idle (SPH charges from solar by default; no explicit period needed)
- LOAD_SUPPORT    → discharge period
- EXPORT_ARBITRAGE → discharge period
- IDLE            → nothing (inverter default)
"""

import logging
from datetime import datetime
from typing import ClassVar

from . import time_utils
from .dp_schedule import DPSchedule
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class SphScheduleManager:
    """Creates Growatt SPH inverter schedules from strategic intents.

    SPH inverters support separate charge and discharge period lists (max 3 each)
    with global power percentage and SOC settings per write call.

    This class mirrors the public interface of GrowattScheduleManager so that
    BatterySystemManager can use either interchangeably via duck typing.
    """

    MAX_CHARGE_PERIODS = 3
    MAX_DISCHARGE_PERIODS = 3

    # Intents that produce a charge period on SPH
    # SOLAR_STORAGE is excluded — SPH charges from solar by default without an explicit period.
    CHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset({"GRID_CHARGING"})

    # Intents that produce a discharge period on SPH
    DISCHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset(
        {"LOAD_SUPPORT", "EXPORT_ARBITRAGE"}
    )

    INTENT_TO_MODE: ClassVar[dict[str, str]] = {
        "GRID_CHARGING": "battery_first",
        "SOLAR_STORAGE": "battery_first",
        "LOAD_SUPPORT": "load_first",
        "EXPORT_ARBITRAGE": "grid_first",
        "IDLE": "load_first",
    }

    # Map strategic intents to inverter control settings (used for hourly_settings)
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
        """Initialize the SPH schedule manager."""
        if battery_settings is None:
            raise ValueError("battery_settings is required and cannot be None")

        self.battery_settings = battery_settings
        self.max_charge_power_kw = battery_settings.max_charge_power_kw
        self.max_discharge_power_kw = battery_settings.max_discharge_power_kw

        self.current_schedule: DPSchedule | None = None
        self.strategic_intents: list[str] = []
        self.tou_intervals: list[dict] = []
        self.hourly_settings: dict[int, dict] = {}

        # SPH always does a full rewrite — no corruption concept
        self.corruption_detected: bool = False

        # Internal period lists (≤3 each)
        self._charge_periods: list[dict] = []
        self._discharge_periods: list[dict] = []

    @property
    def active_tou_intervals(self) -> list[dict]:
        """All TOU intervals are active for SPH (no 9-slot hardware constraint)."""
        return self.tou_intervals

    # ── Period utility ────────────────────────────────────────────────────────

    def _period_to_time(self, period: int) -> tuple[int, int]:
        """Convert period number (0-95) to (hour, minute)."""
        return period // 4, (period % 4) * 15

    # ── SPH period grouping ───────────────────────────────────────────────────

    def _group_sph_periods(self) -> tuple[list[dict], list[dict]]:
        """Group consecutive strategic intent periods into charge and discharge blocks.

        Returns:
            Tuple of (charge_blocks, discharge_blocks) where each block is a dict with
            keys 'start_period', 'end_period', and 'intents'.
        """
        if not self.strategic_intents:
            return [], []

        charge_blocks: list[dict] = []
        discharge_blocks: list[dict] = []

        for _category, target_list, intent_set in [
            ("charge", charge_blocks, self.CHARGE_INTENTS),
            ("discharge", discharge_blocks, self.DISCHARGE_INTENTS),
        ]:
            current_block: dict | None = None

            for period, intent in enumerate(self.strategic_intents):
                if intent in intent_set:
                    if current_block is None:
                        current_block = {
                            "start_period": period,
                            "end_period": period,
                            "intents": [intent],
                        }
                    else:
                        current_block["end_period"] = period
                        current_block["intents"].append(intent)
                else:
                    if current_block is not None:
                        target_list.append(current_block)
                        current_block = None

            if current_block is not None:
                target_list.append(current_block)

        return charge_blocks, discharge_blocks

    def _enforce_period_limit(self, blocks: list[dict], max_periods: int) -> list[dict]:
        """Enforce maximum period count by dropping shortest blocks.

        Args:
            blocks: List of period blocks
            max_periods: Maximum allowed blocks

        Returns:
            Trimmed list of at most max_periods blocks
        """
        if len(blocks) <= max_periods:
            return blocks

        logger.warning(
            "SPH PERIOD LIMIT EXCEEDED: %d blocks, maximum is %d — dropping shortest",
            len(blocks),
            max_periods,
        )

        def block_duration(b: dict) -> int:
            return b["end_period"] - b["start_period"] + 1

        # Keep the longest blocks, sorted by original order
        sorted_by_duration = sorted(blocks, key=block_duration, reverse=True)
        kept = sorted_by_duration[:max_periods]
        dropped = sorted_by_duration[max_periods:]

        for b in dropped:
            sh, sm = self._period_to_time(b["start_period"])
            eh, em = self._period_to_time(b["end_period"])
            logger.warning(
                "  DROPPED: %02d:%02d-%02d:%02d (%d periods) intents=%s",
                sh,
                sm,
                eh,
                em + 14,
                block_duration(b),
                b["intents"],
            )

        # Return kept blocks in chronological order
        return sorted(kept, key=lambda b: b["start_period"])

    def _blocks_to_period_dicts(self, blocks: list[dict]) -> list[dict]:
        """Convert period blocks to time-string dicts for hardware and display.

        Args:
            blocks: List of period blocks from _group_sph_periods

        Returns:
            List of dicts with 'start_time', 'end_time', 'enabled' keys
        """
        result = []
        for block in blocks:
            sh, sm = self._period_to_time(block["start_period"])
            eh, em = self._period_to_time(block["end_period"])

            # Cap end time to 23:59
            if sh >= 24:
                continue  # Skip DST fall-back periods beyond 23:59
            if eh >= 24:
                eh, em = 23, 59
            else:
                em += 14  # Last minute of the 15-min period

            result.append(
                {
                    "start_time": f"{sh:02d}:{sm:02d}",
                    "end_time": f"{eh:02d}:{em:02d}",
                    "enabled": True,
                }
            )
        return result

    # ── Schedule building ─────────────────────────────────────────────────────

    def _build_sph_periods(self) -> None:
        """Build charge and discharge period lists from strategic intents."""
        charge_blocks, discharge_blocks = self._group_sph_periods()

        charge_blocks = self._enforce_period_limit(
            charge_blocks, self.MAX_CHARGE_PERIODS
        )
        discharge_blocks = self._enforce_period_limit(
            discharge_blocks, self.MAX_DISCHARGE_PERIODS
        )

        self._charge_periods = self._blocks_to_period_dicts(charge_blocks)
        self._discharge_periods = self._blocks_to_period_dicts(discharge_blocks)

        # Build unified tou_intervals for dashboard display
        self.tou_intervals = []
        for p in self._charge_periods:
            self.tou_intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "batt_mode": "battery_first",
                    "enabled": True,
                    "strategic_intent": "GRID_CHARGING",
                }
            )
        for p in self._discharge_periods:
            self.tou_intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "batt_mode": "grid_first",
                    "enabled": True,
                    "strategic_intent": "LOAD_SUPPORT/EXPORT_ARBITRAGE",
                }
            )
        # Sort by start time for display
        self.tou_intervals.sort(key=lambda x: x["start_time"])

        logger.info(
            "SPH periods built: %d charge period(s), %d discharge period(s)",
            len(self._charge_periods),
            len(self._discharge_periods),
        )
        for p in self._charge_periods:
            logger.info("  Charge:    %s-%s", p["start_time"], p["end_time"])
        for p in self._discharge_periods:
            logger.info("  Discharge: %s-%s", p["start_time"], p["end_time"])

    def _calculate_hourly_settings(self) -> None:
        """Pre-calculate hourly settings from strategic intents."""
        self.hourly_settings = {}

        if not self.strategic_intents:
            raise ValueError(
                "Missing strategic intents for hourly settings calculation"
            )

        num_periods = len(self.strategic_intents)
        num_hours = (num_periods + 3) // 4

        for hour in range(num_hours):
            # Dominant intent for this hour
            start_p = hour * 4
            end_p = min(start_p + 4, num_periods)
            period_intents = [self.strategic_intents[p] for p in range(start_p, end_p)]

            intent_counts: dict[str, int] = {}
            for intent in period_intents:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
            max_count = max(intent_counts.values())
            candidates = [i for i, c in intent_counts.items() if c == max_count]
            dominant_intent = min(candidates)

            control = self.INTENT_TO_CONTROL[dominant_intent]

            self.hourly_settings[hour] = {
                "grid_charge": control["grid_charge"],
                "charge_rate": control["charge_rate"],
                "discharge_rate": control["discharge_rate"],
                "strategic_intent": dominant_intent,
                "state": (
                    "charging"
                    if dominant_intent in ("GRID_CHARGING", "SOLAR_STORAGE")
                    else (
                        "discharging"
                        if dominant_intent in ("LOAD_SUPPORT", "EXPORT_ARBITRAGE")
                        else "idle"
                    )
                ),
                "batt_mode": (
                    "battery_first"
                    if dominant_intent in ("GRID_CHARGING", "SOLAR_STORAGE")
                    else (
                        "grid_first"
                        if dominant_intent == "EXPORT_ARBITRAGE"
                        else "load_first"
                    )
                ),
                "battery_action_kw": 0.0,
            }

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Process DPSchedule with strategic intents into SPH format.

        Args:
            schedule: DPSchedule containing strategic_intent list in original_dp_results
        """
        logger.info("Creating SPH schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        logger.info(
            "Using %d strategic intents (quarterly resolution)",
            len(self.strategic_intents),
        )

        self._build_sph_periods()
        self._calculate_hourly_settings()

        logger.info(
            "SPH schedule created: %d charge period(s), %d discharge period(s), "
            "%d display intervals",
            len(self._charge_periods),
            len(self._discharge_periods),
            len(self.tou_intervals),
        )

    # ── Hardware interface ────────────────────────────────────────────────────

    def write_schedule_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        """Write SPH charge and discharge periods to hardware.

        SPH always does a full rewrite (no differential update). Both charge
        and discharge calls are issued regardless of what was set before.

        Args:
            controller: HomeAssistantAPIController instance
            effective_period: Unused for SPH (full rewrite each time)
            current_tou: Unused for SPH (full rewrite each time)

        Returns:
            Tuple of (writes, disables) — always (2, 0) for SPH
        """
        charge_power = 100  # Full power percentage
        discharge_power = 100

        charge_stop_soc = int(self.battery_settings.max_soc)
        discharge_stop_soc = int(self.battery_settings.min_soc)

        charge_params = self._build_charge_params()
        discharge_params = self._build_discharge_params()
        mains_enabled = len(self._charge_periods) > 0

        logger.info(
            "SPH HARDWARE: Writing charge periods (power=%d%%, stop_soc=%d%%, mains=%s): %s",
            charge_power,
            charge_stop_soc,
            mains_enabled,
            self._charge_periods,
        )
        controller.write_ac_charge_times(
            charge_power=charge_power,
            charge_stop_soc=charge_stop_soc,
            mains_enabled=mains_enabled,
            **charge_params,
        )

        logger.info(
            "SPH HARDWARE: Writing discharge periods (power=%d%%, stop_soc=%d%%): %s",
            discharge_power,
            discharge_stop_soc,
            self._discharge_periods,
        )
        controller.write_ac_discharge_times(
            discharge_power=discharge_power,
            discharge_stop_soc=discharge_stop_soc,
            **discharge_params,
        )

        return 2, 0

    def _build_charge_params(self) -> dict[str, object]:
        """Build flat charge period params for write_ac_charge_times."""
        params: dict[str, object] = {}
        for i in range(self.MAX_CHARGE_PERIODS):
            n = i + 1
            if i < len(self._charge_periods):
                p = self._charge_periods[i]
                params[f"period_{n}_start"] = p["start_time"]
                params[f"period_{n}_end"] = p["end_time"]
                params[f"period_{n}_enabled"] = True
            else:
                params[f"period_{n}_enabled"] = False
        return params

    def _build_discharge_params(self) -> dict[str, object]:
        """Build flat discharge period params for write_ac_discharge_times."""
        params: dict[str, object] = {}
        for i in range(self.MAX_DISCHARGE_PERIODS):
            n = i + 1
            if i < len(self._discharge_periods):
                p = self._discharge_periods[i]
                params[f"period_{n}_start"] = p["start_time"]
                params[f"period_{n}_end"] = p["end_time"]
                params[f"period_{n}_enabled"] = True
            else:
                params[f"period_{n}_enabled"] = False
        return params

    def sync_soc_limits(self, controller) -> None:
        """Sync SOC limits from config to inverter hardware.

        Reads current charge/discharge stop SOC from the inverter and writes
        back only if they differ from the configured max_soc / min_soc.
        Requires read_and_initialize_from_hardware() to have been called first
        so that cached periods are available for the write.
        """
        configured_max_soc = int(self.battery_settings.max_soc)
        configured_min_soc = int(self.battery_settings.min_soc)

        charge_result = controller.read_ac_charge_times()
        if not charge_result or "charge_stop_soc" not in charge_result:
            raise RuntimeError(
                f"read_ac_charge_times returned unexpected data — cannot sync SOC limits: {charge_result!r}"
            )

        discharge_result = controller.read_ac_discharge_times()
        if not discharge_result or "discharge_stop_soc" not in discharge_result:
            raise RuntimeError(
                f"read_ac_discharge_times returned unexpected data — cannot sync SOC limits: {discharge_result!r}"
            )

        actual_charge_soc = charge_result["charge_stop_soc"]
        actual_discharge_soc = discharge_result["discharge_stop_soc"]

        charge_mismatch = actual_charge_soc != configured_max_soc
        discharge_mismatch = actual_discharge_soc != configured_min_soc

        if not charge_mismatch and not discharge_mismatch:
            logger.info(
                "SOC limits verified: charge_stop=%d%%, discharge_stop=%d%%",
                configured_max_soc,
                configured_min_soc,
            )
            return

        logger.info(
            "SOC limit mismatch — config: charge_stop=%d%%, discharge_stop=%d%% | "
            "inverter: charge_stop=%s%%, discharge_stop=%s%% — syncing",
            configured_max_soc,
            configured_min_soc,
            actual_charge_soc,
            actual_discharge_soc,
        )

        if charge_mismatch:
            controller.write_ac_charge_times(
                charge_power=100,
                charge_stop_soc=configured_max_soc,
                mains_enabled=len(self._charge_periods) > 0,
                **self._build_charge_params(),
            )
            logger.info("Set charge_stop_soc to %d%%", configured_max_soc)

        if discharge_mismatch:
            controller.write_ac_discharge_times(
                discharge_power=100,
                discharge_stop_soc=configured_min_soc,
                **self._build_discharge_params(),
            )
            logger.info("Set discharge_stop_soc to %d%%", configured_min_soc)

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Read current SPH schedule from inverter and initialize this manager.

        Args:
            controller: HomeAssistantAPIController instance
            current_hour: Current hour (0-23)
        """
        logger.info("Reading SPH charge/discharge times from inverter")

        charge_result = controller.read_ac_charge_times()
        discharge_result = controller.read_ac_discharge_times()

        self._charge_periods = []
        self._discharge_periods = []

        # Parse charge periods
        if charge_result and "periods" in charge_result:
            for period in charge_result["periods"]:
                if period.get("enabled", False):
                    self._charge_periods.append(
                        {
                            "start_time": period.get("start_time", "00:00"),
                            "end_time": period.get("end_time", "23:59"),
                            "enabled": True,
                        }
                    )

        # Parse discharge periods
        if discharge_result and "periods" in discharge_result:
            for period in discharge_result["periods"]:
                if period.get("enabled", False):
                    self._discharge_periods.append(
                        {
                            "start_time": period.get("start_time", "00:00"),
                            "end_time": period.get("end_time", "23:59"),
                            "enabled": True,
                        }
                    )

        # Build display intervals
        self.tou_intervals = []
        for p in self._charge_periods:
            self.tou_intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "batt_mode": "battery_first",
                    "enabled": True,
                    "strategic_intent": "existing_schedule",
                }
            )
        for p in self._discharge_periods:
            self.tou_intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "batt_mode": "grid_first",
                    "enabled": True,
                    "strategic_intent": "existing_schedule",
                }
            )
        self.tou_intervals.sort(key=lambda x: x["start_time"])

        logger.info(
            "SPH initialized from hardware: %d charge period(s), %d discharge period(s)",
            len(self._charge_periods),
            len(self._discharge_periods),
        )

    # ── Schedule comparison ───────────────────────────────────────────────────

    def compare_schedules(
        self, other_schedule: "SphScheduleManager", from_period: int = 0
    ) -> tuple[bool, str]:
        """Compare SPH periods with another schedule manager.

        Args:
            other_schedule: Another SphScheduleManager to compare against
            from_period: Comparison start period (informational for SPH)

        Returns:
            Tuple of (schedules_differ, reason)
        """
        current_charge = self._charge_periods
        new_charge = other_schedule._charge_periods
        current_discharge = self._discharge_periods
        new_discharge = other_schedule._discharge_periods

        def _periods_equal(a: list[dict], b: list[dict]) -> bool:
            if len(a) != len(b):
                return False
            for pa, pb in zip(a, b, strict=False):
                if (
                    pa.get("start_time") != pb.get("start_time")
                    or pa.get("end_time") != pb.get("end_time")
                    or pa.get("enabled") != pb.get("enabled")
                ):
                    return False
            return True

        if not _periods_equal(current_charge, new_charge):
            logger.info(
                "DECISION: SPH charge periods differ — current=%s new=%s",
                current_charge,
                new_charge,
            )
            return True, "SPH charge periods differ"

        if not _periods_equal(current_discharge, new_discharge):
            logger.info(
                "DECISION: SPH discharge periods differ — current=%s new=%s",
                current_discharge,
                new_discharge,
            )
            return True, "SPH discharge periods differ"

        logger.info("DECISION: SPH schedules match")
        return False, ""

    # ── Hourly settings ───────────────────────────────────────────────────────

    def get_hourly_settings(self, hour: int) -> dict:
        """Get pre-calculated settings for a specific hour.

        Args:
            hour: Hour (0-23)

        Returns:
            Dict with grid_charge, charge_rate, discharge_rate, state, batt_mode, etc.

        Raises:
            ValueError: If hourly settings not calculated yet for this hour
        """
        if hour not in self.hourly_settings:
            raise ValueError(
                f"No hourly settings for hour {hour}. "
                f"Strategic intents: {len(self.strategic_intents)}, "
                f"Settings calculated: {len(self.hourly_settings)}"
            )
        return self.hourly_settings[hour]

    # ── TOU display ───────────────────────────────────────────────────────────

    def get_daily_TOU_settings(self) -> list[dict]:
        """Return tou_intervals for display/API consumption."""
        return list(self.tou_intervals)

    def log_current_TOU_schedule(self, header: str = "") -> None:
        """Log current SPH charge/discharge periods."""
        if header:
            logger.info(header)

        if not self._charge_periods and not self._discharge_periods:
            logger.info("SPH: No active charge or discharge periods")
            return

        logger.info(" -= SPH Schedule =-")
        for i, p in enumerate(self._charge_periods, 1):
            logger.info(
                "  Charge  period %d: %s-%s (mains_enabled=True)",
                i,
                p["start_time"],
                p["end_time"],
            )
        for i, p in enumerate(self._discharge_periods, 1):
            logger.info(
                "  Discharge period %d: %s-%s",
                i,
                p["start_time"],
                p["end_time"],
            )

    def log_detailed_schedule(self, header: str = "") -> None:
        """Log detailed schedule with per-period strategic intents."""
        if header:
            logger.info(header)

        if not self.strategic_intents:
            logger.info("SPH: No schedule data available")
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        lines = [
            "\n╔═══════════════╦══════════════════╦═══════════════╗",
            "║  Time Period  ║ Strategic Intent ║  SPH Action   ║",
            "╠═══════════════╬══════════════════╬═══════════════╣",
        ]

        num_periods = len(self.strategic_intents)
        period = 0
        while period < num_periods:
            intent = self.strategic_intents[period]
            # Group consecutive same-intent periods
            run_start = period
            while (
                period + 1 < num_periods
                and self.strategic_intents[period + 1] == intent
            ):
                period += 1
            run_end = period

            sh, sm = run_start // 4, (run_start % 4) * 15
            eh, em = run_end // 4, (run_end % 4) * 15
            em += 14

            time_range = f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"
            is_current = run_start <= current_period <= run_end
            marker = "*" if is_current else " "

            if intent in self.CHARGE_INTENTS:
                action = "charge"
            elif intent in self.DISCHARGE_INTENTS:
                action = "discharge"
            else:
                action = "idle"

            lines.append(f"║{marker}{time_range:13} ║ {intent:16} ║ {action:13} ║")
            period += 1

        lines.append("╚═══════════════╩══════════════════╩═══════════════╝")
        lines.append("* indicates current period")

        logger.info("\n".join(lines))

    # ── API / display methods ─────────────────────────────────────────────────

    def get_all_tou_segments(self) -> list[dict]:
        """Return TOU intervals for API/display consumption."""
        if not self.tou_intervals:
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
        return list(self.tou_intervals)

    def get_strategic_intent_summary(self) -> dict:
        """Get a summary of strategic intents for the day (aggregated from quarterly periods)."""
        if not self.strategic_intents:
            return {}

        num_periods = len(self.strategic_intents)
        num_hours = (num_periods + 3) // 4

        intent_hours: dict[str, list[int]] = {}
        for hour in range(num_hours):
            start_p = hour * 4
            end_p = min(start_p + 4, num_periods)
            period_intents = [self.strategic_intents[p] for p in range(start_p, end_p)]

            intent_counts: dict[str, int] = {}
            for intent in period_intents:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
            max_count = max(intent_counts.values())
            dominant = min(i for i, c in intent_counts.items() if c == max_count)

            if dominant not in intent_hours:
                intent_hours[dominant] = []
            intent_hours[dominant].append(hour)

        descriptions = {
            "GRID_CHARGING": "Storing cheap grid energy for later use",
            "SOLAR_STORAGE": "Storing excess solar energy for evening/night",
            "LOAD_SUPPORT": "Using battery to support home consumption",
            "EXPORT_ARBITRAGE": "Selling stored energy to grid for profit",
            "IDLE": "No significant battery activity",
        }
        return {
            intent: {
                "hours": hours,
                "count": len(hours),
                "description": descriptions.get(intent, "Unknown intent"),
            }
            for intent, hours in intent_hours.items()
        }

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

    def get_detailed_period_groups(
        self, intents: list[str] | None = None
    ) -> list[dict]:
        """Get period groups with full control parameters for display/API."""
        effective_intents = intents if intents is not None else self.strategic_intents
        if not effective_intents:
            return []

        num_periods = len(effective_intents)
        period_settings = []
        for period in range(num_periods):
            intent = effective_intents[period]
            mode = self.INTENT_TO_MODE[intent]
            control = self.INTENT_TO_CONTROL[intent]
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

        groups = []
        current_group: dict | None = None
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

        result = []
        for group in groups:
            start_h, start_m = self._period_to_time(group["start_period"])
            end_h, end_m = self._period_to_time(group["end_period"])
            end_m += 14
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

    # ── Health check ──────────────────────────────────────────────────────────

    def check_health(self, controller) -> list:
        """Check SPH battery control capabilities.

        SPH inverters use Growatt service calls rather than individual HA entity
        reads, so we verify connectivity by calling read_ac_charge_times.
        """
        try:
            result = controller.read_ac_charge_times()
            if result and "periods" in result:
                check = {
                    "component": "Growatt Service (read_ac_charge_times)",
                    "status": "OK",
                    "message": f"Connected — charge_power={result.get('charge_power')}%, stop_soc={result.get('charge_stop_soc')}%",
                }
                overall_status = "OK"
            else:
                check = {
                    "component": "Growatt Service (read_ac_charge_times)",
                    "status": "ERROR",
                    "message": "Service call returned no data — check Growatt integration and device_id in config",
                }
                overall_status = "ERROR"
        except Exception as e:
            check = {
                "component": "Growatt Service (read_ac_charge_times)",
                "status": "ERROR",
                "message": f"Service call failed: {e}",
            }
            overall_status = "ERROR"

        health_check = {
            "name": "Battery Control (SPH)",
            "description": "Controls SPH battery charging and discharging schedule",
            "required": True,
            "status": overall_status,
            "checks": [check],
            "last_run": datetime.now().isoformat(),
        }

        return [health_check]
