#!/bin/bash

# Demo for the health-check recovery banner (#215).
#
# Brings up the mock-HA E2E stack with a fully healthy baseline (a
# ci-normal-day.json variant with today's date and lifetime energy sensors
# added, and InfluxDB left unconfigured), so Battery Control is the ONLY
# thing that ever goes wrong. Breaks it to trigger the live "critical issue"
# banner, then fixes it to trigger the dismissible "recovered" banner — both
# visible directly in the browser, not just via the API.
#
# Usage: ./scripts/demo_health_recovery.sh [up|break|fix|down]
#   (no args) — runs the full up -> break -> fix sequence, leaves the stack running
#   up        — bring up the stack only
#   break     — mark the sensor unavailable and recheck (expect an active ERROR banner)
#   fix       — restore the sensor and recheck (expect the dismissible recovered banner)
#   down      — tear down the stack

set -e

if [ ! -f "CLAUDE.md" ]; then
    echo "❌ Error: run this script from the project root directory"
    exit 1
fi

PROJECT_NAME="health-recovery-demo"
BESS_PORT="${BESS_PORT:-18180}"
MOCK_HA_PORT="${MOCK_HA_PORT:-18123}"
SENSOR="number.growatt_battery_charging_power_rate"
SENSOR_ATTRS='{"unit_of_measurement": "%", "min": 0, "max": 100}'

GENERATED_SCENARIO="scripts/mock_ha/scenarios/demo-health-recovery.json"
# Must live under the repo (not /tmp) — podman machine only shares /Users
# into the VM, so a host path outside it 404s on mount even though it
# exists on the Mac side.
SCRATCH_DIR=".demo-scratch"
GENERATED_SETTINGS="$SCRATCH_DIR/settings.json"
GENERATED_OPTIONS="$SCRATCH_DIR/options.json"

if ! command -v podman-compose >/dev/null 2>&1; then
    echo "❌ podman-compose not found on PATH."
    echo "   Install with: pip install --user podman-compose"
    echo "   Then add its bin dir (e.g. ~/Library/Python/<ver>/bin) to PATH."
    exit 1
fi

compose() {
    SCENARIO="demo-health-recovery" BESS_PORT="$BESS_PORT" MOCK_HA_PORT="$MOCK_HA_PORT" \
        BESS_SETTINGS="$GENERATED_SETTINGS" BESS_OPTIONS="$GENERATED_OPTIONS" \
        podman-compose -p "$PROJECT_NAME" -f docker-compose.ci.yml "$@"
}

generate_fixtures() {
    mkdir -p "$SCRATCH_DIR"

    # ci-normal-day.json pinned to a fixed past date (mock_time), so on any
    # other day the Nordpool price lookup mismatches "today" and errors —
    # rewrite mock_time to today and add lifetime sensors (missing from the
    # base scenario) so Energy Monitoring passes too. Battery Control is then
    # the only thing this demo ever breaks.
    python3 - "$GENERATED_SCENARIO" <<'PYEOF'
import json
import sys
from datetime import datetime

out_path = sys.argv[1]
with open("scripts/mock_ha/scenarios/ci-normal-day.json") as f:
    scenario = json.load(f)

scenario["mock_time"] = datetime.now().strftime("@%Y-%m-%d 08:30:00")
scenario["sensors"].update({
    "sensor.growatt_lifetime_battery_charged": {"state": "1000", "attributes": {"unit_of_measurement": "kWh"}},
    "sensor.growatt_lifetime_battery_discharged": {"state": "900", "attributes": {"unit_of_measurement": "kWh"}},
    "sensor.growatt_lifetime_solar_energy": {"state": "2000", "attributes": {"unit_of_measurement": "kWh"}},
    "sensor.growatt_lifetime_import_from_grid": {"state": "1500", "attributes": {"unit_of_measurement": "kWh"}},
    "sensor.growatt_lifetime_export_to_grid": {"state": "300", "attributes": {"unit_of_measurement": "kWh"}},
    "sensor.growatt_lifetime_load_consumption": {"state": "3000", "attributes": {"unit_of_measurement": "kWh"}},
})

with open(out_path, "w") as f:
    json.dump(scenario, f, indent=2)
PYEOF

    python3 - "$GENERATED_SETTINGS" <<'PYEOF'
import json
import sys

out_path = sys.argv[1]
with open("e2e/ci-bess-settings.json") as f:
    settings = json.load(f)

settings["sensors"]["growatt_server_min"].update({
    "lifetime_battery_charged": "sensor.growatt_lifetime_battery_charged",
    "lifetime_battery_discharged": "sensor.growatt_lifetime_battery_discharged",
    "lifetime_solar_energy": "sensor.growatt_lifetime_solar_energy",
    "lifetime_import_from_grid": "sensor.growatt_lifetime_import_from_grid",
    "lifetime_export_to_grid": "sensor.growatt_lifetime_export_to_grid",
    "lifetime_load_consumption": "sensor.growatt_lifetime_load_consumption",
})

with open(out_path, "w") as f:
    json.dump(settings, f, indent=2)
PYEOF

    python3 - "$GENERATED_OPTIONS" <<'PYEOF'
import json
import sys

out_path = sys.argv[1]
with open("e2e/ci-options.json") as f:
    options = json.load(f)

# Leave InfluxDB unconfigured so "Historical Data Access" is NOT_CONFIGURED
# (silently skipped) instead of an active WARNING.
options["influxdb"] = {"url": "", "bucket": "", "username": "", "password": ""}

with open(out_path, "w") as f:
    json.dump(options, f, indent=2)
PYEOF
}

