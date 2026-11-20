"""The insights endpoint has no live-data or control dependencies."""

import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from api import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bess.daily_view_store import DailyViewStore
from core.bess.settings import BatterySettings, HomeSettings


def test_weekly_endpoint_reads_only_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = Mock(side_effect=AssertionError("No inverter/HA calls are permitted"))
    system = SimpleNamespace(
        is_configured=True,
        daily_view_store=DailyViewStore(tmp_path),
        home_settings=SimpleNamespace(currency="EUR"),
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
    with TestClient(app) as client:
        response = client.get("/api/insights/weekly-performance?date=2026-09-07")
        assert response.status_code == 200
        data = response.json()["weeklyPerformance"]
        assert data["status"] == "insufficient_data"
        assert data["optimal"] is None
        assert data["capturedPercent"] is None
        assert data["startDate"] == date(2026, 9, 7).isoformat()
        assert (
            client.get("/api/insights/weekly-performance?date=invalid").status_code
            == 422
        )
        assert client.post("/api/insights/weekly-performance").status_code == 405
        assert (
            client.get("/api/insights/weekly-performance?mode=estimated").status_code
            == 422
        )
    control.assert_not_called()


def test_backup_profile_is_reviewable_but_requires_explicit_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "assumptions.json"
    profile.write_text(
        json.dumps(
            {
                "battery": asdict(BatterySettings()),
                "home": asdict(HomeSettings(currency="EUR")),
                "inverter": {"platform": "huawei_solar_luna2000"},
            }
        )
    )
    original = profile.read_bytes()
    control = Mock(side_effect=AssertionError("Read-only historical analysis"))
    system = SimpleNamespace(
        is_configured=True,
        daily_view_store=DailyViewStore(tmp_path / "history"),
        home_settings=SimpleNamespace(currency="SEK"),
        update_battery_schedule=control,
        ha_controller=control,
    )
    monkeypatch.setattr(
        sys.modules["app"],
        "bess_controller",
        SimpleNamespace(system=system, startup_complete=True),
        raising=False,
    )
    monkeypatch.setenv("BESS_HINDSIGHT_ASSUMPTIONS_FILE", str(profile))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        verified = client.get(
            "/api/insights/weekly-performance?date=2026-09-07"
        ).json()["weeklyPerformance"]
        assert verified["assumptionProfile"]["currency"] == "EUR"
        assert verified["assumptions"] is None
        assert verified["diagnostics"]["configurationAssumed"] == 0
        assert (
            client.get("/api/insights/weekly-performance?mode=estimated").status_code
            == 422
        )
        response = client.get(
            "/api/insights/weekly-performance?date=2026-09-07&mode=estimated&assumptions_source=backup&allow_partial=true"
        )
        assert response.status_code == 200
        assert response.json()["weeklyPerformance"]["mode"] == "estimated"
    assert profile.read_bytes() == original
    control.assert_not_called()
