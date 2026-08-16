"""Pure scenario simulator: execute control commands derived from a plan and
compute realized flows/savings. Growatt MIN / cloud, execution-only.

Reuses the optimizer's own primitives (_state_transition, _build_period_data)
so that faithful control yields cent-exact equality with the plan.
"""

from dataclasses import dataclass, field

from core.bess.dp_battery_algorithm import (
    _build_period_data,
    _effective_ac_cap_kwh,
    _period_flows,
    _state_transition,
)
from core.bess.execution_model import (
    command_index,
    intra_period_discharge_gate,
)
from core.bess.inverter_controller import InverterController
from core.bess.models import PeriodData  # noqa: F401  (type clarity)
from core.bess.settings import BatterySettings


@dataclass(frozen=True)
class ControlCommand:
    """The hardware control state applied for one period (Growatt MIN)."""

    battery_mode: str  # "load_first" | "grid_first" | "battery_first"
    discharge_rate_pct: int  # 0..100
    grid_charge: bool
    charge_rate_pct: int = 100  # 0..100; action-derived for GRID_CHARGING


def derive_control_command(
    strategic_intent: str,
    battery_action_kw: float,
    settings: BatterySettings,
    intra_period_discharge_allowed: bool | None = None,
) -> ControlCommand:
    """Map a plan period (intent + planned battery power) to the applied command,
    reusing the production controller mappings so the simulator executes exactly
    what the real controller would write.

    ``intra_period_discharge_allowed`` is the DP's decision for this period
    (``DecisionData.intra_period_discharge_allowed``) and feeds the
    SOLAR_EXPORT/SOLAR_STORAGE intra-period discharge gate. Production also
    gates LOAD_SUPPORT since #520; that is deliberately not reproduced here --
    see ``_map_rates`` -- so this is a mirror of
    ``BatterySystemManager._apply_period_schedule`` for the two solar intents,
    not for all three.

    ``None`` means "this caller is not exercising the gate" and leaves it
    closed -- distinct from ``False``, which is the DP deciding against opening
    it. Keeping the opt-out its own value is what stops the parameter from
    re-acquiring the two-meanings-one-value defect that #526 removed from
    ``shadow_price``."""
    battery_mode = InverterController.INTENT_TO_MODE.get(strategic_intent, "load_first")
    grid_charge, discharge_rate_pct, charge_rate_pct = _map_rates(
        strategic_intent, battery_action_kw, settings, intra_period_discharge_allowed
    )
    return ControlCommand(
        battery_mode=battery_mode,
        discharge_rate_pct=discharge_rate_pct,
        grid_charge=grid_charge,
        charge_rate_pct=charge_rate_pct,
    )


def _gated_discharge_rate(
    baseline: int,
    intra_period_discharge_allowed: bool | None,
) -> int:
    """Apply the DP's intra-period discharge decision on top of a planned
    baseline rate, mirroring `BatterySystemManager._apply_period_schedule`'s
    `max(baseline, gate)` -- the gate may only raise the ceiling, never lower
    an already-committed plan. No-op (returns baseline) when the caller opted
    out by passing None.

    Omits production's `discharge_rate_is_load_following` platform guard --
    this simulator is Growatt MIN/cloud only (see module docstring), which is
    always load-following, so the guard would always be true here."""
    if intra_period_discharge_allowed is None:
        return baseline
    return max(baseline, intra_period_discharge_gate(intra_period_discharge_allowed))


def _map_rates(
    intent: str,
    action_kw: float,
    settings: BatterySettings,
    intra_period_discharge_allowed: bool | None = None,
) -> tuple[bool, int, int]:
    """Mirror of InverterController._map_intent_to_rates without needing a live
    controller instance. Returns (grid_charge, discharge_rate_pct, charge_rate_pct)."""
    if intent == "GRID_CHARGING":
        if action_kw > 0.01:
            # Rounded up, mirroring `_compute_charge_rate` (Phase 4c): the
            # battery's remaining room binds above the command, so a rate
            # above the plan still delivers exactly the plan, while nearest
            # lands below it and charges less.
            charge_rate_pct = command_index(
                action_kw,
                settings.max_charge_power_kw / 100,
                rate_is_ceiling=True,
            )
        else:
            charge_rate_pct = 100
        return True, 0, charge_rate_pct
    if intent == "IDLE":
        return False, 0, 100
    if intent == "SOLAR_STORAGE":
        rate = _gated_discharge_rate(0, intra_period_discharge_allowed)
        return False, rate, 100
    if intent == "SOLAR_EXPORT":
        # #313: charge_rate=0 blocks passive solar->battery charging so solar
        # bypasses to grid even below max SOE -- unlike IDLE/SOLAR_STORAGE.
        rate = _gated_discharge_rate(0, intra_period_discharge_allowed)
        return False, rate, 0
    if intent == "LOAD_SUPPORT":
        # Production gates LOAD_SUPPORT since #520; this simulator deliberately
        # does not, and that is not an oversight to "fix" by mirroring it.
        #
        # The gate is a sub-period ceiling: it lets the battery cover load that
        # exceeds the period's forecast average. This simulator runs point
        # forecasts at 15-min resolution, where no such excess exists by
        # construction -- so it can only ever model the gate's cost (covering
        # more of a *planned* partial cover from battery than the DP chose),
        # never its benefit. For SOLAR_EXPORT/SOLAR_STORAGE that cost is zero
        # (planned deficit is zero, so an open gate is a no-op here), which is
        # why mirroring them is safe. For LOAD_SUPPORT it is not: mirroring the
        # gate moves 27 of 36 corpus fixtures, +25.67 SEK of realized cost in
        # total, purely from the unmodellable half of the trade-off. Modelling
        # it would pin a number the simulator cannot interpret.
        #
        # Plan-scaled cap only, same as BATTERY_EXPORT -- but rounded UP, not
        # to nearest: this simulator models the Growatt MIN, where load_first
        # is a ceiling, and a ceiling below the plan under-delivers it (Phase
        # 4b, `execution_model.command_index`). Same call the
        # controller makes, so plan and execution cannot round apart.
        if action_kw < -0.01:
            rate = command_index(
                abs(action_kw),
                settings.max_discharge_power_kw / 100,
                rate_is_ceiling=True,
            )
        else:
            rate = 0
        return False, rate, 100
    if intent == "BATTERY_EXPORT":
        # No shadow-price gate: grid_first has no physical deficit backstop,
        # so an open ceiling would oversell beyond the arbitrage plan.
        #
        # Nearest, not up: under grid_first the number is the delivered
        # power, so the plan is what to hit, not what to stay above. Same
        # shared conversion as LOAD_SUPPORT above, opposite direction --
        # which is the distinction 4b exists to make explicit.
        if action_kw < -0.01:
            rate = command_index(
                abs(action_kw),
                settings.max_discharge_power_kw / 100,
                rate_is_ceiling=False,
            )
        else:
            rate = 0
        return False, rate, 0
    raise ValueError(f"Unknown strategic intent: {intent}")


