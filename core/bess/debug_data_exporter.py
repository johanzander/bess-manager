"""Debug data export functionality for comprehensive troubleshooting.

This module provides tools to aggregate all relevant system data, logs, decisions,
and snapshots into a structured export for debugging purposes.
"""

import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .battery_system_manager import BatterySystemManager
from .health_check import run_system_health_checks

logger = logging.getLogger(__name__)


@dataclass
class DebugDataExport:
    """Complete debug data export containing all system state and history."""

    export_timestamp: str
    bess_version: str
    python_version: str
    system_uptime_hours: float
    health_check_results: dict
    battery_settings: dict
    price_settings: dict
    home_settings: dict
    historical_periods: list[dict]
    historical_summary: dict
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

    def aggregate_all_data(self) -> DebugDataExport:
        """Collect all system data into structured export.

        Returns:
            DebugDataExport containing all system state and history
        """
        logger.info("Starting debug data aggregation")

        return DebugDataExport(
            export_timestamp=datetime.now().isoformat(),
            bess_version=self._get_version(),
            python_version=sys.version,
            system_uptime_hours=self._get_uptime_hours(),
            health_check_results=self._get_health_checks(),
            battery_settings=self._serialize_battery_settings(),
            price_settings=self._serialize_price_settings(),
            home_settings=self._serialize_home_settings(),
            historical_periods=self._serialize_historical_data(),
            historical_summary=self._summarize_historical_data(),
            schedules=self._serialize_schedules(),
            schedules_summary=self._summarize_schedules(),
            snapshots=self._serialize_snapshots(),
            snapshots_summary=self._summarize_snapshots(),
            todays_log_content=self._read_todays_log(),
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
                with open(config_path, "r") as f:
                    for line in f:
                        if line.startswith("version:"):
                            # Extract version string, removing quotes
                            version = line.split(":", 1)[1].strip().strip('"')
                            return version
            return "unknown"
        except Exception as e:
            logger.warning(f"Failed to read version from config.yaml: {e}")
            return "unknown"

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
            logger.error(f"Failed to run health checks: {e}", exc_info=True)
            return {
                "error": str(e),
                "message": "Health checks failed during export",
            }

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

    def _serialize_home_settings(self) -> dict:
        """Serialize home settings to dictionary.

        Returns:
            Home settings as dictionary
        """
        return asdict(self.system.home_settings)

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
            logger.error(f"Failed to serialize historical data: {e}", exc_info=True)
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
            logger.error(f"Failed to summarize historical data: {e}", exc_info=True)
            return {"error": str(e)}

    def _serialize_schedules(self) -> list[dict]:
        """Serialize optimization schedules from today.

        Returns:
            List of schedule dictionaries
        """
        try:
            schedules = self.system.schedule_store.get_all_schedules_today()
            result = []
            for schedule in schedules:
                result.append(asdict(schedule))
            return result
        except Exception as e:
            logger.error(f"Failed to serialize schedules: {e}", exc_info=True)
            return []

    def _summarize_schedules(self) -> dict:
        """Create summary statistics for schedules.

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
            logger.error(f"Failed to summarize schedules: {e}", exc_info=True)
            return {"error": str(e)}

    def _serialize_snapshots(self) -> list[dict]:
        """Serialize prediction snapshots from today.

        Returns:
            List of snapshot dictionaries
        """
        try:
            snapshots = self.system.prediction_snapshot_store.get_all_snapshots_today()
            result = []
            for snapshot in snapshots:
                result.append(asdict(snapshot))
            return result
        except Exception as e:
            logger.error(f"Failed to serialize snapshots: {e}", exc_info=True)
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
            logger.error(f"Failed to summarize snapshots: {e}", exc_info=True)
            return {"error": str(e)}

    def _read_todays_log(self) -> str:
        """Read today's log file content.

        Returns:
            Log file content as string, or error message if not available
        """
        try:
            log_dir = Path("/data/logs")
            today_str = datetime.now().strftime("%Y-%m-%d")
            log_file = log_dir / f"bess-{today_str}.log"

            if not log_file.exists():
                return f"Log file not found: {log_file}"

            with open(log_file, "r") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read today's log file: {e}", exc_info=True)
            return f"Error reading log file: {str(e)}"

    def _get_log_file_info(self) -> dict:
        """Get metadata about today's log file.

        Returns:
            Dictionary with log file information
        """
        try:
            log_dir = Path("/data/logs")
            today_str = datetime.now().strftime("%Y-%m-%d")
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
            logger.error(f"Failed to get log file info: {e}", exc_info=True)
            return {"error": str(e)}
