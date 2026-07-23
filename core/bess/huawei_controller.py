"""Huawei LUNA2000 inverter controller.

Huawei LUNA2000 batteries use a persistent, multi-period charge/discharge
list (huawei_solar.set_tou_periods, max 14 periods) gated behind the
battery's working-mode select entity. This is BESS's SM-Period-lists model
(like Growatt SPH), not SolaX's ephemeral per-period VPP commands — see
docs/superpowers/specs/2026-07-22-issue-120-huawei-inverter-platform-design.md
for the write-path and flash-wear rationale.

LUNA2000-only: LG RESU batteries use a price-bidding TOU format where the
inverter decides charge/discharge itself, incompatible with BESS owning the
optimization decision. Not built here.

Huawei Intent Mapping:
- GRID_CHARGING              → charge period (+)
- LOAD_SUPPORT/BATTERY_EXPORT → discharge period (-)
- SOLAR_STORAGE/SOLAR_EXPORT/IDLE → no period (self-consumption default)
"""

import logging
from datetime import datetime
from typing import ClassVar

from . import time_utils
from .dp_schedule import DPSchedule
from .exceptions import SystemConfigurationError
from .inverter_controller import InverterController
from .settings import BatterySettings

logger = logging.getLogger(__name__)

WORKING_MODE_TOU = "time_of_use_luna2000"

# "1234567" sets all seven day-slots via _parse_days_effective's
# `int(day) % 7` indexing (order-independent, presence-only) — verified
# against wlcrs/huawei_solar services.py. BESS always schedules every day
# the same way, so a fixed all-days string is sufficient; see open item #1
# in the design doc for live-hardware confirmation of this convention.
ALL_DAYS = "1234567"


