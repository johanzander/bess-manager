"""The intra-period discharge gate has an economic consequence (#526, #520).

Audit Pass 3, finding F2: forcing `intra_period_discharge_allowed = True` on
every period left every pinned instrument green -- the goldens, the
`test_scenarios` corpus, the strict R == P check and the VPP baseline. The gate
is now pinned per period in the goldens, but a pinned flag is only worth
something if the flag does work, and none of the existing tests demonstrate
that at the level of realized money.

Why nothing showed it: the gate does not change the *planned* energy. It sets
the ceiling the inverter may use when the actual sub-period load exceeds the
forecast, and the corpus is 15-minute point forecasts, where actual == forecast
by construction. `vpp_simulator`'s own docstring makes the same point -- it can
model the gate's cost but never its benefit. So the consequence only becomes
observable once execution is driven against a load the plan did not predict,
which is what this module does.

This is the "assert the outcome, not the command" rule applied to the gate: the
assertions below are on realized cost and delivered energy, not on the rate
written to the register.
"""

import pytest

from core.bess.simulation.inverter_simulator import (
    derive_control_command,
    simulate,
)
from core.bess.tests.helpers import make_battery_settings

pytestmark = pytest.mark.slow


def _run(allowed: bool, actual_home: float) -> object:
    """Execute one SOLAR_EXPORT period against a load the plan did not predict.

    Deliberately routed through `derive_control_command` rather than by handing
    `simulate` a rate directly: the ceiling has to be produced by the real
    `_gated_discharge_rate` -> `intra_period_discharge_gate` path, or this
    tests the simulator's load-first behaviour instead of the gate, and a gate
    reduced to a no-op would sail straight through it.

    The planned discharge is 0.0 kW on both branches -- the gate moves only the
    ceiling, never the plan.
    """
    settings = make_battery_settings()
    command = derive_control_command(
        "SOLAR_EXPORT",
        0.0,
        settings,
        intra_period_discharge_allowed=allowed,
    )
    return simulate(
        [command],
        solar_production=[0.0],
        home_consumption=[actual_home],
        buy_price=[2.0],
        sell_price=[0.5],
        initial_soe=10.0,
        settings=settings,
        dt=1.0,
    )


def test_open_gate_covers_an_unforecast_deficit_from_the_battery():
    """Gate open: the battery serves load the plan never predicted, so the
    deficit is not imported."""
    sim = _run(allowed=True, actual_home=2.0)
    period = sim.period_data[0]

    assert period.energy.battery_discharged == pytest.approx(2.0, abs=1e-6), (
        "an authorized period must let the battery cover the actual deficit; "
        f"it discharged {period.energy.battery_discharged:.4f} kWh"
    )
    assert period.energy.grid_imported == pytest.approx(0.0, abs=1e-6), (
        "nothing should be imported while the battery is authorized and has "
        f"reserve; imported {period.energy.grid_imported:.4f} kWh"
    )


def test_closed_gate_holds_the_reserve_and_buys_the_deficit_instead():
    """Gate closed: identical plan, identical load, but the reserve is held
    and the same energy is bought from the grid."""
    sim = _run(allowed=False, actual_home=2.0)
    period = sim.period_data[0]

    assert period.energy.battery_discharged == pytest.approx(0.0, abs=1e-6), (
        "a period the DP declined to authorize must not discharge; it "
        f"discharged {period.energy.battery_discharged:.4f} kWh"
    )
    assert period.energy.grid_imported == pytest.approx(2.0, abs=1e-6), (
        "the held deficit has to be bought; imported "
        f"{period.energy.grid_imported:.4f} kWh"
    )


def test_the_gate_decision_moves_realized_cost_and_stored_energy():
    """The two branches are not economically equivalent.

    This fails if the gate is reduced to a no-op: measured 2026-08-11, making
    `intra_period_discharge_gate` return 100 unconditionally fails 2 of the 3
    tests here.

    It does *not* fail under Pass 3's F2 mutation (the DP forcing
    `intra_period_discharge_allowed = True` on every period) -- verified, all 3
    stay green -- because this module never runs the DP. That half is caught by
    the `intra_period_discharge_allowed` sequence pinned in the action-selector
    goldens, which the same mutation turns red on 29 of 36 fixtures. The two
    are deliberately complementary: the goldens pin *what the DP decided*, this
    pins *that the decision is worth deciding*. Neither alone covers the gate.
    """
    opened = _run(allowed=True, actual_home=2.0)
    closed = _run(allowed=False, actual_home=2.0)

    # 2 kWh bought at 2.0 SEK/kWh rather than taken from a battery that was
    # already holding it.
    cost_delta = closed.realized_cost - opened.realized_cost
    assert cost_delta == pytest.approx(4.0, abs=1e-6), (
        "holding the reserve must cost the price of importing the deficit; "
        f"closed={closed.realized_cost:.4f} open={opened.realized_cost:.4f} "
        f"delta={cost_delta:+.4f} SEK"
    )

    soe_open = opened.period_data[0].energy.battery_soe_end
    soe_closed = closed.period_data[0].energy.battery_soe_end
    assert soe_closed > soe_open, (
        "the closed gate is what retains the energy -- if both branches end "
        f"at the same SoE the gate did nothing (open={soe_open:.4f}, "
        f"closed={soe_closed:.4f})"
    )
