"""Optimization must survive missing InfluxDB historical data.

Historical reconstruction is an optional enhancement. When InfluxDB is
unavailable (e.g. broken by a Home Assistant update), collecting a completed
period's actuals must not abort the schedule update — the optimization runs on
live SOC + forecast. The gap must instead be surfaced via the runtime failure
tracker so the user knows actuals/savings are incomplete.
"""

from unittest.mock import MagicMock, patch

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.exceptions import HistoricalDataUnavailableError


def _make_bsm():
    bsm = BatterySystemManager.__new__(BatterySystemManager)
    bsm.sensor_collector = MagicMock()
    bsm._runtime_failure_tracker = MagicMock()
    bsm.historical_store = MagicMock()
    bsm.historical_store.get_today_periods.return_value = []
    bsm._price_manager = MagicMock()
    bsm.battery_settings = MagicMock(cycle_cost_per_kwh=0.5)
    bsm._log_energy_balance = MagicMock()
    return bsm


class TestMissingHistoricalDataIsNonFatal:
    def test_does_not_raise_when_influxdb_history_unavailable(self):
        bsm = _make_bsm()
        bsm.sensor_collector.collect_energy_data.side_effect = (
            HistoricalDataUnavailableError("no data for period")
        )

        # Must not raise — the schedule update should continue past this point.
        bsm._update_energy_data(period=10, is_first_run=False, prepare_next_day=False)

    def test_surfaces_failure_for_the_user(self):
        bsm = _make_bsm()
        bsm.sensor_collector.collect_energy_data.side_effect = (
            HistoricalDataUnavailableError("no data for period")
        )

        bsm._update_energy_data(period=10, is_first_run=False, prepare_next_day=False)

        bsm._runtime_failure_tracker.record_failure_once.assert_called_once()
        _args, kwargs = bsm._runtime_failure_tracker.record_failure_once.call_args
        assert kwargs["category"] == "HISTORICAL_DATA_UNAVAILABLE"

    def test_does_not_record_actuals_when_history_unavailable(self):
        bsm = _make_bsm()
        bsm.sensor_collector.collect_energy_data.side_effect = (
            HistoricalDataUnavailableError("no data for period")
        )

        bsm._update_energy_data(period=10, is_first_run=False, prepare_next_day=False)

        bsm.historical_store.record_period.assert_not_called()


class TestSuccessfulReconstructionClearsBanner:
    @patch(
        "core.bess.battery_system_manager.infer_intent_from_flows", return_value="IDLE"
    )
    @patch("core.bess.battery_system_manager.EconomicData")
    def test_dismisses_unavailable_banner_on_success(
        self, _economic_data, _infer_intent
    ):
        bsm = _make_bsm()
        energy_data = MagicMock(
            solar_production=1.0,
            home_consumption=2.0,
            battery_soe_start=10.0,
            battery_soe_end=11.0,
            battery_charged=0.5,
            battery_net_change=0.5,
        )
        bsm.sensor_collector.collect_energy_data.return_value = energy_data
        bsm._price_manager.get_available_prices.return_value = ([1.0] * 96, [0.5] * 96)
        bsm._get_planned_intent_for_period = MagicMock(return_value="IDLE")
        bsm.historical_store.get_period.return_value = MagicMock()

        bsm._update_energy_data(period=10, is_first_run=False, prepare_next_day=False)

        bsm._runtime_failure_tracker.dismiss_by_category.assert_any_call(
            "HISTORICAL_DATA_UNAVAILABLE"
        )
        bsm._runtime_failure_tracker.record_failure_once.assert_not_called()
