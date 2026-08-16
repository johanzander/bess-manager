"""Write the Growatt VPP regression baseline (#539).

The baseline is **v10.0.2's plans executed through today's VPP model**, not
today's plans. That split is deliberate: it holds the execution model fixed
so a failing pin isolates a *planner* change, and it is the only way to reach
the released tag at all — `vpp_simulator` depends on `_period_flows`, which
arrived with Phase 3 and does not exist at v10.0.2, so the tagged code cannot
run today's simulator.

Regenerating the plan half therefore takes two steps and a tag checkout. Do
this on a clean tree -- `git checkout <tag> -- <path>` overwrites the working
copy, so uncommitted work under those paths is lost:

    git status --porcelain          # must be empty before starting
    git checkout v10.0.2 -- core/bess backend ':(exclude)core/bess/tests/unit/data'
    PYTHONPATH=. .venv/bin/python scripts/capture_vpp_baseline.py --plans-only /tmp/plans.json
    git checkout HEAD -- core/bess backend
    git status --short               # the tag carries modules HEAD does not;
    git clean -fd core/bess          # `git reset` them first if they are staged
    PYTHONPATH=. .venv/bin/python scripts/capture_vpp_baseline.py --from-plans /tmp/plans.json

**The fixture exclusion is load-bearing, not tidiness.** The scenario JSON
under `core/bess/tests/unit/data` lives inside `core/bess`, and it changed
substantially between v10.0.2 and now -- 70 files, including `price_data`
(`synthetic_seasonal_winter` went from markup 0.0 / VAT 1.0 / additional 0.0
to 0.08 / 1.25 / 0.773, and `_scenario_inputs` derives buy/sell prices from
exactly those fields). Reverting them means the plan is optimized under the
tag's prices while `simulate_plan` and `capture_plan` execute under today's,
so the baseline compares two different worlds and fixture edits masquerade as
planner drift. An earlier revision of this file did that.

Only regenerate the plan half when deliberately re-baselining against a newer
release. Regenerating it to make a failing test pass discards the very signal
the baseline exists to give.

**Adding a fixture does not need any of that.** A scenario added after the tag
has no v10.0.2 plan and never will, so:

    PYTHONPATH=. .venv/bin/python scripts/capture_vpp_baseline.py --add-new

appends an entry per missing fixture with `plan: null` and today's plan pinned
as `current_plan`. It never touches existing entries.

**A deliberate planner change does not need it either.** When a change moves
what the DP plans, only the `current_plan`/`current` half of each entry is
stale -- the v10.0.2 half is a historical record and must survive untouched,
since the recorded drift between the two halves is the signal
`test_drift_from_the_released_version_is_recorded` exists to hold:

    PYTHONPATH=. .venv/bin/python scripts/capture_vpp_baseline.py --repin-current

rewrites that half only, printing each fixture's realized-cost delta so the PR
can quote the measured VPP movement. It re-simulates every fixture and writes
whenever the plan *or* its execution moved, so it also covers a change to the
VPP model itself, which leaves the plans equal. Before this existed the only
two options
were `--add-new` (a no-op on an unchanged fixture set) and a full re-baseline,
so a legitimate planner change had no supported path and the full re-baseline
-- the one the docstring above warns against -- looked like the remedy.
"""

import argparse
import json
import logging
from pathlib import Path

logging.disable(logging.CRITICAL)

parser = argparse.ArgumentParser()
parser.add_argument("--plans-only", metavar="PATH")
parser.add_argument("--from-plans", metavar="PATH")
parser.add_argument(
    "--add-new",
    action="store_true",
    help="add an entry for each fixture missing from the baseline, pinning "
    "today's plan only (plan: null). The incremental path -- a new fixture "
    "has no v10.0.2 reference and must not trigger a full re-baseline.",
)
parser.add_argument(
    "--repin-current",
    action="store_true",
    help="rewrite only the current_plan/current half of every existing entry, "
    "leaving the v10.0.2 half untouched. For a PR that deliberately changes "
    "what the DP plans; prints the realized-cost delta per fixture.",
)
args = parser.parse_args()

DATA = Path("core/bess/tests/unit/data")

if args.plans_only:
    # Runs against whatever is checked out -- intentionally imports only what
    # exists at v10.0.2.
    from core.bess.tests.helpers import _scenario_inputs, run_scenario

    plans = {}
    for path in sorted(DATA.glob("*.json")):
        scenario = json.loads(path.read_text())
        result = run_scenario(scenario)
        dt = _scenario_inputs(scenario)["period_duration_hours"]
        plans[path.stem] = {
            "intents": [p.decision.strategic_intent for p in result.period_data],
            "actions_kw": [p.decision.battery_action / dt for p in result.period_data],
        }
    Path(args.plans_only).write_text(json.dumps(plans, indent=1))
    print(f"captured {len(plans)} plans")
    raise SystemExit(0)

if not args.from_plans and not args.add_new and not args.repin_current:
    parser.error("pass --plans-only, --from-plans, --add-new or --repin-current")

