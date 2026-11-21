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
from core.bess.execution_model import DEFAULT_CAPABILITIES
from core.bess.settings import BatterySettings, HomeSettings


def _meters() -> SimpleNamespace:
    return SimpleNamespace(
        energy_flow_calculator=SimpleNamespace(
            sensor_to_flow_map={"a": "battery_charged", "b": "battery_discharged"}
        )
    )


def test_weekly_endpoint_reads_only_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = Mock(side_effect=AssertionError("No inverter/HA calls are permitted"))
    system = SimpleNamespace(
        is_configured=True,
        daily_view_store=DailyViewStore(tmp_path),
        home_settings=HomeSettings(currency="EUR"),
        battery_settings=BatterySettings(),
        platform_capabilities=DEFAULT_CAPABILITIES,
        sensor_collector=_meters(),
        inverter_platform="growatt_server_min",
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
        response = client.get("/api/insights/performance?date=2026-09-07")
        assert response.status_code == 200
        data = response.json()["performance"]
        assert data["status"] == "insufficient_data"
        assert data["optimal"] is None
        assert data["capturedPercent"] is None
        assert data["startDate"] == date(2026, 9, 7).isoformat()
        # Without a configured profile, auto estimates with current settings
        # and says so instead of asking the user to choose.
        assert data["assumptionProfile"]["source"].startswith(
            "current BESS Manager settings"
        )
        assert client.get("/api/insights/performance?date=invalid").status_code == 422
        assert client.post("/api/insights/performance").status_code == 405
        assert client.get("/api/insights/performance?mode=estimated").status_code == 422
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
        sensor_collector=_meters(),
        inverter_platform="growatt_server_min",
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
            "/api/insights/performance?date=2026-09-07&mode=verified"
        ).json()["performance"]
        assert verified["assumptionProfile"]["currency"] == "EUR"
        assert verified["assumptions"] is None
        assert verified["diagnostics"]["configurationAssumed"] == 0
        assert client.get("/api/insights/performance?mode=estimated").status_code == 422
        response = client.get(
            "/api/insights/performance?date=2026-09-07&mode=estimated&assumptions_source=backup&allow_partial=true"
        )
        assert response.status_code == 200
        assert response.json()["performance"]["mode"] == "estimated"
        automatic = client.get("/api/insights/performance?date=2026-09-07")
        assert automatic.json()["performance"]["mode"] == "estimated"
        assert automatic.json()["performance"]["assumptionProfile"][
            "source"
        ].startswith("assumptions.json")
    assert profile.read_bytes() == original
    control.assert_not_called()


def test_weekly_analysis_is_reused_until_history_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api as api_module

    history = DailyViewStore(tmp_path)
    system = SimpleNamespace(
        is_configured=True,
        daily_view_store=history,
        home_settings=HomeSettings(currency="EUR"),
        battery_settings=BatterySettings(),
        platform_capabilities=DEFAULT_CAPABILITIES,
        sensor_collector=_meters(),
        inverter_platform="growatt_server_min",
    )
    monkeypatch.setattr(
        sys.modules["app"],
        "bess_controller",
        SimpleNamespace(system=system, startup_complete=True),
        raising=False,
    )
    calls: list[object] = []
    real = api_module.analyze_period

    def counting(*args: object, **kwargs: object) -> object:
        calls.append(kwargs.get("mode"))
        return real(*args, **kwargs)

    monkeypatch.setattr(api_module, "analyze_period", counting)
    app = FastAPI()
    app.include_router(router)
    url = "/api/insights/performance?date=2026-09-07&mode=verified"
    with TestClient(app) as client:
        client.get(url)
        client.get(url)
        assert len(calls) == 1
        (tmp_path / "2026-09-08.json").write_text("{}")
        client.get(url)
        assert len(calls) == 2
        # A restart keeps a completed week's result on disk.
        api_module._performance_cache.clear()
        client.get(url)
        assert len(calls) == 2
        assert list((tmp_path.parent / "performance").glob("week-2026-09-07-*.json"))
        saved = tmp_path.parent / "performance" / "week-2026-09-07-verified.json"
        # An interrupted write must never leave this read-only view unusable.
        saved.write_text('{"key":', encoding="utf-8")
        api_module._performance_cache.clear()
        assert client.get(url).status_code == 200
        assert len(calls) == 3
        monkeypatch.setattr(
            api_module,
            "_PERFORMANCE_CACHE_VERSION",
            api_module._PERFORMANCE_CACHE_VERSION + 1,
        )
        assert client.get(url).status_code == 200
        assert len(calls) == 4
