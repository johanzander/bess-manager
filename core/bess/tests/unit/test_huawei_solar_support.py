import logging
from unittest.mock import Mock

import pytest

from core.bess.battery_system_manager import BatterySystemManager
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.huawei_sensor_transform import (
    HuaweiPowerSnapshot,
    normalize_huawei_power,
    parse_ha_numeric_power,
)
from core.bess.huawei_solar_controller import HuaweiSolarController
from core.bess.sensor_collector import SensorCollector
from core.bess.settings import BatterySettings


def test_huawei_platform_is_valid_and_controller_created():
    manager = BatterySystemManager(
        controller=Mock(),
        price_source=Mock(),
        addon_options={"inverter": {"platform": "huawei_solar"}},
    )
    assert "huawei_solar" in BatterySystemManager.VALID_PLATFORMS
    assert isinstance(manager._inverter_controller, HuaweiSolarController)


def test_huawei_controller_no_write_calls():
    controller = HuaweiSolarController(BatterySettings())
    ha = Mock()

    assert controller.write_schedule_to_hardware(ha, 0, []) == (0, 0)
    assert controller._write_period_to_hardware(ha, True, 100) == (True, "")
    controller.sync_soc_limits(ha)

    ha.assert_not_called()


@pytest.mark.parametrize(
    "raw,charge,discharge", [(1500, 1500, 0), (-1200, 0, 1200), (0, 0, 0)]
)
def test_huawei_battery_normalization(raw, charge, discharge):
    normalized = normalize_huawei_power(HuaweiPowerSnapshot(battery_power_w=raw))
    assert normalized.battery_charge_power == charge
    assert normalized.battery_discharge_power == discharge


@pytest.mark.parametrize("raw,imp,exp", [(-800, 800, 0), (600, 0, 600), (0, 0, 0)])
def test_huawei_grid_normalization(raw, imp, exp):
    normalized = normalize_huawei_power(HuaweiPowerSnapshot(grid_power_w=raw))
    assert normalized.import_power == imp
    assert normalized.export_power == exp


def test_huawei_house_load_formula_examples():
    first = normalize_huawei_power(
        HuaweiPowerSnapshot(pv_power_w=5000, grid_power_w=-1000, battery_power_w=2000)
    )
    assert first.local_load_power == 4000

    second = normalize_huawei_power(
        HuaweiPowerSnapshot(pv_power_w=3000, grid_power_w=500, battery_power_w=-1000)
    )
    assert second.local_load_power == 3500


def test_huawei_house_load_tolerance_and_significant_warning(caplog):
    small = normalize_huawei_power(
        HuaweiPowerSnapshot(pv_power_w=1000, grid_power_w=1001, battery_power_w=0),
        load_tolerance_w=5,
    )
    assert small.local_load_power == 0
    assert small.diagnostic_warning is None

    with caplog.at_level(logging.WARNING):
        significant = normalize_huawei_power(
            HuaweiPowerSnapshot(pv_power_w=1000, grid_power_w=1200, battery_power_w=0),
            load_tolerance_w=5,
        )
    assert significant.local_load_power == 0
    assert significant.diagnostic_warning is not None
    assert "significantly negative" in caplog.text


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        (1500, "W", 1500),
        (1.5, "kW", 1500),
        ("unknown", "W", None),
        ("unavailable", "W", None),
        (None, "W", None),
        ("", "W", None),
        ("not-a-number", "W", None),
    ],
)
def test_huawei_parse_units_and_invalid_values(value, unit, expected):
    assert parse_ha_numeric_power(value, unit) == expected


def test_huawei_registry_discovery_detects_integration_and_raw_sensors():
    ha = HomeAssistantAPIController("http://ha", "token")
    entities = [
        {
            "platform": "huawei_solar",
            "entity_id": "sensor.batteries_state_of_capacity",
            "unique_id": "batteries_state_of_capacity",
        },
        {
            "platform": "huawei_solar",
            "entity_id": "sensor.batteries_charge_discharge_power",
            "unique_id": "batteries_charge_discharge_power",
        },
        {
            "platform": "huawei_solar",
            "entity_id": "sensor.power_meter_active_power",
            "unique_id": "power_meter_active_power",
        },
        {
            "platform": "huawei_solar",
            "entity_id": "sensor.inverter_input_power",
            "unique_id": "inverter_input_power",
        },
    ]

    detected = ha.detect_inverter_integrations(entities)
    platform_sensors, platform = ha.discover_sensors_from_registry(entities)

    assert detected["huawei_solar"] is True
    assert platform == "huawei_solar"
    assert platform_sensors["huawei_solar"] == {
        "battery_soc": "sensor.batteries_state_of_capacity",
        "huawei_battery_power": "sensor.batteries_charge_discharge_power",
        "huawei_grid_power": "sensor.power_meter_active_power",
        "pv_power": "sensor.inverter_input_power",
    }


