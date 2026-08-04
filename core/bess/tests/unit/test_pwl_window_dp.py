import numpy as np
import pytest

from core.bess.pwl_window_dp import (
    _pwl_best_action_at_continuous_state,
    _pwl_eval_array,
    _pwl_prune,
)
from core.bess.settings import BatterySettings


def test_pwl_eval_array_interpolates_between_breakpoints():
    xs = np.array([0.0, 5.0, 10.0])
    vs = np.array([0.0, 10.0, 15.0])
    result = _pwl_eval_array((xs, vs), np.array([2.5, 7.5]))
    assert result[0] == pytest.approx(5.0)
    assert result[1] == pytest.approx(12.5)


def test_pwl_eval_array_extrapolates_below_first_breakpoint():
    xs = np.array([1.0, 2.0])
    vs = np.array([10.0, 20.0])
    result = _pwl_eval_array((xs, vs), np.array([0.0]))
    assert result[0] == pytest.approx(
        0.0
    )  # slope 10/unit, extrapolated down from (1, 10)


def test_pwl_prune_drops_collinear_interior_points():
    xs = np.array([0.0, 1.0, 2.0, 3.0])
    vs = np.array(
        [0.0, 1.0, 2.0, 3.0]
    )  # perfectly linear -- interior points are redundant
    pruned_xs, _pruned_vs = _pwl_prune(xs, vs, eps=1e-9)
    assert len(pruned_xs) == 2
    assert list(pruned_xs) == [0.0, 3.0]


def test_pwl_best_action_at_continuous_state_prefers_idle_when_flat_continuation():
    """With a continuation value function that's flat (indifferent to SOE)
    and zero prices, IDLE should be selected -- no incentive to move energy."""
    battery_settings = BatterySettings()
    xs = np.array([battery_settings.min_soe_kwh, battery_settings.max_soe_kwh])
    vs = np.array([0.0, 0.0])
    soe = (battery_settings.min_soe_kwh + battery_settings.max_soe_kwh) / 2

    action, next_soe, _new_cost_basis, _reward = _pwl_best_action_at_continuous_state(
        soe=soe,
        t=0,
        V_next=(xs, vs),
        power_levels=np.array([]),
        home_consumption=[0.0],
        battery_settings=battery_settings,
        dt=1.0,
        solar_production=[0.0],
        buy_price=[0.0],
        sell_price=[0.0],
        cost_basis=0.0,
        max_charge_power_per_period=None,
    )

    assert action == pytest.approx(0.0)
    assert next_soe == pytest.approx(soe)
