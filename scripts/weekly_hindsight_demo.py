"""Isolated local review server: synthetic observations + the production API.

Run from the repository root with the dev venv:
    python -m uvicorn scripts.weekly_hindsight_demo:app --host 127.0.0.1 --port 8097

No BatterySystemManager, HA client, scheduler or inverter is constructed. The
production Insights and Savings UI is served from frontend/dist. The normal
mock-HA server can run independently to audit its unchanged service-call log.
"""

import json
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.bess.daily_view_store import DailyViewStore
from core.bess.simulation.inverter_simulator import derive_control_command, simulate
from core.bess.tests.unit.test_weekly_hindsight import synthetic_week

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
_data = TemporaryDirectory(prefix="bess-hindsight-demo-")
store = DailyViewStore(Path(_data.name))
battery = synthetic_week(store)
for day_index in range(7):
    day = date(2026, 9, 7) + timedelta(days=day_index)
    view = store.load_day(day)
    assert view is not None
    commands = []
    for p in view.periods:
        assert p.timestamp is not None
        commands.append(
            derive_control_command(
                (
                    "GRID_CHARGING"
                    if 2 <= p.timestamp.hour < 4
                    else (
                        "LOAD_SUPPORT"
                        if 18 <= p.timestamp.hour < 22
                        else "SOLAR_EXPORT"
                    )
                ),
                1 if 2 <= p.timestamp.hour < 4 else -1,
                battery,
            )
        )
    replay = simulate(
        commands,
        [p.energy.solar_production for p in view.periods],
        [p.energy.home_consumption for p in view.periods],
        [p.economic.buy_price for p in view.periods],
        [p.economic.sell_price for p in view.periods],
        0,
        battery,
        0.25,
        currency="EUR",
    )
    for original, realized in zip(view.periods, replay.period_data, strict=True):
        original.energy = realized.energy
        original.energy.observation_verified = True
        original.economic = realized.economic
    store.save_day(view)

# A newer incomplete week exercises default selection and the coverage state.
partial = store.load_day(date(2026, 9, 7))
assert partial is not None
store.save_day(replace(partial, date=date(2026, 9, 14)))

# api.py deliberately imports the initialized controller lazily. This stub exposes
# only the read-side dependencies used in this review server.
_stub = ModuleType("app")
_stub.__dict__["bess_controller"] = SimpleNamespace(
    startup_complete=True,
    system=SimpleNamespace(
        is_configured=True,
        daily_view_store=store,
        home_settings=SimpleNamespace(currency="EUR"),
    ),
)
sys.modules["app"] = _stub
from api import router  # noqa: E402
from api_conversion import convert_keys_to_camel_case  # noqa: E402
from api_dataclasses import APIConsumptionForecastComparison  # noqa: E402

app = FastAPI(title="Synthetic Weekly Hindsight Review")


@app.get("/api/settings")
def settings() -> dict[str, Any]:
    payload = json.loads((ROOT / "e2e/ci-bess-settings.json").read_text())
    return cast(dict[str, Any], convert_keys_to_camel_case(payload))


@app.get("/api/setup/status")
def setup_status() -> dict[str, bool]:
    return {"wizardNeeded": False}


@app.get("/api/system-health")
def health() -> dict[str, Any]:
    return {
        "components": [],
        "hasCriticalErrors": False,
        "hasWarnings": False,
        "totalCriticalIssues": 0,
        "criticalIssues": [],
    }


@app.get("/api/prediction-analysis/snapshots")
def snapshots() -> dict[str, Any]:
    return {"snapshots": [], "count": 0}


@app.get("/api/consumption-forecast-comparison")
def forecasts() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        convert_keys_to_camel_case(
            APIConsumptionForecastComparison("fixed", [], [], 0)
        ),
    )


@app.get("/api/ai/chat/status")
def ai_status() -> dict[str, Any]:
    return {"configured": False, "enabled": False, "model": ""}


app.include_router(router)
app.mount(
    "/assets", StaticFiles(directory=ROOT / "frontend/dist/assets"), name="assets"
)


@app.get("/{path:path}")
def frontend(path: str) -> FileResponse:
    return FileResponse(ROOT / "frontend/dist/index.html")
