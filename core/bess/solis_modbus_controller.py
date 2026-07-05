"""Solis hybrid inverter controller (Pho3niX90/solis_modbus, local Modbus).

Solis hybrids share the same "SM-Period-lists" scheduling model as Growatt
SPH: separate charge and discharge period lists, built via the shared
grouping helpers on ``InverterController`` (``_group_period_blocks``,
``_enforce_period_limit``, ``_blocks_to_period_dicts``). Unlike SPH, which
writes its schedule atomically via growatt_server cloud service calls,
Solis is TX-Modbus: each TOU period is written directly to HA ``time`` and
``switch`` entities exposed by the solis_modbus integration.

Verified against github.com/Pho3niX90/solis_modbus release v4.1.6. The
inverter's "Grid Time of Use" v2 schedule supports 6 charge periods and 6
discharge periods (time_sensors.py registers 43711-43790, switch_sensors.py
register 43707 bits 0-11) — see ``core/bess/ha_api_controller.py``'s
``SOLIS_SUFFIX_MAP`` for the full unique_id -> BESS sensor key derivation
with source line citations.

Credits: based on SA7BNT's research and initial implementation in
bess-manager-beta PR #51 (github.com/johanzander/bess-manager-beta/pull/51).
Re-implemented here to (a) share scheduling logic with GrowattSphController
through proper inheritance instead of calling its private methods across a
class boundary, and (b) re-verify every unique_id/entity claim directly
against the solis_modbus source rather than carrying over PR #51's
assumptions unchecked.

Solis Intent Mapping (identical semantics to GrowattSphController):
- GRID_CHARGING   → charge period (charge-slot enable switch on)
- SOLAR_STORAGE   → idle (charges from solar by default; no explicit period)
- LOAD_SUPPORT    → discharge period
- BATTERY_EXPORT  → discharge period
- IDLE            → nothing (inverter default / self-use mode)

EXPERIMENTAL: not yet validated against a real Solis installation — see
docs/agents/memory/project_platform_maturity.md.
"""

import logging
from datetime import datetime
from typing import ClassVar

