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
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_battery_algorithm import (
    _create_idle_schedule,
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
from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.terminal_value import TerminalValueCurve
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.tests.unit.test_scenarios import build_scenario_optimizer_inputs

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


class TestExportLimitReleaseNotStuck:
    """Regression: release must fire even when a later period's own plan
    doesn't call for export, not just when grid_exported > 0 for that period
    (code review on #459 -- the register was getting stuck curtailed)."""

    def test_releases_on_a_later_period_with_no_planned_export(self):
        bsm, controller = _make_bsm()
        bsm.battery_settings.export_curtailment_enabled = True
        bsm.battery_settings.export_curtailment_price_floor = 0.0
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_period(bsm, PERIOD, grid_exported=0.5, sell_price=-0.01)
        bsm._apply_period_schedule(PERIOD)
        assert controller.calls["growatt_export_limit"] == [True]

        # Next period: price has recovered, but this period's own plan calls
        # for zero export (e.g. battery has headroom) -- must still release.
        next_period = PERIOD + 1
        _set_intent(bsm, next_period, "SOLAR_STORAGE")
        _store_period(bsm, next_period, grid_exported=0.0, sell_price=0.10)
        bsm._apply_period_schedule(next_period)

        assert controller.calls["growatt_export_limit"] == [True, False]

    def test_stays_quiet_when_never_curtailed(self):
        """No spurious release writes on a system that's never curtailed."""
        bsm, controller = _make_bsm()
        bsm.battery_settings.export_curtailment_enabled = True
        bsm.battery_settings.export_curtailment_price_floor = 0.0
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_period(bsm, PERIOD, grid_exported=0.0, sell_price=0.10)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["growatt_export_limit"] == []


class TestExportLimitFailureIsolated:
    """Regression: a curtailment write failure (e.g. unconfigured entity)
    must not take down the rest of the period's hardware apply -- code
    review on #459 found _get_entity_for_service's ValueError propagating
    out of _apply_period_schedule uncaught, aborting apply_period() too."""

    def test_curtailment_exception_does_not_block_apply_period(self):
        bsm, controller = _make_bsm()
        bsm.battery_settings.export_curtailment_enabled = True
        bsm.battery_settings.export_curtailment_price_floor = 0.0
        bsm._inverter_controller.apply_export_limit = MagicMock(
            side_effect=ValueError("No entity ID configured for Export Limit Mode")
        )
        _set_intent(bsm, PERIOD, "SOLAR_STORAGE")
        _store_period(bsm, PERIOD, grid_exported=0.5, sell_price=-0.01)

        bsm._apply_period_schedule(PERIOD)  # must not raise

        assert controller.calls["discharge_rate"], (
            "apply_period's real hardware write must still run despite the "
            "curtailment failure"
        )


def _curtailment_scenario(
    export_curtailment_active: bool, export_curtailment_enabled: bool = False
):
    """2-period scenario isolating the DP's earlier-period reward-propagation
    bug: period 0 can preemptively discharge 1 kWh at a mild loss
    (sell_price=-0.1) to create exactly enough room for period 1's 1 kWh
    solar surplus, avoiding forced export at period 1's much worse
    sell_price=-3.0 (below the 0.0 curtailment floor). Confirmed empirically
    (not just hand-derived) against the real optimizer:

    - Raw sell_price fed straight into the reward (today's behavior,
      independent of the setting -- this is exactly the bug): DP discharges
      1 kWh at period 0 (BATTERY_EXPORT) to defend against period 1's real,
      uncurtailed loss.
    - sell_price[1] effectively floored to 0.0 (simulating the fix): DP holds
      (IDLE) at period 0 instead -- discharging at a loss to avoid a period-1
      cost that curtailment will neutralize anyway is no longer worth it.

    terminal_curve=flat(0.3) gives holding stored energy to the end of the
    horizon a genuine competing value (otherwise a positive-or-neutral
    discharge would trivially dominate regardless of curtailment).

    export_curtailment_active is the caller-computed, capability-aware flag
    (battery_settings.export_curtailment_enabled AND the platform actually
    supports it AND the entities are configured) -- the DP reads only this,
    never the raw settings field, so it can never plan as if curtailment
    will happen on a platform/config that can't actually do it (#459 review).
    export_curtailment_enabled is the raw user setting, passed separately
    to prove the DP ignores it when not also reflected in the active flag.
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
        terminal_curve=TerminalValueCurve.flat(0.3),
        export_curtailment_active=export_curtailment_active,
    )


class TestDPCurtailmentAwareReward:
    """Does the DP's own plan account for curtailment neutralizing a later
    negative-price export penalty? (#269 follow-up, folded into this PR.)"""

    def test_holds_instead_of_preemptive_loss_discharge_when_active(self):
        result = _curtailment_scenario(export_curtailment_active=True)
        period0 = result.period_data[0]
        assert period0.decision.strategic_intent == "IDLE"
        assert period0.energy.battery_discharged == 0.0

    def test_still_defends_with_preemptive_discharge_when_inactive(self):
        """Sanity check: curtailment inactive means the period-1 loss is
        real, so preemptively discharging at a mild loss to avoid it remains
        the correct (and unchanged) call."""
        result = _curtailment_scenario(export_curtailment_active=False)
        period0 = result.period_data[0]
        assert period0.decision.strategic_intent == "BATTERY_EXPORT"
        assert period0.energy.battery_discharged == 1.0

    def test_ignores_raw_setting_when_not_reflected_in_active_flag(self):
        """Regression (#459 review): the user setting alone must never make
        the DP plan for curtailment on an unsupported/unconfigured platform
        -- only the caller-computed, capability-aware active flag can."""
        result = _curtailment_scenario(
            export_curtailment_active=False, export_curtailment_enabled=True
        )
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
        result = _curtailment_scenario(export_curtailment_active=True)
        period1 = result.period_data[1]
        assert period1.economic.sell_price == -3.0


def _forced_export_scenario(export_curtailment_active: bool) -> OptimizationResult:
    """Solar surplus large enough (5 kWh into a 1 kWh battery) that period 1
    exports regardless of whatever the DP did in period 0 -- isolates the
    display-flag question from the preemptive-discharge behavior covered by
    TestDPCurtailmentAwareReward above."""
    bs = BatterySettings(
        total_capacity=1.0,
        min_soc=0.0,
        max_soc=100.0,
        max_charge_power_kw=1.0,
        max_discharge_power_kw=1.0,
        efficiency_charge=1.0,
        efficiency_discharge=1.0,
        cycle_cost_per_kwh=0.0,
    )
    bs.export_curtailment_enabled = export_curtailment_active
    bs.export_curtailment_price_floor = 0.0
    return optimize_battery_schedule(
        buy_price=[1.0, 1.0],
        sell_price=[0.1, -3.0],
        home_consumption=[0.0, 0.0],
        battery_settings=bs,
        solar_production=[0.0, 5.0],
        initial_soe=1.0,
        initial_cost_basis=0.0,
        period_duration_hours=1.0,
        export_curtailment_active=export_curtailment_active,
    )


class TestDPCurtailmentDisplayFlag:
    """The plan itself must be able to report which periods it curtails
    (#501) -- BSM's execution-time gate (TestExportLimitCurtailment above)
    decides this per period as it dispatches, but never writes the verdict
    back onto PeriodData, so the UI has no way to distinguish a curtailed
    period from a genuinely profitable export."""

    def test_flags_period_as_curtailed_when_active_and_below_floor(self):
        result = _forced_export_scenario(export_curtailment_active=True)
        period1 = result.period_data[1]
        assert period1.energy.grid_exported > 0
        assert period1.economic.sell_price < 0.0  # below the 0.0 floor
        assert period1.decision.curtailed is True

    def test_does_not_flag_when_curtailment_inactive(self):
        """Same negative-price export, but curtailment isn't active on this
        platform/config -- must not be flagged as curtailed."""
        result = _forced_export_scenario(export_curtailment_active=False)
        period1 = result.period_data[1]
        assert period1.energy.grid_exported > 0
        assert period1.decision.curtailed is False


class TestBellmanGuardrailNotFooledByFloor:
    """Regression (#459 review, verified by bess-analyst against the real
    optimizer with a randomized sweep, ~1-4% of realistic volatile-price
    scenarios): the "never worse than all-IDLE" numerical safety net
    compares total_optimized_cost (tallied at the REAL, un-floored price)
    against an all-IDLE schedule's REAL-price cost. But the DP's action
    selection optimized against the FLOORED reward_sell_price when
    export_curtailment_active -- an internally inconsistent comparison that
    can silently discard the whole curtailment-aware plan and fall back to
    all-IDLE, even though the DP's own (floored) objective judged its plan
    better. The guardrail must compare both sides on the SAME objective the
    DP actually optimized.

    Minimal real repro found via a randomized sweep against the actual
    optimizer (not hand-derived): at these exact inputs, the pre-fix
    guardrail discards the DP's plan and returns _create_idle_schedule's
    output verbatim (cost 3.162626315789474, identical intents) even though
    the DP's own floored-reward search preferred an active plan."""

    BUY: ClassVar[list[float]] = [0.383, 0.369, 1.762, 2.836, 1.329, 0.885]
    SELL: ClassVar[list[float]] = [-0.889, -2.855, -1.892, -0.811, -0.521, -1.835]
    HOME: ClassVar[list[float]] = [0.35, 0.33, 0.69, 0.43, 0.03, 1.26]
    SOLAR: ClassVar[list[float]] = [1.11, 1.28, 0.37, 1.99, 1.72, 0.24]
    CAP = 5.0
    CYCLE_COST = 0.269
    INITIAL_SOE = 1.5

    def _battery_settings(self):
        return BatterySettings(
            total_capacity=self.CAP,
            min_soc=0.0,
            max_soc=100.0,
            max_charge_power_kw=self.CAP,
            max_discharge_power_kw=self.CAP,
            efficiency_charge=0.95,
            efficiency_discharge=0.95,
            cycle_cost_per_kwh=self.CYCLE_COST,
        )

    def test_does_not_silently_fall_back_to_the_idle_schedule(self):
        idle = _create_idle_schedule(
            horizon=6,
            buy_price=self.BUY,
            sell_price=self.SELL,
            home_consumption=self.HOME,
            solar_production=self.SOLAR,
            initial_soe=self.INITIAL_SOE,
            battery_settings=self._battery_settings(),
            dt=0.25,
            currency="SEK",
        )

        result = optimize_battery_schedule(
            buy_price=self.BUY,
            sell_price=self.SELL,
            home_consumption=self.HOME,
            battery_settings=self._battery_settings(),
            solar_production=self.SOLAR,
            initial_soe=self.INITIAL_SOE,
            initial_cost_basis=self.CYCLE_COST,
            period_duration_hours=0.25,
            export_curtailment_active=True,
        )

        assert result.economic_summary.battery_solar_cost != (
            idle.economic_summary.battery_solar_cost
        )

    def test_matches_the_dps_own_floored_objective_choice(self):
        """With export_curtailment_active=False on the same inputs, the
        guardrail already compares real-price-vs-real-price correctly (no
        floor substitution involved) -- confirm it picks a genuinely
        different, non-idle plan there too, so this scenario is a real
        DP-prefers-active-plan case, not just an idle-schedule quirk."""
        result = optimize_battery_schedule(
            buy_price=self.BUY,
            sell_price=self.SELL,
            home_consumption=self.HOME,
            battery_settings=self._battery_settings(),
            solar_production=self.SOLAR,
            initial_soe=self.INITIAL_SOE,
            initial_cost_basis=self.CYCLE_COST,
            period_duration_hours=0.25,
            export_curtailment_active=False,
        )
        assert any(p.energy.battery_discharged > 0 for p in result.period_data)


class TestDPCurtailmentDisplayFlagOnRealFieldReport:
    """Reproduces @Frank-Leysen's live #501 report (8 Aug 2026, 09:11 CEST,
    10.1.0b5, gist 626de4276692d2f2c76cf4ef025478ea) from the real debug
    bundle -- not a hand-built scenario. The plan showed SOLAR_EXPORT at
    13:45 and 14:15-14:59 (sell price ~-EUR0.021) with SOC 73-78%, and the
    reporter reasonably read that as "paying to export with room to spare."
    Actual behaviour: curtailment is active, so those periods (and several
    SOLAR_STORAGE ones alongside them) cost EUR0 -- the plan was right, the
    display was wrong."""

    def test_flags_the_reported_periods_as_curtailed(self):
        _, inputs = build_scenario_optimizer_inputs("regression_frank_debug_2026_08_08")
        # `export_curtailment_active` is the one input this test sets rather
        # than replays: the fixture does not record it, and curtailment being
        # active is the whole premise of Frank's report. Everything else comes
        # from the fixture -- hand-listing the arguments here previously
        # dropped its `initial_cost_basis` (0.035).
        result = optimize_battery_schedule(
            **{**inputs, "export_curtailment_active": True}
        )

        # Fixture horizon starts at absolute period 36 (09:00); Frank's
        # reported 13:45 and 14:15 slots are absolute periods 55 and 57.
        by_period = {36 + i: pd for i, pd in enumerate(result.period_data)}

        # 13:45 planned as SOLAR_EXPORT at the time of Frank's report; the
        # charge-early tie-break under the curtailment price floor
        # (c26dfad4) now resolves it to charging instead, with the sub-rate
        # surplus still exporting below the floor -- the SOLAR_STORAGE-
        # while-curtailed case, which must be flagged all the same.
        period_1345 = by_period[13 * 4 + 3]
        assert period_1345.decision.strategic_intent == "SOLAR_STORAGE"
        assert period_1345.decision.curtailed is True

        period_1415 = by_period[14 * 4 + 1]
        assert period_1415.decision.strategic_intent == "SOLAR_EXPORT"
        assert period_1415.decision.curtailed is True

        # Sell price matches the reporter's observation (~-EUR0.021).
        assert period_1345.economic.sell_price == pytest.approx(-0.021, abs=0.001)


class TestCurtailedPeriodsNotChargedInReportedCost:
    """Issue #502: a curtailed period's reported cost must reflect what will
    actually happen at runtime (no export, no phantom negative-price charge),
    while PeriodData itself stays honest for BSM's execution-time trigger
    (TestDPCurtailmentAwareReward.test_reported_sell_price_stays_the_real_market_price
    above) and for the DP's own guardrail comparison."""

    def test_battery_solar_cost_excludes_curtailed_export_charge(self):
        """Same DP-produced scenario as
        TestDPCurtailmentAwareReward: period 1 exports 1 kWh at -3.0 (battery
        full, nowhere else for the solar to go) below the 0.0 floor, so it
        will be curtailed to zero export at runtime. The reported aggregate
        must not carry that period's -3.0 export revenue (i.e. +3.0 phantom
        cost) into battery_solar_cost."""
        result = _curtailment_scenario(export_curtailment_active=True)

        period1 = result.period_data[1]
        assert period1.energy.grid_exported == 1.0
        assert period1.economic.sell_price == -3.0

        assert result.economic_summary.battery_solar_cost == pytest.approx(0.0)

    def test_unaffected_when_curtailment_inactive(self):
        """Sanity check: with curtailment inactive, period 0 preemptively
        discharges at a mild loss to defend against period 1's real
        (uncurtailed) loss (TestDPCurtailmentAwareReward), so the reported
        aggregate must be unaffected by the fix here -- confirms the fix is
        conditional on export_curtailment_active, not a blanket change to
        every plan's reported cost."""
        result = _curtailment_scenario(export_curtailment_active=False)

        assert result.economic_summary.battery_solar_cost == pytest.approx(0.1)

    def test_solar_only_baseline_stays_consistent_with_curtailed_total(self):
        """Regression (found in code review on this PR): solar_only_cost --
        the "solar but no battery" baseline used to derive
        solar_to_battery_solar_savings -- must be curtailment-adjusted by
        the SAME transform as battery_solar_cost, or the savings subtraction
        mixes a curtailed total against an honest baseline and misattributes
        curtailment's own savings to the battery. Here the curtailed export
        would happen identically with or without a battery (nothing else in
        the scenario depends on the battery), so once both sides are
        consistently curtailment-adjusted, the battery adds zero measurable
        solar-only savings -- not the inflated ~3.0 SEK an unadjusted
        baseline would report."""
        result = _curtailment_scenario(export_curtailment_active=True)

        assert result.economic_summary.solar_only_cost == pytest.approx(0.0)
        assert result.economic_summary.solar_to_battery_solar_savings == pytest.approx(
            0.0
        )
