"""PV export-limit curtailment at negative sell price (issue #269).

When solar surplus is being exported at a negative sell price and the
battery has no better use for it (full, or the DP already chose not to
store it), the Growatt export-limit register (122/123, via a grid CT/smart
meter) curtails PV production at the inverter instead of paying to export.

Two parts:

1. Execution-time actuation (TestExportLimitCurtailment below): a per-period
   decision in BSM's _apply_period_schedule, platform-agnostic: grid_exported
   > 0 AND sell_price < floor. Only platforms with
   supports_export_limit_control=True (currently SolaxModbusGrowattController)
   actually act on it; everyone else gets a no-op via
   InverterController.apply_export_limit's base implementation. This part
   does not change the DP plan at all -- it fires purely on the DP's own
   already-computed PeriodData.

2. DP planning awareness (TestDPCurtailmentAwareReward below): since the DP's
   backward induction propagates a later period's reward into every earlier
   period's decision via the continuation value, leaving the reward function
   unaware that curtailment will neutralize a later negative-price export
   penalty can make the DP refuse a genuinely profitable earlier action (e.g.
   discharging preemptively at a real, if mild, loss) purely to avoid a loss
   that curtailment already eliminates in reality. When export_curtailment_
   enabled is True, the DP substitutes an effective sell price of 0.0 (rather
   than the raw negative price) into its reward calculation for periods where
   the raw sell_price < export_curtailment_price_floor -- but ONLY inside the
   reward/action-selection calculation, never in the reported
   PeriodData.economic.sell_price (which stays the real market price, both
   for accurate display and because BSM's execution-time trigger above reads
   it directly).
"""

from types import SimpleNamespace

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.tests.conftest import MockHomeAssistantController

PERIOD = 20


def _make_bsm() -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource([0.2] * 96),
        addon_options={"inverter": {"platform": "growatt_server_min"}},
    )
    # Replace with a platform that actually supports export-limit control —
    # the growatt_server_min controller from addon_options resolution above
    # does not (cloud has no export-limit service, see #269 diagnosis).
    bsm._inverter_controller = SolaxModbusGrowattController(
        bsm.battery_settings, control_mode="tou"
    )
    return bsm, controller


def _set_intent(bsm: BatterySystemManager, period: int, intent: str) -> None:
    intents = ["IDLE"] * 96
    intents[period] = intent
    bsm._inverter_controller.strategic_intents = intents
    bsm._inverter_controller.current_schedule = SimpleNamespace(actions=[0.0] * 96)


def _store_period(
    bsm: BatterySystemManager,
    period: int,
    grid_exported: float,
    sell_price: float,
) -> None:
    energy = EnergyData(
        solar_production=grid_exported,
        home_consumption=0.0,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=grid_exported,
        battery_soe_start=10.0,
        battery_soe_end=10.0,
    )
    decision = DecisionData(strategic_intent="SOLAR_STORAGE")
    period_data = PeriodData(
        period=period,
        energy=energy,
        timestamp=time_utils.period_index_to_timestamp(period),
        economic=EconomicData(sell_price=sell_price),
        decision=decision,
    )
    result = OptimizationResult(input_data={}, period_data=[period_data])
    bsm.schedule_store.store_schedule(result, optimization_period=period)


class TestExportLimitCurtailment:
    def test_curtails_when_exporting_at_negative_price(self):
        bsm, controller = _make_bsm()
        bsm.battery_settings.export_curtailment_enabled = True
        bsm.battery_settings.export_curtailment_price_floor = 0.0
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_period(bsm, PERIOD, grid_exported=0.5, sell_price=-0.01)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["growatt_export_limit"] == [True]

    def test_releases_when_price_non_negative(self):
        bsm, controller = _make_bsm()
        bsm.battery_settings.export_curtailment_enabled = True
        bsm.battery_settings.export_curtailment_price_floor = 0.0
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_period(bsm, PERIOD, grid_exported=0.5, sell_price=0.05)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["growatt_export_limit"] == [False]

    def test_no_curtailment_when_not_exporting(self):
        """Negative price but nothing is being exported this period — no-op,
        nothing to curtail (and no need to write "Disabled" every period)."""
        bsm, controller = _make_bsm()
        bsm.battery_settings.export_curtailment_enabled = True
        bsm.battery_settings.export_curtailment_price_floor = 0.0
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_period(bsm, PERIOD, grid_exported=0.0, sell_price=-0.01)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["growatt_export_limit"] == []

    def test_disabled_by_setting_is_a_noop(self):
        """export_curtailment_enabled=False (the default) — never writes,
        even if exporting at a negative price. Opt-in only: requires a CT/
        smart meter most users don't have configured."""
        bsm, controller = _make_bsm()
        bsm.battery_settings.export_curtailment_enabled = False
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_period(bsm, PERIOD, grid_exported=0.5, sell_price=-0.01)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["growatt_export_limit"] == []

    def test_platform_without_capability_is_a_noop(self):
        """growatt_server (cloud) has no export-limit service — the base
        InverterController.apply_export_limit no-op must not raise or write
        anything, even with curtailment enabled and conditions met."""
        controller = MockHomeAssistantController()
        bsm = BatterySystemManager(
            controller=controller,
            price_source=MockSource([0.2] * 96),
            addon_options={"inverter": {"platform": "growatt_server_min"}},
        )
        bsm.battery_settings.export_curtailment_enabled = True
        bsm.battery_settings.export_curtailment_price_floor = 0.0
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_period(bsm, PERIOD, grid_exported=0.5, sell_price=-0.01)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["growatt_export_limit"] == []


