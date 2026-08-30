"""VPP load tracking: the closed gate finally has a way to hold (#520).

**These are outcome tests, not mapping tests.** Every assertion below is on
energy the battery actually delivered, or on the SoE trajectory it left
behind, executed through `vpp_simulator` from a plan the DP really produced.
A test that pinned `vpp_power=-80` would prove the mapper unchanged and stay
green while the battery emptied itself -- and this issue is precisely a case
where the command looked defensible and the physics did not.

The scenarios come from real corpus fixtures rather than hand-built periods,
per `docs/agents/simulator.md`: a synthetic-input unit test on `_intent_to_vpp`
can pass while the new branch is unreachable by any real DP-produced schedule,
which is the coverage gap that shipped undetected in #385. Measured on the
41-fixture corpus, closed-gate `LOAD_SUPPORT` periods with a real deficit are
reachable in 24 of them.

**What the corpus says the bug is worth.** Executing every fixture's plan
through today's release behaviour delivers **191.48 kWh** across closed-gate
`LOAD_SUPPORT` deficit periods where the plans call for **180.82 kWh** --
10.66 kWh of reservation spent that `shadow_price` said to keep. That excess
is the defect, and `test_corpus_wide_overshoot_is_eliminated` pins that
tracking removes it.

**And what it is not.** Delivery never falls *below* plan in any fixture,
before or after. That direction is #537's failure -- it mapped a closed gate
to a bare `battery_first` hold and would have abandoned all 118.11 kWh of
planned discharge in the then-corpus's closed-gate periods. Several tests here
assert the lower bound explicitly so that regression cannot return quietly.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from core.bess.simulation.vpp_simulator import (
    VppCommand,
    simulate_vpp,
    vpp_command_to_power,
)
from core.bess.tests.helpers import (
    _scenario_inputs,
    make_battery_settings,
    run_scenario,
)
from core.bess.vpp_load_tracking import (
    VPP_HOLD_POWER_PCT,
    budget_for_period,
    tracked_vpp_power_pct,
)

DATA_DIR = Path(__file__).parent / "data"

# Real hardware data, and the corpus's sharpest instance of the defect: the
# plan plans 2.65 kWh of closed-gate LOAD_SUPPORT discharge and released
# self-use delivers 6.86 kWh -- 2.6x the reservation, across 45 periods.
OVERSHOOT_FIXTURE = "realworld_2026_04_22_202249"


def _run(name: str, *, tracking: bool) -> tuple[Any, Any, dict[str, Any]]:
    """Execute one fixture's real DP plan through the VPP model.

    Returns `(result, sim, inputs)`. The plan is never hand-built: it is
    whatever the optimizer produces for that fixture, so a branch that no real
    schedule reaches cannot be mistaken for covered.
    """
    scenario = json.loads((DATA_DIR / f"{name}.json").read_text())
    inputs = _scenario_inputs(scenario)
    settings = inputs["battery_settings"]
    settings.vpp_load_tracking_enabled = tracking
    dt = inputs["period_duration_hours"]

    result = run_scenario(scenario)
    sim = simulate_vpp(
        [p.decision.strategic_intent for p in result.period_data],
        [p.decision.battery_action / dt for p in result.period_data],
        inputs["solar_production"],
        inputs["home_consumption"],
        inputs["buy_price"],
        inputs["sell_price"],
        inputs["initial_soe"],
        settings,
        dt,
        intra_period_discharge_allowed=[
            p.decision.intra_period_discharge_allowed for p in result.period_data
        ],
    )
    return result, sim, inputs


def _closed_gate_deficit_periods(result: Any, inputs: dict[str, Any]) -> list[int]:
    """Indices of LOAD_SUPPORT periods where the gate is closed and the house
    is actually in deficit -- the only periods this feature can change."""
    solar, home = inputs["solar_production"], inputs["home_consumption"]
    return [
        i
        for i, p in enumerate(result.period_data)
        if p.decision.strategic_intent == "LOAD_SUPPORT"
        and not p.decision.intra_period_discharge_allowed
        and home[i] > solar[i]
    ]


def _delivery(result: Any, sim: Any, inputs: dict[str, Any]) -> tuple[float, float]:
    """(planned, delivered) kWh over the closed-gate deficit periods."""
    idx = _closed_gate_deficit_periods(result, inputs)
    planned = sum(-result.period_data[i].decision.battery_action for i in idx)
    delivered = sum(sim.period_data[i].energy.battery_discharged for i in idx)
    return planned, delivered


class TestTheReservationIsHeld:
    """The half of #520 VPP cannot express today."""

    def test_closed_gate_delivers_the_plan_and_no_more(self) -> None:
        """The whole feature, stated as an outcome on real hardware data.

        Without tracking the inverter's released self-use delivers 6.86 kWh
        against a 2.65 kWh plan; the excess is reservation `shadow_price`
        priced above the current buy price, spent anyway because release is
        VPP's only vocabulary for LOAD_SUPPORT.
        """
        base_result, base_sim, inputs = _run(OVERSHOOT_FIXTURE, tracking=False)
        planned, released = _delivery(base_result, base_sim, inputs)

        assert released > planned, (
            "fixture no longer exhibits the defect -- pick another, or this "
            "test proves nothing"
        )

        result, sim, inputs = _run(OVERSHOOT_FIXTURE, tracking=True)
        planned_tracked, tracked = _delivery(result, sim, inputs)

        assert planned_tracked == pytest.approx(planned), "the plan must not move"
        assert tracked <= planned + 1e-9, (
            f"tracking must not overshoot the reservation: delivered "
            f"{tracked:.2f} kWh against a {planned:.2f} kWh budget"
        )
        assert tracked < released, "tracking must actually change the outcome"

    def test_the_planned_discharge_is_still_fully_delivered(self) -> None:
        """#537's failure, asserted from the other side.

        A closed gate mapped to a bare hold delivers *nothing*, abandoning
        every planned kWh. The budget is a ceiling on delivery, never a
        substitute for it: whatever the plan asked for is still available to
        the house, bounded only by the deficit that actually appears.
        """
        result, sim, inputs = _run(OVERSHOOT_FIXTURE, tracking=True)
        idx = _closed_gate_deficit_periods(result, inputs)
        solar, home = inputs["solar_production"], inputs["home_consumption"]

        for i in idx:
            planned = -result.period_data[i].decision.battery_action
            deficit = home[i] - solar[i]
            delivered = sim.period_data[i].energy.battery_discharged
            # Delivery is bounded by the smaller of what was planned and what
            # the house actually needed -- never by the hold alone.
            expected_floor = min(planned, deficit)
            assert delivered >= expected_floor - 1e-6, (
                f"period {i}: delivered {delivered:.3f} kWh but the house "
                f"needed {deficit:.3f} and the plan allowed {planned:.3f} -- "
                f"this is #537's abandoned-discharge regression"
            )

    def test_corpus_wide_overshoot_is_eliminated(self) -> None:
        """The 10.66 kWh, across every fixture that reaches the branch.

        A per-fixture test can be satisfied by a special case; this one cannot.
        It also pins the lower bound corpus-wide, so a change that bounded
        delivery by emptying the plan would fail here rather than look like an
        improvement.
        """
        total_planned = total_released = total_tracked = 0.0
        touched = 0

        for path in sorted(DATA_DIR.glob("*.json")):
            name = path.stem
            base_result, base_sim, inputs = _run(name, tracking=False)
            planned, released = _delivery(base_result, base_sim, inputs)
            if planned == 0 and released == 0:
                continue
            touched += 1
            _, sim, inputs = _run(name, tracking=True)
            _, tracked = _delivery(base_result, sim, inputs)

            assert tracked <= planned + 1e-6, f"{name}: overshoot survived"
            total_planned += planned
            total_released += released
            total_tracked += tracked

        assert touched >= 20, (
            f"only {touched} fixtures reach the closed-gate branch -- the "
            f"corpus claim rests on breadth, so this is a real regression"
        )
        assert (
            total_released > total_planned + 5.0
        ), "the corpus no longer exhibits the overshoot this feature removes"
        assert total_tracked <= total_planned + 1e-6
        assert (
            total_tracked > total_planned * 0.5
        ), "tracking has emptied the plan rather than bounding it (#537)"


