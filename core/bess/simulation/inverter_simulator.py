"""Pure scenario simulator: execute control commands derived from a plan and
compute realized flows/savings. Growatt MIN / cloud, execution-only.

Reuses the optimizer's own primitives (_state_transition, _build_period_data)
so that faithful control yields cent-exact equality with the plan.
"""

from dataclasses import dataclass, field

from core.bess.dp_battery_algorithm import (
    _build_period_data,
    _effective_ac_cap_kwh,
    _state_transition,
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
    strategic_intent: str, battery_action_kw: float, settings: BatterySettings
) -> ControlCommand:
    """Map a plan period (intent + planned battery power) to the applied command,
    reusing the production controller mappings so the simulator executes exactly
    what the real controller would write."""
    battery_mode = InverterController.INTENT_TO_MODE.get(strategic_intent, "load_first")
    grid_charge, discharge_rate_pct, charge_rate_pct = _map_rates(
        strategic_intent, battery_action_kw, settings
    )
    return ControlCommand(
        battery_mode=battery_mode,
        discharge_rate_pct=discharge_rate_pct,
        grid_charge=grid_charge,
        charge_rate_pct=charge_rate_pct,
    )


def _map_rates(
    intent: str, action_kw: float, settings: BatterySettings
) -> tuple[bool, int, int]:
    """Mirror of InverterController._map_intent_to_rates without needing a live
    controller instance. Returns (grid_charge, discharge_rate_pct, charge_rate_pct)."""
    if intent == "GRID_CHARGING":
        if action_kw > 0.01:
            charge_rate_pct = min(
                100,
                max(0, round(action_kw / settings.max_charge_power_kw * 100)),
            )
        else:
            charge_rate_pct = 100
        return True, 0, charge_rate_pct
    if intent in ("SOLAR_STORAGE", "IDLE"):
        return False, 0, 100
    if intent == "SOLAR_EXPORT":
        # #313: charge_rate=0 blocks passive solar->battery charging so solar
        # bypasses to grid even below max SOE -- unlike IDLE/SOLAR_STORAGE.
        return False, 0, 0
    if intent == "LOAD_SUPPORT":
        if action_kw < -0.01:
            rate = min(
                100,
                max(0, round(abs(action_kw) / settings.max_discharge_power_kw * 100)),
            )
        else:
            rate = 0
        return False, rate, 100
    if intent == "BATTERY_EXPORT":
        if action_kw < -0.01:
            rate = min(
                100,
                max(0, round(abs(action_kw) / settings.max_discharge_power_kw * 100)),
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
    if command.discharge_rate_pct > 0:  # LOAD_SUPPORT: cover home deficit
        deficit = max(0.0, home - solar)
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
        pd = _build_period_data(
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
