"""#466 (ridax67): "How is IDLE used?" — both halves, asserted on outcomes.

What was reported: the plan sold down the battery in a high-price evening and
ran IDLE overnight to hold what was left for the morning. A good plan. On
Growatt VPP it did not happen — *"It seems IDLE is mapped to load first so
the battery was quickly empty."*

That is two separate defects wearing one issue number, and they need
different evidence:

1. **Planning** — the DP chose IDLE in near-tied evening periods where it
   should have covered load from the battery (#488, #517). Guarded by the
   cost pin on `regression_2026_08_06_466.json`, replayed from ridax's own
   bundle `bess-debug-2026-08-06-110152.md`. The cost pin proves the plan got
   cheaper; it does not say IDLE stopped being chosen. This file says that.

2. **Execution** — VPP mapped IDLE to `load_first` self-use, so the battery
   drained overnight instead of holding (#468). Guarded until now only by
   tests asserting the *command* written (`vpp_power=+1`, remote enabled).
   A command assertion proves the mapping, not that the battery held. With
   the VPP execution model (#539) the outcome itself can be asserted, and is,
   below.

Per `rules.md`: assert the outcome, not the command.
"""

import json
from pathlib import Path

import pytest

from core.bess.simulation.vpp_simulator import (
    VppCommand,
    simulate_vpp,
    simulate_vpp_commands,
)
from core.bess.tests.helpers import make_battery_settings, run_scenario

FIXTURE = Path(__file__).parent / "data" / "regression_2026_08_06_466.json"


class TestPlanningHalf:
    """The DP must not idle through a home deficit it can profitably serve."""

    def test_ridax_bundle_never_idles_while_the_home_draws(self):
        """On the reported day, no period idles while the house has load and
        the battery has energy to give.

        The fixture's own description records the pre-fix behaviour: *"near-
        tied evening periods (19:00, 22:15) chose IDLE pre-fix despite home
        load and positive discharge value"*. This asserts that directly,
        rather than inferring it from the fixture's cost pin — a cheaper plan
        could in principle be reached while still idling somewhere else.

        **What this does NOT do, measured 2026-08-11: it does not isolate the
        #466 tie-break.** Disabling `_row_load_covering_discharge` entirely
        leaves this bundle's intents byte-identical (28 SOLAR_EXPORT, 4
        SOLAR_STORAGE, 20 LOAD_SUPPORT) and moves cost by 0.00212 SEK — below
        the 0.1 SEK rounding `test_scenarios` compares at, so that pin misses
        it too. The near-ties this bundle was captured for appear to have been
        dissolved by #512's finer grid, so IDLE avoidance here no longer
        depends on the row built for it.

        The row is still guarded — removing it fails 10 tests in
        `test_tie_policy.py` and `test_idle_tie_break.py`. What this test
        provides is the *outcome* pin on the reported day: if any future
        change reintroduces idling through a deficit on ridax's own data, it
        fails. That is worth having, and it is not the same as proving which
        mechanism prevents it.
        """
        scenario = json.loads(FIXTURE.read_text())
        result = run_scenario(scenario)
        settings_min_soe = scenario["battery"]["min_soe_kwh"]

        idling_through_load = [
            p.period
            for p in result.period_data
            if p.decision.strategic_intent == "IDLE"
            and p.energy.home_consumption > p.energy.solar_production
            and p.energy.battery_soe_start > settings_min_soe + 0.1
        ]

        assert idling_through_load == [], (
            "the DP is idling through a home deficit with usable energy in "
            f"the battery, at periods {idling_through_load} — this is #466's "
            "reported complaint"
        )

    def test_the_bundle_actually_exercises_the_case(self):
        """Guard against the assertion above passing because the day is
        trivial: it must contain real home deficits and a battery able to
        serve them, or it proves nothing."""
        scenario = json.loads(FIXTURE.read_text())
        result = run_scenario(scenario)

        deficits = [
            p
            for p in result.period_data
            if p.energy.home_consumption > p.energy.solar_production
        ]
        assert len(deficits) >= 10, (
            f"only {len(deficits)} periods have a home deficit; this fixture "
            "can no longer discriminate"
        )
        assert any(
            p.decision.strategic_intent == "LOAD_SUPPORT" for p in result.period_data
        ), "no period covers load from the battery at all"


class TestExecutionHalf:
    """VPP IDLE must hold the battery, not drain it into the house."""

    def test_idle_holds_soc_through_a_night_of_house_load(self):
        """ridax's exact symptom: IDLE overnight, battery *"quickly empty"*.

        Twelve hours of house load, no solar, every period IDLE. The battery
        must end where it started — the house draws from the grid. Before
        #468, VPP mapped IDLE to `load_first` self-use and the SoE fell.

        Asserted on the simulated SoE trajectory rather than on the command,
        which is the distinction #466 turned on: the command was arguably
        defensible, the outcome was not.
        """
        settings = make_battery_settings(
            total_capacity=10.0,
            min_soc=10.0,
            max_soc=100.0,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
        )
        periods = 48  # 12 h at 15 min
        start_soe = 8.0

        sim = simulate_vpp(
            ["IDLE"] * periods,
            [0.0] * periods,
            solar_production=[0.0] * periods,
            home_consumption=[0.5] * periods,  # 2 kW draw, no solar
            buy_price=[1.0] * periods,
            sell_price=[0.4] * periods,
            initial_soe=start_soe,
            settings=settings,
            dt=0.25,
        )

        assert sim.commands[0] == VppCommand(
            power_pct=1, remote_control_enabled=True
        ), (
            "IDLE must command battery_first hold (#466) — if this changed, "
            "the outcome assertion below is testing something else. Note the "
            "start SoE is deliberately above min_soe_kwh, so #592's "
            "reserve-floor release does not apply here."
        )

        end_soe = sim.period_data[-1].energy.battery_soe_end
        assert end_soe == pytest.approx(start_soe, abs=1e-9), (
            f"battery drained {start_soe - end_soe:.3f} kWh across an IDLE "
            "night — this is exactly #466's report"
        )
        assert all(
            p.energy.battery_discharged == 0.0 for p in sim.period_data
        ), "IDLE discharged the battery to serve the house"
        assert all(
            p.energy.grid_imported > 0 for p in sim.period_data
        ), "the house must be drawing from the grid instead"

    def test_released_control_would_have_drained_it(self):
        """The counterfactual, so the test above cannot pass for the wrong
        reason: the pre-#468 mapping (release control → `load_first`
        self-use) drains the battery on the same inputs."""
        settings = make_battery_settings(
            total_capacity=10.0,
            min_soc=10.0,
            max_soc=100.0,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
        )
        periods = 48
        start_soe = 8.0

        sim = simulate_vpp_commands(
            [VppCommand(power_pct=0, remote_control_enabled=False)] * periods,
            solar_production=[0.0] * periods,
            home_consumption=[0.5] * periods,
            buy_price=[1.0] * periods,
            sell_price=[0.4] * periods,
            initial_soe=start_soe,
            settings=settings,
            dt=0.25,
        )

        end_soe = sim.period_data[-1].energy.battery_soe_end
        assert end_soe < start_soe - 1.0, (
            "the pre-fix mapping should visibly drain the battery; if it no "
            "longer does, this pair of tests no longer discriminates"
        )
