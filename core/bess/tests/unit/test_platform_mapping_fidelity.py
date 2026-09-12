"""How much of a planned rate each platform can actually execute.

Written after a design defect in #537, which reached review before anyone
noticed it. The reasoning that produced it: Growatt VPP carries
BATTERY_EXPORT's planned discharge magnitude faithfully (`power_pct` is the
plan-scaled rate, negated), so it looked safe to assume VPP could express
"discharge, but only this much" for LOAD_SUPPORT too. It cannot. LOAD_SUPPORT
maps to *release control* -- one command for every planned rate -- so the
plan-scaled cap TOU applies has no VPP counterpart at all.

That is not a fact about the gate, it is a fact about the mapping, and it is
mechanically measurable: sweep the planned action across its full range and
count how many distinct commands come out the other side. An intent whose 101
distinct TOU rates collapse to 1 VPP command cannot execute a partial plan on
that platform, whatever the calling code believes.

The measurement only works if the sweep looks at the *whole* TOU rate triple.
GRID_CHARGING carries its magnitude in `charge_rate`, LOAD_SUPPORT and
BATTERY_EXPORT in `discharge_rate`; a sweep of the discharge half alone scores
GRID_CHARGING as a one-rate intent with nothing to lose and never measures it.

`test_scenarios` and the golden corpus cannot see this. They pin what the DP
*plans*; this pins what a platform can *execute*. A change that makes a
platform less able to follow the plan is invisible to every other test in the
suite -- which is how #537 got as far as it did.

Per `rules.md`: assert the outcome, not the command. The outcome here is
executable fidelity, and it is the property the gate design depends on.
"""

import pytest

from core.bess.solax_modbus_growatt_controller import SolaxModbusGrowattController
from core.bess.tests.helpers import make_battery_settings

INTENTS = [
    "IDLE",
    "SOLAR_STORAGE",
    "SOLAR_EXPORT",
    "LOAD_SUPPORT",
    "BATTERY_EXPORT",
    "GRID_CHARGING",
]

# Intents whose planned rate Growatt VPP CANNOT reproduce: every planned
# magnitude collapses to a single command. Adding an intent here is a
# deliberate statement that the plan's magnitude is discarded on VPP -- it
# must not happen by accident.
#
# GRID_CHARGING was lossy here for the mirror-image reason to LOAD_SUPPORT
# (TOU carries its plan-scaled magnitude in `charge_rate`, and
# `_intent_to_vpp` was not given `charge_rate` at all) until #754: the write
# path (`_apply_period_vpp`) now derives the plan's actual charge rate from
# `self.current_schedule` and passes it through, the same way
# `_apply_period_tou` already derives its own `current_period`. See the
# Growatt VPP Communication Protocol V2.01 section 3.5: register 30409 is a
# documented bidirectional power target ("Actual control value of
# charging/discharging power (30474) = Remote charging/discharging power
# (30409)"), symmetric for charge and discharge -- there was never a
# hardware reason charge alone should be lossy, only a missing plumbing.
VPP_LOSSY_INTENTS = {"LOAD_SUPPORT"}


def _settings():
    return make_battery_settings(
        total_capacity=30.0,
        min_soc=10.0,
        max_soc=100.0,
        max_charge_power_kw=6.0,
        max_discharge_power_kw=6.0,
    )


def _sweep(intent):
    """Every (TOU rate, VPP command) the production path emits for `intent`
    across the full planned-action range.

    The TOU side is the **full** `(grid_charge, charge_rate, discharge_rate)`
    triple, not just `compute_rates_for_period`'s return. That method does not
    report `charge_rate`, which is the half GRID_CHARGING's magnitude travels
    in: `get_period_settings` derives it separately via `compute_charge_rate`
    (`inverter_controller.py:601`, and again at `:762`), and this mirrors those
    two call sites. Sweeping the discharge rate alone made GRID_CHARGING look
    like a one-rate intent, so it took the "not rate-bearing, nothing to lose"
    early return and its loss on VPP was never measured at all.
    """
    settings = _settings()
    controller = SolaxModbusGrowattController(settings, control_mode="vpp")
    controller.strategic_intents = [intent]

    rates, commands = set(), set()
    for hundredths in range(-600, 601):
        action_kw = hundredths / 100.0
        grid_charge, rate, block_passive = controller.compute_rates_for_period(
            0, action_kw
        )
        charge_rate = controller.compute_charge_rate(
            intent, controller.INTENT_TO_CONTROL[intent], action_kw
        )
        rates.add((grid_charge, charge_rate, rate))
        commands.add(
            controller._intent_to_vpp(
                grid_charge, rate, block_passive, intent, charge_rate=charge_rate
            )
        )
    return rates, commands


