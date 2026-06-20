# Plan-Faithfulness Simulator (`R == P`)

> **Audience:** agents and developers changing the optimizer, intent
> classification, or inverter control mapping. For the human-facing overview,
> see [`docs/DEVELOPMENT.md`](../DEVELOPMENT.md) → Testing.

**The single most valuable verification tool in this codebase.** Every savings
number the optimizer reports is a *plan* (`P`) — computed from the chosen battery
*actions*. But the inverter is driven by coarse *modes* (`grid_first` /
`load_first` / `battery_first` + charge/discharge rates), and a mode is a
**policy**, not a power setpoint. So the plan can claim things the hardware can't
deliver. Plan-only tests (`run_scenario`, scenario `expected_results`) cannot see
this gap.

The simulator (`core/bess/simulation/`) closes the loop: it takes the control
commands derived from a plan and computes the **realized** economics (`R`) of
executing them. The invariant is:

> **`R == P`** — executing the optimizer's plan through the inverter must
> reproduce the planned economics (to within the DP's SoE/power-grid resolution).
> A larger gap is a real control-fidelity bug, not noise.

This is *pure simulation* (no hardware, no mock-HA), so it runs in unit tests.

## Core API (`core/bess/simulation/`)

```python
from core.bess.simulation.inverter_simulator import (
    derive_control_command,  # plan period (intent + power) -> ControlCommand
    simulate,                # execute commands on conditions -> realized PeriodData + cost
)
from core.bess.simulation.verification import (
    verify_plan_faithfulness,   # optimize -> derive -> simulate -> (P, R, per-period deltas)
    ab_compare,                 # realized-cost delta between two command sequences (exact)
    realized_under_solar_error, # optimize on FORECAST solar, execute on ACTUAL solar (robustness)
)
```

In **scenario tests**, use the helper `run_scenario_realized(scenario)` (in
`tests/helpers.py`) — it returns `(result, realized_cost)` so you can assert
`R == P` alongside the normal plan checks. `test_scenarios.py` does this for every
scenario.

## When to use it — REQUIRED for any optimizer or control change

If you touch the **DP** (`dp_battery_algorithm.py`), the **intent classification**
(`decision_intelligence.py`), or the **control mapping** (`inverter_controller.py`),
you MUST verify `R == P` still holds — a passing plan-only test means nothing if
the plan isn't executable. Add/keep an `R == P` assertion for the affected
scenarios.

## What it has already caught (why it exists)

- **Phantom solar-export over-crediting** (#145): the optimizer booked export of
  surplus a `load_first` "store" period actually stores → ~8–16% inflated savings
  on sunny days. Invisible to plan-only tests.
- **Discharge can't be paced for home support** (#147): `LOAD_SUPPORT` dumps the
  battery greedily on deep evening peaks → realizes ~3–4% worse than planned.

## Known gaps and `xfail`

A real, unfixed `R != P` gap should be **`xfail`'d with a tracking issue** (so it
stays visible), never hidden under a loose tolerance. See the
`DISCHARGE_PACING_SCENARIOS` set in `test_scenarios.py` (→ #147). The grid-resolution
residual (`max(0.5 SEK, 1% of |P|)` in `test_scenarios.py`) is the *only* tolerance
— it reflects the DP's 0.1 kWh SoE grid, not a fudge factor.
