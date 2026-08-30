"""Growatt VPP execution model, so VPP behaviour changes are measurable.

`inverter_simulator.py` is Growatt MIN/cloud **TOU** only. Every scenario
fixture, every `run_scenario_realized` call and the whole R == P corpus
therefore covers the TOU path and says nothing about VPP -- which is why
"no regression from beta" was unenforceable for Growatt VPP (#539).

**Read a delta from this as "behaviour changed", never as "behaviour got
worse".** At 15-minute point forecasts there is no within-period load spike
by construction, so this can model the intra-period discharge gate's *cost*
(battery held -> import at buy price) but never its *benefit* (spike covered
from the battery). It will therefore score gate-closed changes as a loss
whether or not they are one. That is not speculative: mirroring the gate for
LOAD_SUPPORT in the TOU simulator moves 27 of 36 fixtures by +25.67 SEK of
realized cost, "purely from the unmodellable half of the trade-off"
(`inverter_simulator._map_rates`). Against a fixed baseline the bias cancels
and a delta means *changed*, which is the question this harness exists to
answer. Quoting a delta as an economic verdict is the misuse to guard
against -- several figures in this repo have already been retracted for
exactly that drift.

The command mapping is NOT re-implemented here. `_intent_to_vpp` on the real
`SolaxModbusGrowattController` is called directly, so the simulator cannot
drift from what production writes -- the P1/P4 lesson from Phases 1 and 3,
where hand-mirrored copies of the same logic were the whole bug class.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from core.bess.dp_battery_algorithm import (
    _build_period_data,
    _effective_ac_cap_kwh,
    _period_flows,
    _state_transition,
)
from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.vpp_load_tracking import budget_for_period


@dataclass(frozen=True)
class VppCommand:
    """One period's Growatt VPP command, as written to hardware."""

    power_pct: int  # -100..100; negative discharge/export, positive charge
    remote_control_enabled: bool
    # Energy this period's load-tracking loop may spend, or None when the
    # period is not tracked (#520). None is not "zero budget": it means the
    # command is one of the pre-#520 ones and is executed by the branches
    # below exactly as before, which is what keeps the flag-off corpus and
    # the #539/#540 baseline valid without re-pinning.
    #
    # Present on the *command* rather than passed alongside it because it is
    # part of what the period was told to do -- `simulate_vpp` returns the
    # command list as its record of what production would write, and a bound
    # that lived outside it would leave that record unable to explain the
    # power the model applied.
    tracking_budget_kwh: float | None = None


def derive_vpp_commands(
    intents: list[str],
    actions_kw: list[float],
    settings: BatterySettings,
    soe_trajectory: list[float],
) -> list[VppCommand]:
    """The VPP commands production would write for a planned schedule.

    `soe_trajectory` supplies the state of energy entering each period, which
    `_intent_to_vpp` needs to answer the reserve-floor question (#592). It is
    required, not defaulted: an optional one is exactly how this harness came
    to derive every command with `at_reserve_floor=False`, leaving the release
    branch unreachable through the whole 37-fixture corpus while the baseline
    looked like it covered it.

    Note this derives commands *eagerly*, so it is only correct where the
    trajectory is already known. `simulate_vpp` does not use it -- there the
    SoE is produced by the simulation itself, so each command is derived from
    the running SoE as the loop reaches it.

    Drives the production path end to end:
    `compute_rates_for_period` -> `_intent_to_vpp`, the same two calls
    `BatterySystemManager._apply_period_schedule` makes. Nothing about the
    intent -> (grid_charge, discharge_rate, block_passive_charging) mapping
    is restated here.

    An earlier revision rebuilt those three values from `INTENT_TO_CONTROL`
    by hand. It happened to agree on every intent, but it was a second copy
    of a mapping that production owns -- the drift this harness exists to
    catch, reintroduced inside the harness itself -- and it carried a
    `.get(intent, IDLE)` fallback where `_map_intent_to_rates` raises on an
    unknown intent, so a typo would have silently simulated IDLE.

    Deliberately does not pass the intra-period discharge decision, so it
    always derives the pre-#520 command for a period (`load_tracking_active`
    defaults False on `_intent_to_vpp`). It is the gate-free baseline the
    #539/#540 pins are captured from. The load-tracking path (#520) needs the
    running SoE and the period length to bound a budget, so it lives only in
    `simulate_vpp`, which carries both; there is no correct eager form of it.
    """
    if len(intents) != len(actions_kw):
        # The loop below iterates `actions_kw` and indexes `intents`, so a
        # short `actions_kw` would silently return a partial command list and
        # `simulate_vpp` would report a realized cost for part of a day --
        # which the baseline would present as a plan change, not a harness bug.
        raise ValueError(
            f"plan is inconsistent: {len(intents)} intents vs "
            f"{len(actions_kw)} actions"
        )

    if len(soe_trajectory) < len(actions_kw):
        raise ValueError(
            f"plan is inconsistent: {len(soe_trajectory)} SoE entries for "
            f"{len(actions_kw)} actions"
        )

    controller = _vpp_controller(intents, settings)
    return [
        _derive_vpp_command(
            controller,
            period,
            action_kw,
            at_reserve_floor=soe_trajectory[period] <= settings.min_soe_kwh,
        )
        for period, action_kw in enumerate(actions_kw)
    ]