@pytest.mark.parametrize("intent", INTENTS)
def test_vpp_rate_fidelity_matches_declared_expectation(intent):
    """A rate-bearing intent must keep its magnitude on VPP unless it is
    declared lossy.

    The failure this guards: an intent silently becoming lossy, so planned
    energy is discarded at execution while every plan-level test stays green.
    """
    rates, commands = _sweep(intent)

    if len(rates) == 1:
        # Not rate-bearing -- one planned rate, nothing to lose.
        assert intent not in VPP_LOSSY_INTENTS, (
            f"{intent} is declared VPP-lossy but emits only one TOU rate; "
            "the declaration is stale"
        )
        return

    lossy = len(commands) < len(rates)
    if intent in VPP_LOSSY_INTENTS:
        assert lossy, (
            f"{intent} is declared VPP-lossy but now maps {len(rates)} rates "
            f"to {len(commands)} commands. If VPP gained the ability to "
            "express a partial rate here, remove it from VPP_LOSSY_INTENTS -- "
            "and revisit #520/#537, whose design turns on this."
        )
    else:
        assert not lossy, (
            f"{intent} now collapses {len(rates)} planned rates onto "
            f"{len(commands)} VPP command(s): the planned magnitude is being "
            "discarded at execution. Plan-level tests cannot see this."
        )


def test_load_support_is_the_only_lossy_intent_on_vpp() -> None:
    """Pins the asymmetry that caused #537's defect.

    BATTERY_EXPORT and, since #754, GRID_CHARGING keep their magnitude;
    LOAD_SUPPORT alone releases control instead (#413) and cannot express a
    partial rate. Generalising "this rate-bearing intent is lossy" from one
    intent to another is exactly the wrong inference, and it is only visible
    when they are compared side by side.

    An earlier revision asserted the narrower "LOAD_SUPPORT is the only lossy
    intent", which was false at the time: GRID_CHARGING was misclassified as
    not rate-bearing because the sweep never looked at `charge_rate`, and the
    write path did not derive or pass one. #754 fixed the write path
    (`_apply_period_vpp` now derives `charge_rate` from the plan) and this
    sweep to match (now passing `charge_rate` through), so the assertion
    "LOAD_SUPPORT is the only lossy intent" is true again -- for a different,
    now-correct reason.
    """
    lossy = {
        intent for intent in INTENTS if len(_sweep(intent)[1]) < len(_sweep(intent)[0])
    }
    assert lossy == VPP_LOSSY_INTENTS, (
        f"the set of VPP-lossy intents changed: {lossy} vs declared "
        f"{VPP_LOSSY_INTENTS}. This changes which intents can carry a "
        "partial plan on VPP -- review any gate/ceiling design that assumes "
        "otherwise before updating this pin."
    )


def test_battery_export_carries_the_plan_exactly():
    """The positive half, so the test above cannot pass by everything being
    lossy: BATTERY_EXPORT's command must track the planned magnitude."""
    settings = _settings()
    controller = SolaxModbusGrowattController(settings, control_mode="vpp")
    controller.strategic_intents = ["BATTERY_EXPORT"]

    for action_kw, expected_pct in [(-6.0, -100), (-3.0, -50), (-1.5, -25)]:
        grid_charge, rate, block_passive = controller.compute_rates_for_period(
            0, action_kw
        )
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge, rate, block_passive, "BATTERY_EXPORT"
        )
        assert (power_pct, enabled) == (
            expected_pct,
            True,
        ), f"BATTERY_EXPORT at {action_kw} kW should command {expected_pct}%"


def test_grid_charging_carries_the_plan_exactly() -> None:
    """#754's positive half: GRID_CHARGING's command must track the planned
    magnitude too, not just BATTERY_EXPORT's -- so the test above cannot
    pass by GRID_CHARGING being lossy for a different reason than declared.
    """
    settings = _settings()
    controller = SolaxModbusGrowattController(settings, control_mode="vpp")
    controller.strategic_intents = ["GRID_CHARGING"]

    for action_kw, expected_pct in [(6.0, 100), (3.0, 50), (1.5, 25)]:
        grid_charge, rate, block_passive = controller.compute_rates_for_period(
            0, action_kw
        )
        charge_rate = controller.compute_charge_rate(
            "GRID_CHARGING", controller.INTENT_TO_CONTROL["GRID_CHARGING"], action_kw
        )
        power_pct, enabled = controller._intent_to_vpp(
            grid_charge, rate, block_passive, "GRID_CHARGING", charge_rate=charge_rate
        )
        assert (power_pct, enabled) == (
            expected_pct,
            True,
        ), f"GRID_CHARGING at {action_kw} kW should command {expected_pct}%"
