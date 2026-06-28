"""Debug data export functionality for comprehensive troubleshooting.

This module produces a single markdown file (compact=True by default) that serves
three distinct debugging use cases, all via the same export endpoint.

## Use Case 1 — Exact scenario replay

Reproduce any user's real-world scenario on a local development machine.
Required data: entity_snapshot (full raw HA state, verbatim mock-HA input),
addon_options (entity ID mappings and inverter config), inverter_tou_segments
(current hardware TOU state), historical_periods full JSON (seeds the in-memory
historical store), and price_data (raw pre-markup prices).

This is why the compact export embeds full JSON inside <details> collapsibles for
entity_snapshot, historical_periods, and schedules — the tables are for human
reading, the JSON is machine input for from_debug_log.py.

## Use Case 2 — AI behaviour analysis via bess-analyst + MCP server

Fetch the export from a production system and ask: "Why did we have a series of
small discharges between 07:00 and 08:45 — is this financially optimal?"

The AI needs: compact key-event logs (not the raw 200+ KB full log), the latest
schedule rendered as a period-decisions table, historical_periods as an observation
table (planned intent vs observed intent vs actual energy flows), and settings.
The full JSON collapsibles are present but the AI works from the tables.

## Use Case 3 — Prediction drift analysis throughout the day

The 00:00 optimization predicted 100 SEK savings; by 18:00 only 60 SEK was
realised. Was this a bug, a bad battery action, or just external environmental
change (less sun, higher consumption than predicted)?

Required data: ALL prediction snapshots as an evolution table (one compact row
per hourly optimization run, showing total_savings, actual_count, predicted_count)
combined with the historical_periods observation table. Together these let the
analyst trace whether the gap appeared early (environmental) or late (control
error). No full snapshot JSON is needed — the 5-field evolution table is enough.

## compact=True vs compact=False

compact=True  - default; serves all three use cases; targets ~200-500 KB.
compact=False — raw full dump; complete log, all schedules, all snapshots as JSON;
                use when a specific field not present in compact mode is needed.
"""

import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import time_utils
from .battery_system_manager import BatterySystemManager
from .debug_findings import build_key_findings
from .health_check import run_system_health_checks

logger = logging.getLogger(__name__)

# Substrings (case-insensitive) that mark a dict key as carrying a secret.
# Values for any matching key are replaced with the redaction sentinel below,
# regardless of how deeply nested the key appears.
_SECRET_KEY_FRAGMENTS = (
    "password",
    "api_key",
    "apikey",
    "token",
    "secret",
    "authorization",
    "private_key",
    "client_id",
)
_REDACTED = "<redacted>"

# Per-domain allowlist applied to the `data` and `options` dicts of a HA
# config entry. Only keys here are kept verbatim; everything else is dropped.
# Domains absent from this map are dropped entirely (size summary kept for
# debugging). Keep this list intentionally tight — config-entry data dicts
# are the most likely place for secrets to leak into a debug export.
_CONFIG_ENTRY_DATA_ALLOWLIST: dict[str, frozenset[str]] = {
    "nordpool": frozenset({"area", "areas", "currency", "vat", "country", "name"}),
    "growatt_server": frozenset({"name", "plant_id", "url"}),
    "growatt": frozenset({"name", "plant_id", "url"}),
    "solax_modbus": frozenset({"name"}),
    "solax": frozenset({"name"}),
}

# Domains whose config entries are captured in the WS discovery dump.
_WS_TARGET_DOMAINS = frozenset(
    {"nordpool", "growatt", "growatt_server", "solax_modbus", "solax"}
)

# Domains whose entities are captured from the entity registry.
_ENTITY_REGISTRY_DOMAINS = frozenset(
    {"growatt_server", "solax_modbus", "solax", "nordpool", "octopus_energy"}
)

# Keywords matched against entity_id and unique_id to capture entities
# that belong to BESS-relevant integrations even if they register under
# an unexpected platform name.
_ENTITY_REGISTRY_KEYWORDS = ("growatt", "solax", "nordpool", "octopus")