def _vpp_controller(
    intents: list[str], settings: BatterySettings
) -> SolaxModbusGrowattController:
    """The production controller, configured for one plan's intents."""
    controller = SolaxModbusGrowattController(settings, control_mode="vpp")
    controller.strategic_intents = list(intents)
    return controller


def _derive_vpp_command(
    controller: SolaxModbusGrowattController,
    period: int,
    action_kw: float,
    at_reserve_floor: bool,
    tracking_budget_kwh: float | None = None,
) -> VppCommand:
    """One period's command, via the same two production calls
    `BatterySystemManager._apply_period_schedule` makes.

    `tracking_budget_kwh` is decided by the caller, not here: it comes from
    `vpp_load_tracking.budget_for_period`, which needs the gate decision and
    the plan -- neither of which `_intent_to_vpp` sees. Passing it in keeps
    the controller a stateless mapper, which is the same ownership split
    production uses (BSM drives, controller maps).
    """
    grid_charge, discharge_rate, block_passive_charging = (
        controller.compute_rates_for_period(period, action_kw)
    )
    power_pct, remote_control_enabled = controller._intent_to_vpp(
        grid_charge,
        discharge_rate,
        block_passive_charging,
        controller.strategic_intents[period],
        at_reserve_floor,
        load_tracking_active=tracking_budget_kwh is not None,
    )
    return VppCommand(
        power_pct=power_pct,
        remote_control_enabled=remote_control_enabled,
        tracking_budget_kwh=tracking_budget_kwh,
    )


def _tracking_budgets(
    intents: list[str],
    actions_kw: list[float],
    settings: BatterySettings,
    dt: float,
    intra_period_discharge_allowed: list[bool] | None,
) -> list[float | None]:
    """Per-period tracking budget, or None where the period is not tracked.

    Every period is None unless all four conditions hold: the user opted in,
    the intent is LOAD_SUPPORT, the gate is closed, and a gate decision was
    actually supplied. `simulate_vpp` is called both ways -- the corpus
    baseline and the #539/#540 pin pass no gate decisions, and for them the
    correct answer is the pre-#520 behaviour, not a guess -- so a missing
    `intra_period_discharge_allowed` is a real "do not track" signal here, not
    a defended-against error.
    """
    if not settings.vpp_load_tracking_enabled:
        return [None] * len(actions_kw)
    if intra_period_discharge_allowed is None:
        return [None] * len(actions_kw)
    if len(intra_period_discharge_allowed) != len(actions_kw):
        raise ValueError(
            f"plan is inconsistent: {len(intra_period_discharge_allowed)} gate "
            f"decisions for {len(actions_kw)} actions"
        )
    return [
        (
            budget_for_period(action_kw * dt, allowed)
            if intents[period] == "LOAD_SUPPORT"
            else None
        )
        for period, (action_kw, allowed) in enumerate(
            zip(actions_kw, intra_period_discharge_allowed, strict=True)
        )
    ]


