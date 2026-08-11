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
from core.bess.simulation.vpp_simulator import VppCommand, vpp_command_to_power
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
