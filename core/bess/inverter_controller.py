"""Base class for inverter controllers.

Follows the PriceSource pattern (core/bess/price_manager.py). Subclasses
implement hardware-specific schedule conversion and deployment.
"""

import logging
from abc import ABC, abstractmethod
from typing import ClassVar

from .dp_schedule import DPSchedule
from .settings import BatterySettings

logger = logging.getLogger(__name__)


class InverterController(ABC):
    """Abstract base class for inverter controllers.

    Provides shared state and methods common to all inverter types.
    Subclasses implement hardware-specific schedule conversion and deployment.

    Strategic Intent → Control Mapping:
    - GRID_CHARGING   → grid_charge=True,  charge_rate=100, discharge_rate=0
    - SOLAR_STORAGE   → grid_charge=False, charge_rate=100, discharge_rate=0
    - LOAD_SUPPORT    → grid_charge=False, charge_rate=0,   discharge_rate=100
    - EXPORT_ARBITRAGE → grid_charge=False, charge_rate=0,  discharge_rate=<action-derived>
    - IDLE            → grid_charge=False, charge_rate=100, discharge_rate=0
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
        "EXPORT_ARBITRAGE": {
            "grid_charge": False,
            "charge_rate": 0,
            "discharge_rate": 100,
        },
        "IDLE": {"grid_charge": False, "charge_rate": 100, "discharge_rate": 0},
    }

    # Map strategic intents to battery modes (shared across Growatt MIN and SPH).
    INTENT_TO_MODE: ClassVar[dict[str, str]] = {
        "GRID_CHARGING": "battery_first",
        "SOLAR_STORAGE": "load_first",
        "LOAD_SUPPORT": "load_first",
        "EXPORT_ARBITRAGE": "grid_first",
        "IDLE": "load_first",
    }

    # Human-readable descriptions of strategic intents.
    INTENT_DESCRIPTIONS: ClassVar[dict[str, str]] = {
        "GRID_CHARGING": "Storing cheap grid energy for later use",
        "SOLAR_STORAGE": "Storing excess solar energy for evening/night",
        "LOAD_SUPPORT": "Using battery to support home consumption",
        "EXPORT_ARBITRAGE": "Selling stored energy to grid for profit",
        "IDLE": "No significant battery activity",
    }

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
        self.hourly_settings: dict[int, dict] = {}
        self.corruption_detected: bool = False

    # ── Period utility ────────────────────────────────────────────────────────

    def _period_to_time(self, period: int) -> tuple[int, int]:
        """Convert period number (0-95) to (hour, minute).

        Note: During DST fall-back, periods >= 96 produce hour >= 24.
        Callers must handle this (e.g., cap to 23:59 for TOU schedules).
        """
        return period // 4, (period % 4) * 15

    # ── Intent → hardware rates ───────────────────────────────────────────────

    def compute_rates_for_period(
        self, period: int, battery_action_kw: float
    ) -> tuple[bool, int]:
        """Map strategic intent for a period to hardware control rates.

        Args:
            period: 15-minute period index (0-95)
            battery_action_kw: Battery power in kW (positive=charge, negative=discharge)

        Returns:
            Tuple of (grid_charge, discharge_rate_percent)
        """
        intent = self.strategic_intents[period]
        return self._map_intent_to_rates(intent, battery_action_kw)

    def _map_intent_to_rates(
        self, intent: str, battery_action_kw: float
    ) -> tuple[bool, int]:
        """Map a strategic intent to (grid_charge, discharge_rate).

        Args:
            intent: Strategic intent string
            battery_action_kw: Battery power in kW (used for EXPORT_ARBITRAGE scaling)

        Returns:
            Tuple of (grid_charge, discharge_rate_percent)
        """
        if intent == "GRID_CHARGING":
            return True, 0
        elif intent == "SOLAR_STORAGE":
            return False, 0
        elif intent == "LOAD_SUPPORT":
            return False, 100
        elif intent == "EXPORT_ARBITRAGE":
            if battery_action_kw < -0.01:
                discharge_rate = min(
                    100,
                    max(
                        0,
                        int(abs(battery_action_kw) / self.max_discharge_power_kw * 100),
                    ),
                )
            else:
                discharge_rate = 0
            return False, discharge_rate
        elif intent == "IDLE":
            return False, 0
        else:
            raise ValueError(f"Unknown strategic intent: {intent}")

    def apply_period(self, controller, grid_charge: bool, discharge_rate: int) -> None:
        """Write period control settings to hardware.

        The caller (BatterySystemManager) is responsible for applying the
        discharge inhibit check before calling this method.

        Args:
            controller: HomeAssistantAPIController instance
            grid_charge: Whether to enable grid charging
            discharge_rate: Discharge power rate (0-100%), post-inhibit
        """
        self._write_period_to_hardware(controller, grid_charge, discharge_rate)

    # ── Shared hourly settings ────────────────────────────────────────────────

    def _calculate_hourly_settings(self) -> None:
        """Pre-calculate hourly settings from strategic intents.

        Aggregates quarterly strategic intents (96 periods) into hourly settings
        (24 hours). Each hour uses the dominant (most-common) intent among its
        four quarterly periods; alphabetical order breaks ties deterministically.
        """
        self.hourly_settings = {}

        if not self.strategic_intents:
            raise ValueError(
                "Missing strategic intents for hourly settings calculation"
            )

        num_periods = len(self.strategic_intents)
        num_hours = (num_periods + 3) // 4

        for hour in range(num_hours):
            start_p = hour * 4
            end_p = min(start_p + 4, num_periods)
            period_intents = [self.strategic_intents[p] for p in range(start_p, end_p)]

            intent_counts: dict[str, int] = {}
            for intent in period_intents:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
            max_count = max(intent_counts.values())
            dominant_intent = min(i for i, c in intent_counts.items() if c == max_count)

            control = self.INTENT_TO_CONTROL[dominant_intent]

            self.hourly_settings[hour] = {
                "grid_charge": control["grid_charge"],
                "charge_rate": control["charge_rate"],
                "discharge_rate": control["discharge_rate"],
                "strategic_intent": dominant_intent,
                "state": (
                    "charging"
                    if dominant_intent in ("GRID_CHARGING", "SOLAR_STORAGE")
                    else (
                        "discharging"
                        if dominant_intent in ("LOAD_SUPPORT", "EXPORT_ARBITRAGE")
                        else "idle"
                    )
                ),
                "batt_mode": (
                    "battery_first"
                    if dominant_intent in ("GRID_CHARGING", "SOLAR_STORAGE")
                    else (
                        "grid_first"
                        if dominant_intent == "EXPORT_ARBITRAGE"
                        else "load_first"
                    )
                ),
                "battery_action_kw": 0.0,
            }

    def get_hourly_settings(self, hour: int) -> dict:
        """Get pre-calculated settings for a specific hour.

        Args:
            hour: Hour (0-23)

        Returns:
            Dict with grid_charge, charge_rate, discharge_rate, state, batt_mode, etc.

        Raises:
            ValueError: If hourly settings not calculated yet for this hour
        """
        if hour not in self.hourly_settings:
            raise ValueError(
                f"No hourly settings for hour {hour}. "
                f"Strategic intents: {len(self.strategic_intents)}, "
                f"Settings calculated: {len(self.hourly_settings)}"
            )
        return self.hourly_settings[hour]

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
        self, intents: list[str] | None = None
    ) -> list[dict]:
        """Get period groups with full control parameters for display/API.

        Groups consecutive 15-minute periods ONLY when ALL parameters are identical:
        strategic intent, battery mode, grid charge, charge rate, and discharge rate.

        Args:
            intents: Optional list of strategic intents to group. If None,
                     uses self.strategic_intents (today's schedule).

        Returns:
            List of period groups with all control parameters and time strings
        """
        effective_intents = intents if intents is not None else self.strategic_intents
        if not effective_intents:
            return []

        num_periods = len(effective_intents)

        period_settings = []
        for period in range(num_periods):
            intent = effective_intents[period]
            mode = self.INTENT_TO_MODE.get(intent, "load_first")
            control = self.INTENT_TO_CONTROL.get(
                intent,
                {"grid_charge": False, "charge_rate": 100, "discharge_rate": 0},
            )
            period_settings.append(
                {
                    "period": period,
                    "intent": intent,
                    "mode": mode,
                    "grid_charge": control["grid_charge"],
                    "charge_rate": control["charge_rate"],
                    "discharge_rate": control["discharge_rate"],
                }
            )

        groups = []
        current_group: dict | None = None

        for ps in period_settings:
            if current_group is not None and (
                ps["intent"] == current_group["intent"]
                and ps["mode"] == current_group["mode"]
                and ps["grid_charge"] == current_group["grid_charge"]
                and ps["charge_rate"] == current_group["charge_rate"]
                and ps["discharge_rate"] == current_group["discharge_rate"]
            ):
                current_group["end_period"] = ps["period"]
                current_group["count"] += 1
            else:
                if current_group is not None:
                    groups.append(current_group)
                current_group = {
                    "start_period": ps["period"],
                    "end_period": ps["period"],
                    "intent": ps["intent"],
                    "mode": ps["mode"],
                    "grid_charge": ps["grid_charge"],
                    "charge_rate": ps["charge_rate"],
                    "discharge_rate": ps["discharge_rate"],
                    "count": 1,
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
            result.append(
                {
                    "start_time": f"{start_h:02d}:{start_m:02d}",
                    "end_time": f"{end_h:02d}:{end_m:02d}",
                    "start_period": group["start_period"],
                    "end_period": group["end_period"],
                    "intent": group["intent"],
                    "mode": group["mode"],
                    "grid_charge": group["grid_charge"],
                    "charge_rate": group["charge_rate"],
                    "discharge_rate": group["discharge_rate"],
                    "period_count": group["count"],
                    "duration_minutes": group["count"] * 15,
                }
            )
        return result

    # ── Abstract interface ────────────────────────────────────────────────────

    @property
    @abstractmethod
    def active_tou_intervals(self) -> list[dict]:
        """Return the subset of TOU intervals currently written to hardware."""

    @abstractmethod
    def create_schedule(
        self,
        schedule: DPSchedule,
        current_period: int = 0,
        previous_tou_intervals: list[dict] | None = None,
    ) -> None:
        """Build hardware-specific schedule from DPSchedule."""

    @abstractmethod
    def write_schedule_to_hardware(
        self,
        controller,
        effective_period: int,
        current_tou: list,
    ) -> tuple[int, int]:
        """Write schedule to inverter hardware.

        Returns:
            Tuple of (writes, disables)
        """

    @abstractmethod
    def compare_schedules(
        self, other_schedule: "InverterController", from_period: int = 0
    ) -> tuple[bool, str]:
        """Compare schedules. Returns (schedules_differ, reason)."""

    @abstractmethod
    def read_and_initialize_from_hardware(self, controller, current_hour: int) -> None:
        """Read current schedule from inverter and initialize this controller."""

    @abstractmethod
    def sync_soc_limits(self, controller) -> None:
        """Sync SOC limits from config to inverter hardware."""

    @abstractmethod
    def _write_period_to_hardware(
        self, controller, grid_charge: bool, discharge_rate: int
    ) -> None:
        """Write per-period control settings to hardware (inverter-specific).

        Args:
            controller: HomeAssistantAPIController instance
            grid_charge: Whether to enable grid charging
            discharge_rate: Discharge power rate (0-100%)
        """

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
