# Test Framework Overhaul Plan

> **Status**: Phase 1 — complete
> **Branch strategy**: Each phase is a separate branch merged to `main` before starting the next.

## Why

The BESS Manager has 34 pytest files but zero frontend tests, no E2E tests,
no CI test execution, and no automated deployment verification. The quality
gate (`quality-check.sh`) only checks linting/formatting — not pytest. The
automated GitHub agent pipeline (issue → fix → PR) can merge broken code.

Deployment to HA is fully manual: `deploy.sh` + clicking through the UI.

**Goal**: Fully automated testing pipeline with high confidence that merged
code works end-to-end, enabling the agent pipeline to operate autonomously.

---

## Current Assets

| Asset | Location | What it provides |
|-------|----------|-----------------|
| 34 pytest files | `core/bess/tests/`, `backend/tests/` | Algorithm, pricing, settings, API coverage |
| Mock HA server | `scripts/mock_ha/server.py` | Replays frozen scenarios, records inverter writes |
| Docker compose mock | `docker-compose.mock.yml` | Full BESS stack against mock HA, no real HA needed |
| Scenario generator | `scripts/mock_ha/scenarios/from_debug_log.py` | Creates reproducible scenarios from user debug logs |
| `mock-run.sh` | Project root | Orchestrates mock environment (FAKETIME, config extraction) |
| `quality-check.sh` | `scripts/` | Black, Ruff, ESLint, TypeScript type-check |

## Current Gaps

1. `quality-check.sh` does not run pytest or frontend tests
2. No CI workflow runs any tests — PRs can merge with failures
3. Frontend has zero test infrastructure (no Vitest, no Playwright)
4. Scenario tests only assert economic values, not behavioral (strategic intents)
5. Mock HA is only used manually via `mock-run.sh`, never in CI
6. Deployment to real HA is fully manual with no smoke tests

---

## Architecture Options

### Option A: CI Quality Gate (chosen as Phase 1–2)

Run pytest + frontend unit tests in CI on every PR. Cheapest path to
catching regressions. Does not verify full-stack behavior.

### Option B: Full-Stack E2E with Playwright (chosen as Phase 3–4)

Playwright tests running against docker-compose mock HA. Closes the
"click through UI" gap. The existing mock HA infrastructure is the
foundation — Playwright just drives a browser against it.

### Option C: Deployment Verification (Phase 5, evaluate after B is stable)

Automated deployment to real HA with smoke tests. Maximum confidence but
significant infrastructure cost. Two sub-options:

- **C1**: Self-hosted GitHub Actions runner on HA network, deploys via SMB
- **C2**: Push to GHCR, HA Supervisor API pulls staging tag, CI verifies

**Recommendation**: Implement A → B incrementally. Evaluate C once B is stable
and you have data on what mock HA E2E catches vs. misses.

---

## Phase 1: CI Quality Gate

**Goal**: Pytest and linting run in CI on every PR. Block merges on failure.

### 1.1 CI workflow with path-based test avoidance

Created `.github/workflows/ci.yml` with four parallel jobs:

- **changes** — uses `dorny/paths-filter` to detect which areas changed
- **test-fast** — runs `pytest -m "not slow"` (281 tests, ~3s) — only if `core/` or `backend/` changed
- **test-algorithm** — runs `pytest -m slow` (116 tests, ~30min) — only if `core/bess/` changed
- **test-frontend** — TypeScript type-check + ESLint — only if `frontend/` changed
- **quality** — Black + Ruff formatting/linting (always runs)

Frontend-only changes skip all Python tests. Backend API changes skip the
expensive DP algorithm tests.

### 1.2 Fast/slow test split via pytest markers

Added `pytest.mark.slow` to all test files that run the full DP optimizer:

- **Unit tests** (8 files): `test_scenarios.py`, `test_optimization_algorithm.py`,
  `test_terminal_value.py`, `test_idle_solar_charging.py`, `test_quarterly_vs_hourly.py`,
  `test_action_threshold.py`, `test_extended_horizon.py`, `test_discharge_inhibit.py`
- **Integration tests** (all): auto-marked via `integration/conftest.py`

Result: `pytest -m "not slow"` runs 281 tests in ~3s.
Full suite: 397 tests (116 slow).

