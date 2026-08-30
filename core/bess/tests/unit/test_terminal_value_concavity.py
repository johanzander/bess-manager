"""#602: the terminal row must be concave, so midnight SOE is a dial not a switch.

The defect these tests pin is a *shape* defect, not a calibration one, so they
assert the shape's consequence: that the carried quantity responds gradually to
the input that should control it. `test_the_linear_row_is_a_cliff` is the
discriminator -- it demonstrates on the same fixture that the pre-#602 row
cannot express a moderate carry at any rate, which is why re-tuning the scalar
was never an available fix.

The fixture is #595's real debug bundle (Growatt, SE3, 2026-08-15 08:43, 62
periods to midnight, initial SOE 2.40 kWh against a 2.00 kWh floor), replayed
verbatim from its entity snapshot.
"""

import itertools
import json

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.settings import BatterySettings
from core.bess.terminal_value import (
    TerminalValueCurve,
    calculate_terminal_curve,
    knee_kwh_from_forecast,
)
from core.bess.tests.helpers import _scenario_inputs
from core.bess.tests.unit.golden_capture import DATA_DIR

FIXTURE = "regression_2026_08_15_084345"

# Measured on this fixture, and the numbers #602 reports: the buy median over
# the remaining horizon is 0.852469 and the best export inside it is 0.82746,
# so the hold-versus-export crossover sits at 0.82746 * 0.95 = 0.7861.
HEAD_RATE = 0.809845312
CROSSOVER = 0.786087


def _inputs() -> dict:
    scenario = json.loads((DATA_DIR / f"{FIXTURE}.json").read_text())
    return dict(_scenario_inputs(scenario))


def _boundary_soe(**overrides: object) -> float:
    inputs = _inputs()
    inputs.update(overrides)
    result = optimize_battery_schedule(**inputs)
    return result.period_data[-1].energy.battery_soe_end


def test_midnight_carry_is_a_graded_function_of_the_knee() -> None:
    """The fix: each additional kWh of pre-dawn need carries one more kWh.

    This is the property the old row could not provide at any calibration --
    see the companion test below. Asserted as a trend rather than as pinned
    numbers so it stays a statement about shape, which is what #602 is about.
    """
    carries = [
        _boundary_soe(
            terminal_curve=TerminalValueCurve(head_rate=HEAD_RATE, knee_kwh=knee)
        )
        for knee in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
    ]

    assert carries == sorted(
        carries
    ), f"boundary SOE must not fall as the pre-dawn need grows; got {carries}"
    assert len({round(c, 2) for c in carries}) >= 5, (
        "a concave row must give most knee values their own distinct carry; "
        f"got {carries}"
    )
    steps = [b - a for a, b in itertools.pairwise(carries)]
    assert (
        max(steps) < 2.0
    ), f"no single kWh of extra need may move midnight by 2+ kWh; got {steps}"
    assert (
        carries[-1] - carries[0] > 3.0
    ), f"the knee must actually move the carry across its range; got {carries}"


def test_the_linear_row_is_a_cliff() -> None:
    """The defect: the pre-#602 row is flat, then jumps the whole battery.

    This is what makes the fix a shape change rather than a re-tune. Sweeping
    the scalar across the band where it transitions shows both failure modes at
    once -- a wide dead zone where the rate does nothing, and a step far larger
    than any moderate carry.
    """
    below = [
        _boundary_soe(terminal_curve=TerminalValueCurve.flat(rate))
        for rate in (0.0, 0.30, 0.386087, 0.55, 0.65)
    ]
    assert max(below) - min(below) < 0.5, (
        "the linear row should be inert across most of its range -- that dead "
        f"zone is half the defect; got {below}"
    )

    # The transition, and how narrow it is.
    just_under = _boundary_soe(terminal_curve=TerminalValueCurve.flat(0.7860))
    just_over = _boundary_soe(terminal_curve=TerminalValueCurve.flat(0.7861))
    assert just_over - just_under > 2.0, (
        "a 1e-4 change in the scalar should swing midnight by kWh -- this is "
        f"the knife-edge #602 reports; got {just_under} -> {just_over}"
    )
    assert just_under - max(below) > 5.0, (
        "and the transition itself should be a step, not a ramp; got "
        f"{max(below)} -> {just_under}"
    )


