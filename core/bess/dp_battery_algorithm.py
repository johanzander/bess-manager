"""
Dynamic Programming Algorithm for Battery Energy Storage System (BESS) Optimization.

This module implements a sophisticated dynamic programming approach to optimize battery
dispatch decisions over a 24-hour horizon, considering time-varying electricity prices,
solar production forecasts, and home consumption patterns.

UPDATED: Now captures strategic intent at decision time rather than analyzing flows afterward.

ALGORITHM OVERVIEW:
The optimization uses backward induction dynamic programming to find the globally optimal
battery charging and discharging schedule. At each hour, the algorithm evaluates all
possible battery actions (charge/discharge/hold) and selects the one that minimizes
total cost over the remaining time horizon.

KEY FEATURES:
- 24-hour optimization horizon with perfect foresight
- Cost basis tracking for stored energy (FIFO accounting)
- Multi-objective optimization: cost minimization + battery longevity
- Simultaneous energy flow optimization across multiple sources/destinations
- Strategic intent capture at decision time for transparency and hardware control

STRATEGIC INTENT CAPTURE:
The algorithm now captures the strategic reasoning behind each decision:
- GRID_CHARGING: Storing cheap grid energy for arbitrage
- SOLAR_STORAGE: Storing excess solar for later use
- LOAD_SUPPORT: Discharging to meet home load
- BATTERY_EXPORT: Discharging to grid for profit
- IDLE: No significant activity

ENERGY FLOW MODELING:
The algorithm models complex energy flows where multiple sources can serve multiple
destinations simultaneously:
- Solar → {Home, Battery, Grid Export}
- Battery → {Home, Grid Export}
- Grid → {Home, Battery Charging}

OPTIMIZATION OBJECTIVES:
1. Primary: Minimize total electricity costs over 24-hour period
2. Secondary: Minimize battery degradation through cycle cost modeling
3. Constraints: Physical battery limits, efficiency losses, minimum SOC

RETURN STRUCTURE:
The algorithm returns comprehensive results including:
- Optimal battery actions for each hour
- Strategic intent for each decision
- Detailed energy flow breakdowns showing where each kWh flows
- Economic analysis comparing different scenarios
- All data needed for hardware implementation and performance analysis
"""

__all__ = [
    "optimize_battery_schedule",
    "print_optimization_results",
]


import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np

from core.bess.dp_constants import (
    POWER_STEP_KW,
    SHADOW_PRICE_NOISE_REL,
    SOE_STEP_KWH,
)
from core.bess.execution_model import (
    DEFAULT_CAPABILITIES,
    PlatformCapabilities,
    lattice_grid_charge,
)
from core.bess.models import (
    EconomicData,
    EconomicSummary,
    EnergyData,
    OptimizationResult,
    PeriodData,
    apply_export_curtailment_to_period_data,
)
from core.bess.settings import BatterySettings, HomeSettings
from core.bess.strategic_intent import (
    create_decision_data,
)
from core.bess.terminal_value import TerminalValueCurve

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Algorithm parameters. SOE_STEP_KWH/POWER_STEP_KW live in dp_constants.py
# (shared with strategic_intent.py -- see that module's docstring for why).
POWER_TOLERANCE_KW = 0.001  # Threshold to distinguish IDLE from charge/discharge


class StrategicIntent(Enum):
    """Strategic intents for battery actions, determined at decision time."""

    # Primary intents (mutually exclusive)
    GRID_CHARGING = "GRID_CHARGING"  # Storing cheap grid energy for arbitrage
    SOLAR_STORAGE = "SOLAR_STORAGE"  # Storing excess solar for later use
    LOAD_SUPPORT = "LOAD_SUPPORT"  # Discharging to meet home load
    BATTERY_EXPORT = "BATTERY_EXPORT"  # Discharging battery to grid for profit
    SOLAR_EXPORT = "SOLAR_EXPORT"  # Solar surplus exporting to grid, battery idle
    IDLE = "IDLE"  # No significant action


def _discretize_state_action_space(
    battery_settings: BatterySettings,
) -> tuple[np.ndarray, np.ndarray]:
    """Discretize state and action spaces - FIXED to return SOE levels."""
    # State space: State of Energy (kWh)
    soe_levels = np.arange(
        battery_settings.min_soe_kwh,
        battery_settings.max_soe_kwh + SOE_STEP_KWH,
        SOE_STEP_KWH,
    )

    # Action space: power levels (kW)
    max_power = max(
        battery_settings.max_charge_power_kw, battery_settings.max_discharge_power_kw
    )
    power_levels = np.arange(
        -max_power,
        max_power + POWER_STEP_KW,
        POWER_STEP_KW,
    )

    # Guarantee IDLE (power=0) is an available action. The arange above is
    # offset so it never lands exactly on zero, and under the #146 binary-store
    # semantics ("any positive power charges at max rate") the smallest positive
    # grid power is a full-rate grid charge — not a hold. Without an explicit
    # IDLE action the value iteration cannot represent holding the battery, so
    # the always-achievable IDLE floor (V[t,i] >= idle_reward + V[t+1,i]) is
    # unreachable and V collapses below it.
    if not np.any(np.abs(power_levels) <= POWER_TOLERANCE_KW):
        power_levels = np.sort(np.append(power_levels, 0.0))

    return soe_levels, power_levels


def _idle_battery_flows(
    soe: float,
    next_soe: float,
    battery_settings: BatterySettings,
) -> tuple[float, float]:
    """Derive battery_charged/battery_discharged for an IDLE period.

    During IDLE, excess solar passively charges the battery. The SOE delta
    (computed by _state_transition) is already efficiency-adjusted, so we
    reverse the efficiency to get the solar throughput consumed.

    Returns:
        (battery_charged, battery_discharged) in kWh throughput.
    """
    # No below-floor special case needed: _soe_floor (#233) only clamps next_soe
    # up to min_soe_kwh when soe already started at/above it -- when soe is
    # below the floor, the floor is soe itself, so a zero-solar period already
    # yields next_soe == soe (delta 0) without help from this function. Below
    # the floor with real solar, the delta is genuine stored energy and must
    # be credited the same as any other IDLE period (#269).
    passive_energy_stored = next_soe - soe
    battery_charged = (
        passive_energy_stored / battery_settings.efficiency_charge
        if passive_energy_stored > 0
        else 0.0
    )
    return battery_charged, 0.0


def _soe_floor(soe: float, battery_settings: BatterySettings) -> float:
    """The feasible/reportable SOE floor for a period that *started* at
    `soe`: `min_soe_kwh` if the period started at/above it, otherwise `soe`
    itself. Recovering from a below-floor start (e.g. a live sensor reading
    under Min SOC in demo mode, see #233) must never fabricate a jump to
    the floor with zero real energy stored."""
    return battery_settings.min_soe_kwh if soe >= battery_settings.min_soe_kwh else soe


def _effective_ac_cap_kwh(battery_settings: BatterySettings, dt: float) -> float | None:
    """Per-period AC-output energy cap (kWh), or None when the feature is off.

    Models a hybrid inverter whose total AC output (PV DC→AC conversion plus
    battery discharge) is capped, while DC-coupled PV can charge the battery
    above the cap. The margin is a model-side haircut only — it compensates
    for hourly forecasts flattening sub-period peaks — and is never written
    to hardware.
    """
    if battery_settings.inverter_max_ac_power_kw <= 0.0:
        return None
    return (
        battery_settings.inverter_max_ac_power_kw
        * (1.0 - battery_settings.inverter_ac_power_margin)
        * dt
    )


def _effective_import_cap_kwh(
    home_settings: HomeSettings | None, dt: float
) -> float | None:
    """Per-period grid-import energy cap (kWh) derived from the house's fuse
    service limit, or None when power monitoring is disabled (issue #429).

    Multiplied by `phase_count`: each phase is an independent fuse, so a
    balanced 3-phase house can import up to `phase_count` times a single
    phase's ceiling before any individual phase is stressed. `HomePowerMonitor`
    (`core/bess/power_monitor.py`) already relies on this same assumption at
    runtime -- on a fully unloaded 3-phase house it authorizes the battery up
    to its full `max_charge_power_w` (not a single phase's worth), since
    `available_pct` is computed relative to `max_charge_power_w / phase_count`
    per phase. `HomePowerMonitor` remains the real-time backstop against
    unbalanced loads (it measures actual per-phase current and throttles
    battery charging against the single worst-loaded phase, commit 37201cb9,
    #11); the DP has no per-phase forecast to reproduce that live check, so it
    caps against the balanced-load assumption instead of the unbalanced
    worst case.
    """
    if home_settings is None or not home_settings.power_monitoring_enabled:
        return None
    return (
        home_settings.voltage
        * home_settings.max_fuse_current
        * home_settings.safety_margin
        * home_settings.phase_count
        / 1000.0
    ) * dt


def _ac_flows(
    solar_production: float,
    home_consumption: float,
    solar_to_battery: float,
    battery_discharged: float,
    ac_cap_kwh: float | None,
) -> tuple[float, float, float]:
    """AC-side grid flows for one period, shared by every disposition.

    Solar not stored DC-side must pass through the inverter's AC stage; with a
    cap, anything above it is clipped (lost, zero credit). Battery discharge
    shares the same AC stage — callers must pre-limit discharge to the cap
    headroom (`ac_cap_kwh - min(solar, ac_cap_kwh)`).

    Returns (grid_imported, grid_exported, clipped_solar) in kWh.
    """
    residual_solar = solar_production - solar_to_battery
    if ac_cap_kwh is None:
        ac_solar = residual_solar
    else:
        ac_solar = min(residual_solar, ac_cap_kwh)
    clipped_solar = residual_solar - ac_solar
    ac_output = ac_solar + battery_discharged
    home_served = min(ac_output, home_consumption)
    grid_exported = ac_output - home_served
    grid_imported = home_consumption - home_served
    return grid_imported, grid_exported, clipped_solar


def _ac_flows_grid(
    solar_to_battery: np.ndarray,
    battery_discharged: np.ndarray | float,
    solar_production: float,
    home_consumption: float,
    ac_cap_kwh: float | None,
) -> tuple[np.ndarray, np.ndarray]:
    """np mirror of `_ac_flows` — same formulas, broadcast-friendly.

    Returns (grid_imported, grid_exported), omitting `clipped_solar` (unused
    by any vectorized caller so far).
    """
    residual_solar = solar_production - solar_to_battery
    if ac_cap_kwh is None:
        ac_solar = residual_solar
    else:
        ac_solar = np.minimum(residual_solar, ac_cap_kwh)
    ac_output = ac_solar + battery_discharged
    home_served = np.minimum(ac_output, home_consumption)
    return home_consumption - home_served, ac_output - home_served


@dataclass(frozen=True)
class PeriodFlows:
    """Every physical energy flow one candidate action produces in one period
    (kWh) -- the single flow record principle P4 requires
    (`docs/agents/optimizer-architecture.md`).

    Flows only. **No prices and no costs belong on this record**, deliberately:
    the DP's objective is evaluated at the #269 floored `reward_sell_price`
    while the reported `PeriodData` is priced at the real `sell_price`, so a
    single costed record would collapse a distinction the optimizer depends
    on. The record says what moved; each consumer prices it.

    `energy_stored` is the charge-throughput basis `(solar_to_battery +
    grid_to_battery) * efficiency_charge` -- the quantity the reward's wear
    term is charged on. `_build_period_data` deliberately keeps charging wear
    on the SoE-delta basis `max(0, next_soe - soe)` instead: the two are
    algebraically identical but take different float paths, and the reported
    economics are pinned bit-identically against goldens computed on the
    SoE-delta form.
    """

    solar_to_battery: float
    grid_to_battery: float
    battery_charged: float
    battery_discharged: float
    grid_imported: float
    grid_exported: float
    clipped_solar: float
    energy_stored: float


