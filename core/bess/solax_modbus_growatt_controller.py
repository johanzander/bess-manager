"""Growatt MIN/SPH inverter controller using solax_modbus (TOU or VPP mode).

This controller supports Growatt inverters connected via the solax_modbus
HACS integration (local Modbus) instead of the growatt_server cloud
integration, covering both GEN4 (MIN/MOD/MID) and GEN3 (MIX/SPA/SPH) hardware.

Two control strategies are supported, selected via ``control_mode``:

- ``"tou"`` (default, GEN4 only) — a **single TOU segment** (slot 1) with a
  full-day time window (00:00-23:59). The battery mode is updated per-period
  via ``apply_period`` — only when the mode actually changes — reducing the
  required entity count from 45 (9 slots x 5 entities) to just 5.
- ``"vpp"`` — Growatt's VPP remote power control registers (30100/30407-30410,
  present on both GEN3 and GEN4 per the solax_modbus Growatt plugin source),
  applying per-period power commands with no persistent schedule at all —
  the same "SM-Ephemeral" model ``SolaxController`` already uses for real
  SolaX hardware. See issue #118: GEN3 has no working TOU path today, so VPP
  is its only control mode; GEN4 gets a choice, with VPP intended to
  eventually replace TOU once proven on real hardware.

Mode semantics (TOU):
- ``load_first`` — inverter default when no TOU segment is active
- ``battery_first`` — charge from grid + solar (GRID_CHARGING intent)
- ``grid_first`` — export to grid (BATTERY_EXPORT intent)

VPP intent -> power mapping mirrors ``SolaxController``, plus a
block_passive_charging distinction at rate=0 (#355 -- see
docs/superpowers/specs/2026-07-20-vpp-passive-charge-block-design.md):
- GRID_CHARGING              -> power=+100%, remote_control enabled
- LOAD_SUPPORT/BATTERY_EXPORT (rate>0) -> power=-rate%, remote_control enabled
- SOLAR_STORAGE/IDLE (rate=0, block_passive_charging=False) -> remote_control
  disabled (load_first self-use -- battery may absorb solar surplus)
- SOLAR_EXPORT (rate=0, block_passive_charging=True) -> power=0,
  remote_control ENABLED (grid_first hold, per the Growatt VPP protocol
  V2.01 section 3.5 -- battery held flat, solar bypasses to grid)

The VPP fallback timer (``vpp_time``, register 30408) is rewritten every
active period, resetting the inverter's own dead-man's-switch: if BESS stops
writing (crash, restart), the inverter reverts to load_first on its own once
the timer lapses — the same safety property ``SolaxController`` gets from
SolaX's autorepeat duration.
"""

import logging
import time

from . import time_utils
from .dp_schedule import DPSchedule
from .growatt_min_controller import GrowattMinController
from .health_check import perform_health_check
from .settings import BatterySettings

logger = logging.getLogger(__name__)

# VPP fallback timer, in minutes. Must be > 15 (period length) so a normal
# hourly re-optimization cadence never lets the timer lapse; keeps the
# inverter's dead-man's-switch tight if BESS actually stops writing.
_VPP_FALLBACK_MINUTES = 20


