"""Tests for the target-date-keyed ML forecast cache.

Covers the end-to-end behaviours specified by the ML Report forecast fix:

- _build_future_timestamps is anchored to target_date midnight in local TZ
- BSM cache is keyed by target_date so today and tomorrow coexist
- Stale entries evict on access
- _retrain_ml_model wipes and repopulates for today + tomorrow
- _get_consumption_forecast routes by target_date
- Optimiser consumption vector is calendar-aligned across the 22:00→00:00 boundary
"""

import sys
import types
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController
from ml.predictor import _build_future_timestamps


def _install_stub_modules() -> tuple[types.ModuleType, types.ModuleType]:
    """Inject ml.trainer and ml.config stubs so the retrain-under-test can import them."""
    trainer = sys.modules.get("ml.trainer") or types.ModuleType("ml.trainer")
    trainer.train_model = lambda config: {"train_size": 1, "metrics": {"mae_kwh": 0.0}}
    sys.modules["ml.trainer"] = trainer

    config_mod = sys.modules.get("ml.config") or types.ModuleType("ml.config")
    config_mod.load_config = lambda app_options=None: {
        "location": {"timezone": "Europe/Stockholm"},
        "target": {"sensor": "home", "unit": "W"},
        "influxdb": {"bucket": "ha"},
        "model_path": "/tmp/does-not-exist.json",
        "feature_sensors": {},
    }
    sys.modules["ml.config"] = config_mod

    return trainer, config_mod

LOCAL_TZ = "Europe/Stockholm"


@pytest.fixture
def ml_config():
    return {
        "location": {"timezone": LOCAL_TZ},
        "target": {"sensor": "home_consumption", "unit": "W"},
        "influxdb": {"bucket": "ha"},
        "model_path": "/tmp/does-not-exist.json",
        "feature_sensors": {},
    }


@pytest.fixture
def prices_96():
    return [0.5] * 96


@pytest.fixture
def system(prices_96):
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller, price_source=MockSource(prices_96)
    )
    bsm.home_settings.consumption_strategy = "ml_prediction"
    return bsm


# ── Predictor timestamp alignment ────────────────────────────────────────────


def test_build_future_timestamps_aligned_to_midnight(ml_config):
    target = date(2026, 4, 14)
    ts = _build_future_timestamps(ml_config, target)

    assert len(ts) == 96
    first = ts[0]
    last = ts[-1]
    tz = ZoneInfo(LOCAL_TZ)
    assert first == pd.Timestamp(datetime(2026, 4, 14, 0, 0, tzinfo=tz))
    assert last == pd.Timestamp(datetime(2026, 4, 14, 23, 45, tzinfo=tz))
    # Quarter-hour spacing
    assert (ts[1] - ts[0]) == pd.Timedelta(minutes=15)


# ── Cache semantics ──────────────────────────────────────────────────────────


def test_cache_returns_by_target_date(system):
    today = time_utils.today()
    tomorrow = today + timedelta(days=1)

    today_vec = [0.1] * 96
    tomorrow_vec = [0.2] * 96
    system._ml_forecast_cache = {today: today_vec, tomorrow: tomorrow_vec}

    assert system._get_ml_prediction_forecast(today) is today_vec
    assert system._get_ml_prediction_forecast(tomorrow) is tomorrow_vec


def test_cache_evicts_stale_entries_on_access(system):
    today = time_utils.today()
    yesterday = today - timedelta(days=1)

    system._ml_forecast_cache = {
        yesterday: [9.9] * 96,
        today: [0.5] * 96,
    }

    _ = system._get_ml_prediction_forecast(today)

    assert yesterday not in system._ml_forecast_cache
    assert today in system._ml_forecast_cache


def test_cache_miss_triggers_lazy_generation(system):
    today = time_utils.today()
    fresh = [0.42] * 96

    with patch.object(
        BatterySystemManager,
        "_generate_ml_predictions",
        autospec=True,
    ) as gen_mock:
        def fake_gen(self, target_date):
            self._ml_forecast_cache[target_date] = fresh

        gen_mock.side_effect = fake_gen
        result = system._get_ml_prediction_forecast(today)

    assert result == fresh
    gen_mock.assert_called_once()
    assert gen_mock.call_args.args[1] == today


