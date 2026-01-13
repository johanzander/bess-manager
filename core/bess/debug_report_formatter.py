"""Markdown report formatter for debug data export.

This module generates human-readable markdown reports with embedded JSON
sections for comprehensive system debugging.
"""

import json
import logging
from typing import Any

from .debug_data_exporter import DebugDataExport

logger = logging.getLogger(__name__)


class DebugReportFormatter:
    """Formats debug data export into markdown report."""

    def format_report(self, export: DebugDataExport) -> str:
        """Generate comprehensive markdown report with JSON sections.

        Args:
            export: DebugDataExport containing all system data

        Returns:
            Markdown-formatted report string
        """
        try:
            sections = [
                self._format_header(export),
                self._format_system_info(export),
                self._format_health_status(export),
                self._format_settings(export),
                self._format_historical_data(export),
                self._format_schedules(export),
                self._format_snapshots(export),
                self._format_logs(export),
            ]
            return "\n\n".join(sections)
        except Exception as e:
            logger.error(f"Failed to format debug report: {e}", exc_info=True)
            return self._format_error_report(export, e)

    def _format_header(self, export: DebugDataExport) -> str:
        """Format report header with timestamp and version.

        Args:
            export: DebugDataExport data

        Returns:
            Markdown header section
        """
        return f"""# BESS Manager Debug Export

**Export Date**: {export.export_timestamp}

**BESS Version**: {export.bess_version}"""

    def _format_system_info(self, export: DebugDataExport) -> str:
        """Format system information section.

        Args:
            export: DebugDataExport data

        Returns:
            Markdown system info section
        """
        system_info = {
            "bess_version": export.bess_version,
            "python_version": export.python_version,
            "system_uptime_hours": round(export.system_uptime_hours, 2),
            "export_timestamp": export.export_timestamp,
        }

        return f"""## System Information

```json
{self._format_json(system_info)}
```"""

    def _format_health_status(self, export: DebugDataExport) -> str:
        """Format health status section with collapsible details.

        Args:
            export: DebugDataExport data

        Returns:
            Markdown health status section
        """
        health = export.health_check_results

        # Extract overall status
        overall_status = health.get("overall_status", "UNKNOWN")
        critical_count = health.get("critical_count", 0)
        warning_count = health.get("warning_count", 0)
        ok_count = health.get("ok_count", 0)

        summary = f"""## System Health Status

**Overall Status**: {overall_status}

**Component Summary**:
- Critical Issues: {critical_count}
- Warnings: {warning_count}
- OK: {ok_count}"""

        details = f"""
<details>
<summary>Full Health Check Results (click to expand)</summary>

```json
{self._format_json(health)}
```

</details>"""

        return summary + details

    def _format_settings(self, export: DebugDataExport) -> str:
        """Format settings section with all configurations.

        Args:
            export: DebugDataExport data

        Returns:
            Markdown settings section
        """
        battery = self._format_json(export.battery_settings)
        price = self._format_json(export.price_settings)
        home = self._format_json(export.home_settings)

        return f"""## Settings

### Battery Settings

```json
{battery}
```

### Price Settings

```json
{price}
```

### Home Settings

```json
{home}
```"""

    def _format_historical_data(self, export: DebugDataExport) -> str:
        """Format historical data section with summary.

        Args:
            export: DebugDataExport data

        Returns:
            Markdown historical data section
        """
        summary = export.historical_summary
        total = summary.get("total_periods", 0)
        with_data = summary.get("periods_with_data", 0)

        summary_text = f"""## Historical Sensor Data

**Total Periods**: {total}

**Periods with Data**: {with_data}"""

        if with_data == 0:
            return summary_text + "\n\n*No historical data available*"

        details = f"""
<details>
<summary>Full Historical Data ({with_data} periods - click to expand)</summary>

```json
{self._format_json(export.historical_periods)}
```

</details>"""

        return summary_text + details

    def _format_schedules(self, export: DebugDataExport) -> str:
        """Format optimization schedules section with summary.

        Args:
            export: DebugDataExport data

        Returns:
            Markdown schedules section
        """
        summary = export.schedules_summary
        total = summary.get("total_schedules", 0)

        summary_text = f"""## Optimization Schedules

**Total Schedules**: {total}"""

        if total == 0:
            return summary_text + "\n\n*No optimization schedules available*"

        first = summary.get("first_optimization", "N/A")
        last = summary.get("last_optimization", "N/A")

        summary_text += f"""

**First Optimization**: {first}

**Last Optimization**: {last}"""

        details = f"""
<details>
<summary>Full Schedule Data ({total} schedules - click to expand)</summary>

```json
{self._format_json(export.schedules)}
```

</details>"""

        return summary_text + details

    def _format_snapshots(self, export: DebugDataExport) -> str:
        """Format prediction snapshots section with summary.

        Args:
            export: DebugDataExport data

        Returns:
            Markdown snapshots section
        """
        summary = export.snapshots_summary
        total = summary.get("total_snapshots", 0)

        summary_text = f"""## Prediction Snapshots

**Total Snapshots**: {total}"""

        if total == 0:
            return summary_text + "\n\n*No prediction snapshots available*"

        first = summary.get("first_snapshot", "N/A")
        last = summary.get("last_snapshot", "N/A")

        summary_text += f"""

**First Snapshot**: {first}

**Last Snapshot**: {last}"""

        details = f"""
<details>
<summary>Full Snapshot Data ({total} snapshots - click to expand)</summary>

```json
{self._format_json(export.snapshots)}
```

</details>"""

        return summary_text + details

    def _format_logs(self, export: DebugDataExport) -> str:
        """Format logs section with file info.

        Args:
            export: DebugDataExport data

        Returns:
            Markdown logs section
        """
        log_info = export.log_file_info
        exists = log_info.get("exists", False)

        summary = f"""## System Logs (Today)

**Log File**: {log_info.get('path', 'N/A')}"""

        if not exists:
            return summary + "\n\n*Log file not found*"

        size_bytes = log_info.get("size_bytes", 0)
        size_kb = size_bytes / 1024
        modified = log_info.get("modified", "N/A")

        summary += f"""

**Size**: {size_kb:.1f} KB

**Last Modified**: {modified}"""

        # Check if log content is available
        if "not found" in export.todays_log_content.lower() or "error" in export.todays_log_content.lower():
            return summary + f"\n\n*{export.todays_log_content}*"

        # Count log lines
        log_lines = export.todays_log_content.count("\n")

        details = f"""
<details>
<summary>Full Log Content ({log_lines} lines - click to expand)</summary>

```
{export.todays_log_content}
```

</details>"""

        return summary + details

    def _format_json(self, data: Any) -> str:
        """Format data as indented JSON.

        Args:
            data: Data to format

        Returns:
            JSON string with 2-space indentation
        """
        return json.dumps(data, indent=2, default=str)

    def _format_error_report(self, export: DebugDataExport, error: Exception) -> str:
        """Generate minimal error report when formatting fails.

        Args:
            export: DebugDataExport data (may be partial)
            error: Exception that occurred

        Returns:
            Basic markdown error report
        """
        return f"""# BESS Manager Debug Export (ERROR)

**Export Date**: {export.export_timestamp}

**BESS Version**: {export.bess_version}

## Error During Export

An error occurred while generating the debug report:

```
{str(error)}
```

## Partial Data

The following data was collected before the error:

```json
{{
  "bess_version": "{export.bess_version}",
  "export_timestamp": "{export.export_timestamp}",
  "system_uptime_hours": {export.system_uptime_hours}
}}
```

Please check the BESS Manager logs for more details.
"""
