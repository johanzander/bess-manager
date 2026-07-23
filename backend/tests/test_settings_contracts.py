"""Contract tests — settings field names must be consistent across all layers.

These tests exist to catch the class of bug where a field is renamed in one
place but not updated in another.  Two real examples this suite would have
caught:

  1. Startup crash: migration renamed ``max_charge_discharge_power`` →
     ``max_charge_power_kw`` but ``_apply_settings`` still required the old
     name.  The bootstrap-defaults tests below would have failed immediately.

  2. Nordpool 400: the service call used ``config_entry_id`` but HA's API
     expects ``config_entry``.  The Nordpool contract test below catches this
     by inspecting the actual kwargs sent to the mock controller.

How to use when adding or renaming a settings field
-----------------------------------------------------
None of Battery/Home/Price translate camelCase in core/bess/settings.py —
all three reach update_settings() in snake_case unchanged (issue #197,
extended to Battery/Home in #219).

  1. If the field should be required at startup: add it to
     BATTERY_REQUIRED_FIELDS / HOME_REQUIRED_FIELDS / PRICE_REQUIRED_FIELDS
     in api_conversion.py. If optional (has a class default and the store
     may omit it): no registry change needed for Battery/Home —
     BATTERY_MODEL_ATTRS/HOME_MODEL_ATTRS are derived live from their
     dataclasses, so a new optional field is picked up automatically. Price
     currently has no optional-but-store-backed fields; if one is added,
     give it the same two-set treatment as Battery/Home (see
     BATTERY_MODEL_ATTRS's comment).
  2. Update ``_bootstrap_defaults`` in ``settings_store.py`` so it writes
     the new key name (required fields only — optional fields fall back to
     the dataclass default if absent).
  3. Run this file.  All tests should pass before committing — in
     particular TestModelAttrsConsistency (parametrized over Battery/Home)
     and TestPriceModelAttrsConsistency, which catch a required-fields set
     drifting from the dataclass.
"""

import dataclasses
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from api_conversion import (
    BATTERY_MODEL_ATTRS,
    BATTERY_REQUIRED_FIELDS,
    HOME_MODEL_ATTRS,
    HOME_REQUIRED_FIELDS,
    PRICE_REQUIRED_FIELDS,
)

import core.bess.settings_store as _sm
from core.bess.settings import BatterySettings, HomeSettings
from core.bess.settings_store import SettingsStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_store(tmp_path, monkeypatch) -> SettingsStore:
    """Return a SettingsStore backed by a temp file (bootstrap defaults)."""
    monkeypatch.setattr(_sm, "SETTINGS_PATH", str(tmp_path / "bess_settings.json"))
    store = SettingsStore()
    store.load({})
    return store


def _valid_options() -> dict:
    """Minimal options dict that satisfies all _apply_settings requirements."""
    return {
        "battery": {
            "total_capacity": 30.0,
            "min_soc": 10.0,
            "max_soc": 100.0,
            "cycle_cost_per_kwh": 0.5,
            "max_charge_power_kw": 15.0,
            "max_discharge_power_kw": 15.0,
            "min_action_profit_threshold": 0.0,
            # Present in every real store (added by migration) but not
            # required at startup — see BATTERY_REQUIRED_FIELDS.
            "charging_power_rate": 40,
            "efficiency_charge": 0.97,
            "efficiency_discharge": 0.95,
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
            "spot_multiplier": 1.0175,
            "export_spot_multiplier": 1.018,
            "use_actual_price": False,
        },
    }


# ---------------------------------------------------------------------------
# 1. Bootstrap defaults must contain every field required at startup
#
# If this fails: update _bootstrap_defaults() in settings_store.py to include
# the field named in the assertion message.
# ---------------------------------------------------------------------------


