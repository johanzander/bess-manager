"""Tests for BESSController startup re-hydration of device IDs.

backend/app.py stubs out the real ``app`` module at collection time (see
conftest.py) so importing ``api`` doesn't trigger a full BESSController
init against a live Home Assistant. These tests load backend/app.py fresh,
under a distinct module name, to exercise the real BESSController.__init__
startup path (including its module-level ``bess_controller = BESSController()``
instantiation) with HomeAssistantAPIController/BatterySystemManager mocked
out at the source so no network calls happen.
"""

import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import core.bess.battery_system_manager as _bsm_module
import core.bess.ha_api_controller as _ha_api_module
import core.bess.settings_store as _settings_store_module


def _settings_path(tmp_path) -> str:
    return str(tmp_path / "bess_settings.json")


def _write_settings(path, growatt_device_id="", huawei_device_id=""):
    from core.bess.settings_store import SettingsStore

    defaults = SettingsStore._bootstrap_defaults()
    defaults["growatt"]["device_id"] = growatt_device_id
    defaults["inverter"]["device_id"] = huawei_device_id
    with open(path, "w", encoding="utf-8") as f:
        json.dump(defaults, f)


def _load_real_app_module(monkeypatch):
    """Import backend/app.py fresh under a throwaway module name.

    The real module name ``app`` is permanently stubbed by
    backend/tests/conftest.py for the whole test session, so we load the
    file under a different name to get the real BESSController class with
    its actual __init__ logic. HomeAssistantAPIController and
    BatterySystemManager must already be patched (at their source modules)
    before this runs, since app.py's module-level
    ``bess_controller = BESSController()`` executes immediately on import.
    """
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    monkeypatch.setenv("HA_TEST_MODE", "true")
    monkeypatch.setenv("HA_TOKEN", "test-token")
    monkeypatch.setenv("HA_URL", "http://ha.local")
    monkeypatch.delenv("HASSIO_TOKEN", raising=False)

    app_path = os.path.join(backend_dir, "app.py")
    spec = importlib.util.spec_from_file_location("real_backend_app", app_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["real_backend_app"] = module
    spec.loader.exec_module(module)
    return module


class TestDeviceIdRehydration:
    """Persisted device IDs must be re-loaded into ha_controller at boot."""

    def test_huawei_device_id_loaded_from_settings_at_startup(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            _settings_store_module, "SETTINGS_PATH", _settings_path(tmp_path)
        )
        _write_settings(
            _settings_path(tmp_path),
            growatt_device_id="",
            huawei_device_id="huawei-dev-789",
        )

        mock_ha_controller_cls = MagicMock()
        mock_ha_controller_cls.return_value.get_ha_config.return_value = {
            "time_zone": "UTC"
        }
        mock_bsm_cls = MagicMock()
        mock_bsm_cls.return_value.is_configured = False

        with (
            patch.object(
                _ha_api_module, "HomeAssistantAPIController", mock_ha_controller_cls
            ),
            patch.object(_bsm_module, "BatterySystemManager", mock_bsm_cls),
        ):
            _load_real_app_module(monkeypatch)

        assert mock_ha_controller_cls.call_args.kwargs["huawei_device_id"] == (
            "huawei-dev-789"
        )

    def test_growatt_device_id_still_loaded_from_settings_at_startup(
        self, tmp_path, monkeypatch
    ):
        """Regression guard: the Huawei wiring must not disturb Growatt's."""
        monkeypatch.setattr(
            _settings_store_module, "SETTINGS_PATH", _settings_path(tmp_path)
        )
        _write_settings(
            _settings_path(tmp_path),
            growatt_device_id="growatt-dev-123",
            huawei_device_id="",
        )

        mock_ha_controller_cls = MagicMock()
        mock_ha_controller_cls.return_value.get_ha_config.return_value = {
            "time_zone": "UTC"
        }
        mock_bsm_cls = MagicMock()
        mock_bsm_cls.return_value.is_configured = False

        with (
            patch.object(
                _ha_api_module, "HomeAssistantAPIController", mock_ha_controller_cls
            ),
            patch.object(_bsm_module, "BatterySystemManager", mock_bsm_cls),
        ):
            _load_real_app_module(monkeypatch)

        assert mock_ha_controller_cls.call_args.kwargs["growatt_device_id"] == (
            "growatt-dev-123"
        )
        # Stored-but-empty device_id passes through as "" (falsy), same as
        # growatt_device_id already behaves when the setting exists but is unset.
        assert mock_ha_controller_cls.call_args.kwargs["huawei_device_id"] == ""
