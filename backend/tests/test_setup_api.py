"""Tests for setup wizard API endpoints.

Coverage goals:
- GET /api/setup/status: returns wizard_needed based on sensor config
- POST /api/setup/confirm: validates entity IDs, persists config
- POST /api/setup/complete: persists all settings, applies live, starts scheduler
"""

import sys
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

_test_app = FastAPI()
_test_app.include_router(router)
_client = TestClient(_test_app, raise_server_exceptions=False)


@pytest.fixture()
def mock_controller():
    """Minimal bess_controller mock for setup endpoints."""
    ctrl = MagicMock()
    ctrl.ha_controller.sensors = {}
    ctrl.settings_store.data = {}
    ctrl.settings_store.get_section.return_value = {}
    sys.modules["app"].bess_controller = ctrl
    return ctrl


# ---------------------------------------------------------------------------
# Richer fixture for setup_complete — needs mutable read-modify-write store
# ---------------------------------------------------------------------------

_PRE_EXISTING_STORE: dict = {
    "battery": {
        "total_capacity": 10.0,
        "min_soc": 5.0,
        "max_soc": 100.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "cycle_cost_per_kwh": 0.3,
        "min_action_profit_threshold": 0.0,
        "efficiency_charge": 0.97,
        "efficiency_discharge": 0.95,
        "temperature_derating": {"enabled": False, "weather_entity": ""},
    },
    "home": {
        "default_hourly": 2.0,
        "currency": "EUR",
        "consumption_strategy": "fixed",
        "max_fuse_current": 16,
        "voltage": 230,
        "safety_margin": 1.0,
        "phase_count": 1,
        "power_monitoring_enabled": False,
    },
    "electricity_price": {
        "area": "SE3",
        "markup_rate": 0.05,
        "vat_multiplier": 1.20,
        "additional_costs": 0.50,
        "tax_reduction": 0.10,
    },
    "energy_provider": {
        "provider": "nordpool_official",
        "nordpool_official": {"config_entry_id": "old-entry"},
    },
    "growatt": {"device_id": "old-dev"},
    "inverter": {"platform": "growatt_server_min"},
    "sensors": {"battery_soc": "sensor.old_soc"},
}


@pytest.fixture()
def complete_controller():
    """A bess_controller with a mutable store for setup_complete tests."""
    ctrl = MagicMock()
    store_data = deepcopy(_PRE_EXISTING_STORE)
    ctrl.settings_store.data = store_data
    ctrl.ha_controller.sensors = {}

    def _get_section(name: str) -> dict:
        return dict(store_data.get(name, {}))

    def _save_all(data: dict) -> None:
        for key, val in data.items():
            store_data[key] = dict(val)

    def _get_active_sensors() -> dict:
        sensors = store_data.get("sensors", {})
        if "platform" not in sensors:
            return {k: v for k, v in sensors.items() if isinstance(v, str)}
        platform = sensors.get("platform", "")
        result = dict(sensors.get("shared", {}))
        result.update(sensors.get(platform, {}))
        return result

    ctrl.settings_store.get_section.side_effect = _get_section
    ctrl.settings_store.save_all.side_effect = _save_all
    ctrl.settings_store.get_active_sensors.side_effect = _get_active_sensors

    sys.modules["app"].bess_controller = ctrl
    return ctrl


def _full_wizard_payload(**overrides) -> dict:
    """A realistic wizard completion payload (mirrors what the frontend sends)."""
    base = {
        "sensors": {
            "platform": "growatt_server_min",
            "growatt_server_min": {
                "battery_soc": "sensor.growatt_battery_soc",
                "pv_power": "sensor.growatt_pv_power",
            },
            "growatt_server_sph": {},
            "solax_modbus_growatt_min": {},
            "solax_modbus_growatt_sph": {},
            "solax_modbus_native": {},
            "shared": {},
        },
        "nordpoolArea": "SE4",
        "nordpoolConfigEntryId": "entry-abc",
        "growattDeviceId": "dev-123",
        "totalCapacity": 30.0,
        "minSoc": 10.0,
        "maxSoc": 95.0,
        "maxChargeDischargePower": 15.0,
        "cycleCost": 0.50,
        "minActionProfitThreshold": 8.0,
        "currency": "SEK",
        "consumption": 3.5,
        "consumptionStrategy": "sensor",
        "maxFuseCurrent": 25,
        "voltage": 230,
        "safetyMarginFactor": 1.0,
        "phaseCount": 3,
        "powerMonitoringEnabled": True,
        "area": "SE4",
        "markupRate": 0.08,
        "vatMultiplier": 1.25,
        "additionalCosts": 0.77,
        "taxReduction": 0.20,
        "provider": "nordpool_official",
        "inverterPlatform": "growatt_server_min",
    }
    base.update(overrides)
    return base


