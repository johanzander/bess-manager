from core.bess.debug_findings import summarize_log_anomalies

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
