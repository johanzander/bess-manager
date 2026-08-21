"""Branch coverage for the VPP execution model (#539).

The `v10.0.2` baseline pins whole-corpus behaviour, but the corpus cannot
reach every branch of `vpp_command_to_power`: no SOLAR_EXPORT period in any
of the 36 fixtures has `home > solar`, so grid_first's load-serving path is
dead there, and the zero-delivery paths only arise at the SoE floor. Those
are exactly the branches where the modelling choices live, so they are pinned
here directly.

Assertions are on the *power the inverter would apply* rather than on
realized cost, because that is the model's own output -- the outcome-level
pin is the baseline test. Where a branch encodes a contested reading of the
hardware protocol, the test says which reading and why, so a future change
has to be deliberate.
"""

import pytest

from core.bess.dp_battery_algorithm import _state_transition
from core.bess.simulation.vpp_simulator import (
    VppCommand,
    derive_vpp_commands,
    vpp_command_to_power,
)
from core.bess.tests.helpers import make_battery_settings

DT = 1.0


def _settings():
    return make_battery_settings(
        total_capacity=10.0,
        min_soc=25.0,
        max_soc=100.0,
        max_charge_power_kw=6.0,
        max_discharge_power_kw=6.0,
    )


class TestGridFirstHold:
    def test_grid_first_serves_load_from_battery(self):
        """`power=0` + remote enabled is grid_first, which per #118/#466 still
        draws self-consumption from the battery -- only battery_first (`>0`)
        releases the house to grid/solar.

        This contradicts #355's reading of the same command as a full hold.
        #118 is preferred because it is backed by a real-hardware report. If
        that is ever corrected, this test is the place it must be corrected --
        the fixture corpus has no SOLAR_EXPORT period with `home > solar`, so
        it produces no signal on this branch at all.
        """
        s = _settings()
        power = vpp_command_to_power(
            VppCommand(0, True), solar=0.0, home=1.0, soe=8.0, settings=s, dt=DT
        )
        assert power is not None and power < 0, "grid_first must serve the load"
        assert power == pytest.approx(-1.0)

    def test_grid_first_holds_against_solar_surplus(self):
        """#355: grid_first must not absorb surplus into the battery."""
        s = _settings()
        power = vpp_command_to_power(
            VppCommand(0, True), solar=3.0, home=1.0, soe=8.0, settings=s, dt=DT
        )
        assert power is None, "a hold must not become a passive charge"

    def test_grid_first_at_the_floor_holds_rather_than_charging(self):
        """Zero deliverable energy must stay a hold. Returning -0.0 would miss
        `_state_transition`'s discharge tolerance and fall into its IDLE
        branch, charging the battery from surplus under a hold command."""
        s = _settings()
        power = vpp_command_to_power(
            VppCommand(0, True),
            solar=3.0,
            home=4.0,  # real deficit, but nothing available to serve it
            soe=s.min_soe_kwh,
            settings=s,
            dt=DT,
        )
        assert power is None


class TestForcedDischarge:
    def test_forced_discharge_delivers_the_commanded_rate(self):
        s = _settings()
        power = vpp_command_to_power(
            VppCommand(-50, True), solar=0.0, home=0.1, soe=9.0, settings=s, dt=DT
        )
        assert power == pytest.approx(-3.0)  # 50% of 6 kW

    def test_forced_discharge_at_the_floor_does_not_charge(self):
        """The #541-review defect: at the SoE floor a forced-export command
        returned -0.0, which is not below `POWER_TOLERANCE_KW`, so
        `_state_transition` absorbed solar surplus into the battery -- a
        charge under an export command.

        Reproduces `realworld_2026_04_29_220919` period 37 in miniature.
        """
        s = _settings()
        power = vpp_command_to_power(
            VppCommand(-1, True),
            solar=1.3,
            home=0.2,  # 1.1 kWh surplus available to be wrongly absorbed
            soe=s.min_soe_kwh,
            settings=s,
            dt=DT,
        )
        assert power is None, "must hold, not fall through to IDLE's charging"

    def test_the_floor_case_would_charge_if_it_returned_zero(self):
        """Why the branch above returns None rather than 0.0 or -0.0 -- the
        physics core, not the simulator, is what turns either into a charge."""
        s = _settings()
        charged = _state_transition(
            s.min_soe_kwh, -0.0, s, DT, solar_production=1.3, home_consumption=0.2
        )
        assert charged > s.min_soe_kwh


