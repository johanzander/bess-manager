"""User force mode: an override of the plan, held until cleared.

The optimizer keeps planning; only the command follows the override. Outcomes
are asserted through the Growatt MIN execution model
(`core/bess/simulation/inverter_simulator.py`) wherever it can see the
behaviour. The write-path gates in `BatterySystemManager._apply_period_schedule`
read the commanded decisions, which no execution model sees, so those tests
assert the command that lands on the inverter instead -- the same stance as
`test_vpp_idle_gate_release.py`.
"""

from types import SimpleNamespace
from typing import cast

import pytest

from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.dp_schedule import DPSchedule
from core.bess.exceptions import SystemConfigurationError
from core.bess.force_mode import FORCE_MODES, apply_force_mode
from core.bess.models import (
    DecisionData,
    EconomicData,
    EnergyData,
    OptimizationResult,
    PeriodData,
)
from core.bess.price_manager import MockSource
from core.bess.settings import BatterySettings
from core.bess.simulation.inverter_simulator import (
    ControlCommand,
    SimulationResult,
    derive_control_command,
    simulate,
)
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.tests.conftest import MockHomeAssistantController
from core.bess.tests.helpers import make_battery_settings

PERIODS = 96
DT = 24.0 / PERIODS


def _plan(
    intent: str,
    action_kwh: float,
    periods: int = PERIODS,
    period_data: list[PeriodData | None] | None = None,
) -> DPSchedule:
    return DPSchedule(
        actions=[action_kwh] * periods,
        state_of_energy=[10.0] * periods,
        prices=[1.0] * periods,
        original_dp_results={
            "strategic_intent": [intent] * periods,
            "period_data": period_data or [],
        },
    )


def _planned_period(
    period: int,
    intent: str,
    discharge_allowed: bool,
    grid_exported: float = 0.0,
    sell_price: float = 0.5,
    curtailed: bool = False,
) -> PeriodData:
    """One period as the optimizer planned it, timestamped like production."""
    return PeriodData(
        period=period,
        energy=EnergyData(
            solar_production=grid_exported,
            home_consumption=0.0,
            battery_charged=0.0,
            battery_discharged=0.0,
            grid_imported=0.0,
            grid_exported=grid_exported,
            battery_soe_start=10.0,
            battery_soe_end=10.0,
        ),
        timestamp=time_utils.period_index_to_timestamp(period),
        economic=EconomicData(sell_price=sell_price),
        decision=DecisionData(
            strategic_intent=intent,
            intra_period_discharge_allowed=discharge_allowed,
            curtailed=curtailed,
        ),
    )


def _commands(schedule: DPSchedule, settings: BatterySettings) -> list[ControlCommand]:
    dt = 24.0 / len(schedule.actions)
    return [
        derive_control_command(intent, action / dt, settings)
        for intent, action in zip(
            schedule.strategic_intents, schedule.actions, strict=True
        )
    ]


def _run(
    schedule: DPSchedule,
    settings: BatterySettings,
    solar: float,
    home: float,
    soe: float,
) -> SimulationResult:
    n = len(schedule.actions)
    return simulate(
        _commands(schedule, settings),
        solar_production=[solar] * n,
        home_consumption=[home] * n,
        buy_price=[1.0] * n,
        sell_price=[0.5] * n,
        initial_soe=soe,
        settings=settings,
        dt=24.0 / n,
    )