from core.bess.tests.unit.vpp_capture import (  # noqa: E402
    BASELINE_PATH,
    capture_plan,
    fixture_names,
    simulate_plan,
)

# Mirrors what `test_current_plan_is_pinned` asserts: commands exactly, the
# float arrays at 1e-9. Comparing those exactly instead would re-pin every
# fixture whenever the script runs on a different interpreter than last wrote
# the artefact, since realized cost is reproducible only to ~1e-13 across
# environments (see test_action_selector_parity's module docstring).
VPP_TOLERANCE = 1e-9


def execution_matches(actual, recorded):
    return (
        actual["commands"] == recorded["commands"]
        and abs(actual["realized_cost"] - recorded["realized_cost"]) <= VPP_TOLERANCE
        and all(
            abs(a - b) <= VPP_TOLERANCE
            for a, b in zip(
                actual["soe_trajectory"], recorded["soe_trajectory"], strict=True
            )
        )
    )


if args.repin_current:
    baseline = json.loads(BASELINE_PATH.read_text())
    moved = []
    for name in fixture_names():
        entry = baseline["fixtures"].get(name)
        if entry is None:
            raise SystemExit(
                f"{name} has no baseline entry -- run --add-new first, not this."
            )
        current_plan = capture_plan(name)
        current = simulate_plan(name, current_plan)
        # Both halves, not just the plan: a change that moves the *simulator*
        # leaves every plan equal while the commands/realized-cost/SoE
        # assertions go red, and re-pinning the plan alone would then report
        # "nothing written" -- leaving a full re-baseline, the thing this
        # file's docstring warns against, as the only apparent remedy.
        if current_plan == entry["current_plan"] and execution_matches(
            current, entry["current"]
        ):
            continue
        before = entry["current"]["realized_cost"]
        after = current["realized_cost"]
        moved.append((name, after - before))
        # The v10.0.2 half (`plan`, `commands`, `realized_cost`,
        # `soe_trajectory`) is deliberately not touched.
        entry["current_plan"] = current_plan
        entry["current"] = current
    if not moved:
        print("no fixture's plan changed; nothing written")
        raise SystemExit(0)
    BASELINE_PATH.write_text(json.dumps(baseline, indent=1))
    print(f"re-pinned the current half of {len(moved)} fixture(s):")
    for name, delta in sorted(moved, key=lambda x: -abs(x[1])):
        print(f"  {name:56s} realized_cost {delta:+.4f} SEK")
    raise SystemExit(0)

if args.add_new:
    # A fixture added today has no v10.0.2 plan and never will -- the tag
    # cannot be asked what it would have done with a scenario that did not
    # exist. Pin the half that is meaningful (today's plan and its VPP
    # execution) and record `plan: null` for the half that is not. Without
    # this, adding any fixture fails the baseline tests with a full
    # re-baseline as the only apparent remedy -- which discards the drift
    # signal, exactly what this file's docstring warns against.
    baseline = json.loads(BASELINE_PATH.read_text())
    added = []
    for name in fixture_names():
        if name in baseline["fixtures"]:
            continue
        current_plan = capture_plan(name)
        baseline["fixtures"][name] = {
            "plan": None,
            "commands": None,
            "realized_cost": None,
            "soe_trajectory": None,
            "current_plan": current_plan,
            "current": simulate_plan(name, current_plan),
        }
        added.append(name)
    if not added:
        # Nothing to do -- and rewriting the file anyway would churn the diff
        # of an artefact whose whole value is being hard to change casually.
        print("no fixtures missing from the baseline; nothing written")
        raise SystemExit(0)
    baseline["fixtures"] = dict(sorted(baseline["fixtures"].items()))
    BASELINE_PATH.write_text(json.dumps(baseline, indent=1))
    print(f"added {len(added)} fixture(s) with no v10.0.2 reference: {added}")
    raise SystemExit(0)

released_plans = json.loads(Path(args.from_plans).read_text())
baseline = {
    "_source": "v10.0.2 plans (captured with today's fixtures), plus today's "
    "plans, both executed through the VPP model at the commit that wrote "
    "this file. See scripts/capture_vpp_baseline.py.",
    "fixtures": {},
}
for name, released_plan in sorted(released_plans.items()):
    current_plan = capture_plan(name)
    baseline["fixtures"][name] = {
        # The released reference: what beta does today.
        "plan": released_plan,
        **simulate_plan(name, released_plan),
        # Today's plan, recorded so the planner is pinned on *every* fixture.
        # Without this the drift check could only assert which fixtures had
        # already moved away from v10.0.2, leaving any further regression on
        # the 35 that already moved completely uncovered.
        "current_plan": current_plan,
        "current": simulate_plan(name, current_plan),
    }
BASELINE_PATH.write_text(json.dumps(baseline, indent=1))
print(f"wrote {BASELINE_PATH}: {len(baseline['fixtures'])} fixtures")