class TestBootstrapFieldConsistency:
    """Bootstrap defaults must include all fields that startup validation requires."""

    def test_battery_keys(self, tmp_path, monkeypatch):
        store = _fresh_store(tmp_path, monkeypatch)
        battery = store.data["battery"]
        for key in BATTERY_REQUIRED_FIELDS:
            assert key in battery, (
                f"Bootstrap defaults missing required battery key '{key}'. "
                f"Add it to _bootstrap_defaults() in settings_store.py."
            )

    def test_home_keys(self, tmp_path, monkeypatch):
        store = _fresh_store(tmp_path, monkeypatch)
        home = store.data["home"]
        for key in HOME_REQUIRED_FIELDS:
            assert key in home, (
                f"Bootstrap defaults missing required home key '{key}'. "
                f"Add it to _bootstrap_defaults() in settings_store.py."
            )

    def test_price_keys(self, tmp_path, monkeypatch):
        store = _fresh_store(tmp_path, monkeypatch)
        price = store.data["electricity_price"]
        for key in PRICE_REQUIRED_FIELDS:
            assert key in price, (
                f"Bootstrap defaults missing required electricity_price key '{key}'. "
                f"Add it to _bootstrap_defaults() in settings_store.py."
            )

    def test_no_old_field_names_in_battery(self, tmp_path, monkeypatch):
        """Pre-migration field names must not appear after bootstrap/migration."""
        store = _fresh_store(tmp_path, monkeypatch)
        battery = store.data["battery"]
        assert "max_charge_discharge_power" not in battery, (
            "Old field 'max_charge_discharge_power' still in battery settings. "
            "Startup would fail because _apply_settings requires max_charge_power_kw."
        )
        assert (
            "cycle_cost" not in battery or "cycle_cost_per_kwh" in battery
        ), "Old field 'cycle_cost' present without new 'cycle_cost_per_kwh'."

    def test_no_old_field_names_in_home(self, tmp_path, monkeypatch):
        """Home store keys must use dataclass attribute names after bootstrap/migration."""
        store = _fresh_store(tmp_path, monkeypatch)
        home = store.data["home"]
        assert "consumption" not in home, (
            "Old field 'consumption' still in home settings. "
            "Rename to 'default_hourly' to match HomeSettings attribute."
        )
        assert "safety_margin_factor" not in home, (
            "Old field 'safety_margin_factor' still in home settings. "
            "Rename to 'safety_margin' to match HomeSettings attribute."
        )
        assert (
            "default_hourly" in home
        ), "home.default_hourly missing from bootstrap defaults."
        assert (
            "safety_margin" in home
        ), "home.safety_margin missing from bootstrap defaults."


# ---------------------------------------------------------------------------
# 2. _apply_settings: validates and transforms correctly
#
# Tests call _apply_settings as an unbound method with a MagicMock self so
# that the actual BESSController (which needs a live HA connection) is never
# constructed.
# ---------------------------------------------------------------------------


