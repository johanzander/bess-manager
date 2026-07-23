"""Coverage tests for inverter controllers: GrowattMin, GrowattSph, Solax, SolaxModbus.

Targets uncovered methods in each controller to push coverage toward 90%+.
"""

import pytest

from core.bess.dp_schedule import DPSchedule
from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.settings import BatterySettings
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController


def _hourly_to_quarterly(
    hourly_intents: dict[int, str], default: str = "IDLE"
) -> list[str]:
    """Convert hourly strategic intents to quarterly (96 periods).

    Local copy of the helper in test_growatt_tou_scheduling.py — no shared
    fixture/helper for DPSchedule construction existed in this file yet.
    """
    quarterly = [default] * 96
    for hour, intent in hourly_intents.items():
        for period in range(hour * 4, (hour + 1) * 4):
            quarterly[period] = intent
    return quarterly


def _make_min_schedule(intents: list[str]) -> DPSchedule:
    """Build a minimal DPSchedule carrying the given strategic intents."""
    n = len(intents)
    return DPSchedule(
        actions=[0.0] * n,
        state_of_energy=[20.0] * n,
        prices=[2.0] * n,
        original_dp_results={"strategic_intent": intents},
    )


@pytest.fixture
def battery_settings():
    return BatterySettings()


@pytest.fixture
def min_ctrl(battery_settings):
    return GrowattMinController(battery_settings=battery_settings)


@pytest.fixture
def sph_ctrl(battery_settings):
    return GrowattSphController(battery_settings=battery_settings)


@pytest.fixture
def solax_ctrl(battery_settings):
    return SolaxController(battery_settings=battery_settings)


@pytest.fixture
def modbus_ctrl(battery_settings):
    return SolaxModbusGrowattController(battery_settings=battery_settings)


# ── GrowattMinController ─────────────────────────────────────────────────────


class TestMinInitializeFromTouSegments:
    def test_parses_enabled_segments(self, min_ctrl):
        segments = [
            {
                "segment_id": 1,
                "enabled": True,
                "batt_mode": "battery_first",
                "start_time": "01:00",
                "end_time": "05:00",
            },
            {
                "segment_id": 2,
                "enabled": False,
                "batt_mode": "load_first",
                "start_time": "05:00",
                "end_time": "10:00",
            },
        ]
        min_ctrl.initialize_from_tou_segments(segments, current_hour=3)
        assert len(min_ctrl.tou_intervals) == 2
        assert min_ctrl.tou_intervals[0]["enabled"] is True
        assert min_ctrl.tou_intervals[1]["enabled"] is False
        assert min_ctrl.current_hour == 3

    def test_integer_batt_mode_conversion(self, min_ctrl):
        segments = [
            {
                "segment_id": 1,
                "enabled": True,
                "batt_mode": 0,
                "start_time": "00:00",
                "end_time": "06:00",
            },
            {
                "segment_id": 2,
                "enabled": True,
                "batt_mode": 1,
                "start_time": "06:00",
                "end_time": "12:00",
            },
            {
                "segment_id": 3,
                "enabled": True,
                "batt_mode": 2,
                "start_time": "12:00",
                "end_time": "18:00",
            },
        ]
        min_ctrl.initialize_from_tou_segments(segments)
        assert min_ctrl.tou_intervals[0]["batt_mode"] == "load_first"
        assert min_ctrl.tou_intervals[1]["batt_mode"] == "battery_first"
        assert min_ctrl.tou_intervals[2]["batt_mode"] == "grid_first"

    def test_no_segments(self, min_ctrl):
        min_ctrl.initialize_from_tou_segments([])
        assert min_ctrl.tou_intervals == []


class TestMinGetDailyTouSettings:
    def test_empty_when_no_intervals(self, min_ctrl):
        assert min_ctrl.get_daily_TOU_settings() == []

    def test_returns_intervals(self, min_ctrl):
        min_ctrl.tou_intervals = [
            {
                "segment_id": 1,
                "batt_mode": "battery_first",
                "start_time": "01:00",
                "end_time": "05:00",
                "enabled": True,
            },
        ]
        result = min_ctrl.get_daily_TOU_settings()
        assert len(result) == 1
        assert result[0]["batt_mode"] == "battery_first"

    def test_capped_to_max_intervals(self, min_ctrl):
        min_ctrl.tou_intervals = [
            {
                "segment_id": i,
                "batt_mode": "load_first",
                "start_time": f"{i:02d}:00",
                "end_time": f"{i:02d}:59",
                "enabled": True,
            }
            for i in range(15)
        ]
        result = min_ctrl.get_daily_TOU_settings()
        assert len(result) <= min_ctrl.max_intervals