def vpp_command_to_power(
    command: VppCommand,
    solar: float,
    home: float,
    soe: float,
    settings: BatterySettings,
    dt: float,
) -> float | None:
    """Battery power (kW; + charge, - discharge) the inverter applies under a
    VPP command. Returns None for "battery held exactly, solar bypasses to
    grid", matching `inverter_simulator.mode_to_power`'s convention.

    Firmware priority follows the sign rule documented in
    `INVERTER_PLATFORMS.md` (Growatt VPP protocol V2.01 §3.5): with remote
    control enabled, `power > 0` selects battery-first and `power <= 0`
    selects grid-first. With remote control disabled the inverter reverts to
    its own load_first self-use (#413), which is also what the 20-minute VPP
    timeout falls back to (#404).

    **Modelling assumption, stated because the sources conflict.** #355
    describes `power=0, enabled` (grid_first) as holding the battery, while
    #466 records that grid_first still draws self-consumption from the
    battery and only battery_first releases the house to grid/solar (#118).
    This models the #118/#466 reading -- grid_first holds the battery against
    *charging* but still lets it serve load -- because that is the one backed
    by a real-hardware report. If that is wrong, the baseline and the
    comparison inherit the error equally, so regression detection is
    unaffected; only an absolute cost reading would be.
    """
    ac_cap_kwh = _effective_ac_cap_kwh(settings, dt)
    ac_headroom_kwh = (
        float("inf")
        if ac_cap_kwh is None
        else max(0.0, ac_cap_kwh - min(solar, ac_cap_kwh))
    )
    available = max(0.0, soe - settings.min_soe_kwh)
    deficit = max(0.0, home - solar)

    if command.tracking_budget_kwh is not None:
        # Load tracking (#520): the battery follows the *measured* deficit,
        # stopping once the period's planned energy is spent.
        #
        # In production this is a 10 s loop rewriting `vpp_power` against live
        # sensors; here the period's load and solar are single figures, so the
        # deficit is constant across it and the loop's whole 15 minutes
        # collapse to one `min`. That is not a simplification of the control
        # law -- it is the same law evaluated on constant inputs.
        #
        # The budget sits alongside the physical bounds rather than replacing
        # them: a reservation cannot license a discharge the inverter, the SoE
        # floor or the AC stage would not deliver anyway.
        delivered = min(
            deficit,
            command.tracking_budget_kwh,
            settings.max_discharge_power_kw * dt,
            available * settings.efficiency_discharge,
            ac_headroom_kwh,
        )
        # Budget exhausted, no deficit, or nothing deliverable -- all three are
        # the hold, and the hold must return None rather than -0.0 for the same
        # reason the other branches do: `_state_transition` reads a
        # not-quite-negative power as IDLE and absorbs solar surplus into the
        # battery. Here that would be a *charge* under a command whose entire
        # purpose is to stop spending, and the hold's own solar absorption is
        # applied by that IDLE branch anyway (see VPP_HOLD_POWER_PCT).
        if delivered <= 0:
            return None
        return -delivered / dt

    if not command.remote_control_enabled:
        # load_first self-use: the inverter covers the home deficit itself,
        # unconstrained by any *planned* rate. It is still bounded by the
        # inverter's physical discharge rating -- dropping the plan's ceiling
        # does not let a 6 kW inverter deliver a 20 kW deficit.
        if deficit <= 0:
            return 0.0  # passive solar charging via _state_transition's IDLE
        delivered = min(
            deficit,
            settings.max_discharge_power_kw * dt,
            available * settings.efficiency_discharge,
            ac_headroom_kwh,
        )
        # Same zero-delivery trap as the two enabled-remote branches below: at
        # the SoE floor `delivered` is 0 and `-0.0` reads as "not a discharge"
        # to `_state_transition`, dropping into its IDLE branch. Today that is
        # harmless here -- this line is only reached with `deficit > 0`, i.e.
        # `home > solar`, so there is no surplus for IDLE to absorb -- but the
        # invariant is incidental, not designed, and #537 wiring a planned rate
        # into this branch would make it reachable with a surplus. Handled the
        # same way in all three branches so it cannot come back in whichever
        # one was left inconsistent.
        if delivered <= 0:
            return None
        return -delivered / dt

    if command.power_pct >= 100:
        # battery_first at full rate: deliberate grid charging. Returning any
        # power above POWER_TOLERANCE_KW is enough -- see the note below.
        return settings.max_charge_power_kw

    if command.power_pct > 0:
        # battery_first at a *trickle* rate: the hold used by IDLE (#466), and
        # by #520's closed gate once that lands. The point is that
        # self-consumption comes from grid/solar rather than the battery.
        #
        # Returning 0.0 (not the commanded rate) is deliberate and load
        # bearing. STORE physics in `_state_transition` / `_period_flows` are
        # **binary**: any power above `POWER_TOLERANCE_KW` (0.001) charges at
        # the full `max_charge_power_kw * dt`, and the commanded magnitude is
        # never read -- see `_charge_candidate`'s "binary store physics" note.
        # So returning the honest 1% rate (e.g. 0.06 kW) would simulate a
        # full-rate grid charge: measured, `_state_transition(soe=3.0,
        # power=0.06)` and `power=6.0` both return 9.0. An earlier revision of
        # this file did exactly that, and every IDLE period in the baseline
        # encoded ~6 kWh of fictional grid import on a no-solar fixture.
        #
        # 0.0 routes to `_state_transition`'s IDLE branch: passive solar
        # absorption only, never a grid draw -- which is what a hold is, and
        # what `inverter_simulator.mode_to_power` already does for IDLE.
        #
        # The intermediate rates this cannot express are not reachable:
        # `_intent_to_vpp` only ever writes +1 (hold) or +100 (charge) on the
        # positive side. The raise below keeps that an enforced property.
        if command.power_pct != 1:
            raise ValueError(
                f"unmodellable VPP charge rate {command.power_pct}%: the "
                "physics core's STORE branch is binary, so only a full-rate "
                "charge (>=100) or a hold (1) can be simulated faithfully"
            )
        return 0.0

    if command.power_pct < 0:
        # Forced discharge/export at the commanded rate, regardless of load
        # (#324) -- this is the behaviour that makes the gate's TOU ceiling
        # semantics wrong here.
        rate_kw = settings.max_discharge_power_kw * abs(command.power_pct) / 100.0
        delivered = min(
            rate_kw * dt, available * settings.efficiency_discharge, ac_headroom_kwh
        )
        if delivered <= 0:
            # Nothing to export -- at the SoE floor, or the AC stage is full
            # of PV. Returning -0.0 here would be read as "not a discharge" by
            # `_state_transition` (`power < -POWER_TOLERANCE_KW` is False) and
            # fall into its IDLE branch, which absorbs solar surplus into the
            # battery -- a *charge* under a forced-export command, and a direct
            # contradiction of BATTERY_EXPORT's `charge_rate = 0` and of the
            # grid_first hold below.
            #
            # Reachable and previously baked into the baseline:
            # `realworld_2026_04_29_220919` period 37 commands (-1, True) at
            # SoE 2.5 (== min) with 1.1 kWh of surplus, and the battery charged
            # to 3.567 kWh. Same defect class as the +1%-hold bug.
            return None
        return -delivered / dt

    # power == 0, remote control enabled: grid_first. Battery is held against
    # charging from solar surplus (#355), but still serves load (#118).
    #
    # **This load-serving branch is not exercised by the fixture corpus** --
    # no SOLAR_EXPORT period in any of the 36 fixtures has `home > solar`, so
    # replacing the condition with `if False` leaves the whole baseline green.
    # The #118/#466-vs-#355 modelling choice therefore has no corpus signal
    # behind it and is pinned only by
    # `test_vpp_simulator_branches::test_grid_first_serves_load_from_battery`.
    # Anything revisiting grid_first (#537, or a hardware confirmation) must
    # change that test deliberately rather than discovering it silently.
    if deficit > 0:
        delivered = min(
            deficit,
            settings.max_discharge_power_kw * dt,
            available * settings.efficiency_discharge,
            ac_headroom_kwh,
        )
        # Same zero-delivery trap as the forced-discharge branch above: a hold
        # must stay a hold, never fall through to IDLE's solar absorption.
        if delivered > 0:
            return -delivered / dt
    return None


