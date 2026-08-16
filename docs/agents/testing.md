# Testing Guide (Agent Reference)

> **Full guide**: `docs/DEVELOPMENT.md` — covers environment setup, Docker,
> VS Code integration, and deploying to real hardware.
> This file focuses on what agents need: test philosophy and bug reproduction.

## The Core Rule

**Test behavior (what the system does), not implementation (how it does it).**

A test that breaks when you swap two equivalent algorithms is a bad test.
A test that passes after the swap — because the observable outcome is the same — is a good test.

### Before writing the RED test for a bug fix

Identify the **correct design** before writing any test. A test written against the wrong design locks in that design and makes the correct fix harder to reach.

Ask before writing:
- Should this method be called from this caller at all, or is there a better owner?
- Is there an existing lifecycle path (`start()`, `__init__`) that already handles this? Why is it failing there?
- Does the test assert a specific internal call chain — and if so, is that call chain the right architecture?
- **Does the method you're about to modify have more than one caller?** `grep` for every call site first. If the callers sit at different points in a lifecycle (e.g. one runs during `start()` before some other init step, another runs later from a periodic job or a manual endpoint), a change scoped to "make caller A's symptom go away" can silently change behavior for caller B too. See `docs/agents/rules.md` → Architecture → Separation of concerns, and the Debugging Protocol's fix-scope-assessment step, for the general rule this falls under.
- **If the method has multiple callers with different lifecycle timing, write one test per caller context**, not just one test for the behavior the fix motivates. A test on the wrapper/most-visible caller passing is not evidence the other callers are unaffected.

If you can't answer these, stop and reason through the design first. A test that says "call `_foo()` from layer X" may be specifying bad architecture, not good behavior.

## What to Test

### Business behavior

```python
# Good: test what users care about
def test_high_price_hour_triggers_discharge():
    strategic_intents[20] = "BATTERY_EXPORT"
    scheduler.apply_schedule(strategic_intents)
    assert scheduler.is_hour_configured_for_export(20)
```

### Hardware constraints

```python
# Good: these rules must never break regardless of algorithm
assert scheduler.has_no_overlapping_intervals()
assert scheduler.intervals_are_chronologically_ordered()
```

### Integration outcomes

```python
# Good: end-to-end savings are positive given favorable prices
result = optimizer.run(prices=high_spread_prices, initial_soc=0.2)
assert result.total_savings > 0
```

## What NOT to Test

```python
# Bad: tests internal data structures
assert i.get("period_type") == "strategic"  # breaks if field is renamed

# Bad: tests algorithm-specific slot boundaries
assert slot_start_times == ["02:40", "05:20"]

# Bad: tests exact counts that are implementation-specific
assert len(intervals) == 9
```

## Running the Test Suite

```bash
pytest -m "not slow"                # fast tests only (~3s, 280+ tests)
pytest -m slow                      # algorithm/integration tests (~30min)
pytest                              # all tests
pytest core/bess/tests/unit/        # unit tests only (fast, no HA required)
pytest core/bess/tests/integration/ # integration tests
pytest --cov=core.bess              # with coverage
```

Tests are split by `pytest.mark.slow`. The slow marker is applied to all
optimizer/DP tests and all integration tests (auto-marked via
`core/bess/tests/integration/conftest.py`).

The `run_tests` tool in `issue_fixer.py` calls `pytest --tb=short -q` automatically
after writing fixes. Fix all failures before finishing.

## CI Pipeline

CI runs automatically on every PR and push to `main` (`.github/workflows/ci.yml`):

| Job | Trigger | What it runs |
|-----|---------|-------------|
| **Fast tests** | `backend/` or `core/` changed | `pytest -m "not slow"` (~3s, 333 tests) |
| **Algorithm tests** | `core/bess/` changed | `pytest -m slow` (~30min, 116 tests) |
| **Frontend checks** | `frontend/` changed | `npm test` + type-check + lint |
| **E2E tests** | backend/frontend/e2e/docker changed | Playwright: 2 phases (smoke + wizard) against docker-compose mock HA |
| **Code quality** | Always | Black + Ruff formatting/linting |
| **Docker build & boot** | `backend/`, `core/`, `frontend/`, or `Dockerfile` changed | Builds production Dockerfile, boots with mock-HA, smoke-tests endpoints |