def test_the_crossover_is_where_the_linear_row_flips() -> None:
    """Why no scalar works: the flip is pinned to the export alternative.

    The DP compares the terminal rate against what exporting inside the horizon
    earns, so a single rate is either above it (hold everything) or below it
    (hold nothing). Naming that quantity here is what makes the cliff's location
    a fact about the objective rather than a coincidence of this fixture.
    """
    inputs = _inputs()
    settings = inputs["battery_settings"]
    crossover = max(inputs["sell_price"]) * settings.efficiency_discharge
    assert crossover == pytest.approx(CROSSOVER, abs=1e-5)

    # The transition completes just under the crossover rather than straddling
    # it -- by 0.99x the carry has already swung -- so the claim to pin is that
    # the whole swing is confined to a narrow band ending there, not that the
    # flip sits exactly on it.
    dumped = _boundary_soe(terminal_curve=TerminalValueCurve.flat(crossover * 0.85))
    held = _boundary_soe(terminal_curve=TerminalValueCurve.flat(crossover))
    assert held - dumped > 5.0, (
        "the swing from 'hold nothing' to 'hold most of the battery' should "
        f"happen within 15% below the export alternative; got {dumped} -> {held}"
    )


def test_knee_is_the_load_carried_until_pv_takes_over() -> None:
    """The knee is a quantity read from forecasts, not a price estimate.

    Midnight-aligned quarter-hour day: 0.25 kWh/period of load, solar rising
    from period 24 (06:00) and covering load from period 28 (07:00). Six hours
    of load at 0.25 is 6.0 kWh, which needs 6.0 / 0.95 stored to deliver.
    """
    settings = BatterySettings(total_capacity=20.0, min_soc=10, max_soc=100)
    consumption = [0.25] * 96
    solar = [0.0] * 24 + [0.1, 0.15, 0.2, 0.24] + [1.0] * 68

    knee = knee_kwh_from_forecast(consumption, solar, settings)

    covered = 0.25 * 24 + (0.25 - 0.1) + (0.25 - 0.15) + (0.25 - 0.2) + (0.25 - 0.24)
    assert knee == pytest.approx(covered / settings.efficiency_discharge)


@pytest.mark.parametrize("zero_at", [0, 3, 12])
def test_a_zero_consumption_hour_is_not_a_pv_crossover(zero_at: int) -> None:
    """#715: a forecast period with no load is a data gap, not "PV took over".

    An empty HA-statistics bucket and a managed-load clamp both leave a
    forecast hour at exactly 0.0 kWh. During pre-dawn darkness solar is also
    0.0, so the raw ``solar >= consumption`` scan reads ``0.0 >= 0.0`` as the
    PV crossover, breaks there, and collapses the knee -- to 0.0 if the gap is
    at the terminal boundary itself. The scan must skip a no-load period and
    keep accumulating until PV genuinely covers a real load.
    """
    settings = BatterySettings(total_capacity=20.0, min_soc=10, max_soc=100)
    consumption = [0.25] * 96
    consumption[zero_at] = 0.0
    solar = [0.0] * 28 + [1.0] * 68  # PV covers load from period 28 (07:00)

    knee = knee_kwh_from_forecast(consumption, solar, settings)

    covered = 0.25 * 27  # periods 0..27 less the single zeroed period
    assert knee == pytest.approx(covered / settings.efficiency_discharge)


def test_a_no_load_hour_with_concurrent_solar_is_skipped_not_subtracted() -> None:
    """#715: a no-load period must not pull the running net load negative.

    A daylight data gap (empty Recorder bucket, managed-load clamp) can land on
    a period where the solar sensor already reports production. Suppressing the
    crossover break is not enough: the scan must also not run
    ``net += consumption - solar`` for that period, or it subtracts the stray
    solar and understates -- or, with an early gap, negates -- the knee.
    """
    settings = BatterySettings(total_capacity=20.0, min_soc=10, max_soc=100)
    consumption = [0.25] * 96
    consumption[20] = 0.0  # 05:00 data gap
    # period 20 already shows a solar spike; real crossover is at period 28
    solar = [0.0] * 20 + [1.5] + [0.0] * 7 + [1.0] * 68

    knee = knee_kwh_from_forecast(consumption, solar, settings)

    covered = 0.25 * 27  # periods 0..27 less period 20; its 1.5 solar is ignored
    assert knee == pytest.approx(covered / settings.efficiency_discharge)