### 1.3 Updated quality-check.sh

Runs fast tests only (`-m "not slow"`) so the issue-fix bot completes quickly.
Full algorithm tests run in a separate CI job when `core/bess/` changes.

### 1.4 Dev dependencies

Updated `requirements-dev.txt` with: pytest, pytest-cov, httpx, black, ruff.
Added `[tool.pytest.ini_options]` to `pyproject.toml` with testpaths and markers.

### 1.5 Branch protection

Enable branch protection on `main` requiring the CI jobs to pass.

### Files modified
- `.github/workflows/ci.yml` (new)
- `scripts/quality-check.sh` (add pytest step)
- `requirements-dev.txt` (proper test deps)
- `pyproject.toml` (pytest config + markers)
- `core/bess/tests/integration/conftest.py` (new — auto-mark slow)
- 8 unit test files (added `pytestmark = pytest.mark.slow`)

### Done
- [x] CI runs fast tests (~3s) on every PR
- [x] Algorithm tests only run when `core/bess/` changes
- [x] Frontend checks only run when `frontend/` changes
- [x] `quality-check.sh` runs fast tests (benefits issue-fix bot)
- [ ] Branch protection configured on `main` (manual step)

---

## Phase 2: Frontend Unit Tests

**Goal**: Add Vitest + React Testing Library. Test critical hooks and API layer.

### 2.1 Add test infrastructure

```bash
cd frontend
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

Update `frontend/package.json`:
```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

Add `frontend/vitest.config.ts`:
```ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
```

### 2.2 Write priority tests

Target the highest-value areas first:

| Test file | What it covers | Why it matters |
|-----------|---------------|----------------|
| `src/lib/__tests__/api.test.ts` | Axios client, base URL detection, ingress path handling | Every page depends on this |
| `src/hooks/__tests__/useSettings.test.ts` | Settings fetch, update, error states | Settings page + setup wizard |
| `src/hooks/__tests__/useDashboardData.test.ts` | Dashboard data fetching, resolution switching | Main page |
| `src/pages/__tests__/SetupWizardPage.test.tsx` | Discover → confirm → complete flow | Critical onboarding path |

### 2.3 Add to CI and quality gate

Extend `ci.yml`:
```yaml
      - run: cd frontend && npm ci && npm test
```

Extend `quality-check.sh`:
```bash
echo "🔸 Running frontend tests..."
if npm test; then
    echo "✅ Frontend tests passed"
else
    echo "❌ Frontend tests failed"
    ERRORS=$((ERRORS + 1))
fi
```

### Files modified
- `frontend/package.json` (add test deps + script)
- `frontend/vitest.config.ts` (new)
- `frontend/src/test/setup.ts` (new — test environment setup)
- `frontend/src/lib/__tests__/api.test.ts` (new)
- `frontend/src/hooks/__tests__/useSettings.test.ts` (new)
- `frontend/src/hooks/__tests__/useDashboardData.test.ts` (new)
- `frontend/src/pages/__tests__/SetupWizardPage.test.tsx` (new)
- `.github/workflows/ci.yml` (add frontend test step)
- `scripts/quality-check.sh` (add npm test step)

### Done when
- [ ] `npm test` runs and passes in `frontend/`
- [ ] CI runs frontend tests alongside pytest
- [ ] At least 4 test files covering API layer, hooks, and setup wizard

---

## Phase 3: Playwright E2E Against Mock HA

**Goal**: Browser tests verifying the full stack (frontend → backend → mock HA).

### 3.1 Commit representative scenarios

Select 2–3 scenarios from debug logs and commit them:

```
scripts/mock_ha/scenarios/
  ci-normal-day.json        — typical day with solar + price spread
  ci-high-volatility.json   — extreme price swings, tests discharge logic
  ci-setup-wizard.json      — fresh install, no sensors configured
```

These are frozen snapshots — deterministic inputs for repeatable tests.

### 3.2 Add docker-compose.ci.yml

CI-friendly overlay (no volume mounts, no live reload):

