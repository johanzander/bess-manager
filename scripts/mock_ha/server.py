"""Mock Home Assistant REST API server for BESS development and testing.

Serves synthetic sensor data and records service calls (inverter writes, SOC
limit changes, switch toggles) so the full BESS stack can run without a real
Home Assistant instance.

Usage:
    SCENARIO=2026-03-24-225535 uvicorn scripts.mock_ha.server:app --port 8123
    # or via docker-compose.mock.yml
"""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [mock-ha] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mock Home Assistant API")


@app.middleware("http")
async def log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Log every HA API state read so you can see what BESS is querying."""
    response = await call_next(request)
    path = request.url.path
    # Only log HA state reads — skip mock control endpoints and service calls
    # (service calls are already logged in call_service)
    if path.startswith("/api/states/"):
        entity_id = path[len("/api/states/") :]
        logger.info("GET %-60s → %d", entity_id, response.status_code)
    return response


# Mutable state — populated at startup from scenario file
_sensors: dict[str, Any] = {}
_time_segments: list[dict] = []
_ac_charge_times: dict[str, Any] = {}
_ac_discharge_times: dict[str, Any] = {}
_service_log: list[dict] = []
# Nordpool prices keyed by date string "YYYY-MM-DD" → list of quarterly prices (SEK/kWh)
_nordpool_prices: dict[str, list[float]] = {}
# IANA timezone name for this scenario (e.g. "Europe/Stockholm")
_timezone: str = "UTC"
# WebSocket registry data — populated from scenario or auto-generated from sensors
_entity_registry: list[dict] = []
_config_entries: list[dict] = []
_devices: list[dict] = []
_services: dict[str, Any] = {}


def _generate_entity_registry(inverter_type: str) -> list[dict]:
    """Auto-generate entity registry entries from _sensors dict.

    Infers the HA integration platform from the inverter_type and sensor
    entity IDs so that BESS auto-discovery can detect the integration.
    """
    platform_map = {
        "growatt_server_min": "growatt_server",
        "growatt_server_sph": "growatt_server",
        "solax_modbus_growatt_min": "solax_modbus",
        "solax_modbus_growatt_sph": "solax_modbus",
        "solax_modbus_native": "solax_modbus",
    }
    inverter_platform = platform_map.get(inverter_type, "growatt_server")

    entries: list[dict] = []
    for entity_id in _sensors:
        # Determine platform from entity_id patterns
        platform = inverter_platform  # default: assume inverter entity
        if "nordpool" in entity_id:
            platform = "nordpool"
        elif "solcast" in entity_id:
            platform = "solcast_solar"
        elif "weather." in entity_id:
            platform = "weather"
        elif entity_id.startswith("sensor.current_l"):
            platform = "homeassistant"
        elif entity_id.startswith("sensor.48h_"):
            platform = "homeassistant"

        entries.append(
            {
                "entity_id": entity_id,
                "platform": platform,
                "unique_id": entity_id.replace(".", "_"),
            }
        )
    return entries


def _generate_config_entries(scenario: dict) -> list[dict]:
    """Generate synthetic config entries for auto-discovery."""
    entries = []
    inverter_type = scenario.get("inverter_type", "min")

    # Nordpool config entry (needed for nordpool_config_entry_id)
    if any("nordpool" in k for k in _sensors):
        entries.append(
            {
                "entry_id": "mock_nordpool_config_entry",
                "domain": "nordpool",
                "title": "Nordpool",
                "state": "loaded",
            }
        )

    # Inverter config entry
    if inverter_type in ("growatt_server_min", "growatt_server_sph"):
        entries.append(
            {
                "entry_id": "mock_growatt_config_entry",
                "domain": "growatt_server",
                "title": "Growatt Server",
                "state": "loaded",
            }
        )
    elif inverter_type in (
        "solax_modbus_growatt_min",
        "solax_modbus_growatt_sph",
        "solax_modbus_native",
    ):
        entries.append(
            {
                "entry_id": "mock_solax_config_entry",
                "domain": "solax_modbus",
                "title": "SolaX Modbus",
                "state": "loaded",
            }
        )

    return entries


def _generate_services(inverter_type: str) -> dict:
    """Generate synthetic service list for inverter type detection."""
    services: dict[str, Any] = {}

    if inverter_type in ("growatt_server_min", "growatt_server_sph"):
        growatt_services: dict[str, Any] = {}
        # MIN uses update_time_segment, SPH uses write_ac_charge_times
        if inverter_type == "growatt_server_min":
            growatt_services["update_time_segment"] = {}
            growatt_services["read_time_segments"] = {}
        else:
            growatt_services["write_ac_charge_times"] = {}
            growatt_services["read_ac_charge_times"] = {}
            growatt_services["write_ac_discharge_times"] = {}
            growatt_services["read_ac_discharge_times"] = {}
        services["growatt_server"] = growatt_services

    # solax_modbus platforms use entity-based control — no
    # growatt_server services needed. Detection relies on entity
    # registry suffixes (TOU time_1_enabled vs VPP remotecontrol_*).

    return services


def _load_scenario() -> None:
    """Load scenario JSON from /scenarios/{SCENARIO}.json."""
    scenario_name = os.environ.get("SCENARIO", "")
    scenario_path = Path(f"/scenarios/{scenario_name}.json")

    if not scenario_path.exists():
        # Try relative path for local development (outside Docker)
        scenario_path = Path(__file__).parent / "scenarios" / f"{scenario_name}.json"

    if not scenario_path.exists():
        raise FileNotFoundError(
            f"Scenario file not found: {scenario_path}. "
            "Set SCENARIO env var to a file in scripts/mock_ha/scenarios/."
        )

    with scenario_path.open() as f:
        scenario = json.load(f)

    global _timezone
    _sensors.update(scenario.get("sensors", {}))
    _time_segments.extend(scenario.get("time_segments", []))
    _ac_charge_times.update(scenario.get("ac_charge_times", {}))
    _ac_discharge_times.update(scenario.get("ac_discharge_times", {}))
    _timezone = scenario.get("timezone", "UTC")

    # Build nordpool prices lookup for the mock get_prices_for_date service call.
    # Prices can come from two sources:
    #   1. Nordpool sensor attributes (today/tomorrow) — for nordpool/nordpool_official when sensor exists
    #   2. price_data field — explicit fallback for nordpool_official (no sensor state to capture)
    # mock_time format: "@YYYY-MM-DD HH:MM:SS" — extract the date as the reference "today".
    # Note: only ref_date and ref_date+1 are populated; requests for any other date return {}.
    mock_time_str = scenario.get("mock_time", "")
    m = re.search(r"@(\d{4}-\d{2}-\d{2})", mock_time_str)
    if m:
        ref_date = date.fromisoformat(m.group(1))
        nordpool_sensor = next(
            (v for k, v in _sensors.items() if "nordpool" in k and isinstance(v, dict)),
            None,
        )
        if nordpool_sensor:
            attrs = nordpool_sensor.get("attributes", {})
            today_prices = attrs.get("today", [])
            tomorrow_prices = attrs.get("tomorrow", [])
        if not nordpool_sensor or (not today_prices and not tomorrow_prices):
            # nordpool_official uses service calls — sensor may exist but won't
            # carry today/tomorrow price arrays. Fall back to price_data.
            price_data = scenario.get("price_data", {})
            today_prices = price_data.get("today", [])
            tomorrow_prices = price_data.get("tomorrow", [])
        if today_prices:
            _nordpool_prices[ref_date.isoformat()] = today_prices
        if tomorrow_prices:
            _nordpool_prices[(ref_date + timedelta(days=1)).isoformat()] = (
                tomorrow_prices
            )
        if _nordpool_prices:
            summary = ", ".join(
                f"{d} ({len(p)} periods)" for d, p in _nordpool_prices.items()
            )
            logger.info("Nordpool prices loaded: %s", summary)
        else:
            logger.warning(
                "No nordpool prices found in scenario — price fetches will return empty"
            )
    else:
        # mock_time is required — without it we cannot anchor prices to a date and
        # BESS will run against real wall-clock time with no price data.
        # Regenerate the scenario with from_debug_log.py to fix this.
        raise ValueError(
            f"Scenario '{scenario_name}' has no mock_time. "
            "Regenerate it with: "
            "python scripts/mock_ha/scenarios/from_debug_log.py <debug_log>"
        )

    # WebSocket registry data — used by setup wizard auto-discovery
    _entity_registry.extend(scenario.get("entity_registry", []))
    _config_entries.extend(scenario.get("config_entries", []))
    _devices.extend(scenario.get("devices", []))
    _services.update(scenario.get("services", {}))

    # Auto-generate entity registry for sensors not already covered
    existing_entity_ids = {e["entity_id"] for e in _entity_registry}
    inverter_type = scenario.get("inverter_type", "min")
    auto_entries = [
        e
        for e in _generate_entity_registry(inverter_type)
        if e["entity_id"] not in existing_entity_ids
    ]
    if auto_entries:
        _entity_registry.extend(auto_entries)
        logger.info(
            "Auto-generated %d entity registry entries for inverter_type=%s",
            len(auto_entries),
            inverter_type,
        )

    if not _config_entries:
        _config_entries.extend(_generate_config_entries(scenario))

    if not _services:
        inverter_type = scenario.get("inverter_type", "min")
        _services.update(_generate_services(inverter_type))

    logger.info(
        "Loaded scenario '%s' — %d sensors, %d TOU segments, %d registry entries",
        scenario.get("name", scenario_name),
        len(_sensors),
        len(_time_segments),
        len(_entity_registry),
    )


@app.on_event("startup")
async def startup() -> None:
    _load_scenario()


# ---------------------------------------------------------------------------
# Home Assistant state API
# ---------------------------------------------------------------------------


def _make_state_response(entity_id: str, value: Any) -> dict:
    """Normalise a scenario sensor value into a HA state response dict."""
    if isinstance(value, dict) and "state" in value:
        # Already a full HA state object — return it, ensuring entity_id is set
        return {"entity_id": entity_id, **value}
    # Scalar value: wrap it
    return {
        "entity_id": entity_id,
        "state": str(value),
        "attributes": {},
    }


@app.get("/api/config")
async def get_config() -> JSONResponse:
    """Return HA configuration including the scenario timezone."""
    return JSONResponse({"time_zone": _timezone})


@app.get("/api/states")
async def get_all_states() -> JSONResponse:
    """Return all entity states as a list — used by auto-discovery."""
    return JSONResponse(
        [_make_state_response(eid, val) for eid, val in _sensors.items()]
    )


@app.get("/api/states/{entity_id:path}")
async def get_state(entity_id: str) -> JSONResponse:
    """Return current state for any entity."""
    value = _sensors.get(entity_id)
    if value is None:
        logger.warning("Unknown entity requested: %s", entity_id)
        return JSONResponse(
            {
                "entity_id": entity_id,
                "state": "unavailable",
                "attributes": {},
            }
        )
    return JSONResponse(_make_state_response(entity_id, value))


# ---------------------------------------------------------------------------
# Home Assistant service API
# ---------------------------------------------------------------------------


@app.post("/api/services/{domain}/{service}")
async def call_service(domain: str, service: str, request: Request) -> JSONResponse:
    """Record the service call and return a canned response."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    entry = {
        "timestamp": datetime.now().isoformat(),
        "domain": domain,
        "service": service,
        "data": body,
    }
    _service_log.append(entry)
    logger.info("Service call: %s.%s %s", domain, service, body)

    # Return service-specific responses for read operations
    if domain == "nordpool" and service == "get_prices_for_date":
        requested_date = body.get("date", "")
        prices_kwh = _nordpool_prices.get(requested_date, [])
        if prices_kwh:
            # OfficialNordpoolSource expects prices in MWh (it divides by 1000 to get kWh).
            # Use area code extracted from the nordpool sensor key (e.g. "SE4" from
            # sensor.nordpool_kwh_se4_sek_...). OfficialNordpoolSource ignores the key
            # name, but using the real area keeps the response consistent.
            area = next(
                (
                    _match.group(1).upper()
                    for k in _sensors
                    if (_match := re.search(r"nordpool_kwh_(\w+?)_", k))
                ),
                "prices",
            )
            entries = [{"price": round(p * 1000, 4)} for p in prices_kwh]
            return JSONResponse({"service_response": {area: entries}})
        logger.warning("No nordpool prices for date: %s", requested_date)
        return JSONResponse({})

    if domain == "growatt_server":
        if service == "read_time_segments":
            return JSONResponse({"service_response": {"time_segments": _time_segments}})
        if service in ("read_ac_charge_times", "read_ac_charge_time"):
            return JSONResponse({"service_response": _ac_charge_times})
        if service in ("read_ac_discharge_times", "read_ac_discharge_time"):
            return JSONResponse({"service_response": _ac_discharge_times})

    # State-mutating service calls — update _sensors so subsequent reads
    # reflect the change (needed for entity-based TOU and EMS control).
    if domain == "select" and service == "select_option":
        entity_id = body.get("entity_id", "")
        option = body.get("option", "")
        if entity_id in _sensors:
            if isinstance(_sensors[entity_id], dict):
                _sensors[entity_id]["state"] = option
            else:
                _sensors[entity_id] = {"state": option, "attributes": {}}
        else:
            _sensors[entity_id] = {"state": option, "attributes": {}}

    elif domain == "number" and service == "set_value":
        entity_id = body.get("entity_id", "")
        value = body.get("value", 0)
        if entity_id in _sensors:
            if isinstance(_sensors[entity_id], dict):
                _sensors[entity_id]["state"] = str(value)
            else:
                _sensors[entity_id] = {"state": str(value), "attributes": {}}
        else:
            _sensors[entity_id] = {"state": str(value), "attributes": {}}

    elif domain == "switch" and service in ("turn_on", "turn_off"):
        entity_id = body.get("entity_id", "")
        state = "on" if service == "turn_on" else "off"
        if entity_id in _sensors:
            if isinstance(_sensors[entity_id], dict):
                _sensors[entity_id]["state"] = state
            else:
                _sensors[entity_id] = {"state": state, "attributes": {}}
        else:
            _sensors[entity_id] = {"state": state, "attributes": {}}

    # All write operations: record and acknowledge
    return JSONResponse({})


