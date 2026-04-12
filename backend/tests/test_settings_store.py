"""Tests for SettingsStore — the unified persistent settings backend.

All tests focus on BEHAVIOR: what the store does, not how it stores it
internally. Tests use a temporary directory so they never touch /data/.
"""

import json
import os

import pytest
import settings_store as _sm
from api_dataclasses import (
    APIHomeSettingsPayload,
    APIPriceSettings,
    APISensorsPayload,
    APISetupCompletePayload,
)
from pydantic import ValidationError
from settings_store import SettingsStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_path(tmp_path) -> str:
    return str(tmp_path / "bess_settings.json")


def _patch_path(tmp_path, monkeypatch):
    """Redirect the module-level SETTINGS_PATH to tmp_path for isolation."""
    path = _settings_path(tmp_path)
    monkeypatch.setattr(_sm, "SETTINGS_PATH", path)
    return path


# ---------------------------------------------------------------------------
# First-boot migration
# ---------------------------------------------------------------------------


class TestFirstBootMigration:
    """SettingsStore must migrate settings from options.json on first boot."""

    def test_migration_creates_settings_file(self, tmp_path, monkeypatch):
        """On first boot, settings file should be created from options."""
        _patch_path(tmp_path, monkeypatch)
        options = {
            "battery": {"total_capacity": 30.0, "min_soc": 10.0},
            "home": {"consumption": 8.0, "currency": "SEK"},
            "influxdb": {"url": "http://localhost:8086"},  # should NOT be migrated
        }

        store = SettingsStore()
        store.load(options)

        assert os.path.exists(_settings_path(tmp_path))

    def test_migration_carries_owned_sections(self, tmp_path, monkeypatch):
        """Owned sections from options.json appear in the store after migration."""
        _patch_path(tmp_path, monkeypatch)
        options = {
            "battery": {"total_capacity": 30.0, "min_soc": 10.0},
            "home": {"consumption": 8.0, "currency": "SEK"},
            "electricity_price": {"markup_rate": 0.05},
        }

        store = SettingsStore()
        store.load(options)

        assert store.get_section("battery")["total_capacity"] == 30.0
        assert store.get_section("home")["currency"] == "SEK"
        assert store.get_section("electricity_price")["markup_rate"] == 0.05

    def test_migration_excludes_non_owned_sections(self, tmp_path, monkeypatch):
        """Non-owned options (e.g. influxdb) must NOT appear in the store."""
        _patch_path(tmp_path, monkeypatch)
        options = {
            "battery": {"total_capacity": 30.0},
            "influxdb": {"url": "http://localhost:8086"},
        }

        store = SettingsStore()
        store.load(options)

        assert "influxdb" not in store.data

    def test_existing_file_skips_migration(self, tmp_path, monkeypatch):
        """If bess_settings.json already exists, options.json is not applied."""
        path = _patch_path(tmp_path, monkeypatch)
        # Pre-write a settings file with known content
        existing = {"battery": {"total_capacity": 10.0}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f)

        options = {"battery": {"total_capacity": 99.0}}  # different value
        store = SettingsStore()
        store.load(options)

        # Store should keep the existing file value, NOT the options value
        assert store.get_section("battery")["total_capacity"] == 10.0


# ---------------------------------------------------------------------------
# Section read / write
# ---------------------------------------------------------------------------