The E2E job runs Playwright tests covering API contract validation, page-level
rendering, and the setup wizard flow. It starts in two phases:
1. **Normal day** — tests all pages, API contracts, and navigation
2. **Growatt VPP** — verifies a fresh-install VPP-mode schedule build completes without error (regression for #399, #469)
3. **Wizard** — runs the setup wizard against every scenario combination in the table below

### Wizard Scenario Matrix

Each scenario boots a fresh mock-HA + BESS stack with different integrations
installed, validating that discovery, auto-selection, and the full wizard flow
work for every supported configuration. Generated from `e2e/tests/wizard-expectations.ts`
(the source of truth CI actually asserts against) — do not hand-edit this table
without re-deriving it from that file, since a wrong value here can silently
mask a wrong value there.

| Scenario | Pricing | Inverter | Phase | Solcast | Cons.F | Disch.Inhib | Weather |
|----------|---------|----------|-------|---------|--------|-------------|---------|
| `ci-wizard-nordpool-min` | Nordpool Official | MIN (Cloud) | 3 | - | - | - | - |
| `ci-wizard-nordpool-sph` | Nordpool Official | SPH (Cloud) | 3 | - | - | - | - |
| `ci-wizard-nordpool-solax` | Nordpool Official | SolaX Native | - | - | - | - | - |
| `ci-wizard-octopus` | Octopus | MIN (Cloud) | - | - | - | - | - |
| `ci-wizard-entsoe` | ENTSO-e | MIN (Cloud) | - | - | - | - | - |
| `ci-wizard-entsoe-frank-126` | ENTSO-e | MIN (SolaX Modbus) | 3 | YES | - | - | - |
| `ci-wizard-full` | Nordpool Official | MIN (Cloud) | 3 | YES | YES | YES | YES |
| `ci-wizard-nordpool-hacs` | Nordpool HACS | MIN (Cloud) | 1 | YES | - | - | YES |
| `ci-wizard-growatt-sph-cloud-octopus` | Octopus | SPH (Cloud) | - | - | - | - | - |
| `ci-wizard-both-providers` | Nordpool + Octopus | MIN (Cloud) | 1 | - | - | YES | YES |
| `ci-wizard-growatt-modbus` | Nordpool Official | MIN (Cloud) — auto-selects Growatt Cloud even though SolaX Modbus is also detected | - | - | - | - | - |
| `ci-wizard-solis` | Nordpool Official | Solis | - | - | - | - | - |
| `ci-wizard-growatt-vpp` | Nordpool Official | SPH (SolaX Modbus, GEN3, VPP) — experimental, see [platform maturity](memory/project_platform_maturity.md) | 3 | - | - | - | - |
| `ci-wizard-huawei-luna2000` | Nordpool Official | Huawei LUNA2000 — experimental, see [platform maturity](memory/project_platform_maturity.md) | - | - | - | - | YES |

`ci-wizard-huawei-luna2000` is the only fixture that drives a full backend
schedule cycle on Huawei. It carries two TOU periods on the battery so the
#431 readback has something to read, 96 quarterly prices and a solar forecast
so the DP actually solves. Run it end to end with:

```bash
SCENARIO=ci-wizard-huawei-luna2000 BESS_SETTINGS=./e2e/ci-bess-settings-huawei.json \
  BESS_FAKETIME_PRELOAD=/usr/local/lib/libfaketime.so.1 \
  BESS_FAKETIME="2026-05-21 17:17:48" \
  podman-compose -f docker-compose.ci.yml up -d
```

The faketime pin is required: the fixture's prices are keyed to its
`mock_time` date, so without it the scheduler aborts with "No price data
available" (see the `verify` skill's gotchas).

**Not in this table — backend-discovery-only, not Playwright-runnable:**
`ci-wizard-growatt-modbus-gen3.json` was meant to test a GEN3-via-SolaX-Modbus
"no TOU" path, but GEN3 (`solax_modbus_growatt_sph`) has no TOU path at all —
`battery_system_manager.py:291-292` documents it as VPP-only. The fixture is
missing the 5 VPP entities the wizard requires to complete, so "Next" never
enables and the full flow can't finish. It still gets exercised by
`test_scenario_discovery.py` (backend-only, doesn't need wizard completion).
GEN3-via-SolaX-Modbus is itself experimental/unvalidated in the real world —
only Growatt Cloud SPH and GEN4-via-Modbus are — so this isn't worth forcing
into a full-completion test by adding fabricated VPP entity IDs.

**What each test validates per scenario:**
- Correct pricing provider auto-selected (Nordpool vs Octopus vs ENTSO-e)
- Correct inverter platform auto-selected — the wizard picks the backend's
  `detectedInverterPlatforms[0]`, so when a scenario has both a Growatt Cloud
  config entry and SolaX Modbus entities, Cloud wins (it's listed first)
- Optional integrations shown as found/not-found with correct status
- Provider-specific fields shown/hidden correctly
- Can switch between providers/platforms when more than one is available
- Full wizard completion end-to-end

Scenario expectations are defined in `e2e/tests/wizard-expectations.ts`.
Scenario data files live in `scripts/mock_ha/scenarios/ci-wizard-*.json`.

The Docker build & boot job catches a common failure mode: the production
`Dockerfile` explicitly lists backend files in its `COPY` command. If a new
file is added but not listed, the image builds but crashes at runtime with
an `ImportError`. This job verifies the app actually starts.

`quality-check.sh` runs fast tests + linting and is used by the issue-fix bot.

## Docker Compose Environments

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Local dev with hot-reload |
| `docker-compose.ci.yml` | E2E testing: Dockerfile.dev + volume mounts, configurable via `SCENARIO`, `BESS_PORT`, `BESS_SETTINGS`, `BESS_OPTIONS` |
| `docker-compose.prod-test.yml` | Production image verification (real Dockerfile, no code mounts) |

## Bug Reproduction with Mock HA

This is the most important tool for agents fixing bugs from debug logs.
The mock HA environment runs the full BESS stack against a frozen snapshot of a
user's system state — no real Home Assistant required.

**Why this matters**: A debug log from a user contains everything needed to
reproduce the exact conditions that caused the bug. Mock HA replays it identically.

### Workflow

```bash
# 1. Generate a scenario from the debug log the user provided
python scripts/mock_ha/scenarios/from_debug_log.py <debug-log-file.md>
# Outputs: scripts/mock_ha/scenarios/<timestamp>.json

# For a DP/control-mapping fix that needs a fast, no-container plan-faithfulness
# regression test (see .claude/skills/implement-issue/SKILL.md's TDD step),
# also tag the log with the issue it diagnoses -- this additionally writes a
# lean fixture to core/bess/tests/unit/data/regression_<timestamp>.json:
python scripts/mock_ha/scenarios/from_debug_log.py <debug-log-file.md> --issue <N>

# 2. Start mock HA + BESS (runs at the frozen timestamp from the log)
./mock-run.sh <timestamp>
# e.g. ./mock-run.sh 2026-03-24-225535

# 3. Optionally replay from a specific time of day
./mock-run.sh 2026-03-24-225535 09:00

# Access:
#   BESS UI:             http://localhost:8080
#   Inverter writes:     http://localhost:8123/mock/service_log
#   Sensor states:       http://localhost:8123/mock/sensors
```

### What mock HA provides

| Debug log field | Mock HA uses it for |
|----------------|---------------------|
| `entity_snapshot` | Verbatim sensor responses BESS will read |
| `historical_periods` | Seeds the historical store (no InfluxDB needed) |
| `price_data` | Raw quarterly prices for the optimizer |
| `addon_options` | Sensor entity IDs, inverter config |
| `inverter_tou_segments` | Current inverter memory state |
| `export_timestamp` | Pins the wall clock so BESS runs at that exact moment |

### Verifying a fix

After applying the fix and running mock HA, check `http://localhost:8123/mock/service_log`
to see what TOU segments BESS sent to the inverter. Compare with expected behavior.

## Plan-Faithfulness Simulator (`R == P`)

When you change the optimizer, intent classification, or inverter control
mapping, a passing plan-only test means nothing if the plan isn't faithfully
executable by the hardware. The plan-faithfulness simulator
(`core/bess/simulation/`) closes that loop and is **REQUIRED** verification for
any such change.

**Full reference: [`simulator.md`](simulator.md)** — the `R == P` invariant, the
API (`derive_control_command` / `simulate` / `verify_plan_faithfulness`), the
`run_scenario_realized` helper, the `xfail` policy, and what it has caught.

## Test Data

JSON scenario fixtures live in `core/bess/tests/unit/data/`.
Name them descriptively: `high_solar_export.json`, `ev_charging_overnight.json`.

Scenarios may carry `expected_results` (plan economics) and `expected_behavior`
(intent presence/absence, `savings_positive`). When the optimizer legitimately
changes behavior, regenerate these **from the optimizer** rather than
hand-editing:

```bash
.venv/bin/python scripts/capture_scenario_expected_results.py   # prints every delta
```

It rewrites only the keys a fixture already carries and prints what moved, so
the PR can quote the measured movement. `--check` reports staleness without
writing. It is a *deliberate re-pin*, never a way to green a red suite — if you
cannot explain a printed delta, that delta is the finding.

**`terminal_value_per_kwh` is required on every fixture**, enforced by
`test_scenarios.py::test_every_fixture_declares_a_terminal_value`. It used to
be an optional override (added for #422); every other fixture fell through to
`optimize_battery_schedule`'s `0.0` default, and at 0.0 the DP's terminal-row
branch never executes, so the whole corpus was blind to terminal value in both
directions. Generate it with:

```bash
.venv/bin/python scripts/capture_scenario_terminal_values.py
```

which applies the production formula (`core/bess/terminal_value.py`) to the
fixture's own prices, reproducing #422's calendar-day cap scoping as the last
`24 / period_duration` periods.

**The recorded value is derived, never hand-pinned.** The script overwrites any
recorded value that disagrees with the formula, and
`test_scenarios.py::test_recorded_terminal_values_still_match_the_production_formula`
fails a fixture that carries one — the whole point of the retrofit is that the
corpus runs at production's terminal value, so a fixture pinned to something
else is silently exempt from the gate it was added to feed. A defect in how
`BatterySystemManager` *computes* that input therefore belongs in a test of
`BatterySystemManager`, not in a scenario fixture.

Adding or changing a fixture therefore means regenerating three artefacts, in
this order (the second and third fail by design until you do):

```bash
.venv/bin/python scripts/capture_scenario_terminal_values.py
.venv/bin/python scripts/capture_selector_goldens.py
PYTHONPATH=. .venv/bin/python scripts/capture_vpp_baseline.py --add-new
```

For a change that moves what the DP *plans* on existing fixtures, the VPP step
is `--repin-current` instead of `--add-new`: it rewrites only the
`current_plan`/`current` half and prints each fixture's realized-cost delta.
Never run a full VPP re-baseline to go green — that regenerates both halves and
destroys the recorded v10.0.2 drift signal.

**For a bug fix that changes optimizer economics or behavior: pin the
regression into this fixture system before reaching for a standalone test
file.** `test_scenarios.py::test_all_scenarios` auto-discovers every `*.json`
here and is already the codebase's canonical, always-run regression harness
(the "N pinned fixtures" referenced across the changelog for prior DP
changes) — a bespoke Python file re-deriving `_scenario_inputs` and hand-
asserting cost numbers duplicates it. Concretely, after generating a fixture
from a debug log (`from_debug_log.py --issue N`, see below), the next step
is always to set that fixture's `expected_results`/`expected_behavior` from
the *fixed* code's output, not to write a separate test around the same
data. Reserve a standalone test file for what the fixture system genuinely
cannot express: a private method's internal formula (e.g. the exact
terminal-value cap numbers), or plan-faithfulness (`R == P`, see below) —
`test_all_scenarios` never runs the inverter simulator.

**`expected_behavior.intents_present`/`intents_absent` only discriminates
on an engineered/isolated scenario** — one deliberately built so the intent
under test has no other legitimate source (e.g. zero consumption, so any
`BATTERY_EXPORT` can only come from the mechanism being tested). On a real
multi-purpose debug-log fixture, "is this intent present *anywhere* in the
whole result" is usually satisfiable by something unrelated elsewhere in
the horizon and proves nothing — pinning `expected_results` (aggregate
economics) is almost always the right choice for those instead, since a
suppressed/wrong intent still shows up in the total cost even when it's
masked at the presence-check level. Full per-period intent pinning is the
maximally deterministic alternative but is usually not worth the
brittleness — an unrelated DP tie-break shifting one period elsewhere in a
100+ period horizon shouldn't fail the test.

**Before trusting a pinned `expected_results`/`expected_behavior`, prove it
actually discriminates**: temporarily feed the fixture the pre-fix
(buggy) input and confirm the test fails, not just that it passes with the
fix. A pin that passes under both the bug and the fix isn't a regression
guard.

## Red Flags

A test has implementation coupling if it checks:

- Specific internal field names (`period_type`, `segment_id`)
- Exact internal time boundaries (`02:40–05:19`)
- Algorithm-specific counts (`len(intervals) == 9`)
- Anything in a comment saying `"specific to current algorithm"`
