"""SolaX inverter controller.

SolaX inverters are controlled via the homeassistant-solax-modbus integration
using VPP (Virtual Power Plant) commands.  Unlike Growatt, SolaX has no
persistent TOU schedule stored in the inverter.  Instead, commands are issued
per 15-minute period and kept active via the integration's autorepeat mechanism.

Control model:
- BESS calls ``_write_period_to_hardware()`` at each period boundary.
- ``set_solax_active_power_control(watts)`` sends the four-step VPP sequence:
  1. Enable battery control mode.
  2. Set active power target (positive = charge, negative = discharge).
  3. Set autorepeat duration to 1 200 s (covers 15-min period plus margin).
  4. Press trigger.
- For IDLE / SOLAR_STORAGE the inverter is placed back into self-use mode via
  ``set_solax_vpp_disabled()``; autorepeat on the previous command expires
  naturally, providing a safe fallback.

Intent-to-power mapping:
- GRID_CHARGING    → +max_charge_W    (charge from grid at max rate)
- SOLAR_STORAGE    → disable VPP      (let solar charge naturally)
- LOAD_SUPPORT     -> -(rate% x max_discharge_W)  (discharge to cover load)
- EXPORT_ARBITRAGE -> -max_discharge_W (full discharge for export)
- IDLE             → disable VPP      (no battery action)
"""

import logging
from datetime import datetime