class TestSectionAccess:
    """get_section and save_section expose section-level data correctly."""

    def test_get_missing_section_returns_empty_dict(self, tmp_path, monkeypatch):
        """Requesting a section that doesn't exist returns {}."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})

        assert store.get_section("sensors") == {}

    def test_save_section_makes_data_readable(self, tmp_path, monkeypatch):
        """Saving a section allows it to be read back immediately."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})

        store.save_section("battery", {"total_capacity": 20.0})

        assert store.get_section("battery")["total_capacity"] == 20.0

    def test_save_section_persists_to_disk(self, tmp_path, monkeypatch):
        """Data saved via save_section survives a fresh store load."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("home", {"currency": "EUR"})

        # Load a brand-new store from the same file
        store2 = SettingsStore()
        store2.load({})

        assert store2.get_section("home")["currency"] == "EUR"

    def test_save_section_replaces_not_merges(self, tmp_path, monkeypatch):
        """Saving a section replaces its entire content."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("battery", {"total_capacity": 20.0, "min_soc": 10.0})
        # Save again with only one key
        store.save_section("battery", {"total_capacity": 25.0})

        section = store.get_section("battery")
        assert section["total_capacity"] == 25.0
        assert "min_soc" not in section

    def test_get_section_returns_copy(self, tmp_path, monkeypatch):
        """Mutating the returned dict must not affect the store."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("home", {"currency": "SEK"})

        section = store.get_section("home")
        section["currency"] = "USD"  # mutate the copy

        assert store.get_section("home")["currency"] == "SEK"


# ---------------------------------------------------------------------------
# save_all
# ---------------------------------------------------------------------------


class TestSaveAll:
    """save_all atomically replaces all provided sections."""

    def test_save_all_updates_multiple_sections(self, tmp_path, monkeypatch):
        """All provided sections are updated in one call."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})

        store.save_all(
            {
                "battery": {"total_capacity": 15.0},
                "home": {"currency": "NOK"},
            }
        )

        assert store.get_section("battery")["total_capacity"] == 15.0
        assert store.get_section("home")["currency"] == "NOK"

    def test_save_all_ignores_unknown_sections(self, tmp_path, monkeypatch):
        """Sections not in OWNED_SECTIONS are silently ignored."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})

        store.save_all({"influxdb": {"url": "http://localhost"}})

        assert "influxdb" not in store.data

    def test_save_all_leaves_unmentioned_sections_intact(self, tmp_path, monkeypatch):
        """Sections not included in a save_all call are not deleted."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("home", {"currency": "DKK"})

        store.save_all({"battery": {"total_capacity": 10.0}})

        # home section must still be present
        assert store.get_section("home")["currency"] == "DKK"

    def test_save_all_persists_to_disk(self, tmp_path, monkeypatch):
        """Data from save_all survives a fresh store load."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_all({"battery": {"total_capacity": 42.0}})

        store2 = SettingsStore()
        store2.load({})

        assert store2.get_section("battery")["total_capacity"] == 42.0


# ---------------------------------------------------------------------------
# apply_discovered — additive merging
# ---------------------------------------------------------------------------


class TestApplyDiscovered:
    """Discovery data is merged additively — existing values are never overwritten."""

    def test_discovered_sensors_are_stored(self, tmp_path, monkeypatch):
        """Sensors provided by discovery appear in the sensors section."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})

        store.apply_discovered(
            sensor_map={"battery_soc": "sensor.battery_soc"},
        )

        assert store.get_section("sensors")["battery_soc"] == "sensor.battery_soc"

    def test_discovery_does_not_overwrite_existing_sensor(self, tmp_path, monkeypatch):
        """A sensor already configured by the user is not overwritten by discovery."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("sensors", {"battery_soc": "sensor.user_configured"})

        store.apply_discovered(
            sensor_map={"battery_soc": "sensor.auto_discovered"},
        )

        assert store.get_section("sensors")["battery_soc"] == "sensor.user_configured"

    def test_nordpool_area_is_stored(self, tmp_path, monkeypatch):
        """Nordpool area discovered during setup lands in electricity_price."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})

        store.apply_discovered(sensor_map={}, nordpool_area="SE4")

        assert store.get_section("electricity_price").get("area") == "SE4"

    def test_nordpool_area_not_overwritten(self, tmp_path, monkeypatch):
        """Existing nordpool area is not overwritten by later discovery."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("electricity_price", {"area": "SE3"})

        store.apply_discovered(sensor_map={}, nordpool_area="SE4")

        assert store.get_section("electricity_price")["area"] == "SE3"

    def test_growatt_device_id_is_stored(self, tmp_path, monkeypatch):
        """Growatt device ID discovered during setup lands in the growatt section."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})

        store.apply_discovered(sensor_map={}, growatt_device_id="abc-123")

        assert store.get_section("growatt").get("device_id") == "abc-123"

    def test_empty_entity_ids_are_not_stored(self, tmp_path, monkeypatch):
        """Discovery must not store empty-string entity IDs."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})

        store.apply_discovered(sensor_map={"battery_soc": ""})

        assert store.get_section("sensors").get("battery_soc") is None


# ---------------------------------------------------------------------------
# Pydantic payload validation
# ---------------------------------------------------------------------------


class TestPayloadValidation:
    """New Pydantic payload models enforce entity-ID format and optional fields."""

    def test_sensors_payload_rejects_invalid_entity_id(self):
        """APISensorsPayload raises ValidationError for malformed entity IDs."""
        with pytest.raises(ValidationError):
            APISensorsPayload(sensors={"battery_soc": "not_valid_entity"})

    def test_sensors_payload_accepts_valid_entity_id(self):
        """APISensorsPayload accepts correctly formatted entity IDs."""
        payload = APISensorsPayload(
            sensors={"battery_soc": "sensor.battery_soc_percent"}
        )
        assert payload.sensors["battery_soc"] == "sensor.battery_soc_percent"

    def test_sensors_payload_allows_empty_entity_id(self):
        """Empty string entity IDs are allowed (sensor not yet configured)."""
        payload = APISensorsPayload(sensors={"battery_soc": ""})
        assert payload.sensors["battery_soc"] == ""

    def test_home_settings_payload_requires_all_fields(self):
        """APIHomeSettingsPayload requires all home/grid fields — it is a full PUT body."""
        with pytest.raises(ValidationError):
            APIHomeSettingsPayload()  # type: ignore[call-arg]  # missing required fields

    def test_home_settings_payload_accepts_complete_data(self):
        """APIHomeSettingsPayload is valid when all fields are provided."""
        payload = APIHomeSettingsPayload(
            currency="SEK",
            consumption=8.0,
            consumptionStrategy="fixed",
            maxFuseCurrent=25,
            voltage=230,
            safetyMarginFactor=0.9,
            phaseCount=1,
            powerMonitoringEnabled=False,
        )
        assert payload.currency == "SEK"

    def test_setup_complete_payload_entity_id_validated(self):
        """APISetupCompletePayload validates sensor entity IDs."""
        with pytest.raises(ValidationError):
            APISetupCompletePayload(sensors={"battery_soc": "BAD FORMAT"})

    def test_setup_complete_payload_accepts_partial_data(self):
        """APISetupCompletePayload works when only some fields are provided."""
        payload = APISetupCompletePayload(
            sensors={"battery_soc": "sensor.battery_soc"},
            totalCapacity=30.0,
            currency="SEK",
        )
        assert payload.totalCapacity == 30.0
        assert payload.nordpoolArea is None  # not provided


# ---------------------------------------------------------------------------
# Price settings round-trip
# ---------------------------------------------------------------------------


class TestPriceSettingsRoundTrip:
    """APIPriceSettings.to_internal_update must invert from_internal."""

    def test_to_internal_update_keys(self):
        """to_internal_update returns the expected snake_case keys."""
        settings = APIPriceSettings(
            area="SE4",
            markupRate=0.05,
            vatMultiplier=1.25,
            additionalCosts=0.02,
            taxReduction=0.0,
            minProfit=0.10,
            useActualPrice=False,
        )

        internal = settings.to_internal_update()

        assert internal["area"] == "SE4"
        assert internal["markup_rate"] == 0.05
        assert internal["vat_multiplier"] == 1.25
        assert internal["additional_costs"] == 0.02
        assert internal["tax_reduction"] == 0.0
        assert internal["min_profit"] == 0.10
        assert internal["use_actual_price"] is False
