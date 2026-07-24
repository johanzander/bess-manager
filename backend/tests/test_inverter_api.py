"""Tests for /api/growatt/inverter_status and /api/growatt/detailed_schedule.

These endpoints form the contract between the backend controller state and
the frontend InverterStatusDashboard component. Missing or wrong fields here
produce broken UI (wrong platform badge, "Segment #undefined" labels).
"""

import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bess import time_utils
from core.bess.models import DecisionData, EnergyData, OptimizationResult, PeriodData
from core.bess.schedule_store import StoredSchedule
from core.bess.settings_store import VALID_PLATFORMS

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


class TestInverterStatusUnavailableBatterySoc:
    """battery_soc sensor going 'unavailable' must not surface as an opaque
    TypeError from dividing None by a float."""

    def test_returns_clear_error(self):
        ctrl = _make_controller("growatt_server_min")
        ctrl.system._controller.get_battery_soc.return_value = None
        sys.modules["app"].bess_controller = ctrl

        resp = _client.get("/api/growatt/inverter_status")

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "NoneType" not in detail
        assert "battery_soc" in detail.lower() or "battery soc" in detail.lower()


class TestInverterStatusChargePowerRate:
    """chargePowerRate must be a live sensor read, not the config default (issue #271)."""

    def test_charge_power_rate_reflects_live_controller_value(self):
        ctrl = _make_controller("growatt_server_sph")
        # 40 is BATTERY_DEFAULT_CHARGING_POWER_RATE - use a different value to
        # prove this isn't falling back to the config default.
        ctrl.system._controller.get_charging_power_rate.return_value = 100
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/inverter_status")
        assert resp.status_code == 200
        assert resp.json()["chargePowerRate"] == 100


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


class TestScheduleDataChargeRate:
    """chargePowerRate in schedule_data must reflect charge_rate from get_period_settings."""

    def test_charge_power_rate_reflects_period_settings(self):
        ctrl = _make_controller("growatt_server_min")
        sm = ctrl.system._inverter_controller
        sm.get_period_settings.return_value = {
            "batt_mode": "battery_first",
            "strategic_intent": "GRID_CHARGING",
            "grid_charge": True,
            "charge_rate": 25,
            "discharge_rate": 0,
        }
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/detailed_schedule")
        assert resp.status_code == 200
        schedule = resp.json()["scheduleData"]
        assert len(schedule) > 0
        for entry in schedule:
            assert (
                entry["chargePowerRate"] == 25
            ), f"hour {entry['hour']}: expected chargePowerRate=25, got {entry['chargePowerRate']}"

    def test_charge_power_rate_defaults_to_100_when_charge_rate_absent(self):
        ctrl = _make_controller("growatt_server_min")
        sm = ctrl.system._inverter_controller
        # get_period_settings returns no charge_rate key → should default to 100
        sm.get_period_settings.return_value = {
            "batt_mode": "load_first",
            "strategic_intent": "IDLE",
            "grid_charge": False,
            "discharge_rate": 100,
        }
        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/detailed_schedule")
        assert resp.status_code == 200
        schedule = resp.json()["scheduleData"]
        for entry in schedule:
            assert entry["chargePowerRate"] == 100


# ===========================================================================
# GET /api/growatt/detailed_schedule — period_groups intent reconciliation
# (issue #317)
# ===========================================================================


def _make_period_data(
    period: int, data_source: str, strategic_intent: str, observed_intent: str | None
) -> PeriodData:
    energy = EnergyData(
        solar_production=0.0,
        home_consumption=0.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.0,
        battery_soe_start=15.0,
        battery_soe_end=15.0,
    )
    decision = DecisionData(
        strategic_intent=strategic_intent, observed_intent=observed_intent
    )
    return PeriodData(
        period=period,
        energy=energy,
        timestamp=time_utils.period_index_to_timestamp(period),
        data_source=data_source,
        decision=decision,
    )


def _group_per_period(**kwargs) -> list[dict]:
    """Fake get_detailed_period_groups: one ungrouped group per period, echoing
    back whatever `intents` list was actually passed in — lets the test see
    exactly what the endpoint decided each period's reconciled intent is."""
    intents = kwargs["intents"]
    return [
        {
            "start_time": f"{i // 4:02d}:{(i % 4) * 15:02d}",
            "end_time": f"{i // 4:02d}:{(i % 4) * 15 + 15:02d}",
            "mode": "load_first",
            "intent": intents[i],
            "period_count": 1,
            "duration_minutes": 15,
            "charge_rate": 100,
            "discharge_rate": 0,
            "grid_charge": False,
            "total_action_kwh": 0.0,
            "soc_end_pct": None,
        }
        for i in range(len(intents))
    ]


