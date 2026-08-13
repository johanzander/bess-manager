"""Historical backfill gap-fills zero-energy periods from InfluxDB power sensors.

Cumulative HA counters (e.g. Growatt lifetime discharge energy) only tick in
0.1 kWh steps. When a real discharge happens but is too small to register in
a period's window, the counter delta reads exactly zero. The historical/
backfill collection path corrects this via InfluxDB power-sensor data
(the gap-filling block in `sensor_collector.py`'s `collect_energy_data`).
Runtime (live) collection gets its own,
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


class TestSharedSignedPowerEntitiesExcluded:
    """A signed sensor backing two flow keys cannot be gap-filled from InfluxDB.

    Native SolaX / Huawei battery power (#542) and Solis / Huawei grid power
    (#475/#438) each publish ONE signed entity that backs two BESS keys.
    InfluxDB returns a period *mean* of that entity, which has already summed
    charge and discharge (or import and export) into a single number — the
    direction is gone and no split can recover it. Worse, entity_to_flow is
    keyed by entity_id, so a shared entity silently resolves to whichever
    flow the map iterates last: charging energy would be recorded as
    battery_discharged. Such entities must be excluded from the InfluxDB
    power path entirely; the live PowerSampleBuffer path (#387) still covers
    them because it reads through the sign-splitting getters.
    """

    @staticmethod
    def _shared_battery_controller():
        entity_map = _entity_map()
        # Both battery keys resolve to the one signed entity, exactly as
        # discover_sensors_from_registry pairs them for solax_modbus_native.
        entity_map["battery_charge_power"] = "solax_battery_power_charge"
        entity_map["battery_discharge_power"] = "solax_battery_power_charge"
        ha = MagicMock()
        ha.resolve_sensor_for_influxdb.side_effect = lambda key: entity_map.get(key)
        ha._resolve_entity_id.return_value = ("soc_entity", None)
        return ha

    def test_shared_signed_entity_excluded_from_power_sensors(self):
        collector = SensorCollector(
            self._shared_battery_controller(), BatterySettings(total_capacity=30.0)
        )
        assert "solax_battery_power_charge" not in collector.power_sensors
        # The unshared ones are untouched.
        assert "pv_power_entity" in collector.power_sensors
        assert "import_power_entity" in collector.power_sensors

    def test_shared_signed_entity_maps_to_no_flow(self):
        collector = SensorCollector(
            self._shared_battery_controller(), BatterySettings(total_capacity=30.0)
        )
        entity_to_flow = collector._build_power_entity_to_flow_map()
        assert "sensor.solax_battery_power_charge" not in entity_to_flow
        assert entity_to_flow["sensor.pv_power_entity"] == "solar_production"

    def test_shared_signed_grid_entity_also_excluded(self):
        """Same collision, pre-existing on Solis/Huawei grid power."""
        entity_map = _entity_map()
        entity_map["import_power"] = "solis_grid_power_net"
        entity_map["export_power"] = "solis_grid_power_net"
        ha = MagicMock()
        ha.resolve_sensor_for_influxdb.side_effect = lambda key: entity_map.get(key)
        ha._resolve_entity_id.return_value = ("soc_entity", None)

        collector = SensorCollector(ha, BatterySettings(total_capacity=30.0))
        assert "solis_grid_power_net" not in collector.power_sensors
        assert (
            "sensor.solis_grid_power_net"
            not in collector._build_power_entity_to_flow_map()
        )
