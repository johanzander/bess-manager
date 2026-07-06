"""Characterization + target behaviour for binary solar-surplus disposition.
Issue #145. Tests in the CURRENT section document today's behaviour and will be
updated to the target behaviour in Task 2/3 (the change is intentional)."""

from core.bess.dp_battery_algorithm import _compute_reward, _state_transition
from core.bess.models import EnergyData
from core.bess.tests.helpers import make_battery_settings

DT = 0.25
PRICES_BUY = [1.0]
PRICES_SELL = [0.8]


def test_idle_passively_charges_from_solar_surplus():
    """idle (power=0) mirrors load_first hardware: surplus charges the battery
    passively up to max_charge_rate/room; only overflow exports to grid."""
    bs = make_battery_settings(max_charge_power_kw=10.0)
    # surplus = 1.5 - 0.1 = 1.4 kWh; rate_throughput = 10*0.25 = 2.5 kWh; all fits
    next_soe = _state_transition(
        5.0, 0.0, bs, DT, solar_production=1.5, home_consumption=0.1
    )
    expected_stored = 1.4 * bs.efficiency_charge  # 1.4 * 0.97 = 1.358
    assert round(next_soe - 5.0, 4) == round(expected_stored, 4)

    reward, _ = _compute_reward(
        power=0.0,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=0.1,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=1.5,
        cost_basis=bs.cycle_cost_per_kwh,
    )
    # all surplus stored, grid_exported = 0; cost = battery_wear_cost only
    battery_wear = expected_stored * bs.cycle_cost_per_kwh
    assert round(reward, 4) == round(-battery_wear, 4)


def test_idle_exports_when_battery_full():
    """idle (power=0) with a full battery: no passive charging possible,
    all surplus exports to grid — SOLAR_EXPORT semantics."""
    bs = make_battery_settings(max_charge_power_kw=10.0)
    full_soe = bs.max_soe_kwh  # 20.0 kWh
    next_soe = _state_transition(
        full_soe, 0.0, bs, DT, solar_production=1.5, home_consumption=0.1
    )
    assert next_soe == full_soe  # battery full, cannot charge

    reward, _ = _compute_reward(
        power=0.0,
        soe=full_soe,
        next_soe=full_soe,
        period=0,
        home_consumption=0.1,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=1.5,
        cost_basis=bs.cycle_cost_per_kwh,
    )
    # surplus 1.4 kWh exported at sell_price → reward = +1.4*0.8
    assert round(reward, 4) == round(1.4 * 0.8, 4)


def test_store_action_charges_at_max_rate_solar_plus_grid():
    """TARGET: a STORE action charges at MAX rate — solar fills first, grid tops up.

    Renamed from test_charge_stores_all_surplus_not_a_fraction after the 2026-06-27
    fix that allows simultaneous solar+grid charging during surplus hours.

    Scenario: solar=1.5, home=0.1 → surplus=1.4 kWh. rate_throughput=2.5 kWh.
    Solar covers 1.4 kWh; grid covers the remaining 1.1 kWh.
    power magnitude (0.4) is still ignored — any positive power = STORE at max rate.
    """
    bs = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    next_soe = _state_transition(
        5.0, 0.4, bs, DT, solar_production=1.5, home_consumption=0.1
    )
    # Solar covers 1.4 kWh, grid covers 1.1 kWh → total = 2.5 kWh stored (rate-limited)
    assert round(next_soe - 5.0, 4) == 2.5, (
        f"Expected STORE at max rate (2.5 kWh = solar 1.4 + grid 1.1) "
        f"but got {next_soe - 5.0:.4f} kWh"
    )

    reward, _ = _compute_reward(
        power=0.4,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=0.1,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=1.5,
        cost_basis=bs.cycle_cost_per_kwh,
    )
    # grid_to_battery=1.1 kWh at buy_price=1.0; wear=2.5*cycle_cost; export=0
    # total_cost = 1.1*1.0 + 2.5*cycle_cost_per_kwh
    expected_cost = 1.1 * PRICES_BUY[0] + 2.5 * bs.cycle_cost_per_kwh
    assert round(reward, 4) == round(
        -expected_cost, 4
    ), f"Expected reward={-expected_cost:.4f} but got {reward:.4f}"


