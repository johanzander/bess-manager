"""Shared capture path for the action-selector bit-parity goldens.

One definition of "run this fixture and record what came out", used by both
`scripts/capture_selector_goldens.py` (which writes the goldens) and
`test_action_selector_parity.py` (which re-runs and compares). Two copies
of the run configuration would let the goldens describe a run the test
never performs, which is precisely the kind of silent divergence the
parity gate exists to catch.
"""

import json
from pathlib import Path

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.tests.helpers import _scenario_inputs

DATA_DIR = Path(__file__).parent / "data"
GOLDEN_DIR = DATA_DIR / "golden"


def fixture_names() -> list[str]:
    """Every scenario fixture, in stable order (the golden directory itself
    is a subdirectory, so `glob` on this level never picks it up)."""
    return sorted(path.stem for path in DATA_DIR.glob("*.json"))


def capture_fixture(name: str) -> dict:
    """Run `optimize_battery_schedule` on one fixture and return the outputs
    the parity gate pins: the emitted actions, the SOE trajectory, and the
    optimized cost.

    The call mirrors `test_scenarios.test_all_scenarios` exactly, so the
    goldens describe the same solve the canonical scenario suite asserts on.
    """
    scenario = json.loads((DATA_DIR / f"{name}.json").read_text())

    # Pass `_scenario_inputs` through whole rather than re-listing keys. An
    # earlier version rebuilt the call from 8 of them and silently dropped
    # `export_curtailment_active`, `home_settings` and `initial_cost_basis`
    # -- so `regression_2026_08_08_143843`, which sets
    # `export_curtailment_active` precisely to pin #510's charge-early
    # tie-break, was captured with curtailment OFF. That left
    # `sell_price_floored` permanently None and
    # `_prefer_curtailed_charge_absorb` -- one of the two tie-breaks Phase 1
    # physically moves -- unentered by all 36 goldens, alongside the #429
    # import-cap filter and the 8 fixtures carrying `initial_cost_basis`.
    # Re-listing keys here is exactly the second copy of the run
    # configuration this module's docstring exists to forbid.
    inputs = _scenario_inputs(scenario)
    result = optimize_battery_schedule(**inputs)

    return {
        "actions": [p.decision.battery_action for p in result.period_data],
        "soe_trajectory": [inputs["initial_soe"]]
        + [p.energy.battery_soe_end for p in result.period_data],
        "battery_solar_cost": result.economic_summary.battery_solar_cost,
    }