def _curtailment_scenario(export_curtailment_enabled: bool):
    """2-period scenario isolating the DP's earlier-period reward-propagation
    bug: period 0 can preemptively discharge 1 kWh at a mild loss
    (sell_price=-0.1) to create exactly enough room for period 1's 1 kWh
    solar surplus, avoiding forced export at period 1's much worse
    sell_price=-3.0 (below the 0.0 curtailment floor). Confirmed empirically
    (not just hand-derived) against the real optimizer:

    - Raw sell_price fed straight into the reward (today's behavior,
      independent of export_curtailment_enabled -- this is exactly the bug):
      DP discharges 1 kWh at period 0 (BATTERY_EXPORT) to defend against
      period 1's real, uncurtailed loss.
    - sell_price[1] effectively floored to 0.0 (simulating the fix): DP holds
      (IDLE) at period 0 instead -- discharging at a loss to avoid a period-1
      cost that curtailment will neutralize anyway is no longer worth it.

    terminal_value_per_kwh=0.3 gives holding stored energy to the end of the
    horizon a genuine competing value (otherwise a positive-or-neutral
    discharge would trivially dominate regardless of curtailment).
    """
    bs = BatterySettings(
        total_capacity=2.0,
        min_soc=0.0,
        max_soc=100.0,
        max_charge_power_kw=2.0,
        max_discharge_power_kw=2.0,
        efficiency_charge=1.0,
        efficiency_discharge=1.0,
        cycle_cost_per_kwh=0.0,
    )
    bs.export_curtailment_enabled = export_curtailment_enabled
    bs.export_curtailment_price_floor = 0.0
    return optimize_battery_schedule(
        buy_price=[1.0, 1.0],
        sell_price=[-0.1, -3.0],
        home_consumption=[0.0, 0.0],
        battery_settings=bs,
        solar_production=[0.0, 1.0],
        initial_soe=2.0,
        initial_cost_basis=0.0,
        period_duration_hours=1.0,
        terminal_value_per_kwh=0.3,
    )


class TestDPCurtailmentAwareReward:
    """Does the DP's own plan account for curtailment neutralizing a later
    negative-price export penalty? (#269 follow-up, folded into this PR.)"""

    def test_holds_instead_of_preemptive_loss_discharge_when_enabled(self):
        result = _curtailment_scenario(export_curtailment_enabled=True)
        period0 = result.period_data[0]
        assert period0.decision.strategic_intent == "IDLE"
        assert period0.energy.battery_discharged == 0.0

    def test_still_defends_with_preemptive_discharge_when_disabled(self):
        """Sanity check: curtailment disabled means the period-1 loss is
        real, so preemptively discharging at a mild loss to avoid it remains
        the correct (and unchanged) call."""
        result = _curtailment_scenario(export_curtailment_enabled=False)
        period0 = result.period_data[0]
        assert period0.decision.strategic_intent == "BATTERY_EXPORT"
        assert period0.energy.battery_discharged == 1.0

    def test_reported_sell_price_stays_the_real_market_price(self):
        """The effective-price substitution must never leak into reported
        PeriodData -- BSM's execution-time curtailment trigger
        (_apply_period_schedule) reads economic.sell_price directly, and it
        must still see the real (negative) price to decide whether to
        curtail. Only the DP's internal reward/action-selection calculation
        should ever see the floored effective price."""
        result = _curtailment_scenario(export_curtailment_enabled=True)
        period1 = result.period_data[1]
        assert period1.economic.sell_price == -3.0
