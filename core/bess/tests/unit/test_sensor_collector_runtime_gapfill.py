"""Runtime collection gap-fills zero-energy periods from the live power buffer.

Extends the historical-only gap-fill (test_sensor_collector_gapfill.py) with
the InfluxDB-free runtime path: PowerSampleBuffer accumulates live power
samples every minute (SensorCollector.sample_live_power), and
collect_energy_data's runtime branch consumes that period's buffer to
correct a "0 -> double" cumulative-counter misattribution (#387), or to log
a DEBUG comparison when the counter already had a real nonzero delta.
"""

import logging
from datetime import date
from unittest.mock import MagicMock, patch

from core.bess.sensor_collector import SensorCollector
from core.bess.settings import BatterySettings


def _entity_map():
    return {
        "lifetime_battery_charged": "battery_charged_entity",
        "lifetime_battery_discharged": "battery_discharged_entity",
        "lifetime_solar_energy": "solar_entity",
        "lifetime_import_from_grid": "import_entity",
        "lifetime_export_to_grid": "export_entity",
        "battery_soc": "soc_entity",
        "pv_power": "pv_power_entity",
        "local_load_power": "load_power_entity",
        "import_power": "import_power_entity",
        "export_power": "export_power_entity",
        "battery_charge_power": "charge_power_entity",
        "battery_discharge_power": "discharge_power_entity",
    }


def _make_runtime_collector():
    entity_map = _entity_map()
    ha = MagicMock()
    ha.resolve_sensor_for_influxdb.side_effect = lambda key: entity_map.get(key)
    ha._resolve_entity_id.return_value = ("soc_entity", None)
    ha.get_battery_charged_lifetime.return_value = 100.0
    ha.get_battery_discharged_lifetime.return_value = 50.0
    ha.get_solar_production_lifetime.return_value = 200.0
    ha.get_grid_import_lifetime.return_value = 300.0
    ha.get_grid_export_lifetime.return_value = 10.0
    ha.get_battery_soc.return_value = 45.0

    battery_settings = BatterySettings(total_capacity=30.0)
    collector = SensorCollector(ha, battery_settings)
    collector._last_readings = {
        "battery_charged_entity": 100.0,
        "battery_discharged_entity": 50.0,
        "solar_entity": 200.0,
        "import_entity": 300.0,
        "export_entity": 10.0,
        "soc_entity": 45.0,
    }
    return collector


class TestRuntimeGapFillFromBuffer:
    def test_gap_fills_zero_discharge_from_the_live_power_buffer(self):
        collector = _make_runtime_collector()
        # Several small samples averaging to a discharge estimate under the
        # counter's 0.1 kWh resolution ceiling - physically consistent with
        # the counter delta having read exactly zero for this period.
        collector._power_sample_buffer.record(10, {"battery_discharged": 200.0})
        collector._power_sample_buffer.record(10, {"battery_discharged": 300.0})
        collector._power_sample_buffer.record(10, {"battery_discharged": 250.0})

        with patch("core.bess.sensor_collector.time_utils") as mock_time_utils:
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45  # current_period = 11
            mock_time_utils.today.return_value = date(2026, 7, 25)

            energy_data = collector.collect_energy_data(10)

        # mean(200, 300, 250) = 250W * 0.25h / 1000 = 0.0625 kWh
        assert energy_data.battery_discharged == 0.0625

    def test_gap_fill_estimate_is_clamped_to_the_counter_resolution_ceiling(self):
        collector = _make_runtime_collector()
        # A single 1400W sample raw-averages to 0.35 kWh, well above the
        # 0.1 kWh the zero counter delta already proved was the ceiling for
        # this period's true energy - the estimate must be clamped, not
        # written through as-is.
        collector._power_sample_buffer.record(10, {"battery_discharged": 1400.0})

        with patch("core.bess.sensor_collector.time_utils") as mock_time_utils:
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45
            mock_time_utils.today.return_value = date(2026, 7, 25)

            energy_data = collector.collect_energy_data(10)

        assert energy_data.battery_discharged == 0.1 - 0.001

    def test_stays_zero_when_buffer_is_empty(self):
        collector = _make_runtime_collector()
        # No buffer.record() call for period 10 - buffer empty.

        with patch("core.bess.sensor_collector.time_utils") as mock_time_utils:
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45
            mock_time_utils.today.return_value = date(2026, 7, 25)

            energy_data = collector.collect_energy_data(10)

        assert energy_data.battery_discharged == 0.0

    def test_nonzero_counter_delta_wins_over_buffer_and_logs_debug_comparison(
        self, caplog
    ):
        collector = _make_runtime_collector()
        # Give the current live reading a real nonzero discharge delta.
        collector.ha_controller.get_battery_discharged_lifetime.return_value = 55.0
        collector._power_sample_buffer.record(10, {"battery_discharged": 1000.0})

        with (
            patch("core.bess.sensor_collector.time_utils") as mock_time_utils,
            caplog.at_level(logging.DEBUG, logger="core.bess.sensor_collector"),
        ):
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45
            mock_time_utils.today.return_value = date(2026, 7, 25)

            energy_data = collector.collect_energy_data(10)

        # Counter delta (55 - 50 = 5 kWh) wins, not the buffer's 0.25 kWh estimate.
        assert energy_data.battery_discharged == 5.0
        assert any(
            "counter vs power-sample estimate" in record.message
            for record in caplog.records
        )

    def test_buffer_is_always_cleared_after_collect_energy_data(self):
        collector = _make_runtime_collector()
        collector._power_sample_buffer.record(10, {"battery_discharged": 1400.0})

        with patch("core.bess.sensor_collector.time_utils") as mock_time_utils:
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45
            mock_time_utils.today.return_value = date(2026, 7, 25)

            collector.collect_energy_data(10)

        assert collector._power_sample_buffer.consume(10) is None
