"""Growatt SPH inverter controller.

Growatt SPH inverters use a fundamentally different scheduling model from MIN inverters.
Instead of 9 TOU segments with per-segment modes, SPH uses separate charge and discharge
period lists (max 3 each) with global power and SOC settings per call.

SPH Intent Mapping:
- GRID_CHARGING   → charge period (mains_enabled=True)
- SOLAR_STORAGE   → idle (SPH charges from solar by default; no explicit period needed)
- LOAD_SUPPORT    → discharge period
- BATTERY_EXPORT → discharge period
- IDLE            → nothing (inverter default)
"""

import logging
from datetime import datetime
from typing import ClassVar

from . import time_utils
from .dp_schedule import DPSchedule
from .inverter_controller import InverterController
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class GrowattSphController(InverterController):
    """Creates Growatt SPH inverter schedules from strategic intents.

    SPH inverters support separate charge and discharge period lists (max 3 each)
    with global power percentage and SOC settings per write call.

    This class mirrors the public interface of GrowattMinController so that
    BatterySystemManager can use either interchangeably via InverterController.
    """

    supports_charge_rate_control: ClassVar[bool] = False

    MAX_CHARGE_PERIODS = 3
    MAX_DISCHARGE_PERIODS = 3

    # Intents that produce a charge period on SPH
    # SOLAR_STORAGE is excluded — SPH charges from solar by default without an explicit period.
    CHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset({"GRID_CHARGING"})

    # Intents that produce a discharge period on SPH
    DISCHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset(
        {"LOAD_SUPPORT", "BATTERY_EXPORT"}
    )

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the SPH controller."""
        super().__init__(battery_settings)

        # SPH always does a full rewrite — no corruption concept
        # (corruption_detected is already False from base class __init__)

        # Internal period lists (≤3 each)
        self._charge_periods: list[dict] = []
        self._discharge_periods: list[dict] = []

    def _write_period_to_hardware(
        self, controller, grid_charge: bool, discharge_rate: int
    ) -> tuple[bool, str]:
        """No-op: SPH deploys the full schedule atomically via service calls.

        SPH inverters have no per-period entity controls (grid_charge switch,
        discharge rate number).  The entire schedule is written in
        ``write_schedule_to_hardware`` using ``write_ac_charge_times`` /
        ``write_ac_discharge_times``.
        """
        return True, ""

    @property
    def active_tou_intervals(self) -> list[dict]:
        """All TOU intervals are active for SPH (no 9-slot hardware constraint)."""
        return self.tou_intervals

    # ── Period utility ────────────────────────────────────────────────────────
    # NOTE: _group_period_blocks / _enforce_period_limit / _blocks_to_period_dicts
    # live on InverterController (the base class) — they are pure functions of
    # strategic_intents/CHARGE_INTENTS/DISCHARGE_INTENTS shared by any
    # SM-Period-lists controller (SPH here, Solis via SolisModbusController).

    # ── Schedule building ─────────────────────────────────────────────────────

    def _build_sph_periods(self) -> None:
        """Build charge and discharge period lists from strategic intents."""
        self._charge_periods, self._discharge_periods = (
            self._build_period_list_schedule()
        )

        logger.info(
            "SPH periods built: %d charge period(s), %d discharge period(s)",
            len(self._charge_periods),
            len(self._discharge_periods),
        )
        for p in self._charge_periods:
            logger.info("  Charge:    %s-%s", p["start_time"], p["end_time"])
        for p in self._discharge_periods:
            logger.info("  Discharge: %s-%s", p["start_time"], p["end_time"])

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

        writes = 0

        logger.info(
            "SPH HARDWARE: Writing charge periods (power=%d%%, stop_soc=%d%%, mains=%s): %s",
            charge_power,
            charge_stop_soc,
            mains_enabled,
            self._charge_periods,
        )
        try:
            controller.write_ac_charge_times(
                charge_power=charge_power,
                charge_stop_soc=charge_stop_soc,
                mains_enabled=mains_enabled,
                **charge_params,
            )
            writes += 1
        except Exception as e:
            logger.error("FAILED: write_ac_charge_times: %s", e)
            # Failure already recorded by _api_request via record_failure_once

        logger.info(
            "SPH HARDWARE: Writing discharge periods (power=%d%%, stop_soc=%d%%): %s",
            discharge_power,
            discharge_stop_soc,
            self._discharge_periods,
        )
        try:
            controller.write_ac_discharge_times(
                discharge_power=discharge_power,
                discharge_stop_soc=discharge_stop_soc,
                **discharge_params,
            )
            writes += 1
        except Exception as e:
            logger.error("FAILED: write_ac_discharge_times: %s", e)
            # Failure already recorded by _api_request via record_failure_once

        return writes, 0

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

    def initialize_hardware(self, controller) -> None:
        self.sync_soc_limits(controller)

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Read current SPH schedule from inverter and initialize this controller.

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
        self.tou_intervals = self._periods_to_tou_intervals(
            self._charge_periods,
            self._discharge_periods,
            charge_intent="existing_schedule",
            discharge_intent="existing_schedule",
        )

        logger.info(
            "SPH initialized from hardware: %d charge period(s), %d discharge period(s)",
            len(self._charge_periods),
            len(self._discharge_periods),
        )

    # ── Schedule comparison ───────────────────────────────────────────────────

    def compare_schedules(
        self, other_schedule: "GrowattSphController", from_period: int = 0
    ) -> tuple[bool, str]:
        """Compare SPH periods with another schedule controller.

        Args:
            other_schedule: Another GrowattSphController to compare against
            from_period: Comparison start period (informational for SPH)

        Returns:
            Tuple of (schedules_differ, reason)
        """
        return self._compare_period_list_schedules(other_schedule, "SPH")

    # ── Period settings ─────────────────────────────────────────────────────

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