def test_build_period_data_store_disposition_flows():
    from core.bess.dp_battery_algorithm import _build_period_data, _state_transition

    bs = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    nxt = _state_transition(
        5.0, 0.4, bs, DT, solar_production=1.5, home_consumption=0.1
    )
    pd = _build_period_data(
        power=0.4,
        soe=5.0,
        next_soe=nxt,
        period=0,
        home_consumption=0.1,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=1.5,
        new_cost_basis=bs.cycle_cost_per_kwh,
        currency="SEK",
    )
    # After fix: solar covers 1.4 kWh, grid covers 1.1 kWh → max rate 2.5 kWh stored
    assert (
        round(pd.energy.battery_charged, 4) == 2.5
    ), f"Expected battery_charged=2.5 (solar 1.4 + grid 1.1) but got {pd.energy.battery_charged:.4f}"
    assert (
        round(pd.energy.grid_exported, 4) == 0.0
    ), f"Expected grid_exported=0 but got {pd.energy.grid_exported:.4f}"
    assert (
        round(pd.energy.grid_imported, 4) == 1.1
    ), f"Expected grid_imported=1.1 (grid top-up) but got {pd.energy.grid_imported:.4f}"


# ---------------------------------------------------------------------------
# Task 4a: EXPORT disposition classifies as SOLAR_EXPORT (not BATTERY_EXPORT or IDLE)
# ---------------------------------------------------------------------------


def test_idle_with_solar_surplus_classifies_as_solar_export():
    from core.bess.decision_intelligence import classify_strategic_intent

    # power 0, battery full (no passive charging), surplus exported → SOLAR_EXPORT
    ed = EnergyData(
        solar_production=1.5,
        home_consumption=0.1,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=1.4,
        battery_soe_start=5.0,
        battery_soe_end=5.0,
    )
    assert classify_strategic_intent(0.0, ed) == "SOLAR_EXPORT"
    ed2 = EnergyData(
        solar_production=0.1,
        home_consumption=0.1,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.0,
        battery_soe_start=5.0,
        battery_soe_end=5.0,
    )
    assert classify_strategic_intent(0.0, ed2) == "IDLE"


# ---------------------------------------------------------------------------
# Task 4b: BATTERY_EXPORT maps to grid_first + hold (no discharge)
# ---------------------------------------------------------------------------


def test_battery_export_maps_to_grid_first_hold():
    from core.bess.inverter_controller import InverterController
    from core.bess.simulation.inverter_simulator import derive_control_command

    bs = make_battery_settings()
    assert InverterController.INTENT_TO_MODE["BATTERY_EXPORT"] == "grid_first"
    cmd = derive_control_command("BATTERY_EXPORT", battery_action_kw=0.0, settings=bs)
    assert cmd.battery_mode == "grid_first"
    assert cmd.grid_charge is False
    assert cmd.discharge_rate_pct == 0


# ---------------------------------------------------------------------------
# Task: SOLAR_STORAGE charges from solar only — no grid top-up when surplus
# ---------------------------------------------------------------------------


def test_store_with_surplus_draws_grid_to_fill_remaining_rate():
    """After 2026-06-27 fix: STORE action during solar surplus charges at MAX rate.
    Solar fills first; grid covers remaining capacity up to max charge rate.

    This replaced test_store_with_surplus_no_grid_top_up which encoded the old
    SOLAR_STORAGE-only constraint (grid_to_battery=0 when surplus>0). The old
    constraint prevented the optimizer from using cheap solar-surplus hours for
    grid arbitrage, causing it to charge at more expensive no-surplus hours.

    Scenario: solar=2.0, home=1.5 → surplus=0.5 kWh. rate_throughput=2.5 kWh.
    Solar covers 0.5 kWh; grid draws 2.0 kWh; total charged = 2.5 kWh.
    """
    from core.bess.dp_battery_algorithm import _build_period_data, _state_transition

    bs = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    solar_production = 2.0
    home_consumption = 1.5  # surplus = 0.5 kWh
    power = 4.0  # any positive value → STORE at max rate

    next_soe = _state_transition(
        5.0,
        power,
        bs,
        DT,
        solar_production=solar_production,
        home_consumption=home_consumption,
    )

    # After fix: solar 0.5 + grid 2.0 = 2.5 kWh total (rate-limited)
    assert round(next_soe - 5.0, 4) == 2.5, (
        f"Expected STORE at max rate (2.5 kWh) but got {next_soe - 5.0:.4f}. "
        f"Surplus gate may still be blocking grid charging."
    )

    pd = _build_period_data(
        power=power,
        soe=5.0,
        next_soe=next_soe,
        period=0,
        home_consumption=home_consumption,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=solar_production,
        new_cost_basis=bs.cycle_cost_per_kwh,
        currency="SEK",
    )

    # Grid draws 2.0 kWh to top up the remaining capacity after solar
    assert (
        round(pd.energy.grid_imported, 4) == 2.0
    ), f"Expected grid_imported=2.0 (grid top-up) but got {pd.energy.grid_imported:.4f}"
    assert (
        round(pd.energy.battery_charged, 4) == 2.5
    ), f"Expected battery_charged=2.5 but got {pd.energy.battery_charged:.4f}"


# ---------------------------------------------------------------------------
# Task: GRID_CHARGING charges at max rate (binary, mirrors solar fix)
# ---------------------------------------------------------------------------


