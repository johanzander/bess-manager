"""Tests for GET /api/savings/aggregate, disk-usage, and clear routes."""

import sys
from datetime import date
from unittest.mock import MagicMock

from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bess.daily_view_builder import DailyView
from core.bess.daily_view_store import DailyViewStore
from core.bess.models import EconomicData, EnergyData, PeriodData

_test_app = FastAPI()
_test_app.include_router(router)
_client = TestClient(_test_app, raise_server_exceptions=False)


def _period(grid_imported: float, grid_exported: float) -> PeriodData:
    energy = EnergyData(
        solar_production=1.0,
        home_consumption=grid_imported,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    economic = EconomicData(buy_price=2.0, sell_price=1.0, battery_cycle_cost=0.1)
    return PeriodData(period=0, energy=energy, economic=economic)


def _seeded_store(tmp_path) -> DailyViewStore:
    store = DailyViewStore(persist_dir=tmp_path)
    store.save_day(
        DailyView(
            date=date(2026, 7, 8),
            periods=[_period(1.0, 2.0)],
            total_savings=3.0,
            actual_count=1,
            predicted_count=0,
        )
    )
    return store


def _make_started_controller(daily_view_store) -> MagicMock:
    ctrl = MagicMock()
    ctrl.system.is_configured = True
    ctrl.startup_complete = True
    ctrl.system.daily_view_store = daily_view_store
    ctrl.system.home_settings.currency = "EUR"
    return ctrl


def _unconfigured_controller() -> MagicMock:
    ctrl = MagicMock()
    ctrl.system.is_configured = False
    ctrl.startup_complete = True
    return ctrl


class TestSavingsAggregate:
    def test_returns_200_with_expected_bucket_fields(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(
            _seeded_store(tmp_path)
        )

        resp = _client.get("/api/savings/aggregate?period=week&count=1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        bucket = body["buckets"][0]
        assert bucket["dayCount"] == 1
        assert bucket["gridCost"]["value"] == 0.0  # 2.0 import_eur - 2.0 export_eur
        assert bucket["savingsVsGridOnly"]["value"] == 3.0

    def test_empty_store_returns_empty_buckets_list_not_error(self, tmp_path):
        empty_store = DailyViewStore(persist_dir=tmp_path)
        sys.modules["app"].bess_controller = _make_started_controller(empty_store)

        resp = _client.get("/api/savings/aggregate?period=month&count=1")

        assert resp.status_code == 200
        assert resp.json()["buckets"][0]["dayCount"] == 0

    def test_omitted_count_uses_period_default(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(
            _seeded_store(tmp_path)
        )

        resp = _client.get("/api/savings/aggregate?period=week")

        assert resp.status_code == 200
        assert resp.json()["count"] == 12  # DEFAULT_COUNTS["week"]

    def test_invalid_period_returns_422(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(
            _seeded_store(tmp_path)
        )

        resp = _client.get("/api/savings/aggregate?period=fortnight")

        assert resp.status_code == 422

    def test_unconfigured_returns_503(self):
        sys.modules["app"].bess_controller = _unconfigured_controller()

        resp = _client.get("/api/savings/aggregate?period=week")

        assert resp.status_code == 503


class TestDiskUsage:
    def test_returns_day_count_and_bytes(self, tmp_path):
        sys.modules["app"].bess_controller = _make_started_controller(
            _seeded_store(tmp_path)
        )

        resp = _client.get("/api/savings/history/disk-usage")

        assert resp.status_code == 200
        body = resp.json()
        assert body["dayCount"] == 1
        assert body["totalBytes"] > 0


class TestClearHistory:
    def test_clears_and_returns_zeroed_usage(self, tmp_path):
        store = _seeded_store(tmp_path)
        sys.modules["app"].bess_controller = _make_started_controller(store)

        resp = _client.delete("/api/savings/history")

        assert resp.status_code == 200
        assert resp.json()["dayCount"] == 0
        assert store.list_available_dates() == []
