"""End-to-end verification for issue #428: an HA-entity-sourced consumption
series with a shaped evening load must change the optimizer's plan, compared
to the same day with a flat series — proving the new seam actually reaches
the DP, not just that parsing produces the right numbers in isolation.

This is the issue's own "Verification" ask: same day, with vs without a
shaped evening load in the supplied series, pinning the SOE trajectory.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from core.bess import time_utils
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.runtime_failure_tracker import RuntimeFailureTracker
from core.bess.settings import BatterySettings


def _session_method_mock(name, return_value=None):
    m = MagicMock(return_value=return_value)
    m.__name__ = name
    return m


def _mock_response(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.content = b'{"ok": true}'
    resp.headers = {"content-type": "application/json"}
    resp.raise_for_status = MagicMock()
    return resp


def _ctrl_with_series(records: list[dict]) -> HomeAssistantAPIController:
    ctrl = HomeAssistantAPIController(
        ha_url="http://ha.local:8123",
        token="test-token",
        sensor_config={"consumption_forecast_series": "sensor.house_load_forecast"},
    )
    ctrl.max_attempts = 1
    ctrl.retry_base_delay = 0
    ctrl.failure_tracker = RuntimeFailureTracker()
    ctrl.session.get = _session_method_mock(
        "get", return_value=_mock_response({"attributes": {"raw_today": records}})
    )
    return ctrl


def _quarter_hour_records(target_date, kwh_per_period=0.3, ev_periods=None, ev_kwh=4.0):
    start = datetime.combine(target_date, datetime.min.time())
    records = []
    ev_periods = ev_periods or set()
    for i in range(96):
        value = ev_kwh if i in ev_periods else kwh_per_period
        records.append(
            {"start": (start + timedelta(minutes=15 * i)).isoformat(), "value": value}
        )
    return records


# Rising evening price curve — cheap overnight, expensive at 20:00 (period 80).
_HOURLY_PRICES = [0.3] * 16 + [1.5, 2.0, 2.5, 3.0] + [1.0] * 4
_QUARTERLY_PRICES = [p for p in _HOURLY_PRICES for _ in range(4)]

_BATTERY_SETTINGS = BatterySettings(
    total_capacity=10.0,
    min_soc=10.0,
    max_soc=100.0,
    max_charge_power_kw=5.0,
    max_discharge_power_kw=5.0,
    efficiency_charge=0.95,
    efficiency_discharge=0.95,
    cycle_cost_per_kwh=0.05,
)


def _optimize(consumption: list[float]):
    zero_solar = [0.0] * 96
    return optimize_battery_schedule(
        buy_price=_QUARTERLY_PRICES,
        sell_price=[p * 0.5 for p in _QUARTERLY_PRICES],
        home_consumption=consumption,
        solar_production=zero_solar,
        initial_soe=1.0,
        battery_settings=_BATTERY_SETTINGS,
        period_duration_hours=0.25,
    )


class TestShapedLoadChangesThePlan:
    def test_ev_block_pulls_more_charge_into_battery_before_peak(self):
        today = time_utils.today()
        # EV session: periods 76-83 (19:00-20:45), squarely inside the price peak.
        ev_periods = set(range(76, 84))

        flat_ctrl = _ctrl_with_series(_quarter_hour_records(today))
        shaped_ctrl = _ctrl_with_series(
            _quarter_hour_records(today, ev_periods=ev_periods)
        )

        flat_consumption = flat_ctrl.get_consumption_forecast_series()
        shaped_consumption = shaped_ctrl.get_consumption_forecast_series()

        assert shaped_consumption[76:84] == pytest.approx([4.0] * 8)
        assert flat_consumption[76:84] == pytest.approx([0.3] * 8)

        flat_result = _optimize(flat_consumption)
        shaped_result = _optimize(shaped_consumption)

        flat_soe_before_peak = flat_result.period_data[75].energy.battery_soe_end
        shaped_soe_before_peak = shaped_result.period_data[75].energy.battery_soe_end

        # Knowing the EV session is coming, the optimizer must charge more
        # ahead of it than it would for a flat baseline with no such signal.
        assert shaped_soe_before_peak > flat_soe_before_peak

        # The shaped run must actually cover more of the EV load from the
        # battery during the session than the flat run's forecast ever could
        # (the flat forecast has no way to know the load exists).
        shaped_discharge_during_ev = sum(
            pd.energy.battery_discharged for pd in shaped_result.period_data[76:84]
        )
        flat_discharge_during_ev = sum(
            pd.energy.battery_discharged for pd in flat_result.period_data[76:84]
        )
        assert shaped_discharge_during_ev > flat_discharge_during_ev