from . import time_utils
from .dp_schedule import DPSchedule
from .inverter_controller import InverterController
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class SolaxController(InverterController):
    """SolaX inverter controller using VPP active-power commands.

    SolaX does not use a persistent TOU schedule.  ``write_schedule_to_hardware``
    is a no-op; the actual hardware writes happen period-by-period via
    ``_write_period_to_hardware``, called from
    ``BatterySystemManager._apply_period_schedule``.

    ``active_tou_intervals`` is always empty — there are no segments to
    push to the inverter.
    """

    def __init__(self, battery_settings: BatterySettings) -> None:
        """Initialise the SolaX controller."""
        super().__init__(battery_settings)

    # ── Abstract property ─────────────────────────────────────────────────────

    @property
    def active_tou_intervals(self) -> list[dict]:
        """SolaX has no stored TOU intervals — always empty."""
        return []

    # ── Schedule creation ─────────────────────────────────────────────────────

    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Store strategic intents from a DPSchedule.

        SolaX requires no TOU conversion.  Intents are applied period-by-period
        via ``_write_period_to_hardware`` and are not pushed as a batch to the
        inverter hardware.

        Args:
            schedule: DPSchedule containing strategic_intent list.
            current_period: Unused for SolaX.
            previous_tou_intervals: Unused for SolaX.
        """
        logger.info("Creating SolaX schedule from strategic intents")

        self.strategic_intents = schedule.original_dp_results["strategic_intent"]
        self.current_schedule = schedule

        logger.info(
            "SolaX: %d strategic intents loaded (quarterly resolution)",
            len(self.strategic_intents),
        )

        self._calculate_hourly_settings()

    # ── Hardware interface ────────────────────────────────────────────────────

    def _write_period_to_hardware(
        self, controller, grid_charge: bool, discharge_rate: int
    ) -> None:
        """Issue a SolaX VPP command for the current period.

        Derives the power target in watts from the two abstract control
        parameters supplied by the base-class ``apply_period`` path:

        - ``grid_charge=True``  → charge at maximum charge power.
        - ``grid_charge=False, discharge_rate=0`` → disable VPP (IDLE / SOLAR_STORAGE).
        - ``grid_charge=False, discharge_rate>0`` → discharge at the given rate.

        Args:
            controller: HomeAssistantAPIController instance.
            grid_charge: Whether grid charging is requested.
            discharge_rate: Discharge power as a percentage (0-100).
        """
        if not grid_charge and discharge_rate == 0:
            controller.set_solax_vpp_disabled()
        elif grid_charge:
            target_watts = int(self.max_charge_power_kw * 1000)
            controller.set_solax_active_power_control(target_watts)
        else:
            target_watts = -int(
                self.max_discharge_power_kw * discharge_rate / 100 * 1000
            )
            controller.set_solax_active_power_control(target_watts)

    def write_schedule_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        """No-op for SolaX — schedule is applied period-by-period via VPP.

        SolaX has no persistent TOU schedule to push in bulk.  Inverter state
        is fully controlled by per-period ``_write_period_to_hardware`` calls.

        Returns:
            (0, 0) — no writes or disables performed.
        """
        logger.debug("SolaX: write_schedule_to_hardware is a no-op (per-period VPP)")
        return 0, 0

    def sync_soc_limits(self, controller) -> None:
        """Sync battery minimum SOC from config to the SolaX inverter.

        Reads the current minimum SOC from the inverter and writes the
        configured value only when a mismatch is detected.

        Args:
            controller: HomeAssistantAPIController instance.
        """
        configured_min_soc = int(self.battery_settings.min_soc)

        current_mode = controller.get_solax_power_control_mode()
        logger.debug("SolaX: current power control mode = %r", current_mode)

        controller.set_solax_min_soc(configured_min_soc)
        logger.info("SolaX: battery minimum SOC set to %d%%", configured_min_soc)

    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Read current inverter state and initialise this controller.

        SolaX has no stored schedule to read back.  We log the current power
        control mode for diagnostics and leave ``strategic_intents`` empty
        (they will be populated when the next schedule is created).

        Args:
            controller: HomeAssistantAPIController instance.
            current_hour: Current hour (0-23), unused for SolaX.
        """
        current_mode = controller.get_solax_power_control_mode()
        logger.info(
            "SolaX: initialised from hardware — current power control mode = %r",
            current_mode,
        )

    # ── Schedule comparison ───────────────────────────────────────────────────

    def compare_schedules(
        self, other_schedule: "SolaxController", from_period: int = 0
    ) -> tuple[bool, str]:
        """Compare SolaX schedules by strategic-intent list.

        Two schedules differ when any period at or after ``from_period`` has a
        different strategic intent.

        Args:
            other_schedule: Another SolaxController to compare against.
            from_period: First period to compare (earlier periods are ignored).

        Returns:
            Tuple of (schedules_differ, reason).
        """
        current = self.strategic_intents
        new = other_schedule.strategic_intents

        if not current and not new:
            return False, ""

        if len(current) != len(new):
            return True, (f"SolaX intent count differs: {len(current)} vs {len(new)}")

        for period in range(from_period, len(current)):
            if current[period] != new[period]:
                logger.info(
                    "DECISION: SolaX intent differs at period %d — "
                    "current=%s new=%s",
                    period,
                    current[period],
                    new[period],
                )
                return True, (f"SolaX strategic intents differ from period {period}")

        logger.info("DECISION: SolaX schedules match")
        return False, ""

    # ── TOU display ───────────────────────────────────────────────────────────

    def get_daily_TOU_settings(self) -> list[dict]:
        """Return an empty list — SolaX has no TOU segments."""
        return []

    def log_current_TOU_schedule(self, header: str = "") -> None:
        """Log current SolaX VPP intent summary."""
        if header:
            logger.info(header)

        if not self.strategic_intents:
            logger.info("SolaX: no schedule loaded")
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        if current_period < len(self.strategic_intents):
            intent = self.strategic_intents[current_period]
            logger.info(
                "SolaX: current period %d (%02d:%02d) → %s",
                current_period,
                now.hour,
                (now.minute // 15) * 15,
                intent,
            )
        else:
            logger.info("SolaX: %d intents loaded", len(self.strategic_intents))

    def log_detailed_schedule(self, header: str = "") -> None:
        """Log detailed schedule with per-period strategic intents."""
        if header:
            logger.info(header)

        if not self.strategic_intents:
            logger.info("SolaX: no schedule data available")
            return

        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15

        lines = [
            "\n╔═══════════════╦══════════════════╦════════════╗",
            "║  Time Period  ║ Strategic Intent ║ VPP Action ║",
            "╠═══════════════╬══════════════════╬════════════╣",
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

            if intent == "GRID_CHARGING":
                action = "+charge"
            elif intent in ("SOLAR_STORAGE", "IDLE"):
                action = "self-use"
            else:
                action = "-discharge"

            lines.append(f"║{marker}{time_range:13} ║ {intent:16} ║ {action:10} ║")
            period += 1

        lines.append("╚═══════════════╩══════════════════╩════════════╝")
        lines.append("* indicates current period")

        logger.info("\n".join(lines))

    # ── API / display methods ─────────────────────────────────────────────────

    def get_all_tou_segments(self) -> list[dict]:
        """Return strategic intent groups as display segments.

        SolaX has no hardware TOU intervals, so we represent the schedule as
        consecutive intent groups for the dashboard's schedule view.
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

        result = []
        for i, group in enumerate(groups, 1):
            result.append(
                {
                    "segment_id": i,
                    "start_time": group["start_time"],
                    "end_time": group["end_time"],
                    "batt_mode": group["mode"],
                    "enabled": True,
                    "strategic_intent": group["intent"],
                }
            )
        return result

    # ── Health check ──────────────────────────────────────────────────────────

    def check_health(self, controller) -> list:
        """Check SolaX VPP control entity availability.

        Verifies that the power control mode entity is readable, which
        confirms connectivity to the solax-modbus integration.
        """
        try:
            mode = controller.get_solax_power_control_mode()
            if mode is not None:
                check = {
                    "name": "Power Control Mode",
                    "key": "solax_power_control_mode",
                    "entity_id": controller.sensors.get(
                        "solax_power_control_mode", "Not configured"
                    ),
                    "status": "OK",
                    "rawValue": mode,
                    "displayValue": str(mode),
                    "error": None,
                }
                overall_status = "OK"
            else:
                check = {
                    "name": "Power Control Mode",
                    "key": "solax_power_control_mode",
                    "entity_id": controller.sensors.get(
                        "solax_power_control_mode", "Not configured"
                    ),
                    "status": "ERROR",
                    "rawValue": None,
                    "displayValue": "N/A",
                    "error": (
                        "Entity returned None — check solax_power_control_mode "
                        "sensor key in config"
                    ),
                }
                overall_status = "ERROR"
        except ValueError as e:
            check = {
                "name": "Power Control Mode",
                "key": "solax_power_control_mode",
                "entity_id": "Not configured",
                "status": "ERROR",
                "rawValue": None,
                "displayValue": "N/A",
                "error": f"Entity not configured: {e}",
            }
            overall_status = "ERROR"
        except Exception as e:
            check = {
                "name": "Power Control Mode",
                "key": "solax_power_control_mode",
                "entity_id": controller.sensors.get(
                    "solax_power_control_mode", "Not configured"
                ),
                "status": "ERROR",
                "rawValue": None,
                "displayValue": "N/A",
                "error": f"Read failed: {e}",
            }
            overall_status = "ERROR"

        health_check = {
            "name": "Battery Control (SolaX)",
            "description": "Controls SolaX inverter via VPP active-power commands",
            "required": True,
            "status": overall_status,
            "checks": [check],
            "last_run": datetime.now().isoformat(),
        }

        return [health_check]
