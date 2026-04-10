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
                self._format_addon_options(export),
                self._format_entity_snapshot(export),
                self._format_inverter_tou(export),
                self._format_historical_data(export),
                self._format_schedules(export),
                self._format_snapshots(export),
                self._format_logs(export),
            ]
            return "\n\n".join(sections)
        except Exception as e:
            logger.exception(f"Failed to format debug report: {e}")
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
            "timezone": export.timezone,
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
        price_data = self._format_json(export.price_data)
        home = self._format_json(export.home_settings)
        energy_provider = self._format_json(export.energy_provider_config)

        return f"""## Settings

### Battery Settings

```json
{battery}
```

### Price Settings

```json
{price}
```

### Price Data

```json
{price_data}
```

### Home Settings

```json
{home}
```

### Energy Provider Configuration

```json
{energy_provider}
```"""

    def _format_addon_options(self, export: DebugDataExport) -> str:
        return f"""## BESS Configuration

```json
{self._format_json(export.addon_options)}
```"""

    def _format_entity_snapshot(self, export: DebugDataExport) -> str:
        count = len(export.entity_snapshot)

        summary = f"""## Entity Snapshot

**Entities captured**: {count}"""

        if count == 0:
            return summary + "\n\n*No entity states available*"

        if not export.compact:
            return (
                summary
                + f"""

<details>
<summary>Raw HA entity states ({count} entities — click to expand)</summary>

```json
{self._format_json(export.entity_snapshot)}
```

</details>"""
            )

        # Compact: flattened key:value table for quick reading,
        # full JSON in collapsible for mock HA replay.
        rows = ["| Entity ID | State | Unit |", "|---|---|---|"]
        for entity_id, state in sorted(export.entity_snapshot.items()):
            if isinstance(state, dict):
                val = state.get("state", "")
                attrs = state.get("attributes", {})
                unit = attrs.get("unit_of_measurement", "")
            else:
                val = str(state)
                unit = ""
            rows.append(f"| `{entity_id}` | {val} | {unit} |")

        flat_table = "\n".join(rows)

        return (
            summary
            + f"""

{flat_table}

<details>
<summary>Full HA entity states (JSON — needed for mock HA replay)</summary>

```json
{self._format_json(export.entity_snapshot)}
```

</details>"""
        )

    def _format_inverter_tou(self, export: DebugDataExport) -> str:
        segments = export.inverter_tou_segments
        count = len(segments)

        summary = f"""## Inverter TOU Segments

**Segments in Hardware**: {count}"""

        if count == 0:
            return summary + "\n\n*No TOU segments available*"

        return (
            summary
            + f"""

```json
{self._format_json(segments)}
```"""
        )

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

        if not export.compact:
            details = f"""
<details>
<summary>Full Historical Data ({with_data} periods - click to expand)</summary>

```json
{self._format_json(export.historical_periods)}
```

</details>"""
            return summary_text + details

        # Compact: markdown table for quick analysis + full JSON collapsible for replay.
        rows = [
            "| Per | Time  | Src    | Intent           | Observed         |"
            " SOE kWh | Solar | Import | Savings |",
            "|-----|-------|--------|------------------|------------------|"
            "---------|-------|--------|---------|",
        ]
        for p in export.historical_periods:
            if p is None:
                continue
            ts = str(p.get("timestamp", ""))[:16]
            src = p.get("data_source", "")[:6]
            dec = p.get("decision", {})
            intent = dec.get("strategic_intent", "")[:16]
            observed = (dec.get("observed_intent") or "")[:16]
            en = p.get("energy", {})
            soe_s = en.get("battery_soe_start", 0)
            soe_e = en.get("battery_soe_end", 0)
            solar = en.get("solar_production", 0)
            imp = en.get("grid_imported", 0)
            econ = p.get("economic", {})
            savings = econ.get("hourly_savings", 0)
            rows.append(
                f"| {p.get('period', ''):>3} | {ts[11:16]:5} | {src:<6} |"
                f" {intent:<16} | {observed:<16} |"
                f" {soe_s:>4.1f}→{soe_e:<4.1f} | {solar:>5.2f} | {imp:>6.2f} | {savings:>7.4f} |"
            )

        table = "\n".join(rows)

        details = f"""
<details>
<summary>Full Historical Data JSON (needed for mock HA replay)</summary>

```json
{self._format_json(export.historical_periods)}
```

</details>"""

        return summary_text + f"\n\n{table}" + details

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

        if not export.compact or not export.schedules:
            details = f"""
<details>
<summary>Full Schedule Data ({total} schedules - click to expand)</summary>

```json
{self._format_json(export.schedules)}
```

</details>"""
            return summary_text + details

        # Compact: render the latest schedule as a markdown table.
        # The full JSON still lives in the collapsible for deeper digs.
        schedule = export.schedules[0]
        opt_period = schedule.get("optimization_period", "?")
        opt_result = schedule.get("optimization_result", {})
        econ_summary = opt_result.get("economic_summary", {})
        input_data = opt_result.get("input_data", {})
        period_data = opt_result.get("period_data", [])

        # Economic summary JSON (small — always show)
        econ_block = f"""### Economic Summary (period {opt_period})

```json
{self._format_json(econ_summary)}
```"""

        # Input metadata (scalars only, skip large arrays)
        input_meta = {
            k: v
            for k, v in input_data.items()
            if not isinstance(v, list)
        }
        if input_meta:
            econ_block += f"""

```json
{self._format_json(input_meta)}
```"""

        # Period decisions table
        rows = [
            "| Per | Time  | Intent           | Observed         |"
            " BattAct | SOE kWh | BuyPrice | Savings |",
            "|-----|-------|------------------|------------------|"
            "---------|---------|----------|---------|",
        ]
        for p in period_data:
            dec = p.get("decision", {})
            intent = (dec.get("strategic_intent") or "")[:16]
            observed = (dec.get("observed_intent") or "")[:16]
            batt_act = dec.get("battery_action", 0) or 0
            en = p.get("energy", {})
            soe_s = en.get("battery_soe_start", 0)
            soe_e = en.get("battery_soe_end", 0)
            econ = p.get("economic", {})
            buy = econ.get("buy_price", 0)
            savings = econ.get("hourly_savings", 0)
            ts = str(p.get("timestamp", ""))
            time_str = ts[11:16] if len(ts) >= 16 else ""
            rows.append(
                f"| {p.get('period', ''):>3} | {time_str:5} |"
                f" {intent:<16} | {observed:<16} |"
                f" {batt_act:>+7.3f} | {soe_s:>4.1f}→{soe_e:<4.1f} |"
                f" {buy:>8.4f} | {savings:>7.4f} |"
            )

        table = "\n".join(rows)

        details = f"""
<details>
<summary>Full Schedule JSON (for deep debugging)</summary>

```json
{self._format_json(export.schedules)}
```

</details>"""

        return summary_text + f"\n\n{econ_block}\n\n### Period Decisions\n\n{table}" + details

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

        if not export.compact or not export.snapshots:
            details = f"""
<details>
<summary>Full Snapshot Data ({total} snapshots - click to expand)</summary>

```json
{self._format_json(export.snapshots)}
```

</details>"""
            return summary_text + details

        # Compact: evolution table — all snapshots as summary rows.
        # This is the primary tool for use case 3 (morning prediction vs evening actual).
        # Each row shows: when, which period, what total savings looked like at that moment.
        rows = [
            "| Timestamp        | Per | Total Savings | Actual | Predicted |",
            "|------------------|-----|---------------|--------|-----------|",
        ]
        for sn in export.snapshots:
            ts = str(sn.get("snapshot_timestamp", ""))[:16]
            per = sn.get("optimization_period", "")
            savings = sn.get("total_savings", 0) or 0
            actual = sn.get("actual_count", 0)
            predicted = sn.get("predicted_count", 0)
            rows.append(
                f"| {ts:<16} | {per:>3} | {savings:>13.4f} | {actual:>6} | {predicted:>9} |"
            )

        table = "\n".join(rows)

        return summary_text + f"\n\n{table}"

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
        if (
            "not found" in export.todays_log_content.lower()
            or "error reading" in export.todays_log_content.lower()
        ):
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
{error!s}
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