class TestEvaluateIntentsGrowattMin:
    """No growatt_min_controller_pair/make_schedule fixture existed in this
    file — adapted to use the min_ctrl fixture plus local
    _hourly_to_quarterly/_make_min_schedule helpers."""

    def test_no_change_when_intents_identical(self, min_ctrl):
        intents = _hourly_to_quarterly({2: "GRID_CHARGING"})
        min_ctrl.apply_intents(_make_min_schedule(intents), current_period=0)

        differs, _reason = min_ctrl.evaluate_intents(
            _make_min_schedule(intents), current_period=0
        )

        assert differs is False

    def test_detects_change_when_intents_differ(self, min_ctrl):
        min_ctrl.apply_intents(
            _make_min_schedule(_hourly_to_quarterly({2: "GRID_CHARGING"})),
            current_period=0,
        )

        differs, reason = min_ctrl.evaluate_intents(
            _make_min_schedule(_hourly_to_quarterly({10: "BATTERY_EXPORT"})),
            current_period=0,
        )

        assert differs is True
        assert reason

    def test_corruption_forces_apply(self, min_ctrl):
        # Two intervals are required: validate_tou_intervals_ordering treats
        # a single-interval list as trivially ordered (len <= 1 short-circuits
        # to True), so corruption can only be observed with >= 2 intervals.
        intents = _hourly_to_quarterly({2: "GRID_CHARGING", 10: "BATTERY_EXPORT"})
        min_ctrl.apply_intents(_make_min_schedule(intents), current_period=0)
        # Corrupt hardware-committed state directly (out of chronological order)
        min_ctrl.tou_intervals[1]["start_time"] = "01:00"

        differs, reason = min_ctrl.evaluate_intents(
            _make_min_schedule(intents), current_period=0
        )

        assert differs is True
        assert "Corruption" in reason


class TestMinSyncSocLimits:
    def test_no_mismatch_skips_write(self, min_ctrl, mock_controller):
        mock_controller.settings["charge_stop_soc"] = 100
        mock_controller.settings["discharge_stop_soc"] = 10
        min_ctrl.sync_soc_limits(mock_controller)
        assert mock_controller.calls["charge_stop_soc"] == []
        assert mock_controller.calls["discharge_stop_soc"] == []

    def test_charge_mismatch_syncs(self, min_ctrl, mock_controller):
        min_ctrl.battery_settings.max_soc = 90
        min_ctrl.sync_soc_limits(mock_controller)
        assert mock_controller.calls["charge_stop_soc"] == [90]
        assert mock_controller.calls["discharge_stop_soc"] == []

    def test_discharge_mismatch_syncs(self, min_ctrl, mock_controller):
        min_ctrl.battery_settings.min_soc = 20
        min_ctrl.sync_soc_limits(mock_controller)
        assert mock_controller.calls["discharge_stop_soc"] == [20]
        assert mock_controller.calls["charge_stop_soc"] == []


# ── GrowattSphController ─────────────────────────────────────────────────────


class TestSphSyncSocLimits:
    def test_no_mismatch_skips_write(self, sph_ctrl, mock_controller):
        mock_controller.settings["charge_stop_soc"] = 100
        mock_controller.settings["discharge_stop_soc"] = 10
        sph_ctrl.sync_soc_limits(mock_controller)
        assert mock_controller.calls["ac_charge_times"] == []
        assert mock_controller.calls["ac_discharge_times"] == []

    def test_charge_mismatch_syncs(self, sph_ctrl, mock_controller):
        sph_ctrl.battery_settings.max_soc = 90
        sph_ctrl.sync_soc_limits(mock_controller)
        assert len(mock_controller.calls["ac_charge_times"]) == 1
        assert mock_controller.calls["ac_charge_times"][0]["charge_stop_soc"] == 90

    def test_discharge_mismatch_syncs(self, sph_ctrl, mock_controller):
        sph_ctrl.battery_settings.min_soc = 20
        sph_ctrl.sync_soc_limits(mock_controller)
        assert len(mock_controller.calls["ac_discharge_times"]) == 1
        assert (
            mock_controller.calls["ac_discharge_times"][0]["discharge_stop_soc"] == 20
        )