class TestApplySettings:
    """build_system_settings must reject stale field names and produce correct output."""

    def test_valid_options_produce_battery_unchanged_snake_case(self):
        """Battery settings reach BSM in snake_case unchanged — no camelCase
        translation (issue #197, #219)."""
        from api_conversion import build_system_settings

        result = build_system_settings(_valid_options())
        assert result["battery"]["total_capacity"] == 30.0
        assert result["battery"]["max_charge_power_kw"] == 15.0
        assert result["battery"]["max_discharge_power_kw"] == 15.0
        assert result["battery"]["cycle_cost_per_kwh"] == 0.5
        assert result["battery"]["min_action_profit_threshold"] == 0.0
        assert "totalCapacity" not in result["battery"]

    def test_valid_options_battery_passes_through_optional_fields_when_present(self):
        """charging_power_rate/efficiency_charge/efficiency_discharge are
        optional (not in BATTERY_REQUIRED_FIELDS) but must still be applied
        at startup when the store has them — this is the #197 bug: they were
        previously dropped unconditionally, reverting to class defaults on
        every restart even though PATCH applied them correctly in-session."""
        from api_conversion import build_system_settings

        options = _valid_options()
        options["battery"]["charging_power_rate"] = 55.0
        options["battery"]["efficiency_charge"] = 0.91
        options["battery"]["efficiency_discharge"] = 0.88

        result = build_system_settings(options)

        assert result["battery"]["charging_power_rate"] == 55.0
        assert result["battery"]["efficiency_charge"] == 0.91
        assert result["battery"]["efficiency_discharge"] == 0.88

    def test_valid_options_battery_drops_non_model_keys(self):
        """temperature_derating lives in the store's battery section but is
        not a BatterySettings field (applied separately at BSM construction)
        — it must be filtered out, not passed to BatterySettings.update()."""
        from api_conversion import build_system_settings

        options = _valid_options()
        options["battery"]["temperature_derating"] = {
            "enabled": True,
            "weather_entity": "weather.home",
        }

        result = build_system_settings(options)

        assert "temperature_derating" not in result["battery"]

    def test_valid_options_produce_home_unchanged_snake_case(self):
        """Home settings reach BSM in snake_case unchanged — no camelCase
        translation (issue #197, #219)."""
        from api_conversion import build_system_settings

        result = build_system_settings(_valid_options())
        assert result["home"]["default_hourly"] == 3.5
        assert result["home"]["safety_margin"] == 1.0
        assert result["home"]["currency"] == "SEK"
        assert "defaultHourly" not in result["home"]

    def test_valid_options_home_drops_non_model_keys(self):
        """A stray key in the home store section (e.g. a stale pre-migration
        field left behind if both the old and new key ever coexist — see
        settings_store.py's rename-if-absent migration guards) must not
        reach HomeSettings.update(), or startup raises AttributeError."""
        from api_conversion import build_system_settings

        options = _valid_options()
        options["home"]["consumption"] = 3.5  # stale pre-migration key
        result = build_system_settings(options)
        assert "consumption" not in result["home"]

    def test_valid_options_produce_price_unchanged_snake_case(self):
        """Price settings reach BSM in snake_case unchanged — no camelCase
        translation, unlike battery/home (issue #197)."""
        from api_conversion import build_system_settings

        result = build_system_settings(_valid_options())
        assert result["price"]["area"] == "SE4"
        assert result["price"]["vat_multiplier"] == 1.25
        assert result["price"]["markup_rate"] == 0.08
        assert "vatMultiplier" not in result["price"]

    def test_old_battery_field_raises(self):
        from api_conversion import build_system_settings

        options = _valid_options()
        options["battery"]["max_charge_discharge_power"] = 15.0
        del options["battery"]["max_charge_power_kw"]
        with pytest.raises(ValueError, match="max_charge_power_kw"):
            build_system_settings(options)

    def test_old_cycle_cost_field_raises(self):
        from api_conversion import build_system_settings

        options = _valid_options()
        options["battery"]["cycle_cost"] = 0.5
        del options["battery"]["cycle_cost_per_kwh"]
        with pytest.raises(ValueError, match="cycle_cost_per_kwh"):
            build_system_settings(options)

    def test_old_home_consumption_field_raises(self):
        """Old store key 'consumption' must raise — new key is 'default_hourly'."""
        from api_conversion import build_system_settings

        options = _valid_options()
        options["home"]["consumption"] = 3.5
        del options["home"]["default_hourly"]
        with pytest.raises(ValueError, match="default_hourly"):
            build_system_settings(options)

    def test_old_home_safety_margin_field_raises(self):
        """Old store key 'safety_margin_factor' must raise — new key is 'safety_margin'."""
        from api_conversion import build_system_settings

        options = _valid_options()
        options["home"]["safety_margin_factor"] = 1.0
        del options["home"]["safety_margin"]
        with pytest.raises(ValueError, match="safety_margin"):
            build_system_settings(options)

    def test_missing_section_raises(self):
        from api_conversion import build_system_settings

        options = _valid_options()
        del options["battery"]
        with pytest.raises(ValueError, match="battery"):
            build_system_settings(options)


# ---------------------------------------------------------------------------
# 3. api_conversion.BATTERY_MODEL_ATTRS/HOME_MODEL_ATTRS must match their
# dataclasses, and BATTERY_REQUIRED_FIELDS/HOME_REQUIRED_FIELDS must be
# exactly MODEL_ATTRS minus the fields excluded per domain below.
#
# If test_model_attrs_match_dataclass_init_fields fails: a field was
# added/removed from the dataclass — since MODEL_ATTRS is derived live from
# it, this test failing means api.py's PATCH filtering (which imports the
# same frozenset) is already correct; it's here as a regression guard in
# case the derivation is ever hand-rolled again.
#
# If test_required_fields_match_model_attrs_minus_exclusion fails:
# REQUIRED_FIELDS names a field the dataclass doesn't have, or the exclusion
# set below has drifted — fix the typo/stale name.
#
# Price isn't included here: it has no MODEL_ATTRS constant (its PATCH path
# doesn't filter store keys the way Battery/Home's does), so it only gets
# the required-fields test — see TestPriceModelAttrsConsistency below.
# ---------------------------------------------------------------------------

