---
name: verify
description: Stand up the real mock-HA + backend E2E stack locally and drive it to observe a change working, instead of just running tests.
---

# BESS Manager local E2E verification

Use `docker-compose.ci.yml` (works with `podman-compose`) to run the real
backend against a scripted mock Home Assistant instance, then hit the actual
HTTP API (or load the served frontend) to observe the change.

## One-time setup

- `podman-compose` isn't always on PATH: `pip install --user podman-compose`,
  then add `~/Library/Python/<ver>/bin` to PATH for the shell session.
  `podman compose` (the built-in plugin) does NOT work here — it looks for a
  `docker-compose`/`podman-compose` binary and fails without one.
- Backend container serves the frontend from a bind-mounted `frontend/dist`
  (`./frontend/dist:/app/frontend:ro`). Build it first or the container
  crashes on `StaticFiles` init: `cd frontend && npm run build`.

## Bring the stack up

Use a unique project name (`-p`) and non-default ports so it doesn't collide
with another worktree's running stack:

```bash
SCENARIO=ci-normal-day BESS_PORT=18180 MOCK_HA_PORT=18123 \
  podman-compose -p <unique-name> -f docker-compose.ci.yml up -d --build
```

Wait for both containers healthy (`podman ps --filter name=<unique-name>`),
then hit the real API:

```bash
curl -s http://localhost:18180/api/system-health
curl -s http://localhost:18180/api/dashboard-health-summary
```

## Driving live sensor changes

`scripts/mock_ha/server.py` exposes `POST /mock/update_sensor/{entity_id}` to
mutate a sensor's state on the running mock-HA at any time (no restart
needed) — this is the way to observe a *transition* (e.g. a sensor going
unavailable then recovering) through the real system, since a fresh
container/process has no "previous" state to transition from:

```bash
curl -s -X POST http://localhost:18123/mock/update_sensor/number.growatt_battery_charging_power_rate \
  -H "Content-Type: application/json" -d '{"state": "unavailable", "attributes": {...}}'
curl -s -X POST http://localhost:18180/api/system-health/recheck   # observe the break
curl -s -X POST http://localhost:18123/mock/update_sensor/number.growatt_battery_charging_power_rate \
  -H "Content-Type: application/json" -d '{"state": "100", "attributes": {...}}'
curl -s -X POST http://localhost:18180/api/system-health/recheck   # observe the recovery
```

Get the full current sensor snapshot with `GET /mock/sensors` on the mock-HA
port to find real entity IDs/attributes to restore.

## Gotchas

- `${BESS_SETTINGS:-./e2e/ci-bess-settings.json}` is mounted **read-write**
  (no `:ro`). Running the app against it can silently write settings back
  into the fixture (schema migrations, demo_mode defaults, etc). After
  tearing down: `git diff -- e2e/` and `git checkout -- e2e/` if the only
  changes are ones you didn't intend.
- Many scenarios (e.g. `ci-wizard-entsoe.json`) pin `mock_time` to a fixed
  past date (`ci-normal-day.json` → `2025-01-15`), not "today" — the real
  container clock is today's date, so date-anchored service calls (Nordpool
  `get_prices_for_date`) mismatch and the DP scheduler logs "No prices for
  <today>". `backend/Dockerfile.dev` installs `libfaketime` for this; recreate
  the `bess` container manually (not via compose) with
  `-e LD_PRELOAD=/usr/lib/aarch64-linux-gnu/faketime/libfaketime.so.1
  -e FAKETIME="2025-01-15 12:00:00"` and the same network/volumes/env, confirm
  with `podman exec <container> date`. Note this only helps a *fresh* process
  — it won't recover in-memory state accumulated before the restart (e.g. a
  pending health-check transition), since restarting always wipes
  process memory.
- Verifying a bundled frontend UI string without a browser: fetch the served
  JS bundle and grep for the new text —
  `curl -s http://localhost:<port>/ | grep -o '/assets/main-[^"]*\.js'` then
  `curl -s http://localhost:<port><that path> | grep -o '<new UI string>'`
  confirms the exact deployed artifact contains the change, even without a
  headless browser available.
- Tear down: `podman-compose -p <unique-name> -f docker-compose.ci.yml down`.

## Mock-HA entity registry

Only exposed via WebSocket (`config/entity_registry/list`), not REST — to
verify registry-based sensor discovery, go through the real backend endpoint
that calls it (e.g. `POST /api/setup/discover`) rather than curling mock-HA
directly.