class TestForcedSchedule:
    def test_periods_before_the_override_keep_the_plan(self) -> None:
        settings = make_battery_settings()
        plan = _plan("GRID_CHARGING", 1.0)

        forced = apply_force_mode(plan, "BATTERY_EXPORT", 40, settings)

        assert forced.strategic_intents[:40] == ["GRID_CHARGING"] * 40
        assert forced.actions[:40] == [1.0] * 40
        assert forced.strategic_intents[40:] == ["BATTERY_EXPORT"] * 56
        assert forced.forced_from_period == 40

    def test_the_plan_itself_is_not_changed(self) -> None:
        settings = make_battery_settings()
        plan = _plan(
            "IDLE",
            0.0,
            period_data=[_planned_period(p, "IDLE", True) for p in range(PERIODS)],
        )

        apply_force_mode(plan, "BATTERY_EXPORT", 0, settings)

        assert plan.strategic_intents == ["IDLE"] * PERIODS
        assert plan.forced_from_period is None
        # The dashboard shows the stored plan, which shares these records.
        assert all(
            p.decision.strategic_intent == "IDLE"
            and p.decision.intra_period_discharge_allowed
            for p in plan.period_data
        )

    def test_forced_periods_carry_the_forced_commands_decisions(self) -> None:
        """Every reader of the commanded schedule's decisions -- the write path,
        the schedule view, the period-list platforms -- sees the forced mode,
        not the plan's verdicts, without a forced check of its own."""
        settings = make_battery_settings()
        planned: list[PeriodData | None] = [
            _planned_period(p, "SOLAR_STORAGE", True, grid_exported=0.4, curtailed=True)
            for p in range(PERIODS)
        ]
        planned[0] = None  # an elapsed period the optimization did not cover
        plan = _plan("SOLAR_STORAGE", 0.0, period_data=planned)

        forced = apply_force_mode(plan, "BATTERY_EXPORT", 40, settings)

        assert forced.period_data[0] is None
        assert forced.period_data[39] is plan.period_data[39]
        decision = forced.period_data[40].decision
        assert decision.strategic_intent == "BATTERY_EXPORT"
        assert decision.battery_action == forced.actions[40]
        assert decision.intra_period_discharge_allowed is False
        assert decision.curtailed is False
        # Energy stays the plan's: what a forced period's flows would be is
        # not modelled (a forecast-dependent simulation, out of scope here).
        assert forced.period_data[40].energy is plan.period_data[40].energy
        assert forced.period_data[40].timestamp == plan.period_data[40].timestamp

    def test_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            apply_force_mode(
                _plan("IDLE", 0.0), "SOLAR_EXPORT", 0, make_battery_settings()
            )


class TestForcedOutcomes:
    """What the battery does under each forced mode, against a plan that would
    have done something else."""

    def test_forced_export_discharges_to_the_grid_at_full_power(self) -> None:
        settings = make_battery_settings()
        forced = apply_force_mode(_plan("IDLE", 0.0), "BATTERY_EXPORT", 0, settings)

        first = _run(forced, settings, solar=0.0, home=0.0, soe=18.0).period_data[0]

        assert first.energy.battery_discharged == pytest.approx(
            settings.max_discharge_power_kw * DT, rel=0.01
        )
        assert first.energy.grid_exported > 0.9 * settings.max_discharge_power_kw * DT

    def test_forced_grid_charge_charges_at_full_power(self) -> None:
        settings = make_battery_settings()
        forced = apply_force_mode(_plan("IDLE", 0.0), "GRID_CHARGING", 0, settings)

        first = _run(forced, settings, solar=0.0, home=0.0, soe=5.0).period_data[0]

        assert first.energy.grid_imported == pytest.approx(
            settings.max_charge_power_kw * DT, rel=0.01
        )

    def test_forced_solar_storage_never_discharges_into_the_load(self) -> None:
        settings = make_battery_settings()
        plan = _plan("LOAD_SUPPORT", -0.5)
        # The plan itself would cover the house from the battery.
        planned = _run(plan, settings, solar=0.0, home=0.5, soe=15.0).period_data
        assert planned[0].energy.battery_discharged > 0

        forced = apply_force_mode(plan, "SOLAR_STORAGE", 0, settings)
        realized = _run(forced, settings, solar=0.0, home=0.5, soe=15.0).period_data

        assert all(p.energy.battery_discharged == 0 for p in realized)

    def test_forced_load_support_covers_the_house_without_exporting(self) -> None:
        settings = make_battery_settings()
        forced = apply_force_mode(_plan("IDLE", 0.0), "LOAD_SUPPORT", 0, settings)

        first = _run(forced, settings, solar=0.0, home=0.3, soe=15.0).period_data[0]

        assert first.energy.grid_imported == pytest.approx(0.0, abs=1e-9)
        assert first.energy.grid_exported == pytest.approx(0.0, abs=1e-9)

    @pytest.mark.parametrize("periods", [92, 100])
    def test_full_power_holds_on_dst_days(self, periods: int) -> None:
        """A 23- or 25-hour day still commands the full rate: the forced action
        uses the same period length every reader of the schedule converts with."""
        settings = make_battery_settings()
        forced = apply_force_mode(
            _plan("IDLE", 0.0, periods), "BATTERY_EXPORT", 0, settings
        )

        command = _commands(forced, settings)[0]

        assert command.discharge_rate_pct == 100


PERIOD = 40


def _make_bsm(
    platform: str = "growatt_server_min",
) -> tuple[BatterySystemManager, MockHomeAssistantController]:
    controller = MockHomeAssistantController()
    controller.settings["battery_soc"] = 60.0
    bsm = BatterySystemManager(
        controller=controller,
        price_source=MockSource([2.0] * PERIODS),
        addon_options={"inverter": {"platform": platform}},
    )
    return bsm, controller


