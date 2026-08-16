"""Phase 4a: the platform capability model and the relocated execution model.

Three things are pinned here, matching the three claims 4a makes:

1. The capability object reads each platform's real declarations -- including
   the tri-state a boolean cannot express (`period_list` platforms have no
   per-period discharge rate at all).
2. It reaches the optimizer. Before 4a `discharge_rate_is_load_following` had
   zero occurrences in the DP, so a non-Growatt platform's declaration could
   not affect a plan no matter what it said.
3. What that immediately fixes (#580): the off-lattice residual-cover
   candidate is only executable where a discharge rate is a *ceiling*, and is
   no longer offered where it is a target or absent. Asserted on the plan --
   the action and the resulting SoE -- not on a candidate list.
"""

import pytest

from core.bess.dp_battery_algorithm import optimize_battery_schedule
from core.bess.execution_model import (
    DISCHARGE_RATE_ABSENT,
    DISCHARGE_RATE_CEILING,
    DISCHARGE_RATE_TARGET,
    PlatformCapabilities,
    intra_period_discharge_gate,
)
from core.bess.growatt_min_controller import GrowattMinController
from core.bess.growatt_sph_controller import GrowattSphController
from core.bess.huawei_controller import HuaweiController
from core.bess.settings import BatterySettings
from core.bess.solax_controller import SolaxController
from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.solis_modbus_controller import SolisModbusController
from core.bess.tests.helpers import make_battery_settings


def _settings() -> BatterySettings:
    return BatterySettings(
        total_capacity=50.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc=10.0,
        max_soc=95.0,
        cycle_cost_per_kwh=0.05,
    )


# ── The capability model ─────────────────────────────────────────────────────


class TestDischargeRateSemantics:
    """`from_controller` must read the platform, and must distinguish "the
    rate is a forced power" from "there is no rate" -- the design's honest
    tri-state (§"Ceiling semantics are per-platform")."""

    def test_growatt_min_rate_is_a_ceiling(self):
        caps = PlatformCapabilities.from_controller(
            GrowattMinController(_settings()), _settings()
        )
        assert caps.discharge_rate_semantics == DISCHARGE_RATE_CEILING
        assert caps.discharge_rate_is_load_following is True

    def test_solax_native_rate_is_a_target(self):
        caps = PlatformCapabilities.from_controller(
            SolaxController(_settings()), _settings()
        )
        assert caps.discharge_rate_semantics == DISCHARGE_RATE_TARGET
        assert caps.discharge_rate_is_load_following is False

    @pytest.mark.parametrize("controller_cls", [GrowattSphController, HuaweiController])
    def test_period_list_platforms_have_no_rate_at_all(self, controller_cls):
        """SPH/Huawei declare `discharge_rate_is_load_following = False`, but
        the reason is not that they force a power -- they have no per-period
        rate to write. Folding them into "target" would claim a behaviour the
        hardware cannot even be told to perform."""
        caps = PlatformCapabilities.from_controller(
            controller_cls(_settings()), _settings()
        )
        assert caps.discharge_rate_semantics == DISCHARGE_RATE_ABSENT
        assert caps.discharge_rate_is_load_following is False

    def test_solax_modbus_growatt_follows_its_control_mode(self):
        tou = PlatformCapabilities.from_controller(
            SolaxModbusGrowattController(_settings(), control_mode="tou"), _settings()
        )
        vpp = PlatformCapabilities.from_controller(
            SolaxModbusGrowattController(_settings(), control_mode="vpp"), _settings()
        )
        assert tou.discharge_rate_semantics == DISCHARGE_RATE_CEILING
        assert vpp.discharge_rate_semantics == DISCHARGE_RATE_TARGET

    def test_unknown_semantics_is_rejected(self):
        with pytest.raises(ValueError, match="discharge_rate_semantics"):
            PlatformCapabilities(discharge_rate_semantics="load_following")

    def test_no_rate_at_all_cannot_claim_to_deliver_an_exact_cover(self):
        """The cross-field invariant, enforced rather than trusted to the
        controllers: this PR exists partly because Solis declared
        `period_list` while inheriting the base class's load-following True.
        The next period-list controller that repeats it must fail at
        construction, not plan an off-lattice delivery on hardware with no
        per-period rate."""
        with pytest.raises(ValueError, match="load_support_delivers_exact_cover"):
            PlatformCapabilities(
                discharge_rate_semantics=DISCHARGE_RATE_ABSENT,
                load_support_delivers_exact_cover=True,
            )

    def test_every_shipped_controller_satisfies_the_invariant(self):
        """The declarations themselves, not a constructed pair -- a controller
        whose two flags disagree cannot even be read into a capability."""
        for controller in (
            GrowattMinController(_settings()),
            GrowattSphController(_settings()),
            HuaweiController(_settings()),
            SolaxController(_settings()),
            SolisModbusController(_settings()),
            SolaxModbusGrowattController(_settings(), control_mode="tou"),
            SolaxModbusGrowattController(_settings(), control_mode="vpp"),
        ):
            PlatformCapabilities.from_controller(controller, _settings())


