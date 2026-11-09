"""Tests for GET/PUT/DELETE /api/force-mode and the startup restore.

The system object is mocked: these verify what the API persists and tells the
system to do, not how the core applies a forced mode.
"""

import sys
from collections.abc import Iterator
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bess.exceptions import SystemConfigurationError

_test_app = FastAPI()
_test_app.include_router(router)
_client = TestClient(_test_app, raise_server_exceptions=False)

_SUPPORTED = frozenset({"IDLE", "LOAD_SUPPORT", "SOLAR_STORAGE"})
_CLEARED = {"mode": None, "activated_at": None}


class _FakeSystem:
    """Mimics the force-mode surface of BatterySystemManager."""

    def __init__(self) -> None:
        self.is_configured = True
        self.supported_force_modes = _SUPPORTED
        self.force_mode: str | None = None
        self.set_force_mode = MagicMock(side_effect=self._set)

    def _set(self, mode: str | None) -> None:
        if mode is not None and mode not in self.supported_force_modes:
            raise SystemConfigurationError(f"unsupported {mode}")
        self.force_mode = mode


@pytest.fixture()
def controller() -> Iterator[MagicMock]:
    ctrl = MagicMock()
    ctrl.startup_complete = True
    ctrl.system = _FakeSystem()
    store = {"force_mode": deepcopy(_CLEARED)}
    ctrl.settings_store.get_section.side_effect = lambda name: dict(store[name])
    ctrl.settings_store.save_section.side_effect = lambda name, data: store.update(
        {name: dict(data)}
    )
    ctrl.store = store
    sys.modules["app"].bess_controller = ctrl  # type: ignore[attr-defined]
    with patch("api._replan_in_background") as replan:
        ctrl.replan = replan
        yield ctrl


class TestGetForceMode:
    def test_inactive_by_default(self, controller: MagicMock) -> None:
        resp = _client.get("/api/force-mode")
        assert resp.status_code == 200
        assert resp.json() == {
            "active": False,
            "mode": None,
            "activatedAt": None,
            "supportedModes": ["IDLE", "LOAD_SUPPORT", "SOLAR_STORAGE"],
        }

    def test_reports_active_mode_and_activation_time(
        self, controller: MagicMock
    ) -> None:
        controller.system.force_mode = "IDLE"
        controller.store["force_mode"] = {
            "mode": "IDLE",
            "activated_at": "2026-09-16T10:00:00+02:00",
        }
        body = _client.get("/api/force-mode").json()
        assert body["active"] is True
        assert body["mode"] == "IDLE"
        assert body["activatedAt"] == "2026-09-16T10:00:00+02:00"

    def test_unconfigured_returns_503(self, controller: MagicMock) -> None:
        controller.system.is_configured = False
        assert _client.get("/api/force-mode").status_code == 503

    def test_starting_up_returns_503(self, controller: MagicMock) -> None:
        controller.startup_complete = False
        assert _client.get("/api/force-mode").status_code == 503


class TestPutForceMode:
    def test_activates_persists_and_replans(self, controller: MagicMock) -> None:
        resp = _client.put("/api/force-mode", json={"mode": "LOAD_SUPPORT"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["active"] is True
        assert body["mode"] == "LOAD_SUPPORT"
        assert body["activatedAt"] is not None
        assert controller.system.force_mode == "LOAD_SUPPORT"
        assert controller.store["force_mode"]["mode"] == "LOAD_SUPPORT"
        assert controller.store["force_mode"]["activated_at"] == body["activatedAt"]
        controller.replan.assert_called_once_with(controller)

    def test_unsupported_mode_returns_400_and_changes_nothing(
        self, controller: MagicMock
    ) -> None:
        resp = _client.put("/api/force-mode", json={"mode": "BATTERY_EXPORT"})

        assert resp.status_code == 400
        assert controller.system.force_mode is None
        assert controller.store["force_mode"] == _CLEARED
        controller.replan.assert_not_called()

    def test_malformed_body_returns_422(self, controller: MagicMock) -> None:
        assert _client.put("/api/force-mode", json={}).status_code == 422
        assert _client.put("/api/force-mode", json={"mode": 3}).status_code == 422

    def test_unconfigured_returns_503(self, controller: MagicMock) -> None:
        controller.system.is_configured = False
        resp = _client.put("/api/force-mode", json={"mode": "IDLE"})
        assert resp.status_code == 503


class TestDeleteForceMode:
    def test_clears_persists_and_replans(self, controller: MagicMock) -> None:
        controller.system.force_mode = "IDLE"
        controller.store["force_mode"] = {
            "mode": "IDLE",
            "activated_at": "2026-09-16T10:00:00+02:00",
        }

        resp = _client.delete("/api/force-mode")

        assert resp.status_code == 200
        assert resp.json()["active"] is False
        assert resp.json()["activatedAt"] is None
        assert controller.system.force_mode is None
        assert controller.store["force_mode"] == _CLEARED
        controller.replan.assert_called_once_with(controller)

    def test_unconfigured_returns_503(self, controller: MagicMock) -> None:
        controller.system.is_configured = False
        assert _client.delete("/api/force-mode").status_code == 503
