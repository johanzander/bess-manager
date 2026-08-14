"""#320 / Phase 4a: BatterySystemManager must pass its inverter controller's
capability values into optimize_battery_schedule, not rely on the DP's own
defaults -- this is what lets a non-Growatt platform's overrides actually
reach the DP.

Since 4a those values travel as one `PlatformCapabilities` (D2) rather than a
kwarg per fact, and they now include `discharge_rate_semantics`, which before
4a had zero occurrences anywhere in the optimizer."""

from core.bess.execution_model import (
    DISCHARGE_RATE_ABSENT,
    DISCHARGE_RATE_CEILING,
    DISCHARGE_RATE_TARGET,
    PlatformCapabilities,
)
from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.solax_controller import SolaxController
from core.bess.tests.helpers import make_battery_settings


def test_capabilities_carry_the_controllers_lattice_and_semantics():
    """The same expression battery_system_manager.py evaluates at its
    optimize_battery_schedule call site, exercised without the full manager
    lifecycle."""
    settings = make_battery_settings(max_discharge_power_kw=5.0)
    capabilities = PlatformCapabilities.from_controller(
        GrowattMinController(settings), settings
    )

    assert capabilities.discharge_resolution_kw == 0.05
    assert capabilities.discharge_rate_semantics == DISCHARGE_RATE_CEILING
    assert capabilities.control_model == "tou_register"
    assert capabilities.intent_to_mode["BATTERY_EXPORT"] == "grid_first"


def test_a_non_growatt_platform_reaches_the_dp_differently():
    """The wiring's whole purpose: two platforms must not hand the DP the
    same action space. Before 4a they did -- the capability stopped at the
    controllers and BSM's own gate."""
    settings = make_battery_settings(max_discharge_power_kw=5.0)

    solax = PlatformCapabilities.from_controller(SolaxController(settings), settings)
    sph = PlatformCapabilities.from_controller(GrowattSphController(settings), settings)

    assert solax.discharge_rate_semantics == DISCHARGE_RATE_TARGET
    assert sph.discharge_rate_semantics == DISCHARGE_RATE_ABSENT
    assert not solax.discharge_rate_is_load_following
    assert not sph.discharge_rate_is_load_following
