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

from dataclasses import dataclass, field

from core.bess.dp_battery_algorithm import (
    _build_period_data,
    _effective_ac_cap_kwh,
    _period_flows,
    _state_transition,
)
from core.bess.settings import BatterySettings
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController


@dataclass(frozen=True)
class VppCommand:
    """One period's Growatt VPP command, as written to hardware."""

    power_pct: int  # -100..100; negative discharge/export, positive charge
    remote_control_enabled: bool


def derive_vpp_command(
    strategic_intent: str,
    battery_action_kw: float,
    settings: BatterySettings,
) -> VppCommand:
    """The VPP command production would write for this planned period.

    Routes through the real controller's `_intent_to_vpp` rather than
    restating the mapping, so this cannot describe a command the hardware
    path would not actually send.

    Deliberately does not pass the intra-period discharge decision: that
    parameter does not exist on `_intent_to_vpp` yet -- it arrives with #537,
    which is blocked on this harness. That ordering is the point. This
    baseline captures behaviour *without* the gate, so when #537 rebases onto
    it and wires the argument through here, the pinned deltas show exactly
    what the gate changes.
    """
    controller = SolaxModbusGrowattController(settings, control_mode="vpp")
    intent_control = controller.INTENT_TO_CONTROL.get(
        strategic_intent, controller.INTENT_TO_CONTROL["IDLE"]
    )
    grid_charge = bool(intent_control["grid_charge"])
    discharge_rate = int(intent_control["discharge_rate"])
    if strategic_intent in ("LOAD_SUPPORT", "BATTERY_EXPORT"):
        # Action-derived rate, matching InverterController's own mapping.
        discharge_rate = (
            min(
                100,
                max(
                    0,
                    round(
                        abs(battery_action_kw) / settings.max_discharge_power_kw * 100
                    ),
                ),
            )
            if battery_action_kw < -0.01
            else 0
        )
    block_passive_charging = int(intent_control["charge_rate"]) == 0

    power_pct, remote_control_enabled = controller._intent_to_vpp(
        grid_charge,
        discharge_rate,
        block_passive_charging,
        strategic_intent,
    )
    return VppCommand(
        power_pct=power_pct, remote_control_enabled=remote_control_enabled
    )


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

    if not command.remote_control_enabled:
        # load_first self-use: the inverter covers the home deficit itself,
        # unconstrained by any planned rate.
        if deficit <= 0:
            return 0.0  # passive solar charging via _state_transition's IDLE
        delivered = min(
            deficit, available * settings.efficiency_discharge, ac_headroom_kwh
        )
        return -delivered / dt

    if command.power_pct > 0:
        # battery_first. At +100 this is deliberate grid charging; at +1 it
        # is the hold used by IDLE (#466) and by #520's closed gate, where
        # the point is that self-consumption comes from grid/solar rather
        # than the battery -- so no discharge, and only the rate-limited
        # charge the command asks for.
        room = settings.max_soe_kwh - soe
        rate_kw = settings.max_charge_power_kw * command.power_pct / 100.0
        max_charge_kwh = min(rate_kw * dt, room / settings.efficiency_charge)
        return max(0.0, max_charge_kwh) / dt

    if command.power_pct < 0:
        # Forced discharge/export at the commanded rate, regardless of load
        # (#324) -- this is the behaviour that makes the gate's TOU ceiling
        # semantics wrong here.
        rate_kw = settings.max_discharge_power_kw * abs(command.power_pct) / 100.0
        delivered = min(
            rate_kw * dt, available * settings.efficiency_discharge, ac_headroom_kwh
        )
        return -delivered / dt

    # power == 0, remote control enabled: grid_first. Battery is held against
    # charging from solar surplus (#355), but still serves load (#118).
    if deficit > 0:
        delivered = min(
            deficit, available * settings.efficiency_discharge, ac_headroom_kwh
        )
        return -delivered / dt
    return None


@dataclass
class VppSimulationResult:
    period_data: list = field(default_factory=list)
    realized_cost: float = 0.0


def simulate_vpp(
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
    """Execute a VPP command sequence, carrying SoE forward, using the
    optimizer's own flow and accounting primitives -- same arrangement as
    `inverter_simulator.simulate`, so realized cost is comparable between the
    two platforms."""
    soe = initial_soe
    period_data = []
    for t, cmd in enumerate(commands):
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
    )