from . import time_utils
from .dp_schedule import DPSchedule
from .inverter_controller import InverterController
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class SolisModbusController(InverterController):
    """Creates Solis hybrid inverter schedules from strategic intents.

    Solis's Grid Time of Use v2 schedule supports up to 6 charge periods and
    6 discharge periods, written directly to HA time/switch entities (no
    cloud service call, unlike Growatt SPH).
    """

    # Solis has no per-period charge/discharge rate register exposed by
    # solis_modbus for schedule writes — control is enable/disable + time
    # window per slot, same limitation as SPH.
    supports_charge_rate_control: ClassVar[bool] = False

    MAX_CHARGE_PERIODS = 6
    MAX_DISCHARGE_PERIODS = 6

    # Intents that produce a charge period on Solis.
    # SOLAR_STORAGE is excluded — Solis charges from solar by default
    # without an explicit grid-charge period.
    CHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset({"GRID_CHARGING"})

    # Intents that produce a discharge period on Solis.
    DISCHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset(
        {"LOAD_SUPPORT", "BATTERY_EXPORT"}
    )

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the Solis controller."""
        super().__init__(battery_settings)

        # Solis always does a full rewrite — no corruption concept
        # (corruption_detected is already False from base class __init__)

        # Internal period lists (≤6 each)
        self._charge_periods: list[dict] = []
        self._discharge_periods: list[dict] = []

    def _write_period_to_hardware(
        self, controller, grid_charge: bool, discharge_rate: int
    ) -> tuple[bool, str]:
        """No-op: Solis deploys the full schedule via write_schedule_to_hardware.

        Solis has no per-period entity controls beyond the TOU schedule
        itself (no separate grid_charge switch / discharge rate number) —
        the entire period list is written in ``write_schedule_to_hardware``.
        """
        return True, ""

    @property
    def active_tou_intervals(self) -> list[dict]:
        """All TOU intervals are active for Solis (no 9-slot hardware constraint)."""
        return self.tou_intervals

    # ── Schedule building ─────────────────────────────────────────────────────

    def _build_solis_periods(self) -> None:
        """Build charge and discharge period lists from strategic intents."""
        self._charge_periods, self._discharge_periods = (
            self._build_period_list_schedule()
        )

        logger.info(
            "Solis periods built: %d charge period(s), %d discharge period(s)",
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
        """Process DPSchedule with strategic intents into Solis period format."""
        logger.info("Creating Solis schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        logger.info(
            "Using %d strategic intents (quarterly resolution)",
            len(self.strategic_intents),
        )

        self._build_solis_periods()

        logger.info(
            "Solis schedule created: %d charge period(s), %d discharge period(s), "
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
        """Write Solis charge and discharge periods to hardware.

        Solis always does a full rewrite (no differential update): every
        one of the 6 charge slots and 6 discharge slots is written each
        time — active slots get their real start/end time and enabled=True,
        unused slots are disabled with a 00:00-00:00 window.

        Args:
            controller: HomeAssistantAPIController instance
            effective_period: Unused for Solis (full rewrite each time)
            current_tou: Unused for Solis (full rewrite each time)

        Returns:
            Tuple of (writes, disables)
        """
        writes = 0
        disables = 0

        for slot in range(1, self.MAX_CHARGE_PERIODS + 1):
            idx = slot - 1
            if idx < len(self._charge_periods):
                p = self._charge_periods[idx]
                start_time, end_time, enabled = p["start_time"], p["end_time"], True
            else:
                start_time, end_time, enabled = "00:00", "00:00", False

            try:
                controller.write_solis_period(
                    "charge", slot, start_time, end_time, enabled
                )
                writes += 1
                if not enabled:
                    disables += 1
            except Exception as e:
                logger.error("FAILED: write_solis_period(charge, %d): %s", slot, e)

        for slot in range(1, self.MAX_DISCHARGE_PERIODS + 1):
            idx = slot - 1
            if idx < len(self._discharge_periods):
                p = self._discharge_periods[idx]
                start_time, end_time, enabled = p["start_time"], p["end_time"], True
            else:
                start_time, end_time, enabled = "00:00", "00:00", False

            try:
                controller.write_solis_period(
                    "discharge", slot, start_time, end_time, enabled
                )
                writes += 1
                if not enabled:
                    disables += 1
            except Exception as e:
                logger.error("FAILED: write_solis_period(discharge, %d): %s", slot, e)

        return writes, disables

    def sync_soc_limits(self, controller) -> None:
        """Sync SOC limits from config to inverter hardware.

        Solis's global charge/discharge stop SOC registers ("Max Charge
        SOC" / "Overdischarge SOC") are affected by the same dict-embedded
        unique_id integration bug as other monitoring entities (see
        SOLIS_DICT_EMBEDDED_SUFFIX_MAP) and are not wired for auto-write in
        this first pass — no verified, reliable write path exists yet.
        This is a documented gap, not a silent fallback: no SOC write is
        attempted, and no bogus success is reported.
        """
        logger.info(
            "Solis: SOC limit sync not implemented — no verified write path "
            "for global charge/discharge stop SOC registers yet"
        )

    def initialize_hardware(self, controller) -> None:
        self.sync_soc_limits(controller)

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Read current Solis schedule from inverter and initialize this controller."""
        logger.info("Reading Solis charge/discharge periods from inverter")

        charge_periods = controller.read_solis_periods("charge")
        discharge_periods = controller.read_solis_periods("discharge")

        self._charge_periods = [
            {
                "start_time": p["start_time"],
                "end_time": p["end_time"],
                "enabled": True,
            }
            for p in charge_periods
            if p.get("enabled")
        ]
        self._discharge_periods = [
            {
                "start_time": p["start_time"],
                "end_time": p["end_time"],
                "enabled": True,
            }
            for p in discharge_periods
            if p.get("enabled")
        ]

        self.tou_intervals = self._periods_to_tou_intervals(
            self._charge_periods,
            self._discharge_periods,
            charge_intent="existing_schedule",
            discharge_intent="existing_schedule",
        )

        logger.info(
            "Solis initialized from hardware: %d charge period(s), %d discharge period(s)",
            len(self._charge_periods),
            len(self._discharge_periods),
        )

    # ── Schedule comparison ───────────────────────────────────────────────────

    def compare_schedules(
        self, other_schedule: "SolisModbusController", from_period: int = 0
    ) -> tuple[bool, str]:
        """Compare Solis periods with another schedule controller."""
        return self._compare_period_list_schedules(other_schedule, "Solis")

    # ── TOU display ───────────────────────────────────────────────────────────

    def get_daily_TOU_settings(self) -> list[dict]:
        """Return tou_intervals for display/API consumption."""
        return list(self.tou_intervals)

    def log_current_TOU_schedule(self, header: str = "") -> None:
        """Log current Solis charge/discharge periods."""
        if header:
            logger.info(header)

        if not self._charge_periods and not self._discharge_periods:
            logger.info("Solis: No active charge or discharge periods")
            return

        logger.info(" -= Solis Schedule =-")
        for i, p in enumerate(self._charge_periods, 1):
            logger.info("  Charge  period %d: %s-%s", i, p["start_time"], p["end_time"])
        for i, p in enumerate(self._discharge_periods, 1):
            logger.info(
                "  Discharge period %d: %s-%s", i, p["start_time"], p["end_time"]
            )

    def log_detailed_schedule(self, header: str = "") -> None:
        """Log detailed schedule with per-period strategic intents."""
        if header:
            logger.info(header)

        if not self.strategic_intents:
            logger.info("Solis: No schedule data available")
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        lines = [
            "\n╔═══════════════╦══════════════════╦═══════════════╗",
            "║  Time Period  ║ Strategic Intent ║ Solis Action  ║",
            "╠═══════════════╬══════════════════╬═══════════════╣",
        ]

        num_periods = len(self.strategic_intents)
        period = 0
        while period < num_periods:
            intent = self.strategic_intents[period]
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
        """Check Solis battery control capabilities by reading TOU period entities."""
        try:
            charge = controller.read_solis_periods("charge")
            check = {
                "component": "Solis Grid TOU v2 (solis_modbus)",
                "status": "OK",
                "message": f"Connected — {len(charge)} charge slot(s) configured",
            }
            overall_status = "OK"
        except Exception as e:
            check = {
                "component": "Solis Grid TOU v2 (solis_modbus)",
                "status": "ERROR",
                "message": f"Read failed: {e}",
            }
            overall_status = "ERROR"

        health_check = {
            "name": "Battery Control (Solis)",
            "description": "Controls Solis battery charging and discharging schedule",
            "required": True,
            "status": overall_status,
            "checks": [check],
            "last_run": datetime.now().isoformat(),
        }

        return [health_check]
