# BESS Manager Development Guide

This guide helps you set up a development environment for the BESS Battery Manager add-on.

## Documentation

- **[SOFTWARE_DESIGN.md](SOFTWARE_DESIGN.md)** — Architecture, components, and data flow
- **[INSTALLATION.md](INSTALLATION.md)** — Add-on installation and sensor configuration
- **[USER_GUIDE.md](USER_GUIDE.md)** — Dashboard and interface guide
- **[CLAUDE.md](../CLAUDE.md)** — Coding guidelines and architecture conventions for Claude Code
- **[TODO.md](../TODO.md)** — Prioritized improvements and known issues

## Development Environment Setup

### Prerequisites

- Docker and Docker Compose
- Node.js 18 or higher
- Home Assistant instance (local or network-accessible)
- A long-lived access token from Home Assistant

### HomeAssistant Environment Options

The BESS Manager can be developed using either a local or production HomeAssistant instance:

#### Local Development

When running HomeAssistant locally (e.g., on `localhost:8123`):

- Set `HA_URL=http://localhost:8123` in `.env`

- No token is required when running both services locally

- Useful for rapid development and testing

#### Production Environment

When using a remote/production HomeAssistant:

- Set `HA_URL` to your HomeAssistant URL

- Generate and set a long-lived access token in `HA_TOKEN`

- Enables testing with real production data

Example `.env` configuration:

```bash

# Local development

HA_URL=http://localhost:8123
HA_TOKEN=  # Not needed for local development

# OR Production environment

HA_URL=https://your-ha-instance.com
HA_TOKEN=your_long_lived_access_token_here
```text

### Initial Setup

1. Clone the Repository:

   ```bash
   git clone https://github.com/johanzander/bess-manager.git
   cd bess-manager
```text

2. Create Environment File:

   ```bash

   # Create .env in root directory

   HA_URL=http://host.docker.internal:8123
   HA_TOKEN=your_long_lived_access_token_here
   FLASK_DEBUG=true
   PORT=8080

   # Optional database settings

   HA_DB_URL=http://homeassistant.local:8086/api/v2/query
   HA_DB_USER_NAME=your_db_username
   HA_DB_PASSWORD=your_db_password
```text

3. Install frontend dependencies:

   ```bash
   cd frontend && npm install && cd ..
   ```

4. Start the development environment:

   ```bash
   ./dev-run.sh
   ```

   This will build the frontend, then build and start the backend container via Docker Compose.

### Running the Development Environment

Start all services with:

```bash
./dev-run.sh
```

Access the services:

- BESS backend + UI: [http://localhost:8080](http://localhost:8080)
- Vite dev server (hot-reload): [http://localhost:5174](http://localhost:5174)

### VS Code Integration

If using VS Code with Remote-Containers:

1. Open the project in VS Code

2. Click the remote connection button (bottom-left corner)

3. Select "Remote-Containers: Reopen in Container"

## Project Structure

```text
├── backend/           # FastAPI application and add-on config
├── core/             # Core BESS system implementation
│   └── bess/         # BESS-specific modules
│       ├── tests/    # Test directory
│       └── ...       # Implementation modules
├── frontend/         # React-based web interface
└── build/           # Build output (created by package-addon.sh)
    ├── bess_manager/ # Add-on build
    └── repository/   # Repository build
```text

## Development Workflow

### API Development

1. Add new endpoints in `backend/app.py`

2. Update OpenAPI spec if needed

3. Generate frontend API client:

   ```bash
   cd frontend
   npm run generate-api
```text

### Frontend Development

1. Navigate to `frontend/`

2. Make changes to React components

3. Changes hot-reload automatically

4. Build for production:

   ```bash
   npm run build
```text

### Testing

```bash
# Fast tests only (recommended during development, ~3s)
pytest -m "not slow"

# Algorithm/integration tests (full optimizer, ~30min)
pytest -m slow

# Run all tests
pytest

# Run specific categories
pytest core/bess/tests/unit/
pytest core/bess/tests/integration/
pytest backend/tests/

# Run with coverage
pytest --cov=core.bess

# Frontend unit tests
cd frontend && npm test

# E2E tests (requires docker-compose environment running)
cd e2e && npx playwright test --project=chromium
```

Tests are split using `pytest.mark.slow`. The fast set covers backend API and
non-optimizer unit tests. The slow set runs the full DP algorithm and integration
scenarios.

#### Plan-faithfulness simulator (`R == P`)

The savings the optimizer reports are a *plan* — derived from the battery
*actions* it chooses. The real inverter is driven by coarse *modes*
(`load_first` / `grid_first` / `battery_first`), which are policies, not exact
power setpoints, so a plan can claim economics the hardware can't actually
deliver. The plan-faithfulness simulator in `core/bess/simulation/` executes a
plan through a model of the inverter and computes the **realized** economics,
asserting they match the plan (`R == P`). It runs as a pure unit test — no
hardware, no mock HA.

This is a strong correctness tool: it already caught the solar-export
over-crediting bug (savings inflated ~8–16% on sunny days, fixed in 9.6.0) and a
discharge-pacing limitation — both invisible to plan-only tests. If you change
the optimizer or inverter control, verify `R == P` still holds. Deep reference:
[`docs/agents/simulator.md`](agents/simulator.md).

### E2E Tests (Playwright)

End-to-end tests run a full browser against the backend + mock HA stack:

```bash
# Start the test environment
SCENARIO=ci-normal-day docker compose -f docker-compose.ci.yml up -d

# Wait for BESS to be ready
until curl -sf http://localhost:8080/api/settings > /dev/null; do sleep 2; done

# Run all E2E tests (smoke + pages + API contracts)
cd e2e && npx playwright test --project=chromium

# Run only wizard tests (requires wizard scenario)
cd e2e && npx playwright test --project=wizard

# Stop environment
docker compose -f docker-compose.ci.yml down
```

**Running multiple worktrees without port conflicts:**

```bash
# Automatic — finds free ports and isolates containers per-worktree
./e2e/run-e2e.sh                       # all tests
./e2e/run-e2e.sh --project=chromium    # smoke only
./e2e/run-e2e.sh --project=wizard      # wizard only

# Manual — pick a port to avoid collisions with other worktrees
BESS_PORT=8085 MOCK_HA_PORT=8185 docker compose -p my-branch -f docker-compose.ci.yml up -d
BESS_PORT=8085 npx playwright test --project=chromium
```

The `BESS_PORT` env var is used by both `docker-compose.ci.yml` (host port mapping)
and `playwright.config.ts` (base URL). The `-p` flag gives each environment its own
container namespace so names don't collide.

**E2E test structure:**

| Spec file | What it tests |
|-----------|---------------|
| `api-smoke.spec.ts` | All API endpoints return 200 |
| `api-contracts.spec.ts` | Response shapes the frontend depends on |
| `dashboard.spec.ts` | Dashboard loading, content, resolution selector |
| `navigation.spec.ts` | All routes load without errors |
| `settings-page.spec.ts` | Tab navigation, form editing, save persistence |
| `inverter-page.spec.ts` | Schedule overview, TOU intervals, intents |
| `savings-page.spec.ts` | View modes, resolution, cost display |
| `mock-ha.spec.ts` | Mock HA connectivity and inverter commands |
| `setup-wizard.spec.ts` | Full wizard flow with auto-discovery |

### Docker Build Verification

To verify the production Docker image builds correctly and the app starts:

```bash
docker compose -f docker-compose.prod-test.yml up -d --build
curl http://localhost:8080/api/system-health
docker compose -f docker-compose.prod-test.yml down
```

This builds the real `Dockerfile` (which explicitly lists backend files to COPY)
and boots it with mock-HA. Catches missing files that would cause runtime
`ImportError` in production. Use `BESS_PORT=8081` if port 8080 is in use.

### CI Pipeline

CI runs on every PR (`.github/workflows/ci.yml`):

| Job | Trigger | What it runs |
|-----|---------|-------------|
| **Fast tests** | `backend/` or `core/` changed | `pytest -m "not slow"` (~3s, 333 tests) |
| **Algorithm tests** | `core/bess/` changed | `pytest -m slow` (~30min, 116 tests) |
| **Frontend checks** | `frontend/` changed | `npm test` + type-check + lint |
| **E2E tests** | backend/frontend/e2e/docker changed | Playwright against docker-compose mock HA (2 phases: smoke + wizard) |
| **Code quality** | Always | Black + Ruff formatting/linting |
| **Docker build & boot** | backend/frontend/Dockerfile changed | Production image boots and responds |

The quality gate script (`scripts/quality-check.sh`) runs fast tests + linting
and is used by the automated issue-fix bot.

### Code Quality

```bash

# Format code

black .
ruff check --fix .

# Type checking

mypy .

# Run all pre-commit hooks

pre-commit run --all-files
```text

## Debugging

### Backend Debugging

- Logs are available via:

  ```bash
  docker-compose logs -f
```text

- Set `FLASK_DEBUG=true` in `.env` for debug mode

### Frontend Debugging

- Use browser developer tools

- React Developer Tools extension recommended

- Source maps enabled in development

### Common Issues

1. Connection Issues:

   - Verify access token validity

   - Check `HA_URL` configuration

   - Ensure Docker network connectivity

2. Import Errors:

   - Verify `requirements.txt` is complete

   - Rebuild container: `docker-compose down && docker-compose up -d`

3. API Errors:

   - Check logs for detailed messages

   - Verify required Home Assistant entities exist

   - Check access token permissions

## Deploying to a Local Home Assistant Instance

This is the developer workflow for testing a built add-on on real hardware before publishing.
Normal users should install from the GitHub repository — see [INSTALLATION.md](INSTALLATION.md).

**Prerequisites:** Node.js 18 or higher (required to build the frontend).

1. Build the add-on package:

   ```bash
   chmod +x package-addon.sh
   ./package-addon.sh
   ```

   This runs `npm ci && npm run build` locally, then assembles the add-on into `build/bess_manager/`.

2. Transfer files to Home Assistant:
   - Copy `build/bess_manager/` contents to `/addons/bess_manager/` on the HA host
   - Via SSH, Samba, or the File Editor add-on

3. Install the local add-on:
   - Settings → Add-ons → Reload
   - Find "BESS Battery Manager" under Local add-ons
   - Click "Install"

## Mock HA Development Environment

The mock HA environment lets you run the full BESS stack (backend + frontend) without a
real Home Assistant instance or inverter. BESS runs unmodified — only `HA_URL` is pointed
at a local mock server that serves synthetic sensor data and records service calls.

### Quick Start

Generate a scenario from a debug log, then run it:

```bash
python scripts/mock_ha/scenarios/from_debug_log.py bess-debug-2026-03-24-225535.md
./mock-run.sh 2026-03-24-225535
```

To replay from a specific time of day (useful for testing optimizer behavior at
a particular hour), pass an optional `HH:MM` argument:

```bash
./mock-run.sh 2026-04-22-202249 09:00    # run as if it is 09:00 on that date
```

The date is kept from the scenario; only the time is overridden.

- BESS UI: <http://localhost:8080>
- Service call log (inverter writes): <http://localhost:8123/mock/service_log>
- Sensor states: <http://localhost:8123/mock/sensors>

### How It Works

```
BESS container (unmodified)
    ↓ HA_URL=http://mock-ha:8123
mock-ha container (FastAPI)
  → GET  /api/states/{entity_id}      → sensor state from scenario JSON
  → POST /api/services/{domain}/{svc} → record call, return canned response
  → GET  /mock/service_log            → inspect what was written to inverter
```

The mock server loads a scenario JSON at startup. BESS reads sensors and writes
schedules exactly as it would against real HA — the mock records every service call
so you can verify what the optimizer decided to send to the inverter.

### Scenarios

Scenarios live in `scripts/mock_ha/scenarios/` and are named after the debug log
timestamp they were generated from (e.g. `2026-03-24-225535.json`). Each scenario
contains:

- `sensors` — all HA entity states BESS will read
- `inverter_type` — `"min"` or `"sph"`, determines which inverter service calls BESS uses
- `mock_time` — frozen wall-clock time (e.g. `"@2026-03-24 22:55:35"`); BESS
  believes it is running at this time via `libfaketime`
- `time_segments` — inverter TOU state at time of capture (active segments only;
  disabled slots are not reconstructable from debug logs)

### BESS Config

The entire scenario — sensor states, inverter type, and BESS config (entity ID
mappings, battery settings, inverter config) — is generated from the debug log.
`mock-run.sh` mounts `bess_config` as `/data/options.json` in the BESS container.

### Generating a Debug Log

**Option A — System Health page:** Open the BESS UI, go to System Health, and click
the **Export Debug Data** button. Save the downloaded `.md` file anywhere accessible.

**Option B — Via Claude Code (MCP):** With a running BESS instance and the MCP server
configured, ask Claude to fetch and generate a scenario in one step:

> "Fetch the current BESS debug log and generate a mock scenario from it"

Claude will use `fetch_live_debug` (saves to `.bess-logs/`) then run
`from_debug_log.py` automatically. No manual download needed.

### Replay from Debug Log

The `from_debug_log.py` script extracts everything needed for a faithful replay:

- Battery SOC (converted from `initial_soe` / `total_capacity`)
- Nordpool prices — from `### Price Data` in new-style logs (exact quarterly values),
  or reverse-calculated from marked-up `buy_price` in old logs
- Solar forecast from `full_solar_production`
- Inverter TOU segments from `## Inverter TOU Segments` (new-style logs)
- Frozen timestamp from the debug log filename

```bash
# Generate scenario from a saved debug log
python scripts/mock_ha/scenarios/from_debug_log.py bess-debug-YYYY-MM-DD-HHMMSS.md

# Run replay — BESS runs as if it is that exact moment in time
./mock-run.sh YYYY-MM-DD-HHMMSS

# Run replay from a specific time (e.g. to test optimizer before solar hours)
./mock-run.sh YYYY-MM-DD-HHMMSS 09:00
```

### Debug Log Export

The debug log includes:

- `### Price Data` — full raw Nordpool quarterly prices for both days, enabling
  exact replay without reverse-calculating through the markup formula
- `## Inverter TOU Segments` — active TOU slots held in memory, mirroring the
  current hardware state

## Automated Agent Workflow

GitHub issues are handled by a three-stage automated pipeline. See
`docs/agents/workflow.md` for the full process description.

### Stage 1 — Triage (automatic on every new issue)

`.github/workflows/issue-triage.yml` fires when an issue is opened. It
classifies the issue (bug / feature / question) and applies labels. For bugs
without debug info it posts instructions for getting a BESS debug export. For
bugs with debug info it posts an initial root-cause analysis immediately.

When a user replies with a debug log on a `needs-debug-log` issue, the workflow
fires again automatically and runs deeper analysis.

### Stage 2 — Fix (triggered by `@claude-bot`)

Commenting `@claude-bot fix this` on an issue triggers
`.github/workflows/claude-bot.yml`, which runs `scripts/issue_fixer.py`. The
bot explores the codebase, implements a fix, runs `pytest`, and opens a draft
PR. It will attempt to fix test failures before opening the PR.

### Stage 3 — Review (triggered by `@claude-bot` on a PR)

Commenting `@claude-bot` on a PR triggers `scripts/pr_reviewer.py`, which
reviews the diff against `docs/agents/rules.md` and `docs/agents/architecture.md`
and posts a review comment.

**Human gate**: Draft PRs are never merged automatically. You approve and merge.

### Agent Documentation

The `docs/agents/` directory contains focused files loaded into agent system prompts:

| File | Purpose |
|------|---------|
| `rules.md` | Hard constraints (loaded by every agent) |
| `architecture.md` | Component map and key files (agent summary) |
| `patterns.md` | Code patterns with good/bad examples |
| `testing.md` | Test philosophy and mock HA bug reproduction |
| `workflow.md` | PR/release process and label conventions |

### Testing Philosophy

Tests must verify **behavior** (what the system does), not **implementation**
(how it does it). A test that breaks when you swap two equivalent algorithms is
a bad test. See `docs/agents/testing.md` for full guidance and examples.

## Claude Code Integration

BESS Manager includes an MCP (Model Context Protocol) server for integration with Claude Code,
enabling AI-assisted debugging and log analysis.

To enable, add to `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "bess": {
      "command": "python3",
      "args": ["scripts/bess-mcp-server.py"]
    }
  }
}
```

Configure connection in `.env`:

```bash
HA_URL=https://your-homeassistant-url
HA_TOKEN=your-long-lived-access-token
```
