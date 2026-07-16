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

    buy_price * efficiency_discharge >= shadow_price

where shadow_price is the DP value-function gradient dV/dSoE (marginal
opportunity value of stored energy), persisted per period on DecisionData.
During genuine reserve accumulation shadow_price is high (gate stays closed,
protecting the evening target); near a full battery or with ample future
solar, shadow_price drops toward sell price and the gate opens.
"""

from types import SimpleNamespace

import pytest

from core.bess.battery_system_manager import (
    BatterySystemManager,
    intra_period_discharge_gate,
)
from core.bess.dp_battery_algorithm import optimize_battery_schedule
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


def _store_shadow_price(
    bsm: BatterySystemManager, period: int, shadow_price: float
) -> None:
    """Populate the schedule store with a SOLAR_STORAGE period at the given shadow price."""
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
    decision = DecisionData(strategic_intent="SOLAR_STORAGE", shadow_price=shadow_price)
    period_data = PeriodData(
        period=period,
        energy=energy,
        economic=EconomicData(),
        decision=decision,
    )
    result = OptimizationResult(input_data={}, period_data=[period_data])
    bsm.schedule_store.store_schedule(result, optimization_period=period)


class TestSolarStorageDischargeGate:
    def test_dip_covered_when_battery_worth_less_than_grid(self):
        """High buy price, low shadow price -> gate opens, dip covered from battery."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_shadow_price(bsm, PERIOD, shadow_price=0.5)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100

    def test_reserve_protected_when_shadow_price_high(self):
        """Low buy price, high shadow price -> gate stays closed, reserve protected."""
        bsm, controller = _make_bsm(buy_prices=[0.2] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_shadow_price(bsm, PERIOD, shadow_price=4.0)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0

    def test_no_stored_schedule_holds_discharge(self):
        """No schedule stored yet -> gate cannot evaluate, discharge stays 0 (safe default)."""
        bsm, controller = _make_bsm(buy_prices=[2.0] * 96)
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0


def _solar_storage_periods(result):
    return [
        t
        for t, pd in enumerate(result.period_data)
        if pd.decision.strategic_intent == "SOLAR_STORAGE"
    ]


@pytest.mark.slow
def test_solar_storage_holds_during_early_reserve_accumulation():
    """Early in reserve accumulation (battery still filling for an expensive
    evening peak ahead), shadow price is high -- the gate should stay closed
    so the DP's reserve-building plan isn't undermined by every small dip.
    """
    bs = make_battery_settings(efficiency_discharge=0.95)
    eff_d = bs.efficiency_discharge

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

    periods = _solar_storage_periods(result)
    assert periods, "scenario did not produce any SOLAR_STORAGE period"
    for t in periods:
        shadow = result.period_data[t].decision.shadow_price
        assert shadow > buy[t] * eff_d, (
            f"period {t}: shadow {shadow:.3f} should exceed buy*eff_d "
            f"{buy[t] * eff_d:.3f} (reserve worth more than covering a dip now)"
        )
        assert intra_period_discharge_gate(buy[t], shadow, eff_d) == 0


@pytest.mark.slow
def test_solar_storage_opens_when_shadow_price_is_low():
    """Flat, low prices with no future scarcity: the marginal stored kWh has
    negligible opportunity value (nothing expensive ahead to protect it for),
    so shadow price stays low/zero and the gate opens -- a small deficit gets
    covered from battery instead of grid.

    Only the finite-horizon transient (period 0, a normal DP boundary effect
    near the horizon's terminal transition -- see the analogous t==0 handling
    in test_solar_export_discharge_gate.py) lands on SOLAR_STORAGE in this
    scenario; that's sufficient to prove the gate opens when shadow price is
    genuinely low, matching the economic law documented for SOLAR_EXPORT.
    """
    bs = make_battery_settings(efficiency_discharge=0.95)
    eff_d = bs.efficiency_discharge

    # No future price spike to protect a reserve for -- flat, cheap prices
    # throughout, so accumulated solar has low marginal opportunity value.
    buy = [0.3] * 16
    sell = [0.1] * 16
    solar = [3.0] * 8 + [0.0] * 8
    consumption = [0.5] * 16

    result = optimize_battery_schedule(
        buy_price=buy,
        sell_price=sell,
        home_consumption=consumption,
        battery_settings=bs,
        solar_production=solar,
        initial_soe=bs.min_soe_kwh,
    )

    periods = _solar_storage_periods(result)
    assert periods, "scenario did not produce any SOLAR_STORAGE period"
    for t in periods:
        shadow = result.period_data[t].decision.shadow_price
        assert shadow <= buy[t] * eff_d, (
            f"period {t}: shadow {shadow:.3f} should not exceed buy*eff_d "
            f"{buy[t] * eff_d:.3f} (low opportunity value, cheap to refill)"
        )
        assert intra_period_discharge_gate(buy[t], shadow, eff_d) == 100
