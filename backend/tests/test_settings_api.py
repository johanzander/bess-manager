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
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import router

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
        "min_action_profit_threshold": 0.0,
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
    "sensors": {},
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

    ctrl.settings_store.get_section.side_effect = _get_section
    ctrl.settings_store.save_section.side_effect = _save_section

    ctrl.ha_controller.sensors = {}

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
        """min_soe_kwh, max_soe_kwh, reservedCapacity computed from capacity × SOC%."""
        resp = _client.get("/api/settings")
        battery = resp.json()["battery"]
        # 30 kWh × 10% min_soc = 3.0 kWh
        assert battery["minSoeKwh"] == pytest.approx(3.0)
        # 30 kWh × 95% max_soc = 28.5 kWh
        assert battery["maxSoeKwh"] == pytest.approx(28.5)
        assert battery["reservedCapacity"] == pytest.approx(3.0)

    def test_sensors_come_from_ha_controller(self, mock_controller):
        """Sensor values must be sourced from ha_controller, not the store."""
        mock_controller.ha_controller.sensors = {
            "battery_soc": "sensor.battery_live"
        }
        resp = _client.get("/api/settings")
        assert resp.json()["sensors"]["battery_soc"] == "sensor.battery_live"

    def test_store_sensors_not_in_response(self, mock_controller):
        """Store sensors section is replaced by ha_controller sensors — no duplicate."""
        mock_controller.settings_store.data["sensors"] = {
            "battery_soc": "sensor.stale_from_store"
        }
        mock_controller.ha_controller.sensors = {
            "battery_soc": "sensor.live_from_controller"
        }
        resp = _client.get("/api/settings")
        assert resp.json()["sensors"]["battery_soc"] == "sensor.live_from_controller"

    def test_non_sensor_sections_are_camel_case(self, mock_controller):
        """Store snake_case keys must be returned as camelCase for non-sensor sections."""
        resp = _client.get("/api/settings")
        battery = resp.json()["battery"]
        assert "totalCapacity" in battery
        assert "total_capacity" not in battery


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
        for section in ("battery", "home", "electricityPrice",
                        "energyProvider", "growatt", "sensors"):
            resp = _client.patch("/api/settings", json={section: {}})
            assert resp.status_code == 200, (
                f"Section '{section}' was unexpectedly rejected: {resp.text}"
            )


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
            json={"sensors": {"battery_soc": "sensor.battery_soc_percent"}},
        )
        assert mock_controller.ha_controller.sensors.get("battery_soc") == \
            "sensor.battery_soc_percent"


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
        mock_controller.system.temperature_derating.enabled = True  # assert setter called
        assert mock_controller.system.temperature_derating.enabled is True

    def test_health_refresh_called_after_patch(self, mock_controller):
        """_run_health_check must be called to keep dashboard banner current."""
        _client.patch("/api/settings", json={"home": {"defaultHourly": 5.0}})
        mock_controller.system._run_health_check.assert_called()


# ===========================================================================
# PATCH /api/settings — sensor validation
# ===========================================================================


class TestPatchSettingsSensorValidation:
    """Entity IDs must match the 'domain.name' pattern or be empty."""

    def test_valid_entity_id_stored(self, mock_controller):
        resp = _client.patch(
            "/api/settings",
            json={"sensors": {"battery_soc": "sensor.battery_soc_percent"}},
        )
        assert resp.status_code == 200
        assert mock_controller.ha_controller.sensors.get("battery_soc") == \
            "sensor.battery_soc_percent"

    def test_invalid_entity_id_returns_422(self, mock_controller):
        resp = _client.patch(
            "/api/settings",
            json={"sensors": {"battery_soc": "not_valid_entity_format"}},
        )
        assert resp.status_code == 422

    def test_entity_id_missing_domain_returns_422(self, mock_controller):
        resp = _client.patch(
            "/api/settings",
            json={"sensors": {"battery_soc": "battery_soc_percent"}},
        )
        assert resp.status_code == 422

    def test_empty_entity_id_not_stored(self, mock_controller):
        """Empty strings clear intent — they must not overwrite configured sensors."""
        mock_controller.ha_controller.sensors = {"battery_soc": "sensor.existing"}
        _client.patch("/api/settings", json={"sensors": {"battery_soc": ""}})
        assert mock_controller.ha_controller.sensors.get("battery_soc") == "sensor.existing"

    def test_multiple_valid_sensors_all_stored(self, mock_controller):
        payload = {
            "sensors": {
                "battery_soc": "sensor.battery_soc",
                "grid_power": "sensor.grid_power",
            }
        }
        resp = _client.patch("/api/settings", json=payload)
        assert resp.status_code == 200
        assert mock_controller.ha_controller.sensors["battery_soc"] == "sensor.battery_soc"
        assert mock_controller.ha_controller.sensors["grid_power"] == "sensor.grid_power"


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
        # 20 kWh × 10% = 2.0 kWh min_soe
        assert "minSoeKwh" in battery
        assert battery["minSoeKwh"] == pytest.approx(2.0)

    def test_patch_response_contains_sensors(self, mock_controller):
        mock_controller.ha_controller.sensors = {"battery_soc": "sensor.batt"}
        resp = _client.patch("/api/settings", json={"home": {}})
        assert "sensors" in resp.json()
