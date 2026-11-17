"""Debug-log replay at an earlier time must start from that time's battery level (#889).

``./mock-run.sh <bundle> HH:MM`` moves the clock, but every entity -- the
battery SOC included -- used to stay at its export-time value, so the replayed
optimizer planned from a level the battery never had at ``HH:MM``. In #881 the
bundle was exported at 07:31 with 24% (12 kWh of 50), while the bundle's own
period 4 (01:00) records ``battery_soe_start = 33.0`` kWh; replayed at 01:00
the night planned GRID_CHARGING instead of the reported LOAD_SUPPORT.

These tests assert what the mock Home Assistant ends up serving for the SOC
entity, not how the value is carried there.
"""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SOC_ENTITY = "sensor.inverter_state_of_charge_soc"
_CAPACITY = 50.0
_EXPORT_SOC = "24"


def _load_module(name: str, relative: str) -> Any:
    """Import a scripts/ file by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _replay_soc() -> Any:
    return _load_module("replay_soc", "scripts/mock_ha/replay_soc.py")


def _period(index: int, soe_start: float) -> dict:
    return {
        "period": index,
        "energy": {"battery_soe_start": soe_start, "battery_soe_end": soe_start - 1},
    }


def _scenario(sensors_config: dict, history: list[dict | None]) -> dict:
    return {
        "timezone": "Europe/Stockholm",
        "mock_time": "@2026-11-10 07:31:00",
        "bess_config": {
            "battery": {"total_capacity": _CAPACITY},
            "sensors": sensors_config,
        },
        "sensors": {_SOC_ENTITY: {"state": _EXPORT_SOC, "attributes": {}}},
        "historical_periods": history,
    }


_PER_PLATFORM = {
    "platform": "growatt_server_min",
    "shared": {},
    "growatt_server_min": {"battery_soc": _SOC_ENTITY},
}
_LEGACY_FLAT = {"battery_soc": _SOC_ENTITY}


def _history_through_export() -> list[dict | None]:
    """Periods 0..29 recorded, each starting 1 kWh lower; period 4 holds 33 kWh."""
    return [_period(i, 37.0 - i) for i in range(30)]


@pytest.mark.parametrize("sensors_config", [_PER_PLATFORM, _LEGACY_FLAT])
def test_earlier_replay_serves_the_recorded_soc_for_that_period(
    sensors_config: dict,
) -> None:
    scenario = _scenario(sensors_config, _history_through_export())

    overrides = _replay_soc().replay_soc_overrides(scenario, "01:00")

    assert float(overrides[_SOC_ENTITY]) == pytest.approx(33.0 / _CAPACITY * 100)


def test_replay_mid_period_uses_that_period_start() -> None:
    scenario = _scenario(_PER_PLATFORM, _history_through_export())

    overrides = _replay_soc().replay_soc_overrides(scenario, "01:14")

    assert float(overrides[_SOC_ENTITY]) == pytest.approx(33.0 / _CAPACITY * 100)


@pytest.mark.parametrize("replay_time", ["07:30", "09:00"])
def test_replay_at_or_after_export_period_keeps_the_snapshot(
    replay_time: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The export period's snapshot is the real value -- not a gap to warn about."""
    scenario = _scenario(_PER_PLATFORM, _history_through_export())

    assert _replay_soc().replay_soc_overrides(scenario, replay_time) == {}
    assert "WARNING" not in capsys.readouterr().err


def test_missing_history_for_the_period_keeps_the_snapshot_and_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    history = _history_through_export()
    history[4] = None
    scenario = _scenario(_PER_PLATFORM, history)

    assert _replay_soc().replay_soc_overrides(scenario, "01:00") == {}
    assert "WARNING" in capsys.readouterr().err


def test_mock_ha_serves_the_override_instead_of_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The value reaches the entity BESS reads, attributes untouched."""
    scenario_name = "ci-normal-day"
    scenario = json.loads(
        (
            _REPO_ROOT / "scripts" / "mock_ha" / "scenarios" / f"{scenario_name}.json"
        ).read_text()
    )
    entity = scenario["bess_config"]["sensors"]["battery_soc"]
    snapshot = scenario["sensors"][entity]
    assert snapshot["state"] != "66.0"

    monkeypatch.setenv("SCENARIO", scenario_name)
    monkeypatch.setenv("MOCK_SENSOR_OVERRIDES", json.dumps({entity: "66.0"}))
    server = _load_module("mock_ha_server", "scripts/mock_ha/server.py")
    server._load_scenario()

    assert server._sensors[entity]["state"] == "66.0"
    assert server._sensors[entity]["attributes"] == snapshot["attributes"]


def test_scenario_without_a_soc_mapping_replays_unchanged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Setup-wizard scenarios map no sensors yet; HH:MM must still start (#889)."""
    scenario = _scenario({}, _history_through_export())

    assert _replay_soc().replay_soc_overrides(scenario, "01:00") == {}
    assert "battery_soc" in capsys.readouterr().err


def test_fall_back_day_repeated_hour_uses_its_first_occurrence() -> None:
    """02:30 on the fall-back day is period 10, not the wall-clock-later 14."""
    scenario = _scenario(_PER_PLATFORM, [_period(i, 60.0 - i) for i in range(40)])
    scenario["mock_time"] = "@2026-10-25 09:00:00"

    overrides = _replay_soc().replay_soc_overrides(scenario, "02:30")

    assert float(overrides[_SOC_ENTITY]) == pytest.approx(50.0 / _CAPACITY * 100)
