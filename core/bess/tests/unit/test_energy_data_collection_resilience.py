"""Optimization must survive missing InfluxDB historical data.

Historical reconstruction is an optional enhancement. When InfluxDB is
unavailable (e.g. broken by a Home Assistant update), collecting a completed
period's actuals must not abort the schedule update — the optimization runs on
live SOC + forecast. The gap is surfaced to the user by the dedicated
"Incomplete Historical Data" dashboard banner, so it must NOT also be raised as
a runtime-error alert (that panel is for unexpected, actionable failures).
"""

from unittest.mock import MagicMock

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

    def test_does_not_raise_runtime_error_alert(self):
        bsm = _make_bsm()
        bsm.sensor_collector.collect_energy_data.side_effect = (
            HistoricalDataUnavailableError("no data for period")
        )

        bsm._update_energy_data(period=10, is_first_run=False, prepare_next_day=False)

        # The dedicated dashboard banner already informs the user; do not add a
        # redundant entry to the runtime-error panel.
        bsm._runtime_failure_tracker.record_failure_once.assert_not_called()
        bsm._runtime_failure_tracker.record_failure.assert_not_called()

    def test_does_not_record_actuals_when_history_unavailable(self):
        bsm = _make_bsm()
        bsm.sensor_collector.collect_energy_data.side_effect = (
            HistoricalDataUnavailableError("no data for period")
        )

        bsm._update_energy_data(period=10, is_first_run=False, prepare_next_day=False)

        bsm.historical_store.record_period.assert_not_called()