class SolaxModbusGrowattController(GrowattMinController):
    """Growatt MIN/SPH controller using solax_modbus, TOU or VPP control.

    ``control_mode="tou"`` manages a single TOU segment (slot 1), updating its
    mode each period when needed. ``control_mode="vpp"`` issues per-period VPP
    power commands instead, with no persistent TOU schedule — analogous to
    how ``SolaxController`` applies per-period VPP commands for real SolaX
    hardware, with ``write_schedule_to_hardware`` doing only the one-time VPP
    enable sequence.
    """

    def __init__(
        self, battery_settings: BatterySettings, control_mode: str = "tou"
    ) -> None:
        """Initialize the Growatt solax_modbus controller.

        Args:
            battery_settings: Battery configuration.
            control_mode: "tou" (single-segment TOU, GEN4 default) or "vpp"
                (VPP remote power control, GEN3's only control mode).
        """
        super().__init__(battery_settings)
        if control_mode not in ("tou", "vpp"):
            raise ValueError(
                f"Unknown control_mode {control_mode!r}, expected 'tou' or 'vpp'"
            )
        self.control_mode = control_mode
        self._last_written_tou_mode: str | None = None
        # VPP-only state, seeded from hardware in read_and_initialize_from_hardware
        # rather than persisted as class-level statics — controllers are
        # recreated each optimization cycle, so state must survive via
        # read-back, the same pattern TOU mode already uses.
        self._vpp_status_confirmed: bool = False
        self._last_written_vpp_remote_control: bool | None = None
        self._last_written_vpp_power: int | None = None

    @property
    def _is_tou_control(self) -> bool:
        """Single source of truth for the TOU-vs-VPP capability split below.

        True in TOU mode: the EMS charge/discharge-rate registers are used
        directly, and discharge_rate acts as a load_first ceiling. False in
        VPP mode: power is driven by vpp_power (RAM) instead, as an
        immediate forced command (#324) -- neither EMS-rate-control nor
        load-following semantics apply.
        """
        return self.control_mode != "vpp"

    @property
    def supports_charge_rate_control(self) -> bool:
        """VPP mode drives power via vpp_power (RAM); no EMS rate writes.

        TOU mode still uses the EMS charge/discharge-rate registers
        directly, so this stays True there (base class default).
        """
        return self._is_tou_control

    @property
    def discharge_rate_is_load_following(self) -> bool:
        """TOU mode's discharge_rate is a load_first ceiling; VPP mode's is
        an immediate forced vpp_power command. See #324.
        """
        return self._is_tou_control

    # ── Abstract property ────────────────────────────────────────────────────

    @property
    def active_tou_intervals(self) -> list[dict]:
        """Return the single TOU segment if active, else empty list.

        Always empty in VPP mode — there is no persistent TOU schedule.
        """
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
        """Store strategic intents — control is applied per-period, no batch TOU needed.

        Skips the parent's 9-segment TOU interval computation.  Strategic intents
        are stored and hourly settings calculated for API/display consumption.

        Args:
            schedule: DPSchedule containing strategic_intent list.
            current_period: Current 15-minute period (0-95).
            previous_tou_intervals: Unused for single-segment/VPP approach.
        """
        logger.info(
            "Creating %s schedule from strategic intents", self.control_mode.upper()
        )

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        logger.info(
            "%s: %d strategic intents loaded (quarterly resolution)",
            self.control_mode.upper(),
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

        if self.control_mode == "tou":
            self._update_tou_display_state()

    # ── Hardware interface ────────────────────────────────────────────────────

    def apply_period(
        self,
        controller,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
    ) -> tuple[bool, str]:
        """Write period control settings for the current control mode.

        Args:
            controller: HomeAssistantAPIController instance
            grid_charge: Whether to enable grid charging
            discharge_rate: Discharge power rate (0-100%), post-inhibit
            block_passive_charging: Whether passive solar->battery charging
                should be blocked this period (SOLAR_EXPORT). TOU mode
                ignores this -- realized via the separate charge_rate
                register instead. VPP mode acts on it directly (#355): it
                has no charge_rate register, so this is its only channel for
                distinguishing SOLAR_EXPORT (hold, block charging) from
                SOLAR_STORAGE/IDLE (self-use, allow charging) at
                discharge_rate=0.

        Returns:
            Tuple of (success, error_message). error_message is empty on success.
        """
        if self.control_mode == "vpp":
            return self._apply_period_vpp(
                controller, grid_charge, discharge_rate, block_passive_charging
            )
        return self._apply_period_tou(controller, grid_charge, discharge_rate)

    def _apply_period_tou(
        self, controller, grid_charge: bool, discharge_rate: int
    ) -> tuple[bool, str]:
        """Write period control settings, including TOU mode update when needed.

        Derives the required TOU mode from the current period's strategic intent.
        Only writes the TOU segment when the mode actually changes, minimising
        inverter writes.
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

    def _intent_to_vpp(
        self,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
    ) -> tuple[int, bool]:
        """Map (grid_charge, discharge_rate, block_passive_charging) to
        (power_pct, remote_control_enabled).

        - grid_charge=True                       -> +100% (charge at max rate)
        - grid_charge=False, rate=0, block=True   -> 0%, remote control ENABLED
          (SOLAR_EXPORT). Per the Growatt VPP protocol (V2.01, section 3.5),
          vpp_power<=0 with remote control enabled selects "grid first"
          priority, holding the battery instead of self-use absorbing solar
          surplus into it -- see #355 and
          docs/superpowers/specs/2026-07-20-vpp-passive-charge-block-design.md.
          Not yet real-hardware-validated; ships experimental pending
          confirmation.
        - grid_charge=False, rate=0, block=False  -> 0%, remote control DISABLED
          (load_first self-use -- SOLAR_STORAGE/IDLE, battery may absorb solar)
        - grid_charge=False, rate>0                -> -rate% (discharge/export)
        """
        if grid_charge:
            return 100, True
        if discharge_rate == 0:
            return 0, block_passive_charging
        return -discharge_rate, True

    def seed_from(self, other: "GrowattMinController") -> None:
        """See base docstring. Adds VPP confirmation/tracking state and the
        last-written TOU mode, both of which gate redundant hardware writes."""
        super().seed_from(other)
        if isinstance(other, SolaxModbusGrowattController):
            self._vpp_status_confirmed = other._vpp_status_confirmed
            self._last_written_vpp_remote_control = (
                other._last_written_vpp_remote_control
            )
            self._last_written_vpp_power = other._last_written_vpp_power
            self._last_written_tou_mode = other._last_written_tou_mode

    def _ensure_vpp_status_enabled(self, controller) -> None:
        """Enable the VPP Status register once, if not already confirmed.

        VPP Remote Control has no effect while VPP Status is disabled — this
        must be written (with a settle delay) before the first Remote Control
        write, per real-hardware testing on issue #118.
        """
        if self._vpp_status_confirmed:
            return
        controller.set_growatt_vpp_status(True)
        controller.set_growatt_vpp_allow_ac_charging(True)
        time.sleep(1)
        self._vpp_status_confirmed = True

    def _apply_period_vpp(
        self,
        controller,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
    ) -> tuple[bool, str]:
        """Write one period's VPP power command.

        Only writes when the command actually changes (remote-control state or
        power level), minimising inverter writes — the fallback timer is
        rewritten alongside any active command to keep the dead-man's-switch
        from lapsing during a stable run of identical periods.
        """
        power_pct, remote_control_enabled = self._intent_to_vpp(
            grid_charge, discharge_rate, block_passive_charging
        )

        command_changed = (
            remote_control_enabled != self._last_written_vpp_remote_control
            or (remote_control_enabled and power_pct != self._last_written_vpp_power)
        )
        if not command_changed:
            return True, ""

        try:
            self._ensure_vpp_status_enabled(controller)
            controller.set_growatt_vpp_period(
                remote_control_enabled=remote_control_enabled,
                power_pct=power_pct,
                fallback_minutes=_VPP_FALLBACK_MINUTES,
            )
            self._last_written_vpp_remote_control = remote_control_enabled
            self._last_written_vpp_power = power_pct if remote_control_enabled else None
            return True, ""
        except Exception as e:
            logger.error("FAILED: Growatt VPP period write: %s", e)
            return False, str(e)

    def write_schedule_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        """Initialise hardware for the current control mode.

        TOU mode: sets segment 1 to the current period's mode with a full-day
        window. Legacy segments 2-9 are cleaned up at startup
        (read_and_initialize_from_hardware), not here.

        VPP mode: enables VPP Status/AC-charging once, then issues the initial
        per-period power command — subsequent periods go through apply_period.

        Args:
            controller: HomeAssistantAPIController instance
            effective_period: Period (0-95) from which to start applying changes
            current_tou: TOU intervals currently active on the inverter (unused)

        Returns:
            Tuple of (segments_updated, segments_disabled)
        """
        if self.control_mode == "vpp":
            grid_charge, discharge_rate, block_passive_charging = False, 0, False
            if effective_period < len(self.strategic_intents):
                intent = self.strategic_intents[effective_period]
                grid_charge, discharge_rate = self._map_intent_to_rates(
                    intent, battery_action_kw=0.0
                )
                block_passive_charging = (
                    self.INTENT_TO_CONTROL[intent]["charge_rate"] == 0
                )
            success, _ = self._apply_period_vpp(
                controller, grid_charge, discharge_rate, block_passive_charging
            )
            return (1, 0) if success else (0, 0)

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
        """Read current control state from hardware and seed internal trackers.

        Pure read — no hardware writes. VPP mode reads back the VPP Status and
        Remote Control registers so state survives controller
        re-instantiation (BESS recreates the controller each optimization
        cycle) without resorting to class-level statics.
        """
        self.current_hour = current_hour

        if self.control_mode == "vpp":
            status = controller.get_growatt_vpp_status()
            self._vpp_status_confirmed = status == "Enabled"
            remote_control = controller.get_growatt_vpp_remote_control()
            self._last_written_vpp_remote_control = (
                remote_control == "Enabled" if remote_control is not None else None
            )
            logger.info(
                "Growatt VPP: initialised from hardware — status=%s remote_control=%s",
                status,
                remote_control,
            )
            return

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
        if self.control_mode == "vpp":
            # VPP mode must never touch TOU entities — not even to disable
            # them. A GEN4 install switching tou -> vpp with a still-active
            # TOU segment relies on the user (or setup wizard guidance) to
            # clear it, not on a runtime write here — see issue #309.
            return
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
        """Return the single TOU segment if active. Always empty in VPP mode."""
        if not self.tou_intervals:
            return []
        return [seg.copy() for seg in self.tou_intervals]

    def get_all_tou_segments(self, current_period: int | None = None):
        """Return TOU segments with defaults for complete 24-hour coverage.

        For the single-segment/VPP approach, returns strategic-intent groups
        as display segments (no hardware TOU segments exist in VPP mode).
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
        """Log current single-segment TOU state, or VPP command state."""
        if header:
            logger.info(header)

        if self.control_mode == "vpp":
            if self._last_written_vpp_remote_control:
                logger.info(
                    "Growatt VPP: remote control enabled, power=%s%%",
                    self._last_written_vpp_power,
                )
            else:
                logger.info("Growatt VPP: remote control disabled (load_first)")
            return

        mode = self._last_written_tou_mode or "load_first"
        if mode == "load_first":
            logger.info("Modbus: TOU segment 1 disabled (load_first default)")
        else:
            logger.info("Modbus: TOU segment 1 = %s (00:00-23:59)", mode)

    # ── Health check ─────────────────────────────────────────────────────────

    def check_health(self, controller) -> list:
        """Check battery control capabilities for the active control mode."""
        # grid_charge_enabled is shared by both modes; the EMS rate/stop-SOC
        # entities are TOU-only — VPP setups commonly have them disabled in
        # HA since VPP mode never reads or writes them (issue #308).
        all_methods = (
            ["grid_charge_enabled"]
            if self.control_mode == "vpp"
            else [
                "get_charging_power_rate",
                "get_discharging_power_rate",
                "grid_charge_enabled",
                "get_charge_stop_soc",
                "get_discharge_stop_soc",
            ]
        )
        health_check = perform_health_check(
            component_name="Battery Control",
            description="Controls battery charging and discharging schedule",
            is_required=True,
            controller=controller,
            all_methods=all_methods,
        )

        required_keys = (
            [
                "growatt_vpp_status",
                "growatt_vpp_remote_control",
                "growatt_vpp_allow_ac_charging",
                "growatt_vpp_time",
                "growatt_vpp_power",
            ]
            if self.control_mode == "vpp"
            else [
                "tou_time_1_enabled",
                "tou_time_1_begin",
                "tou_time_1_end",
                "tou_time_1_mode",
                "tou_time_1_update",
            ]
        )
        entity_label = "VPP Entity" if self.control_mode == "vpp" else "TOU Entity"
        for key in required_keys:
            entity_id = controller.sensors.get(key, "")
            if entity_id:
                status, error = "OK", None
            else:
                status, error = "ERROR", "Not configured — re-run setup wizard"
            health_check["checks"].append(
                {
                    "name": f"{entity_label}: {key}",
                    "key": key,
                    "method_name": None,
                    "entity_id": entity_id or "Not configured",
                    "status": status,
                    "rawValue": None,
                    "displayValue": entity_id or "Not configured",
                    "error": error,
                }
            )

        # Re-evaluate overall status including the mode-specific checks
        has_error = any(c["status"] == "ERROR" for c in health_check["checks"])
        has_warning = any(c["status"] == "WARNING" for c in health_check["checks"])
        if has_error:
            health_check["status"] = "ERROR"
        elif has_warning:
            health_check["status"] = "WARNING"

        return [health_check]