class HuaweiController(InverterController):
    """Creates Huawei LUNA2000 inverter schedules from strategic intents.

    Writes a single combined charge/discharge period list (max 14 periods)
    via huawei_solar.set_tou_periods, gated behind the working-mode select.
    """

    supports_charge_rate_control: ClassVar[bool] = False
    discharge_rate_is_load_following: ClassVar[bool] = False

    MAX_TOU_PERIODS = 14

    CHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset({"GRID_CHARGING"})
    DISCHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset(
        {"LOAD_SUPPORT", "BATTERY_EXPORT"}
    )

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize the Huawei controller."""
        super().__init__(battery_settings)
        self._periods: list[dict] = []

    def _write_period_to_hardware(
        self,
        controller,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
    ) -> tuple[bool, str]:
        """No-op: Huawei deploys the full schedule atomically via set_tou_periods."""
        return True, ""

    @property
    def active_tou_intervals(self) -> list[dict]:
        """All TOU intervals are active — no per-slot hardware constraint."""
        return self.tou_intervals

    # ── Period grouping ───────────────────────────────────────────────────

    def _group_huawei_periods(self) -> list[dict]:
        """Group consecutive charge/discharge periods into flagged blocks."""
        if not self.strategic_intents:
            return []

        blocks: list[dict] = []
        current: dict | None = None

        for period, intent in enumerate(self.strategic_intents):
            if intent in self.CHARGE_INTENTS:
                flag = "+"
            elif intent in self.DISCHARGE_INTENTS:
                flag = "-"
            else:
                flag = None

            if flag is None:
                if current is not None:
                    blocks.append(current)
                    current = None
                continue

            if current is not None and current["flag"] == flag:
                current["end_period"] = period
            else:
                if current is not None:
                    blocks.append(current)
                current = {"start_period": period, "end_period": period, "flag": flag}

        if current is not None:
            blocks.append(current)

        return blocks

    def _enforce_period_limit(self, blocks: list[dict]) -> list[dict]:
        """Enforce MAX_TOU_PERIODS by dropping shortest blocks."""
        if len(blocks) <= self.MAX_TOU_PERIODS:
            return blocks

        logger.warning(
            "HUAWEI PERIOD LIMIT EXCEEDED: %d blocks, maximum is %d — dropping shortest",
            len(blocks),
            self.MAX_TOU_PERIODS,
        )

        def block_duration(b: dict) -> int:
            return b["end_period"] - b["start_period"] + 1

        sorted_by_duration = sorted(blocks, key=block_duration, reverse=True)
        kept = sorted_by_duration[: self.MAX_TOU_PERIODS]
        return sorted(kept, key=lambda b: b["start_period"])

    def _blocks_to_period_dicts(self, blocks: list[dict]) -> list[dict]:
        """Convert period blocks to time-string dicts with charge/discharge flag."""
        result = []
        for block in blocks:
            sh, sm = self._period_to_time(block["start_period"])
            eh, em = self._period_to_time(block["end_period"])

            if sh >= 24:
                continue  # Skip DST fall-back periods beyond 23:59
            if eh >= 24:
                eh, em = 23, 59
            else:
                em += 14

            result.append(
                {
                    "start_time": f"{sh:02d}:{sm:02d}",
                    "end_time": f"{eh:02d}:{em:02d}",
                    "flag": block["flag"],
                }
            )
        return result

    def _build_huawei_periods(self) -> None:
        """Build the combined charge/discharge period list from strategic intents."""
        blocks = self._group_huawei_periods()
        blocks = self._enforce_period_limit(blocks)
        self._periods = self._blocks_to_period_dicts(blocks)

        self.tou_intervals = []
        for idx, p in enumerate(self._periods):
            self.tou_intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "batt_mode": "battery_first" if p["flag"] == "+" else "grid_first",
                    "enabled": True,
                    "is_default": False,
                    "strategic_intent": (
                        "GRID_CHARGING" if p["flag"] == "+" else "LOAD_SUPPORT/BATTERY_EXPORT"
                    ),
                    "segment_id": idx + 1,
                }
            )

        logger.info("Huawei periods built: %d period(s)", len(self._periods))
        for p in self._periods:
            logger.info("  %s: %s-%s", p["flag"], p["start_time"], p["end_time"])

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Process DPSchedule with strategic intents into Huawei TOU periods."""
        logger.info("Creating Huawei schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        self._build_huawei_periods()

    # ── Hardware interface ────────────────────────────────────────────────

    def _periods_to_text(self) -> str:
        """Join periods into huawei_solar.set_tou_periods text format."""
        lines = [
            f"{p['start_time']}-{p['end_time']}/{ALL_DAYS}/{p['flag']}"
            for p in self._periods
        ]
        return "\n".join(lines)

    def write_schedule_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        """Write Huawei TOU periods to hardware.

        First confirms the connected battery is LUNA2000 (via the
        integration-exposed working-mode option list — see
        HomeAssistantAPIController.get_huawei_working_mode_options), then
        gates the write behind the working-mode select: sets it to
        time_of_use_luna2000 only when drifted, then writes the full
        period list (always a full rewrite — no differential update).

        Raises:
            SystemConfigurationError: If the connected battery does not
                expose 'time_of_use_luna2000' as a working-mode option
                (i.e. it's an LG RESU battery, not supported).
        """
        available_modes = controller.get_huawei_working_mode_options()
        if available_modes and WORKING_MODE_TOU not in available_modes:
            raise SystemConfigurationError(
                "Connected Huawei battery does not support "
                f"'{WORKING_MODE_TOU}' (available modes: {available_modes}). "
                "Only LUNA2000 batteries are supported — LG RESU is not."
            )

        writes = 0

        current_mode = controller.get_huawei_working_mode()
        if current_mode != WORKING_MODE_TOU:
            logger.info(
                "HUAWEI HARDWARE: working mode is %r, setting to %r",
                current_mode,
                WORKING_MODE_TOU,
            )
            try:
                controller.set_huawei_working_mode(WORKING_MODE_TOU)
                writes += 1
            except Exception as e:
                logger.error("FAILED: set_huawei_working_mode: %s", e)

        periods_text = self._periods_to_text()
        logger.info(
            "HUAWEI HARDWARE: Writing %d TOU period(s)", len(self._periods)
        )
        try:
            controller.write_huawei_tou_periods(periods_text)
            writes += 1
        except Exception as e:
            logger.error("FAILED: write_huawei_tou_periods: %s", e)

        return writes, 0

    def sync_soc_limits(self, controller) -> None:
        """Sync SOC limits from config to inverter hardware.

        Writes storage_charging_cutoff_capacity / storage_grid_charge_cutoff_state_of_charge
        directly via number.set_value — no read-then-compare, since the
        underlying HA entities already report their own state via the
        entity registry and a mismatched write is idempotent.
        """
        configured_max_soc = int(self.battery_settings.max_soc)
        configured_min_soc = int(self.battery_settings.min_soc)

        controller.set_charge_stop_soc(configured_max_soc)
        controller.set_discharge_stop_soc(configured_min_soc)
        logger.info(
            "Huawei SOC limits synced: charge_stop=%d%%, discharge_stop=%d%%",
            configured_max_soc,
            configured_min_soc,
        )

    def initialize_hardware(self, controller) -> None:
        self.sync_soc_limits(controller)

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Huawei has no readback API for TOU periods in this Phase 1 pass.

        huawei_solar exposes no read_tou_periods service — the periods are
        only visible via the (undocumented) coordinator state, not a public
        service call. Leaves strategic_intents empty; the next
        create_schedule() call populates it, matching the pattern used
        when hardware state genuinely can't be read back.
        """
        logger.info(
            "Huawei: no TOU readback available — starting with empty schedule"
        )

    # ── Schedule comparison ───────────────────────────────────────────────

    def compare_schedules(
        self, other_schedule: "HuaweiController", from_period: int = 0
    ) -> tuple[bool, str]:
        """Compare Huawei period lists with another schedule controller."""
        current = self._periods
        new = other_schedule._periods

        if len(current) != len(new):
            logger.info(
                "DECISION: Huawei period count differs — current=%d new=%d",
                len(current),
                len(new),
            )
            return True, "Huawei period count differs"

        for pa, pb in zip(current, new, strict=False):
            if (
                pa.get("start_time") != pb.get("start_time")
                or pa.get("end_time") != pb.get("end_time")
                or pa.get("flag") != pb.get("flag")
            ):
                logger.info(
                    "DECISION: Huawei periods differ — current=%s new=%s",
                    current,
                    new,
                )
                return True, "Huawei periods differ"

        logger.info("DECISION: Huawei schedules match")
        return False, ""

    # ── TOU display ──────────────────────────────────────────────────────

    def get_daily_TOU_settings(self) -> list[dict]:
        return list(self.tou_intervals)

    def get_all_tou_segments(self) -> list[dict]:
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

    def log_current_TOU_schedule(self, header: str = "") -> None:
        if header:
            logger.info(header)
        if not self._periods:
            logger.info("Huawei: No active TOU periods")
            return
        logger.info(" -= Huawei TOU Schedule =-")
        for i, p in enumerate(self._periods, 1):
            logger.info(
                "  Period %d: %s-%s (%s)",
                i,
                p["start_time"],
                p["end_time"],
                "charge" if p["flag"] == "+" else "discharge",
            )

    def log_detailed_schedule(self, header: str = "") -> None:
        if header:
            logger.info(header)
        if not self.strategic_intents:
            logger.info("Huawei: No schedule data available")
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        lines = [
            "\n╔═══════════════╦══════════════════╦═══════════════╗",
            "║  Time Period  ║ Strategic Intent ║ Huawei Action ║",
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
            marker = "*" if run_start <= current_period <= run_end else " "

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

    # ── Health check ─────────────────────────────────────────────────────

    def check_health(self, controller) -> list:
        """Check Huawei battery control capabilities via the working-mode entity."""
        try:
            mode = controller.get_huawei_working_mode()
            if mode is not None:
                check = {
                    "component": "Huawei working mode (select)",
                    "status": "OK",
                    "message": f"Connected — current mode={mode}",
                }
                overall_status = "OK"
            else:
                check = {
                    "component": "Huawei working mode (select)",
                    "status": "ERROR",
                    "message": "Entity returned no state — check sensor config",
                }
                overall_status = "ERROR"
        except Exception as e:
            check = {
                "component": "Huawei working mode (select)",
                "status": "ERROR",
                "message": f"Read failed: {e}",
            }
            overall_status = "ERROR"

        return [
            {
                "name": "Battery Control (Huawei LUNA2000)",
                "description": "Controls Huawei battery TOU schedule via set_tou_periods",
                "required": True,
                "status": overall_status,
                "checks": [check],
                "last_run": datetime.now().isoformat(),
            }
        ]
