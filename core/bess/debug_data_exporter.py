"""Debug data export functionality for comprehensive troubleshooting.

This module provides tools to aggregate all relevant system data, logs, decisions,
and snapshots into a structured export for debugging purposes.
"""

import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from . import time_utils
from .battery_system_manager import BatterySystemManager
from .health_check import run_system_health_checks

logger = logging.getLogger(__name__)


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


class DebugDataAggregator:
    """Aggregates all system data for debug export."""

    def __init__(self, system: BatterySystemManager):
        """Initialize aggregator with system manager.

        Args:
            system: BatterySystemManager instance to export data from
        """
        self.system = system
        self._start_time = datetime.now()

    def aggregate_all_data(self, compact: bool = True) -> DebugDataExport:
        """Collect all system data into structured export.

        Args:
            compact: If True (default), include only the latest schedule/snapshot
                and last 2000 lines of logs. If False, include everything.

        Returns:
            DebugDataExport containing all system state and history
        """
        logger.info("Starting debug data aggregation (compact=%s)", compact)

        return DebugDataExport(
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
        )

    def _get_version(self) -> str:
        """Get BESS Manager version from config.yaml.

        Returns:
            Version string (e.g., "5.0.1")
        """
        try:
            config_path = Path(__file__).parent.parent.parent / "config.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    for line in f:
                        if line.startswith("version:"):
                            # Extract version string, removing quotes
                            version = line.split(":", 1)[1].strip().strip('"')
                            return version
            return "unknown"
        except Exception as e:
            logger.warning(f"Failed to read version from config.yaml: {e}")
            return "unknown"

    def _get_timezone(self) -> str:
        """Return the IANA timezone name currently used by BESS (e.g. 'Europe/Stockholm')."""
        from . import time_utils

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
        return self.system._energy_provider_config

    def _serialize_battery_settings(self) -> dict:
        """Serialize battery settings to dictionary.

        Returns:
            Battery settings as dictionary
        """
        return asdict(self.system.battery_settings)

    def _serialize_price_settings(self) -> dict:
        """Serialize price settings to dictionary.

        Returns:
            Price settings as dictionary
        """
        return asdict(self.system.price_settings)

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
        return asdict(self.system.home_settings)

    def _serialize_addon_options(self) -> dict:
        """Serialize addon options (entity ID mappings, inverter config).

        This is the complete options.json loaded at startup — includes sensor entity
        IDs, battery settings, price config, and inverter device ID. Used by
        from_debug_log.py to auto-generate bess_config for mock HA replay.

        InfluxDB username and password are stripped — URL is retained for diagnosing
        connection issues.

        Returns:
            Addon options dict as loaded from options.json, with credentials redacted
        """
        try:
            options = dict(self.system._addon_options)
            if "influxdb" in options:
                influxdb = dict(options["influxdb"])
                influxdb.pop("username", None)
                influxdb.pop("password", None)
                options["influxdb"] = influxdb
            return options
        except Exception as e:
            logger.warning("Failed to serialize addon options: %s", e)
            return {}

    def _serialize_entity_snapshot(self) -> dict:
        """Fetch raw HA entity state for every entity BESS reads.

        Returns a dict of {entity_id: state_response} that can be used verbatim
        as the 'sensors' dict in a mock HA scenario — no reconstruction needed.
        Captures all sensor-map entities plus price-provider-specific entities.
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
                    snapshot[entity_id] = state
            except Exception as e:
                logger.warning("Failed to fetch entity %s: %s", entity_id, e)

        # Price provider entities (not in METHOD_SENSOR_MAP)
        config = self.system._energy_provider_config
        provider = config["provider"]

        if provider == "nordpool":
            nordpool_cfg = config["nordpool"]
            for key in ("today_entity", "tomorrow_entity"):
                entity_id = nordpool_cfg.get(key)
                if entity_id:
                    try:
                        state = controller.get_entity_state_raw(entity_id)
                        if state:
                            snapshot[entity_id] = state
                    except Exception as e:
                        logger.warning("Failed to fetch nordpool entity %s: %s", entity_id, e)

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
                            snapshot[entity_id] = state
                    except Exception as e:
                        logger.warning("Failed to fetch octopus entity %s: %s", entity_id, e)

        elif provider != "nordpool_official":
            # nordpool_official uses service calls — no entity state to capture
            logger.warning("Unknown energy provider '%s' — skipping provider entity snapshot", provider)

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
            return list(self.system._schedule_manager.active_tou_intervals)
        except Exception as e:
            logger.warning("Failed to serialize inverter TOU segments: %s", e)
            return []

    def _serialize_historical_data(self) -> list[dict]:
        """Serialize historical data from today's periods.

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
            List of schedule dictionaries
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
            compact: If True, only include the latest snapshot.

        Returns:
            List of snapshot dictionaries
        """
        try:
            snapshots = self.system.prediction_snapshot_store.get_all_snapshots_today()
            if not snapshots:
                return []
            if compact:
                return [asdict(snapshots[-1])]
            return [asdict(snapshot) for snapshot in snapshots]
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

    _COMPACT_LOG_LINES = 2000

    def _read_todays_log(self, compact: bool = True) -> str:
        """Read today's log file content.

        Args:
            compact: If True, only include the last 2000 lines.

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
                if total <= self._COMPACT_LOG_LINES:
                    return "".join(lines)
                truncated = lines[-self._COMPACT_LOG_LINES :]
                return (
                    f"[Truncated: showing last {self._COMPACT_LOG_LINES} of {total} lines. "
                    f"Use compact=false for full log.]\n" + "".join(truncated)
                )
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