# ---------------------------------------------------------------------------
# Home Assistant WebSocket API (used by setup discovery)
# ---------------------------------------------------------------------------


@app.websocket("/api/websocket")
async def ha_websocket(ws: WebSocket) -> None:
    """Mock the HA WebSocket API used by BESS setup discovery.

    Implements the auth handshake and responds to the four command types
    that discover_ha_metadata sends:
      - config_entries/get
      - config/device_registry/list
      - get_services
      - config/entity_registry/list
    """
    await ws.accept()
    try:
        # Phase 1: Authentication
        await ws.send_json({"type": "auth_required", "ha_version": "2025.1.0"})
        auth_msg = await ws.receive_json()
        if auth_msg.get("type") != "auth":
            await ws.close(1008, "Expected auth message")
            return
        await ws.send_json({"type": "auth_ok", "ha_version": "2025.1.0"})

        # Phase 2: Handle commands
        while True:
            msg = await ws.receive_json()
            cmd_type = msg.get("type", "")
            cmd_id = msg.get("id", 0)

            _WS_HANDLERS = {
                "config_entries/get": _config_entries,
                "config/device_registry/list": _devices,
                "get_services": _services,
                "config/entity_registry/list": _entity_registry,
            }

            result = _WS_HANDLERS.get(cmd_type)
            if result is not None:
                await ws.send_json(
                    {"id": cmd_id, "type": "result", "success": True, "result": result}
                )
                logger.info(
                    "WS %-40s → %d entries",
                    cmd_type,
                    len(result) if isinstance(result, list) else len(result.keys()),
                )
            else:
                await ws.send_json(
                    {
                        "id": cmd_id,
                        "type": "result",
                        "success": False,
                        "error": {
                            "code": "not_found",
                            "message": f"Unknown command: {cmd_type}",
                        },
                    }
                )
                logger.warning("WS unknown command: %s", cmd_type)
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Mock control/debug endpoints
# ---------------------------------------------------------------------------


@app.get("/mock/service_log")
async def get_service_log() -> list:
    """Return all recorded service calls (inverter writes, SOC limits, etc.)."""
    return _service_log


@app.get("/mock/sensors")
async def get_sensors() -> dict:
    """Return current sensor state snapshot."""
    return _sensors


@app.post("/mock/update_sensor/{entity_id:path}")
async def update_sensor(entity_id: str, request: Request) -> dict:
    """Update a sensor value at runtime (for live simulation)."""
    body = await request.json()
    _sensors[entity_id] = body
    logger.info("Sensor updated: %s = %s", entity_id, body)
    return {"status": "ok", "entity_id": entity_id}


@app.get("/mock/clear_service_log")
async def clear_service_log() -> dict:
    """Clear the service log."""
    _service_log.clear()
    return {"status": "ok", "cleared": True}


@app.get("/")
async def root() -> dict:
    return {
        "name": "Mock Home Assistant API",
        "endpoints": {
            "sensors": "/api/states/{entity_id}",
            "services": "/api/services/{domain}/{service}",
            "service_log": "/mock/service_log",
            "sensor_list": "/mock/sensors",
            "update_sensor": "POST /mock/update_sensor/{entity_id}",
        },
    }
