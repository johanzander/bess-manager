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
import re
from datetime import datetime
from typing import ClassVar

from . import time_utils
from .dp_schedule import DPSchedule
from .exceptions import SystemConfigurationError
from .inverter_controller import InverterController
from .settings import BatterySettings

logger = logging.getLogger(__name__)

WORKING_MODE_TOU = "time_of_use_luna2000"

# Working-mode select options that mean "BESS-controlled Time Of Use", across
# the integrations that front a Huawei battery. Stock huawei_solar exposes
# ``time_of_use_luna2000``; Huawei EMMA's EmmaEssControlMode select exposes a
# localized ``Time Of Use`` label for the same thing. The other EMMA modes
# (Maximum Self Consumption, Fully Fed To Grid, ...) are deliberately absent so
# a genuinely non-TOU battery (e.g. LG RESU) still fails the guard below.
WORKING_MODE_TOU_EQUIVALENTS = ("time_of_use_luna2000", "Time Of Use")


def _normalize_working_mode(mode: str) -> str:
    """Lowercase and collapse whitespace/underscores for tolerant matching.

    The exposed option label differs by integration and locale (``Time Of
    Use`` vs ``time_of_use``), so equality on the raw string is too brittle —
    normalizing both sides recognizes the same option across those variants.
    """
    return re.sub(r"[\s_]+", " ", str(mode).strip().lower())


_TOU_NORMALIZED_EQUIVALENTS = frozenset(
    _normalize_working_mode(mode) for mode in WORKING_MODE_TOU_EQUIVALENTS
)


def _resolve_tou_working_mode(available_modes: list[str]) -> str:
    """Return the integration's own option string for BESS Time Of Use control.

    An empty ``available_modes`` means the option list was unreadable (a
    transient HA read hiccup): proceed with the stock LUNA2000 option rather
    than turning a read glitch into a scheduling outage. A non-empty list that
    contains no TOU-equivalent option is a real incompatibility (e.g. an LG
    RESU battery) and raises. Matching is normalized so a re-cased or localized
    label of the same option is still recognized, and the actual exposed
    string is returned so ``set_huawei_working_mode`` writes what the
    integration expects.
    """
    if not available_modes:
        return WORKING_MODE_TOU
    for mode in available_modes:
        if _normalize_working_mode(mode) in _TOU_NORMALIZED_EQUIVALENTS:
            return mode
    raise SystemConfigurationError(
        "Connected Huawei battery does not expose a supported Time Of Use "
        f"working mode (available modes: {available_modes}). Supported "
        f"options: {list(WORKING_MODE_TOU_EQUIVALENTS)}. Only LUNA2000/EMMA "
        "Time Of Use batteries are supported — LG RESU is not."
    )


