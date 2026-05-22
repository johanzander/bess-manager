"""Tests for setup wizard API endpoints.

Coverage goals:
- GET /api/setup/status: returns wizard_needed based on sensor config
- POST /api/setup/confirm: validates entity IDs, persists config
- POST /api/setup/complete: persists final settings
"""

import sys
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


class TestConfirmSetup:
    """POST /api/setup/confirm."""

    def test_rejects_invalid_entity_ids(self, mock_controller):
        resp = _client.post(
            "/api/setup/confirm",
            json={"sensors": {"battery_soc": "not-valid-format"}},
        )
        assert resp.status_code == 422

    def test_accepts_valid_entity_ids(self, mock_controller):
        mock_controller.ha_controller.apply_discovered_config = MagicMock()
        resp = _client.post(
            "/api/setup/confirm",
            json={
                "sensors": {"battery_soc": "sensor.growatt_battery_soc"},
                "nordpool_area": "SE4",
                "nordpool_config_entry_id": "abc-123",
            },
        )
        assert resp.status_code == 200

    def test_accepts_empty_sensors(self, mock_controller):
        mock_controller.ha_controller.apply_discovered_config = MagicMock()
        resp = _client.post("/api/setup/confirm", json={"sensors": {}})
        assert resp.status_code == 200


class TestSetupComplete:
    """POST /api/setup/complete."""

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
