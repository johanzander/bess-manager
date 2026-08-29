"""Tests for SettingsStore — the unified persistent settings backend.

All tests focus on BEHAVIOR: what the store does, not how it stores it
internally. Tests use a temporary directory so they never touch /data/.
"""

import json
import os
from pathlib import Path

import pytest
from api_dataclasses import (
    APISensorsPayload,
    APISetupCompletePayload,
)
from pydantic import ValidationError

import core.bess.settings_store as _sm
from core.bess.settings_store import SettingsStore

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


class TestLegacyInverterTypeMigration:
    """`growatt.inverter_type` -> `inverter.platform`.

    This migration is the *only* remaining backward-compat path for installs
    predating `inverter.platform`: the redundant fallback in
    `BatterySystemManager._resolve_initial_platform()` was removed, so if this
    rewrite ever breaks, those installs silently boot into unconfigured mode
    with no price data. Pin it explicitly.
    """

    def _load(self, tmp_path, monkeypatch, existing: dict) -> SettingsStore:
        path = _patch_path(tmp_path, monkeypatch)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f)
        store = SettingsStore()
        store.load({})
        return store

    @pytest.mark.parametrize(
        ("legacy_type", "expected_platform"),
        [("MIN", "growatt_server_min"), ("SPH", "growatt_server_sph")],
    )
    def test_legacy_type_rewritten_to_platform(
        self, tmp_path, monkeypatch, legacy_type, expected_platform
    ):
        store = self._load(
            tmp_path, monkeypatch, {"growatt": {"inverter_type": legacy_type}}
        )
        assert store.get_section("inverter")["platform"] == expected_platform

    def test_growatt_device_id_carried_over(self, tmp_path, monkeypatch):
        """The device_id moves with the platform — an SPH install that only
        ever wrote growatt.device_id must not lose it."""
        store = self._load(
            tmp_path,
            monkeypatch,
            {"growatt": {"inverter_type": "SPH", "device_id": "dev-42"}},
        )
        assert store.get_section("inverter")["device_id"] == "dev-42"

    def test_existing_platform_wins_over_legacy_type(self, tmp_path, monkeypatch):
        """A config carrying both keys keeps inverter.platform — it is the
        source of truth, and a stale inverter_type must not override it."""
        store = self._load(
            tmp_path,
            monkeypatch,
            {
                "growatt": {"inverter_type": "MIN"},
                "inverter": {"platform": "solax_modbus_native"},
            },
        )
        assert store.get_section("inverter")["platform"] == "solax_modbus_native"

    def test_unknown_legacy_type_leaves_platform_unset(self, tmp_path, monkeypatch):
        """An unrecognised value must not invent a platform."""
        store = self._load(
            tmp_path, monkeypatch, {"growatt": {"inverter_type": "BOGUS"}}
        )
        assert not store.get_section("inverter").get("platform")

    def test_migrated_config_resolves_to_configured_platform(
        self, tmp_path, monkeypatch
    ):
        """End-to-end: the migrated store feeds BatterySystemManager's startup
        resolution, which no longer reads growatt.inverter_type itself."""
        from core.bess.battery_system_manager import BatterySystemManager

        store = self._load(tmp_path, monkeypatch, {"growatt": {"inverter_type": "SPH"}})
        assert (
            BatterySystemManager._resolve_initial_platform(store.data)
            == "growatt_server_sph"
        )


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

        sensors = store.get_section("sensors")
        assert "platform" in sensors  # per-platform structure from bootstrap defaults

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
        """Sensors provided by discovery appear in the active platform sub-dict."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        # Set an active platform so apply_discovered routes to the right sub-dict
        sensors = store.get_section("sensors")
        sensors["platform"] = "growatt_server_min"
        store.save_section("sensors", sensors)

        store.apply_discovered(
            sensor_map={"battery_soc": "sensor.battery_soc"},
        )

        assert store.get_active_sensors()["battery_soc"] == "sensor.battery_soc"

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
        sensors = store.get_section("sensors")
        sensors["platform"] = "growatt_server_min"
        sensors["growatt_server_min"] = {"battery_soc": "sensor.old_value"}
        store.save_section("sensors", sensors)

        store.apply_discovered(
            sensor_map={"battery_soc": "sensor.corrected_by_discovery"},
        )

        assert (
            store.get_active_sensors()["battery_soc"] == "sensor.corrected_by_discovery"
        )

    def test_discovery_empty_does_not_overwrite_existing_sensor(
        self, tmp_path, monkeypatch
    ):
        """An empty discovered value leaves the existing sensor value intact."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        sensors = store.get_section("sensors")
        sensors["platform"] = "growatt_server_min"
        sensors["growatt_server_min"] = {"battery_soc": "sensor.user_configured"}
        store.save_section("sensors", sensors)

        store.apply_discovered(
            sensor_map={"battery_soc": ""},
        )

        assert store.get_active_sensors()["battery_soc"] == "sensor.user_configured"

    def test_nordpool_area_is_stored(self, tmp_path, monkeypatch):
        """Nordpool area discovered during setup lands in electricity_price."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})

        store.apply_discovered(sensor_map={}, nordpool_area="SE4")

        assert store.get_section("electricity_price").get("area") == "SE4"

    def test_nordpool_area_overwritten_by_discovery(self, tmp_path, monkeypatch):
        """Discovery always updates the area with the authoritative value from HA."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("electricity_price", {"area": "SE3"})

        store.apply_discovered(sensor_map={}, nordpool_area="SE4")

        assert store.get_section("electricity_price")["area"] == "SE4"

    def test_bootstrap_default_area_overwritten_by_discovery(
        self, tmp_path, monkeypatch
    ):
        """Bootstrap default SE4 is replaced when discovery returns the real area.

        On first boot, _bootstrap_defaults writes SE4 as a placeholder.
        apply_discovered must overwrite it with the actual area so that
        nordpool_official users in other areas get the right configuration.
        """
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})  # bootstraps with SE4

        store.apply_discovered(sensor_map={}, nordpool_area="SE3")

        assert store.get_section("electricity_price")["area"] == "SE3"

    def test_discovery_area_overwrites_user_area(self, tmp_path, monkeypatch):
        """Discovery area is authoritative — it reflects the actual HA installation."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.load({})
        store.save_section("electricity_price", {"area": "NO1"})

        store.apply_discovered(sensor_map={}, nordpool_area="SE3")

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

        assert store.get_active_sensors().get("battery_soc") is None


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

    def test_obsolete_min_action_profit_threshold_is_stripped(
        self, tmp_path, monkeypatch
    ):
        """Existing installs carry the key on disk. Startup already survives it
        (build_system_settings filters to BATTERY_MODEL_ATTRS), but the store
        file is user-visible, so the dead key should not persist there."""
        store = self._store_with_data(
            tmp_path,
            monkeypatch,
            {"battery": {"total_capacity": 15.0, "min_action_profit_threshold": 8.0}},
        )
        battery = store.get_section("battery")
        assert "min_action_profit_threshold" not in battery

        # And the stripped section must still construct real BatterySettings.
        from core.bess.settings import BatterySettings

        BatterySettings().update(**battery)

    def test_home_consumption_renamed_to_default_hourly(self, tmp_path, monkeypatch):
        """Old field 'consumption' must be renamed to 'default_hourly' on load."""
        store = self._store_with_data(
            tmp_path,
            monkeypatch,
            {"home": {"consumption": 4.5, "currency": "SEK"}},
        )
        home = store.get_section("home")
        assert (
            "default_hourly" in home
        ), "Old 'consumption' not renamed to 'default_hourly'"
        assert home["default_hourly"] == 4.5
        assert "consumption" not in home

    def test_home_safety_margin_factor_renamed(self, tmp_path, monkeypatch):
        """Old field 'safety_margin_factor' must be renamed to 'safety_margin' on load."""
        store = self._store_with_data(
            tmp_path,
            monkeypatch,
            {"home": {"safety_margin_factor": 1.2, "currency": "SEK"}},
        )
        home = store.get_section("home")
        assert "safety_margin" in home
        assert home["safety_margin"] == 1.2
        assert "safety_margin_factor" not in home

    def test_battery_max_charge_discharge_power_split(self, tmp_path, monkeypatch):
        """Old single-power field must be split into charge and discharge variants."""
        store = self._store_with_data(
            tmp_path,
            monkeypatch,
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
            tmp_path,
            monkeypatch,
            {"battery": {"cycle_cost": 0.8, "total_capacity": 30.0}},
        )
        battery = store.get_section("battery")
        assert "cycle_cost_per_kwh" in battery
        assert battery["cycle_cost_per_kwh"] == 0.8
        assert "cycle_cost" not in battery

    def test_battery_missing_fields_get_defaults(self, tmp_path, monkeypatch):
        """Fields absent from an old store file are added with safe defaults."""
        store = self._store_with_data(
            tmp_path,
            monkeypatch,
            {"battery": {"total_capacity": 30.0}},
        )
        battery = store.get_section("battery")
        for field in (
            "cycle_cost_per_kwh",
            "charging_power_rate",
            "efficiency_charge",
            "efficiency_discharge",
        ):
            assert (
                field in battery
            ), f"Expected default for '{field}' to be added by migration"

    def test_electricity_price_missing_multiplier_fields_get_defaults(
        self, tmp_path, monkeypatch
    ):
        """Configs written before spot_multiplier existed must get safe defaults.

        Without this, build_system_settings() raises ValueError at startup
        for any pre-existing config (PRICE_STORE_TO_API requires the key).
        """
        store = self._store_with_data(
            tmp_path,
            monkeypatch,
            {"electricity_price": {"area": "SE4", "markup_rate": 0.08}},
        )
        price = store.get_section("electricity_price")
        assert price["spot_multiplier"] == 1.0
        assert price["export_spot_multiplier"] == 1.0
        assert price["use_actual_price"] is False

    def test_electricity_price_existing_multiplier_fields_preserved(
        self, tmp_path, monkeypatch
    ):
        """Migration must not clobber a user's already-configured multiplier."""
        store = self._store_with_data(
            tmp_path,
            monkeypatch,
            {
                "electricity_price": {
                    "area": "EUR",
                    "spot_multiplier": 1.0175,
                    "export_spot_multiplier": 1.018,
                }
            },
        )
        price = store.get_section("electricity_price")
        assert price["spot_multiplier"] == 1.0175
        assert price["export_spot_multiplier"] == 1.018

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
            tmp_path,
            monkeypatch,
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


