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
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import core.bess.battery_system_manager as _bsm_module
import core.bess.ha_api_controller as _ha_api_module
import core.bess.settings_store as _settings_store_module
from core.bess.exceptions import SystemConfigurationError


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

    # Real app.py's BESSController.__init__ calls time_utils.set_timezone()
    # from the mocked HA config, permanently mutating the shared module-global
    # TIMEZONE. Restore it on teardown so this file doesn't leak UTC into the
    # rest of the test session (e.g. the historical-data dashboard tests).
    import core.bess.time_utils as time_utils

    monkeypatch.setattr(time_utils, "TIMEZONE", time_utils.TIMEZONE, raising=False)

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


class TestTimezoneFetchOrdering:
    """Issue #440: a failed timezone fetch must surface on the existing
    RuntimeFailureTracker/dashboard-banner mechanism instead of vanishing
    into a log line.

    ha_controller.failure_tracker is only wired to a real RuntimeFailureTracker
    inside BatterySystemManager.__init__ (battery_system_manager.py:202-214).
    If the timezone fetch runs before BatterySystemManager is constructed,
    ha_controller.failure_tracker is still None, so a final-attempt HA API
    failure never reaches record_failure_once and is silently lost.
    """

    def test_timezone_fetch_runs_after_battery_system_manager_construction(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            _settings_store_module, "SETTINGS_PATH", _settings_path(tmp_path)
        )
        _write_settings(_settings_path(tmp_path))

        call_order = []

        mock_ha_controller_cls = MagicMock()
        mock_ha_controller_cls.return_value.get_ha_config.side_effect = (
            lambda: call_order.append("get_ha_config") or {"time_zone": "UTC"}
        )
        mock_bsm_cls = MagicMock()
        mock_bsm_cls.return_value.is_configured = False

        def _record_bsm_construction(*args, **kwargs):
            call_order.append("battery_system_manager")
            return mock_bsm_cls.return_value

        mock_bsm_cls.side_effect = _record_bsm_construction

        with (
            patch.object(
                _ha_api_module, "HomeAssistantAPIController", mock_ha_controller_cls
            ),
            patch.object(_bsm_module, "BatterySystemManager", mock_bsm_cls),
        ):
            _load_real_app_module(monkeypatch)

        assert call_order == ["battery_system_manager", "get_ha_config"], (
            "the timezone fetch must run after BatterySystemManager is "
            "constructed, so ha_controller.failure_tracker is already wired "
            "and a fetch failure gets recorded instead of silently lost"
        )


class TestForceModeRestoreAtStartup:
    """A persisted force-mode override is re-applied before the first optimization."""

    def _boot(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        persisted: dict[str, str | None],
        system: MagicMock,
    ) -> tuple[Any, MagicMock]:
        monkeypatch.setattr(
            _settings_store_module, "SETTINGS_PATH", _settings_path(tmp_path)
        )
        _write_settings(_settings_path(tmp_path))
        path = _settings_path(tmp_path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["force_mode"] = persisted
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        mock_ha_controller_cls = MagicMock()
        mock_ha_controller_cls.return_value.get_ha_config.return_value = {
            "time_zone": "UTC"
        }
        mock_bsm_cls = MagicMock(return_value=system)
        with (
            patch.object(
                _ha_api_module, "HomeAssistantAPIController", mock_ha_controller_cls
            ),
            patch.object(_bsm_module, "BatterySystemManager", mock_bsm_cls),
            patch("api_conversion.build_system_settings", return_value={}),
        ):
            module = _load_real_app_module(monkeypatch)
        return module.bess_controller, mock_ha_controller_cls.return_value

    def _system(self, supported: frozenset[str]) -> MagicMock:
        system = MagicMock()
        system.is_configured = True
        state: dict = {"mode": None}

        def _set(mode: str | None) -> None:
            if mode is not None and mode not in supported:
                raise SystemConfigurationError(f"unsupported {mode}")
            state["mode"] = mode

        system.set_force_mode.side_effect = _set
        type(system).force_mode = property(lambda _self: state["mode"])
        return system

    def test_persisted_mode_is_applied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        system = self._system(frozenset({"IDLE"}))
        self._boot(tmp_path, monkeypatch, {"mode": "IDLE", "activated_at": "t"}, system)
        assert system.force_mode == "IDLE"

    def test_nothing_persisted_leaves_system_unforced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        system = self._system(frozenset({"IDLE"}))
        self._boot(tmp_path, monkeypatch, {"mode": None, "activated_at": None}, system)
        assert system.force_mode is None

    def test_unsupported_persisted_mode_is_cleared_reported_and_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        system = self._system(frozenset({"IDLE"}))
        controller, ha = self._boot(
            tmp_path,
            monkeypatch,
            {"mode": "BATTERY_EXPORT", "activated_at": "t"},
            system,
        )

        assert system.force_mode is None
        assert controller.settings_store.get_section("force_mode") == {
            "mode": None,
            "activated_at": None,
        }
        ha.failure_tracker.record_failure.assert_called_once()

    def test_mode_dropped_by_a_platform_switch_is_not_restored_later(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        system = self._system(frozenset({"BATTERY_EXPORT"}))
        controller, _ = self._boot(
            tmp_path,
            monkeypatch,
            {"mode": "BATTERY_EXPORT", "activated_at": "t"},
            system,
        )
        # The platform switch dropped it in the live system.
        system.set_force_mode(None)

        controller.forget_dropped_force_mode()

        assert controller.settings_store.get_section("force_mode") == {
            "mode": None,
            "activated_at": None,
        }

    def test_mode_the_new_platform_still_runs_stays_persisted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        system = self._system(frozenset({"IDLE"}))
        controller, _ = self._boot(
            tmp_path, monkeypatch, {"mode": "IDLE", "activated_at": "t"}, system
        )

        controller.forget_dropped_force_mode()

        assert controller.settings_store.get_section("force_mode") == {
            "mode": "IDLE",
            "activated_at": "t",
        }
