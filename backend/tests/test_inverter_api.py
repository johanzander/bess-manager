"""Tests for /api/growatt/inverter_status and /api/growatt/detailed_schedule.

These endpoints form the contract between the backend controller state and
the frontend InverterStatusDashboard component. Missing or wrong fields here
produce broken UI (wrong platform badge, "Segment #undefined" labels).
"""

import sys
from unittest.mock import MagicMock

import pytest
from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from settings_store import VALID_PLATFORMS

_test_app = FastAPI()
_test_app.include_router(router)
_client = TestClient(_test_app, raise_server_exceptions=False)


def _make_controller(platform: str) -> MagicMock:
    """Return a bess_controller mock wired for the given inverter platform."""
    ctrl = MagicMock()
    ctrl.system.inverter_platform = platform
    ctrl.system.battery_settings.total_capacity = 30.0
    ctrl.system.battery_settings.max_soc = 95
    ctrl.system.battery_settings.min_soc = 10
    ctrl.system._controller.get_battery_soc.return_value = 75
    ctrl.system._controller.grid_charge_enabled.return_value = False
    ctrl.system._controller.get_discharging_power_rate.return_value = 100
    ctrl.system._controller.get_battery_charge_power.return_value = 0.0
    ctrl.system._controller.get_battery_discharge_power.return_value = 0.0

    sm = ctrl.system._inverter_controller
    sm.strategic_intents = ["IDLE"] * 96
    sm.get_period_settings.return_value = {
        "batt_mode": "load_first",
        "strategic_intent": "IDLE",
        "grid_charge": False,
        "discharge_rate": 100,
    }
    sm.get_all_tou_segments.return_value = [
        {
            "segment_id": 1,
            "start_time": "02:00",
            "end_time": "05:59",
            "batt_mode": "battery_first",
            "enabled": True,
            "is_default": False,
            "strategic_intent": "GRID_CHARGING",
        }
    ]
    sm.get_strategic_intent_summary.return_value = {}
    sm._get_intent_description.return_value = ""
    sm.get_detailed_period_groups.return_value = []
    ctrl.system.price_manager.get_today_prices.return_value = [1.0] * 24
    ctrl.system.schedule_store.get_latest_schedule.return_value = None
    return ctrl


# ===========================================================================
# GET /api/growatt/inverter_status
# ===========================================================================


@pytest.mark.parametrize("platform", VALID_PLATFORMS)
class TestInverterStatus:
    """inverterPlatform in the response must be the exact configured platform string."""

    def test_returns_200(self, platform):
        ctrl = _make_controller(platform)
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/inverter_status")
        assert resp.status_code == 200

    def test_inverter_platform_is_exact_valid_platform_string(self, platform):
        ctrl = _make_controller(platform)
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/inverter_status")
        assert resp.json()["inverterPlatform"] == platform


# ===========================================================================
# GET /api/growatt/detailed_schedule
# ===========================================================================


class TestDetailedSchedule:
    """touIntervals contract: every item must carry segmentId and isDefault."""

    def test_returns_200(self):
        ctrl = _make_controller("growatt_server_sph")
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/detailed_schedule")
        assert resp.status_code == 200

    def test_inverter_platform_present(self):
        ctrl = _make_controller("growatt_server_sph")
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/detailed_schedule")
        assert resp.json()["inverterPlatform"] == "growatt_server_sph"

    def test_tou_intervals_have_segment_id(self):
        ctrl = _make_controller("growatt_server_sph")
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/detailed_schedule")
        intervals = resp.json()["touIntervals"]
        assert len(intervals) > 0
        for interval in intervals:
            assert "segmentId" in interval, f"segmentId missing from {interval}"
            assert isinstance(interval["segmentId"], int)
            assert interval["segmentId"] >= 1

    def test_tou_intervals_have_is_default(self):
        ctrl = _make_controller("growatt_server_sph")
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/detailed_schedule")
        intervals = resp.json()["touIntervals"]
        for interval in intervals:
            assert "isDefault" in interval, f"isDefault missing from {interval}"
            assert isinstance(interval["isDefault"], bool)

    def test_active_intervals_are_not_default(self):
        ctrl = _make_controller("growatt_server_sph")
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/detailed_schedule")
        intervals = resp.json()["touIntervals"]
        for interval in intervals:
            if interval.get("enabled"):
                assert interval["isDefault"] is False