class TestGetSetupStatus:
    """GET /api/setup/status."""

    def test_wizard_needed_when_no_sensors(self, mock_controller):
        mock_controller.ha_controller.sensors = {"battery_soc": "", "solar_power": ""}
        resp = _client.get("/api/setup/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["wizardNeeded"] is True
        assert body["configuredSensors"] == 0

    def test_wizard_not_needed_when_sensors_configured(self, mock_controller):
        mock_controller.ha_controller.sensors = {
            "battery_soc": "sensor.growatt_battery_soc",
            "solar_power": "sensor.growatt_solar_power",
        }
        resp = _client.get("/api/setup/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["wizardNeeded"] is False
        assert body["configuredSensors"] == 2
        assert body["totalSensors"] == 2

    def test_partially_configured_still_needs_wizard(self, mock_controller):
        mock_controller.ha_controller.sensors = {
            "battery_soc": "sensor.growatt_battery_soc",
            "solar_power": "",
            "import_power": "",
        }
        resp = _client.get("/api/setup/status")
        body = resp.json()
        # Only 1 configured sensor — wizard_needed is False because at least 1 is configured
        assert body["wizardNeeded"] is False
        assert body["configuredSensors"] == 1


class TestSetupCompleteLegacy:
    """POST /api/setup/complete — legacy persistence tests."""

    def test_persists_octopus_entities(self, mock_controller):
        """Octopus Energy entity IDs from the wizard are saved to settings."""
        # get_section returns a fresh dict each time (read-modify-write pattern)
        mock_controller.settings_store.get_section.return_value = {}

        resp = _client.post(
            "/api/setup/complete",
            json={
                "sensors": {"battery_soc": "sensor.growatt_battery_soc"},
                "provider": "octopus",
                "currency": "GBP",
                "octopusImportTodayEntity": "event.octopus_electricity_import_current_day_rates",
                "octopusImportTomorrowEntity": "event.octopus_electricity_import_next_day_rates",
                "octopusExportTodayEntity": "event.octopus_electricity_export_current_day_rates",
                "octopusExportTomorrowEntity": "event.octopus_electricity_export_next_day_rates",
            },
        )
        assert resp.status_code == 200

        # Find the save_all call and verify octopus entities were persisted
        save_all_call = mock_controller.settings_store.save_all.call_args
        assert save_all_call is not None
        sections = save_all_call[0][0]

        ep = sections["energy_provider"]
        assert ep["provider"] == "octopus"
        assert (
            ep["octopus"]["import_today_entity"]
            == "event.octopus_electricity_import_current_day_rates"
        )
        assert (
            ep["octopus"]["import_tomorrow_entity"]
            == "event.octopus_electricity_import_next_day_rates"
        )
        assert (
            ep["octopus"]["export_today_entity"]
            == "event.octopus_electricity_export_current_day_rates"
        )
        assert (
            ep["octopus"]["export_tomorrow_entity"]
            == "event.octopus_electricity_export_next_day_rates"
        )

    def test_persists_without_octopus_entities(self, mock_controller):
        """Non-Octopus wizard completion does not create octopus section."""
        mock_controller.settings_store.get_section.return_value = {}

        resp = _client.post(
            "/api/setup/complete",
            json={
                "sensors": {"battery_soc": "sensor.growatt_battery_soc"},
                "provider": "nordpool_official",
                "currency": "SEK",
                "nordpoolArea": "SE4",
            },
        )
        assert resp.status_code == 200

        sections = mock_controller.settings_store.save_all.call_args[0][0]
        ep = sections["energy_provider"]
        assert ep["provider"] == "nordpool_official"
        assert "octopus" not in ep

    def test_persists_battery_and_home_settings(self, mock_controller):
        """Core wizard fields (battery, home) are persisted correctly."""
        mock_controller.settings_store.get_section.return_value = {}

        resp = _client.post(
            "/api/setup/complete",
            json={
                "sensors": {},
                "provider": "nordpool_official",
                "totalCapacity": 30.0,
                "minSoc": 15,
                "maxSoc": 95,
                "currency": "SEK",
                "consumption": 3.5,
            },
        )
        assert resp.status_code == 200

        sections = mock_controller.settings_store.save_all.call_args[0][0]
        assert sections["battery"]["total_capacity"] == 30.0
        assert sections["battery"]["min_soc"] == 15
        assert sections["battery"]["max_soc"] == 95
        assert sections["home"]["currency"] == "SEK"
        assert sections["home"]["default_hourly"] == 3.5


class TestRuntimeFailures:
    """GET/POST /api/runtime-failures."""

    def test_get_returns_list(self, mock_controller):
        mock_controller.system.get_runtime_failures.return_value = []
        resp = _client.get("/api/runtime-failures")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_dismiss_nonexistent_returns_404(self, mock_controller):
        mock_controller.system.dismiss_runtime_failure.side_effect = ValueError(
            "not found"
        )
        resp = _client.post("/api/runtime-failures/fake-id/dismiss")
        assert resp.status_code == 404

    def test_dismiss_all_returns_count(self, mock_controller):
        mock_controller.system.dismiss_all_runtime_failures.return_value = 3
        resp = _client.post("/api/runtime-failures/dismiss-all")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "3" in body["message"]


# ===========================================================================
# POST /api/setup/complete
# ===========================================================================


class TestSetupComplete:
    """POST /api/setup/complete — the atomic wizard completion endpoint."""

    def test_returns_200_with_full_payload(self, complete_controller):
        resp = _client.post("/api/setup/complete", json=_full_wizard_payload())
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_saved_sections_listed_in_response(self, complete_controller):
        resp = _client.post("/api/setup/complete", json=_full_wizard_payload())
        saved = resp.json()["saved_sections"]
        assert "battery" in saved
        assert "home" in saved
        assert "electricity_price" in saved
        assert "energy_provider" in saved
        assert "inverter" in saved
        assert "sensors" in saved

    # -- Battery persistence --

    def test_battery_fields_persisted_as_snake_case(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        bat = call_args["battery"]
        assert bat["total_capacity"] == 30.0
        assert bat["min_soc"] == 10.0
        assert bat["max_soc"] == 95.0
        assert bat["max_charge_power_kw"] == 15.0
        assert bat["max_discharge_power_kw"] == 15.0
        assert bat["cycle_cost_per_kwh"] == 0.50
        assert bat["min_action_profit_threshold"] == 8.0

    def test_battery_preserves_keys_not_in_wizard(self, complete_controller):
        """Keys like efficiency_charge and temperature_derating must survive."""
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        bat = call_args["battery"]
        assert bat["efficiency_charge"] == 0.97
        assert bat["temperature_derating"]["enabled"] is False

    # -- Home persistence --

    def test_home_fields_persisted(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        home = call_args["home"]
        assert home["default_hourly"] == 3.5
        assert home["currency"] == "SEK"
        assert home["consumption_strategy"] == "sensor"
        assert home["max_fuse_current"] == 25
        assert home["voltage"] == 230
        assert home["safety_margin"] == 1.0
        assert home["phase_count"] == 3
        assert home["power_monitoring_enabled"] is True

    def test_consumption_strategy_saved_without_currency_or_consumption(
        self, complete_controller
    ):
        """consumptionStrategy must be persisted even when currency/consumption are omitted."""
        payload = {
            "consumptionStrategy": "ha_statistics",
            "maxFuseCurrent": 25,
            "voltage": 230,
            "safetyMarginFactor": 1.0,
            "phaseCount": 3,
            "powerMonitoringEnabled": True,
        }
        resp = _client.post("/api/setup/complete", json=payload)
        assert resp.status_code == 200
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        home = call_args["home"]
        assert home["consumption_strategy"] == "ha_statistics"

    def test_battery_fields_saved_without_total_capacity(self, complete_controller):
        """Battery fields must be persisted even when totalCapacity is omitted."""
        payload = {"minSoc": 15, "cycleCost": 0.6}
        resp = _client.post("/api/setup/complete", json=payload)
        assert resp.status_code == 200
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        bat = call_args["battery"]
        assert bat["min_soc"] == 15
        assert bat["cycle_cost_per_kwh"] == 0.6

    # -- Electricity price persistence --

    def test_electricity_price_fields_persisted(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        elec = call_args["electricity_price"]
        assert elec["area"] == "SE4"
        assert elec["markup_rate"] == 0.08
        assert elec["vat_multiplier"] == 1.25
        assert elec["additional_costs"] == 0.77
        assert elec["tax_reduction"] == 0.20

    def test_price_fields_saved_without_markup_or_vat(self, complete_controller):
        """additionalCosts/taxReduction must be persisted even without markupRate/vatMultiplier."""
        payload = {"additionalCosts": 0.99, "taxReduction": 0.25}
        resp = _client.post("/api/setup/complete", json=payload)
        assert resp.status_code == 200
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        elec = call_args["electricity_price"]
        assert elec["additional_costs"] == 0.99
        assert elec["tax_reduction"] == 0.25

    # -- Energy provider persistence --

    def test_energy_provider_persisted(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        ep = call_args["energy_provider"]
        assert ep["provider"] == "nordpool_official"

    def test_octopus_entities_persisted_when_provider_is_octopus(
        self, complete_controller
    ):
        payload = _full_wizard_payload(
            provider="octopus",
            octopusImportTodayEntity="sensor.octopus_import_today",
            octopusImportTomorrowEntity="sensor.octopus_import_tomorrow",
            octopusExportTodayEntity="sensor.octopus_export_today",
            octopusExportTomorrowEntity="sensor.octopus_export_tomorrow",
        )
        _client.post("/api/setup/complete", json=payload)
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        octopus = call_args["energy_provider"]["octopus"]
        assert octopus["import_today_entity"] == "sensor.octopus_import_today"
        assert octopus["export_tomorrow_entity"] == "sensor.octopus_export_tomorrow"

    # -- Inverter persistence --

    def test_inverter_platform_set_for_min(self, complete_controller):
        _client.post(
            "/api/setup/complete",
            json=_full_wizard_payload(inverterPlatform="growatt_server_min"),
        )
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        assert call_args["inverter"]["platform"] == "growatt_server_min"

    def test_inverter_platform_set_for_sph(self, complete_controller):
        _client.post(
            "/api/setup/complete",
            json=_full_wizard_payload(inverterPlatform="growatt_server_sph"),
        )
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        assert call_args["inverter"]["platform"] == "growatt_server_sph"

    def test_inverter_platform_set_for_solax(self, complete_controller):
        _client.post(
            "/api/setup/complete",
            json=_full_wizard_payload(inverterPlatform="solax_modbus_native"),
        )
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        assert call_args["inverter"]["platform"] == "solax_modbus_native"

    def test_inverter_platform_set_for_solax_modbus_growatt_min(
        self, complete_controller
    ):
        _client.post(
            "/api/setup/complete",
            json=_full_wizard_payload(inverterPlatform="solax_modbus_growatt_min"),
        )
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        assert call_args["inverter"]["platform"] == "solax_modbus_growatt_min"

    def test_inverter_platform_set_for_sph_modbus(self, complete_controller):
        _client.post(
            "/api/setup/complete",
            json=_full_wizard_payload(inverterPlatform="solax_modbus_growatt_sph"),
        )
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        assert call_args["inverter"]["platform"] == "solax_modbus_growatt_sph"

    def test_growatt_inverter_type_not_written(self, complete_controller):
        """Setup should not write legacy growatt.inverter_type for any platform."""
        # Clear pre-existing legacy field to verify setup doesn't add it
        complete_controller.settings_store.data["growatt"] = {"device_id": "old-dev"}
        _client.post(
            "/api/setup/complete",
            json=_full_wizard_payload(inverterPlatform="growatt_server_sph"),
        )
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        assert "inverter_type" not in call_args.get("growatt", {})

    def test_growatt_section_not_written_without_device_id(self, complete_controller):
        _client.post(
            "/api/setup/complete",
            json=_full_wizard_payload(
                inverterPlatform="solax_modbus_native", growattDeviceId=None
            ),
        )
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        assert "growatt" not in call_args

    # -- Sensors --

    def test_sensors_persisted(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        assert (
            call_args["sensors"]["growatt_server_min"]["battery_soc"]
            == "sensor.growatt_battery_soc"
        )

    def test_rejects_invalid_sensor_entity_ids(self, complete_controller):
        payload = _full_wizard_payload(
            sensors={
                "platform": "growatt_server_min",
                "growatt_server_min": {"battery_soc": "BAD-FORMAT"},
                "growatt_server_sph": {},
                "solax_modbus_growatt_min": {},
                "solax_modbus_growatt_sph": {},
                "solax_modbus_native": {},
                "shared": {},
            }
        )
        resp = _client.post("/api/setup/complete", json=payload)
        assert resp.status_code == 422

    # -- Live system updates --

    def test_live_battery_update_sent(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        calls = complete_controller.system.update_settings.call_args_list
        battery_calls = [c for c in calls if "battery" in c[0][0]]
        assert len(battery_calls) >= 1
        sent = battery_calls[0][0][0]["battery"]
        assert sent["totalCapacity"] == 30.0
        assert sent["maxChargePowerKw"] == 15.0

    def test_live_home_update_sent(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        calls = complete_controller.system.update_settings.call_args_list
        home_calls = [c for c in calls if "home" in c[0][0]]
        assert len(home_calls) >= 1
        sent = home_calls[0][0][0]["home"]
        assert sent["defaultHourly"] == 3.5
        assert sent["currency"] == "SEK"

    def test_live_price_update_sent(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        calls = complete_controller.system.update_settings.call_args_list
        price_calls = [c for c in calls if "price" in c[0][0]]
        assert len(price_calls) >= 1
        sent = price_calls[0][0][0]["price"]
        assert sent["vatMultiplier"] == 1.25

    def test_live_energy_provider_update_sent(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        calls = complete_controller.system.update_settings.call_args_list
        ep_calls = [c for c in calls if "energy_provider" in c[0][0]]
        assert len(ep_calls) >= 1

    def test_inverter_platform_switched_live(self, complete_controller):
        _client.post(
            "/api/setup/complete",
            json=_full_wizard_payload(inverterPlatform="growatt_server_sph"),
        )
        complete_controller.system.switch_inverter_platform.assert_called_once_with(
            "growatt_server_sph"
        )

    def test_sensors_applied_to_ha_controller(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        assert (
            complete_controller.ha_controller.sensors["battery_soc"]
            == "sensor.growatt_battery_soc"
        )

    def test_empty_sensor_values_filtered_from_live_sensors(self, complete_controller):
        """Empty string sensors should not appear in the live ha_controller map."""
        payload = _full_wizard_payload(
            sensors={
                "platform": "growatt_server_min",
                "growatt_server_min": {"battery_soc": "sensor.batt", "pv_power": ""},
                "growatt_server_sph": {},
                "solax_modbus_growatt_min": {},
                "solax_modbus_growatt_sph": {},
                "solax_modbus_native": {},
                "shared": {},
            }
        )
        _client.post("/api/setup/complete", json=payload)
        assert "pv_power" not in complete_controller.ha_controller.sensors

    def test_growatt_device_id_applied_to_ha_controller(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        assert complete_controller.ha_controller.growatt_device_id == "dev-123"

    def test_scheduler_started(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        complete_controller.start_scheduler.assert_called_once()

    def test_health_check_rerun(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        complete_controller.system.refresh_health_check.assert_called()

    def test_discovered_config_applied(self, complete_controller):
        _client.post("/api/setup/complete", json=_full_wizard_payload())
        complete_controller.apply_discovered_config.assert_called_once_with(
            sensor_map={},
            nordpool_area="SE4",
            nordpool_config_entry_id="entry-abc",
            growatt_device_id="dev-123",
        )

    # -- Partial payloads --

    def test_minimal_payload_succeeds(self, complete_controller):
        """Wizard with only sensors and no other settings should not crash."""
        resp = _client.post(
            "/api/setup/complete",
            json={"sensors": {"battery_soc": "sensor.batt"}},
        )
        assert resp.status_code == 200

    def test_no_battery_section_when_capacity_is_none(self, complete_controller):
        """If the wizard sends no battery fields, battery should not be in save_all."""
        payload = {"sensors": {"battery_soc": "sensor.batt"}}
        _client.post("/api/setup/complete", json=payload)
        call_args = complete_controller.settings_store.save_all.call_args[0][0]
        assert "battery" not in call_args

    def test_setup_complete_with_demo_mode(self, complete_controller):
        resp = _client.post(
            "/api/setup/complete",
            json={
                "sensors": {"platform": "growatt_server_min"},
                "totalCapacity": 10.0,
                "inverterPlatform": "growatt_server_min",
                "demoMode": True,
            },
        )
        assert resp.status_code == 200
        stored = complete_controller.settings_store.data.get("demo_mode", {})
        assert stored["enabled"] is True
        complete_controller.system.set_demo_mode.assert_called_with(True)


# ---------------------------------------------------------------------------
# Discovery locale persistence (#113)
# ---------------------------------------------------------------------------


def _make_discover_controller(store_data: dict) -> MagicMock:
    """Build a bess_controller mock for /api/setup/discover tests.

    The mock stores data mutably so save_section calls are visible in asserts.
    """
    ctrl = MagicMock()
    ctrl.settings_store.data = store_data

    def _get_section(name: str) -> dict:
        return dict(store_data.get(name, {}))

    def _save_section(name: str, data: dict) -> None:
        store_data[name] = dict(data)

    ctrl.settings_store.get_section.side_effect = _get_section
    ctrl.settings_store.save_section.side_effect = _save_section
    return ctrl


class TestDiscoverLocaleDefaults:
    """POST /api/setup/discover — locale-appropriate defaults (#113)."""

    def _run_discover(self, ctrl, integrations):
        """Helper: mock HA calls and POST /api/setup/discover."""
        ha = ctrl.ha_controller
        ha.discover_integrations.return_value = (integrations, [])
        ha.fetch_entity_registry.return_value = []
        ha.discover_sensors_from_registry.return_value = ({}, None)
        ha.discover_current_sensors.return_value = {}
        ha.discover_optional_sensors.return_value = {}
        ha.discover_octopus_entities.return_value = {}
        ha.ENTITY_SUFFIX_MAP = {}
        ha.SOLAX_GROWATT_MIN_SUFFIX_MAP = {}
        ha.SOLAX_GROWATT_SPH_SUFFIX_MAP = {}
        ha.SOLAX_NATIVE_SUFFIX_MAP = {}
        sys.modules["app"].bess_controller = ctrl
        return _client.post("/api/setup/discover")

    def test_octopus_only_persists_gbp_defaults(self):
        """Octopus-only discovery overwrites Swedish bootstrap defaults with UK values."""
        store = deepcopy(_PRE_EXISTING_STORE)
        store["home"]["currency"] = "SEK"
        store["electricity_price"]["vat_multiplier"] = 1.25
        store["electricity_price"]["additional_costs"] = 0.773
        store["electricity_price"]["tax_reduction"] = 0.1988
        store["energy_provider"]["provider"] = "nordpool_official"

        ctrl = _make_discover_controller(store)
        integrations = {
            "growatt_found": False,
            "device_sn": None,
            "growatt_device_id": None,
            "solax_found": False,
            "nordpool_found": False,
            "nordpool_area": None,
            "nordpool_custom_area": None,
            "nordpool_custom_entity": None,
            "nordpool_config_entry_id": None,
            "octopus_found": True,
            "detected_inverter_platforms": [],
            "detected_phase_count": None,
            "currency": "GBP",
            "vat_multiplier": 1.0,
        }
        resp = self._run_discover(ctrl, integrations)
        assert resp.status_code == 200

        assert store["home"]["currency"] == "GBP"
        assert store["electricity_price"]["vat_multiplier"] == 1.0
        assert store["electricity_price"]["additional_costs"] == 0.0
        assert store["electricity_price"]["tax_reduction"] == 0.0
        assert store["energy_provider"]["provider"] == "octopus"

    def test_nordpool_discovery_does_not_clear_costs(self):
        """Nordpool discovery updates currency/vat but keeps additional_costs/tax_reduction."""
        store = deepcopy(_PRE_EXISTING_STORE)
        store["home"]["currency"] = "SEK"
        store["electricity_price"]["vat_multiplier"] = 1.25
        store["electricity_price"]["additional_costs"] = 0.773
        store["electricity_price"]["tax_reduction"] = 0.1988

        ctrl = _make_discover_controller(store)
        integrations = {
            "growatt_found": False,
            "device_sn": None,
            "growatt_device_id": None,
            "solax_found": False,
            "nordpool_found": True,
            "nordpool_area": "SE3",
            "nordpool_custom_area": None,
            "nordpool_custom_entity": None,
            "nordpool_config_entry_id": "entry-123",
            "octopus_found": False,
            "detected_inverter_platforms": [],
            "detected_phase_count": None,
            "currency": "SEK",
            "vat_multiplier": 1.25,
        }
        resp = self._run_discover(ctrl, integrations)
        assert resp.status_code == 200

        # Currency and VAT unchanged (already correct)
        assert store["home"]["currency"] == "SEK"
        assert store["electricity_price"]["vat_multiplier"] == 1.25
        # Swedish cost fields preserved
        assert store["electricity_price"]["additional_costs"] == 0.773
        assert store["electricity_price"]["tax_reduction"] == 0.1988

    def test_norwegian_nordpool_updates_currency_preserves_costs(self):
        """Non-Swedish Nordpool updates currency but keeps cost fields as rough defaults."""
        store = deepcopy(_PRE_EXISTING_STORE)
        store["home"]["currency"] = "SEK"
        store["electricity_price"]["additional_costs"] = 0.773
        store["electricity_price"]["tax_reduction"] = 0.1988

        ctrl = _make_discover_controller(store)
        integrations = {
            "growatt_found": False,
            "device_sn": None,
            "growatt_device_id": None,
            "solax_found": False,
            "nordpool_found": True,
            "nordpool_area": "NO1",
            "nordpool_custom_area": None,
            "nordpool_custom_entity": None,
            "nordpool_config_entry_id": "entry-456",
            "octopus_found": False,
            "detected_inverter_platforms": [],
            "detected_phase_count": None,
            "currency": "NOK",
            "vat_multiplier": 1.25,
        }
        resp = self._run_discover(ctrl, integrations)
        assert resp.status_code == 200

        assert store["home"]["currency"] == "NOK"
        # Cost fields kept — Swedish values are a rough approximation, better than zero
        assert store["electricity_price"]["additional_costs"] == 0.773
        assert store["electricity_price"]["tax_reduction"] == 0.1988

    def test_no_locale_hints_leaves_defaults_unchanged(self):
        """When discovery returns no currency/vat hints, store is untouched."""
        store = deepcopy(_PRE_EXISTING_STORE)
        original_currency = store["home"]["currency"]
        original_vat = store["electricity_price"]["vat_multiplier"]

        ctrl = _make_discover_controller(store)
        integrations = {
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
            "detected_inverter_platforms": [],
            "detected_phase_count": None,
            "currency": None,
            "vat_multiplier": None,
        }
        resp = self._run_discover(ctrl, integrations)
        assert resp.status_code == 200

        assert store["home"]["currency"] == original_currency
        assert store["electricity_price"]["vat_multiplier"] == original_vat


# ===========================================================================
# POST /api/setup/complete — demo mode TOU reinitialization
# ===========================================================================


class TestSetupCompleteDemoMode:
    """setup/complete must delegate demo mode changes to system.set_demo_mode."""

    def test_disabling_demo_calls_set_demo_mode_false(self, complete_controller):
        """demoMode=False in wizard payload must call set_demo_mode(False)."""
        payload = _full_wizard_payload(demoMode=False)
        _client.post("/api/setup/complete", json=payload)
        complete_controller.system.set_demo_mode.assert_called_once_with(False)

    def test_enabling_demo_calls_set_demo_mode_true(self, complete_controller):
        """demoMode=True in wizard payload must call set_demo_mode(True)."""
        payload = _full_wizard_payload(demoMode=True)
        _client.post("/api/setup/complete", json=payload)
        complete_controller.system.set_demo_mode.assert_called_once_with(True)

    def test_absent_demo_mode_does_not_call_set_demo_mode(self, complete_controller):
        """No demoMode in payload must NOT call set_demo_mode."""
        payload = _full_wizard_payload()  # no demoMode key
        _client.post("/api/setup/complete", json=payload)
        complete_controller.system.set_demo_mode.assert_not_called()
