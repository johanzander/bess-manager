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

VPP intent -> power mapping originally mirrored ``SolaxController``, plus a
block_passive_charging distinction at rate=0 (#355 -- see
docs/superpowers/specs/2026-07-20-vpp-passive-charge-block-design.md).
LOAD_SUPPORT has since diverged (#413 -- see below): ``SolaxController``
still forces a rate for it, this controller now releases VPP control instead.
- GRID_CHARGING              -> power=+100%, remote_control enabled
- BATTERY_EXPORT (rate>0)    -> power=-rate%, remote_control enabled
- LOAD_SUPPORT (any rate)    -> power=0, remote_control DISABLED, regardless
  of discharge_rate (#413 -- releases control to the inverter's own
  load-following self-use instead of forcing a fixed discharge rate, which
  causes unnecessary grid imports/exports whenever the schedule's load
  prediction misses)
- SOLAR_STORAGE (rate=0, block_passive_charging=False) -> remote_control
  disabled (load_first self-use -- battery may absorb solar surplus)
- IDLE (rate=0) -> power=+1%, remote_control ENABLED (battery-first hold,
  per the Growatt VPP protocol V2.01 section 3.5 -- #466: load_first
  self-use discharges the battery to cover house load, but the DP's own
  cost model never credits battery discharge during IDLE
  (_idle_battery_flows in dp_battery_algorithm.py); battery-first keeps
  self-consumption on grid/solar instead. grid_first (power<=0) does not
  achieve this -- per #118, self-consumption is still drawn from the
  battery in grid_first, only battery-first releases it to grid/solar)
- IDLE (rate=0) **at the reserve floor** -> power=0, remote_control
  DISABLED (#592 -- the hold above protects stored energy, and at the floor
  there is none left to protect; keeping remote control enabled rewrites the
  command every period to refresh the fallback timer, so the inverter is
  never handed back and its BMS never sleeps). Releasing rather than
  commanding power=0 with remote control enabled is what keeps this
  flow-neutral -- see _intent_to_vpp
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
from typing import ClassVar

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
    hardware, with ``sync_to_hardware`` doing only the one-time VPP
    enable sequence.
    """

    # TOU mode's per-period write goes through the inherited base
    # _write_period_to_hardware() (#166 comment above _apply_period_tou):
    # writes unconditionally rather than gating on the last-written value,
    # since the #166 gate-removal is itself an active real-hardware test on
    # GEN4. Do not let GrowattMinController's dedupe_register_writes (#402,
    # cloud-only) silently re-gate this.
    dedupe_register_writes: ClassVar[bool] = False

    # Export-limit registers (122/123) exist independent of control_mode —
    # true in both TOU and VPP mode, unlike supports_charge_rate_control.
    supports_export_limit_control: ClassVar[bool] = True

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
        # One flag per flash register, not one for both: they are written
        # together but can drift apart, and repairing the drifted one must not
        # cost a redundant flash write on the healthy one (#399).
        self._vpp_status_confirmed: bool = False
        self._vpp_ac_charging_confirmed: bool = False
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
    def CONTROL_MODEL(self) -> str:
        """Dual-mode: real TOU register in "tou" mode, VPP power+remote_control
        in "vpp" mode — see _is_tou_control for the underlying capability
        split this mirrors."""
        return "tou_register" if self._is_tou_control else "vpp_power"

    @property
    def supports_charge_rate_control(self) -> bool:
        """VPP mode drives power via vpp_power (RAM); no EMS rate writes.

        TOU mode still uses the EMS charge/discharge-rate registers
        directly, so this stays True there (base class default).
        """
        return self._is_tou_control

    def apply_export_limit(self, controller, curtail: bool) -> None:
        """Curtail/release PV export via the CT-meter export-limit registers
        (122/123, issue #269). Independent of control_mode (tou/vpp)."""
        controller.set_growatt_export_limit(curtail)

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

    def apply_intents(self, schedule: DPSchedule, current_period: int = 0) -> None:
        """Adopt this cycle's DP intent list — control is applied per-period,
        no batch TOU/VPP schedule computed here.

        Skips the parent's 9-segment TOU interval computation.  Strategic intents
        are stored and hourly settings calculated for API/display consumption.

        Args:
            schedule: DPSchedule containing strategic_intent list.
            current_period: Current 15-minute period (0-95).
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
        strategic_intent: str = "",
        at_reserve_floor: bool = False,
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
                SOLAR_STORAGE (self-use, allow charging) at discharge_rate=0.
                IDLE is intercepted earlier via strategic_intent (#466) and
                does not reach this flag.
            strategic_intent: The period's strategic intent string. TOU mode
                ignores this (it derives mode from strategic_intents itself).
                VPP mode acts on it directly: distinguishes LOAD_SUPPORT
                (#413) and IDLE (#466) from other rate=0 intents --
                grid_charge/discharge_rate/block_passive_charging alone
                can't tell them apart, but VPP mode must, since each needs a
                different remote_control/power command.
            at_reserve_floor: Whether the battery is currently at (or below)
                its configured minimum SoE. TOU mode ignores this. VPP mode
                uses it to release the IDLE hold (#592) -- see
                _intent_to_vpp. Derived from a live SoC read, not from the
                plan: the hold exists to protect stored energy, so what
                matters is whether any is actually there now.

        Returns:
            Tuple of (success, error_message). error_message is empty on success.
        """
        if self.control_mode == "vpp":
            return self._apply_period_vpp(
                controller,
                grid_charge,
                discharge_rate,
                block_passive_charging,
                strategic_intent,
                at_reserve_floor,
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
        strategic_intent: str = "",
        at_reserve_floor: bool = False,
    ) -> tuple[int, bool]:
        """Map (grid_charge, discharge_rate, block_passive_charging,
        strategic_intent, at_reserve_floor) to
        (power_pct, remote_control_enabled).

        - grid_charge=True                       -> +100% (charge at max rate)
        - grid_charge=False, intent=LOAD_SUPPORT  -> 0%, remote control
          DISABLED, regardless of rate (#413 -- releases control to the
          inverter's own load-following self-use instead of forcing a fixed
          discharge rate, which causes unnecessary grid imports/exports
          whenever the schedule's load prediction misses). Checked before
          the rate=0/block_passive_charging branch below: LOAD_SUPPORT's
          INTENT_TO_CONTROL charge_rate is 0 (same as BATTERY_EXPORT/
          SOLAR_EXPORT), so block_passive_charging is True for it in
          production whenever discharge_rate is also 0 (a common case --
          the DP plan calling for no net discharge, or discharge-inhibit
          forcing the rate to 0) -- without this ordering that would wrongly
          fall into the grid_first-hold branch below instead of releasing.
        - grid_charge=False, rate=0, block=True   -> 0%, remote control ENABLED
          (SOLAR_EXPORT). Per the Growatt VPP protocol (V2.01, section 3.5),
          vpp_power<=0 with remote control enabled selects "grid first"
          priority, holding the battery instead of self-use absorbing solar
          surplus into it -- see #355 and
          docs/superpowers/specs/2026-07-20-vpp-passive-charge-block-design.md.
          Not yet real-hardware-validated; ships experimental pending
          confirmation.
        - grid_charge=False, rate=0, intent=IDLE   -> +1%, remote control
          ENABLED (#466 -- "battery first" per the protocol's >0 branch).
          IDLE's own DP cost model never credits battery discharge for load
          (_idle_battery_flows), so self-consumption must come from
          grid/solar, not the battery. grid_first (this function's block=True
          branch) does NOT achieve that -- per #118, self-consumption is
          still drawn from the battery under grid_first; only battery_first
          releases it to grid/solar. Checked before the generic rate=0
          branch below so IDLE doesn't fall into SOLAR_STORAGE's self-use
          disable. Not yet real-hardware-validated; ships experimental
          pending confirmation.
        - grid_charge=False, rate=0, intent=IDLE, at_reserve_floor=True
          -> 0%, remote control DISABLED (#592). The battery_first hold above
          protects stored energy from self-consumption; at the floor there is
          none left to protect, so it buys nothing and costs the inverter its
          sleep -- remote control being enabled makes _apply_period_vpp
          rewrite the command every period to refresh the fallback timer
          (#404), so the inverter is never handed back and the BMS never
          idles down.

          Releasing, rather than writing power=0 with remote control still
          enabled (which is grid_first), is what keeps this flow-neutral:
          load_first still absorbs passive solar surplus exactly as the
          battery_first hold does, where grid_first would bypass it to the
          grid -- a real change, since IDLE's DP cost model does credit that
          absorption. Flow-neutrality is proved in
          test_vpp_simulator_branches.py::TestIdleAtReserveFloor.

          **How far the battery can actually fall is the inverter's own
          discharge_stop_soc, not BESS's min_soc, and in VPP mode BESS does
          not write that register** -- initialize_hardware returns before
          sync_soc_limits for control_mode="vpp" (#309). So if the inverter's
          own floor sits below the configured min_soc, released self-use can
          draw the gap between them to cover house load. That is not new
          here: LOAD_SUPPORT (#413) and SOLAR_STORAGE already release control
          the same way at any SoC, so this extends an existing exposure to
          IDLE rather than creating one -- and it is bounded by the gap
          between the two floors, which is zero on a correctly configured
          inverter. `vpp_simulator` models the release as a hold at
          min_soe_kwh (available == 0), i.e. it assumes the two floors agree.
          Flagged for real-hardware confirmation with #592's reporter.
        - grid_charge=False, rate=0, block=False  -> 0%, remote control DISABLED
          (load_first self-use -- SOLAR_STORAGE, battery may absorb solar)
        - grid_charge=False, rate>0 (otherwise, i.e. BATTERY_EXPORT)
          -> -rate% (discharge/export)
        """
        if grid_charge:
            return 100, True
        if strategic_intent == "LOAD_SUPPORT":
            return 0, False
        if discharge_rate == 0:
            if strategic_intent == "IDLE":
                return (0, False) if at_reserve_floor else (1, True)
            return 0, block_passive_charging
        return -discharge_rate, True

    def _vpp_display_state(
        self,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
        strategic_intent: str = "",
    ) -> tuple[int, bool]:
        """Display-facing alias for _intent_to_vpp().

        The base class's _mode_display_fields() calls _vpp_display_state()
        uniformly across all vpp_power controllers (see
        core/bess/inverter_controller.py) rather than duck-typing a
        subclass-private method name. This is a pure interface unification
        wrapper -- _intent_to_vpp()'s own logic is unchanged.
        """
        return self._intent_to_vpp(
            grid_charge, discharge_rate, block_passive_charging, strategic_intent
        )

    def _ensure_vpp_status_enabled(self, controller) -> None:
        """Enable the two VPP flash registers, each only if not already confirmed.

        VPP Remote Control has no effect while VPP Status is disabled — this
        must be written (with a settle delay) before the first Remote Control
        write, per real-hardware testing on issue #118. AC charging is the
        second register of the pair: without it GRID_CHARGING periods draw
        nothing from the grid.

        Confirmed **per register**. They are written together but can drift
        apart (a user toggle, a firmware reset, a write that failed after the
        first of the two), and both are flash — so when only one has drifted,
        rewriting the healthy one is exactly the wear #399 asked to eliminate.
        """
        if self._vpp_status_confirmed and self._vpp_ac_charging_confirmed:
            return
        if not self._vpp_status_confirmed:
            controller.set_growatt_vpp_status(True)
            self._vpp_status_confirmed = True
        if not self._vpp_ac_charging_confirmed:
            controller.set_growatt_vpp_allow_ac_charging(True)
            self._vpp_ac_charging_confirmed = True
        time.sleep(1)

    def leave_control_mode(self, controller) -> None:
        """Disable VPP Status when switching away from VPP mode (#479).

        Without this, VPP Remote Control keeps overriding TOU segment
        writes at the hardware level even after BESS's own control_mode
        has switched to "tou" -- see module docstring and
        _ensure_vpp_status_enabled(). Reads live hardware state rather than
        self._vpp_status_confirmed, so this also recovers an install stuck
        from before this fix existed -- toggling control_mode to "vpp" and
        back to "tou" leaves this hardware register in the same disabled
        state a fresh install would end up in.
        """
        if self.control_mode != "vpp":
            return
        if controller.get_growatt_vpp_status() == "Enabled":
            controller.set_growatt_vpp_status(False)

    def _apply_period_vpp(
        self,
        controller,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
        strategic_intent: str = "",
        at_reserve_floor: bool = False,
    ) -> tuple[bool, str]:
        """Write one period's VPP power command.

        Writes every period while remote control is active, refreshing the
        fallback timer so the inverter's dead-man's-switch never lapses
        during a stable run of identical periods (#404). Only skipped when
        remote control is (and was already) disabled — nothing active, no
        timer to protect.
        """
        power_pct, remote_control_enabled = self._intent_to_vpp(
            grid_charge,
            discharge_rate,
            block_passive_charging,
            strategic_intent,
            at_reserve_floor,
        )

        needs_write = remote_control_enabled or (
            remote_control_enabled != self._last_written_vpp_remote_control
        )
        if not needs_write:
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

    def sync_to_hardware(
        self,
        controller,
        effective_period: int,
    ) -> tuple[int, int]:
        """Initialise hardware for the current control mode.

        TOU mode: sets segment 1 to the current period's mode with a full-day
        window. Legacy segments 2-9 are cleaned up at startup
        (read_and_initialize_from_hardware), not here.

        VPP mode: enables VPP Status/AC-charging once. No power command is
        issued here — VPP has no persistent/bulk schedule to push, and
        BatterySystemManager._apply_period_schedule always writes the
        current period's real power command immediately after this call
        returns (via apply_period). Issuing a power command here as well
        used to compute it from a hardcoded battery_action_kw=0.0 stub,
        sending a spurious power=0% write that briefly preceded the correct
        value written moments later (#421).

        Args:
            controller: HomeAssistantAPIController instance
            effective_period: Period (0-95) from which to start applying changes

        Returns:
            Tuple of (segments_updated, segments_disabled)
        """
        if self.control_mode == "vpp":
            self._ensure_vpp_status_enabled(controller)
            return (0, 0)

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
            allow_ac_charging = controller.get_growatt_vpp_allow_ac_charging()
            # Both registers, each seeding its own flag, because
            # _ensure_vpp_status_enabled writes them independently. Seeding a
            # single flag from VPP Status alone made Status a proxy for a
            # register that was never read: an inverter with Status Enabled
            # but AC charging Disabled was treated as fully configured on
            # every restart, so the AC-charging write never happened again and
            # GRID_CHARGING periods silently drew nothing from the grid.
            #
            # A read that returns None (transient API error, entity
            # momentarily unavailable, or the entity not configured at all) is
            # *unknown*, not "Disabled" — but unknown still cannot be assumed
            # good, since a wrongly-assumed Enabled leaves VPP unable to
            # execute its plan with no further chance to repair. It is
            # therefore repaired like a known-wrong register, and logged as
            # unknown so the flash write has a visible cause. Per-register
            # confirmation keeps that to the one register that could not be
            # read.
            for register, state in (
                ("status", status),
                ("allow_ac_charging", allow_ac_charging),
            ):
                if state is None:
                    logger.warning(
                        "Growatt VPP: could not read %s (unknown, not "
                        "necessarily disabled) — it will be rewritten on the "
                        "next VPP command",
                        register,
                    )
            self._vpp_status_confirmed = status == "Enabled"
            self._vpp_ac_charging_confirmed = allow_ac_charging == "Enabled"
            remote_control = controller.get_growatt_vpp_remote_control()
            self._last_written_vpp_remote_control = (
                remote_control == "Enabled" if remote_control is not None else None
            )
            logger.info(
                "Growatt VPP: initialised from hardware — status=%s "
                "allow_ac_charging=%s remote_control=%s",
                status,
                allow_ac_charging,
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

    @staticmethod
    def _diff_intents(
        current: list[str], new: list[str], from_period: int
    ) -> tuple[bool, str]:
        """Shared diff rule for strategic-intent lists.

        Two schedules differ when any period at or after ``from_period`` has a
        different strategic intent.
        """
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

    def reconcile_hardware(self, controller, effective_period: int) -> tuple[int, int]:
        """Nothing to re-assert — and specifically not the parent's version.

        The parent reconciles by re-running its own sync, which reads the
        inverter's segment table over the growatt_server cloud services. This
        platform is modbus: there is no Growatt device_id to address, so
        inheriting that raises SystemConfigurationError and takes the whole
        schedule update with it (issue #554).

        It is also unnecessary here. TOU mode drives a single segment whose
        mode is rewritten whenever it differs, and VPP mode issues per-period
        commands, so neither skips a write while the plan holds steady the way
        the parent does — there is no window in which drift could go unnoticed.
        """
        return 0, 0

    def evaluate_intents(
        self, schedule: DPSchedule, current_period: int = 0
    ) -> tuple[bool, str]:
        """Compare schedules by strategic intent list (like SolaxController).

        Two schedules differ when any period at or after ``current_period``
        has a different strategic intent.
        """
        new = schedule.original_dp_results["strategic_intent"]
        return self._diff_intents(self.strategic_intents, new, current_period)

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
                    "enabled": False,
                    "is_default": True,
                    **(
                        {"batt_mode": "load_first"}
                        if self.CONTROL_MODEL == "tou_register"
                        else {}
                    ),
                }
            ]

        # Build display from intent groups (same approach as SolaxController)
        now = time_utils.now()
        current_p = now.hour * 4 + now.minute // 15

        result = []
        for group in groups:
            block_passive_charging = (
                self.INTENT_TO_CONTROL.get(group["intent"], {}).get("charge_rate") == 0
            )
            mode_fields = self._mode_display_fields(
                group["intent"],
                group["grid_charge"],
                group["discharge_rate"],
                block_passive_charging,
            )
            is_current = group["start_period"] <= current_p <= group["end_period"]
            is_default_display = mode_fields.get("batt_mode") == "load_first"
            result.append(
                {
                    "segment_id": len(result) + 1,
                    "start_time": group["start_time"],
                    "end_time": group["end_time"],
                    **mode_fields,
                    "enabled": not is_default_display,
                    "is_default": is_default_display,
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
