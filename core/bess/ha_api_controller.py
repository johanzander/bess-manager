"""Home Assistant REST API Controller.

This controller provides the same interface as HomeAssistantController
but uses the REST API instead of direct pyscript access.
"""

import json
import logging
import re
import ssl
import time
import urllib.parse
from typing import ClassVar

import requests
import websocket

from .exceptions import SystemConfigurationError
from .runtime_failure_tracker import RuntimeFailureTracker

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


def run_request(http_method, *args, **kwargs):
    """Log the request and response for debugging purposes."""
    try:
        # Log the request details
        logger.debug("HTTP Method: %s", http_method.__name__.upper())
        logger.debug("Request Args: %s", args)
        logger.debug("Request Kwargs: %s", kwargs)

        # Make the HTTP request
        response = http_method(*args, **kwargs)

        # Log the response details
        logger.debug("Response Status Code: %s", response.status_code)
        logger.debug("Response Headers: %s", response.headers)
        logger.debug("Response Content: %s", response.text)

        return response
    except Exception as e:
        logger.error("Error during HTTP request: %s", str(e))
        raise


class HomeAssistantAPIController:
    """A class for interacting with Inverter controls via Home Assistant REST API."""

    failure_tracker: RuntimeFailureTracker | None

    def _get_sensor_display_name(self, sensor_key: str) -> str:
        """Get display name for a sensor key from METHOD_SENSOR_MAP."""
        for method_info in self.METHOD_SENSOR_MAP.values():
            if method_info["sensor_key"] == sensor_key:
                name = method_info["name"]
                return str(name) if name else f"sensor '{sensor_key}'"
        return f"sensor '{sensor_key}'"

    def _get_entity_for_service(self, sensor_key: str) -> str:
        """Get entity ID for service calls with proper error handling."""
        try:
            entity_id, _ = self._resolve_entity_id(sensor_key)
            return entity_id
        except ValueError as e:
            description = self._get_sensor_display_name(sensor_key)
            raise ValueError(f"No entity ID configured for {description}") from e

    def _get_sensor_key(self, method_name: str) -> str | None:
        """Get the sensor key for a method - compatibility method for existing code."""
        return self.get_method_sensor_key(method_name)

    @classmethod
    def get_method_info(cls, method_name: str) -> dict[str, object] | None:
        """Get method information including sensor key and display name."""
        return cls.METHOD_SENSOR_MAP.get(method_name)

    @classmethod
    def get_method_name(cls, method_name: str) -> str | None:
        """Get the display name for a method."""
        method_info = cls.METHOD_SENSOR_MAP.get(method_name)
        if method_info:
            name = method_info["name"]
            return str(name) if name else None
        return None

    @classmethod
    def get_method_sensor_key(cls, method_name: str) -> str | None:
        """Get the sensor key for a method."""
        method_info = cls.METHOD_SENSOR_MAP.get(method_name)
        if method_info:
            sensor_key = method_info["sensor_key"]
            return str(sensor_key) if sensor_key else None
        return None

    def __init__(
        self,
        ha_url: str,
        token: str,
        sensor_config: dict | None = None,
        growatt_device_id: str | None = None,
    ):
        """Initialize the Controller with Home Assistant API access.

        Args:
            ha_url: Base URL of Home Assistant (default: "http://supervisor/core")
            token: Long-lived access token for Home Assistant
            sensor_config: Sensor configuration mapping from options.json
            growatt_device_id: Growatt device ID for TOU segment operations

        """
        self.base_url = ha_url
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.max_attempts = 4
        self.retry_base_delay = 2  # seconds (exponential backoff: 2, 4, 8)
        self.test_mode = False

        # Use provided sensor configuration
        self.sensors = sensor_config or {}

        # Store Growatt device ID for TOU operations
        self.growatt_device_id = growatt_device_id

        # Runtime failure tracker (injected by BatterySystemManager)
        self.failure_tracker = None

        # Create persistent session for connection reuse (400x faster)
        self.session = requests.Session()
        self.session.headers.update(self.headers)

        logger.info(
            "Initialized HomeAssistantAPIController with %d sensor mappings",
            len(self.sensors),
        )

    # Class-level sensor mapping - immutable mapping
    METHOD_SENSOR_MAP: ClassVar[dict[str, dict[str, object]]] = {
        # Battery control methods
        "get_battery_soc": {
            "sensor_key": "battery_soc",
            "name": "Battery State of Charge",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_charging_power_rate": {
            "sensor_key": "battery_charging_power_rate",
            "name": "Battery Charging Power Rate",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_discharging_power_rate": {
            "sensor_key": "battery_discharging_power_rate",
            "name": "Battery Discharging Power Rate",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_charge_stop_soc": {
            "sensor_key": "battery_charge_stop_soc",
            "name": "Battery Charge Stop SOC",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_discharge_stop_soc": {
            "sensor_key": "battery_discharge_stop_soc",
            "name": "Battery Discharge Stop SOC",
            "unit": "%",
            "precision": 1,
            "conversion_threshold": None,
        },
        "grid_charge_enabled": {
            "sensor_key": "grid_charge",
            "name": "Grid Charge Enabled",
            "unit": "bool",
            "precision": 1,
            "conversion_threshold": None,
        },
        # Power monitoring methods
        "get_pv_power": {
            "sensor_key": "pv_power",
            "name": "Solar Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_import_power": {
            "sensor_key": "import_power",
            "name": "Grid Import Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_export_power": {
            "sensor_key": "export_power",
            "name": "Grid Export Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_local_load_power": {
            "sensor_key": "local_load_power",
            "name": "Home Load Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_battery_charge_power": {
            "sensor_key": "battery_charge_power",
            "name": "Battery Charging Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_battery_discharge_power": {
            "sensor_key": "battery_discharge_power",
            "name": "Battery Discharging Power",
            "unit": "W",
            "precision": 0,
            "conversion_threshold": 1000,
        },
        "get_l1_current": {
            "sensor_key": "current_l1",
            "name": "Current L1",
            "unit": "A",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_l2_current": {
            "sensor_key": "current_l2",
            "name": "Current L2",
            "unit": "A",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_l3_current": {
            "sensor_key": "current_l3",
            "name": "Current L3",
            "unit": "A",
            "precision": 1,
            "conversion_threshold": None,
        },
        # Energy totals
        # Home consumption forecast
        "get_estimated_consumption": {
            "sensor_key": "48h_avg_grid_import",
            "name": "Average Hourly Power Consumption",
            "unit": "W",
            "precision": 1,
            "conversion_threshold": 1000,
        },
        # Solar forecast
        "get_solar_forecast": {
            "sensor_key": "solar_forecast_today",
            "name": "Solar Forecast",
            "unit": "list",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_solar_forecast_tomorrow": {
            "sensor_key": "solar_forecast_tomorrow",
            "name": "Solar Forecast Tomorrow",
            "unit": "list",
            "precision": 1,
            "conversion_threshold": None,
        },
        # Lifetime and meter sensors (added for abstraction)
        "get_battery_charged_lifetime": {
            "sensor_key": "lifetime_battery_charged",
            "name": "Lifetime Total Battery Charged",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_battery_discharged_lifetime": {
            "sensor_key": "lifetime_battery_discharged",
            "name": "Lifetime Total Battery Discharged",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_solar_production_lifetime": {
            "sensor_key": "lifetime_solar_energy",
            "name": "Lifetime Total Solar Energy",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_grid_import_lifetime": {
            "sensor_key": "lifetime_import_from_grid",
            "name": "Lifetime Import from Grid",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_grid_export_lifetime": {
            "sensor_key": "lifetime_export_to_grid",
            "name": "Lifetime Total Export to Grid",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_load_consumption_lifetime": {
            "sensor_key": "lifetime_load_consumption",
            "name": "Lifetime Total Load Consumption",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_system_production_lifetime": {
            "sensor_key": "lifetime_system_production",
            "name": "Lifetime System Production",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_self_consumption_lifetime": {
            "sensor_key": "lifetime_self_consumption",
            "name": "Lifetime Self Consumption",
            "unit": "kWh",
            "precision": 1,
            "conversion_threshold": None,
        },
        "get_discharge_inhibit_active": {
            "sensor_key": "discharge_inhibit",
            "name": "Discharge Inhibit",
            "unit": "binary",
            "precision": 0,
            "conversion_threshold": None,
        },
    }

    # ── Entity Discovery Architecture ─────────────────────────────────────
    # HA's entity registry has three key fields per entity:
    #   unique_id  — assigned by the integration, NEVER changes (e.g. "rkm0d7n04x_import_power")
    #   entity_id  — the API-callable name (e.g. "sensor.rkm0d7n04x_import_power"), user CAN rename
    #   platform   — which integration created it (e.g. "growatt_server"), NEVER changes
    #
    # Discovery uses unique_id + platform (both immutable) to FIND the correct
    # entities regardless of user renaming.  It then stores the entity_id because
    # that is what HA's REST/WebSocket APIs require for reading sensor values.
    # Re-running discovery after a rename will update the stored entity_id.
    #
    # ── BESS Sensor Key Mapping ───────────────────────────────────────────
    # Each BESS key has a unique_id suffix per integration.  Discovery matches
    # unique_id.endswith("_<suffix>") to resolve the entity.
    #
    # solax_modbus unique_ids follow the pattern "{serial}_solax_{plugin_key}".
    # The suffix map uses the FULL suffix including the "solax_" prefix to
    # ensure exact, deterministic matching with no ambiguity.
    #
    # growatt_server unique_ids use "{SN}_{key}" or "{SN}-{sensor_key}".
    #
    # BESS key                       growatt_server suffix              solax_modbus suffix (full)
    # ─────────────────────────────  ─────────────────────────────────  ─────────────────────────────────
    # battery_soc                    state_of_charge_soc                solax_battery_capacity / solax_battery_soc
    # battery_charge_power           battery_1_charging_w               solax_battery_power_charge / solax_battery_charge_power
    # battery_discharge_power        battery_1_discharging_w            solax_battery_power_discharge / solax_battery_discharge_power
    # import_power                   import_power                       solax_measured_power / solax_total_forward_power / solax_ac_power_to_user
    # export_power                   export_power                       solax_grid_export / solax_total_reverse_power / solax_ac_power_to_grid
    # local_load_power               local_load_power                   solax_house_load / solax_total_load_power
    # pv_power                       internal_wattage                   solax_pv_power_1 / solax_pv_power_total / solax_total_pv_power
    # grid_charge                    charge_from_grid                   solax_charger_switch
    # battery_charging_power_rate    battery_charge_power_limit         solax_ems_charging_rate
    # battery_discharging_power_rate battery_discharge_power_limit      solax_ems_discharging_rate
    # battery_charge_stop_soc        battery_charge_soc_limit           solax_ems_charging_stop_soc
    # battery_discharge_stop_soc     battery_discharge_soc_limit        solax_ems_discharging_stop_soc
    # lifetime_battery_charged       lifetime_total_all_batteries_charged  solax_battery_input_energy_total / solax_total_battery_input_energy
    # lifetime_battery_discharged    lifetime_total_all_batteries_discharged  solax_battery_output_energy_total / solax_total_battery_output_energy
    # lifetime_solar_energy          lifetime_total_solar_energy        solax_total_solar_energy
    # lifetime_export_to_grid        lifetime_total_export_to_grid      solax_grid_export_total / solax_total_grid_export
    # lifetime_import_from_grid      lifetime_import_from_grid          solax_grid_import_total / solax_total_grid_import
    # lifetime_load_consumption      lifetime_total_load_consumption    solax_total_yield (GEN4) / solax_total_load (GEN3)
    # lifetime_system_production     lifetime_system_production         solax_total_power_generation (GEN4) / solax_total_yield (native SolaX)
    #
    # GEN3-only EMS entities (MIX/SPA/SPH via solax_modbus):
    # battery_charging_power_rate    —                                  solax_battery_first_charge_rate
    # battery_discharging_power_rate —                                  solax_grid_first_discharge_rate
    # lifetime_self_consumption      lifetime_self_consumption          — (growatt_server only)
    #
    # SOLAX-ONLY (VPP control — native SolaX inverters):
    # solax_power_control_mode       —                                  solax_remotecontrol_power_control
    # solax_active_power             —                                  solax_remotecontrol_active_power
    # solax_autorepeat_duration      —                                  solax_remotecontrol_autorepeat_duration
    # solax_power_control_trigger    —                                  solax_remotecontrol_trigger
    # solax_battery_min_soc          —                                  solax_battery_minimum_capacity
    # solax_charger_use_mode         —                                  solax_charger_use_mode (SolaX native only)
    #
    # GROWATT-VIA-SOLAX-ONLY (TOU time slots — Growatt MIN via solax_modbus):
    # Note: plugin key="time_N_enabled" (used in unique_id) but
    # name="Time N Active" (used in entity_id → *_time_N_active).
    # Detection and mapping match on unique_id, so the suffix is "enabled".
    # Slots 4-9 are disabled by default in HA entity registry.
    # tou_time_N_enabled             —                                  solax_time_N_enabled  (N=1..9)
    # tou_time_N_begin               —                                  solax_time_N_begin
    # tou_time_N_end                 —                                  solax_time_N_end
    # tou_time_N_mode                —                                  solax_time_N_mode
    # tou_time_N_update              —                                  solax_time_N_update
    # ───────────────────────────────────────────────────────────────────────────

    # ── Per-platform suffix maps for growatt_server discovery ─────────────
    #
    # The growatt_server HA integration uses different sensor key prefixes
    # depending on the Growatt Cloud device_type:
    #   - "min"/"tlx" (AC-coupled) → sensors from tlx.py → unique_id "{SN}-tlx_*"
    #   - "mix"/"sph" (DC-coupled) → sensors from sph.py → unique_id "{SN}-mix_*"
    #
    # Number/switch entities (battery limits, grid charge) exist ONLY for
    # MIN inverters (V1 API).  SPH has no number/switch entities.
    #
    # unique_id formats:
    #   - Sensor entities: "{SN}-{sensor_key}" (hyphen separator)
    #   - Number/switch entities: "{SN}_{key}" (underscore separator)
    #
    # The sensor key differs from the entity_id suffix because HA generates
    # entity IDs from the slugified translation name, not the key.
    #
    # Each map includes both entity_id-based suffixes (for fallback matching)
    # and unique_id sensor keys (for reliable matching).

    # Growatt MIN/TLX (AC-coupled) via growatt_server cloud integration
    GROWATT_MIN_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        # ── SOC ──────────────────────────────────────────────────────────
        "state_of_charge_soc": "battery_soc",  # entity_id suffix (current translation)
        "statement_of_charge_soc": "battery_soc",  # entity_id suffix (old translation)
        "tlx_statement_of_charge": "battery_soc",  # unique_id sensor key
        # ── Real-time power sensors ──────────────────────────────────────
        "battery_1_charging_w": "battery_charge_power",  # entity_id suffix
        "tlx_battery_1_charge_w": "battery_charge_power",  # unique_id sensor key
        "battery_1_discharging_w": "battery_discharge_power",  # entity_id suffix
        "tlx_battery_1_discharge_w": "battery_discharge_power",  # unique_id sensor key
        "import_power": "import_power",  # entity_id suffix
        "tlx_pac_to_user_total": "import_power",  # unique_id sensor key
        "export_power": "export_power",  # entity_id suffix
        "tlx_pac_to_grid_total": "export_power",  # unique_id sensor key
        "local_load_power": "local_load_power",  # entity_id suffix
        "tlx_pac_to_local_load": "local_load_power",  # unique_id sensor key
        "internal_wattage": "pv_power",  # entity_id suffix
        "tlx_internal_wattage": "pv_power",  # unique_id sensor key
        # ── Grid charge switch (MIN only, V1 API) ────────────────────────
        "charge_from_grid": "grid_charge",  # entity_id suffix (translation name)
        "ac_charge": "grid_charge",  # unique_id key / old entity_id suffix
        # ── Number entities (MIN only, V1 API) ──────────────────────────
        "battery_charge_power_limit": "battery_charging_power_rate",
        "battery_discharge_power_limit": "battery_discharging_power_rate",
        "battery_charge_soc_limit": "battery_charge_stop_soc",
        "battery_discharge_soc_limit": "battery_discharge_stop_soc",
        "battery_discharge_soc_limit_on_grid": "battery_discharge_stop_soc",
        "soc_limit_on_grid": "battery_discharge_stop_soc",
        # ── Lifetime energy sensors ──────────────────────────────────────
        "lifetime_total_all_batteries_charged": "lifetime_battery_charged",
        "tlx_all_batteries_charge_total": "lifetime_battery_charged",
        "lifetime_total_all_batteries_discharged": "lifetime_battery_discharged",
        "tlx_all_batteries_discharge_total": "lifetime_battery_discharged",
        "lifetime_total_solar_energy": "lifetime_solar_energy",
        "tlx_solar_generation_total": "lifetime_solar_energy",
        "lifetime_total_export_to_grid": "lifetime_export_to_grid",
        "tlx_export_to_grid_total": "lifetime_export_to_grid",
        "lifetime_import_from_grid": "lifetime_import_from_grid",
        "tlx_import_from_grid_total": "lifetime_import_from_grid",
        "lifetime_total_load_consumption": "lifetime_load_consumption",
        "mix_load_consumption_total": "lifetime_load_consumption",  # TLX reuses mix_ key
        "lifetime_system_production": "lifetime_system_production",
        "tlx_system_production_total": "lifetime_system_production",
        "lifetime_self_consumption": "lifetime_self_consumption",
        "tlx_self_consumption_total": "lifetime_self_consumption",
    }

    # Growatt MIX/SPH (DC-coupled) via growatt_server cloud integration
    # SPH reuses mix_ sensor key names from the HA integration.
    # SPH power sensors are in W; MIX power sensors are in kW (but both
    # use the same unique_id keys — the unit difference is in the API response).
    # SPH has NO number/switch entities — battery control is via service calls.
    GROWATT_SPH_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        # ── SOC ──────────────────────────────────────────────────────────
        "state_of_charge": "battery_soc",  # entity_id suffix (SPH translation)
        "mix_statement_of_charge": "battery_soc",  # unique_id sensor key
        # ── Real-time power sensors ──────────────────────────────────────
        "battery_charging": "battery_charge_power",  # entity_id suffix
        "mix_battery_charge": "battery_charge_power",  # unique_id sensor key
        "battery_discharging_w": "battery_discharge_power",  # entity_id suffix
        "mix_battery_discharge_w": "battery_discharge_power",  # unique_id sensor key
        "import_from_grid": "import_power",  # entity_id suffix
        "mix_import_from_grid": "import_power",  # unique_id sensor key
        "export_to_grid": "export_power",  # entity_id suffix
        "mix_export_to_grid": "export_power",  # unique_id sensor key
        "all_pv_wattage": "pv_power",  # entity_id suffix
        "mix_wattage_pv_all": "pv_power",  # unique_id sensor key
        # ── Lifetime energy sensors ──────────────────────────────────────
        "lifetime_battery_charged": "lifetime_battery_charged",  # entity_id suffix
        "mix_battery_charge_lifetime": "lifetime_battery_charged",  # unique_id sensor key
        "lifetime_battery_discharged": "lifetime_battery_discharged",  # entity_id suffix
        "mix_battery_discharge_lifetime": "lifetime_battery_discharged",  # unique_id
        "lifetime_solar_energy": "lifetime_solar_energy",  # entity_id suffix
        "mix_solar_generation_lifetime": "lifetime_solar_energy",  # unique_id sensor key
        "lifetime_export_to_grid": "lifetime_export_to_grid",  # entity_id suffix
        "mix_export_to_grid_lifetime": "lifetime_export_to_grid",  # unique_id sensor key
        "lifetime_import_from_grid": "lifetime_import_from_grid",  # entity_id suffix
        "mix_import_from_grid_total": "lifetime_import_from_grid",  # unique_id sensor key
        "lifetime_load_consumption": "lifetime_load_consumption",  # entity_id suffix
        "mix_load_consumption_lifetime": "lifetime_load_consumption",  # unique_id sensor key
    }

    # ── Octopus Energy rate event patterns ────────────────────────────────
    #
    # The Octopus Energy integration (BottlecapDave/HomeAssistant-OctopusEnergy)
    # creates event entities for electricity and gas rate data.  unique_id format:
    #
    #   Electricity import:  octopus_energy_electricity_{serial}_{mpan}_current_day_rates
    #   Electricity export:  octopus_energy_electricity_{serial}_{mpan}_export_current_day_rates
    #   Gas:                 octopus_energy_gas_{serial}_{mprn}_current_day_rates
    #
    # Discovery uses regex on unique_id to match electricity entities only
    # (gas entities are excluded by the ``_electricity_`` requirement).
    # Named groups map directly to the BESS form field keys.
    _OCTOPUS_RATE_PATTERNS: ClassVar[list[tuple[re.Pattern, str]]] = [
        (
            re.compile(r"octopus_energy_electricity_.+_export_current_day_rates$"),
            "exportToday",
        ),
        (
            re.compile(r"octopus_energy_electricity_.+_export_next_day_rates$"),
            "exportTomorrow",
        ),
        (
            re.compile(r"octopus_energy_electricity_.+(?<!export)_current_day_rates$"),
            "importToday",
        ),
        (
            re.compile(r"octopus_energy_electricity_.+(?<!export)_next_day_rates$"),
            "importTomorrow",
        ),
    ]

    # ── Per-platform suffix maps for solax_modbus discovery ─────────────
    #
    # The solax_modbus integration (github.com/wills106/homeassistant-solax-modbus)
    # constructs unique_ids as "{serial}_solax_{plugin_key}".  Every suffix below
    # is the full deterministic suffix including the "solax_" prefix.
    #
    # Each platform has its own map — no collisions, no remapping.

    # Growatt GEN4 (MIN/MOD/MID) via solax_modbus Growatt plugin
    # solax_modbus unique_id format: {user_chosen_device_name}_{register_key}
    # The device name prefix is user-configurable (default "SolaX"), so suffix
    # maps use only the fixed register key.  The matching code uses
    # endswith(f"_{suffix}") which strips any prefix.
    SOLAX_GROWATT_MIN_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        # Real-time power
        "battery_soc": "battery_soc",
        "battery_charge_power": "battery_charge_power",
        "battery_discharge_power": "battery_discharge_power",
        "total_forward_power": "import_power",  # register 3041
        "total_reverse_power": "export_power",  # register 3043
        "pv_power_total": "pv_power",  # register 1, enabled by default
        "total_pv_power": "pv_power",  # disabled by default
        "total_load_power": "local_load_power",
        # Lifetime energy
        "total_battery_input_energy": "lifetime_battery_charged",
        "total_battery_output_energy": "lifetime_battery_discharged",
        "total_solar_energy": "lifetime_solar_energy",
        "total_grid_import": "lifetime_import_from_grid",
        "total_grid_export": "lifetime_export_to_grid",
        "total_yield": "lifetime_load_consumption",  # register 3077, "Total Load Energy"
        "total_power_generation": "lifetime_system_production",  # register 3051
        # EMS control
        "ems_charging_rate": "battery_charging_power_rate",
        "ems_discharging_rate": "battery_discharging_power_rate",
        "ems_charging_stop_soc": "battery_charge_stop_soc",
        "ems_discharging_stop_soc": "battery_discharge_stop_soc",
        "charger_switch": "grid_charge",
        # TOU time slots (9 slots)
        "time_1_enabled": "tou_time_1_enabled",
        "time_1_begin": "tou_time_1_begin",
        "time_1_end": "tou_time_1_end",
        "time_1_mode": "tou_time_1_mode",
        "time_1_update": "tou_time_1_update",
        "time_2_enabled": "tou_time_2_enabled",
        "time_2_begin": "tou_time_2_begin",
        "time_2_end": "tou_time_2_end",
        "time_2_mode": "tou_time_2_mode",
        "time_2_update": "tou_time_2_update",
        "time_3_enabled": "tou_time_3_enabled",
        "time_3_begin": "tou_time_3_begin",
        "time_3_end": "tou_time_3_end",
        "time_3_mode": "tou_time_3_mode",
        "time_3_update": "tou_time_3_update",
        "time_4_enabled": "tou_time_4_enabled",
        "time_4_begin": "tou_time_4_begin",
        "time_4_end": "tou_time_4_end",
        "time_4_mode": "tou_time_4_mode",
        "time_4_update": "tou_time_4_update",
        "time_5_enabled": "tou_time_5_enabled",
        "time_5_begin": "tou_time_5_begin",
        "time_5_end": "tou_time_5_end",
        "time_5_mode": "tou_time_5_mode",
        "time_5_update": "tou_time_5_update",
        "time_6_enabled": "tou_time_6_enabled",
        "time_6_begin": "tou_time_6_begin",
        "time_6_end": "tou_time_6_end",
        "time_6_mode": "tou_time_6_mode",
        "time_6_update": "tou_time_6_update",
        "time_7_enabled": "tou_time_7_enabled",
        "time_7_begin": "tou_time_7_begin",
        "time_7_end": "tou_time_7_end",
        "time_7_mode": "tou_time_7_mode",
        "time_7_update": "tou_time_7_update",
        "time_8_enabled": "tou_time_8_enabled",
        "time_8_begin": "tou_time_8_begin",
        "time_8_end": "tou_time_8_end",
        "time_8_mode": "tou_time_8_mode",
        "time_8_update": "tou_time_8_update",
        "time_9_enabled": "tou_time_9_enabled",
        "time_9_begin": "tou_time_9_begin",
        "time_9_end": "tou_time_9_end",
        "time_9_mode": "tou_time_9_mode",
        "time_9_update": "tou_time_9_update",
    }

    # Growatt GEN3 (MIX/SPA/SPH) via solax_modbus Growatt plugin
    SOLAX_GROWATT_SPH_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        # Real-time power
        "battery_soc": "battery_soc",
        "battery_charge_power": "battery_charge_power",
        "battery_discharge_power": "battery_discharge_power",
        "ac_power_to_user": "import_power",  # register 1015
        "ac_power_to_grid": "export_power",  # register 1023
        "pv_power_total": "pv_power",
        "total_load_power": "local_load_power",
        # Lifetime energy
        "total_battery_input_energy": "lifetime_battery_charged",
        "total_battery_output_energy": "lifetime_battery_discharged",
        "total_solar_energy": "lifetime_solar_energy",
        "total_grid_import": "lifetime_import_from_grid",
        "total_grid_export": "lifetime_export_to_grid",
        "total_load": "lifetime_load_consumption",  # register 1062
        # No lifetime_system_production — BESS derives from lifetime_solar_energy
        # EMS control
        "battery_first_charge_rate": "battery_charging_power_rate",
        "grid_first_discharge_rate": "battery_discharging_power_rate",
        "battery_first_maximum_soc": "battery_charge_stop_soc",
        "load_first_battery_minimum_soc": "battery_discharge_stop_soc",
        "charger_switch": "grid_charge",
    }

    # SolaX native inverters via solax_modbus integration
    SOLAX_NATIVE_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        # Real-time power
        "battery_capacity": "battery_soc",
        "battery_power_charge": "battery_charge_power",
        "battery_power_discharge": "battery_discharge_power",
        "measured_power": "import_power",
        "grid_import": "import_power",  # alternative suffix
        "grid_export": "export_power",
        "pv_power_1": "pv_power",
        "house_load": "local_load_power",
        # Lifetime energy
        "battery_input_energy_total": "lifetime_battery_charged",
        "battery_output_energy_total": "lifetime_battery_discharged",
        "total_solar_energy": "lifetime_solar_energy",
        "grid_import_total": "lifetime_import_from_grid",
        "grid_export_total": "lifetime_export_to_grid",
        "total_yield": "lifetime_system_production",  # register 0x52, "Total Yield" (production)
        # No native register for lifetime_load_consumption
        # VPP control
        "remotecontrol_power_control": "solax_power_control_mode",
        "remotecontrol_active_power": "solax_active_power",
        "remotecontrol_autorepeat_duration": "solax_autorepeat_duration",
        "remotecontrol_trigger": "solax_power_control_trigger",
        "battery_minimum_capacity": "solax_battery_min_soc",
        "battery_minimum_capacity_grid_tied": "solax_battery_min_soc",
        "charger_use_mode": "solax_charger_use_mode",
    }

    def resolve_sensor_for_influxdb(self, sensor_key: str) -> str | None:
        """Resolve sensor key to entity ID formatted for InfluxDB (without 'sensor.' prefix).

        Args:
            sensor_key: The sensor key from config

        Returns:
            Entity ID without 'sensor.' prefix, or None if not configured

        Raises:
            TypeError: If sensor_key is not a string
        """
        if not isinstance(sensor_key, str):
            raise TypeError(f"sensor_key must be a string, got {type(sensor_key)}")

        try:
            entity_id, _ = self._resolve_entity_id(sensor_key)
            return entity_id[7:] if entity_id.startswith("sensor.") else entity_id
        except ValueError:
            return None

    def _resolve_entity_id(self, sensor_key: str) -> tuple[str, str]:
        """Unified entity ID resolution with consistent logic.

        Args:
            sensor_key: The sensor key to resolve

        Returns:
            tuple: (entity_id, resolution_method)

        Raises:
            ValueError: If sensor_key not found
        """
        # First check our sensor configuration
        if sensor_key in self.sensors:
            entity_id = self.sensors[sensor_key]
            if not entity_id or not entity_id.strip():
                raise ValueError(
                    f"Empty entity ID configured for sensor '{sensor_key}'"
                )
            return entity_id, "configured"

        # Require explicit configuration for all operations
        # This ensures proper sensor mapping and prevents silent failures
        raise ValueError(f"No entity ID configured for sensor '{sensor_key}'")

    def get_method_sensor_info(self, method_name: str) -> dict:
        """Get sensor configuration info for a controller method."""
        method_info = self.METHOD_SENSOR_MAP.get(method_name)
        if not method_info:
            return {
                "method_name": method_name,
                "name": method_name,
                "sensor_key": None,
                "entity_id": None,
                "status": "unknown_method",
                "error": f"Method '{method_name}' not found in sensor mapping",
            }

        sensor_key = str(method_info["sensor_key"])
        try:
            entity_id, resolution_method = self._resolve_entity_id(sensor_key)
        except ValueError as e:
            return {
                "method_name": method_name,
                "name": method_info["name"],
                "sensor_key": sensor_key,
                "entity_id": "Not configured",
                "status": "not_configured",
                "error": str(e),
                "current_value": None,
            }

        result = {
            "method_name": method_name,
            "name": method_info["name"],
            "sensor_key": sensor_key,
            "entity_id": entity_id,
            "status": "unknown",
            "error": None,
            "current_value": None,
            "resolution_method": resolution_method,
        }

        try:
            response = self._api_request(
                "get",
                f"/api/states/{entity_id}",
                operation=f"Check sensor info for '{method_name}'",
                category="sensor_read",
            )
            if not response:
                result.update(
                    {
                        "status": "entity_missing",
                        "error": f"Entity '{entity_id}' does not exist in Home Assistant",
                    }
                )
            elif response.get("state") in ["unavailable", "unknown"]:
                result.update(
                    {
                        "status": "entity_unavailable",
                        "error": f"Entity '{entity_id}' state is '{response.get('state')}'",
                    }
                )
            else:
                result.update({"status": "ok", "current_value": response.get("state")})
        except (requests.RequestException, ValueError, KeyError) as e:
            result.update(
                {
                    "status": "error",
                    "error": f"Failed to check entity '{entity_id}': {e!s}",
                }
            )
        return result

    def validate_methods_sensors(self, method_list: list) -> list:
        """Validate sensors for multiple methods at once."""
        return [self.get_method_sensor_info(method) for method in method_list]

    def get_entity_state_raw(self, entity_id: str) -> dict | None:
        """Fetch raw HA state dict for a known entity ID.

        Intended for debug/export use where the caller already has a resolved
        entity ID and wants the full state response without going through the
        sensor-key lookup path.

        Args:
            entity_id: Fully-qualified HA entity ID (e.g. "sensor.battery_soc")

        Returns:
            Full HA state dict, or None if the entity does not exist
        """
        return self._api_request(
            "get",
            f"/api/states/{entity_id}",
            operation=f"Fetch raw state for '{entity_id}'",
            category="sensor_read",
        )

    def _api_request(
        self,
        method,
        path,
        operation=None,
        category=None,
        context: dict | None = None,
        **kwargs,
    ):
        """Make an API request to Home Assistant with retry logic.

        Args:
            method: HTTP method ('get', 'post', etc.)
            path: API path (without base URL)
            operation: Optional human-readable operation description for failure tracking
            category: Optional operation category for failure tracking
            context: Optional dict of contextual parameters for failure diagnostics
            **kwargs: Additional arguments for requests

        Returns:
            Response data from API

        Raises:
            requests.RequestException: If all retries fail

        """
        # List of operations that modify state (write operations)
        write_operations = [
            ("post", "/api/services/growatt_server/update_tlx_inverter_time_segment"),
            ("post", "/api/services/switch/turn_on"),
            ("post", "/api/services/switch/turn_off"),
            ("post", "/api/services/number/set_value"),
        ]

        # Check if this is a write operation and we're in test mode
        is_write_operation = (method.lower(), path) in write_operations

        # Test mode only blocks write operations, never read operations
        if self.test_mode and is_write_operation:
            logger.info(
                "[TEST MODE] Would call %s %s with args: %s",
                method.upper(),
                path,
                kwargs.get("json", {}),
            )
            return None

        url = f"{self.base_url}{path}"
        logger.debug("Making API request to %s %s", method.upper(), url)
        for attempt in range(self.max_attempts):
            try:
                http_method = getattr(self.session, method.lower())

                # Use the environment-aware request function with session (connection pooling)
                response = run_request(http_method, url=url, timeout=30, **kwargs)

                # Raise an exception if the response status is an error
                response.raise_for_status()

                # Only try to parse JSON if there's content
                if (
                    response.content
                    and response.headers.get("content-type") == "application/json"
                ):
                    return response.json()
                return None

            except requests.RequestException as e:
                # Don't retry on 404 (sensor not found) - fail fast for missing sensors
                if (
                    hasattr(e, "response")
                    and e.response is not None
                    and e.response.status_code == 404
                ):
                    logger.error(
                        "API request to %s failed: Sensor not found (404). This indicates a missing or misconfigured sensor.",
                        url,
                    )
                    raise  # Fail immediately on 404

                if attempt < self.max_attempts - 1:  # Not the last attempt
                    delay = self.retry_base_delay * (2**attempt)
                    logger.warning(
                        "API request to %s failed on attempt %d/%d: %s. Retrying in %d seconds...",
                        url,
                        attempt + 1,
                        self.max_attempts,
                        str(e),
                        delay,
                    )
                    time.sleep(delay)
                else:  # Last attempt failed
                    logger.error(
                        "API request to %s failed on final attempt %d/%d: %s",
                        path,
                        attempt + 1,
                        self.max_attempts,
                        str(e),
                    )

                    # Record runtime failure if failure tracker is available
                    if self.failure_tracker:
                        # Use provided operation/category or fall back to generic description
                        operation_description = operation or f"{method.upper()} {path}"
                        operation_category = category or "other"

                        # Enrich context with HTTP response body for diagnostics
                        enriched_context = dict(context) if context else {}
                        if isinstance(e, requests.HTTPError) and e.response is not None:
                            response_body = e.response.text[:500]
                            if response_body:
                                enriched_context["response_body"] = response_body

                        self.failure_tracker.record_failure_once(
                            operation=operation_description,
                            category=operation_category,
                            error=e,
                            context=enriched_context if enriched_context else None,
                        )

                    raise  # Re-raise the last exception

    def _service_call_with_retry(
        self, service_domain, service_name, operation: str | None = None, **kwargs
    ):
        """Call Home Assistant service with retry logic.

        Args:
            service_domain: Service domain (e.g., 'switch', 'number')
            service_name: Service name (e.g., 'turn_on', 'set_value')
            operation: Optional human-readable operation description for failure tracking
            **kwargs: Service parameters

        Returns:
            Response from service call or None

        """
        # List of read-only operations that are safe to execute in test mode
        # In test mode, we block ALL operations EXCEPT these safe reads
        safe_read_operations = [
            ("growatt_server", "read_time_segments"),
            ("growatt_server", "read_ac_charge_times"),
            ("growatt_server", "read_ac_discharge_times"),
            ("nordpool", "get_prices_for_date"),
        ]

        is_safe_read = (service_domain, service_name) in safe_read_operations

        # Test mode blocks ALL operations except safe reads (deny by default)
        if self.test_mode and not is_safe_read:
            logger.info(
                "[TEST MODE] Would call service %s.%s with args: %s",
                service_domain,
                service_name,
                kwargs,
            )
            return None

        # Prepare API call parameters
        path = f"/api/services/{service_domain}/{service_name}"
        json_data = kwargs.copy()

        # Add return_response query parameter for read operations
        query_params = {}
        if json_data.pop("return_response", is_safe_read):
            query_params["return_response"] = "true"

        # Remove 'blocking' from payload
        json_data.pop("blocking", True)

        # Modify URL to include query parameters if needed
        if query_params:
            path += "?" + urllib.parse.urlencode(query_params)

        # Build context from service call kwargs for failure tracking
        context = {
            k: v for k, v in kwargs.items() if k not in ("return_response", "blocking")
        }

        # Make API call
        return self._api_request(
            "post",
            path,
            operation=operation or f"Call {service_domain}.{service_name}",
            category=(
                "battery_control"
                if service_domain in ["number", "switch"]
                else (
                    "inverter_control"
                    if service_domain == "growatt_server"
                    else "other"
                )
            ),
            context=context,
            json=json_data,
        )

    def _get_raw_state(self, sensor_name: str) -> str | None:
        """Get raw state string from HA. Returns None if not configured or unavailable."""
        try:
            entity_id, resolution_method = self._resolve_entity_id(sensor_name)
            logger.debug(
                "Resolving sensor '%s' to entity '%s' (method: %s)",
                sensor_name,
                entity_id,
                resolution_method,
            )
        except ValueError:
            logger.debug(
                "Could not get value for %s: sensor not configured", sensor_name
            )
            return None

        try:
            failure_category = f"sensor_read:{sensor_name}"
            response = self._api_request(
                "get",
                f"/api/states/{entity_id}",
                operation=f"Read sensor '{sensor_name}'",
                category=failure_category,
            )
            if response and "state" in response:
                state = response["state"]
                if isinstance(state, str) and state in ("unavailable", "unknown"):
                    logger.warning(
                        "Sensor %s (entity_id: %s) is %s",
                        sensor_name,
                        entity_id,
                        state,
                    )
                    return None
                # Sensor read succeeded — auto-dismiss any prior failure
                if self.failure_tracker:
                    self.failure_tracker.dismiss_by_category(failure_category)
                return str(state)
            logger.warning(
                "Sensor %s (entity_id: %s) returned invalid response or no state",
                sensor_name,
                entity_id,
            )
            return None
        except requests.RequestException as e:
            logger.error("Error fetching sensor %s: %s", sensor_name, str(e))
            # Note: failure is already recorded by _api_request() — don't
            # duplicate the record_failure call here.
            return None

    def _get_sensor_value(self, sensor_name) -> float | None:
        """Get value from any sensor by name using unified entity resolution.

        Returns:
            float: The sensor value, or None if the sensor is unavailable,
            unknown, or could not be read.
        """
        raw = self._get_raw_state(sensor_name)
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            logger.warning("Could not convert value for %s: %s", sensor_name, raw)
            return None

    def _get_binary_state(self, sensor_name: str) -> bool | None:
        """Get binary sensor state. Returns None if not configured or unavailable."""
        raw = self._get_raw_state(sensor_name)
        if raw is None:
            return None
        return raw == "on"

    def get_discharge_inhibit_active(self) -> bool:
        """Check if discharge inhibit is active. Returns False when not configured or unavailable."""
        if not self.sensors.get("discharge_inhibit"):
            return False
        result = self._get_binary_state("discharge_inhibit")
        return result is True

    def get_estimated_consumption(self):
        """Get estimated consumption in quarterly resolution (96 periods).

        Returns consumption forecast for a full day in 15-minute periods.
        Upscales from hourly average by dividing by 4.

        Returns:
            list[float]: 96 quarterly consumption values in kWh per quarter-hour

        Raises:
            SystemConfigurationError: If sensor data is unavailable
        """
        raw_value = self._get_sensor_value("48h_avg_grid_import")
        assert raw_value is not None, "48h_avg_grid_import sensor not available"
        avg_hourly_consumption = raw_value / 1000

        # Convert hourly average to quarterly by dividing by 4
        # E.g., 4.0 kWh/hour = 1.0 kWh per 15-minute period
        quarterly_consumption = avg_hourly_consumption / 4.0

        # Return 96 quarterly periods (24 hours * 4 quarters per hour)
        return [quarterly_consumption] * 96

    def get_ha_config(self) -> dict:
        """Fetch Home Assistant configuration (timezone, location, etc.)."""
        response = self._api_request(
            "get",
            "/api/config",
            operation="Read HA config",
            category="config",
        )
        assert response is not None, "HA /api/config returned no data"
        return response

    def get_battery_soc(self):
        """Get the battery state of charge (SOC)."""
        return self._get_sensor_value("battery_soc")

    def get_charge_stop_soc(self):
        """Get the charge stop state of charge (SOC)."""
        return self._get_sensor_value("battery_charge_stop_soc")

    def set_charge_stop_soc(self, charge_stop_soc):
        """Set the charge stop state of charge (SOC)."""
        entity_id = self._get_entity_for_service("battery_charge_stop_soc")
        self._service_call_with_retry(
            "number",
            "set_value",
            operation="Set charge stop SOC",
            entity_id=entity_id,
            value=charge_stop_soc,
        )

    def get_discharge_stop_soc(self):
        """Get the discharge stop state of charge (SOC)."""
        return self._get_sensor_value("battery_discharge_stop_soc")

    def set_discharge_stop_soc(self, discharge_stop_soc):
        """Set the discharge stop state of charge (SOC)."""
        entity_id = self._get_entity_for_service("battery_discharge_stop_soc")
        self._service_call_with_retry(
            "number",
            "set_value",
            operation="Set discharge stop SOC",
            entity_id=entity_id,
            value=discharge_stop_soc,
        )

    def get_charging_power_rate(self):
        """Get the charging power rate."""
        return self._get_sensor_value("battery_charging_power_rate")

    def set_charging_power_rate(self, rate):
        """Set the charging power rate."""
        entity_id = self._get_entity_for_service("battery_charging_power_rate")
        self._service_call_with_retry(
            "number",
            "set_value",
            operation="Set charging power rate",
            entity_id=entity_id,
            value=rate,
        )

    def get_discharging_power_rate(self):
        """Get the discharging power rate."""
        return self._get_sensor_value("battery_discharging_power_rate")

    def set_discharging_power_rate(self, rate):
        """Set the discharging power rate."""
        entity_id = self._get_entity_for_service("battery_discharging_power_rate")
        self._service_call_with_retry(
            "number",
            "set_value",
            operation="Set discharging power rate",
            entity_id=entity_id,
            value=rate,
        )

    def get_battery_charge_power(self):
        """Get current battery charging power in watts."""
        return self._get_sensor_value("battery_charge_power")

    def get_battery_discharge_power(self):
        """Get current battery discharging power in watts."""
        return self._get_sensor_value("battery_discharge_power")

    def set_grid_charge(self, enable):
        """Enable or disable grid charging.

        Supports both switch entities (growatt_server: on/off) and select
        entities (solax_modbus: Enabled/Disabled).  The entity domain is
        detected from the configured entity_id prefix.
        """
        entity_id = self._get_entity_for_service("grid_charge")

        if enable:
            logger.info("Enabling grid charge")
        else:
            logger.info("Disabling grid charge")

        operation = "Enable grid charge" if enable else "Disable grid charge"

        if entity_id.startswith("select."):
            self._service_call_with_retry(
                "select",
                "select_option",
                operation=operation,
                entity_id=entity_id,
                option="Enabled" if enable else "Disabled",
            )
        else:
            service = "turn_on" if enable else "turn_off"
            self._service_call_with_retry(
                "switch",
                service,
                operation=operation,
                entity_id=entity_id,
            )

    def grid_charge_enabled(self):
        """Return True if grid charging is enabled.

        Handles both switch entities (state ``"on"``) and select entities
        (state ``"Enabled"``).
        """
        try:
            entity_id = self._get_entity_for_service("grid_charge")
            response = self._api_request(
                "get",
                f"/api/states/{entity_id}",
                operation="Check grid charge state",
                category="sensor_read",
            )
            if response and "state" in response:
                state = response["state"]
                if entity_id.startswith("select."):
                    return state == "Enabled"
                return state == "on"
            return False
        except ValueError as e:
            logger.warning(str(e))
            return False

    def set_inverter_time_segment(
        self,
        segment_id: int,
        batt_mode: str,
        start_time: str,
        end_time: str,
        enabled: bool,
    ) -> None:
        """Set the inverter time segment.

        Args:
            segment_id: Segment number (1-10)
            batt_mode: Battery mode ("load_first", "battery_first", or "grid_first")
            start_time: Start time in "HH:MM" format
            end_time: End time in "HH:MM" format
            enabled: Whether the segment is enabled
        """
        # Prepare service call parameters
        service_params = {
            "segment_id": segment_id,
            "batt_mode": batt_mode,
            "start_time": start_time,
            "end_time": end_time,
            "enabled": enabled,
        }

        # Add device_id if configured
        if self.growatt_device_id:
            service_params["device_id"] = self.growatt_device_id
        else:
            logger.warning(
                "No Growatt device_id configured. TOU segment write may fail. "
                "Please add growatt.device_id to config.yaml"
            )

        enabled_str = "enabled" if enabled else "disabled"
        self._service_call_with_retry(
            "growatt_server",
            "update_time_segment",
            operation=f"Write TOU segment {segment_id}: {batt_mode} {start_time}-{end_time} ({enabled_str})",
            **service_params,
        )

    def read_inverter_time_segments(self):
        """Read all time segments from the inverter with retry logic."""
        try:
            # Prepare service call parameters
            service_params: dict[str, str | bool] = {"return_response": True}

            # Require device_id before attempting the API call
            if not self.growatt_device_id:
                raise SystemConfigurationError(
                    "Growatt device_id not configured. Run the setup wizard to configure the inverter."
                )

            service_params["device_id"] = self.growatt_device_id

            # Call the service and get the response
            result = self._service_call_with_retry(
                "growatt_server",
                "read_time_segments",
                operation=None,
                **service_params,
            )

            # Check if the result contains 'service_response' with 'time_segments'
            if result and "service_response" in result:
                service_response = result["service_response"]
                if "time_segments" in service_response:
                    return service_response["time_segments"]

            # If the result doesn't match expected format, log and return empty list
            logger.warning("Unexpected response format from read_time_segments")
            return []

        except (requests.RequestException, ValueError, KeyError) as e:
            logger.warning("Failed to read time segments: %s", str(e))
            return []

    # ── solax_modbus entity-based TOU segment control (Growatt plugin) ────

    # Maps BESS internal batt_mode to solax_modbus select option strings
    _MODBUS_MODE_OPTIONS: ClassVar[dict[str, str]] = {
        "battery_first": "Battery First",
        "load_first": "Load First",
        "grid_first": "Grid First",
    }

    def set_tou_segment_via_entities(
        self,
        segment_id: int,
        batt_mode: str,
        start_time: str,
        end_time: str,
        enabled: bool,
    ) -> None:
        """Write a TOU segment via solax_modbus entity writes.

        Uses select.select_option for mode/time/enabled, then button.press
        to commit the slot to the inverter.

        The enabled entity's plugin key is ``time_N_enabled`` (used in
        unique_id and BESS sensor key) while its HA entity_id contains
        ``time_N_active`` (from the display name "Time N Active"). The
        option values are "Enabled"/"Disabled" regardless.

        Args:
            segment_id: Slot number (1-9)
            batt_mode: Battery mode ("load_first", "battery_first", "grid_first")
            start_time: Start time "HH:MM"
            end_time: End time "HH:MM"
            enabled: Whether the segment is active
        """
        prefix = f"tou_time_{segment_id}"

        mode_option = self._MODBUS_MODE_OPTIONS[batt_mode]
        enabled_option = "Enabled" if enabled else "Disabled"

        # Set all 4 select entities before pressing update
        entity_writes = [
            (f"{prefix}_enabled", enabled_option),
            (f"{prefix}_begin", start_time),
            (f"{prefix}_end", end_time),
            (f"{prefix}_mode", mode_option),
        ]

        for sensor_key, option in entity_writes:
            entity_id = self._get_entity_for_service(sensor_key)
            self._service_call_with_retry(
                "select",
                "select_option",
                operation=f"TOU slot {segment_id} set {sensor_key}={option}",
                entity_id=entity_id,
                option=option,
            )

        # Press update button to commit the slot to inverter
        update_entity_id = self._get_entity_for_service(f"{prefix}_update")
        self._service_call_with_retry(
            "button",
            "press",
            operation=f"TOU slot {segment_id} commit",
            entity_id=update_entity_id,
        )

    def read_tou_segments_from_entities(self) -> list[dict]:
        """Read all 9 TOU segments from solax_modbus entity states.

        Returns list of segment dicts in the same format as
        read_inverter_time_segments() for compatibility with
        initialize_from_tou_segments().
        """
        # Reverse mode mapping: "Battery First" -> "battery_first"
        mode_reverse = {v: k for k, v in self._MODBUS_MODE_OPTIONS.items()}

        segments: list[dict] = []
        for slot in range(1, 10):
            prefix = f"tou_time_{slot}"
            try:
                enabled_id = self._get_entity_for_service(f"{prefix}_enabled")
                begin_id = self._get_entity_for_service(f"{prefix}_begin")
                end_id = self._get_entity_for_service(f"{prefix}_end")
                mode_id = self._get_entity_for_service(f"{prefix}_mode")
            except ValueError:
                logger.debug("TOU slot %d entities not configured, skipping", slot)
                continue

            try:
                enabled_state = self._api_request("get", f"/api/states/{enabled_id}")
                begin_state = self._api_request("get", f"/api/states/{begin_id}")
                end_state = self._api_request("get", f"/api/states/{end_id}")
                mode_state = self._api_request("get", f"/api/states/{mode_id}")

                enabled_val = enabled_state.get("state", "Disabled")
                batt_mode = mode_reverse.get(
                    mode_state.get("state", "Load First"), "load_first"
                )

                segments.append(
                    {
                        "segment_id": slot,
                        "start_time": begin_state.get("state", "00:00"),
                        "end_time": end_state.get("state", "00:00"),
                        "batt_mode": batt_mode,
                        "enabled": enabled_val == "Enabled",
                    }
                )
            except Exception as e:
                logger.warning("Failed to read TOU slot %d: %s", slot, e)

        return segments

    def write_ac_charge_times(
        self,
        charge_power: int,
        charge_stop_soc: int,
        mains_enabled: bool,
        **period_params: str | bool,
    ) -> None:
        """Write AC charge time periods to an SPH inverter.

        Args:
            charge_power: Charge power as a percentage (0-100)
            charge_stop_soc: SOC percentage at which to stop charging
            mains_enabled: Whether AC (mains) charging is enabled
            **period_params: Flat period parameters, e.g. period_1_start, period_1_end,
                period_1_enabled, period_2_start, ... (up to period_3_*)
        """
        service_params: dict[str, str | int | bool] = {
            "charge_power": charge_power,
            "charge_stop_soc": charge_stop_soc,
            "mains_enabled": mains_enabled,
        }
        service_params.update(period_params)

        if self.growatt_device_id:
            service_params["device_id"] = self.growatt_device_id
        else:
            logger.warning(
                "No Growatt device_id configured. write_ac_charge_times may fail. "
                "Please add growatt.device_id to config.yaml"
            )

        self._service_call_with_retry(
            "growatt_server", "write_ac_charge_times", None, **service_params
        )

    def read_ac_charge_times(self) -> dict:
        """Read current AC charge time periods from an SPH inverter.

        Returns:
            Dict with keys: charge_power, charge_stop_soc, mains_enabled, periods (list)
        """
        try:
            service_params: dict[str, str | bool] = {"return_response": True}

            if self.growatt_device_id:
                service_params["device_id"] = self.growatt_device_id
            else:
                logger.warning(
                    "No Growatt device_id configured. read_ac_charge_times may fail. "
                    "Please add growatt.device_id to config.yaml"
                )

            result = self._service_call_with_retry(
                "growatt_server", "read_ac_charge_times", None, **service_params
            )

            if result and "service_response" in result:
                return result["service_response"]

            logger.warning("Unexpected response format from read_ac_charge_times")
            return {}

        except (requests.RequestException, ValueError, KeyError) as e:
            logger.warning("Failed to read AC charge times: %s", str(e))
            return {}

    def write_ac_discharge_times(
        self,
        discharge_power: int,
        discharge_stop_soc: int,
        **period_params: str | bool,
    ) -> None:
        """Write AC discharge time periods to an SPH inverter.

        Args:
            discharge_power: Discharge power as a percentage (0-100)
            discharge_stop_soc: SOC percentage at which to stop discharging
            **period_params: Flat period parameters, e.g. period_1_start, period_1_end,
                period_1_enabled, period_2_start, ... (up to period_3_*)
        """
        service_params: dict[str, str | int | bool] = {
            "discharge_power": discharge_power,
            "discharge_stop_soc": discharge_stop_soc,
        }
        service_params.update(period_params)

        if self.growatt_device_id:
            service_params["device_id"] = self.growatt_device_id
        else:
            logger.warning(
                "No Growatt device_id configured. write_ac_discharge_times may fail. "
                "Please add growatt.device_id to config.yaml"
            )

        self._service_call_with_retry(
            "growatt_server", "write_ac_discharge_times", None, **service_params
        )

    def read_ac_discharge_times(self) -> dict:
        """Read current AC discharge time periods from an SPH inverter.

        Returns:
            Dict with keys: discharge_power, discharge_stop_soc, periods (list)
        """
        try:
            service_params: dict[str, str | bool] = {"return_response": True}

            if self.growatt_device_id:
                service_params["device_id"] = self.growatt_device_id
            else:
                logger.warning(
                    "No Growatt device_id configured. read_ac_discharge_times may fail. "
                    "Please add growatt.device_id to config.yaml"
                )

            result = self._service_call_with_retry(
                "growatt_server", "read_ac_discharge_times", None, **service_params
            )

            if result and "service_response" in result:
                return result["service_response"]

            logger.warning("Unexpected response format from read_ac_discharge_times")
            return {}

        except (requests.RequestException, ValueError, KeyError) as e:
            logger.warning("Failed to read AC discharge times: %s", str(e))
            return {}

    # ── SolaX VPP control ─────────────────────────────────────────────────────

    def set_solax_active_power_control(self, watts: int) -> None:
        """Issue a SolaX VPP active-power command.

        Enables battery control mode, sets the active power target, arms
        autorepeat for 1 200 s (covers a 15-min period with margin), then
        triggers the command.

        Args:
            watts: Target power in watts.  Positive = charge, negative = discharge.
        """
        mode_entity = self._get_entity_for_service("solax_power_control_mode")
        power_entity = self._get_entity_for_service("solax_active_power")
        repeat_entity = self._get_entity_for_service("solax_autorepeat_duration")
        trigger_entity = self._get_entity_for_service("solax_power_control_trigger")

        logger.info("SolaX VPP: enabling battery control, power=%d W", watts)

        self._service_call_with_retry(
            "select",
            "select_option",
            operation="SolaX VPP enable battery control",
            entity_id=mode_entity,
            option="Enabled Battery Control",
        )
        self._service_call_with_retry(
            "number",
            "set_value",
            operation="SolaX VPP set active power",
            entity_id=power_entity,
            value=watts,
        )
        self._service_call_with_retry(
            "number",
            "set_value",
            operation="SolaX VPP set autorepeat duration",
            entity_id=repeat_entity,
            value=1200,
        )
        self._service_call_with_retry(
            "button",
            "press",
            operation="SolaX VPP trigger",
            entity_id=trigger_entity,
        )

    def set_solax_vpp_disabled(self) -> None:
        """Disable SolaX VPP mode, reverting the inverter to self-use behaviour.

        Used for IDLE and SOLAR_STORAGE intents where the inverter's default
        self-use logic should take over.  Autorepeat on previous commands
        expires naturally; this call cancels active control explicitly.
        """
        mode_entity = self._get_entity_for_service("solax_power_control_mode")

        logger.info("SolaX VPP: disabling battery control (self-use mode)")

        self._service_call_with_retry(
            "select",
            "select_option",
            operation="SolaX VPP disable battery control",
            entity_id=mode_entity,
            option="Disabled",
        )

    def set_solax_min_soc(self, min_soc: int) -> None:
        """Write the battery minimum SOC to the SolaX inverter.

        Args:
            min_soc: Minimum state-of-charge in percent (0-100).
        """
        entity_id = self._get_entity_for_service("solax_battery_min_soc")
        logger.info("SolaX: setting battery minimum SOC to %d%%", min_soc)
        self._service_call_with_retry(
            "number",
            "set_value",
            operation="SolaX set battery minimum SOC",
            entity_id=entity_id,
            value=min_soc,
        )

    def get_solax_power_control_mode(self) -> str | None:
        """Read the current SolaX power control mode."""
        return self._get_raw_state("solax_power_control_mode")

    # ─────────────────────────────────────────────────────────────────────────

    def set_test_mode(self, enabled):
        """Enable or disable test mode."""
        self.test_mode = enabled
        logger.info("%s test mode", "Enabled" if enabled else "Disabled")

    def get_l1_current(self):
        """Get the current load for L1."""
        return self._get_sensor_value("current_l1")

    def get_l2_current(self):
        """Get the current load for L2."""
        return self._get_sensor_value("current_l2")

    def get_l3_current(self):
        """Get the current load for L3."""
        return self._get_sensor_value("current_l3")

    def _parse_solar_forecast(self, sensor_key: str) -> list[float]:
        """Fetch and parse Solcast detailedHourly data into 96 quarterly values.

        Args:
            sensor_key: The sensor key to look up in the sensors mapping.

        Returns:
            list[float]: 96 quarterly solar production values in kWh per quarter-hour.

        Raises:
            SystemConfigurationError: If sensor is not configured or data unavailable.
        """
        entity_id = self.sensors.get(sensor_key)
        if not entity_id:
            raise SystemConfigurationError(
                f"Solar forecast sensor '{sensor_key}' not configured in sensors mapping"
            )

        response = self._api_request(
            "get",
            f"/api/states/{entity_id}",
            operation="Get solar forecast data",
            category="sensor_read",
        )

        if not response or "attributes" not in response:
            raise SystemConfigurationError(
                f"No attributes found for solar forecast sensor {entity_id}"
            )

        attributes = response["attributes"]
        hourly_data = attributes.get("detailedHourly")

        if not hourly_data:
            raise SystemConfigurationError(
                f"No hourly data found in solar forecast sensor {entity_id}"
            )

        # Parse hourly values from Solcast
        hourly_values = [0.0] * 24
        pv_field = "pv_estimate"

        for entry in hourly_data:
            # Handle period_start
            period_start = entry["period_start"]

            # If period_start is a string, parse the hour
            if isinstance(period_start, str):
                hour = int(period_start.split("T")[1].split(":")[0])
            else:
                # Assume it's already a datetime object
                hour = period_start.hour

            hourly_values[hour] = float(entry[pv_field])

        # Convert hourly to quarterly resolution
        # Each hourly value is divided by 4 to get per-quarter-hour energy
        quarterly_values = []
        for hourly_value in hourly_values:
            quarter_value = hourly_value / 4.0
            quarterly_values.extend([quarter_value] * 4)

        return quarterly_values

    def get_solar_forecast(self):
        """Get solar forecast data in quarterly resolution (96 periods).

        Fetches hourly solar forecast from Solcast integration and upscales to
        15-minute resolution by dividing each hourly value by 4.

        Returns:
            list[float]: 96 quarterly solar production values in kWh per quarter-hour

        Raises:
            SystemConfigurationError: If solar forecast sensor is not configured or unavailable
        """
        return self._parse_solar_forecast("solar_forecast_today")

    def get_solar_forecast_tomorrow(self) -> list[float]:
        """Get tomorrow's solar forecast in quarterly resolution (96 periods).

        Fetches hourly solar forecast for tomorrow from Solcast integration
        and upscales to 15-minute resolution.

        Returns:
            list[float]: 96 quarterly solar production values in kWh per quarter-hour

        Raises:
            SystemConfigurationError: If solar forecast sensor is not configured or unavailable
        """
        return self._parse_solar_forecast("solar_forecast_tomorrow")

    def get_sensor_data(self, sensors_list):
        """Get current sensor data via Home Assistant REST API.

        Note: This method only provides current sensor states, not historical data.
        Historical data is handled by InfluxDB integration in sensor_collector.py.

        Args:
            sensors_list: List of sensor names to fetch

        Returns:
            Dictionary with current sensor data in the same format as influxdb_helper
        """
        # Initialize result with proper format
        result = {"status": "success", "data": {}}

        try:
            # For each sensor in the list, get the current state
            for sensor in sensors_list:
                # Use unified entity resolution - require explicit configuration
                entity_id, _ = self._resolve_entity_id(sensor)

                # Get sensor state
                response = self._api_request(
                    "get",
                    f"/api/states/{entity_id}",
                    operation=f"Get sensor data for '{sensor}'",
                    category="sensor_read",
                )
                if response and "state" in response:
                    try:
                        # Store the value, converting to float for numeric sensors
                        value = float(response["state"])
                        result["data"][sensor] = value
                    except (ValueError, TypeError):
                        # For non-numeric states, store as is
                        result["data"][sensor] = response["state"]
                        logger.warning(
                            "Non-numeric state for sensor %s: %s",
                            sensor,
                            response["state"],
                        )

            # Check if we got any data
            if not result["data"]:
                result["status"] = "error"
                result["message"] = "No sensor data available"

            return result

        except (requests.RequestException, ValueError, KeyError) as e:
            logger.error("Error fetching sensor data: %s", str(e))
            return {"status": "error", "message": str(e)}

    def get_pv_power(self):
        """Get current solar PV power production in watts."""
        return self._get_sensor_value("pv_power")

    def get_import_power(self):
        """Get current grid import power in watts."""
        return self._get_sensor_value("import_power")

    def get_export_power(self):
        """Get current grid export power in watts."""
        return self._get_sensor_value("export_power")

    def get_local_load_power(self):
        """Get current home load power in watts."""
        return self._get_sensor_value("local_load_power")

    def get_net_battery_power(self):
        """Get net battery power (positive = charging, negative = discharging) in watts."""
        charge = self.get_battery_charge_power()
        discharge = self.get_battery_discharge_power()
        if charge is None or discharge is None:
            return None
        return charge - discharge

    # Lifetime energy sensors (used by energy monitoring health checks)
    def get_battery_charged_lifetime(self):
        """Get lifetime total battery charged energy in kWh."""
        return self._get_sensor_value("lifetime_battery_charged")

    def get_battery_discharged_lifetime(self):
        """Get lifetime total battery discharged energy in kWh."""
        return self._get_sensor_value("lifetime_battery_discharged")

    def get_solar_production_lifetime(self):
        """Get lifetime total solar energy production in kWh."""
        return self._get_sensor_value("lifetime_solar_energy")

    def get_grid_import_lifetime(self):
        """Get lifetime total grid import energy in kWh."""
        return self._get_sensor_value("lifetime_import_from_grid")

    def get_grid_export_lifetime(self):
        """Get lifetime total grid export energy in kWh."""
        return self._get_sensor_value("lifetime_export_to_grid")

    def get_load_consumption_lifetime(self):
        """Get lifetime total load consumption energy in kWh.

        If no direct sensor is configured (e.g. GEN4 Growatt inverters lack a
        native load consumption register), derives the value from:
            load = solar + grid_import - grid_export
        """
        direct = self._get_sensor_value("lifetime_load_consumption")
        if direct is not None:
            return direct

        # Derive from other lifetime sensors when direct sensor unavailable
        solar = self._get_sensor_value("lifetime_solar_energy")
        grid_import = self._get_sensor_value("lifetime_import_from_grid")
        grid_export = self._get_sensor_value("lifetime_export_to_grid")
        if solar is not None and grid_import is not None and grid_export is not None:
            derived = solar + grid_import - grid_export
            return max(derived, 0.0)  # Guard against small negative rounding
        return None

    def get_system_production_lifetime(self):
        """Get lifetime total system production energy in kWh.

        If no direct sensor is configured (e.g. GEN3 Growatt inverters lack
        a ``total_yield`` register), falls back to ``lifetime_solar_energy``.
        """
        direct = self._get_sensor_value("lifetime_system_production")
        if direct is not None:
            return direct
        return self._get_sensor_value("lifetime_solar_energy")

    def get_self_consumption_lifetime(self):
        """Get lifetime total self consumption energy in kWh."""
        return self._get_sensor_value("lifetime_self_consumption")

    def _ws_query(self, commands: list[dict]) -> list[dict]:
        """Execute WebSocket API commands against Home Assistant.

        Connects to the HA WebSocket API, authenticates, sends each command
        sequentially, and returns the corresponding results.

        The WebSocket API provides access to registries (entity, device, config
        entries) that are not available through the REST API.

        Args:
            commands: List of WebSocket command dicts (each must have 'type').
                      The 'id' field is added automatically.

        Returns:
            List of result dicts, one per command, in the same order.
        """
        ws_url = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = ws_url.rstrip("/") + "/api/websocket"

        sslopt = {}
        if ws_url.startswith("wss://"):
            sslopt = {"cert_reqs": ssl.CERT_REQUIRED}

        ws = websocket.create_connection(ws_url, sslopt=sslopt, timeout=15)
        try:
            # Phase 1: Authentication
            auth_required = json.loads(ws.recv())
            if auth_required.get("type") != "auth_required":
                raise RuntimeError(
                    f"Expected auth_required, got {auth_required.get('type')}"
                )

            ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth_result = json.loads(ws.recv())
            if auth_result.get("type") != "auth_ok":
                raise RuntimeError(f"WebSocket authentication failed: {auth_result}")

            # Phase 2: Send commands and collect results
            results: list[dict] = []
            for idx, cmd in enumerate(commands, start=1):
                msg = dict(cmd)
                msg["id"] = idx
                ws.send(json.dumps(msg))
                response = json.loads(ws.recv())
                if not response.get("success"):
                    raise RuntimeError(
                        f"WS command {cmd['type']} failed: {response.get('error')}"
                    )
                results.append(response["result"])

            return results
        finally:
            ws.close()

    def get_statistics_during_period(
        self,
        statistic_ids: list[str],
        start_time: str,
        end_time: str | None = None,
        period: str = "hour",
        types: list[str] | None = None,
    ) -> dict[str, list[dict]]:
        """Query HA Recorder long-term/short-term statistics via WebSocket.

        Uses the recorder/statistics_during_period WebSocket command to fetch
        pre-aggregated statistics from Home Assistant's recorder database.

        Args:
            statistic_ids: Statistic IDs to query (typically entity_ids for
                HA-native sensors, e.g. ["sensor.load_consumption_total"]).
            start_time: ISO 8601 timestamp for range start.
            end_time: ISO 8601 timestamp for range end (None = now).
            period: Aggregation period — "5minute" or "hour".
            types: Statistics types to return. For total_increasing sensors
                (energy): ["change"]. For measurement sensors (power, SOC):
                ["mean"]. Defaults to ["change"].

        Returns:
            Dict keyed by statistic_id, each value a list of period dicts
            with keys like start, end, change, sum, mean depending on types.
        """
        cmd = {
            "type": "recorder/statistics_during_period",
            "start_time": start_time,
            "statistic_ids": statistic_ids,
            "period": period,
            "types": types or ["change"],
        }
        if end_time is not None:
            cmd["end_time"] = end_time

        results = self._ws_query([cmd])
        return results[0]

    def list_statistic_ids(
        self,
        statistic_type: str | None = None,
    ) -> list[dict]:
        """List all statistic IDs known to the HA Recorder.

        Useful for discovering the correct statistic_id for a given entity,
        since external integrations may use IDs that differ from entity_ids.

        Args:
            statistic_type: Optional filter — "mean" for measurement sensors,
                "sum" for total/total_increasing sensors.

        Returns:
            List of dicts with keys: statistic_id, display_unit_of_measurement,
            has_mean, has_sum, name, source, statistics_unit_of_measurement, etc.
        """
        cmd: dict = {"type": "recorder/list_statistic_ids"}
        if statistic_type is not None:
            cmd["statistic_type"] = statistic_type

        results = self._ws_query([cmd])
        return results[0]

    def find_statistic_id(self, entity_id: str) -> str | None:
        """Find the statistic_id that matches a given entity_id.

        HA-native entities use the entity_id as statistic_id, but external
        integrations may differ (e.g. ``sensor:entity`` vs ``sensor.entity``).
        This queries the recorder for an exact match only to avoid false
        positives from partial substring matches.

        Returns:
            The matching statistic_id, or None if not found.
        """
        all_stats = self.list_statistic_ids()
        for stat in all_stats:
            if stat.get("statistic_id") == entity_id:
                return entity_id
        return None

    def discover_ha_metadata(
        self,
        device_sn: str | None,
        entity_registry: list[dict] | None = None,
    ) -> dict:
        """Discover HA-internal IDs via the WebSocket API.

        Queries the config entry and device registries to find:
        - Nordpool config_entry_id (required for nordpool.get_prices_for_date)
        - Growatt device_id (HA device registry ID for service calls)

        Args:
            device_sn: Growatt device serial number to match, or None
            entity_registry: Pre-fetched entity registry list, or None to fetch.

        Returns:
            dict with keys: growatt_device_id, nordpool_config_entry_id
        """
        commands = [
            {"type": "config_entries/get"},
            {"type": "config/device_registry/list"},
        ]
        if entity_registry is None:
            commands.append({"type": "config/entity_registry/list"})

        results = self._ws_query(commands)
        config_entries_result = results[0]
        devices_result = results[1]
        entity_registry_result = (
            entity_registry if entity_registry is not None else results[2]
        )

        return self._parse_ha_metadata(
            device_sn, config_entries_result, devices_result, entity_registry_result
        )

    def _parse_ha_metadata(
        self,
        device_sn: str | None,
        config_entries_result: list[dict],
        devices_result: list[dict],
        entity_registry_result: list[dict],
    ) -> dict:
        """Parse config entries and device registry into BESS metadata.

        Pure parsing — no WebSocket calls.  Called by both
        ``discover_ha_metadata`` (standalone) and ``discover_integrations``
        (which fetches everything in a single WS connection).

        Returns:
            dict with keys: growatt_device_id, nordpool_config_entry_id,
            nordpool_area, detected_platforms, octopus_found
        """
        # Find nordpool config_entry_id from config entries.
        nordpool_config_entry_id: str | None = None
        octopus_found = False
        for entry in config_entries_result:
            if entry.get("domain") == "nordpool" and entry.get("state") == "loaded":
                nordpool_config_entry_id = entry["entry_id"]
            if (
                entry.get("domain") == "octopus_energy"
                and entry.get("state") == "loaded"
            ):
                octopus_found = True

        # Extract nordpool area from device registry identifiers.
        # The official HA nordpool integration creates a device with
        # identifiers [["nordpool", "SE3"]].  The HACS custom integration
        # uses long identifiers like [["nordpool", "nordpool_kwh_se2_sek_2_10_025"]].
        # We normalise both forms to a short area code (e.g. "SE2") using
        # the same regex that parses entity_ids.
        nordpool_area: str | None = None
        if nordpool_config_entry_id:
            for device in devices_result:
                if nordpool_config_entry_id in device.get("config_entries", []):
                    for ident in device.get("identifiers", []):
                        if (
                            isinstance(ident, (list, tuple))
                            and len(ident) == 2
                            and str(ident[0]).lower() == "nordpool"
                        ):
                            raw = str(ident[1])
                            nordpool_area = (
                                self._parse_nordpool_area_from_entity_id(raw)
                                or raw.upper()
                            )
                            break
                    if nordpool_area:
                        break

        # Find growatt config_entry_id for device matching
        growatt_config_entry_id: str | None = None
        for entry in config_entries_result:
            if (
                entry.get("domain") == "growatt_server"
                and entry.get("state") == "loaded"
            ):
                growatt_config_entry_id = entry["entry_id"]
                break

        # Find growatt device_id from device registry.
        # Strategy 1: match by identifiers containing the device SN
        #   (immutable, unaffected by user renames)
        # Strategy 2: match by config_entry belonging to growatt_server
        #   (works even without a detected SN)
        # Strategy 3: match by device name equal to device SN
        #   (legacy fallback)
        growatt_device_id: str | None = None
        if device_sn:
            sn_upper = device_sn.upper()
            for device in devices_result:
                for ident in device.get("identifiers", []):
                    if (
                        isinstance(ident, (list, tuple))
                        and len(ident) == 2
                        and str(ident[1]).upper() == sn_upper
                    ):
                        growatt_device_id = device["id"]
                        break
                if growatt_device_id:
                    break

        if not growatt_device_id and growatt_config_entry_id:
            for device in devices_result:
                if growatt_config_entry_id in device.get("config_entries", []):
                    growatt_device_id = device["id"]
                    break

        if not growatt_device_id and device_sn:
            sn_upper = device_sn.upper()
            for device in devices_result:
                name = str(device.get("name", "")).upper()
                if name == sn_upper:
                    growatt_device_id = device["id"]
                    break

        # Determine inverter type from entity registry unique_id prefixes.
        # The HA growatt_server integration uses different sensor key prefixes
        # depending on the Growatt Cloud device_type:
        #   "min"/"tlx" (AC-coupled) → sensors from tlx.py → unique_id "{SN}-tlx_*"
        #   "mix"       (DC-coupled) → sensors from mix.py → unique_id "{SN}-mix_*"
        #   "sph"       (DC-coupled) → sensors from sph.py → unique_id "{SN}-mix_*"/"{SN}-sph_*"
        # We check for "-tlx_" as the positive MIN signal.
        # Build detected_platforms list — all platforms we can identify from
        # the entity registry, independent of what the user has selected.
        detected_platforms: list[str] = []
        if growatt_config_entry_id:
            has_tlx = any(
                entry.get("platform") == "growatt_server"
                and "-tlx_" in str(entry.get("unique_id", ""))
                for entry in entity_registry_result
            )
            detected_platforms.append(
                "growatt_server_min" if has_tlx else "growatt_server_sph"
            )

        solax_config_entry = any(
            entry.get("domain") == "solax_modbus" and entry.get("state") == "loaded"
            for entry in config_entries_result
        )
        if solax_config_entry:
            if self._has_growatt_tou_entities(entity_registry_result):
                detected_platforms.append("solax_modbus_growatt_min")
            elif self._has_growatt_gen3_entities(entity_registry_result):
                detected_platforms.append("solax_modbus_growatt_sph")

        logger.info(
            "WS discovery: nordpool_config_entry_id=%s, nordpool_area=%s, "
            "growatt_device_id=%s, octopus_found=%s, "
            "detected_platforms=%s",
            nordpool_config_entry_id,
            nordpool_area,
            growatt_device_id,
            octopus_found,
            detected_platforms,
        )
        return {
            "growatt_device_id": growatt_device_id,
            "nordpool_config_entry_id": nordpool_config_entry_id,
            "nordpool_area": nordpool_area,
            "detected_platforms": detected_platforms,
            "octopus_found": octopus_found,
        }

    def _fetch_all_states(self) -> list[dict]:
        """Fetch all entity states from HA using the official REST API.

        GET /api/states is the only officially supported REST endpoint for
        entity discovery. This method is used by all discovery methods.

        Returns:
            List of state dicts from HA
        """
        states = self._api_request(
            "get",
            "/api/states",
            operation="Fetch all entity states",
            category="config",
        )
        assert states is not None, "HA /api/states returned no data"
        return states

    # Maps Nordpool area code prefix → (currency, vat_multiplier).
    # These are approximate defaults used to pre-fill the setup wizard;
    # users should verify and adjust for their actual tax situation.
    _AREA_HINTS: ClassVar[dict[str, tuple[str, float]]] = {
        "SE": ("SEK", 1.25),
        "NO": ("NOK", 1.25),
        "DK": ("DKK", 1.25),
        "FI": ("EUR", 1.24),
        "EE": ("EUR", 1.22),
        "LT": ("EUR", 1.21),
        "LV": ("EUR", 1.21),
        "GB": ("GBP", 1.0),
    }

    def _hints_from_nordpool_area(self, area: str | None) -> dict:
        """Return currency and VAT hints derived from the Nordpool price area."""
        if not area:
            return {}
        prefix = area[:2].upper()
        pair = self._AREA_HINTS.get(prefix)
        if pair is None:
            return {}
        currency, vat = pair
        return {"currency": currency, "vat_multiplier": vat}

    def discover_integrations(self) -> tuple[dict, list[dict]]:
        """Discover installed HA integrations relevant to BESS configuration.

        Uses three official HA APIs:
        - REST GET /api/config/entity_registry/list: platform-based integration
          detection and entity-to-sensor mapping (robust against entity renaming)
        - REST GET /api/states: live entity attributes (Nordpool area, phase counts)
        - WebSocket: config entries and device registry (config_entry_id, device_id)

        Returns:
            Tuple of (result_dict, states) where result_dict has keys:
            growatt_found, device_sn, growatt_device_id,
            nordpool_found, nordpool_area, nordpool_config_entry_id,
            octopus_found, detected_inverter_platforms,
            detected_phase_count, currency, vat_multiplier.
            states is the raw list from /api/states for reuse by callers.
        """
        result: dict = {
            "growatt_found": False,
            "device_sn": None,
            "growatt_device_id": None,
            "solax_found": False,
            "nordpool_found": False,
            "nordpool_area": None,
            "nordpool_custom_area": None,
            "nordpool_custom_entity": None,
            "nordpool_config_entry_id": None,
            "octopus_found": False,
            "entsoe_found": False,
            "entsoe_entity": None,
            # Auto-detected hints
            "detected_inverter_platforms": [],
            "detected_phase_count": None,
            "currency": None,
            "vat_multiplier": None,
        }

        # ── Single WebSocket connection for all registry queries ─────────
        # Previously this opened two separate WebSocket connections (one for
        # entity registry, one for config entries + devices).  If HA was still
        # starting, the second connection could fail even though the first
        # succeeded — silently losing nordpool_config_entry_id and area.
        # Now all commands go through one connection.  If it fails, we let
        # the exception propagate — partial discovery is worse than no
        # discovery because it silently produces incomplete configuration.
        metadata: dict = {}
        ws_commands = [
            {"type": "config/entity_registry/list"},
            {"type": "config_entries/get"},
            {"type": "config/device_registry/list"},
        ]
        ws_results = self._ws_query(ws_commands)
        registry = ws_results[0]
        config_entries = ws_results[1]
        devices = ws_results[2]

        inverter_detected = self.detect_inverter_integrations(registry)
        result["growatt_found"] = inverter_detected.get("growatt", False)
        result["solax_found"] = inverter_detected.get("solax", False)

        # ── States: Growatt device SN, Nordpool area ─────────────────────
        states = self._fetch_all_states()

        device_sn = self._extract_growatt_device_sn(states)
        if device_sn:
            result["growatt_found"] = True
            result["device_sn"] = device_sn

        for state in states:
            entity_id = str(state.get("entity_id", "")).lower()
            # HACS custom nordpool: sensor.nordpool_kwh_se3_sek_*
            # (Official HA nordpool is detected via config entries below)
            if entity_id.startswith("sensor.nordpool_"):
                result["nordpool_found"] = True
                if not result["nordpool_custom_entity"]:
                    result["nordpool_custom_entity"] = state.get("entity_id")
                if not result["nordpool_custom_area"]:
                    parsed_area = self._parse_nordpool_area_from_entity_id(entity_id)
                    if parsed_area:
                        result["nordpool_custom_area"] = parsed_area
            # Detect Octopus Energy from event entities
            if "octopus_energy" in entity_id and "rate" in entity_id:
                result["octopus_found"] = True

        # ── ENTSO-e Transparency Platform (e.g. Belpex) ───────────────────
        entsoe_entity = self.discover_entsoe_entity(registry, states)
        if entsoe_entity:
            result["entsoe_found"] = True
            result["entsoe_entity"] = entsoe_entity

        # ── Parse config entries + device registry ────────────────────────
        try:
            metadata = self._parse_ha_metadata(
                device_sn, config_entries, devices, registry
            )
            result["growatt_device_id"] = metadata["growatt_device_id"]
            result["nordpool_config_entry_id"] = metadata["nordpool_config_entry_id"]
            if metadata["nordpool_config_entry_id"]:
                result["nordpool_found"] = True
                if metadata.get("nordpool_area"):
                    result["nordpool_area"] = metadata["nordpool_area"]
            if metadata.get("octopus_found"):
                result["octopus_found"] = True
        except Exception as e:
            logger.warning("Failed to parse config entries / device registry: %s", e)

        # ── Auto-detected hints ───────────────────────────────────────────
        # Build a list of all detected platforms — no magic selection.
        # The frontend picks the platform; the backend just reports what's
        # available.
        # Start from WS-detected inverter platforms (growatt cloud + solax modbus growatt)
        detected: list[str] = list(metadata.get("detected_platforms", []))
        if result["solax_found"]:
            has_tou = self._has_growatt_tou_entities(registry)
            has_gen3 = self._has_growatt_gen3_entities(registry)
            result["solax_has_growatt_tou"] = has_tou
            result["solax_has_growatt_gen3"] = has_gen3
            # Only add solax platforms not already detected by _parse_ha_metadata
            if has_tou and "solax_modbus_growatt_min" not in detected:
                detected.append("solax_modbus_growatt_min")
            elif has_gen3 and "solax_modbus_growatt_sph" not in detected:
                detected.append("solax_modbus_growatt_sph")
            elif self._has_solax_native_entities(registry):
                detected.append("solax_modbus_native")
        result["detected_inverter_platforms"] = detected

        # Currency & VAT from Nordpool area or Octopus defaults
        area_hints = self._hints_from_nordpool_area(
            result.get("nordpool_area") or result.get("nordpool_custom_area")
        )
        if area_hints:
            result["currency"] = area_hints.get("currency")
            result["vat_multiplier"] = area_hints.get("vat_multiplier")
        elif result["octopus_found"] and not result["nordpool_found"]:
            result["currency"] = "GBP"
            result["vat_multiplier"] = 1.0
        elif result["entsoe_found"] and not result["nordpool_found"]:
            # ENTSO-e Transparency Platform reports all areas in EUR (const.py).
            # VAT varies per country, so leave vat_multiplier for the user.
            result["currency"] = "EUR"

        return result, states

    def _parse_nordpool_area_from_entity_id(self, entity_id: str) -> str | None:
        """Parse Nordpool area code from an entity_id.

        Examples:
        - sensor.nordpool_kwh_se4_sek_2_10_025 -> SE4  (custom integration)
        - sensor.nordpool_kwh_no1_nok_3_10_025 -> NO1  (custom integration)
        - sensor.nord_pool_se3_current_price    -> SE3  (official HA)
        """
        match = re.search(
            r"(?:^|_)(se[1-4]|no[1-5]|dk[12]|fi|ee|lt|lv)(?:_|$)", entity_id
        )
        if match:
            return match.group(1).upper()
        return None

    def _extract_growatt_device_sn(self, states: list[dict]) -> str | None:
        """Extract Growatt device serial number from entity IDs.

        HA builds entity IDs from the slugified translation name, not the sensor key.
        The SOC sensor (key="tlx_statement_of_charge") is used as the anchor because
        it is present on all MIN/TLX inverters and has a stable, distinctive name.

        The translation name was corrected at some point, producing two possible suffixes:
          sensor.<sn>_statement_of_charge_soc  (old name: "Statement of Charge SOC")
          sensor.<sn>_state_of_charge_soc      (current name: "State of charge (SoC)")

        Both are handled: "_statement_of_charge" is a substring of the old suffix,
        and "_state_of_charge_soc" matches the current suffix.

        Assumes the serial number does not contain underscores (consistent with
        Growatt alphanumeric SN format, e.g. "rkm0d7n04x").

        Args:
            states: List of state dicts from /api/states

        Returns:
            Device serial number string, or None if no Growatt entities found
        """
        for state in states:
            entity_id = str(state.get("entity_id", ""))
            if not entity_id.startswith(("sensor.", "number.", "switch.")):
                continue
            if (
                "_statement_of_charge" in entity_id
                or "_state_of_charge_soc" in entity_id
            ):
                object_id = entity_id.split(".", 1)[1]
                return object_id.split("_", 1)[0]

        return None

    def discover_current_sensors(self, states: list[dict]) -> dict[str, str]:
        """Discover phase current sensor entity IDs.

        Scans entity states for sensors with device_class 'current' that
        match household phase current naming (L1/L2/L3).

        Args:
            states: List of state dicts from /api/states

        Returns:
            dict mapping phase key ('current_l1', 'current_l2', 'current_l3') ->
            entity_id for detected sensors. Empty dict if none found.
        """
        result: dict[str, str] = {}
        for state in states:
            entity_id = str(state.get("entity_id", ""))
            if not entity_id.startswith("sensor."):
                continue
            attrs = state.get("attributes", {})
            if attrs.get("device_class") != "current":
                continue
            lower_id = entity_id.lower()
            if "current_l1" in lower_id and "current_l1" not in result:
                result["current_l1"] = entity_id
            elif "current_l2" in lower_id and "current_l2" not in result:
                result["current_l2"] = entity_id
            elif "current_l3" in lower_id and "current_l3" not in result:
                result["current_l3"] = entity_id

        logger.info("Discovered %d phase current sensor(s)", len(result))
        return result

    def _match_optional_sensor(
        self, entity_id: str, lower_id: str
    ) -> tuple[str, str] | None:
        """Match a single entity to an optional sensor key.

        Returns (sensor_key, entity_id) if matched, None otherwise.
        """
        if "solcast" in lower_id and "peak" not in lower_id:
            if "forecast_today" in lower_id:
                return "solar_forecast_today", entity_id
            if "forecast_tomorrow" in lower_id:
                return "solar_forecast_tomorrow", entity_id

        if entity_id.startswith("weather."):
            return "weather_entity", entity_id

        if "48h" in lower_id and "grid_import" in lower_id:
            return "48h_avg_grid_import", entity_id

        if entity_id.startswith("binary_sensor."):
            if "discharge_inhibit" in lower_id:
                return "discharge_inhibit", entity_id
            # Any binary_sensor ending with _charging or _is_charging is treated
            # as a discharge inhibit (EV charger active indicator).
            # Guarded by binary_sensor. prefix so power sensors like
            # sensor.battery_is_charging_w won't match.
            # Examples: zap263668_charging, ex90_charging, tibber_home_is_charging
            if lower_id.endswith("_charging") or lower_id.endswith("_is_charging"):
                return "discharge_inhibit", entity_id

        return None

    def discover_octopus_entities(self, entity_registry: list[dict]) -> dict[str, str]:
        """Discover Octopus Energy pricing entity IDs from the entity registry.

        Uses the immutable ``unique_id`` field (same approach as Growatt/SolaX
        discovery) so renamed entities are still found.  Matches
        ``_OCTOPUS_RATE_PATTERNS`` regex patterns against the unique_id to
        identify electricity rate entities — gas entities are excluded by
        requiring ``_electricity_`` in the unique_id pattern.

        Args:
            entity_registry: Entity registry list from HA WebSocket API.

        Returns:
            dict mapping form field keys to entity_ids, empty if not found
        """
        result: dict[str, str] = {}

        for entry in entity_registry:
            if entry.get("platform") != "octopus_energy":
                continue
            entity_id = str(entry.get("entity_id", ""))
            unique_id = str(entry.get("unique_id", ""))

            for pattern, bess_key in self._OCTOPUS_RATE_PATTERNS:
                if pattern.search(unique_id) and bess_key not in result:
                    result[bess_key] = entity_id
                    break

        if result:
            logger.info(
                "Octopus discovery: matched %d entities from unique_id patterns",
                len(result),
            )
        return result

    def discover_entsoe_entity(
        self, entity_registry: list[dict], states: list[dict]
    ) -> str | None:
        """Discover the ENTSO-e Transparency Platform price sensor entity_id.

        The ENTSO-e integration (github.com/JaccoR/hass-entso-e, ``DOMAIN = "entsoe"``)
        creates one sensor per metric. Only the *average* price sensor carries the
        ``prices_today`` / ``prices_tomorrow`` attributes we need, and its
        ``unique_id`` is constructed as ``entsoe.{name}_avg_price`` (or
        ``entsoe.avg_price`` when no custom name is set) — see the integration's
        ``sensor.py`` (``_attr_unique_id = f"entsoe.{name}_{description.key}"``,
        ``key="avg_price"``).

        Primary match is the immutable ``unique_id`` (robust against renaming).
        A fallback scans live states for the ``prices_today`` attribute shape so
        detection still works across integration versions / unique_id changes.

        Args:
            entity_registry: Entity registry list from HA WebSocket API.
            states: Live entity states from ``/api/states``.

        Returns:
            The entity_id of the ENTSO-e average-price sensor, or None.
        """
        # Primary: immutable unique_id on the entsoe platform
        for entry in entity_registry:
            if entry.get("platform") != "entsoe":
                continue
            unique_id = str(entry.get("unique_id", ""))
            if unique_id.endswith("avg_price"):
                entity_id = entry.get("entity_id")
                if entity_id:
                    logger.info(
                        "ENTSO-e discovery: matched %s via unique_id %r",
                        entity_id,
                        unique_id,
                    )
                    return entity_id

        # Fallback: detect by the prices_today attribute shape
        for state in states:
            attributes = state.get("attributes") or {}
            prices_today = attributes.get("prices_today")
            if (
                isinstance(prices_today, list)
                and prices_today
                and isinstance(prices_today[0], dict)
                and "time" in prices_today[0]
                and "price" in prices_today[0]
            ):
                entity_id = state.get("entity_id")
                if entity_id:
                    logger.info(
                        "ENTSO-e discovery: matched %s via prices_today attribute shape",
                        entity_id,
                    )
                    return entity_id

        return None

    def discover_optional_sensors(self, states: list[dict]) -> dict[str, str]:
        """Discover optional integration sensors from entity states.

        Scans all entity states for sensors belonging to optional integrations:
        - Solcast solar forecast (forecast_today / forecast_tomorrow)
        - Weather entity for temperature derating
        - 48h average grid import (consumption forecast)
        - Discharge inhibit binary sensor

        Args:
            states: List of state dicts from /api/states

        Returns:
            dict mapping sensor_key -> entity_id for detected optional sensors
        """
        result: dict[str, str] = {}

        for state in states:
            entity_id = str(state.get("entity_id", ""))
            lower_id = entity_id.lower()

            match = self._match_optional_sensor(entity_id, lower_id)
            if match is None:
                continue
            key, matched_id = match

            # Weather: prefer "weather.home" over arbitrary matches
            if key == "weather_entity":
                if key not in result or matched_id == "weather.home":
                    result[key] = matched_id
            elif key not in result:
                result[key] = matched_id

        logger.info("Discovered %d optional sensor(s)", len(result))
        return result

    def fetch_entity_registry(self) -> list[dict]:
        """Fetch the full entity registry from Home Assistant via WebSocket.

        The entity registry is only accessible through the WebSocket API
        (not REST).  Each entry contains at minimum: ``entity_id``,
        ``platform``, ``unique_id``.  The ``platform`` field identifies
        which integration created the entity (e.g. ``"solax_modbus"``,
        ``"growatt_server"``, ``"nordpool"``).

        Raises:
            SystemConfigurationError: If entity registry cannot be queried.
        """
        try:
            results = self._ws_query([{"type": "config/entity_registry/list"}])
            return results[0]
        except Exception as e:
            raise SystemConfigurationError(
                f"Failed to query Home Assistant entity registry: {e}"
            ) from e

    # Platform names used by each integration in the HA entity registry.
    _INVERTER_PLATFORMS: ClassVar[dict[str, list[str]]] = {
        "growatt": ["growatt_server"],
        "solax": ["solax_modbus", "solax"],
    }
    _PRICE_PLATFORMS: ClassVar[dict[str, list[str]]] = {
        "nordpool": ["nordpool"],
        "octopus_energy": ["octopus_energy"],
    }
    _FORECAST_PLATFORMS: ClassVar[dict[str, list[str]]] = {
        "solcast": ["solcast_solar"],
        "weather": ["weather"],
    }

    @staticmethod
    def _detect_platforms(
        entities: list[dict], platform_map: dict[str, list[str]]
    ) -> dict[str, bool]:
        """Check which integration platforms are present in the entity registry."""
        # Build a set of all platform values for fast lookup
        all_platforms = {p for platforms in platform_map.values() for p in platforms}
        found_platforms: set[str] = set()
        for entity in entities:
            plat = entity.get("platform")
            if plat and plat in all_platforms:
                found_platforms.add(plat)

        detected = {}
        for name, platforms in platform_map.items():
            is_found = any(p in found_platforms for p in platforms)
            detected[name] = is_found
            logger.info(
                "Integration '%s': %s",
                name,
                "DETECTED" if is_found else "not found",
            )
        return detected

    # ── Platform markers for solax_modbus platform detection ────────────
    # GEN4 (MIN/MOD/MID/TL-X): uses numbered TOU time slots (time_N_enabled).
    # GEN3 (MIX/SPA/SPH): uses mode-specific time slots and distinct EMS entities.
    # Native SolaX: uses VPP remote-control entities (remotecontrol_power_control).
    _GROWATT_TOU_MARKER_SUFFIX: ClassVar[str] = "time_1_enabled"  # GEN4
    _GROWATT_GEN3_MARKER_SUFFIX: ClassVar[str] = (
        "load_first_battery_minimum_soc"  # GEN3
    )
    _SOLAX_NATIVE_MARKER_SUFFIX: ClassVar[str] = (
        "remotecontrol_power_control"  # VPP mode selector, SolaX-only
    )

    _SOLAX_PLATFORMS: ClassVar[set[str]] = {"solax_modbus", "solax"}

    def _has_solax_entity_suffix(
        self, entities: list[dict], suffix: str, label: str
    ) -> bool:
        """Check whether any solax_modbus entity has a unique_id ending with the suffix."""
        count = 0
        for entity in entities:
            if entity.get("platform") not in self._SOLAX_PLATFORMS:
                continue
            count += 1
            unique_id = str(entity.get("unique_id", ""))
            if unique_id.endswith(f"_{suffix}"):
                logger.info("%s marker found: unique_id=%s", label, unique_id)
                return True
        logger.info("No %s marker found among %d solax_modbus entities", label, count)
        return False

    def _has_growatt_tou_entities(self, entities: list[dict]) -> bool:
        """Check for GEN4 Growatt (MIN/MOD/MID) TOU entities via solax_modbus."""
        return self._has_solax_entity_suffix(
            entities, self._GROWATT_TOU_MARKER_SUFFIX, "Growatt GEN4 TOU"
        )

    def _has_growatt_gen3_entities(self, entities: list[dict]) -> bool:
        """Check for GEN3 Growatt (MIX/SPA/SPH) entities via solax_modbus."""
        return self._has_solax_entity_suffix(
            entities, self._GROWATT_GEN3_MARKER_SUFFIX, "Growatt GEN3"
        )

    def _has_solax_native_entities(self, entities: list[dict]) -> bool:
        """Check for native SolaX inverter VPP entities via solax_modbus."""
        return self._has_solax_entity_suffix(
            entities, self._SOLAX_NATIVE_MARKER_SUFFIX, "SolaX native VPP"
        )

    def detect_inverter_integrations(
        self, entities: list[dict] | None = None
    ) -> dict[str, bool]:
        """Detect which inverter integrations are installed."""
        if entities is None:
            entities = self.fetch_entity_registry()
        return self._detect_platforms(entities, self._INVERTER_PLATFORMS)

    def detect_price_integrations(
        self, entities: list[dict] | None = None
    ) -> dict[str, bool]:
        """Detect which price/energy integrations are installed."""
        if entities is None:
            entities = self.fetch_entity_registry()
        return self._detect_platforms(entities, self._PRICE_PLATFORMS)

    def detect_forecast_integrations(
        self, entities: list[dict] | None = None
    ) -> dict[str, bool]:
        """Detect which forecast/weather integrations are installed."""
        if entities is None:
            entities = self.fetch_entity_registry()
        return self._detect_platforms(entities, self._FORECAST_PLATFORMS)

    def detect_all_integrations(self) -> dict[str, dict[str, bool]]:
        """Detect all required and optional integrations.

        Fetches the entity registry once and reuses it across all detection
        methods to avoid redundant HTTP calls.
        """
        entities = self.fetch_entity_registry()
        return {
            "inverter": self.detect_inverter_integrations(entities),
            "price": self.detect_price_integrations(entities),
            "forecast": self.detect_forecast_integrations(entities),
        }

    def discover_sensors_from_registry(
        self, entities: list[dict] | None = None
    ) -> tuple[dict[str, dict[str, str]], str | None]:
        """Discover sensor entity IDs for all detected inverter platforms.

        Uses the ``platform`` field to identify integration entities, then maps
        entity ID suffixes to BESS sensor keys via the suffix maps.  This is
        robust against entity renaming because it identifies the integration
        directly rather than pattern-matching entity ID prefixes.

        Args:
            entities: Pre-fetched entity registry list, or None to fetch.

        Returns:
            Tuple of (platform_sensors, detected_platform) where
            platform_sensors maps platform name to its sensor dict
            (e.g. ``{"growatt": {bess_key: entity_id, ...}, "solax": {...}}``)
            and detected_platform is ``"growatt"``, ``"solax"``, or None.
            Growatt takes priority when both are present.
        """
        if entities is None:
            entities = self.fetch_entity_registry()

        inverter_detected = self.detect_inverter_integrations(entities)
        platform_sensors: dict[str, dict[str, str]] = {}
        detected_platform: str | None = None

        if inverter_detected.get("growatt"):
            min_sensors = self._map_registry_entities(
                entities,
                ["growatt_server"],
                self.GROWATT_MIN_SUFFIX_MAP,
            )
            sph_sensors = self._map_registry_entities(
                entities,
                ["growatt_server"],
                self.GROWATT_SPH_SUFFIX_MAP,
            )
            if min_sensors:
                platform_sensors["growatt_server_min"] = min_sensors
            if sph_sensors:
                platform_sensors["growatt_server_sph"] = sph_sensors
            # Pick the platform that matched more sensors
            if len(min_sensors) >= len(sph_sensors):
                detected_platform = "growatt_server_min"
            else:
                detected_platform = "growatt_server_sph"

        if inverter_detected.get("solax"):
            solax_platforms = ["solax_modbus", "solax"]
            if self._has_growatt_tou_entities(entities):
                # GEN4: Growatt MIN/MOD/MID with numbered TOU slots
                solax_sensors = self._map_registry_entities(
                    entities, solax_platforms, self.SOLAX_GROWATT_MIN_SUFFIX_MAP
                )
                platform_sensors["solax_modbus_growatt_min"] = solax_sensors
                if not detected_platform:
                    detected_platform = "solax_modbus_growatt_min"
            elif self._has_growatt_gen3_entities(entities):
                # GEN3: Growatt MIX/SPA/SPH with mode-specific time slots
                solax_sensors = self._map_registry_entities(
                    entities, solax_platforms, self.SOLAX_GROWATT_SPH_SUFFIX_MAP
                )
                platform_sensors["solax_modbus_growatt_sph"] = solax_sensors
                if not detected_platform:
                    detected_platform = "solax_modbus_growatt_sph"
            else:
                solax_sensors = self._map_registry_entities(
                    entities, solax_platforms, self.SOLAX_NATIVE_SUFFIX_MAP
                )
                platform_sensors["solax_modbus_native"] = solax_sensors
                if not detected_platform:
                    detected_platform = "solax_modbus_native"

        return platform_sensors, detected_platform

    def _map_registry_entities(
        self,
        entities: list[dict],
        platforms: list[str],
        suffix_map: dict[str, str],
    ) -> dict[str, str]:
        """Map entity registry entries to BESS sensor keys using unique_id.

        Filters entities belonging to the given platforms, then matches
        the ``unique_id`` suffix against the suffix map.  ``unique_id``
        is assigned by the integration and never changes regardless of
        user entity renaming — this is the only reliable matching strategy.

        Enabled entities are preferred over disabled ones.  If the only
        match for a sensor key is a disabled entity, it is still returned
        (the caller can read its state) but a warning is logged.

        Args:
            entities: Full entity registry list.
            platforms: HA platform names to filter by (e.g. ["solax_modbus"]).
            suffix_map: Maps entity suffix -> BESS sensor key.

        Returns:
            dict mapping bess_sensor_key -> entity_id.
        """
        result: dict[str, str] = {}
        disabled_matches: dict[str, str] = {}
        platform_set = set(platforms)

        # Sort suffixes longest-first so "total_grid_import" matches before
        # the shorter "grid_import" when both are in the map.
        sorted_suffixes = sorted(
            suffix_map.items(), key=lambda x: len(x[0]), reverse=True
        )

        for entity in entities:
            if entity.get("platform") not in platform_set:
                continue
            entity_id = entity.get("entity_id", "")
            if "." not in entity_id:
                continue

            unique_id = str(entity.get("unique_id", ""))
            is_disabled = bool(entity.get("disabled_by"))

            for suffix, bess_key in sorted_suffixes:
                if (
                    unique_id.endswith(f"_{suffix}")
                    or unique_id.endswith(f"-{suffix}")
                    or unique_id == suffix
                ):
                    if bess_key not in result:
                        if is_disabled:
                            # Defer — an enabled entity may appear later
                            if bess_key not in disabled_matches:
                                disabled_matches[bess_key] = entity_id
                        else:
                            result[bess_key] = entity_id
                    break

        # Fill gaps with disabled entities and warn
        for bess_key, entity_id in disabled_matches.items():
            if bess_key not in result:
                result[bess_key] = entity_id
                logger.warning(
                    "Sensor '%s' mapped to disabled entity %s — "
                    "enable it in Home Assistant for reliable operation",
                    bess_key,
                    entity_id,
                )

        logger.info(
            "Mapped %d entities from registry (platforms=%s)",
            len(result),
            platforms,
        )
        return result
