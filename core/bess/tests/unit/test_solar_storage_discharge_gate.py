"""SOLAR_STORAGE intra-period discharge gate (shadow-price).

Extends the SOLAR_EXPORT gate (#187,
docs/superpowers/specs/2026-06-27-solar-export-discharge-rate-design.md) to
SOLAR_STORAGE (#318). The optimizer plans power=0 (hold) for SOLAR_STORAGE
periods, mapping to load_first + discharge_rate=0. But discharge_rate=0 is a
hardware register that blocks the battery from covering an intra-period
solar/load deficit (e.g. an unforecast EV-charging session) even when SOC is
well above Min SOC. Whether the battery SHOULD cover the dip is the same
economic question #187 answered for SOLAR_EXPORT: cover from battery only
when the stored energy is worth less than buying from grid right now, i.e.

    buy_price >= shadow_price

where shadow_price is the DP value-function gradient dV/dSoE (marginal
opportunity value of stored energy), persisted per period on DecisionData.
During genuine reserve accumulation shadow_price is high (gate stays closed,
protecting the evening target); near a full battery or with ample future
solar, shadow_price drops toward sell price and the gate opens.
"""

from types import SimpleNamespace

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import (
    has_value_cell_below,
    optimize_battery_schedule,
)
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.tests.helpers import make_battery_settings

PERIOD = 20  # Arbitrary test period (quarter-hour slot)


def _make_bsm(
    buy_prices: list[float],
) -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource(buy_prices),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    return bsm, controller


def _set_intent(bsm: BatterySystemManager, period: int, intent: str) -> None:
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._inverter_controller.strategic_intents = intents
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=[0.0] * 96)