class TestSphReadAndInitializeFromHardware:
    def test_initializes_from_charge_discharge_periods(self, sph_ctrl, mock_controller):
        mock_controller.read_ac_charge_times = lambda: {
            "charge_power": 100,
            "charge_stop_soc": 100,
            "mains_enabled": True,
            "periods": [
                {"start_time": "01:00", "end_time": "05:00", "enabled": True},
            ],
        }
        mock_controller.read_ac_discharge_times = lambda: {
            "discharge_power": 100,
            "discharge_stop_soc": 10,
            "periods": [
                {"start_time": "17:00", "end_time": "21:00", "enabled": True},
            ],
        }
        sph_ctrl.read_and_initialize_from_hardware(mock_controller, current_hour=10)
        assert len(sph_ctrl._charge_periods) == 1
        assert len(sph_ctrl._discharge_periods) == 1
        assert len(sph_ctrl.tou_intervals) == 2

    def test_empty_periods(self, sph_ctrl, mock_controller):
        sph_ctrl.read_and_initialize_from_hardware(mock_controller, current_hour=0)
        assert sph_ctrl._charge_periods == []
        assert sph_ctrl._discharge_periods == []

    def test_disabled_periods_skipped(self, sph_ctrl, mock_controller):
        mock_controller.read_ac_charge_times = lambda: {
            "charge_power": 100,
            "charge_stop_soc": 100,
            "mains_enabled": True,
            "periods": [
                {"start_time": "01:00", "end_time": "05:00", "enabled": False},
            ],
        }
        mock_controller.read_ac_discharge_times = lambda: {
            "discharge_power": 100,
            "discharge_stop_soc": 10,
            "periods": [],
        }
        sph_ctrl.read_and_initialize_from_hardware(mock_controller, current_hour=0)
        assert sph_ctrl._charge_periods == []


# ── InverterController base class (tested via GrowattMinController) ──────────


class TestGetPeriodSettings:
    def test_returns_correct_settings(self, min_ctrl):
        min_ctrl.strategic_intents = ["GRID_CHARGING"] * 4 + ["BATTERY_EXPORT"] * 4
        result = min_ctrl.get_period_settings(0)
        assert result["grid_charge"] is True
        assert result["strategic_intent"] == "GRID_CHARGING"

        result = min_ctrl.get_period_settings(4)
        assert result["grid_charge"] is False
        assert result["strategic_intent"] == "BATTERY_EXPORT"
        assert result["discharge_rate"] == 100

    def test_no_intents_raises(self, min_ctrl):
        with pytest.raises(ValueError):
            min_ctrl.get_period_settings(0)

    def test_out_of_range_raises(self, min_ctrl):
        min_ctrl.strategic_intents = ["IDLE"] * 10
        with pytest.raises(ValueError):
            min_ctrl.get_period_settings(10)

    def test_uses_actual_discharge_rate_when_schedule_available(self, min_ctrl):
        from unittest.mock import MagicMock

        min_ctrl.strategic_intents = ["LOAD_SUPPORT"] * 4
        mock_schedule = MagicMock()
        # 96 periods, LOAD_SUPPORT action at period 0: -1.5 kWh → -6 kW → round(6/15*100)=40
        mock_schedule.actions = [-1.5] + [0.0] * 95
        min_ctrl.current_schedule = mock_schedule
        result = min_ctrl.get_period_settings(0)
        assert result["discharge_rate"] == 40
        assert result["grid_charge"] is False

    def test_falls_back_to_static_dict_when_no_schedule(self, min_ctrl):
        min_ctrl.strategic_intents = ["LOAD_SUPPORT"] * 4
        min_ctrl.current_schedule = None
        result = min_ctrl.get_period_settings(0)
        assert result["discharge_rate"] == 100  # static dict fallback

    def test_action_derived_charge_rate_for_grid_charging(self, min_ctrl):
        from unittest.mock import MagicMock

        min_ctrl.strategic_intents = ["GRID_CHARGING"] * 96
        mock_schedule = MagicMock()
        # 0.17 kWh in 15 min → 0.68 kW → round(0.68 / 15.0 * 100) = 5
        mock_schedule.actions = [0.17] + [0.0] * 95
        min_ctrl.current_schedule = mock_schedule

        result = min_ctrl.get_period_settings(0)
        assert result["charge_rate"] == 5
        assert result["grid_charge"] is True

    def test_grid_charging_full_rate_at_max_action(self, min_ctrl):
        from unittest.mock import MagicMock

        min_ctrl.strategic_intents = ["GRID_CHARGING"] * 96
        mock_schedule = MagicMock()
        # 3.75 kWh in 15 min → 15.0 kW → round(15.0 / 15.0 * 100) = 100
        mock_schedule.actions = [3.75] + [0.0] * 95
        min_ctrl.current_schedule = mock_schedule

        result = min_ctrl.get_period_settings(0)
        assert result["charge_rate"] == 100

    def test_solar_storage_charge_rate_always_100(self, min_ctrl):
        from unittest.mock import MagicMock

        min_ctrl.strategic_intents = ["SOLAR_STORAGE"] * 96
        mock_schedule = MagicMock()
        mock_schedule.actions = [0.5] * 96
        min_ctrl.current_schedule = mock_schedule

        result = min_ctrl.get_period_settings(0)
        assert result["charge_rate"] == 100

    def test_grid_charging_falls_back_to_100_without_schedule(self, min_ctrl):
        min_ctrl.strategic_intents = ["GRID_CHARGING"] * 4
        min_ctrl.current_schedule = None

        result = min_ctrl.get_period_settings(0)
        assert result["charge_rate"] == 100


