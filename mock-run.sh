#!/bin/bash
# Mock HA development environment — runs BESS against a synthetic Home Assistant server.
#
# Usage:
#   ./mock-run.sh 2026-03-24-225535      # replay from generated scenario
#
# To generate a replay scenario from a debug log:
#   python scripts/mock_ha/scenarios/from_debug_log.py docs/bess-debug-2026-03-24-225535.md
#   ./mock-run.sh 2026-03-24-225535
#
# Service call log (inverter writes, SOC limits, etc.):
#   http://localhost:8123/mock/service_log
#
# BESS dashboard:
#   http://localhost:8080

set -euo pipefail

if [ $# -eq 0 ]; then
  echo "Usage: ./mock-run.sh <scenario>"
  echo ""
  echo "Generate a scenario from a debug log first:"
  echo "  python scripts/mock_ha/scenarios/from_debug_log.py docs/bess-debug-YYYY-MM-DD-HHMMSS.md"
  echo ""
  echo "Available scenarios:"
  ls scripts/mock_ha/scenarios/*.json 2>/dev/null | sed 's/.*\///;s/\.json//' || echo "  (none)"
  exit 1
fi

SCENARIO=$1

# Verify scenario file exists
SCENARIO_FILE="scripts/mock_ha/scenarios/${SCENARIO}.json"
if [ ! -f "$SCENARIO_FILE" ]; then
  echo "Error: Scenario not found: $SCENARIO_FILE"
  exit 1
fi

# Extract bess_config from scenario JSON into a temp file for Docker volume mount
INVERTER_TYPE=$(python3 -c "import json; print(json.load(open('$SCENARIO_FILE')).get('inverter_type', 'min'))")
OPTIONS_FILE=$(mktemp /tmp/bess-options-XXXXXX)
python3 -c "
import json, sys
d = json.load(open('$SCENARIO_FILE'))
cfg = d.get('bess_config')
if not cfg:
    print('Error: No bess_config in scenario — regenerate with from_debug_log.py', file=sys.stderr)
    sys.exit(1)
json.dump(cfg, open('$OPTIONS_FILE', 'w'), indent=2)
" || exit 1
export OPTIONS_FILE
# Clean up temp file when the script exits
trap 'rm -f "$OPTIONS_FILE"' EXIT

# Load real InfluxDB credentials from .env if present — enables historical data
# collection when combined with a mock_time scenario (e.g. 2026-03-24-225535).
# HA_URL and HA_TOKEN are always overridden below regardless.
if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi

# Always use the mock HA server, never the real one
export HA_URL=http://mock-ha:8123
export HA_TOKEN=mock_token

echo "==== BESS Mock Development Environment ===="
echo "Scenario:      $SCENARIO"
echo "Inverter type: $INVERTER_TYPE  (bess_config extracted from scenario)"

# Verify Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "Error: Docker is not running. Please start Docker and try again."
  exit 1
fi

# Extract mock_time from scenario (empty string = real wall-clock time)
MOCK_TIME=$(python3 -c "import json; d=json.load(open('$SCENARIO_FILE')); print(d.get('mock_time',''))")
export MOCK_TIME
if [ -n "$MOCK_TIME" ]; then
  echo "Mock time:     $MOCK_TIME  (BESS will run as if it is this time)"
fi

# Build frontend
echo "Building frontend..."
(cd frontend && npm run build) || {
  echo "Warning: Frontend build failed — using existing dist if present"
}

export SCENARIO

echo "Stopping any existing containers..."
docker-compose \
  -f docker-compose.yml \
  -f docker-compose.mock.yml \
  down --remove-orphans

echo "Building and starting mock environment..."
docker-compose \
  -f docker-compose.yml \
  -f docker-compose.mock.yml \
  up --build -d

echo "Waiting for services to start..."
sleep 5

echo ""
echo "==== Mock Environment Running ===="
echo "  BESS UI:       http://localhost:8080"
echo "  Service log:   http://localhost:8123/mock/service_log"
echo "  Sensor state:  http://localhost:8123/mock/sensors"
echo ""
echo "Following logs... (Ctrl+C to stop)"
echo ""

docker-compose \
  -f docker-compose.yml \
  -f docker-compose.mock.yml \
  logs -f --no-log-prefix
