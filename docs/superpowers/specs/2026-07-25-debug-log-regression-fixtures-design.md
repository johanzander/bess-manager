# Debug-log-derived regression fixtures for plan-faithfulness tests

Status: approved
Date: 2026-07-25
Related: issue #269, PR #391 (motivating example, not retrofitted by this work)

## Problem

When a bug is diagnosed from a real user's debug bundle, the regression test
that pins the fix currently has to either hand-build synthetic input arrays
(loses fidelity to what actually happened) or hardcode the real values as
giant inline Python literals in the test file (works, but unreadable and
not reusable — this is what PR #269's `test_plan_faithfulness.py` addition
does today).

Two existing, separate scenario-file conventions already solve adjacent
problems, but neither solves this one directly:

- `scripts/mock_ha/scenarios/from_debug_log.py` generates a full HA-entity
  replay scenario for the containerized E2E stack (`mock-run.sh` /
  `docker-compose.ci.yml`). It's real-log-derived, but the output carries
  real entity IDs and sensor state, and per `.gitignore` only a curated
  `ci-*`/`synthetic-*` subset gets committed — everything else (including
  anything generated from a real user's bundle) stays local/ephemeral by
  design.
- `core/bess/tests/unit/data/*.json` is the committed, lean, numeric-only
  scenario format (`base_prices`/`home_consumption`/`solar_production`/
  `battery`) consumed by `test_scenarios.py`'s generic data-driven loop and
  by `run_scenario`/`run_scenario_realized` in `helpers.py`. Nothing
  generates this format from a debug log today — every file in that
  directory was hand-built, including the one prior real-log-derived
  example (`unit/fixtures/issue_231_real_debug_export.json`, now orphaned
  since the code it tested was later removed).

## Goal

Make it possible to derive a committed, lean, plan-faithfulness-ready
regression fixture directly from a user's debug bundle — reusing the
already-parsed data `from_debug_log.py` produces — tagged with the issue/PR
it pins, so future DP/control-mapping bug fixes don't need giant inline
literals and the fixture is traceable back to its origin.

## Design

### 1. New output mode on the existing generator

Extend `scripts/mock_ha/scenarios/from_debug_log.py` (not a new script) with
an optional flag:

```
python scripts/mock_ha/scenarios/from_debug_log.py <log.md> --issue 269 [--pr 391]
```

It already calls `parse_debug_log()` and has `log.input_data` in hand. When
`--issue` is passed, after writing the existing E2E scenario as today, it
additionally writes the new lean fixture (below) to
`core/bess/tests/unit/data/`. No new parsing logic — a second writer over
data already parsed once. `--pr` is optional (typically unknown until the
PR is opened) and can be added later via a one-line edit to the JSON, or a
follow-up `--issue 269 --pr 391` re-run (idempotent, overwrites the same
file).

### 2. New fixture format

`core/bess/tests/unit/data/regression_YYYY_MM_DD_HHMMSS.json` — timestamp
derived from the debug log filename, same convention as the existing
`realworld_*.json` files, under a new `regression_` category (documented in
`core/bess/tests/unit/data/README.md` alongside the existing categories).

```json
{
  "name": "regression_2026_07_25_090230",
  "description": "Issue #269: DP held below min_soe_kwh exporting solar at negative price instead of charging",
  "issue": 269,
  "pr": 391,
  "source": "debug_log/bess-debug-2026-07-25-090230.md",
  "resolution": "quarterly",
  "period_duration_hours": 0.25,
  "buy_price": [ ... ],
  "sell_price": [ ... ],
  "home_consumption": [ ... ],
  "solar_production": [ ... ],
  "battery": {
    "max_soe_kwh": 15.0,
    "min_soe_kwh": 1.8,
    "max_charge_power_kw": 5.0,
    "max_discharge_power_kw": 5.0,
    "efficiency_charge": 0.97,
    "efficiency_discharge": 0.95,
    "cycle_cost_per_kwh": 0.035,
    "initial_soe": 1.65,
    "initial_cost_basis": 0.035
  }
}
```

`buy_price`/`sell_price` are the **final** values from `log.input_data` —
exactly what the optimizer saw that day — not `base_prices` (pre-markup,
requiring `price_data` markup config to reconstruct). This is more faithful
(exact replay) and immune to a future markup-formula change silently
altering what an old fixture means. Existing `data/*.json` files keep using
`base_prices` unchanged; the two are alternate inputs into the same loader,
not a schema migration.

### 3. Loader extension

`core/bess/tests/helpers.py::_scenario_inputs`:

- If `scenario` has `buy_price`/`sell_price` keys, use them directly and
  skip `PriceManager`/`base_prices` entirely.
- Otherwise, fall back to today's `base_prices` + optional `price_data`
  path, unchanged.
- Read `battery.get("initial_cost_basis")` if present and pass it through
  to `optimize_battery_schedule` (currently dropped — not read at all).

Fully backward compatible: every existing `data/*.json` file has no
`buy_price`/`sell_price` keys and no `initial_cost_basis`, so it takes the
unchanged path.

### 4. Baseline coverage for free

`test_scenarios.py`'s existing loop already globs `data/*.json` via
`get_all_scenario_files()`, so any new `regression_*.json` is automatically
included in the generic physical-constraint/savings-positive checks with no
wiring changes.

### 5. Per-bug regression assertions stay hand-written

The generic checks above wouldn't have caught issue #269 specifically (SOE
stayed in-bounds, savings stayed positive throughout — only the below-floor
charging *decision* was wrong). Each fixed bug still gets a small, dedicated
test function (in the appropriate `test_*.py`, not auto-generated) that:

- loads its `regression_*.json` fixture by name,
- asserts the specific behavior the bug fix produces,
- optionally calls `run_scenario_realized` for an R == P plan-faithfulness
  check when the fix touches DP/intent/control-mapping code (per
  `.claude/skills/implement-issue/SKILL.md`'s existing requirement).

## Out of scope

- Retrofitting PR #391's already-reviewed test to use this convention —
  ships as a separate, later change once this tooling exists.
- Cleaning up the orphaned `unit/fixtures/issue_231_real_debug_export.json`
  — noted for awareness, not touched here.
- Any change to the E2E (`scripts/mock_ha/scenarios/`) scenario format or
  its `.gitignore` rules.

## Testing

- Unit test for the new `--issue`/`--pr` flag on `from_debug_log.py`:
  given a sample debug log, asserts the lean fixture is written with the
  expected keys/values.
- Unit test(s) for `_scenario_inputs`' new `buy_price`/`sell_price` and
  `initial_cost_basis` handling: a scenario dict with those keys produces
  the expected `optimize_battery_schedule` kwargs, and existing
  `base_prices`-only scenarios are unaffected (regression coverage for the
  fallback path).
- `core/bess/tests/unit/data/README.md` updated with the new category.