class TestLattice:
    """The lattice facts the candidate space enumerates."""

    def test_default_step_is_one_percent_of_max_discharge(self):
        settings = make_battery_settings(max_discharge_power_kw=5.0)
        assert PlatformCapabilities().discharge_rate_step_kw(settings) == 0.05

    def test_declared_resolution_wins(self):
        settings = make_battery_settings(max_discharge_power_kw=5.0)
        caps = PlatformCapabilities(discharge_resolution_kw=0.025)
        assert caps.discharge_rate_step_kw(settings) == 0.025

    def test_min_gear_clears_the_classification_threshold(self):
        """Not simply one step: on a battery whose 1% lands at or below
        `POWER_CLASSIFICATION_THRESHOLD_KW` (0.05 kW) the first commandable
        gear is higher, which is the #282 postmortem's rule."""
        caps = PlatformCapabilities()
        five_kw = make_battery_settings(max_discharge_power_kw=5.0)
        # 1% of 5 kW is 0.05 kW -- exactly the threshold, so the first gear
        # clear of it is 2%.
        assert caps.min_discharge_gear_index(five_kw) == 2
        assert caps.min_discharge_gear_index(five_kw) * caps.discharge_rate_step_kw(
            five_kw
        ) == pytest.approx(0.1)

        # 1% of 20 kW is 0.2 kW, already clear of the threshold.
        twenty_kw = make_battery_settings(max_discharge_power_kw=20.0)
        assert caps.min_discharge_gear_index(twenty_kw) == 1
        assert caps.min_discharge_gear_index(twenty_kw) * caps.discharge_rate_step_kw(
            twenty_kw
        ) == pytest.approx(0.2)


class TestGateRelocation:
    """D1 moved `intra_period_discharge_gate` into this leaf so the simulator
    and the optimizer can share it without importing the orchestrator. The
    behaviour is unchanged, and the module must stay a leaf."""

    def test_gate_is_unchanged(self):
        assert intra_period_discharge_gate(True) == 100
        assert intra_period_discharge_gate(False) == 0

    def test_module_imports_nothing_above_itself(self):
        """The whole point of D1. If `execution_model` ever imports the
        orchestrator, the selector's dependency on it re-creates exactly the
        cycle the phase removed."""
        import ast
        import pathlib

        from core.bess import execution_model

        source = pathlib.Path(execution_model.__file__).read_text()
        # Only in-package imports matter -- stdlib cannot create a cycle.
        in_package: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                if node.level:  # relative: `from .settings import ...`
                    in_package.add(node.module or "")
                elif node.module and node.module.startswith("core.bess"):
                    in_package.add(node.module.removeprefix("core.bess."))
            elif isinstance(node, ast.Import):
                in_package.update(
                    alias.name.removeprefix("core.bess.")
                    for alias in node.names
                    if alias.name.startswith("core.bess")
                )
        assert in_package <= {"settings", "dp_constants"}, (
            "execution_model must stay a leaf (D1) -- it may only import the "
            f"two leaf modules, but imports {sorted(in_package)}"
        )


# ── What the capability changes in the plan (#580) ───────────────────────────
#
# The scenario is `test_backward_pass_values_the_residual_cover_candidate`'s:
# a net load below the smallest lattice discharge, with a negative sell price
# so every overshooting lattice candidate pays to export the overshoot.
# Covering the residual exactly is then the uniquely best action -- but only
# where the hardware delivers `min(command, actual load)`.

