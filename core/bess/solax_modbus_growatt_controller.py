"""Growatt MIN inverter controller using solax_modbus with single-segment TOU.

This controller supports Growatt MIN inverters connected via the solax_modbus
HACS integration (local Modbus) instead of the growatt_server cloud integration.

Unlike the cloud controller (GrowattMinController) which pre-programs up to 9
TOU segments, this controller uses a **single TOU segment** (slot 1) with a
full-day time window (00:00-23:59).  The battery mode is updated per-period
via ``apply_period`` — only when the mode actually changes — reducing the
required entity count from 45 (9 slots x 5 entities) to just 5.

This is analogous to how ``SolaxController`` applies per-period VPP commands
with ``write_schedule_to_hardware`` as a near no-op.

Per-period control (``set_grid_charge``, ``set_discharging_power_rate``) uses
generic HA service calls that resolve entity IDs from sensor config, so no
override is needed for those.

Mode semantics:
- ``load_first`` — inverter default when no TOU segment is active
- ``battery_first`` — charge from grid + solar (GRID_CHARGING intent)
- ``grid_first`` — export to grid (BATTERY_EXPORT intent)
"""

import logging

from . import time_utils
from .dp_schedule import DPSchedule
from .growatt_min_controller import GrowattMinController
from .health_check import perform_health_check
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class SolaxModbusGrowattController(GrowattMinController):
    """Growatt MIN controller using solax_modbus with single-segment TOU.

    Instead of pre-programming 9 TOU segments, this controller manages a single
    TOU segment (slot 1) and updates its mode each period when needed.
    """

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the Growatt solax_modbus controller."""
        super().__init__(battery_settings)
        self._last_written_tou_mode: str | None = None

    # ── Abstract property ────────────────────────────────────────────────────

    @property
    def active_tou_intervals(self) -> list[dict]:
        """Return the single TOU segment if active, else empty list."""
        return self._active_tou_intervals

    @active_tou_intervals.setter
    def active_tou_intervals(self, value: list[dict]) -> None:
        self._active_tou_intervals = value

    # ── Schedule creation ────────────────────────────────────────────────────

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Store strategic intents — TOU mode is applied per-period, no batch TOU needed.

        Skips the parent's 9-segment TOU interval computation.  Strategic intents
        are stored and hourly settings calculated for API/display consumption.

        Args:
            schedule: DPSchedule containing strategic_intent list.
            current_period: Current 15-minute period (0-95).
            previous_tou_intervals: Unused for single-segment approach.
        """
        logger.info("Creating Modbus single-segment schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        logger.info(
            "Modbus: %d strategic intents loaded (quarterly resolution)",
            len(self.strategic_intents),
        )

        # Log intent transitions from current_period onward — periods before
        # current_period are already elapsed and re-log identically on every
        # hourly re-optimization otherwise.
        for period in range(max(1, current_period), len(self.strategic_intents)):
            if self.strategic_intents[period] != self.strategic_intents[period - 1]:
                logger.info(
                    "Intent transition at period %d: %s -> %s",
                    period,
                    self.strategic_intents[period - 1],
                    self.strategic_intents[period],
                )

        # Build single-segment TOU state for API display
        self._update_tou_display_state()

    # ── Hardware interface ────────────────────────────────────────────────────

    def apply_period(
        self, controller, grid_charge: bool, discharge_rate: int
    ) -> tuple[bool, str]:
        """Write period control settings, including TOU mode update when needed.

        Derives the required TOU mode from the current period's strategic intent.
        Only writes the TOU segment when the mode actually changes, minimising
        inverter writes.

        Args:
            controller: HomeAssistantAPIController instance
            grid_charge: Whether to enable grid charging
            discharge_rate: Discharge power rate (0-100%), post-inhibit

        Returns:
            Tuple of (success, error_message). error_message is empty on success.
        """
        errors = []
        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        mode = "load_first"
        if current_period < len(self.strategic_intents):
            intent = self.strategic_intents[current_period]
            mode = self.INTENT_TO_MODE.get(intent, "load_first")

            if mode != self._last_written_tou_mode:
                enabled = mode != "load_first"
                logger.info(
                    "TOU segment 1 mode: %s -> %s (period %d, intent %s)",
                    self._last_written_tou_mode,
                    mode,
                    current_period,
                    intent,
                )
                try:
                    controller.set_tou_segment_via_entities(
                        segment_id=1,
                        batt_mode=mode,
                        start_time="00:00",
                        end_time="23:59",
                        enabled=enabled,
                    )
                    self._last_written_tou_mode = mode
                    self._update_tou_display_state()
                except Exception as e:
                    logger.error("FAILED: set TOU segment mode to %s: %s", mode, e)
                    errors.append(str(e))

        # #166 added a gate here to skip writing discharge_rate=0 in load_first
        # mode, on the theory that it disables the inverter's native self-use
        # discharge. That theory was never confirmed against real hardware and
        # left SOLAR_STORAGE/IDLE with a stale discharge_rate register (#issue
        # reported by Doodlehusse on #200 follow-up). This beta build removes
        # the gate to test on real GEN4 hardware — writes unconditionally, same
        # as GrowattMinController's cloud path.
        success, error_msg = self._write_period_to_hardware(
            controller, grid_charge, discharge_rate
        )
        if not success:
            errors.append(error_msg)

        if errors:
            return False, "; ".join(errors)
        return True, ""

    def write_schedule_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        """Initialise single TOU segment on hardware.

        Sets segment 1 to the current period's mode with a full-day window.
        Legacy segments 2-9 are cleaned up at startup (read_and_initialize_from_hardware),
        not here, to avoid repeated attempts on unconfigured entities.

        Args:
            controller: HomeAssistantAPIController instance
            effective_period: Period (0-95) from which to start applying changes
            current_tou: TOU intervals currently active on the inverter (unused)

        Returns:
            Tuple of (segments_updated, segments_disabled)
        """
        mode = "load_first"
        if effective_period < len(self.strategic_intents):
            intent = self.strategic_intents[effective_period]
            mode = self.INTENT_TO_MODE.get(intent, "load_first")

        enabled = mode != "load_first"
        logger.info(
            "Modbus: writing initial TOU segment 1 — mode=%s, enabled=%s",
            mode,
            enabled,
        )

        controller.set_tou_segment_via_entities(
            segment_id=1,
            batt_mode=mode,
            start_time="00:00",
            end_time="23:59",
            enabled=enabled,
        )
        self._last_written_tou_mode = mode
        self._update_tou_display_state()

        return 1, 0

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Read TOU state from hardware and seed the mode tracker.

        Reads all available TOU slots to determine segment 1's current mode
        and sets up internal display state.  Pure read — no hardware writes.

        Args:
            controller: HomeAssistantAPIController instance
            current_hour: Current hour (0-23)
        """
        self.current_hour = current_hour
        segments = controller.read_tou_segments_from_entities()

        # Seed mode tracker from segment 1
        seg1 = next((s for s in segments if s["segment_id"] == 1), None)
        if seg1 and seg1.get("enabled"):
            self._last_written_tou_mode = seg1["batt_mode"]
            logger.info(
                "Modbus: initialised from hardware — segment 1 mode=%s",
                self._last_written_tou_mode,
            )
        else:
            self._last_written_tou_mode = "load_first"
            logger.info(
                "Modbus: initialised from hardware — no active TOU segment, defaulting to load_first"
            )

        # Set display state
        self._update_tou_display_state()

    def _disable_legacy_tou_slots(self, controller) -> None:
        """Disable any TOU slots 2-9 still enabled from a previous 9-segment config.

        On startup, reads all available TOU slots (1-9).  Any slot 2-9 that is
        found enabled gets disabled — handles migration from the old 9-segment
        approach regardless of how many slots the user had enabled.
        """
        segments = controller.read_tou_segments_from_entities()
        disabled_count = 0
        for seg in segments:
            if seg["segment_id"] >= 2 and seg.get("enabled", False):
                logger.info(
                    "Disabling legacy TOU slot %d (%s %s-%s) — "
                    "single-segment mode active",
                    seg["segment_id"],
                    seg.get("batt_mode", "?"),
                    seg.get("start_time", "?"),
                    seg.get("end_time", "?"),
                )
                controller.set_tou_segment_via_entities(
                    segment_id=seg["segment_id"],
                    batt_mode="load_first",
                    start_time="00:00",
                    end_time="00:00",
                    enabled=False,
                )
                disabled_count += 1

        if disabled_count > 0:
            logger.info("Migration: disabled %d legacy TOU slot(s)", disabled_count)

    def initialize_hardware(self, controller) -> None:
        self._disable_legacy_tou_slots(controller)
        super().initialize_hardware(controller)

    # ── Schedule comparison ──────────────────────────────────────────────────

    def compare_schedules(
        self,
        other_schedule: "SolaxModbusGrowattController",
        from_period: int = 0,
    ) -> tuple[bool, str]:
        """Compare schedules by strategic intent list (like SolaxController).

        Two schedules differ when any period at or after ``from_period`` has a
        different strategic intent.

        Args:
            other_schedule: Another controller to compare against.
            from_period: First period to compare (earlier periods are ignored).

        Returns:
            Tuple of (schedules_differ, reason).
        """
        current = self.strategic_intents
        new = other_schedule.strategic_intents

        if not current and not new:
            return False, ""

        if len(current) != len(new):
            return True, (f"Modbus intent count differs: {len(current)} vs {len(new)}")

        for period in range(from_period, len(current)):
            if current[period] != new[period]:
                logger.info(
                    "DECISION: Modbus intent differs at period %d — "
                    "current=%s new=%s",
                    period,
                    current[period],
                    new[period],
                )
                return True, (f"Modbus strategic intents differ from period {period}")

        logger.info("DECISION: Modbus schedules match")
        return False, ""

    # ── TOU display ──────────────────────────────────────────────────────────

    def _update_tou_display_state(self) -> None:
        """Update internal TOU interval lists for API/display consumption."""
        mode = self._last_written_tou_mode or "load_first"
        enabled = mode != "load_first"

        if enabled:
            segment = {
                "segment_id": 1,
                "batt_mode": mode,
                "start_time": "00:00",
                "end_time": "23:59",
                "enabled": True,
            }
            self.tou_intervals = [segment]
            self._active_tou_intervals = [segment]
        else:
            self.tou_intervals = []
            self._active_tou_intervals = []

    def get_daily_TOU_settings(self) -> list[dict]:
        """Return the single TOU segment if active."""
        if not self.tou_intervals:
            return []
        return [seg.copy() for seg in self.tou_intervals]

    def get_all_tou_segments(self, current_period: int | None = None):
        """Return TOU segments with defaults for complete 24-hour coverage.

        For the single-segment approach, returns the active segment (if any)
        plus default load_first segments filling the gaps.
        """
        groups = self.get_detailed_period_groups()
        if not groups:
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

        # Build display from intent groups (same approach as SolaxController)
        now = time_utils.now()
        current_p = now.hour * 4 + now.minute // 15

        result = []
        for group in groups:
            mode = self.INTENT_TO_MODE.get(group["intent"], "load_first")
            is_current = group["start_period"] <= current_p <= group["end_period"]
            result.append(
                {
                    "segment_id": len(result) + 1,
                    "start_time": group["start_time"],
                    "end_time": group["end_time"],
                    "batt_mode": mode,
                    "enabled": mode != "load_first",
                    "is_default": mode == "load_first",
                    "is_current": is_current,
                    "strategic_intent": group["intent"],
                }
            )
        return result

    def log_current_TOU_schedule(self, header=None) -> None:
        """Log current single-segment TOU state."""
        if header:
            logger.info(header)

        mode = self._last_written_tou_mode or "load_first"
        if mode == "load_first":
            logger.info("Modbus: TOU segment 1 disabled (load_first default)")
        else:
            logger.info("Modbus: TOU segment 1 = %s (00:00-23:59)", mode)

    # ── Health check ─────────────────────────────────────────────────────────

    def check_health(self, controller) -> list:
        """Check battery control capabilities including TOU schedule entities."""
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

        # Verify TOU schedule entities are configured (required for schedule application)
        tou_keys = [
            "tou_time_1_enabled",
            "tou_time_1_begin",
            "tou_time_1_end",
            "tou_time_1_mode",
            "tou_time_1_update",
        ]
        for key in tou_keys:
            entity_id = controller.sensors.get(key, "")
            if entity_id:
                status, error = "OK", None
            else:
                status, error = "ERROR", "Not configured — re-run setup wizard"
            health_check["checks"].append(
                {
                    "name": f"TOU Entity: {key}",
                    "key": key,
                    "method_name": None,
                    "entity_id": entity_id or "Not configured",
                    "status": status,
                    "rawValue": None,
                    "displayValue": entity_id or "Not configured",
                    "error": error,
                }
            )

        # Re-evaluate overall status including TOU checks
        has_error = any(c["status"] == "ERROR" for c in health_check["checks"])
        has_warning = any(c["status"] == "WARNING" for c in health_check["checks"])
        if has_error:
            health_check["status"] = "ERROR"
        elif has_warning:
            health_check["status"] = "WARNING"

        return [health_check]