cmd_up() {
    if [ ! -d "frontend/dist" ]; then
        echo "🔸 Building frontend (frontend/dist missing)..."
        (cd frontend && npm run build)
    fi
    echo "🔸 Generating a fully healthy baseline scenario (today's date, lifetime sensors, no InfluxDB)..."
    generate_fixtures
    echo "🔸 Starting stack on http://localhost:$BESS_PORT (mock-HA on $MOCK_HA_PORT)..."
    compose up -d --build
    echo "✅ Up. Open http://localhost:$BESS_PORT in a browser, then run:"
    echo "     ./scripts/demo_health_recovery.sh break"
    echo "     ./scripts/demo_health_recovery.sh fix"
}

cmd_break() {
    echo "🔸 Marking $SENSOR unavailable..."
    curl -s -X POST "http://localhost:$MOCK_HA_PORT/mock/update_sensor/$SENSOR" \
        -H "Content-Type: application/json" \
        -d "{\"state\": \"unavailable\", \"attributes\": $SENSOR_ATTRS}" >/dev/null
    curl -s -X POST "http://localhost:$BESS_PORT/api/system-health/recheck" >/dev/null
    echo "✅ Rechecked. Refresh the dashboard — expect a red, non-dismissible"
    echo "   'Critical System Issues Detected' banner for Battery Control."
}

cmd_fix() {
    echo "🔸 Restoring $SENSOR..."
    curl -s -X POST "http://localhost:$MOCK_HA_PORT/mock/update_sensor/$SENSOR" \
        -H "Content-Type: application/json" \
        -d "{\"state\": \"100\", \"attributes\": $SENSOR_ATTRS}" >/dev/null
    curl -s -X POST "http://localhost:$BESS_PORT/api/system-health/recheck" >/dev/null
    echo "✅ Rechecked. Refresh the dashboard — expect the red banner gone, replaced"
    echo "   by an amber, dismissible 'Recovered From an Earlier Issue' banner."
}

cmd_down() {
    compose down
    rm -rf "$SCRATCH_DIR" "$GENERATED_SCENARIO"
}

case "${1:-}" in
    up) cmd_up ;;
    break) cmd_break ;;
    fix) cmd_fix ;;
    down) cmd_down ;;
    "")
        cmd_up
        sleep 2
        cmd_break
        sleep 1
        cmd_fix
        echo ""
        echo "🔸 Stack still running. Tear down with: ./scripts/demo_health_recovery.sh down"
        ;;
    *)
        echo "Usage: $0 [up|break|fix|down]"
        exit 1
        ;;
esac