def _store_authorization(bsm: BatterySystemManager, period: int, allowed: bool) -> None:
    """Populate the schedule store with a SOLAR_STORAGE period carrying the DP's
    sub-period discharge authorization (#526 -- the BSM reads the decision, not
    the shadow price it was derived from)."""
    energy = EnergyData(
        solar_production=0.0,
        home_consumption=0.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.0,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    decision = DecisionData(
        strategic_intent="SOLAR_STORAGE", intra_period_discharge_allowed=allowed
    )
    period_data = PeriodData(
        period=period,
        energy=energy,
        timestamp=time_utils.period_index_to_timestamp(period),
        economic=EconomicData(),
        decision=decision,
    )
    result = OptimizationResult(input_data={}, period_data=[period_data])
    bsm.schedule_store.store_schedule(result, optimization_period=period)


class TestSolarStorageDischargeGate:
    def test_dip_covered_when_battery_worth_less_than_grid(self):
        """DP authorized (stored energy worth less than buying now) -> gate
        opens, dip covered from battery."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_authorization(bsm, PERIOD, allowed=True)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100

    def test_reserve_protected_when_dp_withholds_authorization(self):
        """DP withheld authorization (reserve worth more than the dip) ->
        gate stays closed, reserve protected."""
        bsm, controller = _make_bsm(buy_prices=[0.2] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_authorization(bsm, PERIOD, allowed=False)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0

    def test_no_stored_schedule_holds_discharge(self):
        """No schedule stored yet -> gate cannot evaluate, discharge stays 0 (safe default)."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0


def _solar_storage_periods(result, settings):
    """SOLAR_STORAGE periods whose shadow price the DP could actually compute.

    Periods with no value-function cell below their start-of-period SoE (a
    battery sitting on its reserve floor, e.g. the first period of a scenario
    starting empty) are excluded: the shadow price is a left one-sided slope
    and does not exist there, so there is no marginal opportunity value for
    these tests to reason about. Before #526 such periods reported the `0.0`
    default, which read as "stored energy is worthless" and wrongly satisfied
    the gate-open comparison -- the exact confusion #526 removed.

    Asks the DP's own predicate rather than re-deriving the index rule; a
    test-side mirror of that arithmetic is what went stale in #571.
    """
    return [
        t
        for t, pd in enumerate(result.period_data)
        if pd.decision.strategic_intent == "SOLAR_STORAGE"
        and has_value_cell_below(pd.energy.battery_soe_start, settings)
    ]


@pytest.mark.slow
def test_solar_storage_holds_during_early_reserve_accumulation():
    """Early in reserve accumulation (battery still filling for an expensive
    evening peak ahead), shadow price is high -- the gate should stay closed
    so the DP's reserve-building plan isn't undermined by every small dip.
    """
    bs = make_battery_settings(efficiency_discharge=0.95)

    # Scarce solar relative to accumulation need, then a very expensive
    # evening peak that depends on the reserve being intact -- every marginal
    # kWh of accumulated solar matters, so shadow price is high.
    buy = [0.3] * 8 + [10.0] * 8
    sell = [0.1] * 16
    solar = [1.2] * 8 + [0.0] * 8
    consumption = [0.3] * 8 + [3.0] * 8

    result = optimize_battery_schedule(
        buy_price=buy,
        sell_price=sell,
        home_consumption=consumption,
        battery_settings=bs,
        solar_production=solar,
        initial_soe=bs.min_soe_kwh,  # empty -> must accumulate reserve
    )

    periods = _solar_storage_periods(result, bs)
    assert periods, (
        "scenario did not produce any SOLAR_STORAGE period with a computable "
        "shadow price"
    )
    for t in periods:
        shadow = result.period_data[t].decision.shadow_price
        # #683: shadow_price is per kWh delivered, the same unit as buy_price,
        # so the close condition carries no efficiency factor.
        assert shadow > buy[t], (
            f"period {t}: shadow {shadow:.3f} should exceed buy {buy[t]:.3f} "
            "(reserve worth more than covering a dip now)"
        )
        assert result.period_data[t].decision.intra_period_discharge_allowed is False


@pytest.mark.slow
def test_solar_storage_opens_when_shadow_price_is_low():
    """Abundant morning solar against a modest evening price step: the DP
    genuinely charges to cover the evening consumption (cycle cost + losses
    are still worth paying against the buy/sell spread), but solar supply
    comfortably exceeds what that evening need requires -- so the marginal
    stored kWh has low opportunity value, shadow price stays low, and the
    gate opens.

    (A prior version of this test relied on a finite-horizon boundary
    artifact -- the pre-#313 DP forcing a passive charge at period 0 with
    nothing to use it for -- which #313 correctly eliminated: bypass now
    strictly dominates a charge nothing ever discharges. This scenario
    instead gives the stored energy genuine future use, so storing remains
    the DP's real choice.)
    """
    bs = make_battery_settings(efficiency_discharge=0.95)

    # Morning solar (0.75 kWh/period) far exceeds the modest evening draw
    # (0.125 kWh/period) it needs to cover, so extra stored energy has low
    # marginal value once the evening need is satisfied -- shadow price
    # stays low even though storing at all is worthwhile against the
    # evening price step.
    buy = [0.3] * 8 + [3.0] * 8
    sell = [0.1] * 16
    solar = [3.0] * 8 + [0.0] * 8
    consumption = [0.3] * 8 + [0.5] * 8

    result = optimize_battery_schedule(
        buy_price=buy,
        sell_price=sell,
        home_consumption=consumption,
        battery_settings=bs,
        solar_production=solar,
        initial_soe=bs.min_soe_kwh,
    )

    periods = _solar_storage_periods(result, bs)
    assert periods, (
        "scenario did not produce any SOLAR_STORAGE period with a computable "
        "shadow price"
    )
    for t in periods:
        shadow = result.period_data[t].decision.shadow_price
        # #683: per kWh delivered on both sides, so no efficiency factor. The
        # old `buy * eff_d` form was strictly tighter than the rule production
        # applies, so a shadow price landing in (buy*eff_d, buy] would have
        # failed here while the gate below correctly reported open.
        assert shadow <= buy[t], (
            f"period {t}: shadow {shadow:.3f} should not exceed buy "
            f"{buy[t]:.3f} (low opportunity value, cheap to refill)"
        )
        assert result.period_data[t].decision.intra_period_discharge_allowed is True