class TestBatteryFirst:
    def test_full_rate_charges(self):
        s = _settings()
        assert vpp_command_to_power(
            VppCommand(100, True), solar=0.0, home=0.0, soe=5.0, settings=s, dt=DT
        ) == pytest.approx(s.max_charge_power_kw)

    def test_hold_does_not_charge_from_grid(self):
        """+1 is the IDLE/hold convention (#466). STORE physics are binary, so
        returning the honest 1% rate would simulate a full-rate grid charge --
        0.0 routes to the IDLE branch: passive solar only, never a grid draw."""
        s = _settings()
        assert (
            vpp_command_to_power(
                VppCommand(1, True), solar=0.0, home=0.0, soe=5.0, settings=s, dt=DT
            )
            == 0.0
        )

    def test_unmodellable_intermediate_rate_raises(self):
        """Only +1 and +100 are ever written; anything else cannot be
        simulated faithfully and must fail loudly rather than silently
        becoming a full-rate charge."""
        s = _settings()
        with pytest.raises(ValueError, match="unmodellable"):
            vpp_command_to_power(
                VppCommand(50, True), solar=0.0, home=0.0, soe=5.0, settings=s, dt=DT
            )


class TestReleasedControl:
    def test_released_control_covers_the_deficit(self):
        s = _settings()
        power = vpp_command_to_power(
            VppCommand(0, False), solar=0.0, home=2.0, soe=8.0, settings=s, dt=DT
        )
        assert power == pytest.approx(-2.0)

    def test_released_control_is_capped_by_the_inverter_rating(self):
        """Releasing control drops the *planned* rate ceiling, not the
        inverter's physical one.

        An earlier revision capped this branch by deficit, available energy
        and AC headroom only, so a 6 kW inverter delivered the whole deficit
        however large: at `dt=0.25` a 5 kWh deficit came back as -20 kW. That
        was reachable and was baked into the v10.0.2 baseline --
        `synthetic_consumption_high_no_solar` commands `(0, False)` over
        periods 16-20 against 7-10 kWh hourly deficits, and its recorded SoE
        trajectory dropped 7.37 and 9.47 kWh in single hours.
        """
        s = _settings()
        assert vpp_command_to_power(
            VppCommand(0, False), solar=0.0, home=9.0, soe=9.0, settings=s, dt=DT
        ) == pytest.approx(-6.0)
        assert vpp_command_to_power(
            VppCommand(0, False), solar=0.0, home=5.0, soe=9.0, settings=s, dt=0.25
        ) == pytest.approx(-6.0)

    def test_grid_first_load_serving_is_capped_by_the_inverter_rating(self):
        """Same physical cap on the grid_first load-serving branch. The corpus
        cannot reach it (no SOLAR_EXPORT period has `home > solar`), so this is
        the only thing holding it."""
        s = _settings()
        assert vpp_command_to_power(
            VppCommand(0, True), solar=0.0, home=9.0, soe=9.0, settings=s, dt=DT
        ) == pytest.approx(-6.0)

    def test_released_control_at_the_floor_does_not_charge(self):
        """The third zero-delivery path, held to the same rule as the two
        enabled-remote ones.

        At the SoE floor with a deficit, `delivered` is 0 and `-0.0` reads as
        "not a discharge" to `_state_transition` (`power < -POWER_TOLERANCE_KW`
        is False), dropping into its IDLE branch. Today that cannot misbehave
        here -- this branch needs `home > solar`, so there is no surplus for
        IDLE to absorb -- but the invariant is incidental rather than designed,
        and #537 wiring a planned rate into the released path would make the
        branch reachable with a surplus. Pinned so the fix cannot come apart in
        the one branch that was left inconsistent.
        """
        s = _settings()
        assert (
            vpp_command_to_power(
                VppCommand(0, False),
                solar=0.0,
                home=1.0,
                soe=s.min_soe_kwh,
                settings=s,
                dt=DT,
            )
            is None
        )

    def test_released_control_absorbs_surplus(self):
        """Unlike the enabled-remote holds, load_first self-use genuinely does
        absorb surplus, so 0.0 (the IDLE branch) is correct here."""
        s = _settings()
        assert (
            vpp_command_to_power(
                VppCommand(0, False), solar=3.0, home=1.0, soe=5.0, settings=s, dt=DT
            )
            == 0.0
        )


