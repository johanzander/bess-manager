#!/usr/bin/env bash
# Run E2E tests with automatic port allocation to avoid conflicts
# when multiple worktrees run simultaneously.
#
# Usage:
#   ./e2e/run-e2e.sh                          # run all tests (smoke + wizard)
#   ./e2e/run-e2e.sh --project=chromium       # run smoke tests only
#   ./e2e/run-e2e.sh --project=wizard         # run wizard tests only
#   BESS_PORT=8085 ./e2e/run-e2e.sh           # use a specific port
#
# Port derivation uses the same cksum approach as dev-run.sh so each
# worktree directory gets a stable, predictable port (8080-8179 range).

set -euo pipefail
cd "$(dirname "$0")/.."

# --- Port selection (same algorithm as dev-run.sh) ---
if [ -z "${BESS_PORT:-}" ]; then
  _hash=$(printf '%s' "$(basename "$(pwd)")" | cksum | awk '{print $1}')
  export BESS_PORT=$(( 8080 + _hash % 100 ))
fi
export MOCK_HA_PORT="${MOCK_HA_PORT:-$(( BESS_PORT + 100 ))}"

# Use a project name based on the directory to avoid container name collisions
export COMPOSE_PROJECT_NAME="bess-e2e-$(basename "$(pwd)")"

echo "========================================================"
echo "  E2E tests — BESS_PORT=${BESS_PORT}, MOCK_HA_PORT=${MOCK_HA_PORT}"
echo "  project=${COMPOSE_PROJECT_NAME}"
echo "========================================================"

# --- Ensure frontend is built ---
if [ ! -d frontend/dist ]; then
  echo "==> Building frontend..."
  (cd frontend && npm ci && npm run build)
fi

# --- Cleanup on exit ---
cleanup() {
  echo "==> Stopping environment..."
  docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.ci.yml down 2>/dev/null || true
}
trap cleanup EXIT

# --- Determine which projects to run ---
PLAYWRIGHT_ARGS=("$@")
RUN_CHROMIUM=false
RUN_WIZARD=false

if [ ${#PLAYWRIGHT_ARGS[@]} -eq 0 ]; then
  RUN_CHROMIUM=true
  RUN_WIZARD=true
else
  for arg in "${PLAYWRIGHT_ARGS[@]}"; do
    case "$arg" in
      *chromium*) RUN_CHROMIUM=true ;;
      *wizard*)   RUN_WIZARD=true ;;
    esac
  done
fi

# --- Phase 1: Smoke tests (normal day) ---
if [ "$RUN_CHROMIUM" = true ]; then
  echo "==> Phase 1: Starting environment (ci-normal-day)..."
  SCENARIO=ci-normal-day docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.ci.yml up -d
  echo "==> Waiting for BESS on port ${BESS_PORT}..."
  timeout 120 bash -c "until curl -sf http://localhost:${BESS_PORT}/api/settings > /dev/null 2>&1; do sleep 2; done"

  echo "==> Running smoke & page tests..."
  (cd e2e && BESS_PORT="$BESS_PORT" npx playwright test --project=chromium)

  docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.ci.yml down
fi

# --- Phase 2: Wizard tests (all scenario combinations) ---
if [ "$RUN_WIZARD" = true ]; then
  WIZARD_SCENARIOS=(
    "ci-wizard-nordpool-min"
    "ci-wizard-nordpool-sph"
    "ci-wizard-nordpool-solax"
    "ci-wizard-octopus"
    "ci-wizard-full"
    "ci-wizard-nordpool-hacs"
    "ci-wizard-octopus-sph"
    "ci-wizard-both-providers"
    "ci-wizard-growatt-modbus"
  )

  for scenario in "${WIZARD_SCENARIOS[@]}"; do
    # Reset settings to empty so wizard triggers fresh each time
    echo '{}' > ./e2e/ci-wizard-settings.json

    echo "==> Phase 2: Starting environment (${scenario})..."
    SCENARIO="$scenario" \
      BESS_SETTINGS=./e2e/ci-wizard-settings.json \
      BESS_OPTIONS=./e2e/ci-wizard-options.json \
      docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.ci.yml up -d
    echo "==> Waiting for BESS on port ${BESS_PORT}..."
    timeout 120 bash -c "until curl -sf http://localhost:${BESS_PORT}/api/setup/status > /dev/null 2>&1; do sleep 2; done"

    echo "==> Running wizard tests (${scenario})..."
    (cd e2e && BESS_PORT="$BESS_PORT" SCENARIO="$scenario" npx playwright test --project=wizard)

    docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.ci.yml down
  done
fi

echo ""
echo "========================================================"
echo "  All E2E tests passed!"
echo "========================================================"