# ---------------------------------------------------------------------------
# demo_mode section
# ---------------------------------------------------------------------------


def test_bootstrap_defaults_include_demo_mode():
    defaults = SettingsStore._bootstrap_defaults()
    assert "demo_mode" in defaults
    assert defaults["demo_mode"] == {"enabled": False}


def test_migrate_schema_adds_demo_mode_to_old_config(tmp_path, monkeypatch):
    _patch_path(tmp_path, monkeypatch)
    store = SettingsStore()
    store.data = {
        "battery": {"total_capacity": 10.0},
        "home": {"currency": "SEK"},
    }
    store._migrate_schema()
    assert store.data.get("demo_mode") == {"enabled": False}


# ---------------------------------------------------------------------------
# ai_analyst.model migration (legacy Claude 4.0 launch IDs → current)
# ---------------------------------------------------------------------------


def test_migrate_schema_rewrites_legacy_sonnet_4_id(tmp_path, monkeypatch):
    _patch_path(tmp_path, monkeypatch)
    store = SettingsStore()
    store.data = {
        "battery": {"total_capacity": 10.0},
        "ai_analyst": {
            "api_key": "sk-ant-xyz",
            "model": "claude-sonnet-4-20250514",
            "enabled": True,
        },
    }
    store._migrate_schema()
    assert store.data["ai_analyst"]["model"] == "claude-sonnet-4-6"
    # Other fields are untouched
    assert store.data["ai_analyst"]["api_key"] == "sk-ant-xyz"
    assert store.data["ai_analyst"]["enabled"] is True