def _command_forced(
    bsm: BatterySystemManager,
    plan_intent: str,
    mode: str,
    planned: PeriodData | None = None,
) -> None:
    """Command ``mode`` over a plan of ``plan_intent``. ``planned`` is the
    plan's own record of PERIOD -- in production the commanded schedule is
    built from the very PeriodData the schedule store holds."""
    inverter_controller = bsm._inverter_controller
    assert inverter_controller is not None
    period_data: list[PeriodData | None] = [None] * PERIODS
    period_data[PERIOD] = planned
    forced = apply_force_mode(
        _plan(plan_intent, 0.0, period_data=period_data),
        mode,
        PERIOD,
        bsm.battery_settings,
    )
    inverter_controller.strategic_intents = forced.strategic_intents
    inverter_controller.current_schedule = forced


def _command_plan(bsm: BatterySystemManager, intent: str) -> None:
    inverter_controller = bsm._inverter_controller
    assert inverter_controller is not None
    inverter_controller.strategic_intents = [intent] * PERIODS
    inverter_controller.current_schedule = cast(
        DPSchedule,
        SimpleNamespace(forced_from_period=None, actions=[1.0] * PERIODS),
    )


def _store_plan_period(
    bsm: BatterySystemManager,
    intent: str,
    discharge_allowed: bool,
    grid_exported: float = 0.0,
    sell_price: float = 0.5,
) -> PeriodData:
    period_data = _planned_period(
        PERIOD, intent, discharge_allowed, grid_exported, sell_price
    )
    result = OptimizationResult(input_data={}, period_data=[period_data])
    bsm.schedule_store.store_schedule(result, optimization_period=PERIOD)
    return period_data


class TestWritePathFollowsTheOverride:
    def test_forced_solar_storage_ignores_the_plans_open_discharge_verdict(
        self,
    ) -> None:
        """The plan's verdict would lift the ceiling to 100% (the unforced case
        in test_solar_storage_discharge_gate.py); a forced SOLAR_STORAGE must
        not discharge."""
        bsm, controller = _make_bsm()
        planned = _store_plan_period(bsm, "SOLAR_STORAGE", discharge_allowed=True)
        _command_forced(bsm, "SOLAR_STORAGE", "SOLAR_STORAGE", planned)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 0

    def test_forced_export_writes_the_full_rate(self) -> None:
        bsm, controller = _make_bsm()
        _command_forced(bsm, "IDLE", "BATTERY_EXPORT")
        _store_plan_period(bsm, "IDLE", discharge_allowed=False)

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["discharge_rate"][-1] == 100

    def test_forced_export_is_not_curtailed_by_the_plans_export_verdict(self) -> None:
        bsm, controller = _make_bsm()
        bsm._inverter_controller = SolaxModbusGrowattController(
            bsm.battery_settings, control_mode="tou"
        )
        bsm.battery_settings.export_curtailment_enabled = True
        bsm.battery_settings.export_curtailment_price_floor = 0.0
        _command_forced(bsm, "SOLAR_STORAGE", "BATTERY_EXPORT")
        # The unforced plan exports at a negative price -> it would curtail.
        _store_plan_period(
            bsm, "SOLAR_STORAGE", False, grid_exported=0.5, sell_price=-0.01
        )

        bsm._apply_period_schedule(PERIOD)

        assert True not in controller.calls["growatt_export_limit"]

    def test_forced_export_releases_a_curtailment_left_on_from_the_plan(self) -> None:
        bsm, controller = _make_bsm()
        bsm._inverter_controller = SolaxModbusGrowattController(
            bsm.battery_settings, control_mode="tou"
        )
        bsm.battery_settings.export_curtailment_enabled = True
        bsm._export_limit_curtailed = True
        _command_forced(bsm, "SOLAR_STORAGE", "BATTERY_EXPORT")

        bsm._apply_period_schedule(PERIOD)

        assert controller.calls["growatt_export_limit"] == [False]

    def test_forced_idle_holds_on_vpp_although_the_plan_would_release(self) -> None:
        """On Growatt VPP a planned IDLE whose verdict is open releases control
        (#786); a forced IDLE is a hold the user asked for."""
        controller = MockHomeAssistantController()
        controller.settings["battery_soc"] = 60.0
        bsm = BatterySystemManager(
            controller=controller,
            price_source=MockSource([2.2] * PERIODS),
            addon_options={
                "inverter": {
                    "platform": "solax_modbus_growatt_min",
                    "control_mode": "vpp",
                }
            },
        )
        planned = _store_plan_period(bsm, "IDLE", discharge_allowed=True)
        _command_forced(bsm, "IDLE", "IDLE", planned)

        bsm._apply_period_schedule(PERIOD)

        command = controller.calls["growatt_vpp_periods"][-1]
        assert command["remote_control_enabled"] is True
        assert command["power_pct"] == 1

    def test_history_records_the_forced_intent(self) -> None:
        bsm, _ = _make_bsm()
        _command_forced(bsm, "GRID_CHARGING", "SOLAR_STORAGE")
        _store_plan_period(bsm, "GRID_CHARGING", discharge_allowed=False)

        bsm._apply_period_schedule(PERIOD)

        assert bsm._commanded_intent_for_period(PERIOD) == "SOLAR_STORAGE"

    def test_an_unforced_period_records_the_planned_intent(self) -> None:
        bsm, _ = _make_bsm()
        _command_plan(bsm, "GRID_CHARGING")
        _store_plan_period(bsm, "GRID_CHARGING", discharge_allowed=False)

        bsm._apply_period_schedule(PERIOD)

        assert bsm._commanded_intent_for_period(PERIOD) == "GRID_CHARGING"

    def test_clearing_mid_period_records_the_planned_intent(self) -> None:
        """The period is re-applied from the plan once cleared; history and the
        GRID_CHARGING cost-basis split must follow that, not the earlier
        forced command."""
        bsm, _ = _make_bsm()
        _command_forced(bsm, "GRID_CHARGING", "SOLAR_STORAGE")
        _store_plan_period(bsm, "GRID_CHARGING", discharge_allowed=False)
        bsm._apply_period_schedule(PERIOD)

        _command_plan(bsm, "GRID_CHARGING")
        bsm._apply_period_schedule(PERIOD)

        assert bsm._commanded_intent_for_period(PERIOD) == "GRID_CHARGING"


