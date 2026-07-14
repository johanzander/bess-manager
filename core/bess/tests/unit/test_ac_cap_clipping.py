"""Inverter AC output cap: solar-clipping-aware optimization.

A DC-coupled hybrid inverter (e.g. Growatt MIN 5000TL-XH) caps total AC
output; PV above the cap can only be captured by charging the battery
DC-side, and only while the battery has room. With
``inverter_max_ac_power_kw`` set, the optimizer must value clipped solar at
zero (so a full battery under high solar is genuinely costly) and use the
SOLAR_EXPORT-below-max bypass (#313) — deliberately skip passive absorption —
to preserve headroom for the above-cap window.

Feature-off (``inverter_max_ac_power_kw = 0``) behavior must be unchanged.
"""

import copy
import json
from pathlib import Path

import pytest

from core.bess.decision_intelligence import classify_strategic_intent
from core.bess.dp_battery_algorithm import (
    _ac_flows,
    _build_period_data,
    _compute_reward,
    _discharge_candidates,
    _effective_ac_cap_kwh,
    _state_transition,
)
from core.bess.simulation.inverter_simulator import (
    derive_control_command,
    simulate,
)
from core.bess.tests.helpers import (
    _scenario_inputs,
    make_battery_settings,
    run_scenario,
    run_scenario_realized,
)

DT = 0.25
PRICES_BUY = [1.0]
PRICES_SELL = [0.8]


def make_capped_settings(**overrides):
    defaults = {"inverter_max_ac_power_kw": 5.0, "inverter_ac_power_margin": 0.0}
    defaults.update(overrides)
    return make_battery_settings(**defaults)


# ---------------------------------------------------------------------------
# Cap math
# ---------------------------------------------------------------------------


def test_effective_ac_cap_disabled_and_margin():
    assert _effective_ac_cap_kwh(make_battery_settings(), DT) is None
    assert _effective_ac_cap_kwh(make_capped_settings(), DT) == 5.0 * DT
    derated = _effective_ac_cap_kwh(
        make_capped_settings(inverter_ac_power_margin=0.2), DT
    )
    assert derated == pytest.approx(5.0 * 0.8 * DT)


def test_ac_flows_unconstrained_matches_energy_balance():
    grid_imported, grid_exported, clipped = _ac_flows(1.75, 0.15, 0.5, 0.0, None)
    assert clipped == 0.0
    assert grid_imported == 0.0
    assert grid_exported == pytest.approx(1.75 - 0.5 - 0.15)


def test_ac_flows_clips_solar_above_cap():
    cap_kwh = 5.0 * DT  # 1.25
    grid_imported, grid_exported, clipped = _ac_flows(1.75, 0.15, 0.0, 0.0, cap_kwh)
    assert clipped == pytest.approx(0.5)
    assert grid_exported == pytest.approx(cap_kwh - 0.15)
    assert grid_imported == 0.0


def test_ac_flows_dc_charging_bypasses_cap():
    # Storing 0.5 kWh DC-side leaves exactly the cap's worth on the AC stage.
    cap_kwh = 5.0 * DT
    _grid_imported, grid_exported, clipped = _ac_flows(1.75, 0.15, 0.5, 0.0, cap_kwh)
    assert clipped == 0.0
    assert grid_exported == pytest.approx(1.25 - 0.15)


# ---------------------------------------------------------------------------
# Dispositions under the cap
# ---------------------------------------------------------------------------


def test_idle_full_battery_clips_above_cap():
    """A full battery under 7 kW solar loses everything above the AC cap."""
    bs = make_capped_settings()
    full = bs.max_soe_kwh
    next_soe = _state_transition(
        full, 0.0, bs, DT, solar_production=1.75, home_consumption=0.15
    )
    assert next_soe == full

    pd = _build_period_data(
        power=0.0,
        soe=full,
        next_soe=next_soe,
        period=0,
        home_consumption=0.15,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=1.75,
        new_cost_basis=bs.cycle_cost_per_kwh,
        currency="SEK",
    )
    assert pd.energy.clipped_solar == pytest.approx(0.5)
    assert pd.energy.grid_exported == pytest.approx(1.25 - 0.15)
    assert pd.energy.solar_to_grid == pytest.approx(1.25 - 0.15)


def test_reward_full_battery_loses_clipped_export_credit():
    """The DP must see less export revenue when the cap clips the surplus —
    this is what makes early filling economically wrong."""
    capped = make_capped_settings()
    uncapped = make_battery_settings()
    full = capped.max_soe_kwh

    def idle_reward(bs):
        next_soe = _state_transition(
            full, 0.0, bs, DT, solar_production=1.75, home_consumption=0.15
        )
        reward, _ = _compute_reward(
            power=0.0,
            soe=full,
            next_soe=next_soe,
            period=0,
            home_consumption=0.15,
            battery_settings=bs,
            dt=DT,
            buy_price=PRICES_BUY,
            sell_price=PRICES_SELL,
            solar_production=1.75,
            cost_basis=bs.cycle_cost_per_kwh,
        )
        return reward

    assert idle_reward(capped) == pytest.approx(
        idle_reward(uncapped) - 0.5 * PRICES_SELL[0]
    )


