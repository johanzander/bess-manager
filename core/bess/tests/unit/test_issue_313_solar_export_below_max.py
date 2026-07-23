"""Issue #313: the DP conflates two separate decisions into one `power=0`
branch — whether this period's solar surplus bypasses the battery to export
directly, vs. how much *already-stored* SOE to additionally discharge. That
conflation forces a real headroom-creating discharge to happen in whichever
period first needs the room, even when a better-priced, side-effect-free
slot for the same discharge was available earlier in the same horizon.

Root cause and validated fix: docs/superpowers/specs/2026-07-16-issue-313-root-cause-investigation.md.

Fix: the DP now always considers a `SOLAR_EXPORT`-below-max candidate
(battery SOE unchanged, solar exports directly) as a genuine alternative to
IDLE's forced passive charge, whenever doing so preserves headroom that's
worth more than the value of storing this period's own solar.
`_compute_reward`/`_build_period_data` already produce the correct
economics for this state when given `next_soe == soe` (see
`test_surplus_disposition.py::test_idle_exports_when_battery_full`, which
documents the same reward shape at soe==max_soe) — the fix makes it
reachable below max_soe too. Since this can only ever match or beat what
IDLE alone could do (it's an additional candidate in the same max()), the
change is validated by running it against the full existing test/scenario
suite: no regressions, only neutral-or-improved results (see
`./scripts/quality-check.sh` and `.venv/bin/pytest -m slow` runs recorded in
the PR).

Frank's real 2-day trace from issue #126/#313 is covered as a proper
scenario fixture (`core/bess/tests/unit/data/realworld_2026_07_13_155212.json`,
run automatically by `test_scenarios.py::test_all_scenarios`), not
duplicated here -- this file only covers the isolated unit-level behavior of
the new DP candidate itself.
"""

import numpy as np

from core.bess.dp_battery_algorithm import (
    _best_action_at_continuous_state,
    _discretize_state_action_space,
)
from core.bess.tests.helpers import make_battery_settings


def test_best_action_prefers_solar_bypass_when_stored_energy_has_no_future_value():
    """Isolated unit-level test of the new candidate, avoiding any confound
    with discharge-timing decisions: soe starts at the floor (nothing
    available to discharge), and V_next is flat zero everywhere (no future
    benefit from holding more energy -- e.g. end of horizon). With solar
    surplus available and room to store it, IDLE would passively charge for
    zero benefit (cycle_cost=0, so no cost either, but no gain); bypassing
    and exporting the same surplus now earns real revenue at sell_price.
    Bypass must strictly win.
    """
    bs = make_battery_settings(
        total_capacity=10.0,
        min_soc=20.0,  # min_soe_kwh = 2.0
        max_soc=100.0,  # max_soe_kwh = 10.0
        max_charge_power_kw=20.0,
        max_discharge_power_kw=20.0,
        efficiency_charge=1.0,
        efficiency_discharge=1.0,
        cycle_cost_per_kwh=0.0,
    )
    soe_levels, power_levels = _discretize_state_action_space(bs)
    v_next = np.zeros(len(soe_levels))

    soe = bs.min_soe_kwh  # 2.0 -- nothing available to discharge
    home_consumption = [0.0]
    solar_production = [5.0]  # surplus fits within the 8.0 kWh of room
    buy_price = [0.1]
    sell_price = [0.1]

    action, next_soe, _, reward = _best_action_at_continuous_state(
        soe=soe,
        t=0,
        V_next=v_next,
        power_levels=power_levels,
        home_consumption=home_consumption,
        battery_settings=bs,
        dt=1.0,
        solar_production=solar_production,
        buy_price=buy_price,
        sell_price=sell_price,
        cost_basis=0.0,
        max_charge_power_per_period=None,
    )

    assert action == 0.0
    assert next_soe == soe, (
        f"Expected battery untouched (bypass), got next_soe={next_soe} "
        f"(started at soe={soe})"
    )
    assert round(reward, 4) == round(5.0 * 0.1, 4), (
        f"Expected the full 5.0 kWh solar surplus exported at sell_price=0.1 "
        f"(reward=0.5), got {reward:.4f}"
    )