# The integration this platform normally drives. An install pointing
# inverter.service_domain elsewhere is declaring a compatible integration
# (e.g. an EMMA behind its own TLS bridge, PR #412), which is what makes an
# absent working-mode select expected rather than a misconfiguration.
DEFAULT_SERVICE_DOMAIN = "huawei_solar"

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

    # A discharge period is a time slot, not a rate -- there is no per-period
    # control that could deliver a partial load cover as planned.
    load_support_delivers_exact_cover: ClassVar[bool] = False

    CONTROL_MODEL: ClassVar[str] = "period_list"

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

    def _group_huawei_periods(self, intents: list[str]) -> list[dict]:
        """Group consecutive charge/discharge periods into flagged blocks."""
        if not intents:
            return []

        blocks: list[dict] = []
        current: dict | None = None

        for period, intent in enumerate(intents):
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
                    "days": ALL_DAYS,
                    "flag": block["flag"],
                }
            )
        return result

    def _build_candidate(self, intents: list[str]) -> list[dict]:
        """Compute the Huawei period list for ``intents``, without mutating self.

        Shared by apply_intents (commits onto self) and evaluate_intents
        (diffs against self's current state).
        """
        blocks = self._group_huawei_periods(intents)
        blocks = self._enforce_period_limit(blocks)
        periods = self._blocks_to_period_dicts(blocks)

        logger.info("Huawei periods built: %d period(s)", len(periods))
        for p in periods:
            logger.info("  %s: %s-%s", p["flag"], p["start_time"], p["end_time"])

        return periods

    def _periods_to_tou_intervals(
        self, periods: list[dict], intent: str | None = None
    ) -> list[dict]:
        """Render periods for display. ``intent`` overrides the flag-derived
        label for periods BESS read back rather than planned."""
        return [
            {
                "start_time": p["start_time"],
                "end_time": p["end_time"],
                "enabled": True,
                "is_default": False,
                "strategic_intent": intent
                or (
                    "GRID_CHARGING"
                    if p["flag"] == "+"
                    else "LOAD_SUPPORT/BATTERY_EXPORT"
                ),
                "segment_id": idx + 1,
            }
            for idx, p in enumerate(periods)
        ]

    def _build_huawei_periods(self) -> None:
        """Unchanged public behavior: mutates self._periods/self.tou_intervals
        from self.strategic_intents. Delegates to _build_candidate, shared
        with apply_intents/evaluate_intents."""
        self._periods = self._build_candidate(self.strategic_intents)
        self.tou_intervals = self._periods_to_tou_intervals(self._periods)

    def apply_intents(self, schedule: DPSchedule, current_period: int = 0) -> None:
        """Adopt this cycle's DP intent list, rebuilding Huawei TOU periods."""
        logger.info("Creating Huawei schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        self._build_huawei_periods()

    # ── Hardware interface ────────────────────────────────────────────────

    def _periods_to_text(self) -> str:
        """Join periods into huawei_solar.set_tou_periods text format."""
        lines = [
            f"{p['start_time']}-{p['end_time']}/{p['days']}/{p['flag']}"
            for p in self._periods
        ]
        return "\n".join(lines)

    @staticmethod
    def _period_from_text(line: str) -> dict:
        """Inverse of one _periods_to_text line: "HH:MM-HH:MM/<days>/<+|->".

        Raises:
            ValueError: If the line isn't a period. A period BESS cannot read
                is not one it may drop — a dropped period would make the
                hardware look like it already holds BESS's plan.
        """
        times, days, flag = line.strip().split("/")
        start_time, end_time = times.split("-")
        if flag not in ("+", "-"):
            raise ValueError(f"Unknown Huawei charge flag {flag!r} in {line!r}")
        return {
            "start_time": start_time,
            "end_time": end_time,
            "days": days,
            "flag": flag,
        }

    def _read_periods_from_hardware(self, controller) -> list[dict]:
        """The period list the battery currently holds, parsed.

        Raises:
            ValueError: If a reported period can't be parsed.
            SystemConfigurationError: If the sensor can't be read — an
                unreadable entity must not read as "no periods programmed".
        """
        return [
            self._period_from_text(line)
            for line in controller.read_huawei_tou_periods()
        ]

    def sync_to_hardware(
        self,
        controller,
        effective_period: int,
    ) -> tuple[int, int]:
        """Write Huawei TOU periods to hardware, unless it already holds them.

        The period list is compared against one read fresh from the battery,
        never against this controller's own model of it — the same
        read-compare-write Growatt MIN adopted in #551/#552, for the same
        reason: a model can only ever claim what BESS meant to write. Here it
        also spares the battery a flash write per cycle, since set_tou_periods
        rewrites the whole list atomically and cannot update just what moved.
        The comparison is skipped, and the write always made, when no TOU
        period sensor is mapped (#431). The read happens before any hardware
        write, so a failed read leaves the battery exactly as it was.

        First confirms the connected battery is LUNA2000 (via the
        integration-exposed working-mode option list — see
        HomeAssistantAPIController.get_huawei_working_mode_options), then
        gates the write behind the working-mode select: sets it to the
        integration's equivalent Time Of Use option only when drifted, then
        writes the full period list (always a full rewrite — no differential
        update).

        The whole gate is skipped when no working-mode entity is mapped.
        Installs behind an energy manager (Huawei EMMA, PR #412) expose no
        LUNA2000 working-mode select — the manager owns the mode itself.
        Skipping it also skips the LG RESU family check below, so BESS is
        trusting the operator's platform choice there; that is logged here
        and surfaced by check_health rather than passing unremarked.

        Raises:
            SystemConfigurationError: If the connected battery exposes a
                non-empty working-mode option list with no supported Time Of
                Use option (stock ``time_of_use_luna2000`` or EMMA's
                ``Time Of Use``) — i.e. it's an LG RESU battery, not supported.
        """
        writes = 0

        # Read before writing anything. The read raises rather than reporting
        # an empty list, so ordering decides what a failed read leaves behind:
        # done here it aborts the cycle untouched, and BSM sets
        # _hardware_write_pending and retries the whole sync next cycle. Done
        # after set_grid_charge, it would leave the battery holding a new
        # grid-charge state against the old period list for an hour.
        hardware_periods = (
            self._read_periods_from_hardware(controller)
            if controller.is_sensor_configured("huawei_tou_periods")
            else None
        )

        has_working_mode = controller.is_sensor_configured("huawei_working_mode")

        if not has_working_mode:
            logger.info(
                "HUAWEI HARDWARE: no working mode entity mapped — skipping the "
                "working-mode gate and the LUNA2000/LG RESU battery family "
                "check. Expected on EMMA-managed installs, where the energy "
                "manager owns the battery working mode."
            )
        else:
            available_modes = controller.get_huawei_working_mode_options()
            target_mode = _resolve_tou_working_mode(available_modes)

            current_mode = controller.get_huawei_working_mode()
            if current_mode != target_mode:
                logger.info(
                    "HUAWEI HARDWARE: working mode is %r, setting to %r",
                    current_mode,
                    target_mode,
                )
                try:
                    controller.set_huawei_working_mode(target_mode)
                    writes += 1
                except Exception as e:
                    logger.error("FAILED: set_huawei_working_mode: %s", e)

        has_charge_period = any(p["flag"] == "+" for p in self._periods)
        try:
            controller.set_grid_charge(has_charge_period)
            writes += 1
        except Exception as e:
            logger.error("FAILED: set_grid_charge: %s", e)

        if hardware_periods is not None and hardware_periods == self._periods:
            logger.info(
                "HUAWEI HARDWARE: battery already holds these %d TOU period(s) "
                "— no write",
                len(self._periods),
            )
            return writes, 0

        periods_text = self._periods_to_text()
        logger.info("HUAWEI HARDWARE: Writing %d TOU period(s)", len(self._periods))
        try:
            controller.write_huawei_tou_periods(periods_text)
            writes += 1
        except Exception as e:
            logger.error("FAILED: write_huawei_tou_periods: %s", e)

        return writes, 0

    def sync_soc_limits(self, controller) -> None:
        """Sync SOC limits from config to inverter hardware via entity writes.

        Reads current charge/discharge stop SOC from the inverter and writes
        back only if they differ from the configured max_soc / min_soc.
        """
        configured_max_soc = int(self.battery_settings.max_soc)
        configured_min_soc = int(self.battery_settings.min_soc)

        actual_max_soc = controller.get_charge_stop_soc()
        actual_min_soc = controller.get_discharge_stop_soc()

        if (
            actual_max_soc == configured_max_soc
            and actual_min_soc == configured_min_soc
        ):
            logger.info(
                "Huawei SOC limits verified: charge_stop=%d%%, discharge_stop=%d%%",
                actual_max_soc,
                actual_min_soc,
            )
            return

        if actual_max_soc != configured_max_soc:
            controller.set_charge_stop_soc(configured_max_soc)
            logger.info("Set Huawei charge_stop_soc to %d%%", configured_max_soc)

        if actual_min_soc != configured_min_soc:
            controller.set_discharge_stop_soc(configured_min_soc)
            logger.info("Set Huawei discharge_stop_soc to %d%%", configured_min_soc)

    def initialize_hardware(self, controller) -> None:
        self.sync_soc_limits(controller)

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Initialize the period list from what the battery currently holds.

        Readback is available when the integration's TOU period sensor is
        mapped — declared configuration, not a probe (#431). Installs whose
        integration exposes no such entity keep the original behaviour: an
        empty schedule that the next apply_intents() converges, at the cost
        of one redundant rewrite per restart.

        strategic_intents stays empty either way: the battery reports charge
        and discharge periods, never which intent produced them.
        """
        if not controller.is_sensor_configured("huawei_tou_periods"):
            logger.info(
                "Huawei: no TOU period sensor mapped — starting with empty schedule"
            )
            return

        logger.info("Reading Huawei TOU periods from the battery")
        self._periods = self._read_periods_from_hardware(controller)
        self.tou_intervals = self._periods_to_tou_intervals(
            self._periods, intent="existing_schedule"
        )

        logger.info(
            "Huawei initialized from hardware: %d period(s)", len(self._periods)
        )
        for p in self._periods:
            logger.info(
                "  %s: %s-%s/%s", p["flag"], p["start_time"], p["end_time"], p["days"]
            )

    # ── Schedule comparison ───────────────────────────────────────────────

    def evaluate_intents(
        self, schedule: DPSchedule, current_period: int = 0
    ) -> tuple[bool, str]:
        """Compare Huawei periods a candidate schedule would produce against
        what's currently applied."""
        candidate_intents = schedule.original_dp_results["strategic_intent"]
        new = self._build_candidate(candidate_intents)
        current = self._periods

        if len(current) != len(new):
            logger.info(
                "DECISION: Huawei period count differs — current=%d new=%d",
                len(current),
                len(new),
            )
            return True, "Huawei period count differs"

        for pa, pb in zip(current, new, strict=False):
            # days is part of the identity of a period, not decoration: BESS
            # always writes all-days, so a period read back covering only
            # some weekdays leaves BESS's own period genuinely missing (#431).
            if (
                pa["start_time"] != pb["start_time"]
                or pa["end_time"] != pb["end_time"]
                or pa["days"] != pb["days"]
                or pa["flag"] != pb["flag"]
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
        if not controller.is_sensor_configured("huawei_working_mode"):
            # A missing working-mode entity means two different things, and
            # the configured service domain is what separates them — declared
            # configuration, not a probe of the hardware.
            #
            # On an install driving a compatible integration under its own
            # domain, the energy manager (EMMA) owns the mode and its absence
            # is the expected shape. On a stock huawei_solar install it is a
            # misconfiguration with real consequences: BESS writes TOU periods
            # the battery never acts on, because nothing puts it into
            # time_of_use_luna2000. That must not read as a warning.
            is_managed_install = (
                getattr(controller, "service_domain", "") or ""
            ) != DEFAULT_SERVICE_DOMAIN
            status = "WARNING" if is_managed_install else "ERROR"
            message = (
                (
                    "Not mapped — working-mode writes and the LUNA2000/LG RESU "
                    "battery family check are skipped. Expected on "
                    "EMMA-managed installs."
                )
                if is_managed_install
                else (
                    "Not mapped — BESS cannot set the battery to "
                    f"'{WORKING_MODE_TOU}', so written TOU periods will have no "
                    "effect. Map the working-mode select in Settings, or set "
                    "the inverter service domain if this battery is managed by "
                    "an energy manager that owns the mode."
                )
            )
            return [
                {
                    "name": "Battery Control (Huawei LUNA2000)",
                    "description": (
                        "Controls Huawei battery TOU schedule via set_tou_periods"
                    ),
                    "required": True,
                    "status": status,
                    "checks": [
                        {
                            "component": "Huawei working mode (select)",
                            "status": status,
                            "message": message,
                        }
                    ],
                    "last_run": datetime.now().isoformat(),
                }
            ]

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