def test_idle_cost_basis_discounts_clipped_absorption():
    """Passive IDLE absorption under clipping must get the same cost-basis
    discount STORE does: energy that would have been clipped anyway is free,
    so only the export actually displaced is charged against cost basis."""
    capped = make_capped_settings()
    uncapped = make_battery_settings()
    soe = 5.0
    solar, home = 1.75, 0.15  # 7 kW solar vs 5 kW cap -> 0.5 kWh would clip

    def idle_cost_basis(bs):
        next_soe = _state_transition(
            soe, 0.0, bs, DT, solar_production=solar, home_consumption=home
        )
        # Battery absorbs the full 1.6 kWh surplus in both cases (rate/room
        # are not binding), so the physical transition is identical.
        assert next_soe == pytest.approx(soe + 1.6 * bs.efficiency_charge)
        _, new_cost_basis = _compute_reward(
            power=0.0,
            soe=soe,
            next_soe=next_soe,
            period=0,
            home_consumption=home,
            battery_settings=bs,
            dt=DT,
            buy_price=PRICES_BUY,
            sell_price=PRICES_SELL,
            solar_production=solar,
            cost_basis=bs.cycle_cost_per_kwh,
        )
        return new_cost_basis, next_soe

    basis_capped, next_soe = idle_cost_basis(capped)
    basis_uncapped, _ = idle_cost_basis(uncapped)
    # Uncapped: all 1.6 kWh absorbed displaces export. Capped: only 1.1 kWh
    # (cap 1.25 minus 0.15 home) was exportable -- the 0.5 kWh that would
    # have clipped must not be charged against cost basis.
    assert basis_capped == pytest.approx(
        basis_uncapped - 0.5 * PRICES_SELL[0] / next_soe
    )


def test_bypass_preserves_soe_and_classifies_as_solar_export():
    """The SOLAR_EXPORT-below-max bypass (#313) — next_soe forced equal to
    soe — is what lets the cap-aware plan defer passive absorption."""
    bs = make_capped_settings()
    soe = 5.0

    pd = _build_period_data(
        power=0.0,
        soe=soe,
        next_soe=soe,
        period=0,
        home_consumption=0.15,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=1.0,
        new_cost_basis=bs.cycle_cost_per_kwh,
        currency="SEK",
    )
    assert pd.energy.battery_charged == 0.0
    assert pd.energy.clipped_solar == 0.0  # 4 kW is below the 5 kW cap
    assert pd.energy.grid_exported == pytest.approx(1.0 - 0.15)
    assert classify_strategic_intent(0.0, pd.energy) == "SOLAR_EXPORT"


def test_store_absorbs_above_cap_overflow_dc_side():
    """Actively charging at the peak keeps the residual under the cap —
    nothing clips while the battery has rate and room."""
    bs = make_capped_settings(max_charge_power_kw=5.0)
    soe = 2.0
    next_soe = _state_transition(
        soe, 5.0, bs, DT, solar_production=1.75, home_consumption=0.15
    )
    pd = _build_period_data(
        power=5.0,
        soe=soe,
        next_soe=next_soe,
        period=0,
        home_consumption=0.15,
        battery_settings=bs,
        dt=DT,
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        solar_production=1.75,
        new_cost_basis=bs.cycle_cost_per_kwh,
        currency="SEK",
    )
    assert pd.energy.clipped_solar == 0.0
    assert pd.energy.solar_to_battery == pytest.approx(1.25)  # rate-limited
    assert pd.energy.grid_to_battery == 0.0


def test_discharge_candidates_respect_ac_headroom():
    bs = make_capped_settings()
    cap_kwh = 5.0 * DT

    # Solar at/above the cap: no AC headroom left for battery discharge.
    assert (
        _discharge_candidates(
            10.0,
            bs,
            DT,
            home_consumption=0.15,
            solar_production=1.75,
            ac_cap_kwh=cap_kwh,
        )
        == []
    )

    # 3 kW solar leaves 2 kW of headroom.
    candidates = _discharge_candidates(
        10.0, bs, DT, home_consumption=0.15, solar_production=0.75, ac_cap_kwh=cap_kwh
    )
    assert candidates
    assert max(candidates) <= (cap_kwh - 0.75) / DT + 1e-9

    # Without the cap the full rate is available.
    uncapped = _discharge_candidates(
        10.0, bs, DT, home_consumption=0.15, solar_production=1.75
    )
    assert max(uncapped) == pytest.approx(bs.max_discharge_power_kw)


# ---------------------------------------------------------------------------
# Apply side (hardware + simulator)
# ---------------------------------------------------------------------------