def test_a_zero_consumption_hour_does_not_fake_pv_refills() -> None:
    """#715: the same zero/zero period must not flip ``pv_refills`` either.

    ``calculate_terminal_curve`` derives ``pv_refills`` from the same
    ``solar >= consumption`` test. On a genuinely sunless winter day a single
    zero-load pre-dawn hour makes ``any(...)`` true, which keeps the day on the
    concave branch with an empty head segment -- every terminal kWh then priced
    at ``tail_rate = min(sell) * efficiency``, below the export floor. The
    sunless day must still take the capped scalar.
    """
    settings = BatterySettings(total_capacity=15.0, min_soc=10, max_soc=100)
    buy = [0.21] * 10 + [0.30] * 18 + [0.38] * 10
    sell = [0.10] * 22 + [0.16] * 8 + [0.12] * 8
    consumption = [0.0] + [0.3] * 37  # hour 0 has no forecast load
    solar = [0.0] * 38  # no sun anywhere

    curve = calculate_terminal_curve(buy, sell, consumption, solar, settings)

    assert curve.knee_kwh == float("inf"), (
        "a zero-consumption pre-dawn hour is missing data, not a PV crossover; "
        "a sunless day must still take the capped scalar"
    )
    assert (
        curve.head_rate < max(sell) * settings.efficiency_discharge
    ), "the capped scalar must hold the rate under the export alternative"


def test_a_sunless_day_keeps_the_capped_scalar() -> None:
    """No PV crossover means no knee, so the row stays the pre-#602 one.

    Without sun to refill the battery there is no quantity at which a stored
    kWh stops being worth the buy price, so the knee outruns the battery and
    the concave row would be straight *and* uncapped -- which is #126/#244's
    hoarding bug. That regime keeps the cap; see `calculate_terminal_curve`.
    """
    settings = BatterySettings(total_capacity=15.0, min_soc=10, max_soc=100)
    buy = [0.21] * 10 + [0.30] * 18 + [0.38] * 10
    sell = [0.10] * 22 + [0.16] * 8 + [0.12] * 8

    curve = calculate_terminal_curve(buy, sell, [0.3] * 38, [0.0] * 38, settings)

    assert curve.knee_kwh == float("inf"), "a sunless day has no knee"
    assert curve.head_rate < max(sell) * settings.efficiency_discharge, (
        "the cap must still hold the rate under the export alternative here, "
        "or the DP hoards instead of exporting into the evening peak (#244)"
    )


def test_a_row_that_cannot_be_concave_falls_back_to_the_capped_scalar() -> None:
    """The head must never sit at or below the tail (#687 review round 3).

    Concavity is `head_rate > tail_rate` and nothing else. Buy prices carry
    markup and VAT while sell prices carry a tax reduction, so a deeply negative
    spot can drive the buy median under a still-positive sell floor. The row
    would then be *convex*, and convexity makes the extremes dominate -- the DP
    goes back to carrying everything or nothing, which is #602's own defect in
    the new shape. Flooring the head at zero would not catch it: `0 < tail` is
    still convex.
    """
    settings = BatterySettings(total_capacity=20.0, min_soc=10, max_soc=100)
    # Deeply negative spot: the buy median lands below the sell floor.
    buy = [-0.40] * 48
    sell = [0.05, 0.30] * 24
    consumption = [0.25] * 48
    solar = [0.0] * 24 + [1.0] * 24

    curve = calculate_terminal_curve(buy, sell, consumption, solar, settings)

    assert curve.head_rate * settings.efficiency_discharge <= max(
        sell
    ), "fixture no longer produces the inverted shape this guards -- re-pick"
    assert curve.knee_kwh == float("inf"), (
        "a row that cannot be concave has no knee to express, so it must take "
        f"the capped scalar; got head={curve.head_rate} tail={curve.tail_rate}"
    )
    assert curve.head_rate >= curve.tail_rate, "the emitted row must be concave"