def test_migrate_schema_rewrites_legacy_opus_4_id(tmp_path, monkeypatch):
    _patch_path(tmp_path, monkeypatch)
    store = SettingsStore()
    store.data = {"ai_analyst": {"model": "claude-opus-4-20250514"}}
    store._migrate_schema()
    assert store.data["ai_analyst"]["model"] == "claude-opus-4-8"


def test_migrate_schema_leaves_current_model_alone(tmp_path, monkeypatch):
    _patch_path(tmp_path, monkeypatch)
    store = SettingsStore()
    store.data = {"ai_analyst": {"model": "claude-sonnet-4-6"}}
    store._migrate_schema()
    assert store.data["ai_analyst"]["model"] == "claude-sonnet-4-6"


def test_migrate_schema_handles_missing_ai_analyst_section(tmp_path, monkeypatch):
    _patch_path(tmp_path, monkeypatch)
    store = SettingsStore()
    store.data = {"battery": {"total_capacity": 10.0}}
    store._migrate_schema()  # must not raise
    assert "ai_analyst" not in store.data


# ---------------------------------------------------------------------------
# Signed-pair aliasing (issue #604)
# ---------------------------------------------------------------------------


class TestSignedPairAliasing:
    """Platforms with one signed entity get the counterpart key derived on read.

    Native SolaX and Huawei publish battery power as a single signed register;
    Solis and Huawei publish grid power the same way. The counterpart key
    (battery_discharge_power / export_power) points at that same entity so
    HAApiController's signed split fires. That pairing is a fixed integration
    fact, so it is derived on every read rather than only when discovery runs —
    a settings file written before the pairing existed would otherwise leave
    the split silently disabled forever (#604).
    """

    def test_huawei_battery_discharge_derived_from_signed_charge_entity(self):
        """The issue #604 config: only battery_charge_power was persisted."""
        flat = _sm.flatten_sensors(
            {
                "platform": "huawei_solar_luna2000",
                "huawei_solar_luna2000": {
                    "battery_charge_power": "sensor.batteries_charge_discharge_power",
                },
            }
        )
        assert (
            flat["battery_discharge_power"] == "sensor.batteries_charge_discharge_power"
        )

    def test_solax_native_battery_discharge_derived_from_signed_charge_entity(self):
        flat = _sm.flatten_sensors(
            {
                "platform": "solax_modbus_native",
                "solax_modbus_native": {
                    "battery_charge_power": "sensor.solax_battery_power_charge",
                },
            }
        )
        assert flat["battery_discharge_power"] == "sensor.solax_battery_power_charge"

    def test_solis_export_derived_from_signed_import_entity(self):
        flat = _sm.flatten_sensors(
            {
                "platform": "solis_modbus",
                "solis_modbus": {"import_power": "sensor.solis_grid_power_net"},
            }
        )
        assert flat["export_power"] == "sensor.solis_grid_power_net"

    def test_huawei_export_derived_from_signed_import_entity(self):
        flat = _sm.flatten_sensors(
            {
                "platform": "huawei_solar_luna2000",
                "huawei_solar_luna2000": {
                    "import_power": "sensor.power_meter_active_power",
                },
            }
        )
        assert flat["export_power"] == "sensor.power_meter_active_power"

    def test_two_entity_platform_gets_no_derived_counterpart(self):
        """Growatt publishes separate charge/discharge entities — nothing to derive."""
        flat = _sm.flatten_sensors(
            {
                "platform": "growatt_server_min",
                "growatt_server_min": {
                    "battery_charge_power": "sensor.growatt_battery_charging_w",
                    "import_power": "sensor.growatt_import",
                },
            }
        )
        assert "battery_discharge_power" not in flat
        assert "export_power" not in flat

    def test_explicitly_mapped_counterpart_is_never_overwritten(self):
        """A user who mapped a real discharge entity keeps it — no split applies."""
        flat = _sm.flatten_sensors(
            {
                "platform": "huawei_solar_luna2000",
                "huawei_solar_luna2000": {
                    "battery_charge_power": "sensor.signed_battery_power",
                    "battery_discharge_power": "sensor.separate_discharge",
                },
            }
        )
        assert flat["battery_discharge_power"] == "sensor.separate_discharge"

    def test_unmapped_primary_derives_nothing(self):
        """No charge entity means there is nothing to alias to."""
        flat = _sm.flatten_sensors(
            {
                "platform": "huawei_solar_luna2000",
                "huawei_solar_luna2000": {"battery_soc": "sensor.soc"},
            }
        )
        assert "battery_discharge_power" not in flat
        assert "export_power" not in flat

    def test_get_active_sensors_exposes_the_derived_pair(self, tmp_path, monkeypatch):
        """The controller reads sensors through get_active_sensors, so the
        derivation has to be visible there, not only in flatten_sensors."""
        _patch_path(tmp_path, monkeypatch)
        store = SettingsStore()
        store.data["sensors"] = {
            "platform": "huawei_solar_luna2000",
            "huawei_solar_luna2000": {
                "battery_charge_power": "sensor.batteries_charge_discharge_power",
            },
        }
        assert (
            store.get_active_sensors()["battery_discharge_power"]
            == "sensor.batteries_charge_discharge_power"
        )


