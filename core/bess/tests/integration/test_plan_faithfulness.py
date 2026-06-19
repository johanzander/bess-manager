# core/bess/tests/integration/test_plan_faithfulness.py
import pytest

from core.bess.simulation.verification import verify_plan_faithfulness
from core.bess.tests.helpers import make_battery_settings


def _controlled_scenario():
    """A scenario whose optimal plan uses only faithfully-executable actions:
    night grid-charge at a clear low price, evening discharge-to-grid at a clear
    high price, no fractional solar-storage. dt = 1.0h for simple arithmetic."""
    n = 6
    buy = [0.5, 0.5, 2.0, 2.0, 1.0, 1.0]
    sell = [0.4, 0.4, 1.8, 1.8, 0.9, 0.9]
    solar = [0.0] * n
    home = [0.5] * n
    return buy, sell, solar, home


def test_realized_equals_planned_on_controlled_scenario():
    bs = make_battery_settings()
    buy, sell, solar, home = _controlled_scenario()
    planned_cost, realized_cost, per_period = verify_plan_faithfulness(
        buy_price=buy,
        sell_price=sell,
        solar=solar,
        home=home,
        initial_soe=3.0,
        settings=bs,
        dt=1.0,
    )
    # cent-exact: faithful control reproduces the plan
    assert round(realized_cost, 2) == round(
        planned_cost, 2
    ), f"R={realized_cost} != P={planned_cost}; per-period deltas: {per_period}"


def test_identical_command_sequences_have_zero_delta():
    from core.bess.simulation.inverter_simulator import ControlCommand
    from core.bess.simulation.verification import ab_compare

    bs = make_battery_settings()
    n = 6
    buy = [1.0] * n
    sell = [0.8] * n
    solar = [0.5] * n
    home = [0.3] * n
    base = [ControlCommand("load_first", 0, False)] * n
    delta = ab_compare(
        base, base, solar, home, buy, sell, initial_soe=5.0, settings=bs, dt=1.0
    )
    assert delta == 0.0


def test_solar_storage_mode_stores_all_surplus_not_partial():
    """Diagnostic for the plan-faithfulness finding (see
    docs/investigations/simulator-plan-faithfulness-finding.md).

    SOLAR_STORAGE maps to load_first, which stores ALL available surplus solar.
    The control command carries no charge-power fraction, so the mode cannot
    express the optimizer's planned *partial* solar storage. This is the
    structural source of the R != P gap on solar days; it is asserted here so
    the behaviour is pinned and the finding is visible in the suite.
    """
    from core.bess.simulation.inverter_simulator import (
        ControlCommand,
        mode_to_power,
        simulate,
    )

    bs = make_battery_settings(max_charge_power_kw=10.0)
    cmd = ControlCommand("load_first", discharge_rate_pct=0, grid_charge=False)

    # mode_to_power yields 0 kW (passive); _state_transition then stores surplus.
    assert mode_to_power(cmd, solar=5.0, home=0.5, soe=5.0, settings=bs, dt=1.0) == 0.0

    # Over one hour with 4.5 kWh surplus, load_first stores ~all of it (efficiency
    # adjusted), NOT a small partial amount the optimizer might have planned.
    sim = simulate(
        [cmd],
        solar_production=[5.0],
        home_consumption=[0.5],
        buy_price=[1.0],
        sell_price=[1.0],
        initial_soe=5.0,
        settings=bs,
        dt=1.0,
    )
    stored = sim.period_data[0].energy.battery_soe_end - 5.0
    assert stored > 4.0, (
        f"load_first should store ~all 4.5 kWh surplus, got {stored:.2f}; "
        "the mode cannot express a partial charge"
    )