# Fields present in the dataclass (and BATTERY_MODEL_ATTRS) but not required
# at startup because they have class defaults.
_BATTERY_OPTIONAL_FIELDS = frozenset(
    {
        "charging_power_rate",
        "efficiency_charge",
        "efficiency_discharge",
        "inverter_max_ac_power_kw",
        "inverter_ac_power_margin",
    }
)
# min_valid is an internal algorithm parameter, never read from the settings
# store or written by the wizard — the one field HOME_MODEL_ATTRS has that
# HOME_REQUIRED_FIELDS doesn't.
_HOME_OPTIONAL_FIELDS = frozenset({"min_valid"})


@pytest.mark.parametrize(
    "settings_cls, model_attrs, required_fields, optional_fields",
    [
        pytest.param(
            BatterySettings,
            BATTERY_MODEL_ATTRS,
            BATTERY_REQUIRED_FIELDS,
            _BATTERY_OPTIONAL_FIELDS,
            id="battery",
        ),
        pytest.param(
            HomeSettings,
            HOME_MODEL_ATTRS,
            HOME_REQUIRED_FIELDS,
            _HOME_OPTIONAL_FIELDS,
            id="home",
        ),
    ],
)
class TestModelAttrsConsistency:
    def test_model_attrs_match_dataclass_init_fields(
        self, settings_cls, model_attrs, required_fields, optional_fields
    ):
        expected = frozenset(f.name for f in dataclasses.fields(settings_cls) if f.init)
        assert model_attrs == expected, (
            f"MODEL_ATTRS in api_conversion.py doesn't match {settings_cls.__name__}.\n"
            f"Extra:   {model_attrs - expected}\n"
            f"Missing: {expected - model_attrs}"
        )

    def test_required_fields_match_model_attrs_minus_optional(
        self, settings_cls, model_attrs, required_fields, optional_fields
    ):
        """REQUIRED_FIELDS must be exactly MODEL_ATTRS minus the fields that
        are optional for this domain — a plain subset check would miss a
        field that drifted out of both sets."""
        expected = model_attrs - optional_fields
        assert required_fields == expected, (
            f"REQUIRED_FIELDS in api_conversion.py doesn't match {settings_cls.__name__}.\n"
            f"Extra:   {required_fields - expected}\n"
            f"Missing: {expected - required_fields}"
        )


# ---------------------------------------------------------------------------
# 3b. api_conversion.PRICE_REQUIRED_FIELDS must match PriceSettings' store-
# backed fields.
#
# min_profit and use_actual_price are excluded: they are internal algorithm
# parameters (see core/bess/settings.py module docstring), never read from
# the settings store or written by the wizard. If this fails after adding a
# field to PriceSettings, add it to PRICE_REQUIRED_FIELDS in
# api_conversion.py (store-backed) or to the exclusion set below
# (internal-only).
# ---------------------------------------------------------------------------


class TestPriceModelAttrsConsistency:
    def test_required_fields_match_store_backed_dataclass_fields(self):
        from core.bess.settings import PriceSettings

        internal_only = {"min_profit", "use_actual_price"}
        expected = frozenset(
            f.name
            for f in dataclasses.fields(PriceSettings)
            if f.init and f.name not in internal_only
        )
        assert PRICE_REQUIRED_FIELDS == expected, (
            f"PRICE_REQUIRED_FIELDS in api_conversion.py doesn't match PriceSettings.\n"
            f"Extra:   {PRICE_REQUIRED_FIELDS - expected}\n"
            f"Missing: {expected - PRICE_REQUIRED_FIELDS}"
        )


# ---------------------------------------------------------------------------
# 3c. Startup and PATCH paths must reach BSM identically (issue #197).
#
# Startup goes through build_system_settings(); PATCH /api/settings passes
# the (possibly filtered) store dict straight to update_settings(). Both
# must land on the same *Settings values on a real BatterySystemManager.
# ---------------------------------------------------------------------------


