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

Solis Intent Mapping:
- GRID_CHARGING   → charge period (charge-slot enable switch on)
- SOLAR_STORAGE   → nothing (charges from solar by default; no explicit period)
- LOAD_SUPPORT    → nothing (Self Use follows the load)
- BATTERY_EXPORT  → discharge period, cut-off at the planned end SOC
- IDLE            → discharge period with a cut-off above SOC, when deliberate

A discharge slot is not "the battery may discharge". Measured on an S5-EH1P
(#869), an active slot forces its own current out down to its own cut-off SOC
and ignores the load, and below that cut-off the battery does not serve the
house at all. So a slot is the export tool and the hold tool, and the one thing
it cannot do is follow the load.

Real-world validated (issue #130) — see docs/agents/memory/project_platform_maturity.md.
"""

import logging
import math
from datetime import datetime
from typing import Any, ClassVar

from . import time_utils
from .dp_schedule import DPSchedule
from .inverter_controller import InverterController
from .settings import BatterySettings
from .strategic_intent import idle_hold_releasable

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

    # Both False for the same reason as SPH and Huawei: a Solis discharge
    # slot is a time window, with no per-period rate to interpret as a
    # ceiling and none to deliver a partial load cover with. Previously left
    # to inherit the base class's True, which disagreed with this
    # platform's own `period_list` control model -- caught in review of
    # Phase 4a, where the optimizer and the hardware-write path would
    # otherwise have read the same platform two different ways.
    discharge_rate_is_load_following: ClassVar[bool] = False
    load_support_delivers_exact_cover: ClassVar[bool] = False

    CONTROL_MODEL: ClassVar[str] = "period_list"

    MAX_CHARGE_PERIODS = 6
    MAX_DISCHARGE_PERIODS = 6

    # Intents that produce a charge period on Solis.
    # SOLAR_STORAGE is excluded — Solis charges from solar by default
    # without an explicit grid-charge period.
    CHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset({"GRID_CHARGING"})

    # Intents that produce a discharge period on Solis.
    DISCHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset({"BATTERY_EXPORT"})

    # Above any SOC the battery can be below, so a hold needs no SOC reading
    # and survives the battery state moving during the window.
    HOLD_CUTOFF_SOC: ClassVar[int] = 100

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the Solis controller."""
        super().__init__(battery_settings)

        # Solis always does a full rewrite — no corruption concept
        # (corruption_detected is already False from base class __init__)

        # Internal period lists (≤6 each)
        self._charge_periods: list[dict] = []
        self._discharge_periods: list[dict] = []

    def _write_period_to_hardware(
        self,
        controller,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
    ) -> tuple[bool, str]:
        """No-op: Solis deploys the full schedule via sync_to_hardware.

        Solis has no per-period entity controls beyond the TOU schedule
        itself (no separate grid_charge switch / discharge rate number) —
        the entire period list is written in ``sync_to_hardware``.

        ``block_passive_charging`` is accepted to match the base signature
        (``apply_period`` passes it to every platform) and is unused here.
        """
        return True, ""

    @property
    def active_tou_intervals(self) -> list[dict]:
        """All TOU intervals are active for Solis (no 9-slot hardware constraint)."""
        return self.tou_intervals

    # ── Schedule building ─────────────────────────────────────────────────────

    def _is_deliberate_hold(self, period_data: list, period: int) -> bool:
        """Does this IDLE period need the battery actively kept from discharging?

        Self Use would drain it otherwise. Not worth a slot when the plan gives
        no basis, when the IDLE is a fall-through the plan would release (#786),
        or when the battery is within one SOC point of the floor: that is the
        inverter's SOC resolution, so there is nothing a hold could protect.
        """
        if period >= len(period_data) or period_data[period] is None:
            return False
        planned = period_data[period]
        one_soc_point_kwh = self.battery_settings.total_capacity / 100
        if (
            planned.energy.battery_soe_start
            <= self.battery_settings.min_soe_kwh + one_soc_point_kwh
        ):
            return False
        return not idle_hold_releasable(
            planned.decision.intra_period_discharge_allowed,
            planned.energy.grid_imported,
        )

    def _hold_blocks(
        self, intents: list[str], period_data: list, current_period: int
    ) -> list[dict]:
        """Consecutive deliberate-hold periods that have not finished yet."""
        blocks: list[dict] = []
        for period, intent in enumerate(intents):
            if intent != "IDLE" or not self._is_deliberate_hold(period_data, period):
                continue
            if blocks and blocks[-1]["end_period"] == period - 1:
                blocks[-1]["end_period"] = period
                blocks[-1]["intents"].append(intent)
            else:
                blocks.append(
                    {"start_period": period, "end_period": period, "intents": [intent]}
                )
        return [b for b in blocks if b["end_period"] >= current_period]

    def _export_slots(
        self, blocks: list[dict], period_data: list, current_period: int
    ) -> list[dict]:
        """Period dicts for export blocks, limited to what the plan still wants."""
        min_cutoff = math.ceil(self.battery_settings.min_soc)
        slots: list[dict] = []
        for block in blocks:
            remaining = [
                period_data[p]
                for p in range(
                    max(block["start_period"], current_period),
                    block["end_period"] + 1,
                )
            ]
            hours = len(remaining) * time_utils.INTERVAL_MINUTES / 60
            discharged = sum(p.energy.battery_discharged for p in remaining)
            end_soc = math.ceil(
                remaining[-1].energy.battery_soe_end
                / self.battery_settings.total_capacity
                * 100
            )
            for period in self._blocks_to_period_dicts([block]):
                slots.append(
                    {
                        **period,
                        "cutoff_soc": max(end_soc, min_cutoff),
                        "discharge_power_kw": round(discharged / hours, 2),
                    }
                )
        return slots

    def _build_candidate(
        self, schedule: DPSchedule, current_period: int
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Compute charge/discharge periods and display TOU intervals for a
        schedule, without mutating self. Shared by apply_intents (commits onto
        self) and evaluate_intents (diffs against self's current state)."""
        intents = schedule.original_dp_results["strategic_intent"]
        period_data = schedule.period_data

        charge_blocks, export_blocks = self._group_period_blocks(intents)
        charge_blocks = self._enforce_period_limit(
            charge_blocks, self.MAX_CHARGE_PERIODS
        )
        export_blocks = self._enforce_period_limit(
            [b for b in export_blocks if b["end_period"] >= current_period],
            self.MAX_DISCHARGE_PERIODS,
        )
        # Exports share the six slots with holds and are placed first: a
        # dropped hold only falls back to Self Use, a dropped export forgoes
        # the revenue the plan was built around.
        hold_blocks = self._enforce_period_limit(
            self._hold_blocks(intents, period_data, current_period),
            self.MAX_DISCHARGE_PERIODS - len(export_blocks),
        )

        charge_periods = self._blocks_to_period_dicts(charge_blocks)
        export_periods = self._export_slots(export_blocks, period_data, current_period)
        hold_periods = [
            {
                **period,
                "cutoff_soc": self.HOLD_CUTOFF_SOC,
                "discharge_power_kw": None,
            }
            for period in self._blocks_to_period_dicts(hold_blocks)
        ]
        discharge_periods = sorted(
            export_periods + hold_periods, key=lambda p: p["start_time"]
        )

        tou_intervals = sorted(
            self._periods_to_tou_intervals(
                charge_periods, export_periods, discharge_intent="BATTERY_EXPORT"
            )
            + self._periods_to_tou_intervals([], hold_periods, discharge_intent="IDLE"),
            key=lambda interval: interval["start_time"],
        )
        for segment_id, interval in enumerate(tou_intervals, 1):
            interval["segment_id"] = segment_id

        logger.info(
            "Solis periods built: %d charge period(s), %d discharge period(s)",
            len(charge_periods),
            len(discharge_periods),
        )
        for p in charge_periods:
            logger.info("  Charge:    %s-%s", p["start_time"], p["end_time"])
        for p in discharge_periods:
            logger.info(
                "  Discharge: %s-%s cut-off %d%%",
                p["start_time"],
                p["end_time"],
                p["cutoff_soc"],
            )

        return charge_periods, discharge_periods, tou_intervals

    def apply_intents(self, schedule: DPSchedule, current_period: int = 0) -> None:
        """Adopt this cycle's DP intent list, rebuilding Solis charge/discharge periods."""
        logger.info("Creating Solis schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        logger.info(
            "Using %d strategic intents (quarterly resolution)",
            len(self.strategic_intents),
        )

        self._charge_periods, self._discharge_periods, self.tou_intervals = (
            self._build_candidate(schedule, current_period)
        )

        logger.info(
            "Solis schedule created: %d charge period(s), %d discharge period(s), "
            "%d display intervals",
            len(self._charge_periods),
            len(self._discharge_periods),
            len(self.tou_intervals),
        )

    # ── Hardware interface ────────────────────────────────────────────────────

    def sync_to_hardware(
        self,
        controller,
        effective_period: int,
    ) -> tuple[int, int]:
        """Write Solis charge and discharge periods to hardware.

        Solis always does a full rewrite (no differential update): every
        one of the 6 charge slots and 6 discharge slots is written each
        time — active slots get their real start/end time and enabled=True,
        unused slots are disabled with a 00:00-00:00 window.

        Args:
            controller: HomeAssistantAPIController instance
            effective_period: Unused for Solis (full rewrite each time)

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
            start_time, end_time, enabled = "00:00", "00:00", False
            if idx < len(self._discharge_periods):
                p = self._discharge_periods[idx]
                if self._write_discharge_limits(controller, slot, p):
                    start_time, end_time, enabled = p["start_time"], p["end_time"], True

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

    def _write_discharge_limits(self, controller: Any, slot: int, period: dict) -> bool:
        """Set a discharge slot's cut-off and current; True when it is safe to open.

        A slot opened on the limits it already holds would run on whatever was
        last left on the inverter, so a failure here keeps the slot closed.
        check_health reports the missing entities that cause the common case.
        """
        try:
            controller.set_solis_discharge_cutoff_soc(slot, period["cutoff_soc"])
            if period["discharge_power_kw"] is not None:
                amps = (
                    period["discharge_power_kw"]
                    * 1000
                    / (controller.get_battery_voltage())
                )
                controller.set_solis_discharge_current(slot, round(amps, 1))
        except Exception as e:
            logger.error(
                "FAILED: Solis discharge slot %d limits, keeping it closed: %s", slot, e
            )
            return False
        return True

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
        # Only the windows are read back. Leaving the limits unknown makes the
        # next evaluate_intents rewrite any slot found enabled.
        self._discharge_periods = [
            {
                "start_time": p["start_time"],
                "end_time": p["end_time"],
                "enabled": True,
                "cutoff_soc": None,
                "discharge_power_kw": None,
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

    def evaluate_intents(
        self, schedule: DPSchedule, current_period: int = 0
    ) -> tuple[bool, str]:
        """Compare Solis charge/discharge periods a candidate schedule would
        produce against what's currently applied."""
        new_charge, new_discharge, _tou = self._build_candidate(
            schedule, current_period
        )

        differs, reason = self._diff_period_lists(
            self._charge_periods,
            self._discharge_periods,
            new_charge,
            new_discharge,
            "Solis",
        )
        if differs:
            return differs, reason

        def limits(periods: list[dict]) -> list[tuple]:
            return [(p["cutoff_soc"], p["discharge_power_kw"]) for p in periods]

        if limits(self._discharge_periods) != limits(new_discharge):
            logger.info(
                "DECISION: Solis discharge limits differ — current=%s new=%s",
                self._discharge_periods,
                new_discharge,
            )
            return True, "Solis discharge limits differ"

        return False, ""

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
        current_period = time_utils.timestamp_to_period_index(now)

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

            sh, sm = self._period_to_time(run_start)
            eh, em = self._period_to_time(run_end)
            em += 14

            time_range = f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"
            is_current = run_start <= current_period <= run_end
            marker = "*" if is_current else " "

            if intent in self.CHARGE_INTENTS:
                action = "charge"
            elif intent in self.DISCHARGE_INTENTS:
                action = "discharge"
            elif intent == "IDLE":
                action = "self use/hold"
            else:
                action = "self use"

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
            missing = controller.missing_solis_discharge_limit_sensors()
            if missing:
                check = {
                    "component": "Solis Grid TOU v2 (solis_modbus)",
                    "status": "ERROR",
                    "message": (
                        f"{len(missing)} discharge limit entities are not "
                        "configured, so holding and exporting are disabled. "
                        "Re-run sensor discovery in Settings."
                    ),
                }
                overall_status = "ERROR"
            else:
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
