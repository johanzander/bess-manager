"""Pure scenario simulator: execute control commands derived from a plan and
compute realized flows/savings. Growatt MIN / cloud, execution-only.

Reuses the optimizer's own primitives (_state_transition, _build_period_data)
so that faithful control yields cent-exact equality with the plan.
"""

from dataclasses import dataclass, field

from core.bess.dp_battery_algorithm import _build_period_data, _state_transition
from core.bess.inverter_controller import InverterController
from core.bess.models import PeriodData  # noqa: F401  (type clarity)
from core.bess.settings import BatterySettings


@dataclass(frozen=True)
class ControlCommand:
    """The hardware control state applied for one period (Growatt MIN)."""

    battery_mode: str  # "load_first" | "grid_first" | "battery_first"
    discharge_rate_pct: int  # 0..100
    grid_charge: bool


def derive_control_command(
    strategic_intent: str, battery_action_kw: float, settings: BatterySettings
) -> ControlCommand:
    """Map a plan period (intent + planned battery power) to the applied command,
    reusing the production controller mappings so the simulator executes exactly
    what the real controller would write."""
    battery_mode = InverterController.INTENT_TO_MODE.get(strategic_intent, "load_first")
    # Reuse the production intent->rates mapping (grid_charge, discharge_rate_pct).
    grid_charge, discharge_rate_pct = _map_rates(
        strategic_intent, battery_action_kw, settings
    )
    return ControlCommand(
        battery_mode=battery_mode,
        discharge_rate_pct=discharge_rate_pct,
        grid_charge=grid_charge,
    )


def _map_rates(
    intent: str, action_kw: float, settings: BatterySettings
) -> tuple[bool, int]:
    """Mirror of InverterController._map_intent_to_rates without needing a live
    controller instance (that method is an instance method bound to hardware)."""
    if intent == "GRID_CHARGING":
        return True, 0
    if intent in ("SOLAR_STORAGE", "IDLE"):
        return False, 0
    if intent == "LOAD_SUPPORT":
        if action_kw < -0.01:
            rate = min(
                100,
                max(0, round(abs(action_kw) / settings.max_discharge_power_kw * 100)),
            )
        else:
            rate = 0
        return False, rate
    if intent == "BATTERY_EXPORT":
        if action_kw < -0.01:
            rate = min(
                100,
                max(0, round(abs(action_kw) / settings.max_discharge_power_kw * 100)),
            )
        else:
            rate = 0
        return False, rate
    raise ValueError(f"Unknown strategic intent: {intent}")


def mode_to_power(
    command: ControlCommand,
    solar: float,
    home: float,
    soe: float,
    settings: BatterySettings,
    dt: float,
) -> float:
    """Battery power (kW; + charge, - discharge) the Growatt MIN inverter applies
    for one period under the given command and conditions. This is the v1 mode
    policy; check 1 (plan-faithfulness) validates/refines it."""
    if command.battery_mode == "battery_first":  # grid charging
        room = settings.max_soe_kwh - soe
        max_charge_kwh = min(
            settings.max_charge_power_kw * dt, room / settings.efficiency_charge
        )
        return max(0.0, max_charge_kwh) / dt

    if (
        command.battery_mode == "grid_first"
    ):  # export arbitrage: discharge to grid at rate
        available = max(0.0, soe - settings.min_soe_kwh)
        rate_kw = settings.max_discharge_power_kw * command.discharge_rate_pct / 100.0
        delivered_kwh = min(rate_kw * dt, available * settings.efficiency_discharge)
        return -delivered_kwh / dt

    # load_first
    if command.discharge_rate_pct > 0:  # LOAD_SUPPORT: cover home deficit
        deficit = max(0.0, home - solar)
        available = max(0.0, soe - settings.min_soe_kwh)
        rate_kw = settings.max_discharge_power_kw * command.discharge_rate_pct / 100.0
        delivered_kwh = min(
            deficit, rate_kw * dt, available * settings.efficiency_discharge
        )
        return -delivered_kwh / dt

    # SOLAR_STORAGE (load_first + no discharge): STORE disposition — charge all surplus.
    # _state_transition's STORE branch caps at rate/room; no grid top-up since power*dt==surplus.
    surplus = max(0.0, solar - home)
    return surplus / dt


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