_COVER_HORIZON = 4


def _plan_with(capabilities: PlatformCapabilities):
    settings = make_battery_settings(cycle_cost_per_kwh=0.0)
    return optimize_battery_schedule(
        buy_price=[1.5] * _COVER_HORIZON,
        sell_price=[-0.5] * _COVER_HORIZON,
        home_consumption=[0.02] * _COVER_HORIZON,
        solar_production=[0.0] * _COVER_HORIZON,
        battery_settings=settings,
        initial_soe=settings.min_soe_kwh + 1.0,
        period_duration_hours=0.25,
        capabilities=capabilities,
    )


def test_cover_candidate_is_planned_where_the_rate_is_a_ceiling():
    """The #466 candidate still fires on Growatt MIN-shaped hardware: the
    battery covers the sub-lattice residual and the house imports nothing."""
    plan = _plan_with(PlatformCapabilities())
    first = plan.period_data[0]
    assert first.decision.battery_action < 0, (
        f"expected the residual-cover discharge, got "
        f"{first.decision.battery_action} kW"
    )
    assert first.energy.grid_imported == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("semantics", [DISCHARGE_RATE_TARGET, DISCHARGE_RATE_ABSENT])
def test_cover_candidate_is_not_planned_where_the_cover_is_not_delivered(semantics):
    """#580: on SolaX native the number is a forced power, and on SPH / Solis
    / Huawei there is no per-period rate at all. Planning an off-lattice
    delivery there is planning something the hardware will not do -- the #282
    shape. Before 4a the candidate was added unconditionally, so this scenario
    planned the identical cover discharge on every platform.
    """
    plan = _plan_with(
        PlatformCapabilities(
            discharge_rate_semantics=semantics,
            load_support_delivers_exact_cover=False,
        )
    )
    first = plan.period_data[0]
    assert first.decision.battery_action == pytest.approx(0.0, abs=1e-9), (
        f"platform cannot execute an off-lattice cover, but the plan chose "
        f"{first.decision.battery_action} kW"
    )
    assert (
        first.energy.grid_imported > 0.0
    ), "with no executable cover the house deficit must be imported"


def test_cover_candidate_survives_where_load_support_load_follows_without_a_ceiling():
    """solax-modbus Growatt in VPP mode: the rate register is a forced power,
    but LOAD_SUPPORT writes no rate at all -- #413 disables remote control for
    that intent and hands the period to the inverter's own load-following
    self-use, so the cover IS delivered exactly.

    Gating the candidate on the *register's* semantics would silently withdraw
    #466's sunrise-crossover saving from that platform for no fidelity gain,
    which is why the two questions are separate capabilities.
    """
    caps = PlatformCapabilities(
        discharge_rate_semantics=DISCHARGE_RATE_TARGET,
        load_support_delivers_exact_cover=True,
        control_model="vpp_power",
    )
    assert caps.discharge_rate_is_load_following is False

    plan = _plan_with(caps)
    first = plan.period_data[0]
    assert first.decision.battery_action < 0, (
        "VPP-mode LOAD_SUPPORT load-follows natively (#413) -- the cover "
        f"candidate must survive, got {first.decision.battery_action} kW"
    )
    assert first.energy.grid_imported == pytest.approx(0.0, abs=1e-9)


def test_solax_modbus_vpp_declares_the_two_capabilities_differently():
    """The platform that makes the distinction load-bearing, read off the real
    controller rather than constructed by hand."""
    caps = PlatformCapabilities.from_controller(
        SolaxModbusGrowattController(_settings(), control_mode="vpp"), _settings()
    )
    assert caps.discharge_rate_is_load_following is False  # forced vpp_power
    assert caps.load_support_delivers_exact_cover is True  # #413 release


def test_intent_to_mode_cannot_be_mutated_through_a_capability():
    """One dict is shared by the module constant, InverterController and every
    capability default -- an in-place write anywhere would rewrite the mode
    vocabulary for every platform at once."""
    caps = PlatformCapabilities()
    with pytest.raises(TypeError):
        caps.intent_to_mode["IDLE"] = "grid_first"  # type: ignore[index]