def test_simulator_solar_export_command_does_not_absorb_surplus():
    bs = make_capped_settings()
    cmd = derive_control_command("SOLAR_EXPORT", 0.0, bs)
    assert cmd.charge_rate_pct == 0

    sim = simulate(
        commands=[cmd],
        solar_production=[1.0],
        home_consumption=[0.15],
        buy_price=PRICES_BUY,
        sell_price=PRICES_SELL,
        initial_soe=5.0,
        settings=bs,
        dt=DT,
    )
    pd = sim.period_data[0]
    assert pd.energy.battery_charged == 0.0
    assert pd.energy.battery_soe_end == 5.0
    assert pd.energy.grid_exported == pytest.approx(1.0 - 0.15)


# ---------------------------------------------------------------------------
# Whole-day behavior (slow)
# ---------------------------------------------------------------------------


def _load_clipping_scenario() -> dict:
    path = Path(__file__).parent / "data" / "synthetic_clear_sky_ac_clipping.json"
    with open(path) as f:
        return json.load(f)


@pytest.mark.slow
def test_clipping_day_defers_charging_and_avoids_clipping():
    """On a 7 kW-peak clear-sky day with a 5 kW AC cap, the plan must keep
    battery headroom until the above-cap window and clip essentially nothing."""
    scenario = _load_clipping_scenario()
    result = run_scenario(scenario)

    total_clipped = sum(pd.energy.clipped_solar for pd in result.period_data)
    cap_kwh = scenario["battery"]["inverter_max_ac_power_kw"] * 0.25
    overflow = sum(max(0.0, s - cap_kwh) for s in scenario["solar_production"])
    assert overflow > 4.0  # the day genuinely has above-cap energy at stake
    assert (
        total_clipped < 0.3
    ), f"plan clips {total_clipped:.2f} kWh of {overflow:.2f} kWh overflow"

    first_above = next(
        i for i, s in enumerate(scenario["solar_production"]) if s > cap_kwh
    )
    max_soe = scenario["battery"]["max_soe_kwh"]
    soe_before_window = result.period_data[first_above - 1].energy.battery_soe_end
    assert soe_before_window <= max_soe - overflow + 0.3, (
        f"battery at {soe_before_window:.2f}/{max_soe} kWh entering the >cap "
        f"window leaves no room for {overflow:.2f} kWh of overflow"
    )

    intents_before_window = {
        pd.decision.strategic_intent for pd in result.period_data[:first_above]
    }
    # deliberate export-instead-of-absorb periods (#313 bypass)
    assert "SOLAR_EXPORT" in intents_before_window


@pytest.mark.slow
def test_feature_off_plan_costs_more_under_cap_reality():
    """Economic proof: executing the cap-blind plan on cap-limited hardware
    costs strictly more than the cap-aware plan."""
    scenario = _load_clipping_scenario()
    _, realized_on = run_scenario_realized(scenario)

    scenario_off = copy.deepcopy(scenario)
    scenario_off["battery"]["inverter_max_ac_power_kw"] = 0.0
    inputs_off = _scenario_inputs(scenario_off)
    from core.bess.dp_battery_algorithm import optimize_battery_schedule

    result_off = optimize_battery_schedule(**inputs_off)
    dt = inputs_off["period_duration_hours"]
    commands_off = [
        derive_control_command(
            pd.decision.strategic_intent,
            pd.decision.battery_action / dt,
            inputs_off["battery_settings"],
        )
        for pd in result_off.period_data
    ]
    # Execute the cap-blind commands against cap-limited reality.
    settings_on = _scenario_inputs(scenario)["battery_settings"]
    sim_off = simulate(
        commands_off,
        inputs_off["solar_production"],
        inputs_off["home_consumption"],
        inputs_off["buy_price"],
        inputs_off["sell_price"],
        inputs_off["initial_soe"],
        settings_on,
        dt,
    )

    # Both plans end the day with a full battery, so the value of avoided
    # clipping is the daytime export price on the recovered energy — a real
    # but modest margin.
    assert realized_on < sim_off.realized_cost - 0.3, (
        f"cap-aware plan should beat the cap-blind plan under clipping "
        f"reality: on={realized_on:.2f}, off={sim_off.realized_cost:.2f}"
    )

    # Hardware-default counterfactual (the user-reported failure mode): pure
    # load_first passive absorption fills the battery before the above-cap
    # window and clips most of the overflow.
    idle_commands = [
        derive_control_command("IDLE", 0.0, settings_on)
        for _ in range(len(commands_off))
    ]
    sim_idle = simulate(
        idle_commands,
        inputs_off["solar_production"],
        inputs_off["home_consumption"],
        inputs_off["buy_price"],
        inputs_off["sell_price"],
        inputs_off["initial_soe"],
        settings_on,
        dt,
    )
    clipped_idle = sum(pd.energy.clipped_solar for pd in sim_idle.period_data)
    assert clipped_idle > 3.0, (
        f"passive-absorption baseline should clip most of the overflow, "
        f"got {clipped_idle:.2f} kWh"
    )