def _period_flows(
    power: float,
    soe: float,
    next_soe: float,
    home_consumption: float,
    solar_production: float,
    battery_settings: BatterySettings,
    dt: float,
    import_cap_kwh: float | None = None,
) -> PeriodFlows:
    """Derive one candidate action's complete flow set -- the only place a
    planned period's *reported and priced* flows are computed.

    Not the only place the charge split appears, and the difference matters
    if you are about to edit it: `_state_transition` carries its own copy to
    produce `next_soe`, and the two numpy mirrors (`_state_transition_grid`,
    `_compute_reward_grid`) carry vectorized copies that P1(a) permits the
    backward passes. A change to the split here must be made there too, or
    reported `battery_soe_end` will stop agreeing with reported
    `battery_charged`.

    Before Phase 3 this arithmetic existed three MORE times over
    (`_compute_reward`, `_build_period_data`, `_create_idle_schedule`), which
    is the reward-vs-flows divergence class P4 forbids: an edit to the reward
    side that did not reach the reporting side produced periods whose priced
    energy and reported energy disagreed (#497/#459).

    The term order and the in-place `grid_imported += grid_to_battery` are
    load-bearing, not stylistic. 56 of the corpus's 2194 selections are
    decided by a value gap under 1e-12 between candidates with different
    recorded actions (measured 2026-08-10), so re-associating this arithmetic
    -- "compute once, then multiply out" -- moves ULPs and flips them.

    The AC cap is derived here rather than accepted as an argument, and
    `_price_flows` derives it the same way. It used to be a parameter, which
    meant a caller could produce flows under one cap and have them priced
    under another -- the reward-vs-flows divergence class P4 exists to
    remove, merely relocated from the physics to its inputs. Every caller
    passed `_effective_ac_cap_kwh(battery_settings, dt)` anyway, so there was
    nothing to express and something to get wrong.
    """
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    if power > POWER_TOLERANCE_KW:  # STORE disposition (+ optional grid charge)
        surplus = max(0.0, solar_production - home_consumption)
        room_throughput = (
            battery_settings.max_soe_kwh - soe
        ) / battery_settings.efficiency_charge
        rate_throughput = battery_settings.max_charge_power_kw * dt
        solar_to_battery = min(surplus, rate_throughput, room_throughput)
        remaining_rate = max(
            0.0, min(rate_throughput, room_throughput) - solar_to_battery
        )
        grid_to_battery = remaining_rate  # solar fills first, grid tops up the rest

        # genuine excess solar (above rate/room) is exported; deliberate grid
        # top-up imported
        grid_imported, grid_exported, clipped_solar = _ac_flows(
            solar_production, home_consumption, solar_to_battery, 0.0, ac_cap_kwh
        )
        if import_cap_kwh is not None:
            # Grid charging must not push total import (load + charging) over
            # the house fuse's import cap (#429) -- throttle the grid-charge
            # component to whatever headroom the load leaves.
            grid_to_battery = min(
                grid_to_battery, max(0.0, import_cap_kwh - grid_imported)
            )
            # Only under the cap: with the cap binding, nothing physical
            # stops the command overshooting, so the plan must come down to
            # the lattice instead (4c).
            grid_to_battery = float(
                lattice_grid_charge(
                    solar_to_battery,
                    grid_to_battery,
                    battery_settings.max_charge_power_kw / 100 * dt,
                )
            )
        energy_stored = (
            solar_to_battery + grid_to_battery
        ) * battery_settings.efficiency_charge
        grid_imported += grid_to_battery
        return PeriodFlows(
            solar_to_battery=solar_to_battery,
            grid_to_battery=grid_to_battery,
            battery_charged=solar_to_battery + grid_to_battery,
            battery_discharged=0.0,
            grid_imported=grid_imported,
            grid_exported=grid_exported,
            clipped_solar=clipped_solar,
            energy_stored=energy_stored,
        )

    if power < -POWER_TOLERANCE_KW:  # Discharging
        battery_discharged = abs(power) * dt
        grid_imported, grid_exported, clipped_solar = _ac_flows(
            solar_production, home_consumption, 0.0, battery_discharged, ac_cap_kwh
        )
        return PeriodFlows(
            solar_to_battery=0.0,
            grid_to_battery=0.0,
            battery_charged=0.0,
            battery_discharged=battery_discharged,
            grid_imported=grid_imported,
            grid_exported=grid_exported,
            clipped_solar=clipped_solar,
            energy_stored=0.0,
        )

    # IDLE -- passive solar charging; the battery never discharges here
    # (`_idle_battery_flows` returns 0.0 for it by construction).
    battery_charged, battery_discharged = _idle_battery_flows(
        soe, next_soe, battery_settings
    )
    grid_imported, grid_exported, clipped_solar = _ac_flows(
        solar_production,
        home_consumption,
        battery_charged,
        battery_discharged,
        ac_cap_kwh,
    )
    return PeriodFlows(
        solar_to_battery=battery_charged,
        grid_to_battery=0.0,
        battery_charged=battery_charged,
        battery_discharged=battery_discharged,
        grid_imported=grid_imported,
        grid_exported=grid_exported,
        clipped_solar=clipped_solar,
        energy_stored=next_soe - soe,
    )


def _state_transition(
    soe: float,
    power: float,
    battery_settings: BatterySettings,
    dt: float,
    solar_production: float,
    home_consumption: float,
    ac_cap_kwh: float | None = None,
    import_cap_kwh: float | None = None,
) -> float:
    """
    Calculate the next state of energy based on current SOE and power action.

    EFFICIENCY HANDLING:
    - Charging: power x dt x efficiency = energy actually stored
    - Discharging: power x dt / efficiency = energy removed from storage
    This ensures that efficiency losses are properly accounted for in energy balance.

    PASSIVE SOLAR CHARGING (IDLE):
    When power=0, excess solar (production - consumption) passively charges the
    battery up to capacity, clamped by the inverter's max charge rate. This models
    the economically correct baseline: free solar energy is more valuable stored
    for later use than exported at the (typically lower) sell price.

    `ac_cap_kwh` is a live footgun and callers should pass
    `_effective_ac_cap_kwh(battery_settings, dt)` rather than omitting it. It is
    read only inside the `import_cap_kwh` branch, to throttle grid charging
    against the house fuse (#429), so a caller that passes an import cap while
    omitting this one computes `next_soe` under a different inverter limit than
    `_period_flows` derives for the very same action -- the reward-vs-flows
    divergence P4 exists to remove.

    It cannot be asserted away, which is the trap: `_effective_ac_cap_kwh`
    returns None for a battery with no AC cap configured, so None is a
    legitimate value here and is indistinguishable from a forgotten argument.
    The real remedy is to derive the cap inside this function, as
    `_period_flows` and `_price_flows` now do -- deferred rather than done here
    only because this is the bit-parity-pinned physics core the migration plan
    says to refactor around. Today `select_action` is the only caller passing an
    import cap and it passes the derived value, so nothing is presently wrong.
    """
    if power > POWER_TOLERANCE_KW:  # STORE disposition (+ optional grid charge)
        surplus = max(0.0, solar_production - home_consumption)
        room_throughput = (
            battery_settings.max_soe_kwh - soe
        ) / battery_settings.efficiency_charge
        rate_throughput = battery_settings.max_charge_power_kw * dt
        solar_to_battery = min(surplus, rate_throughput, room_throughput)
        remaining_rate = max(
            0.0, min(rate_throughput, room_throughput) - solar_to_battery
        )
        grid_to_battery = remaining_rate  # solar fills first, grid tops up the rest
        if import_cap_kwh is not None:
            # Grid charging must not push total import (load + charging)
            # over the house fuse's import cap (#429) -- throttle the
            # grid-charge component to whatever headroom the load leaves.
            load_import, _, _ = _ac_flows(
                solar_production, home_consumption, solar_to_battery, 0.0, ac_cap_kwh
            )
            grid_to_battery = min(
                grid_to_battery, max(0.0, import_cap_kwh - load_import)
            )
            # Same quantization as the flow record, so the state transition
            # and the flows agree on what was charged (4c).
            grid_to_battery = float(
                lattice_grid_charge(
                    solar_to_battery,
                    grid_to_battery,
                    battery_settings.max_charge_power_kw / 100 * dt,
                )
            )
        charge_energy = (
            solar_to_battery + grid_to_battery
        ) * battery_settings.efficiency_charge
        next_soe = min(battery_settings.max_soe_kwh, soe + charge_energy)

    elif power < -POWER_TOLERANCE_KW:  # Discharging
        # Energy removed from storage = power throughput ÷ discharging efficiency
        discharge_energy = abs(power) * dt / battery_settings.efficiency_discharge
        available_energy = soe - battery_settings.min_soe_kwh
        actual_discharge = min(discharge_energy, available_energy)
        next_soe = soe - actual_discharge

    else:  # IDLE — passive solar charging (mirrors load_first hardware behavior)
        surplus = max(0.0, solar_production - home_consumption)
        room_throughput = (
            battery_settings.max_soe_kwh - soe
        ) / battery_settings.efficiency_charge
        rate_throughput = battery_settings.max_charge_power_kw * dt
        solar_to_battery = min(surplus, rate_throughput, room_throughput)
        charge_energy = solar_to_battery * battery_settings.efficiency_charge
        next_soe = min(battery_settings.max_soe_kwh, soe + charge_energy)

    # Ensure SOE stays within physical bounds (see _soe_floor).
    next_soe = min(
        battery_settings.max_soe_kwh, max(_soe_floor(soe, battery_settings), next_soe)
    )

    return next_soe


def _state_transition_grid(
    soe: np.ndarray,
    power: np.ndarray,
    battery_settings: BatterySettings,
    dt: float,
    solar_production: float,
    home_consumption: float,
    ac_cap_kwh: float | None = None,
    import_cap_kwh: float | None = None,
) -> np.ndarray:
    """Vectorized form of `_state_transition` for the DP backward pass.

    `soe` is a column vector (S, 1) of SoE levels and `power` is a row
    vector (1, A) of candidate actions; the result broadcasts to (S, A).
    Every arithmetic step mirrors `_state_transition` exactly (same
    operations, same order) so results are bit-identical per cell -- this
    is what lets `_run_dynamic_programming` vectorize without changing the
    DP's numerics. See #236.
    """
    max_soe = battery_settings.max_soe_kwh
    min_soe = battery_settings.min_soe_kwh
    eff_charge = battery_settings.efficiency_charge
    eff_discharge = battery_settings.efficiency_discharge

    surplus = max(0.0, solar_production - home_consumption)
    rate_throughput = battery_settings.max_charge_power_kw * dt

    # STORE disposition (power > TOL): binary physics -- next_soe does not
    # depend on the exact positive power value, only on soe (see
    # _build_period_data's "STORE physics are binary" note).
    room_throughput = (max_soe - soe) / eff_charge
    solar_to_battery = np.minimum(np.minimum(surplus, rate_throughput), room_throughput)
    remaining_rate = np.maximum(
        0.0, np.minimum(rate_throughput, room_throughput) - solar_to_battery
    )
    grid_to_battery = remaining_rate
    if import_cap_kwh is not None:
        load_import, _ = _ac_flows_grid(
            solar_to_battery, 0.0, solar_production, home_consumption, ac_cap_kwh
        )
        grid_to_battery = np.minimum(
            grid_to_battery, np.maximum(0.0, import_cap_kwh - load_import)
        )
        # Mirrors the replay's quantization so both passes value the same
        # charge (4c) -- the one-action-set requirement on the charge side.
        grid_to_battery = lattice_grid_charge(
            solar_to_battery,
            grid_to_battery,
            battery_settings.max_charge_power_kw / 100 * dt,
        )
    store_charge_energy = (solar_to_battery + grid_to_battery) * eff_charge
    store_next_soe = np.minimum(max_soe, soe + store_charge_energy)

    # Discharging (power < -TOL)
    discharge_energy = np.abs(power) * dt / eff_discharge
    available_energy = soe - min_soe
    actual_discharge = np.minimum(discharge_energy, available_energy)
    discharge_next_soe = soe - actual_discharge

    # IDLE -- passive solar charging only, no grid top-up
    idle_charge_energy = solar_to_battery * eff_charge
    idle_next_soe = np.minimum(max_soe, soe + idle_charge_energy)

    next_soe = np.where(
        power > POWER_TOLERANCE_KW,
        store_next_soe,
        np.where(power < -POWER_TOLERANCE_KW, discharge_next_soe, idle_next_soe),
    )

    # See _soe_floor's docstring (#233) -- only raise to the floor when soe
    # started at/above it.
    floor = np.where(soe >= min_soe, min_soe, soe)
    next_soe = np.minimum(max_soe, np.maximum(floor, next_soe))
    return next_soe