def _bsm():
    from core.bess.battery_system_manager import BatterySystemManager
    from core.bess.ha_api_controller import HomeAssistantAPIController
    from core.bess.price_manager import MockSource

    return BatterySystemManager(
        controller=MagicMock(spec=HomeAssistantAPIController),
        price_source=MockSource([1.0] * 96),
    )


def _full_options(store) -> dict:
    return {
        "battery": store.data["battery"],
        "home": store.data["home"],
        "electricity_price": store.data["electricity_price"],
    }


def _apply_startup(store):
    """Build settings via the startup path (build_system_settings) and
    apply them to a fresh BatterySystemManager."""
    from api_conversion import build_system_settings

    system = _bsm()
    system.update_settings(build_system_settings(_full_options(store)))
    return system


def _apply_patch(section: str, payload: dict):
    """Apply a PATCH /api/settings payload directly to a fresh
    BatterySystemManager, mirroring api.py's update_settings() call."""
    system = _bsm()
    system.update_settings({section: payload})
    return system


class TestBatterySettingsRoundTrip:
    def test_startup_path_applies_optional_battery_fields_to_bsm(
        self, tmp_path, monkeypatch
    ):
        """Regression test for the #197 bug: charging_power_rate,
        efficiency_charge and efficiency_discharge are optional (not in
        BATTERY_REQUIRED_FIELDS) but were previously dropped unconditionally
        by build_system_settings() regardless of what the store held —
        applied live via PATCH, then silently reverted to class defaults on
        every restart. They must now survive the startup path."""
        store = _fresh_store(tmp_path, monkeypatch)
        battery = dict(store.data["battery"])
        battery["charging_power_rate"] = 55.0
        battery["efficiency_charge"] = 0.91
        battery["efficiency_discharge"] = 0.88
        store.data["battery"] = battery

        system = _apply_startup(store)

        assert system.battery_settings.charging_power_rate == 55.0
        assert system.battery_settings.efficiency_charge == 0.91
        assert system.battery_settings.efficiency_discharge == 0.88

    def test_startup_path_drops_temperature_derating_without_crashing(
        self, tmp_path, monkeypatch
    ):
        """temperature_derating lives in the store's battery section but is
        applied separately at BSM construction, not via update_settings() —
        the startup path must filter it out rather than crash with
        AttributeError on BatterySettings.update()."""
        store = _fresh_store(tmp_path, monkeypatch)
        battery = dict(store.data["battery"])
        battery["temperature_derating"] = {"enabled": True, "weather_entity": ""}
        store.data["battery"] = battery

        _apply_startup(store)  # no raise

    def test_startup_and_patch_paths_produce_identical_bsm_state(
        self, tmp_path, monkeypatch
    ):
        from api_conversion import BATTERY_MODEL_ATTRS

        store = _fresh_store(tmp_path, monkeypatch)
        battery = dict(store.data["battery"])
        battery["total_capacity"] = 42.0
        battery["efficiency_charge"] = 0.91
        store.data["battery"] = battery

        startup_system = _apply_startup(store)

        # PATCH /api/settings filters to BATTERY_MODEL_ATTRS, then passes
        # the raw store dict directly (api.py) — the one place Battery's
        # round trip differs from Home/Price's unfiltered passthrough below.
        in_mem = {k: v for k, v in battery.items() if k in BATTERY_MODEL_ATTRS}
        patch_system = _apply_patch("battery", in_mem)

        assert startup_system.battery_settings == patch_system.battery_settings


class TestHomeSettingsRoundTrip:
    def test_startup_path_applies_home_settings_to_bsm(self, tmp_path, monkeypatch):
        store = _fresh_store(tmp_path, monkeypatch)
        home = dict(store.data["home"])
        home["default_hourly"] = 5.5
        home["phase_count"] = 1
        store.data["home"] = home

        system = _apply_startup(store)

        assert system.home_settings.default_hourly == 5.5
        assert system.home_settings.phase_count == 1

    def test_startup_path_drops_stale_key_without_crashing(self, tmp_path, monkeypatch):
        """A stale pre-migration key (e.g. 'consumption' coexisting with its
        renamed successor 'default_hourly' — see settings_store.py's
        rename-if-absent migration guard) lives in the store's home section
        but is not a HomeSettings field — the startup path must filter it
        out rather than crash with AttributeError on HomeSettings.update()."""
        store = _fresh_store(tmp_path, monkeypatch)
        home = dict(store.data["home"])
        home["consumption"] = 3.5
        store.data["home"] = home

        _apply_startup(store)  # no raise

    def test_startup_and_patch_paths_produce_identical_bsm_state(
        self, tmp_path, monkeypatch
    ):
        store = _fresh_store(tmp_path, monkeypatch)
        home = dict(store.data["home"])
        home["default_hourly"] = 6.25
        store.data["home"] = home

        startup_system = _apply_startup(store)

        # PATCH /api/settings passes the raw store dict directly (api.py).
        patch_system = _apply_patch("home", home)

        assert startup_system.home_settings == patch_system.home_settings


