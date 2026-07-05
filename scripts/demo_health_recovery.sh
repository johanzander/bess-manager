#!/bin/bash

# Demo for the health-check recovery banner (#215).
#
# Brings up the mock-HA E2E stack, breaks a sensor to trigger the live
# "critical issue" banner, then fixes it to trigger the dismissible
# "recovered" banner — the same manual test used to verify PR #239.
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

if ! command -v podman-compose >/dev/null 2>&1; then
    echo "❌ podman-compose not found on PATH."
    echo "   Install with: pip install --user podman-compose"
    echo "   Then add its bin dir (e.g. ~/Library/Python/<ver>/bin) to PATH."
    exit 1
fi

compose() {
    SCENARIO="ci-normal-day" BESS_PORT="$BESS_PORT" MOCK_HA_PORT="$MOCK_HA_PORT" \
        podman-compose -p "$PROJECT_NAME" -f docker-compose.ci.yml "$@"
}

cmd_up() {
    if [ ! -d "frontend/dist" ]; then
        echo "🔸 Building frontend (frontend/dist missing)..."
        (cd frontend && npm run build)
    fi
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
    echo "✅ Rechecked. Refresh the dashboard — expect the red banner gone,"
    echo "   replaced by an amber, dismissible 'Recovered From an Earlier Issue' banner"
    echo "   (only visible once no other active issues remain — ci-normal-day has"
    echo "   two unrelated pre-existing errors baked in; check /api/health-recoveries"
    echo "   directly if you want to see the recovery record in isolation)."
}

cmd_down() {
    compose down
    echo "🔸 Checking for unintended writes to the read-write settings fixture..."
    if ! git diff --quiet -- e2e/ci-bess-settings.json 2>/dev/null; then
        echo "⚠️  e2e/ci-bess-settings.json changed — revert with:"
        echo "     git checkout -- e2e/ci-bess-settings.json"
    fi
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
