"""The execution model: what a command means on the platform that executes it.

Phase 4a of
`docs/superpowers/plans/2026-08-09-optimizer-target-architecture.md`
(design: `docs/superpowers/specs/2026-08-11-phase4-executable-candidates-design.md`,
decisions D1 and D2).

This module is a **leaf**: it imports `settings` and `dp_constants` and
nothing else in `core.bess`. That constraint is the whole point of D1, not a
style preference. `simulation/inverter_simulator` needs the intra-period
discharge gate and so did `battery_system_manager`, which is why the gate used
to live in the orchestrator; the optimizer core (`action_selector`,
`dp_battery_algorithm`, `pwl_window_dp`) needs the same platform facts to know
which actions are executable. With the gate here, both sides depend on a leaf
instead of the optimizer depending on the thing that runs the optimizer.
`dp_battery_algorithm:_run_dynamic_programming` already works around one
import cycle with a function-local import; per `rules.md`'s workaround check,
adding a second was not an option.

What lives here is the platform half of the execution model -- the lattice a
discharge rate is quantized to, what a discharge *number* means once written,
the mode vocabulary, and the smallest gear that can be commanded. Turning a
planned action into a full command (mode + rate + reactive semantics) is 4b's
work and lands here too; 4a deliberately moves no candidate logic.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .dp_constants import POWER_CLASSIFICATION_THRESHOLD_KW
from .settings import BatterySettings

# ── Discharge-rate semantics (the tri-state) ─────────────────────────────────
#
# "Is a discharge rate a ceiling here?" is the question the optimizer actually
# needs (design §"Ceiling semantics are per-platform"), and it has three
# honest answers, not two -- the period-list platforms have no per-period rate
# to interpret at all, so folding them into "not a ceiling" would claim they
# execute a forced power command they cannot even be told.
DISCHARGE_RATE_CEILING = "ceiling"
"""The number is an upper bound: firmware delivers `min(number, actual load)`.
Growatt MIN via TOU registers, solax-modbus Growatt in TOU mode."""

DISCHARGE_RATE_TARGET = "target"
"""The number is a commanded power, delivered regardless of actual load.
SolaX native (`LOAD_SUPPORT -> -(rate% x max_discharge)`), solax-modbus
Growatt in VPP mode."""

DISCHARGE_RATE_ABSENT = "absent"
"""There is no per-period discharge rate at all -- behaviour is discrete
charge/discharge time slots. Growatt SPH, Solis, Huawei (`period_list`)."""

# ── Mode vocabulary ──────────────────────────────────────────────────────────
#
# Canonical intent -> battery mode map, shared by every TOU-register platform.
# `InverterController.INTENT_TO_MODE` is this object (see inverter_controller),
# so the controllers and the execution model cannot drift apart.
#
# Read-only on purpose. One dict is now shared by the module constant, the
# controller class attribute and every `PlatformCapabilities` default, so a
# single in-place write anywhere would silently rewrite the mode vocabulary
# for every platform at once. A `PlatformCapabilities` carrying a *different*
# vocabulary passes its own mapping instead of mutating this one.
INTENT_TO_MODE: Mapping[str, str] = MappingProxyType(
    {
        "GRID_CHARGING": "battery_first",
        "SOLAR_STORAGE": "load_first",
        "LOAD_SUPPORT": "load_first",
        "BATTERY_EXPORT": "grid_first",
        "SOLAR_EXPORT": "load_first",
        "IDLE": "load_first",
    }
)


def intra_period_discharge_gate(allowed: bool) -> int:
    """Intra-period discharge ceiling for a SOLAR_EXPORT, SOLAR_STORAGE, or
    LOAD_SUPPORT period.

    All three intents map to load_first; SOLAR_EXPORT/SOLAR_STORAGE plan
    discharge_rate=0, LOAD_SUPPORT plans a nonzero plan-scaled rate. In every
    case the battery can additionally cover an actual (sub-period) solar/load
    deficit beyond whatever was planned. Whether it SHOULD is economic: cover
    from battery only when the stored energy is worth less than buying from
    grid now.

    That comparison is made by the DP (`_record_marginal_value`), which owns
    the value function the marginal value comes from, and arrives here as
    ``decision.intra_period_discharge_allowed``. This function does not
    re-derive it: doing so from a ``shadow_price`` scalar could not tell a
    computed zero from a never-computed one, and opened the ceiling on absent
    data (#526).

    Returns 100 (allow discharge) or 0 (hold the reserve, buy the dip from
    grid).

    Relocated here from `battery_system_manager` by Phase 4a (D1) -- see the
    module docstring. Callers must gate it on
    `PlatformCapabilities.discharge_rate_is_load_following`: raising the
    ceiling only makes sense where the rate *is* a ceiling (#324).
    """
    return 100 if allowed else 0


@dataclass(frozen=True)
class PlatformCapabilities:
    """What the executing platform can express, as the optimizer needs to see
    it (D2: a separate object, not extra fields on `BatterySettings`).

    `BatterySettings` holds physical-battery facts sourced from user config;
    these are platform facts sourced from the active controller, with a
    different lifetime. `discharge_rate_is_load_following` already living on
    the controller rather than in settings is evidence the split is real.

    The defaults describe the TOU-register platform the DP has always
    implicitly assumed (integer-percent lattice, rate-as-ceiling), so a caller
    with no controller -- unit tests, the synthetic corpus, a manager without
    hardware -- gets exactly the pre-4a behaviour.

    Fields:
      `discharge_resolution_kw` -- smallest controllable discharge increment,
        or None for the platform default of 1% of `max_discharge_power_kw`.
        This is the value `InverterController.discharge_resolution_kw()`
        returns; None is kept distinct from a computed value so the DP's
        default and a platform's explicit declaration stay distinguishable.
      `discharge_rate_semantics` -- one of the three constants above. This is
        about the *rate register*: what a number written into it does.
      `load_support_delivers_exact_cover` -- a different question, with a
        different answer on one platform: is a planned LOAD_SUPPORT discharge
        delivered as `min(plan, actual load)`? That is what the off-lattice
        exact-cover candidate needs (`action_selector._residual_cover_p`).
        On solax-modbus Growatt in VPP mode the rate register is a forced
        power -- so `discharge_rate_is_load_following` is False -- but
        LOAD_SUPPORT never writes a rate there: #413 disables remote control
        for that intent and hands the period back to the inverter's own
        load-following self-use (`_intent_to_vpp`). A cover plan is delivered
        exactly, so this stays True. Native SolaX never received #413 (gap
        note in `solax_controller._vpp_display_state`), so its LOAD_SUPPORT
        really is a forced `-(rate% x max_discharge)` and it is False.
      `control_model` -- the controller's `CONTROL_MODEL`, carried so 4b can
        derive the command without reaching back to a controller class.
      `intent_to_mode` -- the mode vocabulary (read-only).

    Instances are not hashable: `intent_to_mode` is a mapping view, so the
    frozen dataclass's generated `__hash__` raises. Nothing keys on a
    capability object today; if something needs to, hash the scalars.
    """

    discharge_resolution_kw: float | None = None
    discharge_rate_semantics: str = DISCHARGE_RATE_CEILING
    load_support_delivers_exact_cover: bool = True
    control_model: str = "tou_register"
    intent_to_mode: Mapping[str, str] = field(default_factory=lambda: INTENT_TO_MODE)

    def __post_init__(self) -> None:
        if self.discharge_rate_semantics not in (
            DISCHARGE_RATE_CEILING,
            DISCHARGE_RATE_TARGET,
            DISCHARGE_RATE_ABSENT,
        ):
            raise ValueError(
                f"Unknown discharge_rate_semantics: "
                f"{self.discharge_rate_semantics!r}"
            )

    @property
    def discharge_rate_is_load_following(self) -> bool:
        """Does a written discharge rate act as a ceiling on this platform?

        This is the question the *rate register* asks, and the one the
        intra-period discharge gate needs: raising a ceiling to 100 is safe
        where the firmware throttles it back to the real deficit and forces a
        full-power discharge where it does not (#324). `absent` answers no --
        there is no rate to interpret as either.

        It is **not** the question the exact-cover candidate asks; see
        `load_support_delivers_exact_cover`. The two differ on solax-modbus
        Growatt in VPP mode, and conflating them was caught in review.
        """
        return self.discharge_rate_semantics == DISCHARGE_RATE_CEILING

    def discharge_rate_step_kw(self, battery_settings: BatterySettings) -> float:
        """Discharge percent-grid step (kW): the hardware executes discharge as
        an integer percent of `max_discharge_power_kw` unless a finer
        resolution is declared -- the lattice `_discharge_candidates`
        enumerates."""
        if self.discharge_resolution_kw is not None:
            return self.discharge_resolution_kw
        return battery_settings.max_discharge_power_kw / 100

    def min_discharge_gear_index(self, battery_settings: BatterySettings) -> int:
        """Lattice index (percent, on the default lattice) of the smallest
        discharge this platform can be commanded to make *and* have the rest
        of the system read as a discharge.

        Not simply 1: `classify_strategic_intent` treats any magnitude at or
        below `POWER_CLASSIFICATION_THRESHOLD_KW` as noise (postmortem #282),
        and that threshold is derived from the fixed `POWER_STEP_KW` rather
        than from the battery's own power, so on a battery with
        `max_discharge_power_kw <= 10 kW` one step can land inside it. The
        first commandable *gear* is therefore the first lattice index clear of
        the threshold.
        """
        rate_step = self.discharge_rate_step_kw(battery_settings)
        return math.floor(POWER_CLASSIFICATION_THRESHOLD_KW / rate_step) + 1

    def min_discharge_gear_kw(self, battery_settings: BatterySettings) -> float:
        """`min_discharge_gear_index` as a power (kW) -- the smallest lattice
        candidate. A net load below this cannot be covered by any lattice
        action; see `action_selector._residual_cover_p`."""
        return self.min_discharge_gear_index(
            battery_settings
        ) * self.discharge_rate_step_kw(battery_settings)

    @classmethod
    def from_controller(
        cls, controller: Any, battery_settings: BatterySettings
    ) -> "PlatformCapabilities":
        """Read the active controller's declarations into the object the
        optimizer is given.

        Typed `Any` deliberately: importing `InverterController` here would
        point this leaf back up at the controller layer, which is exactly the
        edge D1 removes. Every attribute read is part of the controller's
        published capability surface.
        """
        if controller.CONTROL_MODEL == "period_list":
            semantics = DISCHARGE_RATE_ABSENT
        elif controller.discharge_rate_is_load_following:
            semantics = DISCHARGE_RATE_CEILING
        else:
            semantics = DISCHARGE_RATE_TARGET
        return cls(
            discharge_resolution_kw=controller.discharge_resolution_kw(
                battery_settings.max_discharge_power_kw
            ),
            discharge_rate_semantics=semantics,
            load_support_delivers_exact_cover=(
                controller.load_support_delivers_exact_cover
            ),
            control_model=controller.CONTROL_MODEL,
            intent_to_mode=controller.INTENT_TO_MODE,
        )


DEFAULT_CAPABILITIES = PlatformCapabilities()
"""The platform the optimizer assumed before Phase 4a: an integer-percent
lattice whose discharge rate is a ceiling.

This is exactly what the pre-4a `discharge_resolution_kw=None` meant, and it
is what callers with no controller get -- unit tests, the synthetic corpus, a
`BatterySystemManager` constructed without hardware. It is a *stated default*,
not a fallback: where a controller exists its capabilities are read from it
(`from_controller`), and nothing degrades to this behind the caller's back.
"""