def mode_to_power(
    command: ControlCommand,
    solar: float,
    home: float,
    soe: float,
    settings: BatterySettings,
    dt: float,
) -> float | None:
    """Battery power (kW; + charge, - discharge) the Growatt MIN inverter applies
    for one period under the given command and conditions. This is the v1 mode
    policy; check 1 (plan-faithfulness) validates/refines it.

    Returns `None` for SOLAR_EXPORT-below-max (#313): charge_rate=0 blocks
    passive solar->battery charging entirely (battery untouched, solar
    bypasses to grid), a genuinely different outcome from IDLE/SOLAR_STORAGE's
    `power=0.0` (which still passively charges via `_state_transition`'s IDLE
    branch) -- the same distinction the DP's own reward function makes
    between its IDLE and SOLAR_EXPORT-below-max candidates.
    """
    if command.battery_mode == "battery_first":  # grid charging
        room = settings.max_soe_kwh - soe
        rate_kw = settings.max_charge_power_kw * command.charge_rate_pct / 100
        max_charge_kwh = min(rate_kw * dt, room / settings.efficiency_charge)
        return max(0.0, max_charge_kwh) / dt

    # Battery discharge shares the inverter's AC stage with PV conversion —
    # mirrors the discharge feasibility filter in the DP.
    ac_cap_kwh = _effective_ac_cap_kwh(settings, dt)
    if ac_cap_kwh is None:
        ac_headroom_kwh = float("inf")
    else:
        ac_headroom_kwh = max(0.0, ac_cap_kwh - min(solar, ac_cap_kwh))

    if (
        command.battery_mode == "grid_first"
    ):  # export arbitrage: discharge to grid at rate
        available = max(0.0, soe - settings.min_soe_kwh)
        rate_kw = settings.max_discharge_power_kw * command.discharge_rate_pct / 100.0
        delivered_kwh = min(
            rate_kw * dt, available * settings.efficiency_discharge, ac_headroom_kwh
        )
        return -delivered_kwh / dt

    # load_first
    deficit = max(0.0, home - solar)
    if command.discharge_rate_pct > 0 and deficit > 0:  # cover a real home deficit
        available = max(0.0, soe - settings.min_soe_kwh)
        rate_kw = settings.max_discharge_power_kw * command.discharge_rate_pct / 100.0
        delivered_kwh = min(
            deficit,
            rate_kw * dt,
            available * settings.efficiency_discharge,
            ac_headroom_kwh,
        )
        return -delivered_kwh / dt

    if command.charge_rate_pct == 0:
        # SOLAR_EXPORT-below-max (#313): charge blocked, no discharge --
        # battery held exactly unchanged, solar bypasses to grid.
        return None

    # IDLE/SOLAR_STORAGE (load_first + no discharge): passive solar charging.
    # Return 0.0 so _state_transition uses its IDLE branch (power=0), which charges
    # from solar surplus passively — never drawing from grid (load_first hardware).
    return 0.0


@dataclass
class SimulationResult:
    period_data: list = field(default_factory=list)  # list[PeriodData]
    realized_cost: float = 0.0  # sum of economic.hourly_cost


def simulate(
    commands: list[ControlCommand],
    solar_production: list[float],
    home_consumption: list[float],
    buy_price: list[float],
    sell_price: list[float],
    initial_soe: float,
    settings: BatterySettings,
    dt: float,
    currency: str = "SEK",
) -> SimulationResult:
    """Execute the command sequence period-by-period, carrying SoC forward, using
    the optimizer's own _state_transition + _build_period_data for accounting
    parity. Returns realized PeriodData and total realized cost."""
    soe = initial_soe
    period_data = []
    for t, cmd in enumerate(commands):
        power = mode_to_power(
            cmd, solar_production[t], home_consumption[t], soe, settings, dt
        )
        if power is None:
            # SOLAR_EXPORT-below-max (#313): battery held exactly unchanged,
            # bypassing _state_transition's IDLE branch (which would
            # passively charge from solar instead).
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
        pd = _build_period_data(
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
        period_data.append(pd)
        soe = next_soe
    realized_cost = sum(pd.economic.hourly_cost for pd in period_data)
    return SimulationResult(period_data=period_data, realized_cost=realized_cost)
