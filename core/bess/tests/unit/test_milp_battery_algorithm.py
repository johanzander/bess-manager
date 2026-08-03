"""Core-model acceptance test for the #450 MILP pivot (build-phase slice 1).

Validates the generalized MILP core (modes, SOE recursion, self-throttle,
wear, terminal value) against the same #450 fixture the feasibility spike
used (docs/superpowers/specs/2026-08-03-milp-spike-450.py), which is itself
pinned against the exact-PWL reference implementation
(core/bess/dp_battery_algorithm.py) on this branch.

Scope of this slice only: continuous discharge rate (no re-integerization
yet), buy > sell > 0 assumed (no negative-sell export binary yet), no
below-floor/AC-clip/per-period-cap semantics yet -- see
docs/superpowers/specs/2026-08-03-milp-optimizer-pivot-450.md for the full
remaining build list.
"""

import json
import os

import pytest

from core.bess.milp_battery_algorithm import solve_milp_schedule

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "data", "regression_2026_08_02_043728.json"
)


def _load_fixture():
    with open(_FIXTURE) as f:
        return json.load(f)


def test_matches_spike_continuous_rate_optimum():
    """Continuous-rate MILP core must reproduce the feasibility spike's
    validated optimum (-6.0309207) and the #450 window (BYPASS then three
    charges, SOE 2.0 -> 3.222 -> 4.444 -> 5.666), not just solve to
    *a* feasible optimum."""
    sc = _load_fixture()

    result = solve_milp_schedule(
        buy_price=sc["buy_price"],
        sell_price=sc["sell_price"],
        home_consumption=sc["home_consumption"],
        solar_production=sc["solar_production"],
        battery=sc["battery"],
        dt=sc["period_duration_hours"],
    )

    assert result.status == "optimal"
    assert result.cost == pytest.approx(-6.0309207, abs=1e-4)

    # #450 window: index 35 (13:15) is IDLE (passive solar charge), not
    # STORE -- the cheaper window the DP must pick per the regression test.
    assert result.soe[35] == pytest.approx(2.0, abs=1e-3)
    assert result.soe[36] == pytest.approx(3.222, abs=1e-2)
    assert result.soe[37] == pytest.approx(4.444, abs=1e-2)
    assert result.soe[38] == pytest.approx(5.666, abs=1e-2)


def test_terminal_value_reduces_reported_cost():
    """A positive terminal_value_per_kwh must credit the final SOE above
    the floor -- sanity check on sign/direction before this term is relied
    on by later slices (shadow prices, production wiring)."""
    sc = _load_fixture()
    kwargs = {
        "buy_price": sc["buy_price"],
        "sell_price": sc["sell_price"],
        "home_consumption": sc["home_consumption"],
        "solar_production": sc["solar_production"],
        "battery": sc["battery"],
        "dt": sc["period_duration_hours"],
    }

    baseline = solve_milp_schedule(**kwargs)
    credited = solve_milp_schedule(**kwargs, terminal_value_per_kwh=1.0)

    assert credited.cost < baseline.cost