class TestGetStrategicIntentSummary:
    def test_empty_when_no_intents(self, min_ctrl):
        assert min_ctrl.get_strategic_intent_summary() == {}

    def test_summarizes_by_hour(self, min_ctrl):
        min_ctrl.strategic_intents = (
            ["GRID_CHARGING"] * 4 + ["IDLE"] * 4 + ["BATTERY_EXPORT"] * 4
        )
        summary = min_ctrl.get_strategic_intent_summary()
        assert "GRID_CHARGING" in summary
        assert summary["GRID_CHARGING"]["count"] == 1
        assert 0 in summary["GRID_CHARGING"]["hours"]
        assert "IDLE" in summary
        assert "BATTERY_EXPORT" in summary


class TestApplyPeriod:
    def test_successful_apply(self, min_ctrl, mock_controller):
        success, error = min_ctrl.apply_period(
            mock_controller, grid_charge=True, discharge_rate=50
        )
        assert success is True
        assert error == ""
        assert mock_controller.calls["grid_charge"] == [True]
        assert mock_controller.calls["discharge_rate"] == [50]

    def test_grid_charge_failure_returns_error(self, min_ctrl, mock_controller):
        mock_controller.set_grid_charge = lambda _: (_ for _ in ()).throw(
            RuntimeError("fail")
        )
        success, error = min_ctrl.apply_period(
            mock_controller, grid_charge=True, discharge_rate=0
        )
        assert success is False
        assert "fail" in error