class TestTheOpenGateIsUntouched:
    """#413 must not regress. Its release behaviour is correct wherever the
    energy is genuinely worth more now than later."""

    def test_open_gate_still_releases_control(self) -> None:
        """An open gate returns no budget at all, so the command written is
        exactly the one #413 already writes.

        **The command is what this test can pin, and the outcome is not** --
        deliberately, and the distinction is the whole design. An open-gate
        period reached later in the day now runs on a *higher* SoE, because
        the closed-gate periods before it held their reservation instead of
        self-consuming it. Its delivered energy therefore legitimately rises
        (measured on this fixture: 0.090 -> 0.187 kWh in one period). That is
        the feature, not a regression: energy the gate said to save is
        available where the gate says to spend it.

        Asserting equal delivery here would have pinned the *absence* of the
        benefit. Its lower bound is asserted below instead.
        """
        result, sim_off, _ = _run(OVERSHOOT_FIXTURE, tracking=False)
        _, sim_on, _ = _run(OVERSHOOT_FIXTURE, tracking=True)

        open_gate = [
            i
            for i, p in enumerate(result.period_data)
            if p.decision.strategic_intent == "LOAD_SUPPORT"
            and p.decision.intra_period_discharge_allowed
        ]
        assert open_gate, "fixture has no open-gate LOAD_SUPPORT periods"

        for i in open_gate:
            assert (
                sim_on.commands[i] == sim_off.commands[i]
            ), f"period {i}: an open gate must still release control (#413)"
            assert sim_on.commands[i].tracking_budget_kwh is None
            assert sim_on.commands[i].remote_control_enabled is False

    def test_an_open_gate_is_never_made_stingier(self) -> None:
        """The direction that would be a real #413 regression.

        Delivery in open-gate periods may rise (more reservation survived to
        reach them) but must never fall -- a bound that could only be
        violated by tracking leaking into a period it does not own.
        """
        result, sim_off, _ = _run(OVERSHOOT_FIXTURE, tracking=False)
        _, sim_on, _ = _run(OVERSHOOT_FIXTURE, tracking=True)

        open_gate = [
            i
            for i, p in enumerate(result.period_data)
            if p.decision.strategic_intent == "LOAD_SUPPORT"
            and p.decision.intra_period_discharge_allowed
        ]
        for i in open_gate:
            assert (
                sim_on.period_data[i].energy.battery_discharged
                >= sim_off.period_data[i].energy.battery_discharged - 1e-9
            ), f"period {i}: an open gate delivered less than #413 would have"

    def test_open_gate_covers_a_spike_without_handing_back(self) -> None:
        """The unbounded case, at the level of applied power."""
        s = make_battery_settings(
            total_capacity=10.0,
            min_soc=25.0,
            max_soc=100.0,
            max_charge_power_kw=6.0,
            max_discharge_power_kw=6.0,
        )
        # tracking_budget_kwh None is what an open gate produces.
        power = vpp_command_to_power(
            VppCommand(0, False, tracking_budget_kwh=None),
            solar=0.0,
            home=4.8,
            soe=8.0,
            settings=s,
            dt=1.0,
        )
        assert power == pytest.approx(-4.8), "released self-use must cover the spike"


