"""Base class for inverter controllers.

Follows the PriceSource pattern (core/bess/price_manager.py). Subclasses
implement hardware-specific schedule conversion and deployment.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import ClassVar

from .dp_schedule import DPSchedule
from .execution_model import INTENT_TO_MODE, command_index
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class InverterController(ABC):
    """Abstract base class for inverter controllers.

    Provides shared state and methods common to all inverter types.
    Subclasses implement hardware-specific schedule conversion and deployment.

    Strategic Intent → Control Mapping:
    - GRID_CHARGING  → grid_charge=True,  charge_rate=<action-derived>, discharge_rate=0
    - SOLAR_STORAGE  → grid_charge=False, charge_rate=100, discharge_rate=0
    - LOAD_SUPPORT   → grid_charge=False, charge_rate=0,   discharge_rate=<action-derived>
    - BATTERY_EXPORT → grid_charge=False, charge_rate=0,   discharge_rate=<action-derived>
    - SOLAR_EXPORT   → grid_charge=False, charge_rate=0,   discharge_rate=0
    - IDLE           → grid_charge=False, charge_rate=100, discharge_rate=0

    SOLAR_EXPORT's charge_rate=0 (#313): blocks passive solar->battery
    charging so solar bypasses to grid even when the battery has room --
    unlike IDLE, which is meant to pass through to hardware's normal
    self-use charging. Before #313 these were identical (charge_rate=100),
    harmless while SOLAR_EXPORT only ever occurred with a full battery
    (nothing left to charge anyway either way), but wrong once the DP can
    choose SOLAR_EXPORT below max SOE.
    """

    # Map strategic intents to inverter control settings.
    # Shared across all inverter types: determines grid_charge, charge_rate, discharge_rate.
    INTENT_TO_CONTROL: ClassVar[dict[str, dict[str, bool | int]]] = {
        "GRID_CHARGING": {"grid_charge": True, "charge_rate": 100, "discharge_rate": 0},
        "SOLAR_STORAGE": {
            "grid_charge": False,
            "charge_rate": 100,
            "discharge_rate": 0,
        },
        "LOAD_SUPPORT": {"grid_charge": False, "charge_rate": 0, "discharge_rate": 100},
        "BATTERY_EXPORT": {
            "grid_charge": False,
            "charge_rate": 0,
            "discharge_rate": 100,
        },
        "SOLAR_EXPORT": {"grid_charge": False, "charge_rate": 0, "discharge_rate": 0},
        "IDLE": {"grid_charge": False, "charge_rate": 100, "discharge_rate": 0},
    }

    # Map strategic intents to battery modes (shared across Growatt MIN and SPH).
    # Defined in `execution_model` -- the same vocabulary the optimizer scores
    # commands against (Phase 4a, D1) -- and referenced here so the controllers
    # and the execution model cannot drift apart.
    # Typed `Mapping`, not `dict`: the object is a read-only view (see
    # execution_model), so a `dict` annotation would type-check an in-place
    # write that fails at runtime.
    INTENT_TO_MODE: ClassVar[Mapping[str, str]] = INTENT_TO_MODE

    # Human-readable descriptions of strategic intents.
    INTENT_DESCRIPTIONS: ClassVar[dict[str, str]] = {
        "GRID_CHARGING": "Storing cheap grid energy for later use",
        "SOLAR_STORAGE": "Storing excess solar energy for evening/night",
        "LOAD_SUPPORT": "Using battery to support home consumption",
        "BATTERY_EXPORT": "Selling stored energy to grid for profit",
        "SOLAR_EXPORT": "Solar surplus exporting directly to grid",
        "IDLE": "No significant battery activity",
    }

    # ── Platform capabilities ──────────────────────────────────────────────
    # Subclasses override to declare what the hardware supports.

    # Per-period charge/discharge rate register that power monitoring can
    # read and write.  False on platforms that bake power % into atomic
    # TOU schedule writes (SPH, SolaX native).
    supports_charge_rate_control: ClassVar[bool] = True

    # Whether the platform can curtail PV export via a hardware export-limit
    # register (issue #269), requiring a grid CT/smart meter. False by
    # default -- most platforms' HA integrations don't expose this control
    # at all (e.g. growatt_server exposes no export-limit service/entity).
    supports_export_limit_control: ClassVar[bool] = False

    # ── SM-Period-lists scheduling model ────────────────────────────────────
    # Subclasses that build separate charge/discharge period lists (Growatt
    # SPH, Solis via solis_modbus) must override these with the strategic
    # intents that produce a charge period and a discharge period
    # respectively. Left empty on the base class since not every controller
    # uses the period-list model (e.g. Growatt MIN uses numbered TOU slots).
    CHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset()
    DISCHARGE_INTENTS: ClassVar[frozenset[str]] = frozenset()

    # Maximum number of charge/discharge period-list slots. Subclasses using
    # the SM-Period-lists model (Growatt SPH: 3+3, Solis: 6+6) override these;
    # left at 0 on the base since not every controller uses period lists.
    MAX_CHARGE_PERIODS: ClassVar[int] = 0
    MAX_DISCHARGE_PERIODS: ClassVar[int] = 0

    # Whether discharge_rate acts as a ceiling under native load-following
    # firmware (only draws what's needed to cover an actual deficit) rather
    # than an immediate forced power command executed regardless of actual
    # load. True for TOU/load_first-based control (Growatt MIN cloud,
    # solax_modbus TOU mode). False for VPP-style direct power control
    # (SolaxController, solax_modbus VPP mode), where a discharge_rate>0
    # written by the intra-period discharge gate (#187/#318) would force a
    # full-power discharge instead of gently covering a dip (#324).
    discharge_rate_is_load_following: ClassVar[bool] = True

    # Whether a planned LOAD_SUPPORT discharge is delivered as
    # min(plan, actual load). Related to the flag above but NOT the same
    # question, and the answers differ on solax_modbus VPP mode: there the
    # rate register is a forced power (flag above False), yet LOAD_SUPPORT
    # writes no rate at all -- #413 disables remote control for that intent
    # and lets the inverter's own load-following self-use run the period, so
    # a cover plan is delivered exactly (this flag True). True by default
    # (TOU-register control, where the rate is a ceiling); False on native
    # SolaX, which never received #413, and on the period-list platforms,
    # which have no per-period control to deliver a partial cover with.
    # Read by the optimizer through
    # execution_model.PlatformCapabilities.load_support_delivers_exact_cover
    # to decide whether the off-lattice exact-cover candidate (#466) is
    # executable here (#580).
    load_support_delivers_exact_cover: ClassVar[bool] = True

    # Whether the default _write_period_to_hardware() should skip re-sending
    # a register (grid_charge/discharge_rate) that already matches the last
    # value it successfully wrote (#402: unguarded resends from the 15-min
    # period tick, its own retry, and the discharge-inhibit path could each
    # independently re-trigger the same Growatt cloud API write, which was
    # implicated in rate-limit write failures there). True by default for
    # the base register-write path. SolaxModbusGrowattController's TOU mode
    # overrides this to False -- it deliberately writes unconditionally
    # pending a real-hardware test of the #166 gate revert, and must not be
    # silently re-gated by this unrelated change.
    dedupe_register_writes: ClassVar[bool] = True

    # Real hardware control model this platform uses, driving what fields
    # get_period_settings()/get_detailed_period_groups()/get_all_tou_segments()
    # attach to each period (see _mode_display_fields()):
    # - "tou_register": genuine load_first/battery_first/grid_first hardware
    #   register exists (Growatt MIN, solax_modbus Growatt in TOU mode).
    # - "vpp_power": no mode register; behavior is (power_pct,
    #   remote_control) per period (solax_modbus Growatt VPP mode, native
    #   SolaX).
    # - "period_list": no per-period mode or power value; behavior is
    #   discrete charge/discharge time slots (Growatt SPH, Solis, Huawei).
    CONTROL_MODEL: ClassVar[str] = "tou_register"

    def discharge_resolution_kw(self, max_discharge_power_kw: float) -> float:
        """Smallest controllable discharge increment this platform can
        execute, in kW. Default: Growatt's integer-percent-of-max grid (1%
        steps) -- real hardware only accepts an integer percent rate
        (core/bess/simulation/inverter_simulator.py::_map_rates, postmortem
        #282). Override on a platform whose hardware resolution differs."""
        return max_discharge_power_kw / 100

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialize shared inverter controller state."""
        if battery_settings is None:
            raise ValueError("battery_settings is required and cannot be None")

        self.battery_settings = battery_settings
        self.max_charge_power_kw = battery_settings.max_charge_power_kw
        self.max_discharge_power_kw = battery_settings.max_discharge_power_kw

        self.current_schedule: DPSchedule | None = None
        self.strategic_intents: list[str] = []
        self.tou_intervals: list[dict] = []
        self.corruption_detected: bool = False

        # Last register values successfully written by _write_period_to_hardware,
        # so repeat calls with an unchanged value skip the hardware write instead
        # of re-sending it (grid_charge/discharge_rate #402). None means unknown
        # (always write). Left unset on a failed write so the next call retries.
        self._last_written_grid_charge: bool | None = None
        self._last_written_discharge_rate: int | None = None

    # ── Period utility ────────────────────────────────────────────────────────

    def _period_to_time(self, period: int) -> tuple[int, int]:
        """Convert period number (0-95) to (hour, minute).

        Note: During DST fall-back, periods >= 96 produce hour >= 24.
        Callers must handle this (e.g., cap to 23:59 for TOU schedules).
        """
        return period // 4, (period % 4) * 15

    # ── SM-Period-lists grouping (Growatt SPH, Solis) ─────────────────────────
    # Pure functions of self.strategic_intents / CHARGE_INTENTS / DISCHARGE_INTENTS
    # / _period_to_time — shared by any subclass using the charge/discharge
    # period-list scheduling model. Moved here from GrowattSphController so
    # SolisModbusController can reuse them without cross-class private calls.

    def _group_period_blocks(
        self, intents: list[str] | None = None
    ) -> tuple[list[dict], list[dict]]:
        """Group consecutive strategic intent periods into charge and discharge blocks.

        Args:
            intents: Strategic intents to group. Defaults to ``self.strategic_intents``;
                pass an explicit candidate list to group without mutating self.

        Returns:
            Tuple of (charge_blocks, discharge_blocks) where each block is a dict with
            keys 'start_period', 'end_period', and 'intents'.
        """
        intents = self.strategic_intents if intents is None else intents
        if not intents:
            return [], []

        charge_blocks: list[dict] = []
        discharge_blocks: list[dict] = []

        for _category, target_list, intent_set in [
            ("charge", charge_blocks, self.CHARGE_INTENTS),
            ("discharge", discharge_blocks, self.DISCHARGE_INTENTS),
        ]:
            current_block: dict | None = None

            for period, intent in enumerate(intents):
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
            "PERIOD LIMIT EXCEEDED: %d blocks, maximum is %d — dropping shortest",
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
            blocks: List of period blocks from _group_period_blocks

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

    def _build_period_list_schedule(
        self, intents: list[str] | None = None, *, commit: bool = True
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Group strategic intents into charge/discharge period lists and build
        the display TOU intervals — the shared "new schedule" build for any
        SM-Period-lists controller (Growatt SPH, Solis).

        Args:
            intents: Strategic intents to build from. Defaults to
                ``self.strategic_intents``; pass a candidate list to compute
                without depending on self's committed state.
            commit: When True (default), also assigns ``self.tou_intervals``.
                Callers building a read-only candidate (e.g. for diffing
                against self's current state) must pass ``commit=False``.

        Returns:
            Tuple of (charge_periods, discharge_periods, tou_intervals).
        """
        charge_blocks, discharge_blocks = self._group_period_blocks(intents)
        charge_blocks = self._enforce_period_limit(
            charge_blocks, self.MAX_CHARGE_PERIODS
        )
        discharge_blocks = self._enforce_period_limit(
            discharge_blocks, self.MAX_DISCHARGE_PERIODS
        )

        charge_periods = self._blocks_to_period_dicts(charge_blocks)
        discharge_periods = self._blocks_to_period_dicts(discharge_blocks)

        tou_intervals = self._periods_to_tou_intervals(
            charge_periods, discharge_periods, assign_segment_ids=True
        )
        if commit:
            self.tou_intervals = tou_intervals
        return charge_periods, discharge_periods, tou_intervals

    @staticmethod
    def _periods_to_tou_intervals(
        charge_periods: list[dict],
        discharge_periods: list[dict],
        charge_intent: str = "GRID_CHARGING",
        discharge_intent: str = "LOAD_SUPPORT/BATTERY_EXPORT",
        is_default: bool = False,
        assign_segment_ids: bool = False,
    ) -> list[dict]:
        """Build a unified, time-sorted tou_intervals list for display.

        Shared by any SM-Period-lists controller for both the "new schedule"
        build (assign_segment_ids=True, default intent labels) and the
        "read existing schedule from hardware" path (assign_segment_ids=False,
        charge_intent=discharge_intent="existing_schedule" — matching the
        prior per-controller behavior this was extracted from).
        """
        intervals = []
        for p in charge_periods:
            intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "enabled": p.get("enabled", True),
                    "is_default": is_default,
                    "strategic_intent": charge_intent,
                }
            )
        for p in discharge_periods:
            intervals.append(
                {
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "enabled": p.get("enabled", True),
                    "is_default": is_default,
                    "strategic_intent": discharge_intent,
                }
            )
        intervals.sort(key=lambda x: x["start_time"])
        if assign_segment_ids:
            for idx, interval in enumerate(intervals):
                interval["segment_id"] = idx + 1
        return intervals

    def _diff_period_lists(
        self,
        current_charge: list[dict],
        current_discharge: list[dict],
        new_charge: list[dict],
        new_discharge: list[dict],
        label: str,
    ) -> tuple[bool, str]:
        """Shared ``evaluate_intents`` diff body for SM-Period-lists controllers.

        Args:
            current_charge/current_discharge: Self's currently-applied periods.
            new_charge/new_discharge: A candidate's periods (e.g. from
                ``_build_period_list_schedule(intents, commit=False)``).
            label: Platform label used in log/reason strings (e.g. "SPH", "Solis").
        """

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
                "DECISION: %s charge periods differ — current=%s new=%s",
                label,
                current_charge,
                new_charge,
            )
            return True, f"{label} charge periods differ"

        if not _periods_equal(current_discharge, new_discharge):
            logger.info(
                "DECISION: %s discharge periods differ — current=%s new=%s",
                label,
                current_discharge,
                new_discharge,
            )
            return True, f"{label} discharge periods differ"

        logger.info("DECISION: %s schedules match", label)
        return False, ""

    # ── Intent → hardware rates ───────────────────────────────────────────────

    def compute_rates_for_period(
        self, period: int, battery_action_kw: float
    ) -> tuple[bool, int, bool]:
        """Map strategic intent for a period to hardware control rates.

        Args:
            period: 15-minute period index (0-95)
            battery_action_kw: Battery power in kW (positive=charge, negative=discharge)

        Returns:
            Tuple of (grid_charge, discharge_rate_percent, block_passive_charging).
            block_passive_charging is True when this intent's
            INTENT_TO_CONTROL charge_rate is 0 -- i.e. passive solar->battery
            charging should be blocked (SOLAR_EXPORT), not just left at a
            forced discharge rate of 0 (LOAD_SUPPORT/BATTERY_EXPORT with no
            action this period). Register-based platforms already realize
            this via the separate charge_rate register (adjust_charging_power());
            forced-power/VPP-style platforms have no such register and must
            act on this flag directly at apply_period (see #355).
        """
        intent = self.strategic_intents[period]
        grid_charge, discharge_rate = self._map_intent_to_rates(
            intent, battery_action_kw
        )
        block_passive_charging = self.INTENT_TO_CONTROL[intent]["charge_rate"] == 0
        return grid_charge, discharge_rate, block_passive_charging

    # `_scale_to_percent` lived here and did this conversion by nearest
    # rounding for both rate paths. Both now go through
    # `execution_model.command_index`, which rounds by what the written
    # number means -- discharge in 4b, charge in 4c -- so it has no callers
    # left and is gone rather than kept as a second way to do the same thing.

    def _compute_charge_rate(
        self, intent: str, control: dict[str, bool | int], battery_action_kw: float
    ) -> int:
        """Compute charge_rate for a period, action-derived for GRID_CHARGING.

        Args:
            intent: Strategic intent string
            control: The INTENT_TO_CONTROL entry for this intent
            battery_action_kw: Battery power in kW (positive=charge)

        Returns:
            Charge rate percent (0-100)
        """
        if intent == "GRID_CHARGING" and battery_action_kw > 0.01:
            # Rounded UP, like a discharge ceiling and for the same reason
            # (Phase 4c): the battery's own remaining room binds above the
            # command -- the inverter stops when full -- so a rate above the
            # plan delivers the plan exactly, while nearest-rounding lands
            # below it and silently charges less. Measured pre-fix: 4 of 493
            # charging periods short, worst -0.0288 kWh.
            #
            # Safe because the DP floors a plan the *import cap* limited
            # (`lattice_grid_charge`), which is the one case where nothing
            # physical binds above the command and rounding up would draw
            # more from the grid than the house fuse allows. With that plan
            # already on the lattice, rounding up is a no-op there.
            return command_index(
                battery_action_kw,
                self.max_charge_power_kw / 100,
                rate_is_ceiling=True,
            )
        return control["charge_rate"]

    def _map_intent_to_rates(
        self, intent: str, battery_action_kw: float
    ) -> tuple[bool, int]:
        """Map a strategic intent to (grid_charge, discharge_rate).

        Args:
            intent: Strategic intent string
            battery_action_kw: Battery power in kW (used for BATTERY_EXPORT and LOAD_SUPPORT scaling)

        Returns:
            Tuple of (grid_charge, discharge_rate_percent)
        """
        if intent == "GRID_CHARGING":
            return True, 0
        elif intent == "SOLAR_STORAGE":
            return False, 0
        elif intent in ("LOAD_SUPPORT", "BATTERY_EXPORT"):
            if battery_action_kw < -0.01:
                discharge_rate = command_index(
                    abs(battery_action_kw),
                    # The platform's own lattice, not a hardcoded 1%: the
                    # planner enumerates candidates on
                    # `discharge_resolution_kw` (via
                    # `PlatformCapabilities.discharge_rate_step_kw`), so a
                    # platform that overrides it and a write path that did
                    # not would plan on one grid and command on another --
                    # R != P by construction. No shipped controller
                    # overrides it today, which is exactly why this was
                    # invisible.
                    self.discharge_resolution_kw(self.max_discharge_power_kw),
                    # LOAD_SUPPORT writes load_first, where the number is a
                    # ceiling on hardware that load-follows -- so it must be
                    # rounded UP or it under-delivers the plan (Phase 4b;
                    # see command_index). BATTERY_EXPORT writes
                    # grid_first, where the number is the delivered power on
                    # every platform, so nearest stays correct.
                    rate_is_ceiling=(
                        intent == "LOAD_SUPPORT"
                        and self.discharge_rate_is_load_following
                    ),
                )
            else:
                discharge_rate = 0
            return False, discharge_rate
        elif intent == "SOLAR_EXPORT":
            return False, 0
        elif intent == "IDLE":
            return False, 0
        else:
            raise ValueError(f"Unknown strategic intent: {intent}")

    def apply_period(
        self,
        controller,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
        strategic_intent: str = "",
        at_reserve_floor: bool = False,
    ) -> tuple[bool, str]:
        """Write period control settings to hardware.

        The caller (BatterySystemManager) is responsible for applying the
        discharge inhibit check before calling this method.

        Args:
            controller: HomeAssistantAPIController instance
            grid_charge: Whether to enable grid charging
            discharge_rate: Discharge power rate (0-100%), post-inhibit
            block_passive_charging: Whether passive solar->battery charging
                should be blocked this period (SOLAR_EXPORT). Register-based
                platforms realize this via the separate charge_rate register
                (adjust_charging_power()) and ignore this flag. Forced-power
                platforms with no such register (VPP-style) act on it
                directly -- see #355.
            strategic_intent: The period's strategic intent string.
                grid_charge/discharge_rate collapse LOAD_SUPPORT and
                BATTERY_EXPORT to the same values, so platforms that need to
                treat them differently (VPP-style -- see #413) require the
                intent itself. Register-based platforms ignore this.
            at_reserve_floor: Whether the battery is at (or below) its
                configured minimum SoE right now. Register-based platforms
                ignore this -- their min_soc register already stops discharge
                at the floor. Forced-power platforms use it to stop holding a
                battery that has nothing left to hold, releasing the inverter
                so its BMS can sleep -- see #592.

        Returns:
            Tuple of (success, error_message). error_message is empty on success.
        """
        return self._write_period_to_hardware(
            controller, grid_charge, discharge_rate, block_passive_charging
        )

    def apply_export_limit(self, controller, curtail: bool) -> None:  # noqa: B027
        """Enable/disable PV export curtailment for this period (issue #269).

        No-op by default -- only platforms with supports_export_limit_control
        True override this. Callers should check the capability flag before
        relying on this doing anything; the no-op exists so BSM can call it
        unconditionally without a per-platform branch.

        Args:
            controller: HomeAssistantAPIController instance
            curtail: True to curtail export (write 0%/Meter mode), False to
                release it back to normal (Disabled).
        """

    def get_period_settings(self, period: int) -> dict:
        """Get control settings for a specific 15-minute period.

        Args:
            period: Period index (0-95 normally, varies during DST)

        Returns:
            Dict with grid_charge, charge_rate, discharge_rate,
            strategic_intent, batt_mode
        """
        if not self.strategic_intents:
            raise ValueError("No strategic intents available")
        if period < 0 or period >= len(self.strategic_intents):
            raise ValueError(
                f"Period {period} out of range [0, {len(self.strategic_intents)})"
            )

        intent = self.strategic_intents[period]

        if (
            self.current_schedule is not None
            and self.current_schedule.actions
            and period < len(self.current_schedule.actions)
        ):
            battery_action_kwh = self.current_schedule.actions[period]
            num_periods = len(self.current_schedule.actions)
            period_duration_hours = 24.0 / num_periods
            battery_action_kw = battery_action_kwh / period_duration_hours
            grid_charge, discharge_rate, block_passive_charging = (
                self.compute_rates_for_period(period, battery_action_kw)
            )
            charge_rate = self._compute_charge_rate(
                intent, self.INTENT_TO_CONTROL[intent], battery_action_kw
            )
        else:
            control = self.INTENT_TO_CONTROL[intent]
            grid_charge = control["grid_charge"]
            charge_rate = control["charge_rate"]
            discharge_rate = control["discharge_rate"]
            block_passive_charging = control["charge_rate"] == 0

        return {
            "grid_charge": grid_charge,
            "charge_rate": charge_rate,
            "discharge_rate": discharge_rate,
            "strategic_intent": intent,
            **self._mode_display_fields(
                intent,
                grid_charge,
                discharge_rate,
                block_passive_charging,
                self._planned_at_reserve_floor(period),
            ),
        }

    def _planned_at_reserve_floor(self, period: int) -> bool:
        """Whether the *plan* has the battery on its reserve floor entering
        this period (#592).

        The display counterpart to `BatterySystemManager._at_reserve_floor()`,
        which reads live SoC. A displayed period is a prediction, so the plan's
        own SoE trajectory is the correct input -- but it must answer the same
        question, or the UI shows a hold for periods production releases and
        `_mode_display_fields` breaks its own no-fabrication contract.

        **Index p-1, not p.** `state_of_energy` is `combined_soe`, whose only
        writer stores `period_data.energy.battery_soe_end` (see
        `BatterySystemManager._create_updated_schedule`) -- `battery_soe_end`
        and `battery_soe_start` are distinct fields on `EnergyData`. So
        `state_of_energy[p]` is the SoE *leaving* period p, and the SoE
        *entering* it is index p-1. Reading index p directly would answer for
        the wrong period: at the boundary where the plan first reaches the
        floor it would report "at floor" one period early, and one period late
        on the way back up -- exactly the display/write disagreement this
        method exists to prevent.

        Period 0 has no predecessor in the array, so it reads index 0. That is
        exact only when period 0 *is* the optimization period, where
        `combined_soe[0]` is written as `current_soe` — an entering value. On a
        schedule re-optimized mid-day, index 0 is a historical period holding
        `battery_soe_end` like every other index, so the read is one period
        early there. Display-only and bounded to period 0: `get_period_settings`
        never writes hardware, and the live write path reads SoC directly. Left
        as-is rather than papered over, because the array has no entering value
        for period 0 to read — recording one is a change to
        `_create_updated_schedule`, not to this method.

        False when there is no plan to read: with no trajectory there is no
        prediction to display, and the hold is the unchanged-behaviour answer.
        """
        if self.current_schedule is None:
            return False
        soe = self.current_schedule.state_of_energy
        if period >= len(soe):
            return False
        entering_soe = soe[period - 1] if period > 0 else soe[0]
        return entering_soe <= self.battery_settings.min_soe_kwh

    def _mode_display_fields(
        self,
        intent: str,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool,
        at_reserve_floor: bool = False,
    ) -> dict:
        """Single source of truth for what mode-related fields a period
        gets, branching on CONTROL_MODEL. Never fabricates a label the
        hardware doesn't back — see design spec
        docs/superpowers/specs/2026-07-29-control-model-display-design.md.

        vpp_power controllers each keep their own power-computation method
        (SolaxModbusGrowattController._intent_to_vpp,
        SolaxController._vpp_display_state) rather than sharing one --
        their real hardware behavior has diverged (design spec section 1
        correction).

        Returns:
            {"batt_mode": str} for tou_register.
            {"vpp_power_pct": int, "vpp_remote_control": bool} for vpp_power.
            {} for period_list.
        """
        if self.CONTROL_MODEL == "tou_register":
            return {"batt_mode": self.INTENT_TO_MODE[intent]}

        if self.CONTROL_MODEL == "vpp_power":
            # Every vpp_power controller must implement _vpp_display_state()
            # with this unified signature (SolaxController,
            # SolaxModbusGrowattController) -- no hasattr() duck-typing on a
            # subclass-private method name.
            power_pct, remote_control = self._vpp_display_state(
                grid_charge,
                discharge_rate,
                block_passive_charging,
                intent,
                at_reserve_floor,
            )
            return {
                "vpp_power_pct": power_pct,
                "vpp_remote_control": remote_control,
            }

        if self.CONTROL_MODEL == "period_list":
            return {}

        raise ValueError(f"Unknown CONTROL_MODEL: {self.CONTROL_MODEL!r}")

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

        return {
            intent: {
                "hours": hours,
                "count": len(hours),
                "description": self.INTENT_DESCRIPTIONS.get(intent, "Unknown intent"),
            }
            for intent, hours in intent_hours.items()
        }

    def _get_intent_description(self, intent: str) -> str:
        """Get human-readable description of strategic intent."""
        return self.INTENT_DESCRIPTIONS.get(intent, "Unknown intent")

    def get_detailed_period_groups(
        self,
        intents: list[str] | None = None,
        actions: list[float] | None = None,
        soc_values: list[float | None] | None = None,
        curtailed: list[bool] | None = None,
    ) -> list[dict]:
        """Get period groups with full control parameters for display/API.

        Groups consecutive 15-minute periods ONLY when ALL parameters are identical:
        strategic intent, battery mode, grid charge, charge rate, discharge
        rate, and planned curtailment (#501).

        Args:
            intents: Optional list of strategic intents to group. If None,
                     uses self.strategic_intents (today's schedule).
            actions: Optional list of battery actions in kWh per period (negative=discharge).
                     If None, reads from self.current_schedule.actions. If current_schedule
                     is also None or the period is out of range, action defaults to 0.0.
            soc_values: Optional per-period SOC end values (%). The last period's value
                        in each group is exposed as soc_end_pct in the result.
            curtailed: Optional per-period planned-curtailment flags (#501),
                       from PeriodData.decision.curtailed. Defaults to all
                       False when omitted -- callers without curtailment
                       data get the pre-#501 grouping behavior unchanged.

        Returns:
            List of period groups with all control parameters and time strings
        """
        effective_intents = intents if intents is not None else self.strategic_intents
        if not effective_intents:
            return []

        num_periods = len(effective_intents)

        schedule_actions: list[float] | None = None
        if actions is not None:
            schedule_actions = actions
        elif self.current_schedule is not None:
            schedule_actions = self.current_schedule.actions

        period_settings = []
        for period in range(num_periods):
            intent = effective_intents[period]
            control = self.INTENT_TO_CONTROL.get(
                intent,
                {"grid_charge": False, "charge_rate": 100, "discharge_rate": 0},
            )
            period_curtailed = (
                curtailed[period]
                if curtailed is not None and period < len(curtailed)
                else False
            )

            action_kwh = 0.0
            if schedule_actions is not None and period < len(schedule_actions):
                action_kwh = schedule_actions[period]
            action_kw = action_kwh / 0.25

            _, discharge_rate = self._map_intent_to_rates(intent, action_kw)
            charge_rate = self._compute_charge_rate(intent, control, action_kw)
            block_passive_charging = control["charge_rate"] == 0
            mode_fields = self._mode_display_fields(
                intent, control["grid_charge"], discharge_rate, block_passive_charging
            )

            period_settings.append(
                {
                    "period": period,
                    "intent": intent,
                    **mode_fields,
                    "grid_charge": control["grid_charge"],
                    "charge_rate": charge_rate,
                    "discharge_rate": discharge_rate,
                    "action_kwh": action_kwh,
                    "curtailed": period_curtailed,
                }
            )

        groups = []
        current_group: dict | None = None

        mode_field_keys = ("batt_mode", "vpp_power_pct", "vpp_remote_control")

        for ps in period_settings:
            if current_group is not None and (
                ps["intent"] == current_group["intent"]
                and all(ps.get(k) == current_group.get(k) for k in mode_field_keys)
                and ps["grid_charge"] == current_group["grid_charge"]
                and ps["charge_rate"] == current_group["charge_rate"]
                and ps["discharge_rate"] == current_group["discharge_rate"]
                and ps["curtailed"] == current_group["curtailed"]
            ):
                current_group["end_period"] = ps["period"]
                current_group["count"] += 1
                current_group["total_action_kwh"] += ps["action_kwh"]
            else:
                if current_group is not None:
                    groups.append(current_group)
                current_group = {
                    "start_period": ps["period"],
                    "end_period": ps["period"],
                    "intent": ps["intent"],
                    **{k: ps[k] for k in mode_field_keys if k in ps},
                    "grid_charge": ps["grid_charge"],
                    "charge_rate": ps["charge_rate"],
                    "discharge_rate": ps["discharge_rate"],
                    "curtailed": ps["curtailed"],
                    "count": 1,
                    "total_action_kwh": ps["action_kwh"],
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
            end_period = group["end_period"]
            soc_end: float | None = None
            if soc_values is not None and end_period < len(soc_values):
                soc_end = soc_values[end_period]
            result.append(
                {
                    "start_time": f"{start_h:02d}:{start_m:02d}",
                    "end_time": f"{end_h:02d}:{end_m:02d}",
                    "start_period": group["start_period"],
                    "end_period": group["end_period"],
                    "intent": group["intent"],
                    **{k: group[k] for k in mode_field_keys if k in group},
                    "grid_charge": group["grid_charge"],
                    "charge_rate": group["charge_rate"],
                    "discharge_rate": group["discharge_rate"],
                    "period_count": group["count"],
                    "duration_minutes": group["count"] * 15,
                    "total_action_kwh": group["total_action_kwh"],
                    "soc_end_pct": soc_end,
                    "curtailed": group["curtailed"],
                }
            )
        return result

    # ── Abstract interface ────────────────────────────────────────────────────

    @property
    @abstractmethod
    def active_tou_intervals(self) -> list[dict]:
        """Return the subset of TOU intervals currently written to hardware."""

    @abstractmethod
    def apply_intents(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
    ) -> None:
        """Adopt this cycle's DP intent list as current control state.

        For TOU-style platforms this rebuilds persisted hardware TOU
        intervals; for VPP/SolaX-style ephemeral platforms this is a
        near-passthrough of the intent list (control is applied per-period
        elsewhere, not as a batch schedule).
        """

    @abstractmethod
    def sync_to_hardware(
        self,
        controller,
        effective_period: int,
    ) -> tuple[int, int]:
        """Write schedule to inverter hardware.

        Implementations that need to know what the inverter currently holds
        must read it from the inverter themselves — there is no caller-supplied
        snapshot, because one that drifted out of sync caused issue #551.

        Returns:
            Tuple of (writes, disables)
        """

    @abstractmethod
    def evaluate_intents(
        self, schedule: DPSchedule, current_period: int = 0
    ) -> tuple[bool, str]:
        """Would applying ``schedule`` differ from what's currently in
        effect, from ``current_period`` onwards? Returns (differs, reason).

        Read-only: must not mutate self's committed state (tou_intervals,
        strategic_intents, etc.) — only self.corruption_detected may be set
        as an accepted diagnostic side effect on platforms that support it.
        """

    def reconcile_hardware(self, controller, effective_period: int) -> tuple[int, int]:
        """Re-assert the committed plan on a cycle that changed nothing.

        Default: do nothing. A platform that rewrites its whole control state
        whenever it runs cannot drift undetected — the next cycle overwrites
        whatever it finds. Only a platform that *skips* the write while its
        plan holds steady has a window in which the inverter can lose a
        segment, or restore one, without anybody looking.

        Returns (writes, disables).
        """
        return 0, 0

    @abstractmethod
    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Read current schedule from inverter and initialize this controller."""

    @abstractmethod
    def sync_soc_limits(self, controller) -> None:
        """Sync SOC limits from config to inverter hardware."""

    def initialize_hardware(self, controller) -> None:  # noqa: B027
        """Write initial hardware configuration required before normal operation.

        Called once at startup (after demo mode blocks are cleared). Subclasses
        override to perform whatever one-time writes their hardware requires.
        The default is a no-op so controllers with no startup writes need not
        override it.
        """

    def leave_control_mode(self, controller) -> None:  # noqa: B027
        """Clean up hardware state before this controller instance is replaced
        by a control_mode switch (e.g. vpp -> tou).

        Called on the outgoing controller by BatterySystemManager.switch_control_mode()
        before the new mode's controller is created. The default is a no-op;
        override for hardware whose mode leaves a persistent override active
        that the next mode won't otherwise clear (see #479).
        """

    def _write_period_to_hardware(
        self,
        controller,
        grid_charge: bool,
        discharge_rate: int,
        block_passive_charging: bool = False,
    ) -> tuple[bool, str]:
        """Write per-period control settings to hardware.

        Default implementation uses Growatt register interface (grid_charge +
        discharge_rate). SolaX overrides with VPP commands.

        block_passive_charging is unused here: register-based platforms
        (Growatt TOU/cloud, this default) realize "block passive solar
        charging" via the separate charge_rate register, written by
        BatterySystemManager.adjust_charging_power() -- not via this method.

        Args:
            controller: HomeAssistantAPIController instance
            grid_charge: Whether to enable grid charging
            discharge_rate: Discharge power rate (0-100%)
            block_passive_charging: Unused by this default implementation --
                see docstring above.

        Returns:
            Tuple of (success, error_message). error_message is empty on success.
        """
        errors = []

        if (
            not self.dedupe_register_writes
            or grid_charge != self._last_written_grid_charge
        ):
            try:
                controller.set_grid_charge(grid_charge)
                self._last_written_grid_charge = grid_charge
            except Exception as e:
                logger.error("FAILED: set_grid_charge(%s): %s", grid_charge, e)
                errors.append(str(e))

        if (
            not self.dedupe_register_writes
            or discharge_rate != self._last_written_discharge_rate
        ):
            try:
                controller.set_discharging_power_rate(discharge_rate)
                self._last_written_discharge_rate = discharge_rate
            except Exception as e:
                logger.error(
                    "FAILED: set_discharging_power_rate(%s): %s", discharge_rate, e
                )
                errors.append(str(e))

        if errors:
            return False, "; ".join(errors)
        return True, ""

    @abstractmethod
    def get_all_tou_segments(self) -> list[dict]:
        """Return all TOU segments for API/display consumption."""

    @abstractmethod
    def get_daily_TOU_settings(self) -> list[dict]:
        """Return TOU settings for display/API consumption."""

    @abstractmethod
    def log_current_TOU_schedule(self, header: str = "") -> None:
        """Log current TOU schedule."""

    @abstractmethod
    def log_detailed_schedule(self, header: str = "") -> None:
        """Log detailed schedule with per-period information."""

    @abstractmethod
    def check_health(self, controller) -> list:
        """Check inverter control capabilities.

        Returns:
            List of health check result dicts
        """