```yaml
services:
  bess-dev:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      - HA_URL=http://mock-ha:8123
      - HA_TOKEN=mock_token
      - HA_TEST_MODE=false
    ports:
      - "8080:8080"
    depends_on:
      mock-ha:
        condition: service_healthy

  mock-ha:
    build: ./scripts/mock_ha
    environment:
      - SCENARIO=${SCENARIO:-ci-normal-day}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8123/mock/sensors"]
      interval: 5s
      timeout: 3s
      retries: 10
    ports:
      - "8123:8123"
```

### 3.3 Install Playwright

```bash
# From project root (not frontend — e2e tests are a separate concern)
mkdir e2e
cd e2e
npm init -y
npm install -D @playwright/test
npx playwright install chromium
```

### 3.4 Playwright test structure

```
e2e/
  package.json
  playwright.config.ts
  tests/
    dashboard.spec.ts          — dashboard loads, charts render, resolution toggle
    settings.spec.ts           — change settings, verify persistence across reload
    setup-wizard.spec.ts       — discover → confirm → complete flow
    inverter-commands.spec.ts  — wait for optimization cycle, verify /mock/service_log
    api-smoke.spec.ts          — hit all 24 API endpoints, verify 200 + response shape
    navigation.spec.ts         — all 7 routes load without error
```

**Key pattern — inverter command verification:**
```ts
test('optimization cycle sends TOU segments to inverter', async ({ request }) => {
  // Wait for BESS to complete one cycle (poll /api/dashboard until schedule exists)
  // Then verify mock HA received the expected service calls
  const log = await request.get('http://localhost:8123/mock/service_log');
  const calls = await log.json();
  expect(calls).toContainEqual(
    expect.objectContaining({ service: 'set_tou_segments' })
  );
});
```

### 3.5 Add E2E job to CI

```yaml
  e2e:
    runs-on: ubuntu-latest
    needs: test  # only run if unit tests pass
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - run: cd e2e && npm ci && npx playwright install chromium --with-deps
      - run: cd frontend && npm ci && npm run build
      - run: |
          docker compose -f docker-compose.ci.yml up -d
          # Wait for BESS to be ready
          timeout 120 bash -c 'until curl -sf http://localhost:8080/api/system-health; do sleep 2; done'
      - run: cd e2e && npx playwright test
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: e2e/playwright-report/
      - run: docker compose -f docker-compose.ci.yml down
        if: always()
```

### Files modified
- `scripts/mock_ha/scenarios/ci-*.json` (new — committed scenario files)
- `docker-compose.ci.yml` (new)
- `e2e/` (new directory — package.json, playwright.config.ts, tests/)
- `.github/workflows/ci.yml` (add e2e job)
- `scripts/mock_ha/server.py` (possibly add health endpoint)

### Done when
- [ ] `docker compose -f docker-compose.ci.yml up` starts BESS + mock HA deterministically
- [ ] Playwright tests pass locally against the mock environment
- [ ] CI runs E2E after unit tests pass, uploads report on failure
- [ ] At least 5 E2E test files covering dashboard, settings, setup, inverter, API

---

## Phase 4: Enhanced Scenario Testing

**Goal**: Extend pytest scenario framework with behavioral assertions.

### 4.1 Extend scenario JSON schema

Current `expected_results` only has economic fields. Add:

```json
{
  "expected_results": {
    "base_cost": 12.5,
    "savings_pct": 15.0,
    "strategic_intents": {
      "hour_2": "CHARGE",
      "hour_14": "SOLAR_STORAGE",
      "hour_20": "EXPORT_ARBITRAGE"
    },
    "constraints": {
      "no_overlapping_intervals": true,
      "soc_never_below_min": true,
      "soc_never_above_max": true
    }
  }
}
```

### 4.2 Update test_scenarios.py

Add assertion helpers that check:
- Strategic intent at specified hours matches expected
- Physical constraints are never violated
- Inverter schedule has no overlapping intervals
- SOC trajectory stays within bounds

### 4.3 Add shared test fixtures

Create `core/bess/tests/helpers.py` with:
- `run_optimization(prices, solar, consumption, battery_settings)` — one-liner to run the full optimizer
- `assert_strategic_intent(result, hour, expected_intent)` — behavioral assertion
- `assert_physical_constraints(result)` — constraint validation

