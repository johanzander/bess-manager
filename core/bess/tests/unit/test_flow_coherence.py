"""Cross-fixture flow-coherence debt pin for #497.

Most detailed-flow invariants hold for every period of every fixture and are
asserted per-period by ``helpers.assert_flow_coherence``, which
``test_all_scenarios`` calls unconditionally for every fixture. Two do not:

- **Every exported kWh has a source.** ``grid_exported`` should equal
  ``solar_to_grid + battery_to_grid``.
- **The home is never oversupplied.** ``solar_to_home + battery_to_home +
  grid_to_home`` should not exceed ``home_consumption``.

Both are violated by the same mechanism (#497): the DP's discharge candidate
grid rounds the exact-cover setpoint up by a fraction of a rate step, the
reward zeroes the resulting export *credit* below 0.01 kWh but leaves the
*energy* untouched, and ``EnergyData._calculate_detailed_flows`` then folds the
orphaned sub-0.1 kWh export back into ``battery_to_home`` (#350). The period
ends up reporting a battery that delivered more to the house than the house
consumed, and an export that came from nowhere.

This module pins the size of that debt rather than asserting it away. The count
below is a measurement of current behavior, not a target:

- It going **up** means a new source of incoherent flows was introduced, and
  the diff that did it should be reconsidered.
- It going **down** means #497 (or something overlapping it) was fixed. Update
  the constant, and once it reaches zero delete this module and move the two
  invariants into ``helpers.assert_flow_coherence`` with the others.

Deliberately a whole-fixture-corpus count rather than a per-scenario assertion:
the number that matters is how much incoherence the optimizer produces overall,
which no single scenario can express.
"""

import functools

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.unit.test_scenarios import (
    get_all_scenario_files,
    load_test_scenario,
)

pytestmark = pytest.mark.slow

TOLERANCE = 1e-6

# Measured on 2026-08-08 at 18bccae4 across 33 fixtures / 1875 periods (182),
# re-measured on 2026-08-08 after regression_2026_08_08_143843 joined the
# corpus (34 fixtures): the 29 additional periods are all that fixture's
# night LOAD_SUPPORT discharges exhibiting the same #497 fold (unsourced
# export == home oversupply, sub-0.1 kWh), verified by
# test_every_incoherent_period_is_the_known_497_fold -- more corpus, not a
# new cause. Re-measured on 2026-08-09 after regression_frank_debug_2026_08_08
# joined the corpus (#501, 35 fixtures): its 1 additional period is the same
# #497 fold, verified per-fixture the same way. Every one of the 212 is the
# #497 fold.
KNOWN_INCOHERENT_PERIODS = 212


def _optimize(scenario_name):
    """Optimize one fixture through the SAME input-derivation path every other
    corpus test uses.

    Deliberately `_scenario_inputs(...)` splatted whole rather than rebuilding
    the kwargs by hand: the hand-built version silently defaulted
    `initial_cost_basis` to 0.0 where the shared path defaults it to
    `cycle_cost`, which put 28 of 33 fixtures on a configuration no other test
    runs. The pinned count below has to be measured under the corpus's normal
    conditions to mean anything.
    """
    return optimize_battery_schedule(
        **_scenario_inputs(load_test_scenario(scenario_name))
    )


def _unsourced_export(e):
    return e.grid_exported - e.solar_to_grid - e.battery_to_grid


def _home_supply_error(e):
    """Signed mismatch between what reached the home and what it consumed.

    Checked two-sided on purpose. Oversupply is the #497 symptom, but
    *under*supply -- a house that consumed energy no flow accounts for -- is
    just as incoherent, and a one-sided check would let it accumulate outside
    the pin while this module still claimed there was no second cause. There
    are zero such periods today.
    """
    return e.solar_to_home + e.battery_to_home + e.grid_to_home - e.home_consumption


@functools.cache
def _incoherent_periods():
    """Every ``(scenario_name, period_data)`` whose export is unsourced or
    whose home supply does not match its consumption.

    Cached: this runs the full 33-fixture optimization corpus, and both tests
    in this module need it.
    """
    found = []
    for name in get_all_scenario_files():
        result = _optimize(name)
        for pd in result.period_data:
            if (
                abs(_unsourced_export(pd.energy)) > TOLERANCE
                or abs(_home_supply_error(pd.energy)) > TOLERANCE
            ):
                found.append((name, pd))
    return tuple(found)


def test_orphan_export_debt_is_not_growing():
    """Pin the #497 incoherent-flow count so it can only shrink."""
    found = _incoherent_periods()

    detail = "\n".join(
        f"  {name} period {pd.period}: "
        f"unsourced_export={_unsourced_export(pd.energy):+.4f} kWh, "
        f"home_supply_error={_home_supply_error(pd.energy):+.4f} kWh"
        for name, pd in found[:10]
    )
    assert len(found) == KNOWN_INCOHERENT_PERIODS, (
        f"Incoherent-flow period count changed: {len(found)} vs the pinned "
        f"{KNOWN_INCOHERENT_PERIODS} (#497).\n"
        f"If it went UP, a change introduced a new source of flows that do not "
        f"add up -- reconsider that diff rather than repinning.\n"
        f"If it went DOWN, #497 was (partly) fixed: update "
        f"KNOWN_INCOHERENT_PERIODS, and at zero delete this module and move "
        f"both invariants into helpers.assert_flow_coherence.\n"
        f"First offenders:\n{detail}"
    )


def test_every_incoherent_period_is_the_known_497_fold():
    """No second cause is hiding inside the pinned count.

    The #497 signature is precise: the battery covered the entire home deficit
    and then some, the whole overshoot got folded into ``battery_to_home`` (so
    ``battery_to_home == battery_discharged`` exactly), and what is left over
    is an export attributed to no source, below the 0.1 kWh fold ceiling.

    If this fails while the count above holds, the corpus has picked up a
    genuinely different incoherence and #497's fix will not clear it.
    """
    fold_ceiling = 0.1 + TOLERANCE
    unexplained = []
    for name, pd in _incoherent_periods():
        e = pd.energy
        unsourced = _unsourced_export(e)
        whole_discharge_went_home = (
            abs(e.battery_to_home - e.battery_discharged) < TOLERANCE
        )
        if not (0 < unsourced <= fold_ceiling and whole_discharge_went_home):
            unexplained.append(
                f"{name} period {pd.period}: unsourced={unsourced:+.4f}, "
                f"battery_to_home={e.battery_to_home:.4f}, "
                f"battery_discharged={e.battery_discharged:.4f}"
            )

    assert not unexplained, (
        f"{len(unexplained)} incoherent period(s) do not match the #497 fold "
        f"signature (whole discharge folded into battery_to_home, leaving a "
        f"positive unsourced export at or below the 0.1 kWh fold ceiling) -- "
        f"a second, unrelated cause:\n  " + "\n  ".join(unexplained[:5])
    )
