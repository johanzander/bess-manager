"""Tests for SettingsStore — the unified persistent settings backend.

All tests focus on BEHAVIOR: what the store does, not how it stores it
internally. Tests use a temporary directory so they never touch /data/.
"""

import json
import os

import pytest
import settings_store as _sm
from api_dataclasses import (
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

    def test_discovery_overwrites_existing_sensor(self, tmp_path, monkeypatch):
        """A non-empty discovered entity ID replaces the existing sensor value.

        This is intentional: re-running discovery must be able to correct a
        previously wrong entity ID.  The wizard preserves existing values only
        when discovery returns nothing (empty string), which is handled by the
        ``if entity_id:`` guard in apply_discovered.
        """
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("sensors", {"battery_soc": "sensor.old_value"})

        store.apply_discovered(
            sensor_map={"battery_soc": "sensor.corrected_by_discovery"},
        )

        assert store.get_section("sensors")["battery_soc"] == "sensor.corrected_by_discovery"

    def test_discovery_empty_does_not_overwrite_existing_sensor(self, tmp_path, monkeypatch):
        """An empty discovered value leaves the existing sensor value intact."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("sensors", {"battery_soc": "sensor.user_configured"})

        store.apply_discovered(
            sensor_map={"battery_soc": ""},
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
# Schema migration (_migrate_schema)
# ---------------------------------------------------------------------------


class TestSchemaMigration:
    """_migrate_schema must rename legacy fields and add missing defaults.

    All tests write an *old* settings file to disk, load it via SettingsStore,
    and assert that the in-memory (and re-persisted) data uses the new names.
    """

    def _store_with_data(self, tmp_path, monkeypatch, data: dict) -> SettingsStore:
        """Write raw data to the settings file and load it into a SettingsStore."""
        path = _settings_path(tmp_path)
        monkeypatch.setattr(_sm, "SETTINGS_PATH", path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        store = SettingsStore()
        store.load({})
        return store

    def test_home_consumption_renamed_to_default_hourly(self, tmp_path, monkeypatch):
        """Old field 'consumption' must be renamed to 'default_hourly' on load."""
        store = self._store_with_data(
            tmp_path, monkeypatch,
            {"home": {"consumption": 4.5, "currency": "SEK"}},
        )
        home = store.get_section("home")
        assert "default_hourly" in home, "Old 'consumption' not renamed to 'default_hourly'"
        assert home["default_hourly"] == 4.5
        assert "consumption" not in home

    def test_home_safety_margin_factor_renamed(self, tmp_path, monkeypatch):
        """Old field 'safety_margin_factor' must be renamed to 'safety_margin' on load."""
        store = self._store_with_data(
            tmp_path, monkeypatch,
            {"home": {"safety_margin_factor": 1.2, "currency": "SEK"}},
        )
        home = store.get_section("home")
        assert "safety_margin" in home
        assert home["safety_margin"] == 1.2
        assert "safety_margin_factor" not in home

    def test_battery_max_charge_discharge_power_split(self, tmp_path, monkeypatch):
        """Old single-power field must be split into charge and discharge variants."""
        store = self._store_with_data(
            tmp_path, monkeypatch,
            {"battery": {"max_charge_discharge_power": 10.0, "total_capacity": 30.0}},
        )
        battery = store.get_section("battery")
        assert "max_charge_power_kw" in battery
        assert "max_discharge_power_kw" in battery
        assert battery["max_charge_power_kw"] == 10.0
        assert battery["max_discharge_power_kw"] == 10.0
        assert "max_charge_discharge_power" not in battery

    def test_battery_cycle_cost_renamed(self, tmp_path, monkeypatch):
        """Old field 'cycle_cost' must be renamed to 'cycle_cost_per_kwh'."""
        store = self._store_with_data(
            tmp_path, monkeypatch,
            {"battery": {"cycle_cost": 0.8, "total_capacity": 30.0}},
        )
        battery = store.get_section("battery")
        assert "cycle_cost_per_kwh" in battery
        assert battery["cycle_cost_per_kwh"] == 0.8
        assert "cycle_cost" not in battery

    def test_battery_missing_fields_get_defaults(self, tmp_path, monkeypatch):
        """Fields absent from an old store file are added with safe defaults."""
        store = self._store_with_data(
            tmp_path, monkeypatch,
            {"battery": {"total_capacity": 30.0}},
        )
        battery = store.get_section("battery")
        for field in ("cycle_cost_per_kwh", "min_action_profit_threshold",
                      "charging_power_rate", "efficiency_charge", "efficiency_discharge"):
            assert field in battery, f"Expected default for '{field}' to be added by migration"

    def test_migration_persists_to_disk(self, tmp_path, monkeypatch):
        """Migrated field names must be written back to disk immediately."""
        path = _settings_path(tmp_path)
        monkeypatch.setattr(_sm, "SETTINGS_PATH", path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"home": {"consumption": 3.0, "currency": "NOK"}}, f)

        # First load triggers migration and persists
        SettingsStore().load({})

        # Second load reads the persisted file — must show new field name
        store2 = SettingsStore()
        store2.load({})
        assert store2.get_section("home")["default_hourly"] == 3.0
        assert "consumption" not in store2.get_section("home")

    def test_new_field_names_not_doubled(self, tmp_path, monkeypatch):
        """If a file already uses new field names, migration must not create duplicates."""
        store = self._store_with_data(
            tmp_path, monkeypatch,
            {
                "battery": {
                    "max_charge_power_kw": 12.0,
                    "max_discharge_power_kw": 12.0,
                    "cycle_cost_per_kwh": 0.6,
                    "total_capacity": 30.0,
                },
                "home": {
                    "default_hourly": 3.5,
                    "safety_margin": 1.0,
                    "currency": "SEK",
                },
            },
        )
        battery = store.get_section("battery")
        assert "max_charge_discharge_power" not in battery
        home = store.get_section("home")
        assert "consumption" not in home
        assert "safety_margin_factor" not in home