def test_grid_charging_charges_at_max_rate_not_fractional():
    """TARGET (#145): a charge action with NO solar surplus (grid-charging case)
    must charge at MAX rate (remaining_rate = min(rate_throughput, room_throughput)),
    NOT at the fractional power*dt that the DP planned.

    Hardware: GRID_CHARGING → battery_first charges at MAX rate regardless of the
    planned action magnitude.

    Scenario: solar=0, home=0 → no surplus. power=0.4 kW (small planned action).
    max_charge_power_kw=10, dt=0.25 → max charge = 2.5 kWh.
    Starting at soe=2.0 with max_soe=20.0 → room=18.0, room_throughput=18.0.
    Expected: next_soe - soe == min(10*0.25, 18.0) == 2.5, NOT 0.4*0.25 == 0.1.
    """
    bs = make_battery_settings(
        total_capacity=20.0,
        min_soc=0.0,
        max_soc=100.0,
        max_charge_power_kw=10.0,
        efficiency_charge=1.0,
    )
    soe = 2.0
    next_soe = _state_transition(
        soe, 0.4, bs, DT, solar_production=0.0, home_consumption=0.0
    )
    expected_delta = min(10.0 * DT, bs.max_soe_kwh - soe)  # 2.5 kWh (rate limited)
    assert round(next_soe - soe, 6) == round(expected_delta, 6), (
        f"Expected grid-charge at max rate ({expected_delta} kWh) "
        f"but got {next_soe - soe} kWh (= power*dt = 0.4*0.25 = 0.1 kWh)"
    )


def test_grid_charging_action_reports_achieved_throughput_not_tied_power():
    """Regression for #203: decision.battery_action must reflect the achieved
    charge throughput, not the arbitrary tested `power` that won the DP's
    tie-break among physically-identical positive STORE levels.

    _state_transition's STORE physics are binary (see
    test_grid_charging_charges_at_max_rate_not_fractional above): any positive
    power charges at the same max rate_throughput. The real DP's power_levels
    are iterated ascending with a strict `>` update, so the smallest positive
    level (POWER_STEP_KW = 0.2 kW) always wins as best_action — but that tiny
    tested value must not leak into decision.battery_action, since it drives
    the inverter's charge_rate register via get_period_settings().

    Scenario mirrors test_grid_charging_charges_at_max_rate_not_fractional:
    no solar, power=0.2 kW (the smallest positive power_level). Expected
    battery_action = 2.5 kWh (max-rate achieved charge), not 0.2*0.25=0.05 kWh.
    """
    from core.bess.dp_battery_algorithm import _build_period_data, _state_transition

    bs = make_battery_settings(
        total_capacity=20.0,
        min_soc=0.0,
        max_soc=100.0,
        max_charge_power_kw=10.0,
        efficiency_charge=1.0,
    )
    soe = 2.0
    tied_power = 0.2  # smallest positive power_level — always wins the DP tie-break
    next_soe = _state_transition(
        soe, tied_power, bs, DT, solar_production=0.0, home_consumption=0.0
    )
    pd = _build_period_data(
        power=tied_power,
        soe=soe,
        next_soe=next_soe,
        period=0,
        home_consumption=0.0,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=0.0,
        new_cost_basis=bs.cycle_cost_per_kwh,
        currency="SEK",
    )
    expected_action = min(bs.max_charge_power_kw * DT, bs.max_soe_kwh - soe)  # 2.5 kWh
    assert round(pd.decision.battery_action, 4) == round(expected_action, 4), (
        f"Expected battery_action={expected_action} (achieved max-rate charge) "
        f"but got {pd.decision.battery_action:.4f} "
        f"(leaked tested power={tied_power}*{DT}={tied_power * DT})"
    )
    assert pd.decision.strategic_intent == "GRID_CHARGING"


def test_small_solar_surplus_at_idle_classifies_as_solar_export():
    """A power-0 period with solar surplus classifies as SOLAR_EXPORT (load_first).
    grid_first is only for active battery discharge — idle periods must use
    load_first so the battery can support house load when solar is insufficient."""
    from core.bess.decision_intelligence import classify_strategic_intent

    ed = EnergyData(
        solar_production=0.3,
        home_consumption=0.2,
        battery_charged=0.0,
        battery_discharged=0.0,
        grid_imported=0.0,
        grid_exported=0.1,
        battery_soe_start=5.0,
        battery_soe_end=5.0,
    )
    assert classify_strategic_intent(0.0, ed) == "SOLAR_EXPORT"


def test_solar_export_maps_to_load_first():
    from core.bess.inverter_controller import InverterController
    from core.bess.simulation.inverter_simulator import derive_control_command

    bs = make_battery_settings()
    assert InverterController.INTENT_TO_MODE["SOLAR_EXPORT"] == "load_first"
    cmd = derive_control_command("SOLAR_EXPORT", battery_action_kw=0.0, settings=bs)
    assert cmd.battery_mode == "load_first"
    assert cmd.grid_charge is False
    assert cmd.discharge_rate_pct == 0