# Entity registry fields that are useful for debugging discovery and
# sensor mapping. unique_id is redacted (last-4) since it often contains
# the hub name or serial number.
_ENTITY_REGISTRY_FIELDS = (
    "entity_id",
    "unique_id",
    "platform",
    "device_id",
    "original_name",
    "disabled_by",
    "hidden_by",
    "capabilities",
    "entity_category",
)


def _is_secret_key(key: str) -> bool:
    """True if a dict key name suggests its value is a credential."""
    k = key.lower()
    return any(frag in k for frag in _SECRET_KEY_FRAGMENTS)


def _redact_secrets(obj: Any) -> Any:
    """Recursively redact values of any secret-named dict keys.

    Used as a defence-in-depth pass after structural filtering — catches
    secrets that appear under unexpected key paths (e.g. nested config).
    """
    if isinstance(obj, dict):
        return {
            k: (_REDACTED if _is_secret_key(k) else _redact_secrets(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_secrets(v) for v in obj]
    return obj


def _redact_identifier_value(value: Any) -> str:
    """Replace a device identifier (often a serial or MAC) with last-4 only."""
    s = str(value)
    return f"***{s[-4:]}" if len(s) > 4 else "***"


def _redact_identifiers(identifiers: Any) -> list:
    """Last-4 redaction for HA device-registry identifiers."""
    if not isinstance(identifiers, list):
        return []
    out: list = []
    for ident in identifiers:
        if isinstance(ident, list | tuple) and len(ident) == 2:
            domain, value = ident
            out.append([domain, _redact_identifier_value(value)])
    return out


def _collect_device_serials(devices: list) -> set[str]:
    """Extract raw identifier values (serials, MACs) from device registry entries."""
    serials: set[str] = set()
    for d in devices:
        if not isinstance(d, dict):
            continue
        for ident in d.get("identifiers") or []:
            if isinstance(ident, list | tuple) and len(ident) == 2:
                val = str(ident[1])
                if len(val) >= 4:
                    serials.add(val)
    return serials


def _scrub_config_entry(entry: dict) -> dict:
    """Filter a HA config entry to a minimal, secret-free shape.

    Keeps only fields we use for discovery diagnosis. The `data` and
    `options` dicts are passed through a per-domain allowlist; unknown
    domains have their data replaced with a key-count summary so we still
    know an entry exists without leaking its contents.
    """
    domain = entry.get("domain", "")
    allowed = _CONFIG_ENTRY_DATA_ALLOWLIST.get(domain)

    def _filter(d: Any) -> dict:
        if not isinstance(d, dict):
            return {}
        if allowed is None:
            return {"<filtered>": f"{len(d)} keys (domain not allowlisted)"}
        return {k: v for k, v in d.items() if k in allowed}

    return _redact_secrets(
        {
            "entry_id": entry.get("entry_id"),
            "domain": entry.get("domain"),
            "title": "***",
            "state": entry.get("state"),
            "version": entry.get("version"),
            "options": _filter(entry.get("options", {})),
            "data": _filter(entry.get("data", {})),
        }
    )


def _scrub_device(device: dict) -> dict:
    """Filter a device-registry entry to a minimal, identifier-redacted shape."""
    return {
        "id": device.get("id"),
        "name": device.get("name"),
        "manufacturer": device.get("manufacturer"),
        "model": device.get("model"),
        "identifiers": _redact_identifiers(device.get("identifiers")),
    }


def _scrub_entity_registry_entry(
    entity: dict, device_serials: set[str] | None = None
) -> dict:
    """Filter an entity registry entry, redacting the unique_id.

    The unique_id often contains a device serial or hub name as a prefix
    (e.g. ``KMN0DYP037-tlx_battery_1_charge_w``).  We replace known
    serials with ``***`` so the separator and key are preserved — making
    the output directly usable for building test scenario ``unique_id``
    values by plugging a serial back in.
    """
    raw_uid = str(entity.get("unique_id", ""))
    redacted_uid = _redact_identifier_value(raw_uid) if raw_uid else ""

    out: dict[str, Any] = {}
    for field_name in _ENTITY_REGISTRY_FIELDS:
        if field_name == "unique_id":
            out["unique_id"] = redacted_uid
            # Replace known serials with *** to preserve separator and key.
            scrubbed = raw_uid
            if device_serials:
                for serial in device_serials:
                    if serial in scrubbed:
                        scrubbed = scrubbed.replace(serial, "***")
                        break
            out["unique_id_suffix"] = scrubbed
        else:
            val = entity.get(field_name)
            if val is not None:
                out[field_name] = val
    return out


# Patterns that identify actionable log lines worth including in compact exports.
# These cover: errors/warnings, hardware commands, key decisions, feature-specific
# events (discharge inhibit, charge power), and intent transitions.
_LOG_KEY_PATTERNS = re.compile(
    r"WARNING|ERROR|CRITICAL"
    r"|HARDWARE:"
    r"|Discharge inhibit|charge power|charging power|discharge rate"
    r"|Intent transition|DECISION:"
    r"|Starting optimization|Optimization complete"
    r"|Applying period|Apply schedule"
    r"|LOAD_SUPPORT|BATTERY_EXPORT|GRID_CHARGING"
    r"|TOU hardware|TOU conversion|schedule created"
    r"|Setting.*power rate|power rate.*set",
    re.IGNORECASE,
)

_COMPACT_LOG_TAIL = 50  # Always include this many trailing lines for recent context


@dataclass
class DebugDataExport:
    """Complete debug data export containing all system state and history."""

    export_timestamp: str
    timezone: str
    bess_version: str
    python_version: str
    system_uptime_hours: float
    health_check_results: dict
    battery_settings: dict
    price_settings: dict
    price_data: dict
    home_settings: dict
    energy_provider_config: dict
    addon_options: dict
    entity_snapshot: dict
    historical_periods: list[dict]
    historical_summary: dict
    inverter_tou_segments: list[dict]
    schedules: list[dict]
    schedules_summary: dict
    snapshots: list[dict]
    snapshots_summary: dict
    todays_log_content: str
    log_file_info: dict
    ha_ws_discovery: dict = field(default_factory=dict)
    key_findings: dict = field(default_factory=dict)
    compact: bool = True


class DebugDataAggregator:
    """Aggregates all system data for debug export."""

    def __init__(
        self,
        system: BatterySystemManager,
        settings_data: dict | None = None,
    ):
        """Initialize aggregator with system manager.

        Args:
            system: BatterySystemManager instance to export data from
            settings_data: Full settings store data for debug export.
                If None, addon_options in the export will be empty.
        """
        self.system = system
        self._settings_data = settings_data or {}
        self._start_time = datetime.now()

    def aggregate_all_data(self, compact: bool = True) -> DebugDataExport:
        """Collect all system data into structured export.

        Field-to-use-case mapping:

        UC1 (replay):
            entity_snapshot     — full raw HA state; verbatim mock-HA sensor input
            addon_options       — entity ID mappings + inverter device config
            inverter_tou_segments — seeds mock inverter with real hardware state
            historical_periods  — full JSON seeds the in-memory historical store
            price_data          — raw pre-markup prices for the optimization replay

        UC2 (AI behaviour analysis):
            todays_log_content  — compact key-event filter (not the full log)
            schedules           — latest schedule as period-decisions table
            historical_periods  — planned vs observed intent + actual energy flows
            battery/price/home settings — context for decision reasoning
            health_check_results — surface sensor/component failures

        UC3 (prediction drift):
            snapshots           — ALL snapshots as 5-field evolution table
                                  (total_savings, actual_count, predicted_count
                                   per hourly optimization run)
            historical_periods  — actuals to cross-reference against the evolution

        Args:
            compact: If True (default), serves all three use cases:
                - Logs: key events from the full day + last 50 lines (not 200+ KB full log)
                - Snapshots: all snapshots as 5-field evolution rows (not full JSON)
                - Schedules: latest schedule only, rendered as tables + full JSON collapsible
                - entity_snapshot/historical: tables for reading + full JSON for replay
                If False, raw full dump — complete log, all schedules/snapshots as JSON.

        Returns:
            DebugDataExport containing all system state and history
        """
        logger.info("Starting debug data aggregation (compact=%s)", compact)

        export = DebugDataExport(
            export_timestamp=datetime.now().astimezone().isoformat(),
            timezone=self._get_timezone(),
            bess_version=self._get_version(),
            python_version=sys.version,
            system_uptime_hours=self._get_uptime_hours(),
            health_check_results=self._get_health_checks(),
            battery_settings=self._serialize_battery_settings(),
            price_settings=self._serialize_price_settings(),
            price_data=self._serialize_price_data(),
            home_settings=self._serialize_home_settings(),
            energy_provider_config=self._serialize_energy_provider_config(),
            addon_options=self._serialize_addon_options(),
            entity_snapshot=self._serialize_entity_snapshot(),
            inverter_tou_segments=self._serialize_inverter_tou(),
            historical_periods=self._serialize_historical_data(),
            historical_summary=self._summarize_historical_data(),
            schedules=self._serialize_schedules(compact=compact),
            schedules_summary=self._summarize_schedules(),
            snapshots=self._serialize_snapshots(compact=compact),
            snapshots_summary=self._summarize_snapshots(),
            todays_log_content=self._read_todays_log(compact=compact),
            log_file_info=self._get_log_file_info(),
            ha_ws_discovery=self._serialize_ha_ws_discovery(),
            compact=compact,
        )
        export.key_findings = build_key_findings(
            export.schedules, export.todays_log_content
        )
        return export

    def _get_version(self) -> str:
        """Get BESS Manager version.

        Reads from BESS_VERSION environment variable (set at image build time),
        falling back to config.yaml for local development.

        Returns:
            Version string (e.g., "7.16.1")
        """
        version = os.environ.get("BESS_VERSION", "")
        if version:
            return version
        try:
            config_path = Path(__file__).parent.parent.parent / "config.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    for line in f:
                        if line.startswith("version:"):
                            return line.split(":", 1)[1].strip().strip('"')
            return "unknown"
        except Exception as e:
            logger.warning(f"Failed to read version from config.yaml: {e}")
            return "unknown"

    def _get_timezone(self) -> str:
        """Return the IANA timezone name currently used by BESS (e.g. 'Europe/Stockholm')."""
        return str(time_utils.TIMEZONE)

    def _get_uptime_hours(self) -> float:
        """Calculate system uptime since initialization.

        Returns:
            Uptime in hours
        """
        uptime = datetime.now() - self._start_time
        return uptime.total_seconds() / 3600

    def _get_health_checks(self) -> dict:
        """Run system health checks and return results.

        Returns:
            Health check results dictionary
        """
        try:
            return run_system_health_checks(self.system)
        except Exception as e:
            logger.exception(f"Failed to run health checks: {e}")
            return {
                "error": str(e),
                "message": "Health checks failed during export",
            }

    def _serialize_energy_provider_config(self) -> dict:
        """Serialize energy provider configuration to dictionary.

        Returns:
            Energy provider config as dictionary
        """
        try:
            return self.system._energy_provider_config
        except Exception as e:
            logger.warning("Failed to serialize energy provider config: %s", e)
            return {}

    def _serialize_battery_settings(self) -> dict:
        """Serialize battery settings to dictionary.

        Returns:
            Battery settings as dictionary
        """
        try:
            return asdict(self.system.battery_settings)
        except Exception as e:
            logger.warning("Failed to serialize battery settings: %s", e)
            return {}

    def _serialize_price_settings(self) -> dict:
        """Serialize price settings to dictionary.

        Returns:
            Price settings as dictionary
        """
        try:
            return asdict(self.system.price_settings)
        except Exception as e:
            logger.warning("Failed to serialize price settings: %s", e)
            return {}

    def _serialize_price_data(self) -> dict:
        """Serialize full-day raw prices for today and tomorrow.

        Returns raw (pre-markup) quarterly prices so debug log replays can
        reconstruct the exact sensor values that were seen on that day.
        """
        try:
            today_entries = self.system.price_manager.get_today_prices()
            tomorrow_entries = self.system.price_manager.get_tomorrow_prices()
            return {
                "today": [round(e["price"], 6) for e in today_entries],
                "tomorrow": [round(e["price"], 6) for e in tomorrow_entries],
            }
        except Exception as e:
            logger.warning("Failed to serialize price data: %s", e)
            return {"today": [], "tomorrow": []}

    def _serialize_home_settings(self) -> dict:
        """Serialize home settings to dictionary.

        Returns:
            Home settings as dictionary
        """
        try:
            return asdict(self.system.home_settings)
        except Exception as e:
            logger.warning("Failed to serialize home settings: %s", e)
            return {}

    def _serialize_addon_options(self) -> dict:
        """Serialize settings data (entity ID mappings, inverter config).

        Includes sensor entity IDs, battery settings, price config, and
        inverter device ID. Used by from_debug_log.py to auto-generate
        bess_config for mock HA replay.

        InfluxDB username and password are stripped — URL is retained for
        diagnosing connection issues.

        Returns:
            Settings dict with credentials redacted.
        """
        try:
            options = dict(self._settings_data)
            if "influxdb" in options:
                influxdb = dict(options["influxdb"])
                influxdb.pop("username", None)
                influxdb.pop("password", None)
                options["influxdb"] = influxdb
            return options
        except Exception as e:
            logger.warning("Failed to serialize addon options: %s", e)
            return {}

    def _serialize_ha_ws_discovery(self) -> dict:
        """Capture raw WS responses BESS uses for discovery.

        The official HA Nordpool integration stores the price area inside its
        config entry — invisible from the REST API. Discovery bugs (e.g. issue
        #91, where SE3 users get SE4) require seeing the actual config-entry
        shape that HA returns, because BESS has no other way to learn it.

        Captures config entries, device registry, services, and entity
        registry for all BESS-relevant domains (growatt, solax, nordpool).
        Scrubs secrets via key-name pattern and per-domain data allowlist;
        redacts device identifiers and entity unique_ids.
        """
        controller = self.system._controller
        if controller is None:
            return {"error": "controller not initialized"}

        try:
            results = controller._ws_query(
                [
                    {"type": "config_entries/get"},
                    {"type": "config/device_registry/list"},
                    {"type": "get_services"},
                    {"type": "config/entity_registry/list"},
                ]
            )
        except Exception as e:
            logger.warning("WS discovery dump failed: %s", e)
            return {"error": f"WS query failed: {e}"}

        config_entries_raw = results[0] if len(results) > 0 else []
        devices_raw = results[1] if len(results) > 1 else []
        services_raw = results[2] if len(results) > 2 else {}
        entity_registry_raw = results[3] if len(results) > 3 else []

        config_entries = [
            _scrub_config_entry(e)
            for e in config_entries_raw
            if isinstance(e, dict)
            and (
                e.get("domain") in _WS_TARGET_DOMAINS
                or any(
                    kw in str(e.get("domain", "")).lower()
                    or kw in str(e.get("title", "")).lower()
                    for kw in _ENTITY_REGISTRY_KEYWORDS
                )
            )
        ]

        # Collect raw serials from device identifiers before scrubbing,
        # so we can replace them in unique_ids to preserve the full key format.
        device_serials = _collect_device_serials(devices_raw)

        devices: list[dict] = []
        for d in devices_raw:
            if not isinstance(d, dict):
                continue
            ident_str = json.dumps(d.get("identifiers", [])).lower()
            if "growatt" in ident_str or "solax" in ident_str:
                devices.append(_scrub_device(d))

        services: dict[str, list[str]] = {}
        if isinstance(services_raw, dict):
            for domain in sorted(services_raw.keys()):
                if domain in _WS_TARGET_DOMAINS or any(
                    kw in domain.lower() for kw in _ENTITY_REGISTRY_KEYWORDS
                ):
                    domain_svcs = services_raw[domain]
                    if isinstance(domain_svcs, dict):
                        services[domain] = sorted(domain_svcs.keys())

        # Entity registry: capture entities by known platform OR by keyword
        # match in entity_id/unique_id.  This catches entities that register
        # under an unexpected platform name (e.g. a solax_modbus variant).
        entity_registry: list[dict] = []
        for entity in entity_registry_raw:
            if not isinstance(entity, dict):
                continue
            if entity.get("platform") in _ENTITY_REGISTRY_DOMAINS:
                entity_registry.append(
                    _scrub_entity_registry_entry(entity, device_serials)
                )
            else:
                # Keyword fallback: check entity_id and unique_id
                eid = str(entity.get("entity_id", "")).lower()
                uid = str(entity.get("unique_id", "")).lower()
                if any(kw in eid or kw in uid for kw in _ENTITY_REGISTRY_KEYWORDS):
                    entity_registry.append(
                        _scrub_entity_registry_entry(entity, device_serials)
                    )

        try:
            resolved = controller.discover_ha_metadata(device_sn=None)
        except Exception as e:
            resolved = {"error": str(e)}

        return {
            "config_entries": config_entries,
            "devices": devices,
            "services": services,
            "entity_registry": entity_registry,
            "resolved": resolved,
        }

    # HA state response fields that carry no value for any of the three debug
    # use cases (replay, AI analysis, drift analysis).  Stripping them reduces
    # entity_snapshot size without affecting mock-HA replay: from_debug_log.py
    # only reads 'state' and 'attributes' from each entry.
    _HA_METADATA_KEYS = frozenset(
        {"last_changed", "last_updated", "last_reported", "context"}
    )

    def _strip_ha_metadata(self, state: dict) -> dict:
        """Return a copy of a HA state dict with HA-internal metadata removed."""
        return {k: v for k, v in state.items() if k not in self._HA_METADATA_KEYS}

    def _serialize_entity_snapshot(self) -> dict:
        """Fetch raw HA entity state for every entity BESS reads.

        Returns a dict of {entity_id: state_response} that can be used verbatim
        as the 'sensors' dict in a mock HA scenario — no reconstruction needed.
        Captures all sensor-map entities plus price-provider-specific entities.

        HA metadata fields (last_changed, last_updated, last_reported, context)
        are stripped — they are never read during replay or AI analysis.
        """
        controller = self.system._controller
        if controller is None:
            logger.warning("No HA controller available — skipping entity snapshot")
            return {}
        snapshot: dict = {}

        # All entities registered in the sensor map — use the public info API to resolve
        # entity IDs so resolution goes through the same path as normal sensor reads.
        seen_entities: set[str] = set()
        for method_name in controller.METHOD_SENSOR_MAP:
            info = controller.get_method_sensor_info(method_name)
            entity_id = info.get("entity_id")
            if (
                not entity_id
                or info.get("status") == "not_configured"
                or entity_id in seen_entities
            ):
                continue
            seen_entities.add(entity_id)
            try:
                state = controller.get_entity_state_raw(entity_id)
                if state:
                    snapshot[entity_id] = self._strip_ha_metadata(state)
            except Exception as e:
                logger.warning("Failed to fetch entity %s: %s", entity_id, e)

        # Price provider entities (not in METHOD_SENSOR_MAP)
        config = self.system._energy_provider_config
        provider = config["provider"]

        if provider == "nordpool_hacs":
            nordpool_cfg = config["nordpool_hacs"]
            entity_id = nordpool_cfg.get("entity")
            if entity_id:
                try:
                    state = controller.get_entity_state_raw(entity_id)
                    if state:
                        snapshot[entity_id] = self._strip_ha_metadata(state)
                except Exception as e:
                    logger.warning(
                        "Failed to fetch nordpool entity %s: %s", entity_id, e
                    )

        elif provider == "octopus":
            octopus_cfg = config["octopus"]
            for key in (
                "import_today_entity",
                "import_tomorrow_entity",
                "export_today_entity",
                "export_tomorrow_entity",
            ):
                entity_id = octopus_cfg.get(key)
                if entity_id:
                    try:
                        state = controller.get_entity_state_raw(entity_id)
                        if state:
                            snapshot[entity_id] = self._strip_ha_metadata(state)
                    except Exception as e:
                        logger.warning(
                            "Failed to fetch octopus entity %s: %s", entity_id, e
                        )

        elif provider != "nordpool_official":
            # nordpool_official uses service calls — no entity state to capture
            logger.warning(
                "Unknown energy provider '%s' — skipping provider entity snapshot",
                provider,
            )

        logger.info("Entity snapshot captured: %d entities", len(snapshot))
        return snapshot

    def _serialize_inverter_tou(self) -> list[dict]:
        """Serialize the current inverter TOU segments from memory.

        Returns the segments that were last read from / written to the inverter,
        so debug log replays can seed the mock with the real inverter state.

        Returns:
            List of TOU segment dicts as held in active_tou_intervals
        """
        try:
            return list(self.system._inverter_controller.active_tou_intervals)
        except Exception as e:
            logger.warning("Failed to serialize inverter TOU segments: %s", e)
            return []

    def _serialize_historical_data(self) -> list[dict]:
        """Serialize historical data from today's periods.

        Always returns full period data — the formatter decides how to render
        (table in compact mode, raw JSON in full mode). The full JSON is needed
        for mock HA replay to seed the in-memory historical store.

        Returns:
            List of period data dictionaries
        """
        try:
            periods = self.system.historical_store.get_today_periods()
            result = []
            for period in periods:
                if period is not None:
                    result.append(asdict(period))
                else:
                    result.append(None)
            return result
        except Exception as e:
            logger.exception(f"Failed to serialize historical data: {e}")
            return []

    def _summarize_historical_data(self) -> dict:
        """Create summary statistics for historical data.

        Returns:
            Summary dictionary with counts and ranges
        """
        try:
            periods = self.system.historical_store.get_today_periods()
            non_null = [p for p in periods if p is not None]

            if not non_null:
                return {
                    "total_periods": len(periods),
                    "periods_with_data": 0,
                    "message": "No historical data available",
                }

            return {
                "total_periods": len(periods),
                "periods_with_data": len(non_null),
                "first_period": non_null[0].period if non_null else None,
                "last_period": non_null[-1].period if non_null else None,
            }
        except Exception as e:
            logger.exception(f"Failed to summarize historical data: {e}")
            return {"error": str(e)}

    def _serialize_schedules(self, compact: bool = True) -> list[dict]:
        """Serialize optimization schedules from today.

        Args:
            compact: If True, only include the latest schedule.

        Returns:
            List of schedule dictionaries (formatter table-ifies period_data in compact mode)
        """
        try:
            if compact:
                latest = self.system.schedule_store.get_latest_schedule()
                return [asdict(latest)] if latest else []
            schedules = self.system.schedule_store.get_all_schedules_today()
            return [asdict(schedule) for schedule in schedules]
        except Exception as e:
            logger.exception(f"Failed to serialize schedules: {e}")
            return []

    def _summarize_schedules(self) -> dict:
        """Create summary statistics for schedules.

        Always reports totals regardless of compact mode, so the reader
        knows how many schedules exist even when only the latest is included.

        Returns:
            Summary dictionary with counts and timestamps
        """
        try:
            schedules = self.system.schedule_store.get_all_schedules_today()

            if not schedules:
                return {
                    "total_schedules": 0,
                    "message": "No optimization schedules available",
                }

            return {
                "total_schedules": len(schedules),
                "first_optimization": schedules[0].timestamp.isoformat(),
                "last_optimization": schedules[-1].timestamp.isoformat(),
            }
        except Exception as e:
            logger.exception(f"Failed to summarize schedules: {e}")
            return {"error": str(e)}

    def _serialize_snapshots(self, compact: bool = True) -> list[dict]:
        """Serialize prediction snapshots from today.

        Args:
            compact: If True, return ALL snapshots as 5-field summary rows
                (timestamp, period, predicted_savings, actual_count, predicted_count).
                This enables the full-day prediction evolution table for use case 3
                (morning prediction vs evening actual analysis) at ~6 KB instead
                of 166 KB for the complete JSON.
                If False, return full snapshot data for all snapshots.

        Returns:
            List of snapshot dictionaries
        """
        try:
            snapshots = self.system.prediction_snapshot_store.get_all_snapshots_today()
            if not snapshots:
                return []
            if not compact:
                return [asdict(snapshot) for snapshot in snapshots]
            # Compact: all snapshots as summary rows for the evolution table.
            # Use grid_only_cost - hourly_cost to match the dashboard total
            # savings definition (includes both solar and battery benefit).
            result = []
            for snapshot in snapshots:
                total_savings = sum(
                    p.economic.grid_only_cost - p.economic.hourly_cost
                    for p in snapshot.daily_view.periods
                    if p.economic is not None
                )
                result.append(
                    {
                        "snapshot_timestamp": snapshot.snapshot_timestamp.isoformat(),
                        "optimization_period": snapshot.optimization_period,
                        "total_savings": total_savings,
                        "actual_count": snapshot.daily_view.actual_count,
                        "predicted_count": snapshot.daily_view.predicted_count,
                    }
                )
            return result
        except Exception as e:
            logger.exception(f"Failed to serialize snapshots: {e}")
            return []

    def _summarize_snapshots(self) -> dict:
        """Create summary statistics for prediction snapshots.

        Returns:
            Summary dictionary with counts and timestamps
        """
        try:
            snapshots = self.system.prediction_snapshot_store.get_all_snapshots_today()

            if not snapshots:
                return {
                    "total_snapshots": 0,
                    "message": "No prediction snapshots available",
                }

            return {
                "total_snapshots": len(snapshots),
                "first_snapshot": snapshots[0].snapshot_timestamp.isoformat(),
                "last_snapshot": snapshots[-1].snapshot_timestamp.isoformat(),
            }
        except Exception as e:
            logger.exception(f"Failed to summarize snapshots: {e}")
            return {"error": str(e)}

    def _read_todays_log(self, compact: bool = True) -> str:
        """Read today's log file content.

        Args:
            compact: If True, return key event lines from the full day plus the
                last 50 lines for recent context. This gives full-day visibility
                into actionable events (errors, hardware commands, decisions,
                feature-specific lines) at ~35 KB instead of 208 KB for a
                2000-line tail that only covers ~2 hours.
                If False, return the complete log.

        Returns:
            Log file content as string, or error message if not available
        """
        try:
            log_dir = Path("/data/logs")
            today_str = time_utils.now().strftime("%Y-%m-%d")
            log_file = log_dir / f"bess-{today_str}.log"

            if not log_file.exists():
                return f"Log file not found: {log_file}"

            with open(log_file) as f:
                if not compact:
                    return f.read()
                lines = f.readlines()

            total = len(lines)

            # Key event indices: any line matching the filter patterns
            key_indices = {
                i for i, line in enumerate(lines) if _LOG_KEY_PATTERNS.search(line)
            }
            # Always include the last N lines for recent context
            tail_start = max(0, total - _COMPACT_LOG_TAIL)
            included = sorted(key_indices | set(range(tail_start, total)))

            result: list[str] = []
            prev = -1
            for i in included:
                if prev >= 0 and i > prev + 1:
                    skipped = i - prev - 1
                    result.append(f"[... {skipped} lines skipped ...]\n")
                result.append(lines[i])
                prev = i

            header = (
                f"[Compact log: {len(key_indices)} key events from {total} total lines"
                f" + last {_COMPACT_LOG_TAIL} lines. Use compact=false for full log.]\n"
            )
            return header + "".join(result)

        except Exception as e:
            logger.exception(f"Failed to read today's log file: {e}")
            return f"Error reading log file: {e!s}"

    def _get_log_file_info(self) -> dict:
        """Get metadata about today's log file.

        Returns:
            Dictionary with log file information
        """
        try:
            log_dir = Path("/data/logs")
            today_str = time_utils.now().strftime("%Y-%m-%d")
            log_file = log_dir / f"bess-{today_str}.log"

            if not log_file.exists():
                return {
                    "exists": False,
                    "path": str(log_file),
                    "message": "Log file not found",
                }

            stat = log_file.stat()
            return {
                "exists": True,
                "path": str(log_file),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        except Exception as e:
            logger.exception(f"Failed to get log file info: {e}")
            return {"error": str(e)}
