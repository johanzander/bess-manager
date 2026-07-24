"""Runtime collection must gap-fill zero-energy periods from power sensors too.

The cumulative HA counters (e.g. Growatt lifetime discharge energy) only
tick in 0.1 kWh steps. When a real discharge happens but is too small to
register in this period's window, the counter delta reads exactly zero and
the following period absorbs the missed energy once the counter finally
ticks — a "0 -> double" pattern (issue #387). The historical/backfill path
already corrects this via a power-sensor gap-fill
(`sensor_collector.py:241-256`), but it was previously restricted to
`is_historical_backfill` and never applied during runtime (live) collection,
which is the path actually exercised on every 15-minute schedule update.
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

    # Live sensor readings for the just-completed period: every cumulative
    # counter reports the exact same value as the cached previous reading,
    # i.e. a zero delta (the "0" half of the "0 -> double" pattern).
    ha.get_battery_charged_lifetime.return_value = 100.0
    ha.get_battery_discharged_lifetime.return_value = 50.0
    ha.get_solar_production_lifetime.return_value = 200.0
    ha.get_grid_import_lifetime.return_value = 300.0
    ha.get_grid_export_lifetime.return_value = 10.0
    ha.get_battery_soc.return_value = 45.0
    return ha


def _make_collector():
    ha = _make_ha_controller()
    battery_settings = BatterySettings(total_capacity=30.0)
    collector = SensorCollector(ha, battery_settings)

    # Seed the cache with identical cumulative readings so the live-diff
    # delta is exactly zero, forcing the all-energy-zero gap-fill branch.
    collector._last_readings = {
        "battery_charged_entity": 100.0,
        "battery_discharged_entity": 50.0,
        "solar_entity": 200.0,
        "import_entity": 300.0,
        "export_entity": 10.0,
        "soc_entity": 45.0,
    }
    return collector


class TestRuntimeGapFill:
    def test_runtime_collection_gap_fills_zero_discharge_from_power_sensors(self):
        collector = _make_collector()

        power_batch_result = {
            "status": "success",
            "data": {
                10: {
                    "sensor.discharge_power_entity": 0.35,
                }
            },
        }

        with (
            patch("core.bess.sensor_collector.time_utils") as mock_time_utils,
            patch(
                "core.bess.sensor_collector.get_power_sensor_data_batch",
                return_value=power_batch_result,
            ),
        ):
            # current_period = 11 -> collecting the just-completed period 10
            # via the runtime (live-sensor) branch, not historical backfill.
            mock_time_utils.now.return_value.hour = 2
            mock_time_utils.now.return_value.minute = 45
            mock_time_utils.today.return_value = date(2026, 7, 25)

            energy_data = collector.collect_energy_data(10)

        assert energy_data.battery_discharged == 0.35