def _compute_reward_grid(
    power: np.ndarray,
    soe: np.ndarray,
    next_soe: np.ndarray,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    current_buy_price: float,
    current_sell_price: float,
    solar_production: float,
    import_cap_kwh: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized form of `_compute_reward`'s reward calculation.

    Only the reward (and, for the import-cap feasibility mask, total
    grid_imported) is needed by the DP backward pass -- it discards
    `new_cost_basis`, same simplification the caller already applies to the
    scalar path (`reward, _ = _compute_reward(...)`). Formulas mirror
    `_compute_reward` exactly, branch for branch, for numerical parity. See
    #236.

    Returns (reward, grid_imported).
    """
    max_soe = battery_settings.max_soe_kwh
    eff_charge = battery_settings.efficiency_charge
    cycle_cost = battery_settings.cycle_cost_per_kwh
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    is_charge = power > POWER_TOLERANCE_KW
    is_discharge = power < -POWER_TOLERANCE_KW

    def ac_flows_grid(solar_to_battery, battery_discharged):
        return _ac_flows_grid(
            solar_to_battery,
            battery_discharged,
            solar_production,
            home_consumption,
            ac_cap_kwh,
        )

    # Idle passive-absorption flows. No below-floor special case needed --
    # see _idle_battery_flows's docstring (#269): the delta is already zero
    # below the floor when there's no real solar, and genuine when there is.
    passive_energy_stored = next_soe - soe
    idle_battery_charged = np.where(
        passive_energy_stored > 0,
        passive_energy_stored / eff_charge,
        0.0,
    )
    battery_discharged_active = np.abs(power) * dt

    # STORE disposition reward (mirrors the early-return branch in
    # _compute_reward, which redefines grid_imported/grid_exported locally)
    surplus = max(0.0, solar_production - home_consumption)
    rate_throughput = battery_settings.max_charge_power_kw * dt
    room_throughput = (max_soe - soe) / eff_charge
    solar_to_battery = np.minimum(np.minimum(surplus, rate_throughput), room_throughput)
    remaining_rate = np.maximum(
        0.0, np.minimum(rate_throughput, room_throughput) - solar_to_battery
    )
    grid_to_battery = remaining_rate
    grid_imported_store, grid_exported_store = ac_flows_grid(solar_to_battery, 0.0)
    if import_cap_kwh is not None:
        # Grid charging must not push total import (load + charging) over
        # the house fuse's import cap (#429).
        grid_to_battery = np.minimum(
            grid_to_battery, np.maximum(0.0, import_cap_kwh - grid_imported_store)
        )
        # Same quantization as the other three sites (4c).
        grid_to_battery = lattice_grid_charge(
            solar_to_battery,
            grid_to_battery,
            battery_settings.max_charge_power_kw / 100 * dt,
        )
    energy_stored_store = (solar_to_battery + grid_to_battery) * eff_charge
    battery_wear_cost_store = energy_stored_store * cycle_cost
    grid_imported_store = grid_imported_store + grid_to_battery
    total_cost_store = (
        grid_imported_store * current_buy_price
        - grid_exported_store * current_sell_price
        + battery_wear_cost_store
    )
    reward_store = -total_cost_store

    # Discharging reward. No self-throttle correction (#240): where actions
    # are actually chosen, sub-resolution overshoots never reach this code
    # (_discharge_candidates and the PWL mask exclude them), so any action
    # taken has grid_exported that is zero or a genuine, measurable export.
    # The coarse backward pass does still price in-band grid points here --
    # intentionally, as a value-approximation proxy; see the comment at its
    # feasibility mask in _run_dynamic_programming.
    grid_imported_d, grid_exported_discharge = ac_flows_grid(
        0.0, battery_discharged_active
    )
    total_cost_discharge = (
        grid_imported_d * current_buy_price
        - grid_exported_discharge * current_sell_price
    )
    reward_discharge = -total_cost_discharge

    # IDLE reward
    grid_imported_idle, grid_exported_idle = ac_flows_grid(idle_battery_charged, 0.0)
    energy_stored_idle = next_soe - soe
    battery_wear_cost_idle = energy_stored_idle * cycle_cost
    total_cost_idle = (
        grid_imported_idle * current_buy_price
        - grid_exported_idle * current_sell_price
        + battery_wear_cost_idle
    )
    reward_idle = -total_cost_idle

    reward = np.where(
        is_charge, reward_store, np.where(is_discharge, reward_discharge, reward_idle)
    )
    grid_imported = np.where(
        is_charge,
        grid_imported_store,
        np.where(is_discharge, grid_imported_d, grid_imported_idle),
    )
    return reward, grid_imported


def _compute_reward(
    power: float,
    soe: float,
    next_soe: float,
    period: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    buy_price: list[float],
    sell_price: list[float],
    solar_production: float,
    cost_basis: float,
    import_cap_kwh: float | None = None,
) -> tuple[float, float, PeriodFlows]:
    """Hot-path reward computation — prices the period's `PeriodFlows` record.

    CYCLE COST POLICY:
    - Applied only to charging operations (not discharging)
    - Applied to energy actually stored (after efficiency losses)
    - Grid costs applied to energy throughput (what you draw from grid)
    - Cost basis includes BOTH grid costs AND cycle costs for profitability analysis

    DISCHARGE ACCOUNTING:
    - No profitability veto: every physically valid discharge gets a finite
      reward. IDLE, competing in the same max() during backward induction,
      already makes the hold-vs-discharge call correctly via the
      forward-looking value function -- a separate floor on top of that is
      redundant at best (see docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md).
    - No self-throttle threshold (#240, superseded by #497): this function
      credits whatever flows `_ac_flows` reports, threshold-free. Discharges
      whose overshoot is below the export resolution are excluded from the
      action set outright (`_discharge_is_unexecutable`), never priced here.

    Returns:
        (reward, new_cost_basis, flows). The `PeriodFlows` record is exposed
        so callers get this candidate's complete physical flows without
        recomputing them -- the import-cap feasibility constraint (#429) and
        the reported `PeriodData` both read it rather than re-deriving (P4).
    """
    flows = _period_flows(
        power=power,
        soe=soe,
        next_soe=next_soe,
        home_consumption=home_consumption,
        solar_production=solar_production,
        battery_settings=battery_settings,
        dt=dt,
        import_cap_kwh=import_cap_kwh,
    )
    reward, new_cost_basis = _price_flows(
        flows=flows,
        power=power,
        soe=soe,
        next_soe=next_soe,
        period=period,
        home_consumption=home_consumption,
        battery_settings=battery_settings,
        dt=dt,
        buy_price=buy_price,
        sell_price=sell_price,
        solar_production=solar_production,
        cost_basis=cost_basis,
    )
    return reward, new_cost_basis, flows


def _price_flows(
    flows: PeriodFlows,
    power: float,
    soe: float,
    next_soe: float,
    period: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    buy_price: list[float],
    sell_price: list[float],
    solar_production: float,
    cost_basis: float,
) -> tuple[float, float]:
    """Price an already-derived `PeriodFlows` record: returns
    `(reward, new_cost_basis)`.

    Split from `_compute_reward` so the objective is demonstrably a function
    *of the record* rather than of a second derivation of the physics (P4).
    That is what lets `_replay_accounting_pass` price the stored records a
    PWL splice produced instead of re-deriving flows from the spliced
    trajectory -- where a caller passing a different `import_cap_kwh` than
    the selection loop used would otherwise silently price a period the plan
    never contained.

    Takes no `import_cap_kwh`: the cap is a constraint on *flows*, already
    applied inside `_period_flows`. Re-applying it here could only
    disagree.
    """
    current_buy_price = buy_price[period]
    current_sell_price = sell_price[period]
    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    grid_imported = flows.grid_imported
    grid_exported = flows.grid_exported

    # ============================================================================
    # BATTERY CYCLE COST AND COST BASIS CALCULATION
    # ============================================================================
    new_cost_basis = cost_basis

    if power > POWER_TOLERANCE_KW:  # STORE disposition
        solar_to_battery = flows.solar_to_battery
        grid_to_battery = flows.grid_to_battery
        energy_stored = flows.energy_stored
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh

        if ac_cap_kwh is None:
            solar_opportunity_cost = solar_to_battery * current_sell_price
        else:
            # Storing solar only forgoes the export it actually displaces —
            # absorbing energy that would have been clipped anyway is free.
            _, export_without_storing, _ = _ac_flows(
                solar_production, home_consumption, 0.0, 0.0, ac_cap_kwh
            )
            solar_opportunity_cost = (
                export_without_storing - grid_exported
            ) * current_sell_price
        grid_energy_cost = grid_to_battery * current_buy_price
        total_new_cost = grid_energy_cost + solar_opportunity_cost + battery_wear_cost
        if next_soe > battery_settings.min_soe_kwh:
            existing_cost = soe * cost_basis
            new_cost_basis = (existing_cost + total_new_cost) / next_soe
        else:
            new_cost_basis = (
                (total_new_cost / energy_stored) if energy_stored > 0 else cost_basis
            )

        total_cost = (
            grid_imported * current_buy_price
            - grid_exported * current_sell_price
            + battery_wear_cost
        )
        return -total_cost, new_cost_basis

    elif power < -POWER_TOLERANCE_KW:  # Discharging
        battery_wear_cost = 0.0

    else:  # IDLE — passive solar charging
        battery_charged = flows.battery_charged
        energy_stored = flows.energy_stored  # kWh stored in battery after efficiency
        battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh
        if energy_stored > 0 and next_soe > battery_settings.min_soe_kwh:
            if ac_cap_kwh is None:
                solar_opportunity_cost = battery_charged * current_sell_price
            else:
                # Same clipping discount as the STORE branch: passively
                # absorbing energy that would have been clipped anyway
                # forgoes only the export it actually displaces.
                _, export_without_absorbing, _ = _ac_flows(
                    solar_production, home_consumption, 0.0, 0.0, ac_cap_kwh
                )
                solar_opportunity_cost = (
                    export_without_absorbing - grid_exported
                ) * current_sell_price
            new_cost_basis = (
                soe * cost_basis + solar_opportunity_cost + battery_wear_cost
            ) / next_soe

    # ============================================================================
    # REWARD CALCULATION
    # ============================================================================
    total_cost = (
        grid_imported * current_buy_price
        - grid_exported * current_sell_price
        + battery_wear_cost
    )
    return -total_cost, new_cost_basis


def _record_marginal_value(
    decision,
    *,
    V,
    t: int,
    soe: float,
    battery_settings: BatterySettings,
    buy_price_t: float,
) -> None:
    """Record dV/dSoE for this period and the discharge authorization it implies.

    The shadow price is the value of the last kWh below this state, so it does
    not exist at the bottom level -- and a SoE at or below the reserve floor
    clamps there. Previously the assignment was simply skipped,
    leaving `shadow_price` at its 0.0 default, which every consumer read as
    "stored energy is worthless" and used to open the sub-period discharge
    ceiling on a value that had never been computed (#526).

    The authorization is decided here instead, where the value function is
    owned. At the bottom level there is no removable kWh below this state, so
    there is nothing to authorize and the decision stays False -- absence is
    not permission. Both call sites route through this function so the grid
    forward pass and the PWL-splice replay cannot drift onto different rules,
    which is the mirrored-implementation bug class P1 exists to prevent.

    The same argument applies to the *value estimate* itself, which is what
    #571 fixed: this used to do its own index arithmetic, snapping to the
    nearest grid point with `round()` while the policy walks the interpolant
    (`_interpolate_value`, which floors). A state in the lower half of a cell
    was therefore priced off the cell below -- a region of the value function
    the battery is not in -- so the reported slope stepped mid-cell instead of
    at cell boundaries, and the gate reads that number raw. It now reads the
    interpolant like every other consumer.

    #683 then widened *how much* of the interpolant it reads: one cell is a poor
    estimate of a staircase, so the price is taken across the whole span a
    delivery consumes (`_value_of_delivering_below`). That reading is per kWh
    delivered, which is why the comparison below carries no efficiency factor.
    """
    shadow_price = _value_of_delivering_below(V[t], soe, battery_settings)
    if shadow_price is None:
        return

    decision.shadow_price = shadow_price
    # At economic indifference the gate OPENS. The direction is not arbitrary:
    # when covering load from the battery and importing it are worth the same to
    # the model, P2's row 3 prefers load-tracking discharge, and P7's argument is
    # that a load-following cover absorbs forecast error where an import does
    # not. That is what the `>=` already intends; only differencing noise defeats
    # it, so the comparison is made against that noise rather than against zero
    # (#602 -- see SHADOW_PRICE_NOISE_REL for why these ties became structural).
    decision.intra_period_discharge_allowed = bool(
        buy_price_t >= shadow_price - abs(shadow_price) * SHADOW_PRICE_NOISE_REL
    )


def _build_period_data(
    flows: PeriodFlows,
    power: float,
    soe: float,
    next_soe: float,
    period: int,
    home_consumption: float,
    battery_settings: BatterySettings,
    dt: float,
    buy_price: list[float],
    sell_price: list[float],
    solar_production: float,
    new_cost_basis: float,
    currency: str,
    continuation_value: float = 0.0,
    export_curtailment_active: bool = False,
) -> PeriodData:
    """Build full PeriodData for the winning action of a DP cell.

    `flows` is the record `_compute_reward` already produced for this same
    action (P4): reporting prices exactly the energy the objective priced,
    and there is no second derivation here that an edit to the reward side
    could fail to reach. It is a required argument with no recomputing
    fallback on purpose -- a default that re-derived the flows would be the
    second construction site this phase exists to remove. `import_cap_kwh` is
    likewise gone from the signature: the cap shapes `grid_to_battery` inside
    `_period_flows`, so a reporting-side copy of that throttle could only
    ever disagree with the priced one.

    continuation_value: the DP's actual value-to-go from the resulting state
    (_interpolate_value(V_next, next_soe, ...), the same term
    _best_action_at_continuous_state adds to reward when choosing this
    action) -- reported as decision.future_value. Defaults to 0.0 for any
    caller that hasn't been updated to pass the real continuation value
    (see issue #353).

    export_curtailment_active: caller-computed, capability-aware curtailment
    flag (see optimize_battery_schedule's docstring). Used only to derive
    decision.curtailed (#501) via BatterySettings.should_curtail_export, the
    same shared predicate BSM's execution-time gate applies
    (_apply_period_schedule) -- never affects the reported energy/economic
    fields.
    """
    current_buy_price = buy_price[period]
    current_sell_price = sell_price[period]

    if power > POWER_TOLERANCE_KW:  # STORE disposition (+ optional grid charge)
        # STORE physics are binary (any positive power charges at rate_throughput),
        # so the DP's tie-break can report an arbitrary small `power`. Use the
        # achieved throughput instead — see #203.
        battery_action_kwh = flows.battery_charged
    else:  # Active discharging, or IDLE holding while surplus exports
        battery_action_kwh = power * dt

    energy_data = EnergyData(
        solar_production=solar_production,
        home_consumption=home_consumption,
        battery_charged=flows.battery_charged,
        battery_discharged=flows.battery_discharged,
        grid_imported=flows.grid_imported,
        grid_exported=flows.grid_exported,
        battery_soe_start=soe,
        battery_soe_end=next_soe,
        clipped_solar=flows.clipped_solar,
    )

    # Charging wear on the SoE-delta basis, not `flows.energy_stored`'s
    # charge-throughput basis. The two are algebraically identical and differ
    # only in float path (measured: 42 of 2461 corpus rows, max 6.66e-16),
    # but the reported economics are pinned bit-identically against goldens
    # captured on this form -- so the reward keeps its basis and reporting
    # keeps its own. See `PeriodFlows.energy_stored`.
    energy_stored = max(0.0, next_soe - soe)
    battery_wear_cost = energy_stored * battery_settings.cycle_cost_per_kwh

    curtailed = export_curtailment_active and battery_settings.should_curtail_export(
        flows.grid_exported, current_sell_price
    )

    decision_data = create_decision_data(
        power=power,
        battery_action_kwh=battery_action_kwh,
        energy_data=energy_data,
        cost_basis=new_cost_basis,
        curtailed=curtailed,
        # future_value is the DP's actual value-to-go from the resulting
        # state -- reported here as continuation_value directly (#353).
        future_value=continuation_value,
    )

    economic_data = EconomicData.from_energy_data(
        energy_data=energy_data,
        buy_price=current_buy_price,
        sell_price=current_sell_price,
        battery_cycle_cost=battery_wear_cost,
    )

    # Timestamp is set to None - caller will add timestamps based on optimization_period
    # The algorithm is time-agnostic and operates on relative period indices (0 to horizon-1)
    return PeriodData(
        period=period,
        energy=energy_data,
        timestamp=None,
        data_source="predicted",
        economic=economic_data,
        decision=decision_data,
    )


def print_optimization_results(results, buy_prices, sell_prices, economic_summary=None):
    """Log a detailed results table with strategic intents - new format version.

    Args:
        results: OptimizationResult object with period_data and economic_summary
        buy_prices: List of buy prices
        sell_prices: List of sell prices
        economic_summary: Optional override for the Summary block. Defaults to
            results.economic_summary. Callers pass the full-horizon summary
            when the result's own summary has been rescoped to today-only,
            so the Summary block matches the full-horizon table above it.
    """
    period_data_list = results.period_data
    economic_results = (
        economic_summary if economic_summary is not None else results.economic_summary
    )

    # Initialize totals
    total_consumption = 0
    total_base_cost = 0
    total_solar = 0
    total_solar_to_bat = 0
    total_grid_to_bat = 0
    total_grid_cost = 0
    total_battery_cost = 0
    total_combined_cost = 0
    total_savings = 0
    total_charging = 0
    total_discharging = 0

    # Initialize output string
    output = []

    output.append("\nBattery Schedule:")
    output.append(
        "╔════╦═══════════╦══════╦═══════╦╦═════╦══════╦══════╦═════╦═══════╦═══════════════╦═══════╦══════╦══════╗"
    )
    output.append(
        "║ Hr ║  Buy/Sell ║Cons. ║ Cost  ║║Sol. ║Sol→B ║Gr→B  ║ SoE ║Action ║    Intent     ║  Grid ║ Batt ║ Save ║"
    )
    output.append(
        "║    ║   (SEK)   ║(kWh) ║ (SEK) ║║(kWh)║(kWh) ║(kWh) ║(kWh)║(kWh)  ║               ║ (SEK) ║(SEK) ║(SEK) ║"
    )
    output.append(
        "╠════╬═══════════╬══════╬═══════╬╬═════╬══════╬══════╬═════╬═══════╬═══════════════╬═══════╬══════╬══════╣"
    )

    # Process each hour - replicating original logic exactly
    for i, period_data in enumerate(period_data_list):
        period = period_data.period
        consumption = period_data.energy.home_consumption
        solar = period_data.energy.solar_production
        action = period_data.decision.battery_action or 0.0
        soe_kwh = period_data.energy.battery_soe_end
        intent = period_data.decision.strategic_intent

        # Calculate values exactly like original function
        base_cost = (
            consumption * buy_prices[i]
            if i < len(buy_prices)
            else consumption * period_data.economic.buy_price
        )

        # Extract solar flows from detailed flow data (always available from EnergyData)
        solar_to_battery = period_data.energy.solar_to_battery
        grid_to_battery = period_data.energy.grid_to_battery

        # Calculate costs using original logic - FIXED: use property accessor for battery_cycle_cost
        grid_cost = (
            period_data.energy.grid_imported * period_data.economic.buy_price
            - period_data.energy.grid_exported * period_data.economic.sell_price
        )
        battery_cost = (
            period_data.economic.battery_cycle_cost
        )  # FIXED: access via economic component
        combined_cost = grid_cost + battery_cost
        period_savings = base_cost - combined_cost

        # Update totals
        total_consumption += consumption
        total_base_cost += base_cost
        total_solar += solar
        total_solar_to_bat += solar_to_battery
        total_grid_to_bat += grid_to_battery
        total_grid_cost += grid_cost
        total_battery_cost += battery_cost
        total_combined_cost += combined_cost
        total_savings += period_savings
        total_charging += period_data.energy.battery_charged
        total_discharging += period_data.energy.battery_discharged

        # Format intent to fit column width
        intent_display = intent[:15] if len(intent) > 15 else intent

        # Format period row - preserving original formatting exactly
        buy_sell_str = f"{buy_prices[i] if i < len(buy_prices) else period_data.economic.buy_price:.2f}/{sell_prices[i] if i < len(sell_prices) else period_data.economic.sell_price:.2f}"

        output.append(
            f"║{period:3d} ║ {buy_sell_str:9s} ║{consumption:5.1f} ║{base_cost:6.2f} ║║{solar:4.1f} ║{solar_to_battery:5.1f} ║{grid_to_battery:5.1f} ║{soe_kwh:4.0f} ║{action:6.1f} ║ {intent_display:13s} ║{grid_cost:6.2f} ║{battery_cost:5.2f} ║{period_savings:5.2f} ║"
        )

    # Add separator and total row
    output.append(
        "╠════╬═══════════╬══════╬═══════╬╬═════╬══════╬══════╬═════╬═══════╬═══════════════╬═══════╬══════╬══════╣"
    )
    output.append(
        f"║Tot ║           ║{total_consumption:5.1f} ║{total_base_cost:6.2f} ║║{total_solar:4.1f} ║{total_solar_to_bat:5.1f} ║{total_grid_to_bat:5.1f} ║     ║C:{total_charging:4.1f} ║               ║{total_grid_cost:6.2f} ║{total_battery_cost:5.2f} ║{total_savings:5.2f} ║"
    )
    output.append(
        f"║    ║           ║      ║       ║║     ║      ║      ║     ║D:{total_discharging:4.1f} ║               ║       ║      ║      ║"
    )
    output.append(
        "╚════╩═══════════╩══════╩═══════╩╩═════╩══════╩══════╩═════╩═══════╩═══════════════╩═══════╩══════╩══════╝"
    )

    # Append summary stats to output
    output.append("\n      Summary:")
    output.append(
        f"      Grid-only cost:           {economic_results.grid_only_cost:.2f} SEK"
    )
    output.append(
        f"      Optimized cost:           {economic_results.battery_solar_cost:.2f} SEK"
    )
    output.append(
        f"      Total savings:            {economic_results.grid_to_battery_solar_savings:.2f} SEK"
    )
    savings_percentage = economic_results.grid_to_battery_solar_savings_pct
    output.append(f"      Savings percentage:         {savings_percentage:.1f} %")

    # Log all output in a single call
    logger.info("\n".join(output))


def _run_dynamic_programming(
    horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    battery_settings: BatterySettings,
    dt: float,
    solar_production: list[float] | None = None,
    initial_soe: float | None = None,
    initial_cost_basis: float = 0.0,
    terminal_curve: TerminalValueCurve | None = None,
    currency: str = "SEK",
    max_charge_power_per_period: list[float] | None = None,
    import_cap_kwh: float | None = None,
    capabilities: PlatformCapabilities = DEFAULT_CAPABILITIES,
) -> np.ndarray:
    """
    Run backward induction DP to compute optimal battery control policy.

    Also considers, per period, a residual load-cover column: discharge
    exactly the forecast net load wherever the lattice cannot represent
    covering it (see _residual_cover_p) -- so the value function knows
    holding, under-covering and over-covering are not the only options,
    keeping V consistent with the replay pass whose candidate set
    (_discharge_candidates) contains the same action. Added for the
    sunrise/sunset crossover (#466) and extended to every such period by
    Phase 4b (#352).

    Also considers, at every state, a distinct SOLAR_EXPORT-below-max
    candidate (#313) -- battery SOE held exactly unchanged (no passive
    charge) while this period's own solar surplus exports directly -- as an
    alternative to IDLE's forced full passive charge. Without this, IDLE's
    mandatory charge conflates "let solar bypass the battery" with "how much
    room to keep" into one decision, forcing a genuinely necessary
    headroom-creating action into whichever period first needs the room
    even when a better-priced, side-effect-free slot for it existed earlier
    in the same horizon. See
    docs/superpowers/specs/2026-07-16-issue-313-root-cause-investigation.md.
    """

    # The candidate space this pass estimates V over is defined once, in
    # action_selector (P1) -- this pass evaluates it with its own vectorized
    # evaluator but must not restate what the candidates are. Imported here
    # rather than at module scope because action_selector imports this module
    # for the reward/transition primitives, so a top-level import would be
    # circular -- the same arrangement pwl_window_dp already has with this
    # file.
    from core.bess.action_selector import (
        _residual_cover_p,
        _solar_export_bypass_is_unexecutable,
    )

    # Set defaults if not provided
    if solar_production is None:
        solar_production = [0.0] * horizon
    if initial_soe is None:
        initial_soe = battery_settings.min_soe_kwh

    # Discretize state and action spaces
    soe_levels, power_levels = _discretize_state_action_space(battery_settings)

    V = np.zeros((horizon + 1, len(soe_levels)))

    # Terminal value: assign value to usable energy remaining at end of horizon
    if terminal_curve is not None:
        for i, soe in enumerate(soe_levels):
            V[horizon, i] = terminal_curve.value(soe - battery_settings.min_soe_kwh)

    min_soe_kwh = battery_settings.min_soe_kwh
    max_soe_kwh = battery_settings.max_soe_kwh
    n_states = len(soe_levels)

    # (S, 1) and (1, A) broadcast columns/rows for the vectorized state x
    # action grid -- same discretized values _run_dynamic_programming's
    # scalar loop iterated over, just evaluated all at once per period.
    soe_col = soe_levels.reshape(-1, 1)
    power_row = power_levels.reshape(1, -1)

    is_discharge = power_row < -POWER_TOLERANCE_KW
    is_charge = power_row > POWER_TOLERANCE_KW

    # Charging feasibility depends only on soe (not on the period), so the
    # non-derating part of the mask is period-invariant and can be
    # precomputed once instead of recomputed every backward-induction step.
    available_capacity = max_soe_kwh - soe_col
    max_charge_power = available_capacity / dt / battery_settings.efficiency_charge
    charge_feasible_base = ~is_charge | (power_row <= max_charge_power)

    available_energy = soe_col - min_soe_kwh
    max_discharge_power = available_energy / dt * battery_settings.efficiency_discharge
    discharge_feasible = ~is_discharge | (np.abs(power_row) <= max_discharge_power)

    ac_cap_kwh = _effective_ac_cap_kwh(battery_settings, dt)

    # Backward induction
    for t in reversed(range(horizon)):
        period_max_charge = (
            max_charge_power_per_period[t]
            if max_charge_power_per_period is not None
            else None
        )
        if period_max_charge is not None:
            charge_feasible = charge_feasible_base & (
                ~is_charge | (power_row <= period_max_charge)
            )
        else:
            charge_feasible = charge_feasible_base

        feasible = charge_feasible & discharge_feasible
        if ac_cap_kwh is not None:
            # Battery discharge shares the inverter's AC stage with PV
            # conversion — only the headroom the (possibly clipped) solar
            # leaves is deliverable.
            ac_headroom_kwh = max(
                0.0, ac_cap_kwh - min(solar_production[t], ac_cap_kwh)
            )
            feasible &= ~is_discharge | (np.abs(power_row) * dt <= ac_headroom_kwh)

        # Deliberately NOT masked by _discharge_is_unexecutable (#497): this
        # pass only estimates V on a coarse POWER_STEP_KW lattice; actions are
        # chosen (and executability enforced) in the replay and PWL passes.
        # The coarse lattice often has no executable point near the deficit
        # breakpoint, so an in-band action here -- phantom overshoot credit
        # and all, bounded by GRID_FLOW_RESOLUTION_KWH * sell_price per
        # period -- is a closer proxy for the exact-cover action the replay's
        # finer percent lattice really has than excluding it. Measured on all
        # 33 fixtures (2026-08-09): masking here helps 7 and hurts 10, net
        # -0.004 SEK -- approximation noise, not a real bug either way.
        next_soe = _state_transition_grid(
            soe_col,
            power_row,
            battery_settings,
            dt,
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
            ac_cap_kwh=ac_cap_kwh,
            import_cap_kwh=import_cap_kwh,
        )
        feasible &= (next_soe >= min_soe_kwh) & (next_soe <= max_soe_kwh)

        reward, grid_imported = _compute_reward_grid(
            power_row,
            soe_col,
            next_soe,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            current_buy_price=buy_price[t],
            current_sell_price=sell_price[t],
            solar_production=solar_production[t],
            import_cap_kwh=import_cap_kwh,
        )

        effective_import_cap = None
        if import_cap_kwh is not None:
            # Constrain, don't raise (#429): an action pushing total import
            # over the cap is infeasible UNLESS no feasible action can meet
            # it (e.g. load alone exceeds the cap even at max discharge) --
            # then the least-bad (minimum-import) action(s) remain the
            # feasible floor, same convention as the AC-output cap and
            # temperature derating (mask, never except).
            floor_grid_imported = np.min(
                np.where(feasible, grid_imported, np.inf), axis=1, keepdims=True
            )
            effective_import_cap = np.maximum(import_cap_kwh, floor_grid_imported)
            feasible &= grid_imported <= effective_import_cap + 1e-9

        next_i = np.round((next_soe - min_soe_kwh) / SOE_STEP_KWH).astype(np.int64)
        next_i = np.clip(next_i, 0, n_states - 1)

        value = reward + V[t + 1][next_i]
        value = np.where(feasible, value, -np.inf)

        # IDLE is always a feasible, finite-reward action (no physical
        # constraint check applies to it, and _compute_reward_grid never
        # returns -inf), so the max over actions can never remain -inf here.
        V[t, :] = np.max(value, axis=1)

        # SOLAR_EXPORT-below-max candidate (#313): soe held exactly
        # unchanged (next_soe == soe, same grid index), solar surplus
        # exports directly instead of passively charging. Reusing
        # _compute_reward_grid with next_soe == soe already produces the
        # correct economics (see _idle_battery_flows: zero SOE delta ->
        # battery_charged=0, so grid_exported reflects the full surplus) --
        # the same reward shape IDLE gets when the battery happens to be
        # full, just made reachable below max_soe too. One extra
        # O(n_states) column, not O(n_states x n_actions).
        # With the AC cap set, this candidate is also what defers charging
        # to preserve headroom for above-cap solar: ac_flows_grid caps the
        # exported surplus and the DP weighs the clipped remainder against
        # the value of keeping the room (no separate HOLD action needed).
        #
        # Withheld entirely where the classifier would call the period IDLE
        # rather than SOLAR_EXPORT (#630) -- there the bypass is not a
        # commandable action at all, and plain IDLE is what the hardware
        # does. Unlike the discharge mask above, this one DOES apply here:
        # that exception rests on the coarse lattice having no exact-cover
        # point nearby, so an in-band action is the better proxy. Nothing
        # analogous holds here -- the bypass is an exact action, not a
        # lattice approximation, and its executable neighbour (plain IDLE)
        # is already in the action set at every state.
        if not _solar_export_bypass_is_unexecutable(
            solar_production[t], home_consumption[t], battery_settings, dt
        ):
            zeros_col = np.zeros_like(soe_col)
            reward_bypass, grid_imported_bypass = _compute_reward_grid(
                zeros_col,
                soe_col,
                soe_col,
                home_consumption=home_consumption[t],
                battery_settings=battery_settings,
                dt=dt,
                current_buy_price=buy_price[t],
                current_sell_price=sell_price[t],
                solar_production=solar_production[t],
                import_cap_kwh=import_cap_kwh,
            )
            value_bypass = reward_bypass.reshape(-1) + V[t + 1][np.arange(n_states)]
            if effective_import_cap is not None:
                bypass_feasible = (
                    grid_imported_bypass.reshape(-1)
                    <= effective_import_cap.reshape(-1) + 1e-9
                )
                value_bypass = np.where(bypass_feasible, value_bypass, -np.inf)
            V[t, :] = np.maximum(V[t, :], value_bypass)

        # Residual load-cover candidate (#466 follow-up): one extra
        # O(n_states) column discharging exactly this period's forecast net
        # load, mirroring _discharge_candidates' off-lattice cover candidate
        # so the value function and the replay pass see the same action
        # space. Same feasibility masks as the main grid: available energy,
        # AC-stage headroom, SOE bounds, import cap.
        cover_p = _residual_cover_p(
            home_consumption[t], solar_production[t], dt, capabilities, battery_settings
        )
        if cover_p is not None:
            cover_col = np.full_like(soe_col, -cover_p)
            cover_feasible = (cover_p <= max_discharge_power).reshape(-1)
            if ac_cap_kwh is not None:
                ac_headroom_kwh = max(
                    0.0, ac_cap_kwh - min(solar_production[t], ac_cap_kwh)
                )
                if cover_p * dt > ac_headroom_kwh:
                    cover_feasible = np.zeros(n_states, dtype=bool)
            next_soe_cover = _state_transition_grid(
                soe_col,
                cover_col,
                battery_settings,
                dt,
                solar_production=solar_production[t],
                home_consumption=home_consumption[t],
                ac_cap_kwh=ac_cap_kwh,
                import_cap_kwh=import_cap_kwh,
            )
            cover_feasible &= (
                (next_soe_cover >= min_soe_kwh) & (next_soe_cover <= max_soe_kwh)
            ).reshape(-1)
            reward_cover, grid_imported_cover = _compute_reward_grid(
                cover_col,
                soe_col,
                next_soe_cover,
                home_consumption=home_consumption[t],
                battery_settings=battery_settings,
                dt=dt,
                current_buy_price=buy_price[t],
                current_sell_price=sell_price[t],
                solar_production=solar_production[t],
                import_cap_kwh=import_cap_kwh,
            )
            if effective_import_cap is not None:
                cover_feasible &= (
                    grid_imported_cover.reshape(-1)
                    <= effective_import_cap.reshape(-1) + 1e-9
                )
            next_i_cover = np.round(
                (next_soe_cover - min_soe_kwh) / SOE_STEP_KWH
            ).astype(np.int64)
            next_i_cover = np.clip(next_i_cover, 0, n_states - 1).reshape(-1)
            value_cover = reward_cover.reshape(-1) + V[t + 1][next_i_cover]
            value_cover = np.where(cover_feasible, value_cover, -np.inf)
            V[t, :] = np.maximum(V[t, :], value_cover)

    return V


def _interpolate_value(
    V_row: np.ndarray, soe: float, battery_settings: BatterySettings
) -> float:
    """Linearly interpolate a value-function row (V[t, :]) at a continuous
    SoE, rather than snapping to the nearest discretized grid point.

    `V_row` has no grid points below `min_soe_kwh` (#233's below-floor
    tolerance lets `soe` itself go below it). Clamping those states to
    `V_row[0]` made every below-floor state look identically worthless,
    masking real differences in how close each was to the floor (#336).
    Extrapolate the V_row[0]->V_row[1] gradient instead."""
    idx = (soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH
    if idx < 0.0:
        gradient = V_row[1] - V_row[0] if len(V_row) > 1 else 0.0
        return V_row[0] + idx * gradient
    idx = min(idx, len(V_row) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(V_row) - 1)
    frac = idx - lo
    return V_row[lo] * (1 - frac) + V_row[hi] * frac


def _local_value_slope(
    V_row: np.ndarray, soe: float, battery_settings: BatterySettings
) -> float:
    """dV/dSoE of a value-function row at a continuous SoE, taken across the
    grid cell containing it -- the marginal value of stored energy the grid
    DP itself sees at that state (its local shadow price).

    Used by the hybrid tie detector (#450) to convert the DP's SOE_STEP_KWH
    grid-snapping into a value-noise magnitude in currency units, which is
    what a decision margin has to be compared against. Same index arithmetic
    as _interpolate_value, so the slope reported is exactly the one that
    interpolation uses at `soe`.
    """
    idx = (soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH
    idx = min(max(idx, 0.0), len(V_row) - 1)
    lo = min(int(idx), len(V_row) - 2)
    return float((V_row[lo + 1] - V_row[lo]) / SOE_STEP_KWH)


# In grid-index units, so 2.5e-11 kWh of SoE -- far below any physical
# resolution, and ~1e5x larger than the ulp noise it exists to absorb.
_GRID_POINT_TOLERANCE = 1e-9


def _snapped_grid_index(soe: float, battery_settings: BatterySettings) -> float:
    """Continuous value-function grid index of `soe`, with indices within
    `_GRID_POINT_TOLERANCE` of a grid point snapped exactly onto it.

    A one-sided derivative is discontinuous at each grid point, so an index a
    single ulp off one would answer for the wrong cell. That is not
    hypothetical: a battery resting exactly on its reserve floor yields
    idx = +1e-16 rather than 0.0 in several fixtures, which without this would
    price a kWh below the floor that does not exist and open the gate #526
    closed. `_interpolate_value` needs no such guard -- it is continuous, so
    the same noise moves its output by an ulp too.
    """
    idx = (soe - battery_settings.min_soe_kwh) / SOE_STEP_KWH
    nearest = round(idx)
    if abs(idx - nearest) < _GRID_POINT_TOLERANCE:
        idx = float(nearest)
    return idx


def has_value_cell_below(soe: float, battery_settings: BatterySettings) -> bool:
    """Whether a value-function cell exists below `soe` -- i.e. whether
    `_value_of_delivering_below` can price the last kWh below this state at all.

    Exposed because tests need to select exactly the periods where the shadow
    price is (or is not) computable. Re-deriving that rule test-side is what
    #571 broke: the selectors mirrored the DP's old `round()` snapping and kept
    passing while production moved to the interpolant's cell.
    """
    return _snapped_grid_index(soe, battery_settings) > 0.0


def _value_of_delivering_below(
    V_row: np.ndarray, soe: float, battery_settings: BatterySettings
) -> float | None:
    """Value given up per kWh **delivered** by discharging from this state.

    This replaced a one-cell backward difference, which answered in a different
    unit (per kWh of *SoE*) and, in the discharge-limited regime, answered even
    that inaccurately -- the latter being the actual #683 defect. The old rule
    `buy * eta >= dV/dSoE` was itself dimensionally sound; what it could not
    survive was a bad reading of `dV/dSoE`. `SOE_STEP_KWH` equals
    `POWER_STEP_KW * dt`, while converting SoE into delivery carries
    `efficiency_discharge`. So V is a staircase whose riser is one whole delivery
    step and which is flat once every `1/(1-eta)` cells: a one-cell backward
    difference lands on a riser 19 times out of 20 and reports the *undiscounted*
    price, and on the flat cell reports zero.

    Pricing the delivery instead removes the artifact rather than compensating for
    it. Delivering `SOE_STEP_KWH` costs `SOE_STEP_KWH / eta` of SoE, which spans
    1/eta cells -- just over one -- so the interpolant is read across exactly the
    span the discharge consumes, and the staircase averages out by construction
    instead of 19 times in 20.

    That averaging does not hold in the bottom cell. For a grid index below `1/eta`,
    `soe - SOE_STEP_KWH/eta` falls under `min_soe_kwh`, where `_interpolate_value`
    extrapolates on the `V[0]->V[1]` gradient (#336); the result then collapses
    algebraically to that one cell's slope divided by eta, with no averaging. This is
    not a regression -- it is exactly what the previous estimator returned there, and
    the rule change compensates for it identically (`buy >= g/eta` is `buy*eta >= g`)
    -- but it does mean a flat bottom cell still prices at 0.0 and opens the gate. The
    `None` guard above only covers index 0 itself (#526).

    The result is denominated per delivered kWh, the same unit as `buy_price`, so
    the gate's comparison needs no efficiency factor: covering `dE` now consumes
    `dE/eta` of SoE, which would later have delivered `dE` anyway, so the
    opportunity cost is `dE * p_future` and eta cancels on both sides.

    `None` when no cell below exists -- absence is not permission (#526).
    """
    if not has_value_cell_below(soe, battery_settings) or len(V_row) < 2:
        return None

    soe_consumed = SOE_STEP_KWH / battery_settings.efficiency_discharge
    value_here = _interpolate_value(V_row, soe, battery_settings)
    value_below = _interpolate_value(V_row, soe - soe_consumed, battery_settings)
    return float((value_here - value_below) / SOE_STEP_KWH)


def _best_action_at_continuous_state(
    soe: float,
    t: int,
    V_next: np.ndarray,
    power_levels: np.ndarray,
    home_consumption: list[float],
    battery_settings: BatterySettings,
    dt: float,
    solar_production: list[float],
    buy_price: list[float],
    sell_price: list[float],
    cost_basis: float,
    max_charge_power_per_period: list[float] | None,
    capabilities: PlatformCapabilities = DEFAULT_CAPABILITIES,
    import_cap_kwh: float | None = None,
    sell_price_floored: list[bool] | None = None,
) -> tuple[float, float, float, float, PeriodFlows, float, float]:
    """The grid DP's forward replay: `action_selector.select_action` with the
    continuation value read off the already-known V[t+1, :] row, linearly
    interpolated at the candidate's true continuous SoE instead of snapped to
    the nearest grid index. Used by optimize_battery_schedule's Step 2 to
    reconstruct the continuous path without trusting a policy table computed
    for a slightly different state. See
    docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md.

    Candidate enumeration, evaluation and tie policy all live in
    `action_selector` (P1) -- this wrapper contributes only the grid-flavoured
    `eval_V`/slope pair and the tuple shape its callers expect. `power_levels`
    is unused, kept for call-site compatibility with
    `_discretize_state_action_space`.

    Returns (best_action, best_next_soe, best_new_cost_basis, best_reward,
    best_flows, tie_margin, value_slope). `best_flows` is the winning
    candidate's own `PeriodFlows`, handed straight to `_build_period_data` so
    the reported period describes the physics the objective actually scored
    (P4). `tie_margin` is the gap between the *argmax*
    action's value and the best behaviourally distinct runner-up's --
    float("inf") if no distinct alternative was feasible, meaning "not tied,
    no comparison possible" -- and is measured pre-tie-break on purpose (see
    `SelectionResult`). Used by the hybrid PWL tie detector (#450) to find
    near-tied periods without re-deriving this comparison.
    """
    # Imported here rather than at module scope because action_selector
    # imports this module for the reward/transition primitives it evaluates
    # candidates with, so a top-level import would be circular -- the same
    # arrangement pwl_window_dp already has with this file.
    from core.bess.action_selector import PeriodInputs, select_action

    result = select_action(
        soe=soe,
        t=t,
        cost_basis=cost_basis,
        eval_V=lambda next_soe: _interpolate_value(V_next, next_soe, battery_settings),
        eval_value_slope=lambda next_soe: _local_value_slope(
            V_next, next_soe, battery_settings
        ),
        period_inputs=PeriodInputs(
            buy_price=buy_price,
            sell_price=sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            dt=dt,
            max_charge_power_per_period=max_charge_power_per_period,
            import_cap_kwh=import_cap_kwh,
            capabilities=capabilities,
            sell_price_floored=sell_price_floored,
        ),
        battery_settings=battery_settings,
    )
    return (
        result.chosen.power,
        result.chosen.next_soe,
        result.chosen.new_cost_basis,
        result.chosen.reward,
        result.chosen.flows,
        result.tie_margin,
        result.value_slope,
    )


def _create_idle_schedule(
    horizon: int,
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    initial_soe: float,
    battery_settings: BatterySettings,
    dt: float,
    currency: str,
) -> OptimizationResult:
    """
    Create an all-IDLE schedule where battery passively charges from excess solar.

    Used by the all-IDLE safety net, which swaps this in only when it is
    strictly cheaper than the DP's own schedule (there is no profit gate).
    Excess solar charges the battery up to capacity; only overflow exports to grid.

    Built from the same `_period_flows` / `_price_flows` / `_build_period_data`
    chain as every other path (P4). It used to carry a fourth independent copy
    of the IDLE physics, which had already drifted: it charged the full
    `battery_charged * sell_price` as solar opportunity cost, where
    `_price_flows` discounts the share that would have been AC-clipped anyway
    and therefore cost nothing to absorb. Collapsing the copy adopts the
    correct basis -- see the note at the `_price_flows` call below.

    That correction is not purely internal, and the distinction is worth
    keeping straight: the guardrail *decision* cannot see it, because the
    comparison reads `economic_summary.battery_solar_cost` (summed from each
    period's `hourly_cost`) and `cost_basis` feeds none of it. But when the
    guardrail does fire, this schedule is what gets returned -- so on an
    AC-capped system every period's reported `decision.cost_basis` shifts,
    measured at up to 0.049977 SEK/kWh. No comparison moves; a reported field
    does.
    """
    period_data_list = []
    current_soe = initial_soe
    current_cost_basis = battery_settings.cycle_cost_per_kwh

    for t in range(horizon):
        # Passive solar charging: excess solar goes to battery, overflow to grid
        next_soe = _state_transition(
            current_soe,
            0.0,
            battery_settings,
            dt=dt,
            solar_production=solar_production[t],
            home_consumption=home_consumption[t],
        )
        flows = _period_flows(
            power=0.0,
            soe=current_soe,
            next_soe=next_soe,
            home_consumption=home_consumption[t],
            solar_production=solar_production[t],
            battery_settings=battery_settings,
            dt=dt,
        )
        # Cost basis only. The reward is discarded: this schedule's cost is
        # summed from the reported PeriodData below, exactly as before, and
        # the guardrail comparison reads that sum -- not this term.
        _reward, current_cost_basis = _price_flows(
            flows=flows,
            power=0.0,
            soe=current_soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            cost_basis=current_cost_basis,
        )

        period_data = _build_period_data(
            flows=flows,
            power=0.0,
            soe=current_soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            new_cost_basis=current_cost_basis,
            currency=currency,
        )
        # `_record_marginal_value` is deliberately NOT called here, so
        # `intra_period_discharge_allowed` keeps its `False` default (#526).
        # No value function exists on this path -- it is the numerical safety
        # net returned when the optimized plan scores worse than doing
        # nothing, so there is no dV/dSoE to authorize against. That matters
        # concretely: on a sunny all-IDLE day `classify_strategic_intent` can
        # return SOLAR_EXPORT here, which IS a gate-consulting intent. Before
        # #526 the period's shadow_price defaulted to 0.0 and opened the
        # ceiling to 100 on a value nothing had computed. Absence of an
        # economic basis is not permission.

        period_data_list.append(period_data)
        current_soe = next_soe

    # Calculate economic summary for idle schedule
    total_base_cost = sum(home_consumption[i] * buy_price[i] for i in range(horizon))
    solar_only_cost = sum(h.economic.solar_only_cost for h in period_data_list)
    total_optimized_cost = sum(h.economic.hourly_cost for h in period_data_list)

    total_charged = sum(h.energy.battery_charged for h in period_data_list)
    total_discharged = sum(h.energy.battery_discharged for h in period_data_list)

    economic_summary = EconomicSummary(
        grid_only_cost=total_base_cost,
        solar_only_cost=solar_only_cost,
        battery_solar_cost=total_optimized_cost,
        grid_to_solar_savings=total_base_cost - solar_only_cost,
        grid_to_battery_solar_savings=total_base_cost - total_optimized_cost,
        solar_to_battery_solar_savings=solar_only_cost - total_optimized_cost,
        grid_to_battery_solar_savings_pct=(
            (total_base_cost - total_optimized_cost) / total_base_cost * 100
            if total_base_cost > 0
            else 0.0
        ),
        total_charged=total_charged,
        total_discharged=total_discharged,
    )

    return OptimizationResult(
        period_data=period_data_list,
        economic_summary=economic_summary,
        input_data={
            "buy_price": buy_price,
            "sell_price": sell_price,
            "home_consumption": home_consumption,
            "solar_production": solar_production,
            "initial_soe": initial_soe,
            "initial_cost_basis": battery_settings.cycle_cost_per_kwh,
            "horizon": horizon,
        },
    )


def _replay_accounting_pass(
    horizon: int,
    actions: list[float],
    soe_trajectory: list[float],
    flows_trajectory: list[PeriodFlows],
    initial_cost_basis: float,
    V: np.ndarray,
    buy_price: list[float],
    sell_price: list[float],
    reward_sell_price: list[float],
    home_consumption: list[float],
    solar_production: list[float],
    battery_settings: BatterySettings,
    dt: float,
    currency: str,
    export_curtailment_active: bool = False,
) -> tuple[list[PeriodData], float]:
    """Rebuild PeriodData (and the reward-objective cost) for a given
    (action, SOE, flows) trajectory.

    Only used by the hybrid PWL path (#450): once a tied window's actions have
    been re-solved exactly and spliced in, the accounting produced inline by
    optimize_battery_schedule's selection loop describes the *pre-splice*
    trajectory and must be recomputed. The no-tie path never calls this, so its
    output is bit-for-bit whatever the selection loop produced.

    Only the *prices* are re-applied here. The flows are the records the
    selection loop and the PWL window solve already produced, spliced
    together by `splice_schedule` and priced through `_price_flows` -- this
    pass never re-derives physics (P4). Re-deriving would be a second
    derivation of a trajectory whose actions were chosen elsewhere, and it is
    why this function no longer takes `import_cap_kwh`: the cap shaped
    `grid_to_battery` when the flows were produced, and a replay handed a
    different cap than the solve ran under would otherwise have silently
    priced a period the plan never contained.

    Costs are chained rather than stored: `cost_basis` depends on the
    preceding period's outcome, which splicing changes, so it is the one
    quantity that genuinely must be recomputed here.

    Rewards are priced against `reward_sell_price` -- the DP's own objective
    -- while the reported PeriodData carries the real `sell_price`.
    """
    hourly_results: list[PeriodData] = []
    reward_objective_cost = 0.0
    cost_basis = initial_cost_basis

    for t in range(horizon):
        soe = soe_trajectory[t]
        next_soe = soe_trajectory[t + 1]
        action_flows = flows_trajectory[t]
        action_reward, new_cost_basis = _price_flows(
            flows=action_flows,
            power=actions[t],
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=reward_sell_price,
            solar_production=solar_production[t],
            cost_basis=cost_basis,
        )

        period_data = _build_period_data(
            # The same stored record the reward above was priced from --
            # prices differ between the objective (`reward_sell_price`) and
            # the report (`sell_price`), the physics does not.
            flows=action_flows,
            power=actions[t],
            soe=soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            new_cost_basis=new_cost_basis,
            currency=currency,
            continuation_value=_interpolate_value(V[t + 1], next_soe, battery_settings),
            export_curtailment_active=export_curtailment_active,
        )

        _record_marginal_value(
            period_data.decision,
            V=V,
            t=t,
            soe=soe,
            battery_settings=battery_settings,
            buy_price_t=buy_price[t],
        )

        hourly_results.append(period_data)
        cost_basis = new_cost_basis
        reward_objective_cost -= action_reward

    return hourly_results, reward_objective_cost


def optimize_battery_schedule(
    buy_price: list[float],
    sell_price: list[float],
    home_consumption: list[float],
    battery_settings: BatterySettings,
    solar_production: list[float] | None = None,
    initial_soe: float | None = None,
    initial_cost_basis: float | None = None,
    period_duration_hours: float = 0.25,
    terminal_curve: TerminalValueCurve | None = None,
    currency: str = "SEK",
    max_charge_power_per_period: list[float] | None = None,
    capabilities: PlatformCapabilities = DEFAULT_CAPABILITIES,
    export_curtailment_active: bool = False,
    home_settings: HomeSettings | None = None,
    tie_diagnostics: dict | None = None,
) -> OptimizationResult:
    """
    Battery optimization that eliminates dual cost calculation by using
    DP-calculated PeriodData directly in simulation.

    Args:
        buy_price: List of electricity buy prices for each period
        sell_price: List of electricity buy prices for each period
        home_consumption: List of home consumption for each period (kWh)
        battery_settings: Battery configuration and limits
        solar_production: List of solar production for each period (kWh), defaults to 0
        initial_soe: Initial battery state of energy (kWh), defaults to min_soe
        initial_cost_basis: Initial cost basis for battery cycling, defaults to cycle_cost
        period_duration_hours: Duration of each period in hours (always 0.25 for quarterly resolution)
        terminal_curve: Concave valuation of usable energy remaining at end of
            horizon -- the buy-median rate up to the household's pre-dawn need,
            nothing above it. Prevents end-of-day dumping when tomorrow's prices
            aren't available yet, without the all-or-nothing midnight SOE a single
            rate produces (#602). Defaults to None (no terminal value).
        max_charge_power_per_period: Per-period max charge power limits (kW), typically
            from temperature derating. When provided, charging actions exceeding the
            limit for each period are excluded from the optimization. Defaults to None
            (no per-period limits, uses battery_settings.max_charge_power_kw).
        export_curtailment_active: Caller-computed, capability-aware flag for
            whether export-limit curtailment (#269) will actually execute --
            battery_settings.export_curtailment_enabled AND the platform
            supports it AND the entities are configured. Deliberately NOT
            read from battery_settings.export_curtailment_enabled directly:
            that's just the user's opt-in preference, and planning as if
            curtailment will happen on a platform/config that can't actually
            do it would make outcomes worse than leaving the feature off
            (the plan forgoes real defenses against a loss that never gets
            neutralized). Same call-site pattern as `capabilities` below:
            the caller reads the platform, the DP is told. Defaults to False.
        capabilities: What the executing platform can express -- discharge
            lattice, whether a discharge rate is a ceiling or a target, mode
            vocabulary, minimum gear (`execution_model.PlatformCapabilities`,
            Phase 4a / D2). `BatterySystemManager` builds it from the live
            controller; the default describes the TOU-register platform the DP
            assumed before 4a, so a caller without hardware plans exactly as
            it did before. It is one object rather than a kwarg per fact on
            purpose: two construction sites for the same platform is how the
            planner and the executor drifted apart in #282/#497/#511/#537.
        home_settings: Home electrical settings (fuse limit, voltage, phases). When
            `power_monitoring_enabled` is set, the DP derives a per-period grid-import
            energy cap and treats it as a hard physical constraint (#429): total import
            (house load + battery charging) may not exceed it, constraining rather than
            excluding a period whose load alone exceeds the cap. Defaults to None (no
            import cap, matching power_monitoring_enabled's own default of False).
        tie_diagnostics: Optional mutable dict. When provided, populated with the
            internal tie-margin/value-slope/window/SoE-trajectory data this
            function already computes, for offline measurement tooling (#450).
            Never passed by production callers; a pure no-op when omitted.

    Returns:
        OptimizationResult with optimal battery schedule
    """

    horizon = len(buy_price)
    dt = period_duration_hours
    import_cap_kwh = _effective_import_cap_kwh(home_settings, dt)

    logger.info(f"Optimization using dt={dt} hours for horizon={horizon} periods")

    # Handle defaults
    if solar_production is None:
        solar_production = [0.0] * horizon
    if initial_soe is None:
        initial_soe = battery_settings.min_soe_kwh
    if initial_cost_basis is None:
        initial_cost_basis = battery_settings.cycle_cost_per_kwh

    # Validate inputs to prevent impossible scenarios
    if initial_soe > battery_settings.max_soe_kwh:
        raise ValueError(
            f"Invalid initial_soe={initial_soe:.1f}kWh exceeds battery capacity={battery_settings.max_soe_kwh:.1f}kWh"
        )

    # Allow optimization to start from below minimum SOC (can happen after restart or deep discharge)
    # The optimizer will naturally work to bring SOE back above minimum through charging
    if initial_soe < battery_settings.min_soe_kwh:
        logger.warning(
            f"Starting optimization with initial_soe={initial_soe:.1f}kWh below minimum SOE={battery_settings.min_soe_kwh:.1f}kWh. "
            f"Optimizer will work to restore battery charge."
        )

    logger.info(
        f"Starting direct optimization: horizon={horizon}, initial_soe={initial_soe:.1f}, initial_cost_basis={initial_cost_basis:.3f}"
    )

    # Reward-facing sell price only (#269): when export curtailment is
    # enabled, periods priced below the curtailment floor get an effective
    # sell price of 0.0 for the DP's own reward/action-selection calculation
    # only -- backward induction propagates a later period's reward into
    # every earlier period's decision via the continuation value, so leaving
    # this unfixed would make the DP refuse a genuinely profitable earlier
    # action just to avoid a loss that curtailment neutralizes in reality.
    # The real sell_price list (unchanged) is still what gets reported on
    # PeriodData.economic.sell_price below and fed to _build_period_data --
    # BSM's execution-time curtailment trigger reads that field directly, and
    # the displayed plan should show the honest physics-only cost, not the
    # actuation override.
    if export_curtailment_active:
        floor = battery_settings.export_curtailment_price_floor
        reward_sell_price = [0.0 if p < floor else p for p in sell_price]
        # Which periods the floor actually rewrote -- the tie policy's
        # charge-early row (tie_policy.py, row 4) only fires in these.
        sell_price_floored = [p < floor for p in sell_price]
    else:
        reward_sell_price = sell_price
        sell_price_floored = None

    # Step 1: Run DP to compute the value-to-go array V. Step 2 recomputes
    # each replay action directly from V (interpolated at the true
    # continuous SoE) rather than looking up a grid-snapped policy table.
    V = _run_dynamic_programming(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=reward_sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        initial_cost_basis=initial_cost_basis,
        dt=dt,
        terminal_curve=terminal_curve,
        currency=currency,
        max_charge_power_per_period=max_charge_power_per_period,
        import_cap_kwh=import_cap_kwh,
        capabilities=capabilities,
    )

    # Step 2: Reconstruct the optimal path with continuous SoE propagation.
    # The old approach read period_data from stored_period_data[(t, i)], which
    # reported grid-snapped SoE values (battery_soe_end = soe_levels[next_i]).
    # Here we carry the exact floating-point SoE forward each period so the
    # reported trajectory matches what the simulator will produce (R == P).
    hourly_results = []
    current_soe = initial_soe
    current_cost_basis = initial_cost_basis
    reward_objective_cost = 0.0
    _, power_levels = _discretize_state_action_space(battery_settings)

    tie_margins: list[float] = []
    # Local marginal value of stored energy (dV/dSoE) at each period's chosen
    # next state -- the scale factor that turns the DP's SOE_STEP_KWH
    # grid-snapping into a value error in currency, which is what the tie
    # detector compares the margins against (#450).
    value_slopes: list[float] = []
    # Trajectory recorded alongside the inline accounting so the hybrid PWL
    # path (#450) can re-solve a tied window and splice it back in. Recording
    # is three list appends per period; nothing downstream reads them unless a
    # tie is actually detected.
    actions: list[float] = []
    soe_trajectory: list[float] = [initial_soe]
    # The chosen candidate's flow record per period, recorded alongside the
    # action so a splice can carry physics and action together (P4) and the
    # accounting replay never re-derives either.
    flows_trajectory: list[PeriodFlows] = []
    cost_basis_trajectory: list[float] = []
    for t in range(horizon):
        # Recompute the action directly at the true continuous SoE using the
        # already-known V[t+1, :] (linearly interpolated) as the continuation
        # value -- the same reward+max(V) logic as the backward pass, applied
        # at the true state instead of one snapped to the nearest grid index.
        (
            action,
            next_soe,
            new_cost_basis,
            action_reward,
            action_flows,
            tie_margin,
            value_slope,
        ) = _best_action_at_continuous_state(
            soe=current_soe,
            t=t,
            V_next=V[t + 1],
            power_levels=power_levels,
            home_consumption=home_consumption,
            battery_settings=battery_settings,
            dt=dt,
            solar_production=solar_production,
            buy_price=buy_price,
            sell_price=reward_sell_price,
            cost_basis=current_cost_basis,
            max_charge_power_per_period=max_charge_power_per_period,
            capabilities=capabilities,
            import_cap_kwh=import_cap_kwh,
            sell_price_floored=sell_price_floored,
        )
        tie_margins.append(tie_margin)
        value_slopes.append(value_slope)
        cost_basis_trajectory.append(current_cost_basis)
        actions.append(action)
        soe_trajectory.append(next_soe)
        flows_trajectory.append(action_flows)

        period_data = _build_period_data(
            flows=action_flows,
            power=action,
            soe=current_soe,
            next_soe=next_soe,
            period=t,
            home_consumption=home_consumption[t],
            battery_settings=battery_settings,
            dt=dt,
            buy_price=buy_price,
            sell_price=sell_price,
            solar_production=solar_production[t],
            new_cost_basis=new_cost_basis,
            currency=currency,
            # Same continuation-value term _best_action_at_continuous_state
            # added internally to choose this action (dp_battery_algorithm.py
            # _best_action_at_continuous_state's `value = reward +
            # _interpolate_value(...)`), reported here as future_value (#353)
            # instead of being discarded.
            continuation_value=_interpolate_value(V[t + 1], next_soe, battery_settings),
            export_curtailment_active=export_curtailment_active,
        )

        _record_marginal_value(
            period_data.decision,
            V=V,
            t=t,
            soe=current_soe,
            battery_settings=battery_settings,
            buy_price_t=buy_price[t],
        )

        hourly_results.append(period_data)
        current_soe = next_soe
        current_cost_basis = new_cost_basis
        reward_objective_cost -= action_reward

    # Step 2b (#450): hybrid exact resolution of near-tied decisions. The grid
    # DP snaps continuation-value lookups to SOE_STEP_KWH, which is noise on
    # the order of the tie margins recorded above -- so where two actions are
    # near-tied, the grid DP's pick can be an artifact of that snapping rather
    # than economics. Those windows (and only those) are re-solved with the
    # exact continuous-SOE PWL DP, pinned to the grid DP's own SOE at both
    # ends so everything outside the window is untouched.
    #
    # When no window is flagged, nothing below this point runs and the
    # schedule built above is returned bit-for-bit unchanged. That is rare
    # per period (1% of periods flag across the fixture suite) but NOT rare
    # per solve: 8 of 32 fixtures -- a quarter of runs -- flag at least one
    # window, and those runs pay roughly 20-40x the grid DP's latency (e.g.
    # 0.05s -> 1.6s on the #450 fixture). Budget for the slow path being hit
    # on a meaningful fraction of real optimizations, not for it being
    # exceptional. Imported here rather than at module scope because
    # pwl_window_dp imports this module (it reuses this file's reward and
    # transition primitives), so a top-level import would be circular.
    from core.bess.exceptions import PWLWindowUnderRefinedError
    from core.bess.pwl_window_dp import (
        resolve_pwl_window,
        run_pwl_window_backward_induction,
    )
    from core.bess.schedule_splicer import splice_schedule
    from core.bess.tie_detection import Window, detect_tie_windows

    windows = detect_tie_windows(
        tie_margins,
        value_slopes,
        soe_step_kwh=SOE_STEP_KWH,
    )

    if tie_diagnostics is not None:
        tie_diagnostics["tie_margins"] = list(tie_margins)
        tie_diagnostics["value_slopes"] = list(value_slopes)
        tie_diagnostics["windows"] = list(windows)
        tie_diagnostics["soe_trajectory"] = list(soe_trajectory)
        tie_diagnostics["resolved_initial_cost_basis"] = initial_cost_basis

    if windows:
        logger.info(
            "Near-tied DP decisions detected (#450): re-solving %d window(s) "
            "%s with the exact PWL DP",
            len(windows),
            [(w.start, w.end) for w in windows],
        )
        window_resolutions: dict[int, list[tuple[float, float, PeriodFlows]]] = {}
        # The windows actually solved, which is what the splice and the
        # boundary re-derivation below must iterate -- not `windows`, because
        # a detected window too large for the solver is bisected here and
        # replaced by the sub-windows that were certified in its place.
        resolved_windows: list[Window] = []
        pending = list(windows)
        while pending:
            window = pending.pop(0)
            window_horizon = window.end - window.start
            sl = slice(window.start, window.end)
            window_max_charge = (
                max_charge_power_per_period[sl]
                if max_charge_power_per_period is not None
                else None
            )
            # End SOE is pinned to the grid DP's own SOE at the window's exit,
            # so the untouched schedule after the window stays valid. An
            # infeasible pin raises out of resolve_pwl_window and is
            # deliberately not caught: silently keeping the grid DP's
            # possibly-wrong choice, or splicing in a table whose accuracy the
            # solver itself could not certify, are both exactly the fallback
            # this project forbids.
            #
            # `PWLWindowUnderRefinedError` is caught, and only it, because it
            # says something different from the other raises: not "this answer
            # is wrong" but "this window is too big to answer exactly" (#624).
            # `detect_tie_windows` merges adjacent flagged periods with no cap,
            # while the solver's breakpoint set compounds per backward step, so
            # a long enough run of near-ties exceeds
            # `PWL_MAX_PREIMAGE_SEED_POINTS` no matter what the budget is set
            # to -- measured at ~8 periods, and reported from the field on a
            # nine-period window over volatile SE3 prices. Left uncaught it
            # discarded the entire schedule, including every period that had
            # solved fine, and the hourly retry then reran the same inputs into
            # the same wall forever.
            #
            # Bisecting is not a fallback and does not weaken P6: each half is
            # solved by the same solver under the same certification, and a
            # half that still cannot certify is split again. What changes is
            # only how much the exact solver is asked to do at once. The two
            # halves reconnect through `soe_trajectory[mid]` -- the grid DP's
            # own SOE, which is exactly the pin two separately-detected
            # adjacent windows would already have used, so the splice sees
            # nothing it does not handle today.
            #
            # Termination is by construction rather than by an iteration cap: a
            # one-period window seeds from the four-breakpoint pinned terminal
            # row (`_pinned_terminal_row`), so its preimage cross product is
            # ~4 x |discharge levels| -- three orders of magnitude below the
            # budget, and independent of prices, battery size and grid
            # resolution. A horizon-1 window that still cannot certify is
            # therefore not a sizing problem, and is re-raised.
            #
            # `import_cap_kwh` is the same fuse-derived grid-import cap (#429)
            # the grid DP optimized the rest of the schedule against. It has to
            # be passed here too: the windowed solver re-decides exactly the
            # periods where charging-vs-not is closest, so a window solved
            # without the cap could splice back a grid-charge action that
            # plans more import than the house's fuse can carry -- weakening
            # the constraint precisely where it is most likely to bind.
            try:
                V_window = run_pwl_window_backward_induction(
                    window_horizon=window_horizon,
                    buy_price=buy_price[sl],
                    sell_price=reward_sell_price[sl],
                    home_consumption=home_consumption[sl],
                    solar_production=solar_production[sl],
                    battery_settings=battery_settings,
                    dt=dt,
                    end_soe_target=soe_trajectory[window.end],
                    max_charge_power_per_period=window_max_charge,
                    capabilities=capabilities,
                    import_cap_kwh=import_cap_kwh,
                )
            except PWLWindowUnderRefinedError:
                if window_horizon <= 1:
                    raise
                mid = window.start + window_horizon // 2
                logger.warning(
                    "PWL window (%d, %d) exceeds what the exact solver can "
                    "certify in one solve (#624) -- splitting at %d and "
                    "re-solving each half against the grid DP's own SOE there",
                    window.start,
                    window.end,
                    mid,
                )
                pending.insert(0, Window(start=mid, end=window.end))
                pending.insert(0, Window(start=window.start, end=mid))
                continue
            window_floored = (
                sell_price_floored[sl] if sell_price_floored is not None else None
            )
            resolution = resolve_pwl_window(
                V_window,
                start_soe=soe_trajectory[window.start],
                window_horizon=window_horizon,
                buy_price=buy_price[sl],
                sell_price=reward_sell_price[sl],
                home_consumption=home_consumption[sl],
                solar_production=solar_production[sl],
                battery_settings=battery_settings,
                dt=dt,
                cost_basis=cost_basis_trajectory[window.start],
                max_charge_power_per_period=window_max_charge,
                capabilities=capabilities,
                import_cap_kwh=import_cap_kwh,
                sell_price_floored=window_floored,
            )
            window_resolutions[window.start] = resolution
            resolved_windows.append(window)

            # Splice each window as it is resolved, rather than all of them
            # once the loop ends (#624).
            #
            # A bisected window's second half starts exactly where the first
            # half ends, so it must be solved against the SOE the first half
            # actually reached -- not the grid DP's nominal value there. Those
            # differ: the end-SOE pin is only guaranteed to within
            # `_end_soe_pin_tolerance`, and `splice_schedule` writes the
            # solver's own achieved `next_soe`, not the target. Planning the
            # second half from a state the schedule never visits would make it
            # optimize against a start state the plan does not reach.
            #
            # Measured contribution on the #624 fixture: 0.000000 SEK. This
            # closes a latent inconsistency, not an observed cost error -- the
            # seam periods there are discharge-dominated, where throughput
            # follows the action rather than the start SOE, so the residual
            # cannot express itself as cost. It is kept because the next
            # bisected window need not be discharge-dominated, and because a
            # seam is the one boundary the pre-existing "period AT `end`"
            # re-derivation below deliberately does not cover.
            #
            # For separately-detected windows this is a no-op, so no existing
            # schedule moves: `detect_tie_windows` merges any windows that
            # touch, so a later window's `start` is strictly greater than an
            # earlier window's `end`, and a window only writes SOE up to its
            # own `end`.
            #
            # `cost_basis_trajectory` is deliberately NOT advanced the same
            # way. It feeds the solver's reward, not the physics, and the
            # final accounting comes from `_replay_accounting_pass` over the
            # spliced trajectory below -- so a stale basis at a seam can make
            # the second half's ranking marginally worse, but cannot make its
            # plan unexecutable, which is what R == P is about.
            actions, soe_trajectory, flows_trajectory = splice_schedule(
                actions,
                soe_trajectory,
                flows_trajectory,
                [window],
                {window.start: resolution},
            )

        # A window owns periods [start, end), but writes the SOE at `end` --
        # that is the pinned exit state. The period AT `end` is not re-solved,
        # so it keeps the flow record the selection loop derived from its
        # PRE-splice start SOE, while now reporting the post-splice one. The
        # pin only guarantees the exit lands within `_end_soe_pin_tolerance`,
        # not exactly, so those two can differ -- and a STORE or IDLE period's
        # charge depends on its start SOE (through `room_throughput` and
        # `next_soe - soe`). Left alone, that period would report a
        # `battery_soe_start` its own `battery_charged` cannot produce.
        #
        # Re-derive exactly that one period per window, which is what the
        # pre-Phase-3 replay did for every period. Its action and its
        # `next_soe` are untouched by the splice; only the state it starts
        # from moved.
        #
        # This restores the flow record's agreement with the period's own
        # *start* state, which is what the splice moved. One case it does not
        # reconcile: a RATE-limited (or import-capped) STORE boundary, where
        # throughput is `min(rate_throughput, room_throughput) =
        # rate_throughput` and therefore independent of `soe`, while the stale
        # `next_soe` still encodes the pre-splice start -- so
        # `battery_soe_end - battery_soe_start` overstates `battery_charged`
        # by exactly the pin drift.
        #
        # Room-limited STORE is NOT affected, despite being the intuitive
        # suspect: there throughput is `(max_soe - soe) / eff`, so
        # `energy_stored == max_soe - soe`, and `_state_transition` clamps
        # `next_soe` to `max_soe` -- the two agree for any start SOE,
        # including a spliced one.
        #
        # The gap is pre-existing, not introduced here: `_build_period_data`
        # has always derived STORE throughput from `soe` via room/rate while
        # taking `next_soe` from the trajectory (verified against origin/main),
        # so the same mismatch existed before this pass stopped re-deriving. It
        # is bounded by `_end_soe_pin_tolerance`, and closing it means
        # re-deriving the post-window trajectory, which the pin exists
        # precisely to avoid.
        #
        # A bisected window (#624) puts a boundary *inside* what was one
        # detected window, and the period at that boundary is owned and
        # re-solved by the next half -- it already carries that solver's own
        # flow record. Re-deriving it here would overwrite a record produced
        # by the solver that chose the action with one derived from the
        # trajectory, which is exactly the re-derivation P4 forbids. So the
        # re-derivation applies only to exit periods no resolved window owns.
        resolved_periods = {p for w in resolved_windows for p in range(w.start, w.end)}
        for window in resolved_windows:
            if window.end >= horizon or window.end in resolved_periods:
                continue
            flows_trajectory[window.end] = _period_flows(
                power=actions[window.end],
                soe=soe_trajectory[window.end],
                next_soe=soe_trajectory[window.end + 1],
                home_consumption=home_consumption[window.end],
                solar_production=solar_production[window.end],
                battery_settings=battery_settings,
                dt=dt,
                import_cap_kwh=import_cap_kwh,
            )
        hourly_results, reward_objective_cost = _replay_accounting_pass(
            horizon=horizon,
            actions=actions,
            soe_trajectory=soe_trajectory,
            flows_trajectory=flows_trajectory,
            initial_cost_basis=initial_cost_basis,
            V=V,
            buy_price=buy_price,
            sell_price=sell_price,
            reward_sell_price=reward_sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            battery_settings=battery_settings,
            dt=dt,
            currency=currency,
            export_curtailment_active=export_curtailment_active,
        )

    # Step 3: Calculate economic summary directly from PeriodData
    total_base_cost = sum(
        home_consumption[i] * buy_price[i] for i in range(len(buy_price))
    )

    # Reported cost must reflect what will actually happen at runtime, not
    # the honest physics-only price PeriodData itself keeps (#502): a period
    # that will be curtailed to zero export contributes zero cost here, via
    # a reporting-only copy -- hourly_results/PeriodData stay untouched
    # since BSM's execution-time curtailment trigger and the guardrail
    # comparison above both require the real, un-adjusted values.
    #
    # solar_only_cost (the "solar but no battery" baseline) must be derived
    # from the SAME curtailment-adjusted copy as total_optimized_cost, not
    # the honest hourly_results -- otherwise the battery-vs-solar-only
    # savings subtraction below mixes a curtailed total against an
    # uncurtailed baseline, misattributing curtailment's own savings to the
    # battery (code review finding).
    curtailment_adjusted_periods = [
        apply_export_curtailment_to_period_data(
            h,
            export_curtailment_active,
            battery_settings.export_curtailment_price_floor,
        )
        for h in hourly_results
    ]
    solar_only_cost = sum(
        h.economic.solar_only_cost for h in curtailment_adjusted_periods
    )
    total_optimized_cost = sum(
        h.economic.hourly_cost for h in curtailment_adjusted_periods
    )
    total_charged = sum(h.energy.battery_charged for h in hourly_results)
    total_discharged = sum(h.energy.battery_discharged for h in hourly_results)

    # Calculate savings directly - renamed variables for clarity
    grid_to_battery_solar_savings = total_base_cost - total_optimized_cost
    solar_to_battery_solar_savings = solar_only_cost - total_optimized_cost

    economic_summary = EconomicSummary(
        grid_only_cost=total_base_cost,
        solar_only_cost=solar_only_cost,
        battery_solar_cost=total_optimized_cost,
        grid_to_solar_savings=total_base_cost - solar_only_cost,
        grid_to_battery_solar_savings=grid_to_battery_solar_savings,
        solar_to_battery_solar_savings=solar_to_battery_solar_savings,
        grid_to_battery_solar_savings_pct=(
            (grid_to_battery_solar_savings / total_base_cost) * 100
            if total_base_cost > 0
            else 0
        ),
        total_charged=total_charged,
        total_discharged=total_discharged,
    )

    logger.info(
        f"Direct Results: Grid-only cost: {total_base_cost:.2f}, "
        f"Optimized cost: {total_optimized_cost:.2f}, "
        f"Savings: {grid_to_battery_solar_savings:.2f} {currency} ({economic_summary.grid_to_battery_solar_savings_pct:.1f}%)"
    )

    # ============================================================================
    # NUMERICAL SAFETY NET: guard against SoE-grid discretization residual
    # ============================================================================
    # Bellman's principle of optimality guarantees the DP's own schedule is
    # never worse than doing nothing: IDLE is always a feasible action every
    # period, so backward induction already picks it whenever it's the best
    # available option. The only way the realized schedule can still cost
    # slightly more than an all-IDLE schedule is SoE-grid discretization
    # residual (see docs/superpowers/specs/2026-07-06-dp-bellman-guardrail-removal-design.md)
    # -- a numerical artifact, not an economic one. This is a trivial O(1)
    # comparison, not a configurable threshold.
    idle_schedule = _create_idle_schedule(
        horizon=horizon,
        buy_price=buy_price,
        sell_price=sell_price,
        home_consumption=home_consumption,
        solar_production=solar_production,
        initial_soe=initial_soe,
        battery_settings=battery_settings,
        dt=dt,
        currency=currency,
    )

    # When export_curtailment_active, the DP's action selection optimized
    # against reward_sell_price (floored), not the real sell_price used
    # above -- so comparing total_optimized_cost/idle_schedule at real
    # price here would be judging the DP's plan by a different objective
    # than the one it was asked to optimize, and could silently discard a
    # plan the DP correctly preferred (confirmed via a randomized sweep
    # against this optimizer, #459 review). Recompute both sides of the
    # guardrail comparison at reward_sell_price so it's internally
    # consistent with the actual objective; the RETURNED idle_schedule
    # (if the guardrail fires) still reports at the real price, unchanged.
    guardrail_optimized_cost = total_optimized_cost
    guardrail_idle_cost = idle_schedule.economic_summary.battery_solar_cost
    if export_curtailment_active:
        # reward_objective_cost is accumulated directly from each period's
        # action_reward (_best_action_at_continuous_state's own return
        # value) -- the exact objective the DP chose actions against, not a
        # reconstruction from reported PeriodData (which could drift from
        # the real per-action reward, e.g. self-throttle export-credit
        # zeroing applying to the reward calc but not to the raw
        # grid_exported energy field).
        guardrail_optimized_cost = reward_objective_cost
        guardrail_idle_cost = _create_idle_schedule(
            horizon=horizon,
            buy_price=buy_price,
            sell_price=reward_sell_price,
            home_consumption=home_consumption,
            solar_production=solar_production,
            initial_soe=initial_soe,
            battery_settings=battery_settings,
            dt=dt,
            currency=currency,
        ).economic_summary.battery_solar_cost

    # Both sides must also be credited for energy left at the boundary, or the
    # guardrail judges the DP's plan by a different objective than the DP
    # optimized against and discards plans that deliberately carry energy past
    # the horizon (#602). Latent before the concave row: the capped scalar was
    # small enough that the omission rarely changed the comparison, whereas a
    # buy-median head rate is roughly twice it. Caught by
    # `test_tie_detection_synthetic_coverage`, which found the guardrail firing
    # on a plan that was better once the carry was counted.
    if terminal_curve is not None:
        min_soe = battery_settings.min_soe_kwh
        guardrail_optimized_cost -= terminal_curve.value(
            hourly_results[-1].energy.battery_soe_end - min_soe
        )
        guardrail_idle_cost -= terminal_curve.value(
            idle_schedule.period_data[-1].energy.battery_soe_end - min_soe
        )

    if guardrail_idle_cost < guardrail_optimized_cost:
        logger.info(
            "Idle-schedule guardrail fired: idle cost %.6f < optimized cost %.6f "
            "(delta %.6f %s) -- returning the all-IDLE schedule instead of the "
            "DP's plan.",
            guardrail_idle_cost,
            guardrail_optimized_cost,
            guardrail_optimized_cost - guardrail_idle_cost,
            currency,
        )
        return idle_schedule

    return OptimizationResult(
        period_data=hourly_results,
        economic_summary=economic_summary,
        reward_objective_cost=reward_objective_cost,
        input_data={
            "buy_price": buy_price,
            "sell_price": sell_price,
            "home_consumption": home_consumption,
            "solar_production": solar_production,
            "initial_soe": initial_soe,
            "initial_cost_basis": initial_cost_basis,
            "horizon": horizon,
        },
    )