@dataclass
class VppSimulationResult:
    period_data: list = field(default_factory=list)
    realized_cost: float = 0.0
    # The commands actually issued, derived per period as the run reached it.
    # Returned rather than taken as input because #592 made the command a
    # function of the SoE the simulation itself produces.
    commands: list = field(default_factory=list)


def simulate_vpp(
    intents: list[str],
    actions_kw: list[float],
    solar_production: list[float],
    home_consumption: list[float],
    buy_price: list[float],
    sell_price: list[float],
    initial_soe: float,
    settings: BatterySettings,
    dt: float,
    currency: str = "SEK",
    intra_period_discharge_allowed: list[bool] | None = None,
) -> VppSimulationResult:
    """Execute a VPP command sequence, carrying SoE forward, using the
    optimizer's own flow and accounting primitives -- same arrangement as
    `inverter_simulator.simulate`, so realized cost is comparable between the
    two platforms.

    Takes the *plan* rather than a prebuilt command list: since #592 a
    command depends on whether the battery is at its reserve floor, which is
    only known once the run has carried SoE forward to that period. Deriving
    the list up front is what made the release branch unreachable here, and
    with it the whole corpus's claim to cover it.

    To execute a command list that no plan would produce -- a hypothetical, to
    contrast against what production actually writes -- use
    `simulate_vpp_commands` instead."""
    if len(intents) != len(actions_kw):
        raise ValueError(
            f"plan is inconsistent: {len(intents)} intents vs "
            f"{len(actions_kw)} actions"
        )

    controller = _vpp_controller(intents, settings)
    budgets = _tracking_budgets(
        intents, actions_kw, settings, dt, intra_period_discharge_allowed
    )
    return _simulate(
        lambda t, soe: _derive_vpp_command(
            controller,
            t,
            actions_kw[t],
            at_reserve_floor=soe <= settings.min_soe_kwh,
            tracking_budget_kwh=budgets[t],
        ),
        len(actions_kw),
        solar_production,
        home_consumption,
        buy_price,
        sell_price,
        initial_soe,
        settings,
        dt,
        currency,
    )


