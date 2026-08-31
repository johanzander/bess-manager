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
from functools import partial
from typing import ClassVar

import requests
import websocket

from .consumption_overlay import OverlayBlock, parse_overlay_blocks
from .energy_balance import derive_load_consumption
from .exceptions import ConsumptionOverlayError, SystemConfigurationError
from .runtime_failure_tracker import RuntimeFailureTracker
from .settings_store import SettingsStore, apply_signed_pair_aliases

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
        # Don't log at ERROR here: the caller (_api_request) doesn't yet know
        # whether this attempt will be retried. It logs WARNING for retryable
        # attempts and ERROR only once retries are exhausted.
        logger.debug("Error during HTTP request: %s", str(e))
        raise


def solcast_detailed_hourly_to_quarterly(hourly_data: list) -> list[float]:
    """Expand a Solcast ``detailedHourly`` payload to 96 quarter-hour values.

    Module-level so that anything replaying a captured forecast -- notably
    ``scripts/knee_oracle.py``, which scores the #602/#687 terminal knee
    against metered actuals -- prices the boundary off the *same* parse
    production used. A second, hand-written copy of this is how an oracle
    comes to grade a forecast the optimizer never saw: the hour is taken
    from the raw string with no timezone conversion, so a reimplementation
    that helpfully calls ``astimezone`` agrees only while the feed happens
    to serialize in local time, and silently shifts by the UTC offset
    otherwise.

    Missing hours stay 0.0 rather than raising -- Solcast omits pre-dawn and
    post-dusk hours, which are genuinely zero.
    """
    hourly_values = [0.0] * 24
    for entry in hourly_data:
        period_start = entry["period_start"]
        if isinstance(period_start, str):
            # Deliberately naive: the hour is whatever the payload says it
            # is, in the payload's own offset. See the docstring.
            hour = int(period_start.split("T")[1].split(":")[0])
        else:
            hour = period_start.hour
        hourly_values[hour] = float(entry["pv_estimate"])

    quarterly_values: list[float] = []
    for hourly_value in hourly_values:
        quarterly_values.extend([hourly_value / 4.0] * 4)
    return quarterly_values


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

    def __init__(
        self,
        ha_url: str,
        token: str,
        settings_store: SettingsStore | None = None,
        growatt_device_id: str | None = None,
        huawei_device_id: str | None = None,
        service_domain: str | None = None,
        grid_power_polarity: str | None = None,
        battery_power_polarity: str | None = None,
    ):
        """Initialize the Controller with Home Assistant API access.

        Args:
            ha_url: Base URL of Home Assistant (default: "http://supervisor/core")
            token: Long-lived access token for Home Assistant
            settings_store: Live settings store backing ``.sensors`` — a
                computed view over ``settings_store.get_active_sensors()``,
                never a manually-synced snapshot. Defaults to a fresh, empty
                ``SettingsStore`` for callers that don't need persistence
                (e.g. tests).
            growatt_device_id: Growatt device ID for TOU segment operations
            huawei_device_id: Huawei battery device ID for TOU period operations
            service_domain: HA integration domain for vendor service calls
                (SettingsStore.get_service_domain() — "huawei_solar",
                "growatt_server", or a compatible integration's own domain)
            grid_power_polarity: Sign convention for a platform whose
                import_power/export_power share one signed entity
                (SettingsStore.get_grid_power_polarity() — "import_positive"
                or "" when the platform has separate entities)
            battery_power_polarity: Sign convention for a platform whose
                battery_charge_power/battery_discharge_power share one signed
                entity (SettingsStore.get_battery_power_polarity() —
                "charge_positive" or "" when the platform has separate
                entities)

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

        self._settings_store = settings_store or SettingsStore()

        # Store Growatt device ID for TOU operations
        self.growatt_device_id = growatt_device_id

        # Store Huawei battery device ID for TOU period operations
        self.huawei_device_id = huawei_device_id

        # HA integration domain for vendor service calls (set_tou_periods,
        # update_time_segment, ...). Every other service call infers its
        # domain from the entity_id prefix; these target a device, so the
        # domain is configuration — see SettingsStore.get_service_domain.
        self.service_domain = service_domain or ""

        # Sign convention for a platform whose import_power/export_power
        # share one signed entity (see get_import_power/get_export_power).
        self.grid_power_polarity = grid_power_polarity or ""

        # Sign convention for a platform whose battery charge/discharge power
        # share one signed entity (see get_battery_charge_power/
        # get_battery_discharge_power).
        self.battery_power_polarity = battery_power_polarity or ""

        # Cached entity->device and device->name registry maps for health
        # banner grouping, refreshed on a TTL so the 5-minute health check
        # does not re-fetch the full HA registries every run.
        self._device_maps_cache: tuple | None = None
        self._device_maps_cache_ts: float | None = None

        # Runtime failure tracker (injected by BatterySystemManager)
        self.failure_tracker = None

        # Create persistent session for connection reuse (400x faster)
        self.session = requests.Session()
        self.session.headers.update(self.headers)

        logger.info(
            "Initialized HomeAssistantAPIController with %d sensor mappings",
            len(self.sensors),
        )

    @property
    def sensors(self) -> dict:
        """Active sensor_key -> entity_id map, read live from settings_store.

        Computed on every access — never cached — so a settings mutation
        (direct sensor edit, inverter platform switch, ...) is visible here
        immediately, with no refresh call required.
        """
        return self._settings_store.get_active_sensors()

    @sensors.setter
    def sensors(self, value: dict) -> None:
        self._settings_store.data["sensors"] = dict(value)

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
        "get_consumption_overlay_blocks": {
            "sensor_key": "consumption_overlay",
            "name": "Planned Consumption Changes",
            "unit": "list",
            "precision": None,
            "conversion_threshold": None,
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
    # battery_discharge_power        battery_1_discharging_w            solax_battery_discharge_power (Growatt only; native SolaX has no discharge entity — see #542)
    # import_power                   import_power                       solax_measured_power / solax_total_forward_power / solax_ac_power_to_user
    # export_power                   export_power                       solax_grid_export / solax_total_reverse_power / solax_ac_power_to_grid
    # local_load_power               local_load_power                   solax_house_load / solax_total_load_power
    # pv_power                       internal_wattage                   solax_pv_power_1 / solax_pv_power_total / solax_total_pv_power
    # grid_charge                    charge_from_grid                   solax_charger_switch
    # battery_charging_power_rate    battery_charge_power_limit         solax_ems_charging_rate
    # battery_discharging_power_rate battery_discharge_power_limit      solax_ems_discharging_rate
    # battery_charge_stop_soc        battery_charge_soc_limit           solax_ems_charging_stop_soc
    # battery_discharge_stop_soc     soc_limit_on_grid                  solax_ems_discharging_stop_soc_on_grid
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
    # solax_battery_min_soc          —                                  solax_battery_minimum_capacity_gridtied
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
        # Only the on-grid variant is mapped: BESS only operates grid-tied,
        # and "battery_discharge_soc_limit" (off-grid, api_key
        # wdisChargeSOCLowLimit) has no effect while grid-connected — see
        # #270. Matching it would silently bind a control that does nothing.
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
        # Only the on-grid variant is mapped: BESS only operates grid-tied,
        # and "ems_discharging_stop_soc" (off-grid, register 3037) has no
        # effect while grid-connected — see #270. Matching it would
        # silently bind a control that does nothing.
        "ems_discharging_stop_soc_on_grid": "battery_discharge_stop_soc",
        "charger_switch": "grid_charge",
        # VPP remote power control (registers 30100/30407-30410, GEN3|GEN4).
        # See issue #118 — verified against wills106/homeassistant-solax-modbus
        # plugin_growatt.py NUMBER_TYPES/SELECT_TYPES.
        "vpp_status": "growatt_vpp_status",
        "vpp_remote_control": "growatt_vpp_remote_control",
        "vpp_allow_ac_charging": "growatt_vpp_allow_ac_charging",
        "vpp_time": "growatt_vpp_time",
        "vpp_power": "growatt_vpp_power",
        # Export-limit curtailment (registers 122/123, GEN2|GEN3|GEN4).
        # See issue #269 — verified against plugin_growatt.py
        # SELECT_TYPES/NUMBER_TYPES the same way as the VPP entries above.
        "limit_grid_export": "growatt_export_limit_mode",
        "grid_export_limit": "growatt_export_limit_value",
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
        # VPP remote power control (registers 30100/30407-30410, GEN3|GEN4).
        # Same registers as GEN4 — verified allowedtypes=GEN3|GEN4 in
        # wills106/homeassistant-solax-modbus plugin_growatt.py.
        "vpp_status": "growatt_vpp_status",
        "vpp_remote_control": "growatt_vpp_remote_control",
        "vpp_allow_ac_charging": "growatt_vpp_allow_ac_charging",
        "vpp_time": "growatt_vpp_time",
        "vpp_power": "growatt_vpp_power",
        # Export-limit curtailment (registers 122/123, GEN2|GEN3|GEN4) — #269.
        "limit_grid_export": "growatt_export_limit_mode",
        "grid_export_limit": "growatt_export_limit_value",
    }

    # SolaX native inverters via solax_modbus integration
    SOLAX_NATIVE_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        # Real-time power
        "battery_capacity": "battery_soc",
        # One signed register (REGISTER_S16, 0x16), positive = charging. The
        # integration publishes no discharge counterpart, so
        # discover_sensors_from_registry points battery_discharge_power at
        # this same entity and HAApiController splits it by sign — see
        # PLATFORM_BATTERY_POWER_POLARITY["solax_modbus_native"] (#542).
        "battery_power_charge": "battery_charge_power",
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
        # Only the on-grid variant is mapped: BESS only operates grid-tied,
        # and "battery_minimum_capacity" (register 0x20, general/off-grid)
        # has no effect while grid-connected — see #270. Also fixes a
        # pre-existing typo: upstream's key is "gridtied" (no underscore),
        # not "grid_tied", so this suffix never matched before.
        "battery_minimum_capacity_gridtied": "solax_battery_min_soc",
        "charger_use_mode": "solax_charger_use_mode",
    }

    # ── Solis hybrid inverters via the Pho3niX90/solis_modbus integration ──
    #
    # (github.com/Pho3niX90/solis_modbus, verified against release v4.1.6).
    # DOMAIN = "solis_modbus" (const.py:1). Credits SA7BNT's research and
    # implementation in bess-manager-beta PR #51, re-verified here against
    # the actual integration source per the add-inverter-platform skill.
    #
    # unique_id_generator(controller, third_value) (helpers.py:40-49) builds
    # unique_id = f"solis_modbus_{serial_or_identification_or_host}_{third_value}".
    #
    # Control entities pass a clean string as third_value and are safely
    # matched by suffix (this map, via the normal _map_registry_entities
    # endswith() matching — same mechanism every other platform uses):
    #   - time.py:52 (TOU start/end pickers):
    #     unique_id_generator(controller, entity_definition.get("unique", ...))
    #     where entity["unique"] = f"time_entity_{register}" (time_sensors.py:63).
    #   - solis_binary_sensor.py:36 (TOU per-slot enable switches):
    #     unique_id_generator_binary(controller, register, bit_position, None)
    #     -> f"{register}_{bit_position}" (switch_sensors.py:207-216).
    #
    # IMPORTANT — verified integration bug, not an assumption: for entities
    # built via SolisSensorGroup.__init__ (sensors/solis_base_sensor.py:254),
    # `unique_id=unique_id_generator(controller, entity)` passes the *entire
    # entity definition dict* as third_value instead of `entity["unique"]`.
    # This means most read-only sensors AND all "editable" number entities
    # (per-slot TOU current/cutoff-SOC, global charge/discharge stop SOC)
    # get a unique_id containing the Python repr of their whole definition
    # dict, e.g. ``solis_modbus_SN123_{'name': 'Battery SOC', ..., 'unique':
    # 'solis_modbus_inverter_battery_soc', ...}`` — not a clean suffix.
    # Present in v4.1.6 (stable) and unchanged on HEAD as of 2026-07-05;
    # reported upstream as Pho3niX90/solis_modbus#<TBD>.
    # These CANNOT be matched with endswith() and are handled separately by
    # `_match_solis_dict_embedded_entities` (substring match on the verified
    # ``'unique': '<key>'`` fragment), never by changing the shared
    # `_map_registry_entities` matching logic used by every other platform.
    #
    # `hybrid_sensors_derived` entities (__init__.py:280) go through the
    # *correct* call path (`entity.get("unique", "reserve")`) and therefore
    # DO have clean, endswith()-matchable unique_ids — those are in this map.
    SOLIS_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        # ── Real-time power (hybrid_sensors_derived — clean unique_id) ────
        "solis_modbus_inverter_battery_charge_power": "battery_charge_power",
        "solis_modbus_inverter_battery_discharge_power": "battery_discharge_power",
        # Solis exposes only a single signed net grid power sensor (no
        # separate import/export power entities, hybrid_sensors_derived
        # "Grid Power Net" register 33263/33264, positive=import,
        # negative=export). A suffix map key can only resolve to one BESS
        # sensor key, so auto-discovery wires it to import_power only;
        # export_power is left unconfigured (see docs/INVERTER_PLATFORMS.md
        # Solis section) rather than guessing a second mapping for the same
        # entity.
        "solis_modbus_inverter_grid_power_net": "import_power",
        # PV Power 1 only (hybrid_sensors_derived, register 33049/33050).
        # Solis hybrids have up to 4 MPPT strings (dc_power_1..4); summing
        # them into a single pv_power reading is not implemented in this
        # first pass — installations with a single MPPT string get accurate
        # readings, multi-string installations will under-report.
        "solis_modbus_inverter_dc_power_1": "pv_power",
        # ── Grid Time of Use v2 charge/discharge period times (6 slots) ───
        # unique key = f"time_entity_{register}" (time_sensors.py:34-63).
        "time_entity_43711": "solis_charge_start_1",
        "time_entity_43713": "solis_charge_end_1",
        "time_entity_43753": "solis_discharge_start_1",
        "time_entity_43755": "solis_discharge_end_1",
        "time_entity_43718": "solis_charge_start_2",
        "time_entity_43720": "solis_charge_end_2",
        "time_entity_43760": "solis_discharge_start_2",
        "time_entity_43762": "solis_discharge_end_2",
        "time_entity_43725": "solis_charge_start_3",
        "time_entity_43727": "solis_charge_end_3",
        "time_entity_43767": "solis_discharge_start_3",
        "time_entity_43769": "solis_discharge_end_3",
        "time_entity_43732": "solis_charge_start_4",
        "time_entity_43734": "solis_charge_end_4",
        "time_entity_43774": "solis_discharge_start_4",
        "time_entity_43776": "solis_discharge_end_4",
        "time_entity_43739": "solis_charge_start_5",
        "time_entity_43741": "solis_charge_end_5",
        "time_entity_43781": "solis_discharge_start_5",
        "time_entity_43783": "solis_discharge_end_5",
        "time_entity_43746": "solis_charge_start_6",
        "time_entity_43748": "solis_charge_end_6",
        "time_entity_43788": "solis_discharge_start_6",
        "time_entity_43790": "solis_discharge_end_6",
        # ── Grid Time of Use v2 per-slot enable switches (register 43707) ─
        # unique key = f"switch_{register}_{bit_position}" (switch_sensors.py
        # :207-216); actual unique_id uses unique_id_generator_binary, whose
        # suffix is f"{register}_{bit_position}" (solis_binary_sensor.py:36).
        # Bits 0-5 = charge periods 1-6, bits 6-11 = discharge periods 1-6
        # (switch_sensors.py:176-191).
        "43707_0": "solis_charge_enable_1",
        "43707_1": "solis_charge_enable_2",
        "43707_2": "solis_charge_enable_3",
        "43707_3": "solis_charge_enable_4",
        "43707_4": "solis_charge_enable_5",
        "43707_5": "solis_charge_enable_6",
        "43707_6": "solis_discharge_enable_1",
        "43707_7": "solis_discharge_enable_2",
        "43707_8": "solis_discharge_enable_3",
        "43707_9": "solis_discharge_enable_4",
        "43707_10": "solis_discharge_enable_5",
        "43707_11": "solis_discharge_enable_6",
    }

    # ── Solis monitoring sensors affected by the dict-embedded unique_id bug
    # (see SOLIS_SUFFIX_MAP docstring above). Matched by a Solis-only
    # substring check on the verified ``'unique': '<key>'`` fragment — this
    # is scoped narrowly to Solis and never touches the shared, endswith()-
    # based `_map_registry_entities` used by every other platform.
    # Keys are the verified "unique" field from hybrid_sensors.py (the
    # *non-derived* sensor list, whose SolisSensorGroup construction path
    # has the bug); values are BESS sensor keys.
    SOLIS_DICT_EMBEDDED_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        "solis_modbus_inverter_battery_soc": "battery_soc",  # hybrid_sensors.py:656
        "solis_modbus_inverter_household_load_power": "local_load_power",  # :725
        "solis_modbus_inverter_total_battery_charge_energy": "lifetime_battery_charged",  # :811
        "solis_modbus_inverter_total_battery_discharge_energy": "lifetime_battery_discharged",  # :841
        "solis_modbus_inverter_pv_total_generation": "lifetime_solar_energy",  # :155
        "solis_modbus_inverter_total_energy_imported_from_grid": "lifetime_import_from_grid",  # :871
        "solis_modbus_inverter_total_energy_fed_into_grid": "lifetime_export_to_grid",  # :901
        # Meter-measured whole-home consumption, registers 33177/33178 (#730).
        # Enabled by default; needs a grid CT/meter, standard on Solis hybrids.
        "solis_modbus_inverter_total_energy_consumption": "lifetime_load_consumption",  # :1023
    }

    SOLCAST_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        "total_kwh_forecast_today": "solar_forecast_today",
        "total_kwh_forecast_tomorrow": "solar_forecast_tomorrow",
    }

    # Huawei LUNA2000 via the huawei_solar integration. unique_id format is
    # f"{device.serial_number}_{register_key}" — verified against
    # wlcrs/huawei_solar select.py:204, number.py:358, switch.py:200.
    # Lifetime energy register keys verified against
    # wlcrs/huawei-solar-lib register_names.py/sensor.py: total_dc_input_power
    # (inverter PV total, see #569 below), storage_total_charge/storage_total_discharge (battery),
    # grid_exported_energy/grid_accumulated_energy (separate power-meter device,
    # so these two resolve to "not configured" on meterless installs).
    # input_power (inverter, real-time PV) and power_meter_active_power
    # (separate power-meter device, real-time grid power) verified against
    # the same source (issue #438). power_meter_active_power is a single
    # signed register (positive = export, negative = import — confirmed
    # against Huawei's official register description, not the integration
    # source, which documents no sign convention); it maps to import_power
    # here and discover_sensors_from_registry also points export_power at
    # the same entity, same pattern as Solis's grid_power_net (#475) — see
    # PLATFORM_GRID_POWER_POLARITY["huawei_solar_luna2000"] in settings_store.py.
    HUAWEI_SUFFIX_MAP: ClassVar[dict[str, str]] = {
        "storage_state_of_capacity": "battery_soc",
        "storage_charge_discharge_power": "battery_charge_power",
        "storage_maximum_charging_power": "battery_charging_power_rate",
        "storage_maximum_discharging_power": "battery_discharging_power_rate",
        "storage_charging_cutoff_capacity": "battery_charge_stop_soc",
        "storage_discharging_cutoff_capacity": "battery_discharge_stop_soc",
        "storage_charge_from_grid_function": "grid_charge",
        "storage_working_mode_settings": "huawei_working_mode",
        "active_power": "local_load_power",
        # PV production, NOT accumulated_yield_energy (#569).  That register
        # (32106, "Total yield") is the inverter's accumulated AC *output*:
        # on a LUNA2000 hybrid it rises while the battery discharges and
        # misses whatever charged it, so feeding it to
        # derive_load_consumption inflates home consumption by
        # (battery_discharged - solar_to_battery) with no visible error.
        # 32108 "Total DC input energy" is the lifetime integral of 32064,
        # which is already mapped to pv_power below -- DC-side, so it
        # excludes conversion losses, but Huawei exposes no AC-side PV
        # total at all (wlcrs/huawei_solar README FAQ).
        "total_dc_input_power": "lifetime_solar_energy",
        "storage_total_charge": "lifetime_battery_charged",
        "storage_total_discharge": "lifetime_battery_discharged",
        "grid_exported_energy": "lifetime_export_to_grid",
        "grid_accumulated_energy": "lifetime_import_from_grid",
        # EMMA-only whole-home consumption counter, register key
        # total_energy_consumption (#730). Only present on installs with an
        # EMMA energy manager, and its HA entity is
        # entity_registry_enabled_default=False (sensor.py EMMA_SENSOR_DESCRIPTIONS)
        # — so unlike emma_tou_periods below it is safe to map here: an
        # optional lifetime sensor left disabled is surfaced by
        # _map_registry_entities' #549 disabled-bucket (the wizard prompts the
        # user to enable it), not read at startup.
        "total_energy_consumption": "lifetime_load_consumption",
        "input_power": "pv_power",
        "power_meter_active_power": "import_power",
        # TOU period readback (#431). The integration publishes the configured
        # periods as extra state attributes of this sensor, in the same text
        # format set_tou_periods accepts (sensor.py:2487-2513) — so BESS can
        # start from what the battery actually holds instead of assuming
        # nothing. EMMA's equivalent register (emma_tou_periods) is
        # deliberately absent: its entity is disabled by default upstream
        # (sensor.py:1789), and mapping a disabled entity would hand those
        # installs a startup read of an entity with no state.
        "storage_huawei_luna2000_time_of_use_charging_and_discharging_periods": (
            "huawei_tou_periods"
        ),
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

    def is_sensor_configured(self, sensor_key: str) -> bool:
        """Report whether ``sensor_key`` is mapped to a usable entity ID.

        Public predicate for controllers that treat an optional entity's
        absence as a supported configuration rather than a fault — e.g.
        HuaweiController skipping the working-mode gate on installs behind
        an energy manager that exposes no LUNA2000 working-mode select.
        """
        try:
            self._resolve_entity_id(sensor_key)
        except ValueError:
            return False
        return True

    def _signed_split_state(self, method_name: str, state):
        """Apply the signed split to a raw entity state, for diagnostics.

        get_method_sensor_info reads /api/states/{entity_id} directly rather
        than going through the getters, so on a platform whose charge and
        discharge (or import and export) keys resolve to ONE signed entity it
        would report the same raw signed value for both — e.g. -800 for both
        "Battery Charging Power" and "Battery Discharging Power" on a native
        SolaX discharging at 800 W. Reuses the getters' own split predicates
        instead of re-deriving the polarity here.

        Returns the state unchanged for every other method, for a platform
        with two real entities, or for a state that isn't numeric.
        """
        if method_name in ("get_battery_charge_power", "get_battery_discharge_power"):
            if not self._is_shared_signed_battery_power():
                return state
            split = partial(
                self._split_signed_battery_power,
                charging=method_name == "get_battery_charge_power",
            )
        elif method_name in ("get_import_power", "get_export_power"):
            if not self._is_shared_signed_grid_power():
                return state
            split = partial(
                self._split_signed_grid_power,
                importing=method_name == "get_import_power",
            )
        else:
            return state

        try:
            raw = float(state)
        except (TypeError, ValueError):
            return state
        # .10g, not .g: the default 6 significant digits would round a raw
        # state like "12345.678" to "12345.7" and switch to scientific
        # notation above 1e6, silently degrading a diagnostic reading.
        return f"{split(raw):.10g}"

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
                state = response.get("state")
                # Caught separately from the outer handler: an unknown polarity
                # is a configuration fault, and reporting it as a connectivity
                # error ("Failed to check entity") would hide exactly the loud
                # failure _split_signed_battery_power raises to produce.
                try:
                    current_value = self._signed_split_state(method_name, state)
                except ValueError as e:
                    result.update({"status": "error", "error": str(e)})
                else:
                    result.update({"status": "ok", "current_value": current_value})
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
        optional: bool = False,
        suppress_retry_warnings: bool = False,
        **kwargs,
    ):
        """Make an API request to Home Assistant with retry logic.

        Args:
            method: HTTP method ('get', 'post', etc.)
            path: API path (without base URL)
            operation: Optional human-readable operation description for failure tracking
            category: Optional operation category for failure tracking
            context: Optional dict of contextual parameters for failure diagnostics
            optional: If True, a 404 is expected (e.g. probing a legacy/disabled
                entity) and is logged at debug level instead of error
            suppress_retry_warnings: If True, the failure is an expected
                condition (e.g. Nordpool tomorrow-price calls before the
                provider has published data — an expected daily condition, not
                an error): retry/failure logging is downgraded to debug/info and
                no runtime failure is recorded
            **kwargs: Additional arguments for requests

        Returns:
            Response data from API

        Raises:
            requests.RequestException: If all retries fail

        """
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
                    if optional:
                        logger.debug(
                            "API request to %s failed: Sensor not found (404, optional).",
                            url,
                        )
                    else:
                        logger.error(
                            "API request to %s failed: Sensor not found (404). This indicates a missing or misconfigured sensor.",
                            url,
                        )
                    raise  # Fail immediately on 404

                if attempt < self.max_attempts - 1:  # Not the last attempt
                    delay = self.retry_base_delay * (2**attempt)
                    log_fn = logger.debug if suppress_retry_warnings else logger.warning
                    log_fn(
                        "API request to %s failed on attempt %d/%d: %s. Retrying in %d seconds...",
                        url,
                        attempt + 1,
                        self.max_attempts,
                        str(e),
                        delay,
                    )
                    time.sleep(delay)
                else:  # Last attempt failed
                    log_fn = logger.info if suppress_retry_warnings else logger.error
                    log_fn(
                        "API request to %s failed on final attempt %d/%d: %s",
                        path,
                        attempt + 1,
                        self.max_attempts,
                        str(e),
                    )

                    # Record runtime failure if failure tracker is available.
                    # A suppressed failure is an expected condition (see
                    # suppress_retry_warnings above) — recording it would surface
                    # a routine daily event as a user-visible failure (#583).
                    if self.failure_tracker and not suppress_retry_warnings:
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

    def _vendor_service_domain(self) -> str:
        """Return the configured vendor integration domain, or raise.

        Raises:
            SystemConfigurationError: If no domain is configured — the
                install has no inverter platform selected, so a vendor
                service call can't be addressed at all.
        """
        if not self.service_domain:
            raise SystemConfigurationError(
                component="inverter service domain",
                message=(
                    "No inverter service domain configured. Run the setup "
                    "wizard to select an inverter platform, or set the "
                    "service domain override in Settings."
                ),
            )
        return self.service_domain

    def _service_call_with_retry(
        self,
        service_domain,
        service_name,
        operation: str | None = None,
        category: str | None = None,
        suppress_retry_warnings: bool = False,
        **kwargs,
    ):
        """Call Home Assistant service with retry logic.

        Args:
            service_domain: Service domain (e.g., 'switch', 'number')
            service_name: Service name (e.g., 'turn_on', 'set_value')
            operation: Optional human-readable operation description for failure tracking
            category: Optional failure-tracking category override. Defaults to a
                domain-based heuristic when omitted.
            suppress_retry_warnings: Forwarded to `_api_request` — see its docstring
            **kwargs: Service parameters

        Returns:
            Response from service call or None

        """
        # Read-only operations that are safe to execute in test mode, and
        # that HA requires return_response=true for. The vendor reads are
        # matched by service name against whatever domain this install's
        # inverter integration uses (self.service_domain), not the literal
        # "growatt_server" — a compatible integration under a different
        # domain implements the same services and would otherwise get no
        # data back, failing in a way that looks like its own fault.
        vendor_safe_reads = (
            "read_time_segments",
            "read_ac_charge_times",
            "read_ac_discharge_times",
        )
        is_vendor_domain = bool(self.service_domain) and (
            service_domain == self.service_domain
        )
        is_safe_read = (service_domain, service_name) == (
            "nordpool",
            "get_prices_for_date",
        ) or (is_vendor_domain and service_name in vendor_safe_reads)

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
            category=category
            or (
                "battery_control"
                if service_domain in ["number", "input_number", "switch"]
                else ("inverter_control" if is_vendor_domain else "other")
            ),
            context=context,
            suppress_retry_warnings=suppress_retry_warnings,
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

    def get_consumption_overlay_blocks(self) -> list[OverlayBlock]:
        """Read the user's declared changes to expected consumption (issue #428).

        Returns:
            The blocks declared on the overlay entity's ``blocks`` attribute,
            or an empty list when no overlay entity is configured. "No
            overlay" is a supported configuration, not a degraded one — it is
            what an install that never sets one up keeps running.

        Raises:
            ConsumptionOverlayError: If an overlay entity IS configured but
                its ``blocks`` attribute is absent and the state offers no
                better explanation, or the blocks it holds are malformed. A
                user who declared an EV session is better served by an error
                than by an optimization that quietly ignored it.

        """
        if not self.sensors.get("consumption_overlay"):
            return []

        entity_id, _ = self._resolve_entity_id("consumption_overlay")
        response = self._api_request(
            "get",
            f"/api/states/{entity_id}",
            operation="Read planned consumption changes",
            category="CONSUMPTION_OVERLAY",
            context={"entity_id": entity_id},
        )
        if not response:
            raise ConsumptionOverlayError(
                f"Planned consumption changes entity '{entity_id}' returned no state"
            )

        # `blocks` is the data; `state` is incidental. A template sensor's
        # state commonly comes from an unrelated helper (per the docs'
        # example, an input_boolean) that can itself go "unknown" while
        # `blocks` still renders correctly -- gating on state alone would
        # make that documented example a schedule-stopper. Check `blocks`
        # first, and fall back to reporting the state only when there is no
        # data to fall back on.
        attributes = response.get("attributes") or {}
        if "blocks" in attributes:
            return parse_overlay_blocks(attributes["blocks"])

        state = response.get("state")
        if state in ("unavailable", "unknown", None):
            raise ConsumptionOverlayError(
                f"Planned consumption changes entity '{entity_id}' is {state}"
            )

        raise ConsumptionOverlayError(
            f"Planned consumption changes entity '{entity_id}' has no 'blocks' "
            f"attribute (found: {sorted(attributes)})"
        )

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
        if raw_value is None:
            raise SystemConfigurationError("48h_avg_grid_import sensor not available")
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
        if response is None:
            raise SystemConfigurationError("HA /api/config returned no data")
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
        self._set_number_like(entity_id, charge_stop_soc, "Set charge stop SOC")

    def get_discharge_stop_soc(self):
        """Get the discharge stop state of charge (SOC)."""
        return self._get_sensor_value("battery_discharge_stop_soc")

    def set_discharge_stop_soc(self, discharge_stop_soc):
        """Set the discharge stop state of charge (SOC)."""
        entity_id = self._get_entity_for_service("battery_discharge_stop_soc")
        self._set_number_like(entity_id, discharge_stop_soc, "Set discharge stop SOC")

    def get_charging_power_rate(self):
        """Get the charging power rate."""
        return self._get_sensor_value("battery_charging_power_rate")

    def set_charging_power_rate(self, rate):
        """Set the charging power rate."""
        entity_id = self._get_entity_for_service("battery_charging_power_rate")
        self._set_number_like(entity_id, rate, "Set charging power rate")

    def get_discharging_power_rate(self):
        """Get the discharging power rate."""
        return self._get_sensor_value("battery_discharging_power_rate")

    def set_discharging_power_rate(self, rate):
        """Set the discharging power rate."""
        entity_id = self._get_entity_for_service("battery_discharging_power_rate")
        self._set_number_like(entity_id, rate, "Set discharging power rate")

    def _is_shared_signed_battery_power(self) -> bool:
        """True when battery charge/discharge power resolve to one signed entity.

        Native SolaX and Huawei LUNA2000 expose battery power as a single
        signed register instead of separate charge/discharge entities.
        get_battery_charge_power/get_battery_discharge_power detect this case
        and split the one raw reading by sign instead of reading the entity
        twice unmodified.
        """
        charge_entity = self.sensors.get("battery_charge_power")
        discharge_entity = self.sensors.get("battery_discharge_power")
        return bool(
            self.battery_power_polarity
            and charge_entity
            and charge_entity == discharge_entity
        )

    def _split_signed_battery_power(self, raw: float, *, charging: bool) -> float:
        """Split one signed battery reading into the requested direction.

        Branches on battery_power_polarity rather than assuming it, so that an
        unimplemented or typo'd entry in PLATFORM_BATTERY_POWER_POLARITY fails
        loudly instead of reporting every charge as a discharge and vice versa.
        "charge_positive" is the only value that map holds today.

        Raises:
            ValueError: If battery_power_polarity is not a recognised value.
        """
        if self.battery_power_polarity != "charge_positive":
            raise ValueError(
                f"Unknown battery_power_polarity '{self.battery_power_polarity}' — "
                "cannot split the signed battery power sensor"
            )
        return max(0.0, raw if charging else -raw)

    def get_battery_charge_power(self):
        """Get current battery charging power in watts."""
        if self._is_shared_signed_battery_power():
            raw = self._get_sensor_value("battery_charge_power")
            if raw is None:
                return None
            return self._split_signed_battery_power(raw, charging=True)
        return self._get_sensor_value("battery_charge_power")

    def get_battery_discharge_power(self):
        """Get current battery discharging power in watts."""
        if self._is_shared_signed_battery_power():
            raw = self._get_sensor_value("battery_charge_power")
            if raw is None:
                return None
            return self._split_signed_battery_power(raw, charging=False)
        return self._get_sensor_value("battery_discharge_power")

    def _set_number_like(
        self, entity_id: str, value, operation: str, category: str | None = None
    ) -> None:
        """Write a value to a number-like entity.

        Supports both `number.*` (platform-native) and `input_number.*`
        (user-configured helper) entities. The entity domain is detected
        from the configured entity_id prefix.
        """
        domain = "input_number" if entity_id.startswith("input_number.") else "number"
        self._service_call_with_retry(
            domain,
            "set_value",
            operation=operation,
            category=category,
            entity_id=entity_id,
            value=value,
        )

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

    def get_huawei_working_mode(self) -> str | None:
        """Get the current Huawei battery working mode (e.g. 'time_of_use_luna2000')."""
        return self._get_raw_state("huawei_working_mode")

    def get_huawei_working_mode_options(self) -> list[str]:
        """Get the working-mode select entity's available options.

        The huawei_solar integration removes 'time_of_use_luna2000' from
        this list on LG RESU installs and 'time_of_use_lg' on LUNA2000
        installs (select.py: StorageModeSelectEntity.__init__) — this is
        the integration itself telling us which battery family is
        connected, rather than BESS inferring it from an undocumented
        device-info field. Used by HuaweiController to refuse LG RESU
        installs with a clear error instead of writing LUNA2000-format
        TOU periods against them.

        Returns:
            List of option strings, or [] if the entity is unavailable.

        Raises:
            ValueError: If the working-mode sensor isn't configured.
        """
        entity_id = self._get_entity_for_service("huawei_working_mode")
        response = self._api_request(
            "get",
            f"/api/states/{entity_id}",
            operation="Read Huawei working mode options",
            category="config",
        )
        if not response:
            return []
        return list(response.get("attributes", {}).get("options", []))

    def set_huawei_working_mode(self, option: str) -> None:
        """Set the Huawei battery working mode via the standard select entity.

        Args:
            option: One of the StorageWorkingModesC option strings, lowercased
                (e.g. "time_of_use_luna2000").

        Raises:
            ValueError: If the working-mode sensor isn't configured.
        """
        entity_id = self._get_entity_for_service("huawei_working_mode")
        self._service_call_with_retry(
            "select",
            "select_option",
            operation=f"Set Huawei working mode to {option}",
            entity_id=entity_id,
            option=option,
        )

    def write_huawei_tou_periods(self, periods_text: str) -> None:
        """Write the Huawei battery's TOU period list via huawei_solar.set_tou_periods.

        Args:
            periods_text: Newline-joined period lines, each
                "HH:MM-HH:MM/<days>/<+|->" (+ = charge, - = discharge).

        Raises:
            SystemConfigurationError: If huawei_device_id is not configured.
        """
        if not self.huawei_device_id:
            raise SystemConfigurationError(
                "Huawei battery device_id not configured. Run the setup wizard "
                "to configure the inverter."
            )
        self._service_call_with_retry(
            self._vendor_service_domain(),
            "set_tou_periods",
            operation="Write Huawei TOU periods",
            device_id=self.huawei_device_id,
            periods=periods_text,
        )

    def read_huawei_tou_periods(self) -> list[str]:
        """Read the TOU period list currently programmed on the battery.

        The huawei_solar integration has no read_tou_periods service, but
        HuaweiSolarTOUSensorEntity publishes the periods as "Period N" extra
        state attributes in the same text format set_tou_periods accepts
        (wlcrs/huawei_solar sensor.py:2487-2513), so this is a public entity
        read, not coordinator internals.

        Returns:
            Period lines "HH:MM-HH:MM/<days>/<+|->", ordered by period number.
            Empty when the battery holds no periods.

        Raises:
            ValueError: If the TOU period sensor isn't configured.
            SystemConfigurationError: If the entity can't be read. An
                unreadable entity must not be reported as "no periods
                programmed" — that would let BESS skip a needed write (the
                distinction #552 drew for Growatt MIN).
        """
        entity_id = self._get_entity_for_service("huawei_tou_periods")
        response = self._api_request(
            "get",
            f"/api/states/{entity_id}",
            operation="Read Huawei TOU periods",
            category="sensor_read",
        )
        if not response or response.get("state") in ("unavailable", "unknown", None):
            raise SystemConfigurationError(
                f"Huawei TOU period sensor '{entity_id}' is unreadable "
                f"(state={response.get('state') if response else None})"
            )

        attributes = response.get("attributes", {})
        numbered = [
            (int(key.removeprefix("Period ")), str(value))
            for key, value in attributes.items()
            if key.startswith("Period ") and key.removeprefix("Period ").isdigit()
        ]
        return [text for _, text in sorted(numbered)]

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
            self._vendor_service_domain(),
            "update_time_segment",
            operation=f"Write TOU segment {segment_id}: {batt_mode} {start_time}-{end_time} ({enabled_str})",
            **service_params,
        )

    def read_inverter_time_segments(self):
        """Read all time segments from the inverter with retry logic.

        Raises on a failed or unrecognizable read. An empty list is a valid
        answer meaning "no segments programmed" and must stay distinguishable
        from failure: callers diff against this to decide what to write, and
        a failure silently reported as [] would make them rewrite every
        segment blind (issue #551).
        """
        service_params: dict[str, str | bool] = {"return_response": True}

        # Require device_id before attempting the API call
        if not self.growatt_device_id:
            raise SystemConfigurationError(
                "Growatt device_id not configured. Run the setup wizard to configure the inverter."
            )

        service_params["device_id"] = self.growatt_device_id

        # Transport errors propagate: _service_call_with_retry has already
        # exhausted its retries by the time it raises.
        result = self._service_call_with_retry(
            self._vendor_service_domain(),
            "read_time_segments",
            operation=None,
            **service_params,
        )

        if result and "service_response" in result:
            service_response = result["service_response"]
            if "time_segments" in service_response:
                return service_response["time_segments"]

        raise ValueError(
            f"Unexpected response format from read_time_segments: {result!r}"
        )

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

        Uses select.select_option for mode/enabled and time.set_value for
        begin/end (solax_modbus's Growatt plugin only exposes those as
        `time.*` domain entities), then button.press to commit the slot to
        the inverter.

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

        # solax_modbus's Growatt plugin exposes TOU begin/end only as `time.*`
        # domain entities (no `select.*` equivalent exists), so those two
        # fields must go through time.set_value; select.select_option
        # against a time.* entity id is a silent HA no-op (issue #362/#181).
        select_writes = [
            (f"{prefix}_enabled", enabled_option),
            (f"{prefix}_mode", mode_option),
        ]
        time_writes = [
            (f"{prefix}_begin", start_time),
            (f"{prefix}_end", end_time),
        ]

        for sensor_key, option in select_writes:
            entity_id = self._get_entity_for_service(sensor_key)
            self._service_call_with_retry(
                "select",
                "select_option",
                operation=f"TOU slot {segment_id} set {sensor_key}={option}",
                entity_id=entity_id,
                option=option,
            )

        for sensor_key, hhmm in time_writes:
            entity_id = self._get_entity_for_service(sensor_key)
            self._service_call_with_retry(
                "time",
                "set_value",
                operation=f"TOU slot {segment_id} set {sensor_key}={hhmm}",
                entity_id=entity_id,
                time=f"{hhmm}:00",
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
                enabled_state = self._api_request(
                    "get", f"/api/states/{enabled_id}", optional=True
                )
                begin_state = self._api_request(
                    "get", f"/api/states/{begin_id}", optional=True
                )
                end_state = self._api_request(
                    "get", f"/api/states/{end_id}", optional=True
                )
                mode_state = self._api_request(
                    "get", f"/api/states/{mode_id}", optional=True
                )

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

    # ── Solis solis_modbus entity-based TOU period control ─────────────────
    # Solis (TX-Modbus) writes each period directly to HA entities, unlike
    # SPH's atomic growatt_server service calls. Charge/discharge period
    # start/end are `time` entities; per-slot enable is a `switch` entity
    # (see SOLIS_SUFFIX_MAP for the verified unique_id -> BESS sensor key
    # derivation). Sensor keys: solis_{charge,discharge}_{start,end}_N and
    # solis_{charge,discharge}_enable_N for N in 1..6.

    def write_solis_period(
        self,
        direction: str,
        slot: int,
        start_time: str,
        end_time: str,
        enabled: bool,
    ) -> None:
        """Write one Solis Grid TOU v2 charge or discharge period (slot 1-6).

        Args:
            direction: "charge" or "discharge"
            slot: TOU slot number (1-6)
            start_time: Start time "HH:MM"
            end_time: End time "HH:MM"
            enabled: Whether the period's enable switch should be on
        """
        if direction not in ("charge", "discharge"):
            raise ValueError(
                f"direction must be 'charge' or 'discharge', got {direction!r}"
            )

        start_key = f"solis_{direction}_start_{slot}"
        end_key = f"solis_{direction}_end_{slot}"
        enable_key = f"solis_{direction}_enable_{slot}"

        start_entity = self._get_entity_for_service(start_key)
        end_entity = self._get_entity_for_service(end_key)
        enable_entity = self._get_entity_for_service(enable_key)

        self._service_call_with_retry(
            "time",
            "set_value",
            operation=f"Solis {direction} slot {slot} start={start_time}",
            entity_id=start_entity,
            time=f"{start_time}:00",
        )
        self._service_call_with_retry(
            "time",
            "set_value",
            operation=f"Solis {direction} slot {slot} end={end_time}",
            entity_id=end_entity,
            time=f"{end_time}:00",
        )
        self._service_call_with_retry(
            "switch",
            "turn_on" if enabled else "turn_off",
            operation=f"Solis {direction} slot {slot} enabled={enabled}",
            entity_id=enable_entity,
        )

    def read_solis_periods(self, direction: str) -> list[dict]:
        """Read all 6 Solis Grid TOU v2 periods for one direction from HA entity states.

        Args:
            direction: "charge" or "discharge"

        Returns:
            List of dicts with slot, start_time, end_time, enabled — only for
            slots whose entities are configured.
        """
        if direction not in ("charge", "discharge"):
            raise ValueError(
                f"direction must be 'charge' or 'discharge', got {direction!r}"
            )

        periods: list[dict] = []
        for slot in range(1, 7):
            try:
                start_entity = self._get_entity_for_service(
                    f"solis_{direction}_start_{slot}"
                )
                end_entity = self._get_entity_for_service(
                    f"solis_{direction}_end_{slot}"
                )
                enable_entity = self._get_entity_for_service(
                    f"solis_{direction}_enable_{slot}"
                )
            except ValueError:
                logger.debug(
                    "Solis %s slot %d entities not configured, skipping",
                    direction,
                    slot,
                )
                continue

            try:
                start_state = self._api_request("get", f"/api/states/{start_entity}")
                end_state = self._api_request("get", f"/api/states/{end_entity}")
                enable_state = self._api_request("get", f"/api/states/{enable_entity}")

                start_time = str(start_state.get("state", "00:00:00"))[:5]
                end_time = str(end_state.get("state", "00:00:00"))[:5]
                enabled = enable_state.get("state") == "on"

                periods.append(
                    {
                        "slot": slot,
                        "start_time": start_time,
                        "end_time": end_time,
                        "enabled": enabled,
                    }
                )
            except Exception as e:
                logger.warning(
                    "Failed to read Solis %s slot %d: %s", direction, slot, e
                )

        return periods

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
            self._vendor_service_domain(),
            "write_ac_charge_times",
            None,
            **service_params,
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
                self._vendor_service_domain(),
                "read_ac_charge_times",
                None,
                **service_params,
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
            self._vendor_service_domain(),
            "write_ac_discharge_times",
            None,
            **service_params,
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
                self._vendor_service_domain(),
                "read_ac_discharge_times",
                None,
                **service_params,
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
        self._set_number_like(power_entity, watts, "SolaX VPP set active power")
        self._set_number_like(repeat_entity, 1200, "SolaX VPP set autorepeat duration")
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
        self._set_number_like(entity_id, min_soc, "SolaX set battery minimum SOC")

    def get_solax_power_control_mode(self) -> str | None:
        """Read the current SolaX power control mode."""
        return self._get_raw_state("solax_power_control_mode")

    def get_solax_min_soc(self) -> float | None:
        """Read the current battery minimum SOC from the SolaX inverter."""
        return self._get_sensor_value("solax_battery_min_soc")

    # ── Growatt VPP remote power control (solax_modbus GEN3|GEN4) ─────────────
    #
    # VPP registers (30100/30407/30408/30409/30410) are available on both
    # Growatt GEN3 (MIX/SPA/SPH) and GEN4 (MIN/MOD/MID) via the solax_modbus
    # Growatt plugin — verified against plugin_growatt.py NUMBER_TYPES /
    # SELECT_TYPES (allowedtypes=GEN3|GEN4). Unlike TOU slots, VPP gives
    # per-period power control with no persistent schedule (see issue #118).

    def set_growatt_vpp_status(self, enabled: bool) -> None:
        """Enable/disable the Growatt VPP Status register (30100).

        Written once at startup (or after a restart finds it disabled) —
        VPP Remote Control has no effect while VPP Status is disabled.
        """
        entity_id = self._get_entity_for_service("growatt_vpp_status")
        option = "Enabled" if enabled else "Disabled"
        logger.info("Growatt VPP: status -> %s", option)
        self._service_call_with_retry(
            "select",
            "select_option",
            operation=f"Growatt VPP status -> {option}",
            entity_id=entity_id,
            option=option,
        )

    def set_growatt_vpp_allow_ac_charging(self, enabled: bool) -> None:
        """Enable/disable AC charging via the Growatt VPP register (30410).

        Written once at startup — controls whether ``vpp_power`` may charge
        the battery from the grid (positive values) as opposed to solar-only.
        """
        entity_id = self._get_entity_for_service("growatt_vpp_allow_ac_charging")
        option = "Enabled" if enabled else "Disabled"
        logger.info("Growatt VPP: allow AC charging -> %s", option)
        self._service_call_with_retry(
            "select",
            "select_option",
            operation=f"Growatt VPP allow AC charging -> {option}",
            entity_id=entity_id,
            option=option,
        )

    def set_growatt_vpp_period(
        self, remote_control_enabled: bool, power_pct: int, fallback_minutes: int
    ) -> None:
        """Write one period's VPP command: power, fallback timer, remote control.

        Register 30407 (remote control) is the commit: Growatt VPP has no
        separate trigger entity, so enabling it executes whatever 30409/30408
        currently hold. Both are therefore written *before* arming, and the
        power latch is cleared on release — otherwise the next activation
        arms against the previous active period's value, which can be ±100%
        (issue #593).

        ``vpp_time`` is rewritten every period the command is active, resetting
        the inverter's own fallback timer (register 30408) — if BESS stops
        writing (crash, restart), the inverter reverts to ``load_first`` on its
        own once the timer lapses, giving a hardware dead-man's-switch.

        Either way a power/timer failure is fail-safe: on activation it leaves
        remote control untouched, so the period degrades to ``load_first``
        self-use instead of executing a stale command; on release the disable
        has already landed, so only the latch-clearing courtesy is lost.

        Args:
            remote_control_enabled: Whether VPP Remote Control (30407) should
                be enabled for this period. False reverts the inverter to
                load_first and zeroes 30409.
            power_pct: Target power as a percentage (-100..100). Negative =
                discharge/export, positive = charge from grid. Ignored when
                ``remote_control_enabled`` is False, which always writes 0.
            fallback_minutes: Value to (re)write to ``vpp_time`` (30408) when
                ``remote_control_enabled`` is True.
        """
        remote_control_entity = self._get_entity_for_service(
            "growatt_vpp_remote_control"
        )
        option = "Enabled" if remote_control_enabled else "Disabled"
        logger.info(
            "Growatt VPP: remote control -> %s%s",
            option,
            f", power={power_pct}%" if remote_control_enabled else "",
        )

        def _arm(value: str) -> None:
            self._service_call_with_retry(
                "select",
                "select_option",
                operation=f"Growatt VPP remote control -> {value}",
                entity_id=remote_control_entity,
                option=value,
            )

        if not remote_control_enabled:
            # Release first, then clear the latch. Writing 0 while remote
            # control is still Enabled would select the grid_first hold for
            # the duration, changing release behaviour on every load_first
            # entry; this order leaves release identical to before.
            #
            # The power entity is resolved only *after* the disable has
            # landed: getting back to load_first is the safety-critical half,
            # and clearing the latch is a courtesy to the next activation, so
            # a mis-provisioned power entity must not block the release.
            _arm("Disabled")
            power_entity = self._get_entity_for_service("growatt_vpp_power")
            self._set_number_like(
                power_entity, 0, "Growatt VPP clear power latch -> 0%"
            )
            return

        # Resolved before any write, so a mis-provisioned install fails with
        # the inverter untouched rather than armed on a stale command.
        power_entity = self._get_entity_for_service("growatt_vpp_power")
        self._set_number_like(
            power_entity, power_pct, f"Growatt VPP set power -> {power_pct}%"
        )

        time_entity = self._get_entity_for_service("growatt_vpp_time")
        self._set_number_like(
            time_entity,
            fallback_minutes,
            f"Growatt VPP reset fallback timer -> {fallback_minutes} min",
        )

        # Arm last: enabling remote control IS the commit on Growatt VPP.
        _arm("Enabled")

    # ── Growatt export-limit curtailment (registers 122/123) ──────────────────
    #
    # See issue #269 — requires a grid CT/smart meter. Curtailing writes
    # "Meter 1" (use the CT meter to throttle PV/MPPT production) and 0%
    # (strict zero export); releasing writes "Disabled" only — the register
    # 123 percentage is meaningless once the meter selection is disabled, so
    # it's left untouched (and the negative range on 123 means "allow this
    # much import," never written here).

    def set_growatt_export_limit(self, curtail: bool) -> None:
        """Enable/disable PV export curtailment via the CT-meter export limit."""
        mode_entity = self._get_entity_for_service("growatt_export_limit_mode")
        option = "Meter 1" if curtail else "Disabled"
        logger.info("Growatt export limit: mode -> %s", option)
        self._service_call_with_retry(
            "select",
            "select_option",
            operation=f"Growatt export limit mode -> {option}",
            category="export_limit_curtailment",
            entity_id=mode_entity,
            option=option,
        )

        if not curtail:
            return

        value_entity = self._get_entity_for_service("growatt_export_limit_value")
        self._set_number_like(
            value_entity,
            0,
            "Growatt export limit -> 0% (curtail)",
            category="export_limit_curtailment",
        )

    def get_growatt_vpp_status(self) -> str | None:
        """Read the current Growatt VPP Status register state."""
        return self._get_raw_state("growatt_vpp_status")

    def get_growatt_vpp_remote_control(self) -> str | None:
        """Read the current Growatt VPP Remote Control register state."""
        return self._get_raw_state("growatt_vpp_remote_control")

    def get_growatt_vpp_allow_ac_charging(self) -> str | None:
        """Read the current Growatt VPP allow-AC-charging register state.

        Both flash registers the VPP path writes at startup need a read-back,
        not just VPP Status: they are written together but can drift apart (a
        user toggle, a firmware reset, or a write that failed after the first
        of the two), and an install with Status Enabled but AC charging
        Disabled cannot execute GRID_CHARGING at all.
        """
        return self._get_raw_state("growatt_vpp_allow_ac_charging")

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

        return solcast_detailed_hourly_to_quarterly(hourly_data)

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

    def _is_shared_signed_grid_power(self) -> bool:
        """True when import_power/export_power resolve to one signed entity.

        Some platforms (Solis) expose grid power as a single signed sensor
        instead of separate import/export entities. get_import_power/
        get_export_power detect this case and split the one raw reading by
        sign instead of reading the entity twice unmodified.
        """
        import_entity = self.sensors.get("import_power")
        export_entity = self.sensors.get("export_power")
        return bool(
            self.grid_power_polarity
            and import_entity
            and import_entity == export_entity
        )

    def _split_signed_grid_power(self, raw: float, *, importing: bool) -> float:
        """Split one signed grid reading into the requested direction.

        Anything that is not "import_positive" is treated as
        "export_positive" — the two values PLATFORM_GRID_POWER_POLARITY holds.
        """
        positive_is_import = self.grid_power_polarity == "import_positive"
        return max(0.0, raw if importing == positive_is_import else -raw)

    def get_import_power(self):
        """Get current grid import power in watts."""
        if self._is_shared_signed_grid_power():
            raw = self._get_sensor_value("import_power")
            if raw is None:
                return None
            return self._split_signed_grid_power(raw, importing=True)
        return self._get_sensor_value("import_power")

    def get_export_power(self):
        """Get current grid export power in watts."""
        if self._is_shared_signed_grid_power():
            raw = self._get_sensor_value("import_power")
            if raw is None:
                return None
            return self._split_signed_grid_power(raw, importing=False)
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

        Falls through to the derived path whenever the direct reading is
        missing — the gate is the runtime value, not the platform, so an
        unmapped *or* momentarily unavailable entity reaches it. SolaX native
        has no native load register at all and always takes the derived path.
        Solis exposes one natively (solis_modbus register 33177) and Huawei
        does on EMMA installs with the entity enabled (#730); both take the
        derived path only when that sensor is absent or unreadable, as any
        other platform does.

        The derived value comes from the energy balance (see
        :func:`core.bess.energy_balance.derive_load_consumption`), which needs
        all five counters. Returns ``None`` when any is unreadable — the
        battery terms are not optional, and dropping them reports load plus
        net battery charge (issue #528) — and also when the balance comes out
        negative, which on monotonic lifetime totals means a counter is
        stalled or under-reporting rather than rounding noise.
        """
        direct = self._get_sensor_value("lifetime_load_consumption")
        if direct is not None:
            return direct

        # Derive from other lifetime sensors when direct sensor unavailable
        inputs = {
            "lifetime_solar_energy": self._get_sensor_value("lifetime_solar_energy"),
            "lifetime_import_from_grid": self._get_sensor_value(
                "lifetime_import_from_grid"
            ),
            "lifetime_export_to_grid": self._get_sensor_value(
                "lifetime_export_to_grid"
            ),
            "lifetime_battery_charged": self._get_sensor_value(
                "lifetime_battery_charged"
            ),
            "lifetime_battery_discharged": self._get_sensor_value(
                "lifetime_battery_discharged"
            ),
        }
        missing = [key for key, value in inputs.items() if value is None]
        if missing:
            # Name the counters, so "N/A" in the health check is traceable to
            # a specific unmapped or unavailable sensor rather than silent.
            logger.warning(
                "Cannot derive lifetime load consumption: %s unreadable "
                "(unmapped or unavailable). All five counters are required.",
                ", ".join(missing),
            )
            return None
        solar = inputs["lifetime_solar_energy"]
        grid_import = inputs["lifetime_import_from_grid"]
        grid_export = inputs["lifetime_export_to_grid"]
        battery_charged = inputs["lifetime_battery_charged"]
        battery_discharged = inputs["lifetime_battery_discharged"]
        derived = derive_load_consumption(
            solar_production=solar,
            import_from_grid=grid_import,
            export_to_grid=grid_export,
            battery_charged=battery_charged,
            battery_discharged=battery_discharged,
        )
        if derived < 0:
            # Report the inputs rather than a laundered number: a health check
            # showing a plausible value would hide the broken counter.
            logger.warning(
                "Derived lifetime load consumption is negative (%.1f kWh) - "
                "lifetime counters disagree, so no value can be reported. "
                "solar=%.1f import=%.1f export=%.1f charged=%.1f discharged=%.1f",
                derived,
                solar,
                grid_import,
                grid_export,
                battery_charged,
                battery_discharged,
            )
            return None
        return derived

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

    def get_device_maps(self, ttl_seconds: int = 900) -> tuple[dict, dict]:
        """Return ``entity_id -> device_id`` and ``device_id -> name`` maps.

        Fetches the HA entity and device registries in one WebSocket
        connection and builds both maps. Results are cached for
        ``ttl_seconds`` so the 5-minute health check does not re-fetch the
        full registries every run; the TTL self-heals after a sensor is
        reconfigured.

        Raises:
            SystemConfigurationError: If the HA registries cannot be
                queried — the banner call site decides explicitly whether a
                registry failure degrades the grouping or surfaces.
        """
        now = time.time()
        if (
            self._device_maps_cache is not None
            and now - (self._device_maps_cache_ts or 0) < ttl_seconds
        ):
            return self._device_maps_cache
        try:
            results = self._ws_query(
                [
                    {"type": "config/entity_registry/list"},
                    {"type": "config/device_registry/list"},
                ]
            )
            entity_to_device = {
                entry["entity_id"]: entry.get("device_id")
                for entry in results[0]
                if entry.get("entity_id") and entry.get("device_id")
            }
            device_names = {
                device["id"]: device.get("name") or device["id"]
                for device in results[1]
                if device.get("id")
            }
            self._device_maps_cache = (entity_to_device, device_names)
            self._device_maps_cache_ts = now
            return self._device_maps_cache
        except Exception as e:
            raise SystemConfigurationError(
                f"Failed to query Home Assistant device/entity registries: {e}"
            ) from e

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

    def get_history_period(
        self,
        entity_ids: list[str],
        start_time: str,
        end_time: str,
    ) -> list[list[dict]]:
        """Fetch raw state history for entities via the REST history endpoint.

        Wraps ``GET /api/history/period/<start_time>`` — Home Assistant's
        recorder-backed history API. Used by ``ha_recorder_helper`` to
        reconstruct per-period energy actuals without an external time-series
        database.

        The response is one list of state entries per requested entity, in the
        request's entity order. ``minimal_response`` means only the first entry
        of each list carries ``entity_id``; later entries carry just ``state``
        and ``last_changed`` / ``last_updated``. HA also prepends the state as
        it was at ``start_time``, so a caller does not need a separate "value
        before the window" query.

        Args:
            entity_ids: Full entity IDs to fetch (e.g. ``["sensor.x", ...]``).
            start_time: ISO 8601 timestamp for range start.
            end_time: ISO 8601 timestamp for range end.

        Returns:
            List of per-entity state-entry lists. Empty list if HA returned no
            content.
        """
        path = f"/api/history/period/{start_time}"
        params = {
            "filter_entity_id": ",".join(entity_ids),
            "end_time": end_time,
            "minimal_response": "",
            "no_attributes": "",
        }
        result = self._api_request(
            "get",
            path,
            operation="Fetch recorder history period",
            category="historical_data",
            params=params,
        )
        return result or []

    def discover_ha_metadata(
        self,
        entity_registry: list[dict] | None = None,
    ) -> dict:
        """Discover HA-internal IDs via the WebSocket API.

        Queries the config entry and device registries to find:
        - Nordpool config_entry_id (required for nordpool.get_prices_for_date)
        - Growatt device_id (HA device registry ID for service calls)
        - Huawei battery device_id (HA device registry ID for service calls)

        Args:
            entity_registry: Pre-fetched entity registry list, or None to fetch.

        Returns:
            dict with keys: growatt_device_id, huawei_device_id,
            nordpool_config_entry_id
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
            config_entries_result, devices_result, entity_registry_result
        )

    def _parse_ha_metadata(
        self,
        config_entries_result: list[dict],
        devices_result: list[dict],
        entity_registry_result: list[dict],
    ) -> dict:
        """Parse config entries and device registry into BESS metadata.

        Pure parsing — no WebSocket calls.  Called by both
        ``discover_ha_metadata`` (standalone) and ``discover_integrations``
        (which fetches everything in a single WS connection).

        Returns:
            dict with keys: growatt_device_id, huawei_device_id,
            nordpool_config_entry_id, nordpool_area, detected_platforms,
            octopus_found
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

        # Find growatt device_id from device registry by matching the
        # config_entry belonging to growatt_server.  Real HA devices always
        # carry `config_entries`, so no identifier/serial-number fallback is
        # needed.
        growatt_device_id: str | None = None
        if growatt_config_entry_id:
            for device in devices_result:
                if growatt_config_entry_id in device.get("config_entries", []):
                    growatt_device_id = device["id"]
                    break

        # Find huawei_solar config_entry_id, then the *battery* device
        # within it (huawei_solar creates multiple devices per config entry —
        # inverter, battery, power meter, optional EMMA — so device_id must
        # be filtered to the one whose entities include the working-mode
        # marker, not just "any device on this config entry").
        huawei_config_entry_id: str | None = None
        for entry in config_entries_result:
            if entry.get("domain") == "huawei_solar" and entry.get("state") == "loaded":
                huawei_config_entry_id = entry["entry_id"]
                break

        huawei_device_id: str | None = None
        if huawei_config_entry_id:
            battery_entity_device_ids = {
                e.get("device_id")
                for e in entity_registry_result
                if e.get("platform") == "huawei_solar"
                and str(e.get("unique_id", "")).endswith(
                    f"_{self._HUAWEI_BATTERY_MARKER_SUFFIX}"
                )
            }
            for device in devices_result:
                if (
                    huawei_config_entry_id in device.get("config_entries", [])
                    and device.get("id") in battery_entity_device_ids
                ):
                    huawei_device_id = device["id"]
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

        solis_config_entry = any(
            entry.get("domain") == "solis_modbus" and entry.get("state") == "loaded"
            for entry in config_entries_result
        )
        if solis_config_entry and self._has_solis_tou_v2_entities(
            entity_registry_result
        ):
            detected_platforms.append("solis_modbus")

        logger.info(
            "WS discovery: nordpool_config_entry_id=%s, nordpool_area=%s, "
            "growatt_device_id=%s, huawei_device_id=%s, octopus_found=%s, "
            "detected_platforms=%s",
            nordpool_config_entry_id,
            nordpool_area,
            growatt_device_id,
            huawei_device_id,
            octopus_found,
            detected_platforms,
        )
        return {
            "growatt_device_id": growatt_device_id,
            "huawei_device_id": huawei_device_id,
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
        if states is None:
            raise SystemConfigurationError("HA /api/states returned no data")
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
        # Continental Nord Pool day-ahead areas (post-expansion):
        "NL": ("EUR", 1.21),
        "BE": ("EUR", 1.21),
        "DE": ("EUR", 1.19),
        "FR": ("EUR", 1.20),
        "AT": ("EUR", 1.20),
        "PL": ("PLN", 1.23),
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
            growatt_found, growatt_device_id,
            huawei_found, huawei_device_id,
            nordpool_found, nordpool_area, nordpool_config_entry_id,
            octopus_found, detected_inverter_platforms,
            detected_phase_count, currency, vat_multiplier.
            states is the raw list from /api/states for reuse by callers.
        """
        result: dict = {
            "growatt_found": False,
            "growatt_device_id": None,
            "solax_found": False,
            "solis_found": False,
            "huawei_found": False,
            "huawei_device_id": None,
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
        result["solis_found"] = inverter_detected.get("solis", False)
        result["huawei_found"] = inverter_detected.get("huawei", False)

        # ── States: Nordpool area ────────────────────────────────────────
        states = self._fetch_all_states()

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
            metadata = self._parse_ha_metadata(config_entries, devices, registry)
            result["growatt_device_id"] = metadata["growatt_device_id"]
            result["huawei_device_id"] = metadata.get("huawei_device_id")
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
        if result["solis_found"] and "solis_modbus" not in detected:
            if self._has_solis_tou_v2_entities(registry):
                detected.append("solis_modbus")
        if result["huawei_found"]:
            detected.append("huawei_solar_luna2000")
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
        - sensor.nordpool_kwh_se4_sek_2_10_025   -> SE4   (custom integration)
        - sensor.nordpool_kwh_no1_nok_3_10_025   -> NO1   (custom integration)
        - sensor.nord_pool_se3_current_price      -> SE3   (official HA)
        - sensor.nordpool_kwh_nl_eur_2_10_025    -> NL    (HACS continental)
        - sensor.nordpool_kwh_de_lu_eur_2_10_025 -> DE_LU (HACS DE-LU, HA slug)
        - nordpool_kwh_de-lu_eur_2_10_025        -> DE-LU (device registry identifier)
        """
        match = re.search(
            r"(?:^|_)(se[1-4]|no[1-5]|dk[12]|fi|ee|lt|lv|nl|be|de(?:[-_]lu)?|fr|at|pl)(?:_|$)",
            entity_id,
        )
        if match:
            return match.group(1).upper()
        return None

    def discover_current_sensors(self, states: list[dict]) -> dict[str, str]:
        """Discover phase current sensor entity IDs.

        Scans entity states for sensors with device_class 'current' that
        match household phase current naming, in two conventions:

        - ``current_l1``/``l2``/``l3`` (Tibber Pulse, Shelly 3EM, ...).
        - ``phase_a``/``b``/``c`` on a *metering* device (#120). huawei_solar
          names its three-phase meter's currents "Phase A/B/C current"
          (register keys ``active_grid_{A,B,C}_current``), which yields
          ``sensor.power_meter_phase_a_current``. The inverter's own AC output
          currents carry the identical display name and differ only by device
          prefix, so the phase_a/b/c form is only accepted on an entity whose
          id also marks it as a meter — binding fuse protection to the
          inverter's output instead of the house feed would silently protect
          the wrong circuit.

        Candidates are grouped by the device their entity_id belongs to (the
        entity id with its phase token blanked, see
        ``_phase_current_group_id``), and one group supplies every phase. Only
        groups exposing a set the rest of the system can act on —
        ``USABLE_PHASE_SETS`` — are eligible; the alternative is handing the
        wizard a two-phase count it rejects, or a set without L1 that makes
        PowerMonitor raise on every quarter. ``meter`` is a bare substring, so a
        sub-circuit meter (heat pump, EV charger) passes the gate too;
        selecting per phase independently would mix two devices into a reading
        set describing no real circuit. Preference, in order:

        1. The most phases. A one-phase EV-charger clamp must never beat a
           complete three-phase meter — the wizard derives the install's
           phase count from this result, so a short group silently configures
           single-phase fuse protection on a three-phase house.
        2. The explicit ``current_lN`` convention over inferred ``phase_a/b/c``
           naming. This matters on upgrade: an install with a dedicated clamp
           meter keeps it rather than repointing at a newly-discovered smart
           meter.
        3. A grid-side name (``GRID_ID_MARKERS``). Between two equally
           complete meters, ``power_meter`` is the house feed and
           ``easee_meter``/``heatpump_meter`` a sub-circuit carrying a
           fraction of it — binding to the latter under-protects the main
           fuse, which then trips without BESS ever throttling.
        4. Lowest group id, purely so the result is reproducible — never
           ``/api/states`` order, which is arbitrary and varies across
           restarts.

        A lone sub-circuit meter can still win when it is the only complete
        set and its name carries no grid marker; the wizard lets the user
        correct that, and such entities cannot be told apart by name alone on
        a discovery path with no unique_id suffix map. Phase count is
        deliberately ranked above the grid-side name, so a grid-named
        *single-phase* clamp loses to a complete three-phase sub-circuit set:
        the two orderings cannot both hold, and the alternative reinstates the
        worse failure — a one-phase group setting the wizard's phase count on
        a three-phase house.

        Args:
            states: List of state dicts from /api/states

        Returns:
            dict mapping phase key ('current_l1', 'current_l2', 'current_l3') ->
            entity_id for detected sensors. Empty dict if none found.
        """
        # group_id -> (convention_rank, {phase_key: entity_id})
        groups: dict[str, tuple[int, dict[str, str]]] = {}
        for state in states:
            entity_id = str(state.get("entity_id", ""))
            if not entity_id.startswith("sensor."):
                continue
            attrs = state.get("attributes", {})
            if attrs.get("device_class") != "current":
                continue
            lower_id = entity_id.lower()
            matched = self._match_phase_current_key(lower_id)
            if not matched:
                continue
            key, pattern, rank = matched
            group_id = self._phase_current_group_id(lower_id, pattern)
            _, phases = groups.setdefault(group_id, (rank, {}))
            phases.setdefault(key, entity_id)

        usable = {
            gid: value
            for gid, value in groups.items()
            if set(value[1]) in self.USABLE_PHASE_SETS
        }
        if not usable:
            if groups:
                logger.info(
                    "Phase currents: %d candidate device(s), none exposing a "
                    "usable phase set (L1, or L1+L2+L3): %s",
                    len(groups),
                    ", ".join(sorted(groups)),
                )
            logger.info("Discovered 0 phase current sensor(s)")
            return {}

        group_id, (_, result) = min(
            usable.items(),
            key=lambda kv: (
                -len(kv[1][1]),
                kv[1][0],
                self._grid_side_rank(kv[0]),
                kv[0],
            ),
        )
        if len(usable) > 1:
            logger.info(
                "Phase currents: %d candidate device(s), selected %s",
                len(usable),
                group_id,
            )
        logger.info("Discovered %d phase current sensor(s)", len(result))
        return dict(result)

    # Household phase-current naming conventions: (pattern, phase key,
    # meter-gated, convention rank). Lower rank wins when one install exposes
    # both conventions — the explicit current_lN form is a deliberate
    # household-phase naming, phase_a/b/c is inferred from a meter's own
    # per-phase registers. The phase_a/b/c form is meter-gated; see
    # discover_current_sensors.
    PHASE_CURRENT_PATTERNS: ClassVar[tuple[tuple[str, str, bool, int], ...]] = (
        ("current_l1", "current_l1", False, 0),
        ("current_l2", "current_l2", False, 0),
        ("current_l3", "current_l3", False, 0),
        ("phase_a", "current_l1", True, 1),
        ("phase_b", "current_l2", True, 1),
        ("phase_c", "current_l3", True, 1),
    )

    # Entity-id marker identifying a metering device, used to keep the
    # phase_a/b/c form off the inverter's own output currents.
    METER_ID_MARKER: ClassVar[str] = "meter"

    # Entity-id markers naming the *house feed* rather than a sub-circuit.
    # Only used to break a tie between equally complete candidate groups; see
    # discover_current_sensors.
    GRID_ID_MARKERS: ClassVar[tuple[str, ...]] = ("power_meter", "grid")

    # The only phase sets the rest of the system can act on: the wizard
    # accepts a detected phase count of 1 or 3 and nothing else, and
    # PowerMonitor reads current_l1 unconditionally. A group missing L1, or
    # holding exactly two phases, would configure fuse protection that raises
    # on every quarter — reporting nothing found is the honest outcome.
    USABLE_PHASE_SETS: ClassVar[tuple[frozenset[str], ...]] = (
        frozenset({"current_l1"}),
        frozenset({"current_l1", "current_l2", "current_l3"}),
    )

    def _grid_side_rank(self, group_id: str) -> int:
        """0 when a candidate group's id names the house feed, else 1."""
        return 0 if any(m in group_id for m in self.GRID_ID_MARKERS) else 1

    def _phase_current_group_id(self, lower_id: str, pattern: str) -> str:
        """Identify the device a phase-current entity belongs to.

        The entity id with its phase token blanked out. HA appends ``_2`` to
        an entity id that collides with an existing one, which happens per
        entity and so can hit a single phase of an otherwise uniform set
        (``..._current_l3_2``); that suffix is stripped, or the meter would
        split into two groups and lose the phases it really has.
        """
        return re.sub(r"_\d+$", "", lower_id.replace(pattern, "*"))

    def _match_phase_current_key(self, lower_id: str) -> tuple[str, str, int] | None:
        """Match a current sensor's entity_id to a phase.

        Returns (phase_key, matched_pattern, convention_rank), or None. The
        pattern is returned so the caller can derive the owning device's group
        id by blanking it out of the entity_id.

        Patterns match on token boundaries, not bare substrings: a meter that
        exposes line-to-line currents names them ``phase_ab``, which must not
        be read as phase A.
        """
        is_meter = self.METER_ID_MARKER in lower_id
        for pattern, key, meter_only, rank in self.PHASE_CURRENT_PATTERNS:
            if not re.search(
                rf"(?<![a-z0-9]){re.escape(pattern)}(?![a-z0-9])", lower_id
            ):
                continue
            if meter_only and not is_meter:
                continue
            return key, pattern, rank
        return None

    def _match_optional_sensor(
        self, entity_id: str, lower_id: str
    ) -> tuple[str, str] | None:
        """Match a single entity to an optional sensor key.

        Returns (sensor_key, entity_id) if matched, None otherwise.
        """
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

    def discover_optional_sensors(
        self, states: list[dict], entity_registry: list[dict] | None = None
    ) -> dict[str, str]:
        """Discover optional integration sensors.

        Uses the entity registry (unique_id) for Solcast detection and entity
        states for weather, consumption forecast, and discharge inhibit
        sensors.

        Args:
            states: List of state dicts from /api/states
            entity_registry: Entity registry list (for Solcast detection).

        Returns:
            dict mapping sensor_key -> entity_id for detected optional sensors
        """
        result: dict[str, str] = {}

        if entity_registry is not None:
            # Solcast forecast sensors are optional — a disabled one is
            # simply left unconfigured, nothing to report to the wizard.
            solcast, _solcast_disabled = self._map_registry_entities(
                entity_registry, ["solcast_solar"], self.SOLCAST_SUFFIX_MAP
            )
            result.update(solcast)

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
        "solis": ["solis_modbus"],
        "huawei": ["huawei_solar"],
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

    _HUAWEI_BATTERY_MARKER_SUFFIX: ClassVar[str] = (
        "storage_working_mode_settings"  # only present on battery-equipped Huawei installs
    )

    _SOLAX_PLATFORMS: ClassVar[set[str]] = {"solax_modbus", "solax"}

    # Solis: "solis_modbus" is a dedicated integration domain (unlike
    # solax_modbus, which multiplexes several inverter brands), so platform
    # match alone already identifies it uniquely. The marker below confirms
    # the installed inverter actually exposes the Grid Time of Use v2
    # schedule (InverterFeature.V2 gates it in time_sensors.py:31) rather
    # than an older Solis hybrid without local TOU control.
    _SOLIS_PLATFORMS: ClassVar[set[str]] = {"solis_modbus"}
    _SOLIS_TOU_MARKER_SUFFIX: ClassVar[str] = (
        "time_entity_43711"  # Grid TOU v2 Charge Start (Slot 1)
    )

    def _has_solis_tou_v2_entities(self, entities: list[dict]) -> bool:
        """Check for Solis Grid Time of Use v2 schedule entities."""
        return self._has_solax_entity_suffix(
            entities,
            self._SOLIS_TOU_MARKER_SUFFIX,
            "Solis TOU v2",
            platforms=self._SOLIS_PLATFORMS,
        )

    def _match_solis_dict_embedded_entities(
        self, entities: list[dict]
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Map Solis monitoring entities affected by the dict-embedded unique_id bug.

        Scoped to the ``solis_modbus`` platform only — never touches
        ``_map_registry_entities``'s endswith()/exact matching used by every
        other platform. See ``SOLIS_DICT_EMBEDDED_SUFFIX_MAP`` for the source
        citation for this integration bug.

        Matches via a regex anchored to the ``unique`` dict key specifically
        (``'unique':\\s*'<key>'``) rather than a bare substring check — this
        tolerates whitespace variation in the dict repr while still requiring
        both quote boundaries around the key, so it can't false-positive on
        the key appearing as a fragment of some other field's value.

        Enabled entities are preferred over disabled ones, mirroring
        ``_map_registry_entities``: a disabled entity is never mapped (it
        has no state, so reading it 404s), and keys whose only match is
        disabled are returned separately for the caller to report (#549).

        Returns:
            Tuple of (mapped, disabled), each mapping
            bess_sensor_key -> entity_id.  The two never share a key.
        """
        result: dict[str, str] = {}
        disabled_matches: dict[str, str] = {}
        for key, bess_key in self.SOLIS_DICT_EMBEDDED_SUFFIX_MAP.items():
            if bess_key in result:
                continue
            pattern = re.compile(r"'unique':\s*'" + re.escape(key) + r"'")
            for entity in entities:
                if entity.get("platform") not in self._SOLIS_PLATFORMS:
                    continue
                entity_id = entity.get("entity_id", "")
                if "." not in entity_id:
                    continue
                unique_id = str(entity.get("unique_id", ""))
                if not pattern.search(unique_id):
                    continue
                if entity.get("disabled_by"):
                    # Defer — an enabled entity may appear later
                    if bess_key not in disabled_matches:
                        disabled_matches[bess_key] = entity_id
                    continue
                result[bess_key] = entity_id
                break

        disabled_only = {
            bess_key: entity_id
            for bess_key, entity_id in disabled_matches.items()
            if bess_key not in result
        }
        for bess_key, entity_id in disabled_only.items():
            logger.warning(
                "Solis dict-embedded sensor %s not mapped: its only match "
                "%s is disabled in Home Assistant — enable it, then re-run "
                "discovery",
                bess_key,
                entity_id,
            )

        logger.info("Mapped %d Solis dict-embedded monitoring entities", len(result))
        return result, disabled_only

    def _has_solax_entity_suffix(
        self,
        entities: list[dict],
        suffix: str,
        label: str,
        platforms: set[str] | None = None,
    ) -> bool:
        """Check whether any entity of the given platform(s) has a unique_id
        ending with the suffix. Defaults to ``_SOLAX_PLATFORMS`` for the
        existing solax_modbus marker checks; pass ``platforms`` to reuse this
        for another platform's own marker (e.g. Solis)."""
        platform_set = platforms if platforms is not None else self._SOLAX_PLATFORMS
        count = 0
        for entity in entities:
            if entity.get("platform") not in platform_set:
                continue
            count += 1
            unique_id = str(entity.get("unique_id", ""))
            if unique_id.endswith(f"_{suffix}"):
                logger.info("%s marker found: unique_id=%s", label, unique_id)
                return True
        logger.info("No %s marker found among %d matching entities", label, count)
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
    ) -> tuple[dict[str, dict[str, str]], str | None, dict[str, dict[str, str]]]:
        """Discover sensor entity IDs for all detected inverter platforms.

        Uses the ``platform`` field to identify integration entities, then maps
        entity ID suffixes to BESS sensor keys via the suffix maps.  This is
        robust against entity renaming because it identifies the integration
        directly rather than pattern-matching entity ID prefixes.

        Args:
            entities: Pre-fetched entity registry list, or None to fetch.

        Returns:
            Tuple of (platform_sensors, detected_platform, platform_disabled)
            where platform_sensors maps platform name to its sensor dict
            (e.g. ``{"growatt": {bess_key: entity_id, ...}, "solax": {...}}``),
            detected_platform is ``"growatt"``, ``"solax"``, or None (Growatt
            takes priority when both are present), and platform_disabled maps
            platform name to the sensor keys left unmapped because their only
            registry match is disabled in Home Assistant (#549).
        """
        if entities is None:
            entities = self.fetch_entity_registry()

        inverter_detected = self.detect_inverter_integrations(entities)
        platform_sensors: dict[str, dict[str, str]] = {}
        platform_disabled: dict[str, dict[str, str]] = {}
        detected_platform: str | None = None

        if inverter_detected.get("growatt"):
            min_sensors, min_disabled = self._map_registry_entities(
                entities,
                ["growatt_server"],
                self.GROWATT_MIN_SUFFIX_MAP,
            )
            sph_sensors, sph_disabled = self._map_registry_entities(
                entities,
                ["growatt_server"],
                self.GROWATT_SPH_SUFFIX_MAP,
            )
            # Include a platform whose every match is disabled: its sensor
            # dict is empty, but dropping it would hide the "enable these
            # entities" report that is the only way out of that state.
            if min_sensors or min_disabled:
                platform_sensors["growatt_server_min"] = min_sensors
                platform_disabled["growatt_server_min"] = min_disabled
            if sph_sensors or sph_disabled:
                platform_sensors["growatt_server_sph"] = sph_sensors
                platform_disabled["growatt_server_sph"] = sph_disabled
            # Pick the platform that matched more sensors
            if len(min_sensors) >= len(sph_sensors):
                detected_platform = "growatt_server_min"
            else:
                detected_platform = "growatt_server_sph"

        if inverter_detected.get("solax"):
            solax_platforms = ["solax_modbus", "solax"]
            if self._has_growatt_tou_entities(entities):
                # GEN4: Growatt MIN/MOD/MID with numbered TOU slots
                solax_sensors, solax_disabled = self._map_registry_entities(
                    entities, solax_platforms, self.SOLAX_GROWATT_MIN_SUFFIX_MAP
                )
                platform_sensors["solax_modbus_growatt_min"] = solax_sensors
                platform_disabled["solax_modbus_growatt_min"] = solax_disabled
                if not detected_platform:
                    detected_platform = "solax_modbus_growatt_min"
            elif self._has_growatt_gen3_entities(entities):
                # GEN3: Growatt MIX/SPA/SPH with mode-specific time slots
                solax_sensors, solax_disabled = self._map_registry_entities(
                    entities, solax_platforms, self.SOLAX_GROWATT_SPH_SUFFIX_MAP
                )
                platform_sensors["solax_modbus_growatt_sph"] = solax_sensors
                platform_disabled["solax_modbus_growatt_sph"] = solax_disabled
                if not detected_platform:
                    detected_platform = "solax_modbus_growatt_sph"
            else:
                solax_sensors, solax_disabled = self._map_registry_entities(
                    entities, solax_platforms, self.SOLAX_NATIVE_SUFFIX_MAP
                )
                # battery_power_charge is a single signed register — native
                # SolaX has no separate discharge entity (#542). Pair
                # battery_discharge_power to it here as well as at read time,
                # so the key lands in platform_sensors and the reconciliation
                # below takes it off platform_disabled.
                apply_signed_pair_aliases("solax_modbus_native", solax_sensors)
                platform_sensors["solax_modbus_native"] = solax_sensors
                platform_disabled["solax_modbus_native"] = solax_disabled
                if not detected_platform:
                    detected_platform = "solax_modbus_native"

        if inverter_detected.get("solis"):
            solis_platforms = ["solis_modbus"]
            solis_sensors, solis_disabled = self._map_registry_entities(
                entities, solis_platforms, self.SOLIS_SUFFIX_MAP
            )
            # Dict-embedded-unique_id monitoring entities need a separate,
            # Solis-scoped matcher (see SOLIS_DICT_EMBEDDED_SUFFIX_MAP) —
            # merge them in without touching _map_registry_entities.
            embedded, embedded_disabled = self._match_solis_dict_embedded_entities(
                entities
            )
            solis_sensors.update(
                {k: v for k, v in embedded.items() if k not in solis_sensors}
            )
            solis_disabled.update(
                {k: v for k, v in embedded_disabled.items() if k not in solis_disabled}
            )
            # Solis has no separate export_power entity — grid_power_net is
            # a single signed sensor (see SOLIS_SUFFIX_MAP comment); pair
            # export_power to it (#475, same reason as SolaX's battery pair
            # above).
            apply_signed_pair_aliases("solis_modbus", solis_sensors)
            # Monitoring sensors are always mapped, but only auto-select
            # solis_modbus as the detected platform when the Grid TOU v2
            # marker is present — without it, schedule writes fail on every
            # attempt (write_solis_period raises), so a monitoring-only
            # Solis install must not be silently promoted to "detected"
            # like a fully-controllable one.
            platform_sensors["solis_modbus"] = solis_sensors
            platform_disabled["solis_modbus"] = solis_disabled
            if self._has_solis_tou_v2_entities(entities):
                if not detected_platform:
                    detected_platform = "solis_modbus"
            else:
                logger.warning(
                    "solis_modbus detected but no Grid Time of Use v2 "
                    "entities found — schedule control unavailable on this "
                    "inverter/firmware; monitoring sensors mapped but "
                    "solis_modbus is not auto-selected as detected_platform"
                )

        if inverter_detected.get("huawei"):
            huawei_sensors, huawei_disabled = self._map_registry_entities(
                entities, ["huawei_solar"], self.HUAWEI_SUFFIX_MAP
            )
            # Huawei is single-signed on BOTH pairs: power_meter_active_power
            # for grid (#438/#475) and storage_charge_discharge_power (reg
            # 37765, positive = charging) for battery (#542). Neither has a
            # counterpart entity, so both derived keys are paired to them.
            apply_signed_pair_aliases("huawei_solar_luna2000", huawei_sensors)
            platform_sensors["huawei_solar_luna2000"] = huawei_sensors
            platform_disabled["huawei_solar_luna2000"] = huawei_disabled
            if not detected_platform:
                detected_platform = "huawei_solar_luna2000"

        # A key that some other path did map (a derived alias, the Solis
        # signed-sensor aliasing above) is configured, not disabled — the
        # two dicts must never overlap, or the wizard would block on a
        # sensor it actually has.
        for platform, disabled in platform_disabled.items():
            mapped = platform_sensors.get(platform, {})
            for bess_key in list(disabled):
                if bess_key in mapped:
                    del disabled[bess_key]

        return platform_sensors, detected_platform, platform_disabled

    def _map_registry_entities(
        self,
        entities: list[dict],
        platforms: list[str],
        suffix_map: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Map entity registry entries to BESS sensor keys using unique_id.

        Filters entities belonging to the given platforms, then matches
        the ``unique_id`` suffix against the suffix map.  ``unique_id``
        is assigned by the integration and never changes regardless of
        user entity renaming — this is the only reliable matching strategy.

        Enabled entities are preferred over disabled ones.  A disabled
        entity is never mapped: it has no state in Home Assistant, so any
        read of it 404s.  Keys whose only match is disabled are returned
        separately so the caller can tell the user which entities to
        enable, instead of persisting a mapping that cannot work (#549).

        Args:
            entities: Full entity registry list.
            platforms: HA platform names to filter by (e.g. ["solax_modbus"]).
            suffix_map: Maps entity suffix -> BESS sensor key.

        Returns:
            Tuple of (mapped, disabled), each mapping
            bess_sensor_key -> entity_id.  The two never share a key.
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

        # Keys whose only match is disabled stay unmapped — reading a
        # disabled entity 404s, so mapping one just defers the failure to
        # runtime.  Report them instead (#549).
        disabled_only = {
            bess_key: entity_id
            for bess_key, entity_id in disabled_matches.items()
            if bess_key not in result
        }
        for bess_key, entity_id in disabled_only.items():
            logger.warning(
                "Sensor '%s' not mapped: its only match %s is disabled in "
                "Home Assistant — enable it, then re-run discovery",
                bess_key,
                entity_id,
            )

        logger.info(
            "Mapped %d entities from registry (platforms=%s, %d disabled)",
            len(result),
            platforms,
            len(disabled_only),
        )
        return result, disabled_only