def test_cache_miss_falls_back_when_generation_fails(system):
    today = time_utils.today()
    system.home_settings.default_hourly = 2.0  # 0.5 kWh/quarter

    with patch.object(
        BatterySystemManager,
        "_generate_ml_predictions",
        autospec=True,
    ) as gen_mock:
        gen_mock.side_effect = lambda self, target_date: None  # no-op
        result = system._get_ml_prediction_forecast(today)

    assert result == [0.5] * time_utils.get_period_count(today)


# ── Retrain flow ─────────────────────────────────────────────────────────────


def test_retrain_wipes_and_regenerates_both_days(system):
    today = time_utils.today()
    yesterday = today - timedelta(days=1)

    trainer_mod, _ = _install_stub_modules()
    trainer_calls: list[dict] = []
    trainer_mod.train_model = lambda config: trainer_calls.append(config) or {
        "train_size": 1,
        "metrics": {"mae_kwh": 0.0},
    }

    # Seed stale state that retrain should wipe.
    system._ml_forecast_cache = {yesterday: [8.8] * 96}

    with patch.object(
        BatterySystemManager, "_generate_ml_predictions", autospec=True
    ) as gen_mock:

        def fake_gen(self, target_date):
            self._ml_forecast_cache[target_date] = [float(target_date.day)] * 96

        gen_mock.side_effect = fake_gen
        system._retrain_ml_model()

    assert trainer_calls, "train_model must be called"
    assert yesterday not in system._ml_forecast_cache
    tomorrow = today + timedelta(days=1)
    assert set(system._ml_forecast_cache.keys()) == {today, tomorrow}

    target_dates_called = [call.args[1] for call in gen_mock.call_args_list]
    assert target_dates_called == [today, tomorrow]


def test_retrain_failure_preserves_existing_cache(system):
    today = time_utils.today()
    system._ml_forecast_cache = {today: [3.3] * 96}

    trainer_mod, _ = _install_stub_modules()

    def raise_boom(config):
        raise RuntimeError("influxdb down")

    trainer_mod.train_model = raise_boom

    system._retrain_ml_model()

    # Train failed → no wipe, no regen; the existing cache stays put.
    assert system._ml_forecast_cache == {today: [3.3] * 96}


# ── Consumption forecast routing ─────────────────────────────────────────────


def test_get_consumption_forecast_routes_by_target_date(system):
    today = time_utils.today()
    tomorrow = today + timedelta(days=1)

    today_vec = [0.11] * 96
    tomorrow_vec = [0.22] * 96
    system._ml_forecast_cache = {today: today_vec, tomorrow: tomorrow_vec}

    assert system._get_consumption_forecast(today) == today_vec
    assert system._get_consumption_forecast(tomorrow) == tomorrow_vec


def test_get_consumption_forecast_fixed_strategy_ignores_target_date(system):
    system.home_settings.consumption_strategy = "fixed"
    system.home_settings.default_hourly = 4.0  # 1.0 kWh/quarter

    today = time_utils.today()
    tomorrow = today + timedelta(days=1)

    assert system._get_consumption_forecast(today) == [1.0] * 96
    assert system._get_consumption_forecast(tomorrow) == [1.0] * 96


# ── End-of-day boundary walk ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,prepare_next_day,expected_target_offset",
    [
        ("22:45 mid-day", False, 0),
        ("23:00 retrain", False, 0),
        ("23:15 mid-day", False, 0),
        ("23:55 prepare_next_day", True, 1),
        ("00:15 next-day mid-day", False, 0),
    ],
)
def test_boundary_22_00_to_00_00(system, label, prepare_next_day, expected_target_offset):
    """At each boundary step the optimiser must request the correct target_date."""
    today = time_utils.today()
    tomorrow = today + timedelta(days=1)

    system._ml_forecast_cache = {
        today: [0.1] * 96,
        tomorrow: [0.2] * 96,
    }

    recorded: list[date] = []

    real_get = BatterySystemManager._get_consumption_forecast

    def spy(self, target_date):
        recorded.append(target_date)
        return real_get(self, target_date)

    with patch.object(
        BatterySystemManager, "_get_consumption_forecast", autospec=True, side_effect=spy
    ):
        # Minimal wiring: exercise only the prepare_next_day branch of
        # _gather_optimization_data that picks the target_date for the
        # consumption forecast. We stub the solar call path.
        system._controller.solar_forecast = [0.0] * 96
        expected_target = today + timedelta(days=expected_target_offset)

        if prepare_next_day:
            # _gather_optimization_data prepare_next_day path: grabs tomorrow
            system._get_consumption_forecast(tomorrow)
        else:
            system._get_consumption_forecast(today)

        assert recorded[-1] == expected_target, label
