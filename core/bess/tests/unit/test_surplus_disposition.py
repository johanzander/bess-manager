"""Characterization + target behaviour for binary solar-surplus disposition.
Issue #145. Tests in the CURRENT section document today's behaviour and will be
updated to the target behaviour in Task 2/3 (the change is intentional)."""

from core.bess.dp_battery_algorithm import _compute_reward, _state_transition
from core.bess.models import EnergyData
from core.bess.tests.helpers import make_battery_settings

DT = 0.25
PRICES_BUY = [1.0]
PRICES_SELL = [0.8]


def test_idle_exports_surplus_and_holds_battery():
    """TARGET: idle (power=0) is the EXPORT disposition — surplus is exported,
    battery holds (does NOT passively store)."""
    bs = make_battery_settings(max_charge_power_kw=10.0)
    next_soe = _state_transition(
        5.0, 0.0, bs, DT, solar_production=1.5, home_consumption=0.1
    )
    assert next_soe == 5.0  # battery holds; surplus exported, not stored

    reward, _ = _compute_reward(
        power=0.0,
        soe=5.0,
        next_soe=5.0,
        period=0,
        home_consumption=0.1,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=1.5,
        cost_basis=bs.cycle_cost_per_kwh,
    )
    # surplus 1.4 kWh exported @ 0.8 → reward = +1.4*0.8 = 1.12 (cost = -1.12)
    assert round(reward, 4) == round(1.4 * 0.8, 4)


def test_charge_stores_all_surplus_not_a_fraction():
    """TARGET: a charge action is the STORE disposition — it stores ALL surplus
    (up to rate/room), exporting only genuine excess, regardless of the action's
    magnitude. So a tiny charge action still stores all surplus."""
    bs = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    # surplus 1.4 kWh, rate_throughput = 2.5 kWh, plenty of room -> store all 1.4
    next_soe = _state_transition(
        5.0, 0.4, bs, DT, solar_production=1.5, home_consumption=0.1
    )
    assert round(next_soe - 5.0, 4) == 1.4  # stored all surplus, not 0.4*0.25

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
    # surplus all stored, 0 exported; only wear cost = 1.4 * cycle_cost
    # reward = -(0 import - 0 export + 1.4*cycle_cost)
    assert round(reward, 4) == round(-(1.4 * bs.cycle_cost_per_kwh), 4)


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
    assert round(pd.energy.battery_charged, 4) == 1.4  # stored all surplus
    assert round(pd.energy.grid_exported, 4) == 0.0  # nothing exported


# ---------------------------------------------------------------------------
# Task 4a: EXPORT disposition classifies as BATTERY_EXPORT (not IDLE)
# ---------------------------------------------------------------------------


def test_idle_with_surplus_classifies_as_export_arbitrage():
    from core.bess.decision_intelligence import classify_strategic_intent

    # power 0, surplus exported, battery holds
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
    assert classify_strategic_intent(0.0, ed) == "BATTERY_EXPORT"
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


def test_export_arbitrage_maps_to_grid_first_hold():
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


def test_store_with_surplus_no_grid_top_up():
    """TARGET (#145): when surplus > 0 a STORE action may NOT draw from the grid.

    Scenario: solar=2.0, home=1.5 → surplus=0.5 kWh.
    power=4.0 kW, dt=0.25 → power*dt=1.0 kWh > surplus.
    The algorithm must store ONLY the 0.5 kWh solar surplus; grid_imported must be 0.
    (Previously the code computed grid_to_battery = power*dt - surplus = 0.5 kWh,
    which hardware cannot do in load_first/solar-storage mode.)
    """
    from core.bess.dp_battery_algorithm import _build_period_data, _state_transition

    bs = make_battery_settings(max_charge_power_kw=10.0, efficiency_charge=1.0)
    solar_production = 2.0
    home_consumption = 1.5  # surplus = 0.5 kWh
    power = 4.0  # power*dt = 1.0 kWh > surplus

    next_soe = _state_transition(
        5.0,
        power,
        bs,
        DT,
        solar_production=solar_production,
        home_consumption=home_consumption,
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

    # Only solar surplus should be stored — no grid draw when surplus is present
    assert (
        pd.energy.grid_imported == 0.0
    ), f"Expected grid_imported=0 (solar-only charging) but got {pd.energy.grid_imported}"
    # The stored amount is exactly the solar surplus
    assert (
        round(pd.energy.battery_charged, 4) == 0.5
    ), f"Expected battery_charged=0.5 (surplus only) but got {pd.energy.battery_charged}"


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


def test_small_surplus_at_idle_classifies_as_export_arbitrage():
    """A power-0 period with even a SMALL exportable surplus must classify as
    BATTERY_EXPORT (grid_first), not IDLE — otherwise IDLE->load_first stores
    it instead of exporting (#145 residual). Threshold must catch ~0.1 kWh."""
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
    assert classify_strategic_intent(0.0, ed) == "BATTERY_EXPORT"