def test_battery_export_active_discharge_still_grid_first():
    """BATTERY_EXPORT with real discharge action → grid_first + action-derived rate."""
    from core.bess.simulation.inverter_simulator import derive_control_command

    bs = make_battery_settings()
    cmd = derive_control_command("BATTERY_EXPORT", battery_action_kw=-5.0, settings=bs)
    assert cmd.battery_mode == "grid_first"
    assert cmd.discharge_rate_pct == 50
    assert cmd.grid_charge is False


# ---------------------------------------------------------------------------
# Issue #204: anti-cycling discharge gate over-values stored energy when
# solar already covers all home load (no grid purchase to displace)
# ---------------------------------------------------------------------------


def test_discharge_no_longer_blocked_by_cost_basis_floor_issue_204():
    """UPDATED for guardrail removal: Issue #204 used to test that a discharge
    was blocked by the anti-cycling profitability floor when solar covers all
    home load and buy_price > sell_price. With the profitability floor removed,
    the discharge is no longer blocked but is still evaluated by the DP's
    value function (IDLE can still be chosen if it's better). Discharge with
    finite reward is now the expected behavior."""
    bs = make_battery_settings()
    buy_price = [1.0568]
    sell_price = [0.46126]
    cost_basis = 0.6219
    soe = bs.max_soe_kwh  # battery full
    power = -0.4  # discharge power that yields the reported 0.1 kWh action

    next_soe = _state_transition(
        soe, power, bs, DT, solar_production=0.893, home_consumption=0.155
    )

    reward, _ = _compute_reward(
        power=power,
        soe=soe,
        next_soe=next_soe,
        period=0,
        home_consumption=0.155,
        battery_settings=bs,
        dt=DT,
        buy_price=buy_price,
        sell_price=sell_price,
        solar_production=0.893,
        cost_basis=cost_basis,
    )
    assert reward != float("-inf"), (
        f"Discharge should no longer be blocked by profitability floor "
        f"(that guardrail was removed). Got reward={reward}"
    )


def test_small_discharge_still_evaluated_without_profitability_floor():
    """UPDATED for guardrail removal: same solar-covers-load scenario as above
    but with a smaller discharge action (0.05 kWh) whose capacity_after_discharge
    falls below SOE_STEP_KWH. With the profitability floor removed, even small
    actions with limited capacity are no longer blocked — they're evaluated by
    the DP and IDLE can be chosen if it's better."""
    bs = make_battery_settings()
    buy_price = [1.0568]
    sell_price = [0.46126]
    cost_basis = 0.6219
    soe = bs.max_soe_kwh
    power = -0.2  # half the reported action size

    next_soe = _state_transition(
        soe, power, bs, DT, solar_production=0.893, home_consumption=0.155
    )
    capacity_after_discharge = bs.max_soe_kwh - next_soe
    assert (
        capacity_after_discharge < 0.1
    )  # confirms this is the smaller-action edge case

    reward, _ = _compute_reward(
        power=power,
        soe=soe,
        next_soe=next_soe,
        period=0,
        home_consumption=0.155,
        battery_settings=bs,
        dt=DT,
        buy_price=buy_price,
        sell_price=sell_price,
        solar_production=0.893,
        cost_basis=cost_basis,
    )
    assert reward != float(
        "-inf"
    ), f"Discharge should no longer be blocked by profitability floor. Got reward={reward}"


def test_discharge_not_blocked_when_solar_does_not_cover_load():
    """Regression guard: when solar does NOT cover home load, there IS a real
    grid purchase to avoid, so avoid_purchase_value must remain in the max()
    and a genuinely profitable discharge must not be blocked."""
    bs = make_battery_settings()
    buy_price = [1.0568]
    sell_price = [0.46126]
    cost_basis = 0.5  # below avoid_purchase_value, discharge is profitable
    soe = bs.max_soe_kwh
    power = -0.4
    solar_production = 0.1
    home_consumption = 1.0  # exceeds solar, no excess solar

    next_soe = _state_transition(
        soe,
        power,
        bs,
        DT,
        solar_production=solar_production,
        home_consumption=home_consumption,
    )

    reward, _ = _compute_reward(
        power=power,
        soe=soe,
        next_soe=next_soe,
        period=0,
        home_consumption=home_consumption,
        battery_settings=bs,
        dt=DT,
        buy_price=buy_price,
        sell_price=sell_price,
        solar_production=solar_production,
        cost_basis=cost_basis,
    )
    assert reward != float(
        "-inf"
    ), "Expected discharge NOT blocked (real grid purchase avoided) but got -inf"