class TestPriceSettingsRoundTrip:
    def test_startup_path_applies_price_settings_to_bsm(self, tmp_path, monkeypatch):
        store = _fresh_store(tmp_path, monkeypatch)
        price = dict(store.data["electricity_price"])
        price["markup_rate"] = 0.42
        price["area"] = "SE3"
        store.data["electricity_price"] = price

        system = _apply_startup(store)

        assert system.price_settings.markup_rate == 0.42
        assert system.price_settings.area == "SE3"

    def test_startup_and_patch_paths_produce_identical_bsm_state(
        self, tmp_path, monkeypatch
    ):
        store = _fresh_store(tmp_path, monkeypatch)
        price = dict(store.data["electricity_price"])
        price["markup_rate"] = 0.33
        price["tax_reduction"] = 0.15
        store.data["electricity_price"] = price

        startup_system = _apply_startup(store)

        # PATCH /api/settings passes the raw store dict directly (api.py).
        patch_system = _apply_patch("price", price)

        assert startup_system.price_settings == patch_system.price_settings


# ---------------------------------------------------------------------------
# 4. HA service call contracts
#
# These tests mock the HA controller and verify that the parameters we send
# match what HA's API actually expects.  The expected field names were verified
# against a live HA instance:
#
#   GET /api/services → nordpool.get_prices_for_date.fields → "config_entry"
#
# If a test here fails after a HA update, first verify the new field name with
# curl before changing the test — the test may be right and the code wrong.
# ---------------------------------------------------------------------------


class TestNordpoolServiceContract:
    """Official Nordpool service call must use the field name HA expects."""

    def _call_nordpool(self, target_date: date) -> MagicMock:
        """Call get_prices_for_date with a mocked HA controller."""
        from core.bess.official_nordpool_source import OfficialNordpoolSource

        ha_controller = MagicMock()
        ha_controller._service_call_with_retry.return_value = {
            "service_response": {
                "SE4": [
                    {
                        "start": f"{target_date}T22:00:00+00:00",
                        "end": f"{target_date}T23:00:00+00:00",
                        "price": 612.0,
                    }
                ]
                * 96
            }
        }

        source = OfficialNordpoolSource(ha_controller, "test-config-entry-id", 1.25)

        # Patch time_utils so the date-range guard accepts our target_date.
        with patch("core.bess.official_nordpool_source.time_utils") as mock_time:
            mock_time.today.return_value = target_date
            source.get_prices_for_date(target_date)

        return ha_controller

    def test_uses_config_entry_field(self):
        """Service call must send 'config_entry', not 'config_entry_id'.

        Verified against live HA: GET /api/services shows the field is
        'config_entry'.  Changing this to 'config_entry_id' causes a 400.
        """
        ha_controller = self._call_nordpool(date(2026, 4, 13))
        kwargs = ha_controller._service_call_with_retry.call_args.kwargs
        assert "config_entry" in kwargs, (
            "Service call must use field 'config_entry' — "
            "verify against HA's /api/services endpoint before changing"
        )
        assert (
            "config_entry_id" not in kwargs
        ), "Field 'config_entry_id' causes a 400 — HA expects 'config_entry'"

    def test_config_entry_value_passed_through(self):
        ha_controller = self._call_nordpool(date(2026, 4, 13))
        kwargs = ha_controller._service_call_with_retry.call_args.kwargs
        assert kwargs["config_entry"] == "test-config-entry-id"

    def test_date_field_present(self):
        ha_controller = self._call_nordpool(date(2026, 4, 13))
        kwargs = ha_controller._service_call_with_retry.call_args.kwargs
        assert kwargs["date"] == "2026-04-13"
