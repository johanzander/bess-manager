# Testing Guide (Agent Reference)

> **Full guide**: `docs/DEVELOPMENT.md` — covers environment setup, Docker,
> VS Code integration, and deploying to real hardware.
> This file focuses on what agents need: test philosophy and bug reproduction.

## The Core Rule

**Test behavior (what the system does), not implementation (how it does it).**

A test that breaks when you swap two equivalent algorithms is a bad test.
A test that passes after the swap — because the observable outcome is the same — is a good test.

## What to Test

### Business behavior

```python
# Good: test what users care about
def test_high_price_hour_triggers_discharge():
    strategic_intents[20] = "EXPORT_ARBITRAGE"
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
2. **Wizard** — runs the setup wizard against 7 scenario combinations

### Wizard Scenario Matrix

Each scenario boots a fresh mock-HA + BESS stack with different integrations
installed, validating that discovery, auto-selection, and the full wizard flow
work for every supported configuration.

| # | Scenario | Pricing | Inverter | Phase | Solcast | Cons.F | Disch.Inhib | Weather |
|---|----------|---------|----------|-------|---------|--------|-------------|---------|
| 1 | `ci-wizard-nordpool-min` | Nordpool Official | MIN | 3 | - | - | - | - |
| 2 | `ci-wizard-nordpool-sph` | Nordpool Official | SPH | 3 | - | - | - | - |
| 3 | `ci-wizard-octopus` | Octopus | MIN | - | - | - | - | - |
| 4 | `ci-wizard-full` | Nordpool Official | MIN | 3 | YES | YES | YES | YES |
| 5 | `ci-wizard-nordpool-hacs` | Nordpool HACS | MIN | 1 | YES | - | - | YES |
| 6 | `ci-wizard-octopus-sph` | Octopus | SPH | 3 | - | YES | YES | - |
| 7 | `ci-wizard-both-providers` | Nordpool + Octopus | MIN | 1 | - | - | YES | YES |

**What each test validates per scenario:**
- Correct pricing provider auto-selected (Nordpool vs Octopus)
- Correct inverter type auto-detected (MIN vs SPH)
- Optional integrations shown as found/not-found with correct status
- Provider-specific fields shown/hidden correctly
- Can switch between providers when both are available (scenario 7)
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
changes behavior, regenerate these **from the optimizer** (store `expected_results`
at ≥4 decimals to avoid 1-dp rounding-boundary flips) rather than hand-editing.

## Red Flags

A test has implementation coupling if it checks:

- Specific internal field names (`period_type`, `segment_id`)
- Exact internal time boundaries (`02:40–05:19`)
- Algorithm-specific counts (`len(intervals) == 9`)
- Anything in a comment saying `"specific to current algorithm"`