class TestPeriodGroupsIntentReconciliation:
    """dominant_intent must reflect observed_intent for actual periods, not the
    stale DP-planned strategic_intent (issue #317)."""

    def test_actual_period_uses_observed_intent_not_planned(self):
        ctrl = _make_controller("growatt_server_sph")
        sm = ctrl.system._inverter_controller
        # Planned schedule says period 0 was BATTERY_EXPORT...
        sm.strategic_intents = ["BATTERY_EXPORT"] + ["IDLE"] * 95
        sm.get_detailed_period_groups.side_effect = _group_per_period

        num_periods = time_utils.get_period_count(time_utils.today())
        period_data = [
            _make_period_data(0, "actual", "BATTERY_EXPORT", "IDLE"),
        ] + [
            _make_period_data(i, "predicted", "IDLE", None)
            for i in range(1, num_periods)
        ]
        stored_schedule = StoredSchedule(
            timestamp=datetime.now(),
            optimization_period=0,
            optimization_result=OptimizationResult(
                input_data={}, period_data=period_data
            ),
        )
        ctrl.system.schedule_store.get_latest_schedule.return_value = stored_schedule
        by_timestamp = {p.timestamp: p for p in period_data}
        ctrl.system.schedule_store.get_period_data_at.side_effect = (
            lambda ts: by_timestamp.get(ts)
        )

        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/detailed_schedule")
        assert resp.status_code == 200

        groups = resp.json()["periodGroups"]
        period_0_group = next(
            g for g in groups if g["startTime"] == "00:00" and g["endTime"] == "00:15"
        )
        # ...but the actual physical flow was IDLE (no battery discharge) — the
        # reconciled dominant_intent must say so, not the stale plan.
        assert period_0_group["dominantIntent"] == "IDLE"


class TestPeriodGroupsNextDaySchedule:
    """Regression for issue #380: /api/growatt/detailed_schedule's "today"
    period_groups block had no guard against the standalone prepare_next_day
    schedule (optimization_period=0, period_data[0] anchored to tomorrow
    00:00), unlike the two "tomorrow" lookups elsewhere in this file which
    were already patched for it."""

    def test_todays_period_groups_use_todays_schedule_not_next_days(self):
        from core.bess.schedule_store import ScheduleStore

        ctrl = _make_controller("growatt_server_sph")
        sm = ctrl.system._inverter_controller
        sm.strategic_intents = ["IDLE"] * 96
        sm.get_detailed_period_groups.side_effect = _group_per_period

        real_store = ScheduleStore()
        num_periods = time_utils.get_period_count(time_utils.today())

        # Today's real schedule, made moments earlier: period 0 already
        # completed with an observed physical flow of LOAD_SUPPORT.
        today_periods = [
            _make_period_data(0, "actual", "BATTERY_EXPORT", "LOAD_SUPPORT"),
        ] + [
            _make_period_data(i, "predicted", "IDLE", None)
            for i in range(1, num_periods)
        ]
        real_store.store_schedule(
            OptimizationResult(input_data={}, period_data=today_periods),
            optimization_period=0,
        )

        # The prepare_next_day schedule stored at 23:55: optimization_period=0,
        # period_data[0] anchored to tomorrow 00:00 with a different observed
        # intent -- must not shadow today's period 0 at the same positional
        # index.
        tomorrow_period_0 = _make_period_data(0, "actual", "IDLE", "GRID_CHARGE")
        tomorrow_period_0.timestamp = time_utils.period_index_to_timestamp(num_periods)
        real_store.store_schedule(
            OptimizationResult(input_data={}, period_data=[tomorrow_period_0]),
            optimization_period=0,
        )

        ctrl.system.schedule_store = real_store

        sys.modules["app"].bess_controller = ctrl
        resp = _client.get("/api/growatt/detailed_schedule")
        assert resp.status_code == 200

        groups = resp.json()["periodGroups"]
        period_0_group = next(
            g for g in groups if g["startTime"] == "00:00" and g["endTime"] == "00:15"
        )
        assert period_0_group["dominantIntent"] == "LOAD_SUPPORT"
