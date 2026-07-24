"""Historical backfill gap-fills zero-energy periods from InfluxDB power sensors.

Cumulative HA counters (e.g. Growatt lifetime discharge energy) only tick in
0.1 kWh steps. When a real discharge happens but is too small to register in
a period's window, the counter delta reads exactly zero. The historical/
backfill collection path corrects this via InfluxDB power-sensor data
(`sensor_collector.py:244-256`). Runtime (live) collection gets its own,
InfluxDB-free correction via PowerSampleBuffer - see
test_sensor_collector_runtime_gapfill.py (#387).
"""

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


def _make_ha_controller():
    entity_map = _entity_map()
    ha = MagicMock()
    ha.resolve_sensor_for_influxdb.side_effect = lambda key: entity_map.get(key)
    ha._resolve_entity_id.return_value = ("soc_entity", None)
    return ha


class TestHistoricalBackfillGapFill:
    def test_historical_backfill_gap_fills_zero_discharge_from_influxdb(self):
        ha = _make_ha_controller()
        battery_settings = BatterySettings(total_capacity=30.0)
        collector = SensorCollector(ha, battery_settings)

        # Historical path queries InfluxDB for both current and previous
        # period readings - make them identical (zero delta) for period 5.
        identical_readings = {
            "battery_charged_entity": 100.0,
            "battery_discharged_entity": 50.0,
            "solar_entity": 200.0,
            "import_entity": 300.0,
            "export_entity": 10.0,
            "soc_entity": 45.0,
        }

        power_batch_result = {
            "status": "success",
            "data": {5: {"sensor.discharge_power_entity": 0.35}},
        }

        with (
            patch("core.bess.sensor_collector.time_utils") as mock_time_utils,
            patch(
                "core.bess.sensor_collector.get_power_sensor_data_batch",
                return_value=power_batch_result,
            ),
        ):
            mock_time_utils.now.return_value.hour = 3
            mock_time_utils.now.return_value.minute = 0  # current_period = 12
            mock_time_utils.today.return_value = date(2026, 7, 25)

            collector._get_period_readings = MagicMock(
                return_value=dict(identical_readings)
            )

            # period=5 < current_period(12)-1 -> historical backfill branch.
            energy_data = collector.collect_energy_data(5)

        assert energy_data.battery_discharged == 0.35

    def test_runtime_collection_does_not_call_influxdb(self):
        """Runtime collection must never depend on InfluxDB (#387 constraint)."""
        ha = _make_ha_controller()
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

        with (
            patch("core.bess.sensor_collector.time_utils") as mock_time_utils,
            patch(
                "core.bess.sensor_collector.get_power_sensor_data_batch"
            ) as mock_influxdb_power_batch,
        ):
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45  # current_period = 11
            mock_time_utils.today.return_value = date(2026, 7, 25)

            collector.collect_energy_data(10)  # period=10, runtime branch

        mock_influxdb_power_batch.assert_not_called()
