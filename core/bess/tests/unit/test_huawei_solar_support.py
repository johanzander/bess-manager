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
