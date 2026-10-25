"""Suite-wide pytest configuration.

Tests must not depend on the calendar day they run on: on a DST transition day
the real clock gives a 23- or 25-hour day (92/100 quarterly periods), which
silently breaks every test that assumes 96. Pin the clock to a fixed ordinary
day; tests that need a specific date or a DST day pin their own, which
overrides this.
"""

from datetime import datetime

import pytest  # type: ignore

from core.bess import time_utils
from core.bess.tests.helpers import pinned_datetime_class

# An ordinary (non-DST-transition) day, midday. No test hardcodes this date: a
# test whose own fixture date equals "today" takes the live-data path.
PINNED_NOW = datetime(2026, 9, 16, 12, 0, tzinfo=time_utils.TIMEZONE)


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch):
    # time_utils reads the clock through its own `datetime` name, so now(),
    # today() and the period-index helpers all move together.
    monkeypatch.setattr(time_utils, "datetime", pinned_datetime_class(PINNED_NOW))
