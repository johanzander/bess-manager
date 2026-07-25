"""SensorCollector.sample_live_power(): the polling half of the #387 fix.

Called every minute by a new scheduler job (Task 5) to record live power
readings into the rolling buffer that collect_energy_data's runtime branch
(Task 4) later consumes for gap-fill.

Reads the 6 power sensors via their individual live-reading getters on
ha_controller (get_pv_power, get_local_load_power, etc.) rather than the
full-instance `_fetch_all_states()` dump - that method returns every entity
in the user's HA instance and is too heavy to call once a minute (#387 final
review).
"""

from unittest.mock import MagicMock

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


def _make_collector():
    entity_map = _entity_map()
    ha = MagicMock()
    ha.resolve_sensor_for_influxdb.side_effect = lambda key: entity_map.get(key)
    battery_settings = BatterySettings(total_capacity=30.0)
    return SensorCollector(ha, battery_settings)


class TestSampleLivePower:
    def test_records_all_configured_power_sensors_into_the_buffer(self):
        collector = _make_collector()
        collector.ha_controller.get_pv_power.return_value = 1000.0
        collector.ha_controller.get_local_load_power.return_value = 1500.0
        collector.ha_controller.get_import_power.return_value = 0.0
        collector.ha_controller.get_export_power.return_value = 0.0
        collector.ha_controller.get_battery_charge_power.return_value = 0.0
        collector.ha_controller.get_battery_discharge_power.return_value = 500.0

        collector.sample_live_power()
        result = collector._power_sample_buffer.consume(_current_period())

        assert result["solar_production"] == 0.25  # 1000W -> 0.25 kWh
        assert result["battery_discharged"] == 0.125  # 500W -> 0.125 kWh

    def test_skips_a_sensor_whose_getter_raises_without_raising(self):
        collector = _make_collector()
        collector.ha_controller.get_pv_power.side_effect = RuntimeError("unavailable")
        collector.ha_controller.get_local_load_power.return_value = 1500.0
        collector.ha_controller.get_import_power.return_value = 0.0
        collector.ha_controller.get_export_power.return_value = 0.0
        collector.ha_controller.get_battery_charge_power.return_value = 0.0
        collector.ha_controller.get_battery_discharge_power.return_value = 500.0

        collector.sample_live_power()  # must not raise
        result = collector._power_sample_buffer.consume(_current_period())

        assert "solar_production" not in result
        assert result["battery_discharged"] == 0.125

    def test_skips_a_sensor_whose_getter_returns_non_numeric_value(self):
        collector = _make_collector()
        collector.ha_controller.get_pv_power.return_value = "unavailable"
        collector.ha_controller.get_local_load_power.return_value = 1500.0
        collector.ha_controller.get_import_power.return_value = 0.0
        collector.ha_controller.get_export_power.return_value = 0.0
        collector.ha_controller.get_battery_charge_power.return_value = 0.0
        collector.ha_controller.get_battery_discharge_power.return_value = 500.0

        collector.sample_live_power()  # must not raise
        result = collector._power_sample_buffer.consume(_current_period())

        assert "solar_production" not in result
        assert result["battery_discharged"] == 0.125

    def test_noop_when_no_power_sensors_configured(self):
        ha = MagicMock()
        ha.resolve_sensor_for_influxdb.return_value = None
        collector = SensorCollector(ha, BatterySettings(total_capacity=30.0))

        collector.sample_live_power()

        ha.get_pv_power.assert_not_called()

    def test_noop_when_all_getters_fail(self):
        collector = _make_collector()
        collector.ha_controller.get_pv_power.side_effect = RuntimeError("boom")
        collector.ha_controller.get_local_load_power.side_effect = RuntimeError("boom")
        collector.ha_controller.get_import_power.side_effect = RuntimeError("boom")
        collector.ha_controller.get_export_power.side_effect = RuntimeError("boom")
        collector.ha_controller.get_battery_charge_power.side_effect = RuntimeError(
            "boom"
        )
        collector.ha_controller.get_battery_discharge_power.side_effect = RuntimeError(
            "boom"
        )

        collector.sample_live_power()  # must not raise

        assert collector._power_sample_buffer.consume(_current_period()) is None


def _current_period() -> int:
    from core.bess import time_utils

    now = time_utils.now()
    return now.hour * 4 + now.minute // 15
