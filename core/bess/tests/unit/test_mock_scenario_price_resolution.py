"""Regression test for #469: nordpool_official mock scenarios must supply
quarterly (96 periods/day) price data, matching what the real HA
nordpool.get_prices_for_date service now returns.

ci-growatt-vpp.json and ci-normal-day.json still carried stale, hand-authored
24-entry hourly price arrays from the original test-framework PR (#86),
causing battery_system_manager.py's price horizon to see 48 entries
(24 today + 24 tomorrow) instead of 96 and fail to build a schedule.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from core.bess.time_utils import get_period_count

SCENARIOS_DIR = (
    Path(__file__).resolve().parents[4] / "scripts" / "mock_ha" / "scenarios"
)
MOCK_DATE = date(2025, 1, 15)


@pytest.mark.parametrize("scenario_file", ["ci-growatt-vpp.json", "ci-normal-day.json"])
def test_nordpool_official_scenario_has_quarterly_price_resolution(scenario_file):
    data = json.loads((SCENARIOS_DIR / scenario_file).read_text())
    nordpool_sensor = next(
        v for k, v in data["sensors"].items() if "nordpool" in k.lower()
    )
    today_prices = nordpool_sensor["attributes"]["today"]
    tomorrow_prices = nordpool_sensor["attributes"]["tomorrow"]

    expected = get_period_count(MOCK_DATE)

    assert len(today_prices) == expected
    assert len(tomorrow_prices) == expected
