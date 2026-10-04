"""An unavailable battery SOC sensor fails explicitly, naming the cause (#792).

When the recorder has no SOC sample, `collect_energy_data` falls back to the
live SOC from HA. `get_battery_soc()` returns None (it does not raise) when the
sensor is `unknown`/`unavailable`, so a None must be rejected at the fallback
instead of being stored as a reading and surfacing later as a raw
`'<=' not supported between instances of 'int' and 'NoneType'` TypeError.

No execution model applies here: this is a data-collection error path, not a
schedule/control mapping, so the outcome asserted is the raised error itself.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from core.bess.sensor_collector import SensorCollector
from core.bess.settings import BatterySettings

_ENERGY_READINGS = {
    "battery_charged_entity": 100.0,
    "battery_discharged_entity": 50.0,
    "solar_entity": 200.0,
    "import_entity": 300.0,
    "export_entity": 10.0,
}

_ENTITY_MAP = {
    "lifetime_battery_charged": "battery_charged_entity",
    "lifetime_battery_discharged": "battery_discharged_entity",
    "lifetime_solar_energy": "solar_entity",
    "lifetime_import_from_grid": "import_entity",
    "lifetime_export_to_grid": "export_entity",
    "battery_soc": "soc_entity",
}


def _collector_with_unavailable_soc() -> SensorCollector:
    ha = MagicMock()
    ha.resolve_sensor_for_influxdb.side_effect = lambda key: _ENTITY_MAP.get(key)
    ha._resolve_entity_id.return_value = ("soc_entity", None)
    ha.get_battery_soc.return_value = None  # sensor is unknown/unavailable
    return SensorCollector(ha, BatterySettings(total_capacity=30.0))


@pytest.mark.parametrize(
    "recorder_has_soc_for",
    [
        pytest.param("previous", id="end-soc-missing"),
        pytest.param("current", id="start-soc-missing"),
    ],
)
def test_unavailable_soc_fallback_raises_naming_the_sensor(
    recorder_has_soc_for: str,
) -> None:
    collector = _collector_with_unavailable_soc()

    with_soc = {**_ENERGY_READINGS, "soc_entity": 45.0}
    without_soc = dict(_ENERGY_READINGS)
    # _get_period_readings is called for the current period, then the previous.
    readings = (
        [without_soc, with_soc]
        if recorder_has_soc_for == "previous"
        else [with_soc, without_soc]
    )
    collector._get_period_readings = MagicMock(side_effect=readings)  # type: ignore[method-assign]

    with patch("core.bess.sensor_collector.time_utils") as mock_time_utils:
        mock_time_utils.now.return_value.hour = 3
        mock_time_utils.now.return_value.minute = 0  # current_period = 12
        mock_time_utils.today.return_value = date(2026, 7, 25)

        # period=5 < current_period-1 -> historical backfill branch.
        with pytest.raises(KeyError, match=r"Period 5.*SOC.*soc_entity.*unavailable"):
            collector.collect_energy_data(5)
