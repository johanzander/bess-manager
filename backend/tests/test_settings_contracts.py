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
  1. Update the relevant mapping in ``api_conversion.py``
     (BATTERY_STORE_TO_API / HOME_STORE_TO_API / PRICE_STORE_TO_API).
  2. Update ``_bootstrap_defaults`` in ``settings_store.py`` so it writes
     the new key name.
  3. If the BatterySettings dataclass changed, ``_BATTERY_MODEL_ATTRS`` in
     ``api.py`` updates automatically — the test here will verify that.
  4. Run this file.  All tests should pass before committing.
"""

import dataclasses
import sys
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest
import settings_store as _sm
from api_conversion import (
    BATTERY_STORE_TO_API,
    HOME_STORE_TO_API,
    PRICE_STORE_TO_API,
)
from settings_store import SettingsStore


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
        for key in BATTERY_STORE_TO_API:
            assert key in battery, (
                f"Bootstrap defaults missing required battery key '{key}'. "
                f"Add it to _bootstrap_defaults() in settings_store.py."
            )

    def test_home_keys(self, tmp_path, monkeypatch):
        store = _fresh_store(tmp_path, monkeypatch)
        home = store.data["home"]
        for key in HOME_STORE_TO_API:
            assert key in home, (
                f"Bootstrap defaults missing required home key '{key}'. "
                f"Add it to _bootstrap_defaults() in settings_store.py."
            )

    def test_price_keys(self, tmp_path, monkeypatch):
        store = _fresh_store(tmp_path, monkeypatch)
        price = store.data["electricity_price"]
        for key in PRICE_STORE_TO_API:
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
        assert "cycle_cost" not in battery or "cycle_cost_per_kwh" in battery, (
            "Old field 'cycle_cost' present without new 'cycle_cost_per_kwh'."
        )

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
        assert "default_hourly" in home, "home.default_hourly missing from bootstrap defaults."
        assert "safety_margin" in home, "home.safety_margin missing from bootstrap defaults."


# ---------------------------------------------------------------------------
# 2. _apply_settings: validates and transforms correctly
#
# Tests call _apply_settings as an unbound method with a MagicMock self so
# that the actual BESSController (which needs a live HA connection) is never
# constructed.
# ---------------------------------------------------------------------------


class TestApplySettings:
    """build_system_settings must reject stale field names and produce correct output."""

    def test_valid_options_produce_camelcase_battery(self):
        from api_conversion import build_system_settings

        result = build_system_settings(_valid_options())
        assert result["battery"]["totalCapacity"] == 30.0
        assert result["battery"]["maxChargePowerKw"] == 15.0
        assert result["battery"]["maxDischargePowerKw"] == 15.0
        assert result["battery"]["cycleCostPerKwh"] == 0.5
        assert result["battery"]["minActionProfitThreshold"] == 0.0

    def test_valid_options_produce_camelcase_home(self):
        from api_conversion import build_system_settings

        result = build_system_settings(_valid_options())
        assert result["home"]["defaultHourly"] == 3.5
        assert result["home"]["safetyMargin"] == 1.0
        assert result["home"]["currency"] == "SEK"

    def test_valid_options_produce_camelcase_price(self):
        from api_conversion import build_system_settings

        result = build_system_settings(_valid_options())
        assert result["price"]["area"] == "SE4"
        assert result["price"]["vatMultiplier"] == 1.25

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
# 3. api.py _BATTERY_MODEL_ATTRS must match BatterySettings dataclass
#
# If this fails: a field was added/removed from BatterySettings but the
# derived frozenset in api.py doesn't match — check the dataclass definition.
# ---------------------------------------------------------------------------


class TestBatteryModelAttrsConsistency:
    def test_attrs_match_dataclass_init_fields(self):
        from api import _BATTERY_MODEL_ATTRS  # type: ignore[import]
        from core.bess.settings import BatterySettings

        expected = frozenset(
            f.name for f in dataclasses.fields(BatterySettings) if f.init
        )
        assert _BATTERY_MODEL_ATTRS == expected, (
            f"_BATTERY_MODEL_ATTRS in api.py doesn't match BatterySettings dataclass.\n"
            f"Extra in api.py:     {_BATTERY_MODEL_ATTRS - expected}\n"
            f"Missing from api.py: {expected - _BATTERY_MODEL_ATTRS}"
        )


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
        with patch(
            "core.bess.official_nordpool_source.time_utils"
        ) as mock_time:
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
        assert "config_entry_id" not in kwargs, (
            "Field 'config_entry_id' causes a 400 — HA expects 'config_entry'"
        )

    def test_config_entry_value_passed_through(self):
        ha_controller = self._call_nordpool(date(2026, 4, 13))
        kwargs = ha_controller._service_call_with_retry.call_args.kwargs
        assert kwargs["config_entry"] == "test-config-entry-id"

    def test_date_field_present(self):
        ha_controller = self._call_nordpool(date(2026, 4, 13))
        kwargs = ha_controller._service_call_with_retry.call_args.kwargs
        assert kwargs["date"] == "2026-04-13"
