"""Shared capture path for the Growatt VPP regression baseline (#539).

One definition of "run this fixture and record what VPP would do", used by
both `scripts/capture_vpp_baseline.py` (which writes the baseline) and
`test_vpp_regression_baseline.py` (which re-runs and compares) -- the same
arrangement, and for the same reason, as `golden_capture.py`.

**Why the baseline stores the plan, not just the cost.** The DP's plan and
the VPP execution model are separate things that can each move. Recording
`(strategic_intent, battery_action)` per period alongside the realized cost
means a failing pin says *which* changed: a plan difference points at the
optimizer, a cost-only difference points at the simulator or the command
mapping. A cost-only baseline would leave that to guesswork.

**This also makes the v10.0.2 baseline possible at all.** `vpp_simulator`
depends on `_period_flows`, which does not exist at v10.0.2 (it arrived with
Phase 3), so the tagged code cannot run today's simulator. Capturing the
plan at the tag and simulating it with today's model sidesteps that
entirely, and is the more useful split anyway: it holds the execution model
fixed so the comparison isolates planner changes.
"""

import json
from pathlib import Path

from core.bess.simulation.vpp_simulator import simulate_vpp
from core.bess.tests.helpers import _scenario_inputs, run_scenario

DATA_DIR = Path(__file__).parent / "data"
BASELINE_PATH = DATA_DIR / "baselines" / "vpp_baseline_v10_0_2.json"


def fixture_names() -> list[str]:
    """Every scenario fixture. `glob` is non-recursive, so the baseline in
    `data/baselines/` is not picked up -- it must not be, since
    `golden_capture.fixture_names()` globs the same directory and would
    otherwise treat the baseline as a 37th scenario and change what the
    bit-parity gate means."""
    return sorted(path.stem for path in DATA_DIR.glob("*.json"))


def capture_plan(name: str) -> dict:
    """The DP's plan for one fixture, in the terms VPP execution consumes."""
    scenario = json.loads((DATA_DIR / f"{name}.json").read_text())
    result = run_scenario(scenario)
    dt = _scenario_inputs(scenario)["period_duration_hours"]
    return {
        "intents": [p.decision.strategic_intent for p in result.period_data],
        "actions_kw": [p.decision.battery_action / dt for p in result.period_data],
    }


def simulate_plan(name: str, plan: dict) -> dict:
    """Execute a captured plan through the VPP model and report what the
    inverter would be commanded to do, plus the realized cost."""
    scenario = json.loads((DATA_DIR / f"{name}.json").read_text())
    inputs = _scenario_inputs(scenario)
    settings = inputs["battery_settings"]
    dt = inputs["period_duration_hours"]

    sim = simulate_vpp(
        plan["intents"],
        plan["actions_kw"],
        inputs["solar_production"],
        inputs["home_consumption"],
        inputs["buy_price"],
        inputs["sell_price"],
        inputs["initial_soe"],
        settings,
        dt,
    )
    return {
        "commands": [[c.power_pct, c.remote_control_enabled] for c in sim.commands],
        "realized_cost": sim.realized_cost,
        "soe_trajectory": [inputs["initial_soe"]]
        + [p.energy.battery_soe_end for p in sim.period_data],
    }