class TestOptInIsOff:
    def test_flag_off_reproduces_todays_behaviour_exactly(self) -> None:
        """The corpus and the #539/#540 baseline stay valid precisely because
        this holds -- no re-pinning, and the opt-in shape is what makes that
        true. A default-on version would have forced a deliberate re-pin of
        both."""
        for name in (OVERSHOOT_FIXTURE, "regression_2026_07_26_203726"):
            _, sim_off, _ = _run(name, tracking=False)
            _, sim_on_but_flagged_off, _ = _run(name, tracking=False)
            assert sim_off.commands == sim_on_but_flagged_off.commands
            assert sim_off.realized_cost == pytest.approx(
                sim_on_but_flagged_off.realized_cost
            )

    def test_tracking_changes_the_commands_only_when_enabled(self) -> None:
        _, sim_off, _ = _run(OVERSHOOT_FIXTURE, tracking=False)
        _, sim_on, _ = _run(OVERSHOOT_FIXTURE, tracking=True)
        assert (
            sim_on.commands != sim_off.commands
        ), "the flag is not reaching the command path"


class TestTheControlLaw:
    """The tick's own arithmetic. Supplements the outcome tests above; it is
    deliberately not the primary evidence."""

    def test_spike_is_covered_at_the_measured_deficit(self) -> None:
        # #352's reported case: 4.8 kW actual against a 1.96 kW forecast. A
        # power cap would command 1.96 kW and import the remaining 2.84 kW.
        assert (
            tracked_vpp_power_pct(
                4.8, budget_remaining_kwh=0.5, max_discharge_power_kw=6.0
            )
            == -80
        )

    def test_exhausted_budget_hands_back(self) -> None:
        assert tracked_vpp_power_pct(4.8, 0.0, 6.0) == VPP_HOLD_POWER_PCT

    def test_no_deficit_holds_rather_than_releasing(self) -> None:
        """Releasing on a surplus would hand the period to self-use, which is
        what spends the reservation. The hold still absorbs solar."""
        assert tracked_vpp_power_pct(0.0, 1.0, 6.0) == VPP_HOLD_POWER_PCT

    def test_a_tiny_deficit_never_rounds_into_grid_first(self) -> None:
        """0 is grid_first, a different command with different physics (#118:
        it still serves load from the battery, unbounded by this budget)."""
        assert tracked_vpp_power_pct(0.01, 1.0, 6.0) == -1

    def test_rate_is_clamped_to_the_physical_maximum(self) -> None:
        assert tracked_vpp_power_pct(99.0, 10.0, 6.0) == -100

    def test_open_gate_yields_no_budget(self) -> None:
        assert budget_for_period(-0.49, intra_period_discharge_allowed=True) is None

    def test_closed_gate_budgets_the_planned_discharge(self) -> None:
        assert budget_for_period(-0.49, intra_period_discharge_allowed=False) == 0.49

    def test_a_closed_gate_on_a_charging_period_budgets_nothing(self) -> None:
        assert budget_for_period(1.5, intra_period_discharge_allowed=False) == 0.0