class TestIdleAtReserveFloor:
    """#592: at the floor, IDLE releases control instead of holding
    battery_first, so the inverter is handed back and its BMS can sleep.

    These pin *why that is safe*: the released command produces the same
    battery power as today's hold in every case reachable at the floor, so
    no energy flow moves. That is what lets this change ship without
    re-pinning the v10.0.2 VPP baseline.
    """

    def test_release_matches_the_hold_when_solar_is_in_surplus(self) -> None:
        """Both absorb the surplus: the hold via `0.0` -> `_state_transition`'s
        IDLE branch, the released command via its own `deficit <= 0` return.

        This is the case that rules out the reporter's other suggestion in
        #592 -- `power=0` with remote control *enabled* is grid_first, which
        holds against charging and would export this surplus instead, losing
        the passive absorption IDLE's own DP cost model credits.
        """
        s = _settings()
        at_floor = s.min_soe_kwh
        hold = vpp_command_to_power(
            VppCommand(1, True), solar=3.0, home=1.0, soe=at_floor, settings=s, dt=DT
        )
        released = vpp_command_to_power(
            VppCommand(0, False), solar=3.0, home=1.0, soe=at_floor, settings=s, dt=DT
        )
        assert hold == released == 0.0

        grid_first = vpp_command_to_power(
            VppCommand(0, True), solar=3.0, home=1.0, soe=at_floor, settings=s, dt=DT
        )
        assert grid_first is None, (
            "grid_first is NOT flow-neutral here -- it bypasses the surplus to "
            "the grid, which is why #592 releases control instead"
        )

    def test_release_matches_the_hold_when_load_exceeds_solar(self) -> None:
        """No headroom at the floor, so the released command cannot discharge:
        `available == 0` makes `delivered` 0 and the branch returns None (a
        hold), exactly like battery_first. This is what makes releasing safe
        against #466 -- there is no energy left for load_first to drain.

        Note what this does and does not prove. `available` is measured
        against BESS's own `min_soe_kwh`, so this pins the *model*, which
        assumes the inverter's discharge_stop_soc agrees with the configured
        min_soc. In VPP mode BESS never writes that register (#309), so on
        real hardware a lower inverter floor would let released self-use draw
        the gap. Same assumption the model already makes for LOAD_SUPPORT and
        SOLAR_STORAGE; see _intent_to_vpp's #592 note."""
        s = _settings()
        at_floor = s.min_soe_kwh
        hold = vpp_command_to_power(
            VppCommand(1, True), solar=0.0, home=2.0, soe=at_floor, settings=s, dt=DT
        )
        released = vpp_command_to_power(
            VppCommand(0, False), solar=0.0, home=2.0, soe=at_floor, settings=s, dt=DT
        )
        assert hold == 0.0
        assert released is None
        for power in (hold, released):
            assert _state_transition(
                at_floor,
                power or 0.0,
                s,
                DT,
                solar_production=0.0,
                home_consumption=2.0,
            ) == pytest.approx(at_floor), "neither command may move SoE at the floor"

    def test_release_would_discharge_above_the_floor(self) -> None:
        """The guard rail on the test above: releasing control is only
        flow-neutral *at* the floor. One kWh above it the released command
        drains the battery to cover load -- which is exactly #466's defect,
        and why the release is gated on being at the floor rather than
        applied to IDLE generally."""
        s = _settings()
        above_floor = s.min_soe_kwh + 1.0
        released = vpp_command_to_power(
            VppCommand(0, False),
            solar=0.0,
            home=2.0,
            soe=above_floor,
            settings=s,
            dt=DT,
        )
        assert released is not None and released < 0


class TestPlanShape:
    def test_mismatched_plan_lengths_raise(self):
        """`derive_vpp_commands` iterates `actions_kw` and indexes `intents`,
        so a short `actions_kw` would silently produce a partial command list
        and `simulate_vpp` would price part of a day. Against the baseline that
        reads as a plan change rather than as a harness bug, so it is rejected
        at the input instead."""
        s = _settings()
        soe = [5.0, 5.0, 5.0]
        with pytest.raises(ValueError, match="inconsistent"):
            derive_vpp_commands(["IDLE", "IDLE"], [0.0], s, soe)
        with pytest.raises(ValueError, match="inconsistent"):
            derive_vpp_commands(["IDLE"], [0.0, 0.0], s, soe)

    def test_short_soe_trajectory_raises(self) -> None:
        """Same reasoning for the SoE trajectory #592 added: one entry short
        and the last periods would be derived against the wrong floor state,
        silently, rather than failing at the input."""
        s = _settings()
        with pytest.raises(ValueError, match="inconsistent"):
            derive_vpp_commands(["IDLE", "IDLE"], [0.0, 0.0], s, [5.0])
