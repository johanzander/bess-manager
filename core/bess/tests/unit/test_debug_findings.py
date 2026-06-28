from core.bess.debug_findings import (
    build_key_findings,
    reconcile_schedules,
    summarize_log_anomalies,
)

SAMPLE_LOG = """2026-06-28 00:16:00 | WARNING | core.bess.battery_system_manager:1439 - Historical data unavailable for period 0 (00:00): No InfluxDB data available
2026-06-28 00:31:00 | WARNING | core.bess.battery_system_manager:1439 - Historical data unavailable for period 1 (00:15): No InfluxDB data available
2026-06-28 10:31:00 | ERROR | core.bess.influxdb_helper:519 - Error connecting to InfluxDB: HTTPConnectionPool: Max retries exceeded
2026-06-28 11:31:00 | ERROR | core.bess.influxdb_helper:519 - Error connecting to InfluxDB: HTTPConnectionPool: Max retries exceeded
2026-06-28 09:00:00 | INFO | core.bess.app:12 - nothing interesting here
"""


def test_summarize_dedups_by_category_and_source():
    out = summarize_log_anomalies(SAMPLE_LOG)
    by_source = {a.source: a for a in out}

    data_gap = by_source["core.bess.battery_system_manager:1439"]
    assert data_gap.category == "data_gap"
    assert data_gap.count == 2
    assert data_gap.first_ts == "2026-06-28 00:16:00"
    assert data_gap.last_ts == "2026-06-28 00:31:00"

    network = by_source["core.bess.influxdb_helper:519"]
    assert network.category == "network"
    assert network.count == 2


def test_summarize_ignores_uncategorized_info_lines():
    out = summarize_log_anomalies(SAMPLE_LOG)
    assert all("app:12" not in a.source for a in out)


def test_summarize_empty_log_returns_empty():
    assert summarize_log_anomalies("") == []


def _sched(ts, period, intent, action):
    return {
        "timestamp": ts,
        "optimization_result": {
            "period_data": [
                {
                    "period": period,
                    "decision": {
                        "strategic_intent": intent,
                        "battery_action": action,
                    },
                }
            ]
        },
    }


def test_reconcile_flags_intent_disagreement_on_same_slot():
    schedules = [
        _sched("2026-06-28 10:31:00", 63, "BATTERY_EXPORT", -0.1),
        _sched("2026-06-28 11:31:00", 63, "SOLAR_EXPORT", -0.0),
    ]
    out = reconcile_schedules(schedules)
    assert len(out) == 1
    d = out[0]
    assert d.period == 63
    assert d.time == "15:45"
    assert set(d.intents) == {"BATTERY_EXPORT", "SOLAR_EXPORT"}


def test_reconcile_no_disagreement_when_all_runs_agree():
    schedules = [
        _sched("2026-06-28 10:31:00", 63, "SOLAR_EXPORT", -0.0),
        _sched("2026-06-28 11:31:00", 63, "SOLAR_EXPORT", -0.0),
    ]
    assert reconcile_schedules(schedules) == []


def test_build_key_findings_clean_when_nothing_notable():
    schedules = [_sched("2026-06-28 11:31:00", 63, "SOLAR_EXPORT", -0.0)]
    result = build_key_findings(schedules, "")
    assert result["clean"] is True
    assert result["disagreements"] == []
    assert result["anomalies"] == []
