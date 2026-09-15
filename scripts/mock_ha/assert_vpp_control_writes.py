#!/usr/bin/env python3
"""Assert mock HA's service log recorded the startup Growatt VPP register writes.

Used by the "Growatt VPP" E2E phase (issue #538) to prove a period apply
actually reached mock HA, not just that the schedule built without error.
_ensure_vpp_status_enabled (core/bess/solax_modbus_growatt_controller.py)
enables these two registers unconditionally on every startup, regardless of
which strategic intent the optimizer picks for the current period — the one
VPP write guaranteed to happen on every run.

Polls /api/dashboard on the BESS backend until startup completes before
checking the log: that write happens inside update_battery_schedule(), which
is what flips startup_complete (backend/app.py), and /api/dashboard is the
one endpoint that reports "initializing" honestly while it's still running --
/api/dashboard-health-summary returns 200 throughout startup regardless
(backend/api.py), so gating on it races the write on a slow runner.

Usage: assert_vpp_control_writes.py <mock-ha-base-url> [bess-base-url]
"""

import json
import sys
import time
import urllib.request

EXPECTED = [
    "select.growatt_min_vpp_status",
    "select.growatt_min_vpp_allow_ac_charging",
]

STARTUP_TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 2


def wait_for_startup_complete(bess_base_url: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{bess_base_url}/api/dashboard") as response:
                body = json.load(response)
            if body.get("error") != "initializing":
                return
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"BESS did not finish startup within {STARTUP_TIMEOUT_SECONDS}s "
        f"({bess_base_url}/api/dashboard still reports initializing)"
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    mock_ha_base_url = sys.argv[1]
    bess_base_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8080"

    wait_for_startup_complete(bess_base_url)

    with urllib.request.urlopen(f"{mock_ha_base_url}/mock/service_log") as response:
        log = json.load(response)

    missing = [
        entity_id
        for entity_id in EXPECTED
        if not any(
            entry.get("domain") == "select"
            and entry.get("service") == "select_option"
            and entry.get("data", {}).get("entity_id") == entity_id
            and entry.get("data", {}).get("option") == "Enabled"
            for entry in log
        )
    ]
    if missing:
        print(f"Missing expected Growatt VPP register write(s): {missing}")
        return 1

    print("Growatt VPP register writes confirmed in mock HA service log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