class TestComputeRatesForPeriod:
    def test_grid_charging_intent(self, min_ctrl):
        min_ctrl.strategic_intents = ["GRID_CHARGING"] * 4
        grid_charge, discharge_rate, block_passive_charging = (
            min_ctrl.compute_rates_for_period(0, battery_action_kw=5.0)
        )
        assert grid_charge is True
        assert discharge_rate == 0
        assert block_passive_charging is False

    def test_export_arbitrage_intent(self, min_ctrl):
        min_ctrl.strategic_intents = ["BATTERY_EXPORT"] * 4
        grid_charge, discharge_rate, block_passive_charging = (
            min_ctrl.compute_rates_for_period(0, battery_action_kw=-3.0)
        )
        assert grid_charge is False
        assert discharge_rate > 0
        assert block_passive_charging is True

    def test_export_arbitrage_full_power(self, min_ctrl):
        min_ctrl.strategic_intents = ["BATTERY_EXPORT"] * 4
        _grid_charge, discharge_rate, _block = min_ctrl.compute_rates_for_period(
            0, battery_action_kw=-min_ctrl.max_discharge_power_kw
        )
        assert discharge_rate == 100

    def test_idle_intent(self, min_ctrl):
        min_ctrl.strategic_intents = ["IDLE"] * 4
        grid_charge, discharge_rate, block_passive_charging = (
            min_ctrl.compute_rates_for_period(0, battery_action_kw=0.0)
        )
        assert grid_charge is False
        assert discharge_rate == 0
        assert block_passive_charging is False

    def test_solar_export_intent_blocks_passive_charging(self, min_ctrl):
        min_ctrl.strategic_intents = ["SOLAR_EXPORT"] * 4
        grid_charge, discharge_rate, block_passive_charging = (
            min_ctrl.compute_rates_for_period(0, battery_action_kw=0.0)
        )
        assert grid_charge is False
        assert discharge_rate == 0
        assert block_passive_charging is True

    def test_solar_storage_intent_allows_passive_charging(self, min_ctrl):
        min_ctrl.strategic_intents = ["SOLAR_STORAGE"] * 4
        grid_charge, discharge_rate, block_passive_charging = (
            min_ctrl.compute_rates_for_period(0, battery_action_kw=0.0)
        )
        assert grid_charge is False
        assert discharge_rate == 0
        assert block_passive_charging is False

    def test_load_support_partial_discharge(self, min_ctrl):
        # 1.5 kW of 15.0 kW max → 10%
        min_ctrl.strategic_intents = ["LOAD_SUPPORT"] * 4
        grid_charge, discharge_rate, _block = min_ctrl.compute_rates_for_period(
            0, battery_action_kw=-1.5
        )
        assert grid_charge is False
        assert discharge_rate == 10

    def test_load_support_full_discharge(self, min_ctrl):
        min_ctrl.strategic_intents = ["LOAD_SUPPORT"] * 4
        _grid_charge, discharge_rate, _block = min_ctrl.compute_rates_for_period(
            0, battery_action_kw=-min_ctrl.max_discharge_power_kw
        )
        assert discharge_rate == 100

    def test_load_support_zero_action(self, min_ctrl):
        min_ctrl.strategic_intents = ["LOAD_SUPPORT"] * 4
        _grid_charge, discharge_rate, _block = min_ctrl.compute_rates_for_period(
            0, battery_action_kw=0.0
        )
        assert discharge_rate == 0


class TestSimulatorMapRates:
    """_map_rates must mirror _map_intent_to_rates for every intent."""

    def _settings(self):
        return BatterySettings()

    def test_load_support_partial(self):
        from core.bess.simulation.inverter_simulator import _map_rates

        grid_charge, rate, charge_rate = _map_rates(
            "LOAD_SUPPORT", -1.5, self._settings()
        )
        assert grid_charge is False
        assert rate == 10  # 1.5 / 15.0 * 100 = 10
        assert charge_rate == 100

    def test_load_support_full(self):
        from core.bess.simulation.inverter_simulator import _map_rates

        s = self._settings()
        grid_charge, rate, charge_rate = _map_rates(
            "LOAD_SUPPORT", -s.max_discharge_power_kw, s
        )
        assert grid_charge is False
        assert rate == 100
        assert charge_rate == 100

    def test_load_support_zero(self):
        from core.bess.simulation.inverter_simulator import _map_rates

        grid_charge, rate, charge_rate = _map_rates(
            "LOAD_SUPPORT", 0.0, self._settings()
        )
        assert grid_charge is False
        assert rate == 0
        assert charge_rate == 100


# ── SolaxController ──────────────────────────────────────────────────────────


class TestSolaxGetDailyTouSettings:
    def test_returns_empty(self, solax_ctrl):
        assert solax_ctrl.get_daily_TOU_settings() == []


class TestSolaxLogSchedule:
    def test_log_no_schedule(self, solax_ctrl):
        solax_ctrl.log_current_TOU_schedule()

    def test_log_with_intents(self, solax_ctrl):
        solax_ctrl.strategic_intents = ["IDLE"] * 96
        solax_ctrl.log_current_TOU_schedule("test header")

    def test_log_detailed_no_schedule(self, solax_ctrl):
        solax_ctrl.log_detailed_schedule()

    def test_log_detailed_with_intents(self, solax_ctrl):
        solax_ctrl.strategic_intents = (
            ["GRID_CHARGING"] * 8
            + ["SOLAR_STORAGE"] * 40
            + ["BATTERY_EXPORT"] * 16
            + ["IDLE"] * 32
        )
        solax_ctrl.log_detailed_schedule("detailed test")


# ── SolaxModbusGrowattController ─────────────────────────────────────────────
