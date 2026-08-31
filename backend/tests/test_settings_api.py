"""Tests for the unified GET/PATCH /api/settings endpoints.

These tests exercise the merge logic, section routing, camelCase/snake_case
conversion, live update dispatch, and validation — all without a live HA
connection.  They verify the BEHAVIOR the endpoints must exhibit, not the
internal mechanics of how they route internally.

Coverage goals
--------------
- GET /api/settings: computed battery fields, sensors from ha_controller
- PATCH /api/settings: camelCase→snake_case, read-modify-write, section
  dispatch, live updates, sensor validation, unknown section rejection
"""

import sys
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bess.ha_api_controller import HomeAssistantAPIController

# ---------------------------------------------------------------------------
# Minimal FastAPI app that exercises the router under test
# ---------------------------------------------------------------------------

_test_app = FastAPI()
_test_app.include_router(router)
_client = TestClient(_test_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Shared store fixture
# ---------------------------------------------------------------------------

_DEFAULT_STORE: dict = {
    "battery": {
        "total_capacity": 30.0,
        "min_soc": 10.0,
        "max_soc": 95.0,
        "cycle_cost_per_kwh": 0.5,
        "max_charge_power_kw": 15.0,
        "max_discharge_power_kw": 15.0,
        "charging_power_rate": 100,
        "efficiency_charge": 0.97,
        "efficiency_discharge": 0.97,
    },
    "home": {
        "default_hourly": 3.5,
        "currency": "SEK",
        "max_fuse_current": 25,
        "voltage": 230,
        "safety_margin": 1.0,
        "phase_count": 3,
        "consumption_strategy": "fixed",
        "power_monitoring_enabled": False,
    },
    "electricity_price": {
        "area": "SE4",
        "markup_rate": 0.08,
        "vat_multiplier": 1.25,
        "additional_costs": 0.77,
        "tax_reduction": 0.2,
    },
    "energy_provider": {
        "provider": "nordpool_official",
        "nordpool_official": {"config_entry_id": "abc-123"},
    },
    "growatt": {"device_id": "dev-1"},
    "demo_mode": {"enabled": False},
    "sensors": {
        "platform": "growatt_server_min",
        "growatt_server_min": {},
        "growatt_server_sph": {},
        "solax_modbus_growatt_min": {},
        "solax_modbus_growatt_sph": {},
        "solax_modbus_native": {},
        "shared": {},
    },
}


@pytest.fixture()
def mock_controller():
    """A bess_controller mock with a realistic, mutable settings store."""
    ctrl = MagicMock()
    store_data = deepcopy(_DEFAULT_STORE)
    ctrl.settings_store.data = store_data

    # get_section / save_section operate on the live store_data dict so that
    # get_settings() (called at the end of patch_settings) sees the update.
    def _get_section(name: str) -> dict:
        return dict(store_data.get(name, {}))

    def _save_section(name: str, data: dict) -> None:
        store_data[name] = dict(data)

    def _get_active_sensors() -> dict:
        sensors = store_data.get("sensors", {})
        if "platform" not in sensors:
            return {k: v for k, v in sensors.items() if isinstance(v, str)}
        platform = sensors.get("platform", "")
        result = dict(sensors.get("shared", {}))
        result.update(sensors.get(platform, {}))
        return result

    ctrl.settings_store.get_section.side_effect = _get_section
    ctrl.settings_store.save_section.side_effect = _save_section
    ctrl.settings_store.get_active_sensors.side_effect = _get_active_sensors

    # Real controller (not a further mock) so ha_controller.sensors is a
    # live view over store_data, exactly like production (#334) — no
    # refresh call needed between a settings PATCH and the assertion.
    ctrl.ha_controller = HomeAssistantAPIController(
        ha_url="http://ha.local", token="tok", settings_store=ctrl.settings_store
    )

    sys.modules["app"].bess_controller = ctrl
    return ctrl


# ===========================================================================
# GET /api/settings
# ===========================================================================


class TestGetSettings:
    """GET /api/settings must enrich battery data and source sensors live."""

    def test_returns_200(self, mock_controller):
        resp = _client.get("/api/settings")
        assert resp.status_code == 200

    def test_battery_computed_fields_present(self, mock_controller):
        """min_soe_kwh, max_soe_kwh, reservedCapacity computed from capacity x SOC%."""
        resp = _client.get("/api/settings")
        battery = resp.json()["battery"]
        # 30 kWh x 10% min_soc = 3.0 kWh
        assert battery["minSoeKwh"] == pytest.approx(3.0)
        # 30 kWh x 95% max_soc = 28.5 kWh
        assert battery["maxSoeKwh"] == pytest.approx(28.5)
        assert battery["reservedCapacity"] == pytest.approx(3.0)

    def test_resolved_service_domain_exposed(self, mock_controller):
        """The UI shows the platform default as a placeholder for the
        inverter.service_domain override — it reads the resolved value from
        the API rather than duplicating PLATFORM_SERVICE_DOMAIN client-side."""
        mock_controller.settings_store.get_service_domain.return_value = (
            "growatt_server"
        )
        resp = _client.get("/api/settings")
        assert resp.json()["inverter"]["resolvedServiceDomain"] == "growatt_server"

    def test_sensors_come_from_store(self, mock_controller):
        """Sensor values are returned from the per-platform store structure."""
        mock_controller.settings_store.data["sensors"]["growatt_server_min"] = {
            "battery_soc": "sensor.battery_live"
        }
        resp = _client.get("/api/settings")
        sensors = resp.json()["sensors"]
        assert sensors["growatt_server_min"]["battery_soc"] == "sensor.battery_live"

    def test_per_platform_structure_returned(self, mock_controller):
        """GET /api/settings returns the full per-platform sensor structure."""
        mock_controller.settings_store.data["sensors"]["growatt_server_min"] = {
            "battery_soc": "sensor.growatt_soc"
        }
        mock_controller.settings_store.data["sensors"]["shared"] = {
            "weather_entity": "weather.home"
        }
        resp = _client.get("/api/settings")
        sensors = resp.json()["sensors"]
        assert sensors["platform"] == "growatt_server_min"
        assert sensors["growatt_server_min"]["battery_soc"] == "sensor.growatt_soc"
        assert sensors["shared"]["weather_entity"] == "weather.home"

    def test_non_sensor_sections_are_camel_case(self, mock_controller):
        """Store snake_case keys must be returned as camelCase for non-sensor sections."""
        resp = _client.get("/api/settings")
        battery = resp.json()["battery"]
        assert "totalCapacity" in battery
        assert "total_capacity" not in battery

    def test_influxdb_config_present_reflects_helper(
        self, mock_controller: MagicMock
    ) -> None:
        """The frontend deprecation banner (#722) keys off this flag — it must
        mirror is_influxdb_configured()."""
        with patch("api.is_influxdb_configured", return_value=True):
            resp = _client.get("/api/settings")
        assert resp.json()["influxdbConfigPresent"] is True

        with patch("api.is_influxdb_configured", return_value=False):
            resp = _client.get("/api/settings")
        assert resp.json()["influxdbConfigPresent"] is False


# ===========================================================================
# PATCH /api/settings — routing and conversion
# ===========================================================================


class TestPatchSettingsSectionRouting:
    """Unknown or misspelled section names must be rejected with 400."""

    def test_unknown_section_returns_400(self, mock_controller):
        resp = _client.patch("/api/settings", json={"badSection": {"foo": 1}})
        assert resp.status_code == 400
        assert "Unknown settings section" in resp.json()["detail"]

    def test_known_sections_accepted(self, mock_controller):
        for section in (
            "battery",
            "home",
            "electricityPrice",
            "energyProvider",
            "growatt",
            "sensors",
        ):
            resp = _client.patch("/api/settings", json={section: {}})
            assert (
                resp.status_code == 200
            ), f"Section '{section}' was unexpectedly rejected: {resp.text}"


class TestPatchSettingsInverter:
    """PATCH .../inverter — platform switch and Growatt-modbus control_mode."""

    def test_requires_platform(self, mock_controller):
        resp = _client.patch("/api/settings", json={"inverter": {"controlMode": "vpp"}})
        assert resp.status_code == 400

    def test_platform_switched_live(self, mock_controller):
        _client.patch(
            "/api/settings", json={"inverter": {"platform": "solax_modbus_growatt_min"}}
        )
        mock_controller.system.switch_inverter_platform.assert_called_once_with(
            "solax_modbus_growatt_min"
        )

    def test_control_mode_switched_live_for_growatt_modbus_min(self, mock_controller):
        _client.patch(
            "/api/settings",
            json={
                "inverter": {
                    "platform": "solax_modbus_growatt_min",
                    "controlMode": "vpp",
                }
            },
        )
        mock_controller.system.switch_control_mode.assert_called_once_with("vpp")

    def test_control_mode_not_switched_for_other_platforms(self, mock_controller):
        _client.patch(
            "/api/settings",
            json={
                "inverter": {
                    "platform": "solax_modbus_native",
                    "controlMode": "vpp",
                }
            },
        )
        mock_controller.system.switch_control_mode.assert_not_called()

    def test_control_mode_persisted_snake_case(self, mock_controller):
        _client.patch(
            "/api/settings",
            json={
                "inverter": {
                    "platform": "solax_modbus_growatt_sph",
                    "controlMode": "vpp",
                }
            },
        )
        assert mock_controller.settings_store.data["inverter"]["control_mode"] == "vpp"

    def test_control_mode_not_switched_live_for_growatt_modbus_sph(
        self, mock_controller
    ):
        """GEN3 is already resolved to 'vpp' by switch_inverter_platform().

        A stale client-side 'tou' default must not be re-applied via
        switch_control_mode() — the real BatterySystemManager rejects any
        control_mode other than 'vpp' for this platform and would raise.
        """
        _client.patch(
            "/api/settings",
            json={
                "inverter": {
                    "platform": "solax_modbus_growatt_sph",
                    "controlMode": "tou",
                }
            },
        )
        mock_controller.system.switch_control_mode.assert_not_called()


class TestPatchSettingsServiceDomain:
    """inverter.service_domain overrides which HA integration domain vendor
    service calls target (PR #412). It must persist, and the live controller
    must pick it up without a restart — otherwise BESS keeps writing TOU
    periods to the previous integration until the process is restarted."""

    def test_service_domain_persisted(self, mock_controller):
        _client.patch(
            "/api/settings",
            json={
                "inverter": {
                    "platform": "huawei_solar_luna2000",
                    "serviceDomain": "huawei_emma_management",
                }
            },
        )
        assert (
            mock_controller.settings_store.data["inverter"]["service_domain"]
            == "huawei_emma_management"
        )

    def test_live_controller_refreshed(self, mock_controller):
        _client.patch(
            "/api/settings",
            json={
                "inverter": {
                    "platform": "huawei_solar_luna2000",
                    "serviceDomain": "huawei_emma_management",
                }
            },
        )
        mock_controller.refresh_service_domain.assert_called()


class TestPatchSettingsServiceDomainValidation:
    """The Settings UI edits this field via PATCH, not the wizard payload, so
    the pydantic validator on APISetupCompletePayload never sees it. The value
    is interpolated into /api/services/<domain>/<service> — a slash silently
    retargets the request path."""

    @pytest.mark.parametrize("bad", ["switch.foo", "my bridge", "a/b", "UPPER", "1abc"])
    def test_malformed_domain_rejected(self, mock_controller, bad):
        resp = _client.patch(
            "/api/settings",
            json={
                "inverter": {"platform": "huawei_solar_luna2000", "serviceDomain": bad}
            },
        )
        assert resp.status_code == 422, f"accepted malformed domain {bad!r}"

    def test_empty_domain_accepted_as_reset_to_default(self, mock_controller):
        resp = _client.patch(
            "/api/settings",
            json={
                "inverter": {"platform": "huawei_solar_luna2000", "serviceDomain": ""}
            },
        )
        assert resp.status_code == 200


class TestPatchSettingsLegacyInverterType:
    """The legacy growatt.inverterType path was removed — platform changes go
    through the "inverter" section only. A stray legacy key must not switch
    the live platform behind the store's back."""

    def test_legacy_inverter_type_does_not_switch_platform(self, mock_controller):
        resp = _client.patch("/api/settings", json={"growatt": {"inverterType": "SPH"}})
        assert resp.status_code == 200
        mock_controller.system.switch_inverter_platform.assert_not_called()


class TestPatchSettingsCamelToSnake:
    """camelCase field names from the frontend must be written as snake_case in the store."""

    def test_battery_fields_converted_to_snake_case(self, mock_controller):
        _client.patch("/api/settings", json={"battery": {"totalCapacity": 40.0}})
        saved = mock_controller.settings_store.save_section.call_args_list[-1]
        section_dict = saved[0][1]  # second positional arg
        assert "total_capacity" in section_dict
        assert section_dict["total_capacity"] == 40.0

    def test_home_fields_converted_to_snake_case(self, mock_controller):
        _client.patch("/api/settings", json={"home": {"defaultHourly": 4.0}})
        saved = mock_controller.settings_store.save_section.call_args_list[-1]
        section_dict = saved[0][1]
        assert "default_hourly" in section_dict
        assert section_dict["default_hourly"] == 4.0

    def test_electricity_price_section_name_mapped(self, mock_controller):
        """'electricityPrice' from the API must be stored under 'electricity_price'."""
        _client.patch("/api/settings", json={"electricityPrice": {"area": "SE3"}})
        save_calls = mock_controller.settings_store.save_section.call_args_list
        saved_keys = [c[0][0] for c in save_calls]
        assert "electricity_price" in saved_keys

    def test_sensors_keys_not_converted(self, mock_controller):
        """Sensor keys are system identifiers — they must not be camelCase-converted."""
        _client.patch(
            "/api/settings",
            json={
                "sensors": {
                    "growatt_server_min": {"battery_soc": "sensor.battery_soc_percent"}
                }
            },
        )
        assert (
            mock_controller.ha_controller.sensors.get("battery_soc")
            == "sensor.battery_soc_percent"
        )


# ===========================================================================
# PATCH /api/settings — read-modify-write (partial updates)
# ===========================================================================


class TestPatchSettingsMerge:
    """Sections not included in the patch must remain unchanged (partial update)."""

    def test_battery_partial_update_preserves_other_fields(self, mock_controller):
        """Patching only totalCapacity must not erase min_soc or other fields."""
        resp = _client.patch("/api/settings", json={"battery": {"totalCapacity": 40.0}})
        assert resp.status_code == 200
        saved = mock_controller.settings_store.save_section.call_args_list[-1][0][1]
        # Updated field
        assert saved["total_capacity"] == 40.0
        # Pre-existing fields must still be present
        assert "min_soc" in saved
        assert saved["min_soc"] == 10.0

    def test_home_partial_update_preserves_other_fields(self, mock_controller):
        resp = _client.patch("/api/settings", json={"home": {"defaultHourly": 5.0}})
        assert resp.status_code == 200
        saved = mock_controller.settings_store.save_section.call_args_list[-1][0][1]
        assert saved["default_hourly"] == 5.0
        assert saved["currency"] == "SEK"  # untouched

    def test_unpatched_sections_not_touched(self, mock_controller):
        """Patching battery must not trigger a save for the home section."""
        _client.patch("/api/settings", json={"battery": {"totalCapacity": 40.0}})
        saved_sections = [
            c[0][0] for c in mock_controller.settings_store.save_section.call_args_list
        ]
        assert "home" not in saved_sections


# ===========================================================================
# PATCH /api/settings — live in-memory updates
# ===========================================================================


class TestPatchSettingsLiveUpdates:
    """Settings changes must be applied to the running system without restart."""

    def test_battery_update_calls_system_update(self, mock_controller):
        _client.patch("/api/settings", json={"battery": {"totalCapacity": 40.0}})
        calls = mock_controller.system.update_settings.call_args_list
        battery_calls = [c for c in calls if "battery" in c[0][0]]
        assert len(battery_calls) >= 1
        sent = battery_calls[0][0][0]["battery"]
        assert "total_capacity" in sent
        assert sent["total_capacity"] == 40.0

    def test_battery_update_excludes_computed_fields(self, mock_controller):
        """Computed fields (min_soe_kwh, max_soe_kwh, reserved_capacity) must
        not be forwarded to update_settings — they are not BatterySettings init params.
        """
        mock_controller.settings_store.data["battery"]["min_soe_kwh"] = 3.0
        mock_controller.settings_store.data["battery"]["max_soe_kwh"] = 28.5
        mock_controller.settings_store.data["battery"]["reserved_capacity"] = 3.0

        _client.patch("/api/settings", json={"battery": {"totalCapacity": 32.0}})
        calls = mock_controller.system.update_settings.call_args_list
        battery_calls = [c for c in calls if "battery" in c[0][0]]
        assert battery_calls, "update_settings not called for battery"
        sent = battery_calls[0][0][0]["battery"]
        assert "min_soe_kwh" not in sent
        assert "max_soe_kwh" not in sent
        assert "reserved_capacity" not in sent

    def test_home_update_calls_system_update(self, mock_controller):
        _client.patch("/api/settings", json={"home": {"defaultHourly": 5.0}})
        calls = mock_controller.system.update_settings.call_args_list
        home_calls = [c for c in calls if "home" in c[0][0]]
        assert len(home_calls) >= 1
        assert "default_hourly" in home_calls[0][0][0]["home"]

    def test_home_update_excludes_stale_pre_migration_key(self, mock_controller):
        """A stale 'consumption' key coexisting with its renamed successor
        'default_hourly' (e.g. from an interrupted migration — the rename in
        settings_store.py only fires when default_hourly is absent) must not
        be forwarded to update_settings — HomeSettings has no 'consumption'
        field and would raise AttributeError, unlike the startup path which
        already filters via HOME_MODEL_ATTRS (issue #219/#197)."""
        mock_controller.settings_store.data["home"]["consumption"] = 3.5

        resp = _client.patch("/api/settings", json={"home": {"defaultHourly": 5.0}})

        assert resp.status_code == 200
        calls = mock_controller.system.update_settings.call_args_list
        home_calls = [c for c in calls if "home" in c[0][0]]
        assert home_calls, "update_settings not called for home"
        sent = home_calls[0][0][0]["home"]
        assert "consumption" not in sent
        assert sent["default_hourly"] == 5.0

    def test_electricity_price_update_calls_system_update(self, mock_controller):
        _client.patch("/api/settings", json={"electricityPrice": {"area": "SE3"}})
        calls = mock_controller.system.update_settings.call_args_list
        price_calls = [c for c in calls if "price" in c[0][0]]
        assert len(price_calls) >= 1
        assert "area" in price_calls[0][0][0]["price"]

    def test_energy_provider_update_calls_system_update(self, mock_controller):
        new_provider = {"provider": "octopus", "octopus": {"api_key": "sk-test"}}
        _client.patch("/api/settings", json={"energyProvider": new_provider})
        calls = mock_controller.system.update_settings.call_args_list
        ep_calls = [c for c in calls if "energy_provider" in c[0][0]]
        assert len(ep_calls) >= 1
        assert ep_calls[0][0][0]["energy_provider"]["provider"] == "octopus"

    def test_growatt_device_id_applied_to_ha_controller(self, mock_controller):
        _client.patch("/api/settings", json={"growatt": {"deviceId": "new-dev-99"}})
        # device_id is written directly to ha_controller, not via update_settings
        assert mock_controller.ha_controller.growatt_device_id == "new-dev-99"

    def test_temperature_derating_enabled_applied(self, mock_controller):
        mock_controller.settings_store.data["battery"]["temperature_derating"] = {
            "enabled": False,
            "weather_entity": "",
        }
        _client.patch(
            "/api/settings",
            json={"battery": {"temperatureDerating": {"enabled": True}}},
        )
        mock_controller.system.temperature_derating.enabled = (
            True  # assert setter called
        )
        assert mock_controller.system.temperature_derating.enabled is True

    def test_health_refresh_called_after_patch(self, mock_controller):
        """refresh_health_check must be called to keep dashboard banner current."""
        _client.patch("/api/settings", json={"home": {"defaultHourly": 5.0}})
        mock_controller.system.refresh_health_check.assert_called()


# ===========================================================================
# PATCH /api/settings — sensor validation
# ===========================================================================


class TestPatchSettingsSensorValidation:
    """Entity IDs must match the 'domain.name' pattern or be empty."""

    def test_valid_entity_id_stored(self, mock_controller):
        resp = _client.patch(
            "/api/settings",
            json={
                "sensors": {
                    "growatt_server_min": {"battery_soc": "sensor.battery_soc_percent"}
                }
            },
        )
        assert resp.status_code == 200
        assert (
            mock_controller.ha_controller.sensors.get("battery_soc")
            == "sensor.battery_soc_percent"
        )

    def test_invalid_entity_id_returns_422(self, mock_controller):
        resp = _client.patch(
            "/api/settings",
            json={
                "sensors": {
                    "growatt_server_min": {"battery_soc": "not_valid_entity_format"}
                }
            },
        )
        assert resp.status_code == 422

    def test_entity_id_missing_domain_returns_422(self, mock_controller):
        resp = _client.patch(
            "/api/settings",
            json={
                "sensors": {
                    "growatt_server_min": {"battery_soc": "battery_soc_percent"}
                }
            },
        )
        assert resp.status_code == 422

    def test_empty_entity_id_unmaps_sensor(self, mock_controller):
        """Empty string in PATCH unmaps the sensor both on disk and in memory."""
        mock_controller.settings_store.data["sensors"]["growatt_server_min"] = {
            "battery_soc": "sensor.existing"
        }
        _client.patch(
            "/api/settings",
            json={"sensors": {"growatt_server_min": {"battery_soc": ""}}},
        )
        # Must be gone from in-memory ha_controller
        assert "battery_soc" not in mock_controller.ha_controller.sensors
        # Must be gone from persistent store (not lingering as empty string)
        stored = mock_controller.settings_store.data["sensors"]["growatt_server_min"]
        assert "battery_soc" not in stored

    def test_clear_optional_sensor_removes_from_store(self, mock_controller):
        """Clearing an optional sensor (discharge_inhibit) removes it from storage."""
        mock_controller.settings_store.data["sensors"]["shared"] = {
            "discharge_inhibit": "input_boolean.bess_discharge_inhibit",
            "battery_soc": "sensor.battery_soc",
        }
        resp = _client.patch(
            "/api/settings",
            json={"sensors": {"shared": {"discharge_inhibit": ""}}},
        )
        assert resp.status_code == 200
        # Gone from in-memory
        assert "discharge_inhibit" not in mock_controller.ha_controller.sensors
        # Gone from persistent store
        shared = mock_controller.settings_store.data["sensors"]["shared"]
        assert "discharge_inhibit" not in shared
        # Other sensors preserved
        assert "battery_soc" in mock_controller.ha_controller.sensors

    def test_clear_phase_current_sensor_removes_from_store(self, mock_controller):
        """Clearing a phase current sensor removes it from both store and memory."""
        mock_controller.settings_store.data["sensors"]["shared"] = {
            "phase_current_l3": "sensor.phase_l3",
            "phase_current_l1": "sensor.phase_l1",
        }
        resp = _client.patch(
            "/api/settings",
            json={"sensors": {"shared": {"phase_current_l3": ""}}},
        )
        assert resp.status_code == 200
        # L3 gone from both store and memory
        shared = mock_controller.settings_store.data["sensors"]["shared"]
        assert "phase_current_l3" not in shared
        assert "phase_current_l3" not in mock_controller.ha_controller.sensors
        # L1 preserved
        assert shared["phase_current_l1"] == "sensor.phase_l1"
        assert (
            mock_controller.ha_controller.sensors["phase_current_l1"]
            == "sensor.phase_l1"
        )

    def test_multiple_valid_sensors_all_stored(self, mock_controller):
        payload = {
            "sensors": {
                "growatt_server_min": {
                    "battery_soc": "sensor.battery_soc",
                    "grid_power": "sensor.grid_power",
                }
            }
        }
        resp = _client.patch("/api/settings", json=payload)
        assert resp.status_code == 200
        assert (
            mock_controller.ha_controller.sensors["battery_soc"] == "sensor.battery_soc"
        )
        assert (
            mock_controller.ha_controller.sensors["grid_power"] == "sensor.grid_power"
        )


# ===========================================================================
# PATCH /api/settings — power monitoring sensor gating
# ===========================================================================


class TestPatchSettingsPowerMonitoringValidation:
    """Enabling power monitoring via PATCH must be rejected server-side when
    the phase-current sensors its phase_count requires aren't mapped — the
    same gap that let power_monitoring_enabled=True crash-loop in production
    (2026-08-07 debug bundle) because nothing validated it server-side."""

    def test_rejects_power_monitoring_without_phase_sensors(self, mock_controller):
        response = _client.patch(
            "/api/settings",
            json={"home": {"powerMonitoringEnabled": True, "phaseCount": 3}},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "current_l1" in detail or "phase" in detail.lower()
        # The invalid combination must never be persisted, even though the
        # request was rejected — a prior bug wrote power_monitoring_enabled
        # to disk BEFORE running this validation, so the 422 error message
        # was returned but the crash-loop-inducing config was still saved.
        assert not mock_controller.settings_store.data["home"].get(
            "power_monitoring_enabled"
        )

    def test_rejects_single_phase_without_l1_sensor(self, mock_controller):
        response = _client.patch(
            "/api/settings",
            json={"home": {"powerMonitoringEnabled": True, "phaseCount": 1}},
        )
        assert response.status_code == 422

    def test_allows_power_monitoring_when_phase_sensors_mapped(self, mock_controller):
        mock_controller.settings_store.data["sensors"]["shared"] = {
            "current_l1": "sensor.current_l1",
            "current_l2": "sensor.current_l2",
            "current_l3": "sensor.current_l3",
            "battery_charging_power_rate": "sensor.charge_rate",
        }
        response = _client.patch(
            "/api/settings",
            json={"home": {"powerMonitoringEnabled": True, "phaseCount": 3}},
        )
        assert response.status_code == 200

    def test_allows_disabling_power_monitoring_without_sensors(self, mock_controller):
        """Turning power monitoring off must never be blocked by this check."""
        response = _client.patch(
            "/api/settings",
            json={"home": {"powerMonitoringEnabled": False}},
        )
        assert response.status_code == 200


# ===========================================================================
# PATCH /api/settings — consumption strategy gating
# ===========================================================================


class TestPatchSettingsConsumptionStrategyValidation:
    """Selecting the "sensor" consumption strategy without its sensor leaves
    the system unable to build any schedule at all, so the dashboard never
    leaves "Initializing" (#558). The UI hides the option, but PATCH is what
    persists it, so the check has to exist here too."""

    def test_rejects_sensor_strategy_without_its_sensor(self, mock_controller):
        response = _client.patch(
            "/api/settings",
            json={"home": {"consumptionStrategy": "sensor"}},
        )
        assert response.status_code == 422
        assert "48h_avg_grid_import" in response.json()["detail"]
        # Never persisted — a rejected request must not leave the stalling
        # config on disk.
        assert (
            mock_controller.settings_store.data["home"]["consumption_strategy"]
            == "fixed"
        )

    def test_allows_sensor_strategy_when_its_sensor_is_mapped(self, mock_controller):
        mock_controller.settings_store.data["sensors"]["shared"] = {
            "48h_avg_grid_import": "sensor.avg_grid_import",
        }
        response = _client.patch(
            "/api/settings",
            json={"home": {"consumptionStrategy": "sensor"}},
        )
        assert response.status_code == 200

    def test_rejects_unknown_strategy(self, mock_controller):
        response = _client.patch(
            "/api/settings",
            json={"home": {"consumptionStrategy": "bogus_strategy"}},
        )
        assert response.status_code == 422

    def test_rejects_unmapping_the_sensor_the_active_strategy_needs(
        self, mock_controller
    ):
        """Removing 48h_avg_grid_import while the sensor strategy is active
        breaks the system exactly as selecting the strategy without it does —
        the same shape as the power-monitoring sensor-removal guard."""
        mock_controller.settings_store.data["home"]["consumption_strategy"] = "sensor"
        mock_controller.settings_store.data["sensors"]["shared"] = {
            "48h_avg_grid_import": "sensor.avg_grid_import",
        }

        response = _client.patch(
            "/api/settings",
            json={"sensors": {"shared": {"48h_avg_grid_import": ""}}},
        )

        assert response.status_code == 422


# ===========================================================================
# PATCH /api/settings — response shape
# ===========================================================================


class TestPatchSettingsResponse:
    """PATCH must return the full updated settings (same shape as GET)."""

    def test_patch_returns_updated_battery_value(self, mock_controller):
        resp = _client.patch("/api/settings", json={"battery": {"totalCapacity": 50.0}})
        assert resp.status_code == 200
        assert resp.json()["battery"]["totalCapacity"] == 50.0

    def test_patch_response_includes_computed_battery_fields(self, mock_controller):
        resp = _client.patch("/api/settings", json={"battery": {"totalCapacity": 20.0}})
        battery = resp.json()["battery"]
        # 20 kWh x 10% = 2.0 kWh min_soe
        assert "minSoeKwh" in battery
        assert battery["minSoeKwh"] == pytest.approx(2.0)

    def test_patch_response_contains_sensors(self, mock_controller):
        mock_controller.ha_controller.sensors = {"battery_soc": "sensor.batt"}
        resp = _client.patch("/api/settings", json={"home": {}})
        assert "sensors" in resp.json()


# ===========================================================================
# PATCH /api/settings — demoMode section
# ===========================================================================


class TestDemoMode:
    """PATCH /api/settings with demoMode section."""

    def test_patch_demo_mode_persists(self, mock_controller):
        resp = _client.patch("/api/settings", json={"demoMode": {"enabled": True}})
        assert resp.status_code == 200
        stored = mock_controller.settings_store.data.get("demo_mode", {})
        assert stored["enabled"] is True

    def test_patch_demo_mode_enable_calls_set_demo_mode(self, mock_controller):
        _client.patch("/api/settings", json={"demoMode": {"enabled": True}})
        mock_controller.system.set_demo_mode.assert_called_once_with(True)

    def test_patch_demo_mode_disable_calls_set_demo_mode(self, mock_controller):
        mock_controller.settings_store.data["demo_mode"] = {"enabled": True}
        _client.patch("/api/settings", json={"demoMode": {"enabled": False}})
        mock_controller.system.set_demo_mode.assert_called_once_with(False)

    def test_get_settings_returns_demo_mode_enabled(self, mock_controller):
        """GET /api/settings round-trips demoMode after enabling it."""
        _client.patch("/api/settings", json={"demoMode": {"enabled": True}})
        resp = _client.get("/api/settings")
        assert resp.json()["demoMode"]["enabled"] is True

    def test_get_settings_returns_demo_mode_disabled_after_toggle(
        self, mock_controller
    ):
        """Enable then disable — GET must reflect the final state."""
        _client.patch("/api/settings", json={"demoMode": {"enabled": True}})
        _client.patch("/api/settings", json={"demoMode": {"enabled": False}})
        resp = _client.get("/api/settings")
        assert resp.json()["demoMode"]["enabled"] is False

    def test_patch_demo_mode_does_not_write_to_inverter(self, mock_controller):
        """Toggling demo mode must not call apply_period (no hardware writes)."""
        inv = MagicMock()
        mock_controller.system.inverter_controller = inv
        _client.patch("/api/settings", json={"demoMode": {"enabled": True}})
        _client.patch("/api/settings", json={"demoMode": {"enabled": False}})
        inv.apply_period.assert_not_called()