class TestScheduleViewFollowsTheOverride:
    def test_forced_idle_shows_the_hold_although_the_plan_would_release(
        self,
    ) -> None:
        """On Growatt VPP a planned IDLE with an open verdict shows the release
        (#786); the forced IDLE the write path holds must show as the hold."""
        settings = BatterySettings(total_capacity=50.0, min_soc=10.0, max_soc=95.0)
        inverter = SolaxModbusGrowattController(settings, control_mode="vpp")
        plan = _plan(
            "IDLE",
            0.0,
            period_data=[_planned_period(p, "IDLE", True) for p in range(PERIODS)],
        )
        inverter.strategic_intents = plan.strategic_intents
        inverter.current_schedule = plan
        assert inverter.get_period_settings(PERIOD)["vpp_remote_control"] is False

        forced = apply_force_mode(plan, "IDLE", PERIOD, settings)
        inverter.strategic_intents = forced.strategic_intents
        inverter.current_schedule = forced

        fields = inverter.get_period_settings(PERIOD)
        assert fields["vpp_power_pct"] == 1
        assert fields["vpp_remote_control"] is True


class TestForceModeLifecycle:
    def test_unsupported_mode_is_rejected(self) -> None:
        bsm, _ = _make_bsm("solax_modbus_native")

        with pytest.raises(SystemConfigurationError):
            bsm.set_force_mode("LOAD_SUPPORT")
        assert bsm.force_mode is None

    @pytest.mark.parametrize(
        ("platform", "missing"),
        [
            ("growatt_server_min", set()),
            ("growatt_server_sph", set()),
            ("solax_modbus_growatt_min", set()),
            ("huawei_solar_luna2000", set()),
            # Its LOAD_SUPPORT rate is a forced power, not a ceiling.
            ("solax_modbus_native", {"LOAD_SUPPORT"}),
            # Export slots and holds are built from the plan's period_data.
            ("solis_modbus", {"BATTERY_EXPORT", "IDLE"}),
        ],
    )
    def test_supported_modes_per_platform(
        self, platform: str, missing: set[str]
    ) -> None:
        bsm, _ = _make_bsm(platform)

        assert bsm.supported_force_modes == FORCE_MODES - missing

    def test_switching_to_a_platform_that_cannot_run_the_mode_drops_it_visibly(
        self,
    ) -> None:
        bsm, _ = _make_bsm("growatt_server_min")
        bsm.set_force_mode("LOAD_SUPPORT")

        bsm.switch_inverter_platform("solax_modbus_native")

        assert bsm.force_mode is None
        assert any(f.category == "force_mode" for f in bsm.get_runtime_failures())

    def test_clearing_returns_to_the_plan(self) -> None:
        bsm, _ = _make_bsm()
        bsm.set_force_mode("BATTERY_EXPORT")

        bsm.set_force_mode(None)

        assert bsm.force_mode is None