def test_huawei_history_signed_power_split_and_load_formula():
    ha = Mock()
    ha.sensors = {
        "huawei_battery_power": "sensor.battery",
        "huawei_grid_power": "sensor.grid",
        "pv_power": "sensor.pv",
    }
    collector = SensorCollector(ha, BatterySettings())

    flows = collector._normalize_huawei_power_flows(
        {
            "huawei_battery_power": -0.3,
            "huawei_grid_power": -0.2,
            "huawei_pv_power": 1.0,
        }
    )

    assert flows["battery_charged"] == 0
    assert flows["battery_discharged"] == pytest.approx(0.3)
    assert flows["import_from_grid"] == pytest.approx(0.2)
    assert flows["export_to_grid"] == 0
    assert flows["load_consumption"] == pytest.approx(1.5)


def _huawei_controller_with_states(states):
    ha = HomeAssistantAPIController(
        "http://ha",
        "token",
        sensor_config={
            "huawei_battery_power": "sensor.battery",
            "huawei_grid_power": "sensor.grid",
            "pv_power": "sensor.pv",
            "huawei_house_load_power_entity": "sensor.house_load",
        },
    )

    def fake_api(method, path, **kwargs):
        entity_id = path.rsplit("/", 1)[-1]
        return states[entity_id]

    ha._api_request = fake_api
    return ha