def simulate_vpp_commands(
    commands: list[VppCommand],
    solar_production: list[float],
    home_consumption: list[float],
    buy_price: list[float],
    sell_price: list[float],
    initial_soe: float,
    settings: BatterySettings,
    dt: float,
    currency: str = "SEK",
) -> VppSimulationResult:
    """Execute an explicit command sequence, bypassing derivation.

    For hypotheticals only -- "what would the battery have done had it been
    commanded this instead". Anything asserting what production *does* must go
    through `simulate_vpp`, which derives the commands the way production
    does.
    """
    return _simulate(
        lambda t, _soe: commands[t],
        len(commands),
        solar_production,
        home_consumption,
        buy_price,
        sell_price,
        initial_soe,
        settings,
        dt,
        currency,
    )


def _simulate(
    command_at: Callable[[int, float], VppCommand],
    n_periods: int,
    solar_production: list[float],
    home_consumption: list[float],
    buy_price: list[float],
    sell_price: list[float],
    initial_soe: float,
    settings: BatterySettings,
    dt: float,
    currency: str,
) -> VppSimulationResult:
    """The one execution loop. `command_at(period, soe)` supplies each
    period's command against the SoE the run has reached, which is what lets
    a derived command depend on the reserve floor (#592)."""
    soe = initial_soe
    period_data = []
    commands = []
    for t in range(n_periods):
        cmd = command_at(t, soe)
        commands.append(cmd)
        power = vpp_command_to_power(
            cmd, solar_production[t], home_consumption[t], soe, settings, dt
        )
        if power is None:
            next_soe = soe
            power = 0.0
        else:
            next_soe = _state_transition(
                soe,
                power,
                settings,
                dt,
                solar_production=solar_production[t],
                home_consumption=home_consumption[t],
            )
        flows = _period_flows(
            power=power,
            soe=soe,
            next_soe=next_soe,
            home_consumption=home_consumption[t],
            solar_production=solar_production[t],
            battery_settings=settings,
            dt=dt,
        )
        period_data.append(
            _build_period_data(
                flows=flows,
                power=power,
                soe=soe,
                next_soe=next_soe,
                period=t,
                home_consumption=home_consumption[t],
                battery_settings=settings,
                dt=dt,
                buy_price=buy_price,
                sell_price=sell_price,
                solar_production=solar_production[t],
                new_cost_basis=settings.cycle_cost_per_kwh,
                currency=currency,
            )
        )
        soe = next_soe

    return VppSimulationResult(
        period_data=period_data,
        realized_cost=sum(pd.economic.hourly_cost for pd in period_data),
        commands=commands,
    )