# ---------------------------------------------------------------------------
# Huawei discharge-stop SOC repoint migration
# ---------------------------------------------------------------------------


def test_migrate_schema_clears_stale_huawei_grid_charge_cutoff_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing install mapped battery_discharge_stop_soc to the grid-charge
    cutoff register; the migration clears it so a re-scan repoints it."""
    _patch_path(tmp_path, monkeypatch)
    store = SettingsStore()
    store.data = {
        "inverter": {"platform": "huawei_solar_luna2000", "control_mode": "tou"},
        "sensors": {
            "platform": "huawei_solar_luna2000",
            "shared": {},
            "huawei_solar_luna2000": {
                "battery_soc": "sensor.batteries_state_of_capacity",
                "battery_discharge_stop_soc": "number.batteries_grid_charge_cutoff_soc",
            },
        },
    }
    store._migrate_schema()
    assert (
        "battery_discharge_stop_soc"
        not in store.data["sensors"]["huawei_solar_luna2000"]
    )


def test_migrate_schema_keeps_repointed_huawei_discharge_stop_soc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mapping already on the discharging-cutoff entity is left untouched."""
    _patch_path(tmp_path, monkeypatch)
    store = SettingsStore()
    store.data = {
        "inverter": {"platform": "huawei_solar_luna2000", "control_mode": "tou"},
        "sensors": {
            "platform": "huawei_solar_luna2000",
            "shared": {},
            "huawei_solar_luna2000": {
                "battery_discharge_stop_soc": (
                    "number.batteries_discharging_cutoff_capacity"
                ),
            },
        },
    }
    store._migrate_schema()
    assert (
        store.data["sensors"]["huawei_solar_luna2000"]["battery_discharge_stop_soc"]
        == "number.batteries_discharging_cutoff_capacity"
    )
