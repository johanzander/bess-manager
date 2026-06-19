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


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Known control-fidelity gap: battery_first always charges at max rate, "
        "so the per-period SoC trajectory diverges from the optimizer's planned "
        "partial-charge split (7.4 kWh vs 10.0 kWh in P0/P1). "
        "This is the anticipated finding the simulator exists to expose — "
        "do NOT fix by weakening the assertion or patching mode_to_power."
    ),
)
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
