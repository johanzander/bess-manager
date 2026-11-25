"""The insights endpoint reads history through BSM and has no control path."""

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bess.daily_view_store import DailyViewStore
from core.bess.execution_model import DEFAULT_CAPABILITIES
from core.bess.performance_hindsight import (
    HindsightModel,
    PerformanceAnalysis,
    PeriodKind,
    analyze_period,
)
from core.bess.settings import BatterySettings, HomeSettings


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    store = DailyViewStore(tmp_path)
    model = HindsightModel(
        BatterySettings(), HomeSettings(currency="EUR"), DEFAULT_CAPABILITIES
    )
    requests: list[tuple] = []

    def analyze_performance(
        anchor: date | None, period: PeriodKind
    ) -> PerformanceAnalysis:
        requests.append((anchor, period))
        return analyze_period(store, anchor or date(2026, 9, 7), model, period=period)

    control = Mock(side_effect=AssertionError("No inverter/HA calls are permitted"))
    system = SimpleNamespace(
        is_configured=True,
        daily_view_store=store,
        analyze_performance=analyze_performance,
        update_battery_schedule=control,
        ha_controller=control,
    )
    monkeypatch.setattr(
        sys.modules["app"],
        "bess_controller",
        SimpleNamespace(system=system, startup_complete=True),
        raising=False,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), requests, control


def test_the_endpoint_returns_the_period_bucket_with_its_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, requests, control = _client(tmp_path, monkeypatch)
    with client:
        response = client.get("/api/insights/performance?date=2026-09-09")
        assert response.status_code == 200
        body = response.json()
        assert body["startDate"] == "2026-09-07"
        performance = body["performance"]
        assert performance["status"] == "insufficient_data"
        assert performance["comparison"] is None
        assert performance["coverage"]["expectedPeriods"] == 7 * 96
        assert requests == [(date(2026, 9, 9), "week")]
        client.get("/api/insights/performance?period=month")
        assert requests[-1] == (None, "month")
    control.assert_not_called()


@pytest.mark.parametrize(
    "query", ["date=invalid", "period=year", "mode=verified&period=day"]
)
def test_invalid_requests_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    client, requests, _ = _client(tmp_path, monkeypatch)
    with client:
        assert client.get(f"/api/insights/performance?{query}").status_code == 422
        assert client.post("/api/insights/performance").status_code == 405
    assert requests == []
