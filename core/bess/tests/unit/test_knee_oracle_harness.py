"""The knee oracle's forecast scan must not drift from production's.

`scripts/knee_oracle.py` scores the #602/#687 terminal knee against metered
actuals. Its forecast side has to reproduce `knee_kwh_from_forecast` exactly:
a harness that grades a scan production no longer runs measures nothing, and
that is not a hypothetical -- an earlier version of this analysis reported a
midnight carry of 41% where production would really have planned 30%, and the
figure reached a reporter before it was caught.

The scan is repeated in the script only to report *where* it stopped, which is
what separates a timing miss from a level miss. The decision itself is
imported (`pv_covers_load`), so these tests pin the part that is repeated.
"""

import random
import sys
from pathlib import Path

import pytest

from core.bess.settings import BatterySettings
from core.bess.terminal_value import knee_kwh_from_forecast

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))

from knee_oracle import knee_from_forecast, oracle_knee


@pytest.fixture
def settings() -> BatterySettings:
    return BatterySettings(total_capacity=15.0, min_soc=12.0, max_soc=100.0)


class TestForecastScanMatchesProduction:
    def test_agrees_across_randomized_profiles(self, settings: BatterySettings) -> None:
        """Fuzzed against production, seeded with the shapes that broke it.

        Zero-load periods and exact ties are over-represented on purpose:
        those are #715's shape and the reason `pv_covers_load` exists.
        """
        random.seed(7)
        for _ in range(2000):
            length = random.randint(1, 40)
            consumption = [
                random.choice([0.0, 0.0, 0.1, 0.2, 0.35]) for _ in range(length)
            ]
            solar = [random.choice([0.0, 0.0, 0.1, 0.2, 0.5]) for _ in range(length)]

            expected = knee_kwh_from_forecast(consumption, solar, settings)
            actual, _ = knee_from_forecast(
                consumption, solar, settings.efficiency_discharge
            )

            assert actual == pytest.approx(
                expected, abs=1e-12
            ), f"drifted from production on {consumption=} {solar=}"

    def test_zero_load_period_does_not_stop_the_scan(
        self, settings: BatterySettings
    ) -> None:
        """#715: a dark hour with no forecast load is a data gap, not sunrise."""
        consumption = [0.2, 0.0, 0.2, 0.2]
        solar = [0.0, 0.0, 0.0, 0.0]

        knee, crossover = knee_from_forecast(
            consumption, solar, settings.efficiency_discharge
        )

        assert crossover is None
        assert knee == pytest.approx(0.6 / 0.95)

    def test_reports_the_crossover_index(self, settings: BatterySettings) -> None:
        """The one thing the script adds over the production function."""
        consumption = [0.2, 0.2, 0.2, 0.2]
        solar = [0.0, 0.0, 0.5, 0.5]

        knee, crossover = knee_from_forecast(
            consumption, solar, settings.efficiency_discharge
        )

        assert crossover == 2
        assert knee == pytest.approx(0.4 / 0.95)


class TestOracleIsStricterThanTheForecastScan:
    """Metered data needs a guard production does not, and vice versa."""

    def test_single_period_tie_is_not_sunrise(self, settings: BatterySettings) -> None:
        """A 0.1-vs-0.1 quantization tie with solar back to 0.0 next quarter.

        `pv_covers_load` accepts it -- it is real PV meeting a real load -- so
        the forecast scan stops there. On a meter it is noise, and stopping
        reads sunrise ~30 minutes early, understating what the house needed.
        """
        consumption = [0.2, 0.1, 0.2, 0.2, 0.2]
        solar = [0.0, 0.1, 0.0, 0.0, 0.0]

        _, forecast_crossover = knee_from_forecast(
            consumption, solar, settings.efficiency_discharge
        )
        oracle, oracle_crossover = oracle_knee(
            consumption, solar, settings.efficiency_discharge
        )

        assert forecast_crossover == 1
        assert oracle_crossover is None
        assert oracle == pytest.approx(0.8 / 0.95)

    def test_sustained_coverage_is_sunrise(self, settings: BatterySettings) -> None:
        consumption = [0.2, 0.2, 0.1, 0.1]
        solar = [0.0, 0.0, 0.4, 0.5]

        oracle, crossover = oracle_knee(
            consumption, solar, settings.efficiency_discharge
        )

        assert crossover == 2
        assert oracle == pytest.approx(0.4 / 0.95)