def test_huawei_direct_house_load_sensor_w_is_used():
    ha = _huawei_controller_with_states(
        {
            "sensor.battery": {
                "state": "200",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.grid": {
                "state": "-100",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.pv": {"state": "1000", "attributes": {"unit_of_measurement": "W"}},
            "sensor.house_load": {
                "state": "1234",
                "attributes": {"unit_of_measurement": "W"},
            },
        }
    )

    assert ha.get_local_load_power() == 1234


def test_huawei_direct_house_load_sensor_kw_is_used_as_watts():
    ha = _huawei_controller_with_states(
        {
            "sensor.battery": {
                "state": "200",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.grid": {
                "state": "-100",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.pv": {"state": "1000", "attributes": {"unit_of_measurement": "W"}},
            "sensor.house_load": {
                "state": "1.25",
                "attributes": {"unit_of_measurement": "kW"},
            },
        }
    )

    assert ha.get_local_load_power() == 1250


@pytest.mark.parametrize("state", ["unavailable", "not-a-number"])
def test_huawei_invalid_direct_house_load_falls_back_to_calculated(state, caplog):
    ha = _huawei_controller_with_states(
        {
            "sensor.battery": {
                "state": "200",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.grid": {
                "state": "-100",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.pv": {"state": "1000", "attributes": {"unit_of_measurement": "W"}},
            "sensor.house_load": {
                "state": state,
                "attributes": {"unit_of_measurement": "W"},
            },
        }
    )

    with caplog.at_level(logging.WARNING):
        assert ha.get_local_load_power() == 900
    assert "falling back to calculated house load" in caplog.text


def test_huawei_no_direct_house_load_preserves_calculated_behavior():
    ha = HomeAssistantAPIController(
        "http://ha",
        "token",
        sensor_config={
            "huawei_battery_power": "sensor.battery",
            "huawei_grid_power": "sensor.grid",
            "pv_power": "sensor.pv",
        },
    )

    def fake_api(method, path, **kwargs):
        entity_id = path.rsplit("/", 1)[-1]
        return {
            "sensor.battery": {
                "state": "200",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.grid": {
                "state": "-100",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.pv": {"state": "1000", "attributes": {"unit_of_measurement": "W"}},
        }[entity_id]

    ha._api_request = fake_api

    assert ha.get_local_load_power() == 900


def test_huawei_house_load_sensor_not_required_by_health_validation():
    ha = HomeAssistantAPIController(
        "http://ha",
        "token",
        sensor_config={
            "battery_soc": "sensor.soc",
            "huawei_battery_power": "sensor.battery",
            "huawei_grid_power": "sensor.grid",
            "pv_power": "sensor.pv",
        },
    )

    info = ha.get_method_sensor_info("get_local_load_power")

    assert info["status"] == "ok"
    assert "huawei_house_load_power_entity" not in info["entity_id"]


def test_huawei_history_direct_house_load_overrides_formula():
    ha = Mock()
    ha.sensors = {
        "huawei_battery_power": "sensor.battery",
        "huawei_grid_power": "sensor.grid",
        "pv_power": "sensor.pv",
        "huawei_house_load_power_entity": "sensor.house_load",
    }
    collector = SensorCollector(ha, BatterySettings())

    flows = collector._normalize_huawei_power_flows(
        {
            "huawei_battery_power": 0.2,
            "huawei_grid_power": -0.1,
            "huawei_pv_power": 1.0,
            "huawei_house_load_power": 0.42,
        }
    )

    assert flows["load_consumption"] == pytest.approx(0.42)


def test_huawei_direct_house_load_display_uses_configured_entity():
    ha = _huawei_controller_with_states(
        {
            "sensor.battery": {
                "state": "200",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.grid": {
                "state": "-100",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.pv": {"state": "1000", "attributes": {"unit_of_measurement": "W"}},
            "sensor.house_load": {
                "state": "1234",
                "attributes": {"unit_of_measurement": "W"},
            },
        }
    )

    info = ha.get_method_sensor_info("get_local_load_power")

    assert info["status"] == "ok"
    assert info["entity_id"] == "sensor.house_load"
    assert info["current_value"] == 1234
    assert info["resolution_method"] == "huawei_direct_house_load"


def test_huawei_direct_house_load_exposed_as_internal_local_load_power():
    ha = _huawei_controller_with_states(
        {
            "sensor.battery": {
                "state": "200",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.grid": {
                "state": "-100",
                "attributes": {"unit_of_measurement": "W"},
            },
            "sensor.pv": {"state": "1000", "attributes": {"unit_of_measurement": "W"}},
            "sensor.house_load": {
                "state": "1234",
                "attributes": {"unit_of_measurement": "W"},
            },
        }
    )
    collector = SensorCollector(ha, BatterySettings())

    assert ha.resolve_sensor_for_influxdb("local_load_power") == "house_load"
    assert (
        collector.power_sensor_flow_map["local_load_power"] == "huawei_house_load_power"
    )
    assert "huawei_house_load_power_entity" not in collector.power_sensor_flow_map


def test_influxdb_7d_avg_accepts_huawei_direct_house_load(monkeypatch):
    ha = HomeAssistantAPIController(
        "http://ha",
        "token",
        sensor_config={
            "huawei_battery_power": "sensor.battery",
            "huawei_grid_power": "sensor.grid",
            "pv_power": "sensor.pv",
            "huawei_house_load_power_entity": "sensor.house_load",
        },
    )
    manager = BatterySystemManager(controller=ha, price_source=Mock())
    captured = []

    def fake_get_power_sensor_data_batch(sensors, target_date):
        captured.append(sensors)
        return {
            "status": "success",
            "data": {period: {"sensor.house_load": 0.25} for period in range(96)},
        }

    monkeypatch.setattr(
        "core.bess.battery_system_manager.get_power_sensor_data_batch",
        fake_get_power_sensor_data_batch,
    )

    forecast = manager._get_influxdb_7d_avg_forecast()

    assert captured
    assert all(sensors == ["house_load"] for sensors in captured)
    assert forecast == [0.25] * 96


def test_huawei_missing_lifetime_energy_sensors_are_not_critical():
    ha = HomeAssistantAPIController(
        "http://ha",
        "token",
        sensor_config={
            "battery_soc": "sensor.soc",
            "huawei_battery_power": "sensor.battery",
            "huawei_grid_power": "sensor.grid",
            "pv_power": "sensor.pv",
        },
    )
    collector = SensorCollector(ha, BatterySettings())

    health = collector.check_energy_health()

    assert health["required"] is False
    assert health["status"] == "OK"
    assert {check["status"] for check in health["checks"]} == {"SKIPPED"}