### Files modified
- `core/bess/tests/unit/test_scenarios.py` (extend assertion logic)
- `core/bess/tests/unit/data/*.json` (add behavioral expected_results)
- `core/bess/tests/helpers.py` (new — shared test utilities)
- `core/bess/tests/conftest.py` (expose helpers as fixtures)

### Done when
- [ ] Scenario JSON files include strategic intent assertions
- [ ] `test_scenarios.py` validates both economic and behavioral expectations
- [ ] Physical constraint checks run on every scenario
- [ ] Standalone tests (`test_idle_solar_charging.py`, etc.) migrated to use shared helpers

---

## Phase 5: Deployment Verification (evaluate after Phase 4)

**Goal**: Automated deployment to real HA with smoke tests. Only pursue if
mock HA E2E (Phase 3) proves insufficient.

### 5.1 Decision criteria

Proceed with Phase 5 if any of these are true:
- Bugs slip through that mock HA E2E would not catch (HA ingress issues, supervisor lifecycle, real sensor failures)
- The agent pipeline produces PRs that pass all tests but break in real HA
- You want zero-touch releases (merge → deploy → verify → done)

### 5.2 Option C1: Self-hosted runner

```
Real HA (192.168.x.x)
  ├── GitHub Actions self-hosted runner
  ├── SMB share at /Volumes/addons/bess_manager
  └── HA Supervisor API at :8123

CI pipeline:
  unit-tests → e2e-mock → deploy-verify (self-hosted runner only)
    → package-addon.sh
    → rsync to SMB (like deploy.sh)
    → curl HA Supervisor API to restart add-on
    → wait for /api/health to return 200
    → run HTTP smoke tests against real HA ingress
    → report pass/fail
```

Infrastructure needed:
- Self-hosted runner on HA network (can be the HA box itself or a Pi)
- GitHub secrets: `HA_URL`, `HA_TOKEN`, `SMB_PATH`
- New endpoint: `GET /api/health` returning `{ version, uptime, last_cycle }`

### 5.3 Option C2: Container registry

```
CI pipeline:
  unit-tests → e2e-mock → build-push → deploy-verify
    → docker build + push to ghcr.io/johanzander/bess-manager:staging
    → curl HA Supervisor API: update add-on to staging tag
    → wait for add-on healthy
    → run smoke tests
```

Infrastructure needed:
- GHCR repository + push token
- HA configured to pull from GHCR (custom repository URL)
- GitHub secrets: `HA_URL`, `HA_TOKEN`, `GHCR_TOKEN`

### 5.4 Smoke test suite

```python
# tests/smoke/test_ha_deployment.py
def test_addon_starts():
    r = requests.get(f"{HA_URL}/api/health")
    assert r.status_code == 200
    assert r.json()["version"] == expected_version

def test_sensors_readable():
    r = requests.get(f"{HA_URL}/api/dashboard")
    assert r.status_code == 200
    assert r.json()["summary"] is not None

def test_optimization_cycle_completes():
    # Wait up to 120s for a cycle
    r = requests.get(f"{HA_URL}/api/system-health")
    assert r.json()["scheduler"]["last_run"] is not None
```

### 5.5 Safety

- Only run deploy-verify on merges to `main`, not on every PR
- Add rollback: if smoke tests fail, redeploy previous version from git tag
- Consider a dedicated staging HA instance to avoid disrupting production

### Files modified (when pursued)
- `backend/api.py` (add `/api/health` endpoint)
- `.github/workflows/ci.yml` (add deploy-verify job)
- `tests/smoke/` (new — deployment smoke tests)
- Self-hosted runner setup or GHCR configuration

---

## Verification Checklist (end state)

After all phases, the test pipeline should look like:

```
PR opened
  → CI: pytest (34+ files)              [Phase 1]
  → CI: frontend vitest (10+ files)      [Phase 2]
  → CI: Playwright E2E vs mock HA        [Phase 3]
  → CI: behavioral scenario assertions   [Phase 4]
  → (on merge) deploy to HA + smoke test [Phase 5]
```

The agent pipeline (issue → analyze → fix → PR) runs `quality-check.sh`
which includes pytest + frontend tests, and CI blocks merge if E2E fails.
No human intervention needed for routine fixes.
