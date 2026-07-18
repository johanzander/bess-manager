"""Tests for debug_report_formatter markdown table rendering."""

from core.bess.debug_data_exporter import DebugDataExport
from core.bess.debug_report_formatter import DebugReportFormatter


def _minimal_export(**overrides) -> DebugDataExport:
    defaults = {
        "export_timestamp": "2026-07-07T21:45:00+02:00",
        "timezone": "Europe/Stockholm",
        "bess_version": "9.9.0b9",
        "python_version": "3.12.0",
        "system_uptime_hours": 1.0,
        "health_check_results": {},
        "battery_settings": {},
        "price_settings": {},
        "price_data": {},
        "home_settings": {},
        "energy_provider_config": {},
        "addon_options": {},
        "entity_snapshot": {},
        "ha_statistics": {},
        "historical_periods": [],
        "historical_summary": {"total_periods": 0, "periods_with_data": 0},
        "previous_days": [],
        "inverter_tou_segments": [],
        "schedules": [],
        "schedules_summary": {"total_schedules": 0},
        "snapshots": [],
        "snapshots_summary": {"total_snapshots": 0},
        "todays_log_content": "",
        "log_file_info": {},
        "compact": True,
    }
    defaults.update(overrides)
    return DebugDataExport(**defaults)


class TestHistoricalDataTimeColumn:
    """The Time column must reflect the period's own start time, not the
    raw collection timestamp (which is stamped at the *end* of the period)."""

    def test_time_column_uses_period_start_not_collection_timestamp(self):
        # Period 86 covers 21:30-21:45; data for it is collected/stamped at
        # 21:45 (the start of period 87). The raw timestamp would mislabel
        # this row as "21:45", which is actually period 87's start time.
        period = {
            "period": 86,
            "timestamp": "2026-07-07T21:45:00+02:00",
            "data_source": "actual",
            "decision": {"strategic_intent": "BATTERY_EXPORT", "observed_intent": None},
            "energy": {
                "battery_soe_start": 8.1,
                "battery_soe_end": 7.3,
                "solar_production": 0.0,
                "grid_imported": 0.0,
            },
            "economic": {"hourly_savings": 0.0},
        }
        export = _minimal_export(
            historical_periods=[period],
            historical_summary={"total_periods": 1, "periods_with_data": 1},
        )

        report = DebugReportFormatter()._format_historical_data(export)

        assert "|  86 | 21:30 |" in report
        assert "|  86 | 21:45 |" not in report


class TestPeriodDecisionsTimeColumn:
    """Same period-start convention applies to the schedules 'Period
    Decisions' table."""

    def test_time_column_uses_period_start_not_collection_timestamp(self):
        period = {
            "period": 86,
            "timestamp": "2026-07-07T21:45:00+02:00",
            "decision": {"strategic_intent": "BATTERY_EXPORT", "observed_intent": None},
            "energy": {"battery_soe_start": 8.1, "battery_soe_end": 7.3},
            "economic": {"buy_price": 1.0, "hourly_savings": 0.0},
        }
        export = _minimal_export(
            schedules=[
                {
                    "optimization_period": 86,
                    "optimization_result": {
                        "economic_summary": {},
                        "input_data": {},
                        "period_data": [period],
                    },
                }
            ],
            schedules_summary={
                "total_schedules": 1,
                "first_optimization": "N/A",
                "last_optimization": "N/A",
            },
        )

        report = DebugReportFormatter()._format_schedules(export)

        assert "|  86 | 21:30 |" in report
        assert "|  86 | 21:45 |" not in report


class TestFormatPreviousDays:
    def test_no_previous_days_shows_message(self):
        export = _minimal_export(previous_days=[])

        report = DebugReportFormatter()._format_previous_days(export)

        assert "## Previous Days" in report
        assert "No prior-day data available" in report

    def test_renders_period_table_for_each_persisted_day(self):
        period = {
            "period": 76,
            "data_source": "actual",
            "decision": {"strategic_intent": "BATTERY_EXPORT", "observed_intent": None},
            "energy": {
                "battery_soe_start": 8.1,
                "battery_soe_end": 7.3,
                "solar_production": 0.0,
                "grid_imported": 0.0,
            },
            "economic": {"hourly_savings": 0.12},
        }
        export = _minimal_export(
            previous_days=[
                {
                    "date": "2026-07-17",
                    "periods": [period],
                    "total_savings": 4.56,
                    "actual_count": 1,
                    "predicted_count": 0,
                    "missing_count": 0,
                }
            ]
        )

        report = DebugReportFormatter()._format_previous_days(export)

        assert "## Previous Days" in report
        assert "2026-07-17" in report
        assert "BATTERY_EXPORT" in report
        assert "|  76 | 19:00 |" in report
