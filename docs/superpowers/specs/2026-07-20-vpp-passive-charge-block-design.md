# Design: hardware-agnostic "block passive charging" signal for `InverterController` (#355)

**Date**: 2026-07-20
**Status**: Implemented (`block_passive_charging` threaded through
`InverterController.apply_period`; `SolaxModbusGrowattController` VPP mode
acts on it; `SolaxController` accepts the parameter but is unchanged, per
"Effect summary" below). Not yet shipped/merged. VPP-spec command table
below is register-verified against the vendor protocol document; the
runtime firmware behavior of the `grid first` realization is **not**
hardware-verified — see "Open question" at the end. Ships experimental,
pending confirmation from ridax67's beta debug export.
**Related**: #355 (this issue — VPP mode `SOLAR_EXPORT` refills the battery
from solar instead of holding it), #313 (established the `SOLAR_EXPORT`-
below-max DP candidate and the `charge_rate=0` blocking mechanism, TOU-only),
#324/#326 (VPP forced-power vs. load-following distinction —
`discharge_rate_is_load_following`), #320
(`docs/superpowers/specs/2026-07-16-issue-320-platform-capability-abstraction-design.md`
— establishes the capability-method pattern this design extends), #118
(original VPP control-mode design), #308 (VPP has no EMS rate/stop-SOC
entities).

## Problem

Every VPP-mode bug this quarter (#324, #326, the un-wired #313 gate, and now
#355) traces back to the same architectural gap: `InverterController`'s
shared intent→hardware mapping was designed around **register-based**
hardware (Growatt TOU/cloud, SPH) and silently drops information that
**forced-power** hardware (SolaX native VPP, `solax_modbus` Growatt VPP mode)
needs to behave correctly.

Concretely, two parallel channels currently carry a period's control signal
from `BatterySystemManager` to hardware:

1. **`apply_period(controller, grid_charge, discharge_rate)`** — called every
   period from `_apply_period_schedule` (`battery_system_manager.py:2614`).
   Carries only `grid_charge` (bool) and `discharge_rate` (0-100%). The
   strategic intent that produced these two values is discarded before this
   call — `_map_intent_to_rates` (`inverter_controller.py:177-206`) is a
   lossy compression, not an invertible mapping: `SOLAR_STORAGE`,
   `SOLAR_EXPORT`, and `IDLE` all reduce to the *identical* tuple
   `(grid_charge=False, discharge_rate=0)`.
2. **`adjust_charging_power()`** (`battery_system_manager.py:3060-3087`) —
   called separately, every period, and is the *only* channel that currently
   distinguishes "block passive solar→battery charging"
   (`SOLAR_EXPORT`, `charge_rate=0`) from "allow it"
   (`SOLAR_STORAGE`/`IDLE`, `charge_rate=100`). It works by writing a
   dedicated EMS `charging_power_rate` register, gated by
   `supports_charge_rate_control`
   (`inverter_controller.py:85`, already `False` for VPP-style controllers,
   `#308`/`#320`).

For TOU/register hardware, channel 2 is sufficient: `charge_rate=0` really
does block passive charging on that hardware (`docs/agents/bess-knowledge.md`
/ `inverter_controller.py:31-37`, the #313 design assumption). **VPP-style
hardware has no equivalent register at all** — `supports_charge_rate_control`
returns `False` precisely because there is nothing to write. That means the
"block vs. allow passive charging" signal that `SOLAR_EXPORT` vs.
`SOLAR_STORAGE`/`IDLE` needs to convey is simply lost for these controllers:
it's computed, gated off by the capability check, and never delivered by any
other path. `SolaxModbusGrowattController._intent_to_vpp`
(`solax_modbus_growatt_controller.py:256-270`) and `SolaxController`'s
equivalent both currently map *all three* intents to the same VPP command
(`vpp_power=0, remote_control=Disabled` → firmware self-use), because
channel 1 is all they ever receive and channel 1 can't distinguish them
either.

This is not a one-off bug — it's the class of bug this architecture will
keep producing for any future forced-power/SM-Ephemeral platform
(`docs/INVERTER_PLATFORMS.md`'s Axis 2) until the missing signal is made
explicit and threaded through, rather than rediscovered and patched per
symptom (#324 discovered the load-following gap, #326 wired one gate, this
is the block-passive-charging gap).

## VPP protocol confirmation

Re-derived directly from
[`GROWATT VPP COMMUNICATION PROTOCOL OF INVERTER V2.01`](https://github.com/user-attachments/files/18301858/2.1.GROWATT.VPP.COMMUNICATION.PROTOCOL.OF.INVERTER_V2.01.pdf)
(2024-9-20), the spec linked from issue #118, §2.1 (register table)
and §3.5 ("Remote power control schematic diagram", p.32) — not from the
`solax_modbus` HA integration layer, which only exposes a subset of these
registers as entities (`vpp_status`/30100, `vpp_remote_control`/30407,
`vpp_time`/30408, `vpp_power`/30409, `vpp_allow_ac_charging`/30410 — verified
against `wills106/homeassistant-solax-modbus`'s `plugin_growatt.py`; no
separate `charge_enable`/`discharge_enable`/`export_limit` entities exist at
the HA level, despite an earlier informal note in issue #118 suggesting a
three-lever model — that model isn't what actually shipped in the
integration this codebase talks to).

§3.5's documented logic, with `vpp_status`(30100)=`Enabled` and
`vpp_remote_control`(30407)=`Enabled`:

> `vpp_power`(30409) **> 0 → battery first** (charge); **≤ 0 → grid first**
> (discharge/export priority)

With `vpp_remote_control`(30407)=`Disabled`, the inverter falls through to
either a 20-slot on-device schedule (`30411-30471`, not exposed by
`solax_modbus` as entities — out of scope) or, if none is configured,
**`load first`** (native self-use — battery-first for any solar surplus).

| Strategic intent | Desired physical behavior | VPP command | Registers | Status |
|---|---|---|---|---|
| `GRID_CHARGING` | Force charge at rate | `remote_control=Enabled`, `vpp_power=+rate%`, `allow_ac_charging=Enabled` | 30407, 30409, 30410 | Implemented, correct — `>0` → `battery first`, matches spec |
| `LOAD_SUPPORT`/`BATTERY_EXPORT` (rate>0) | Force discharge at rate | `remote_control=Enabled`, `vpp_power=-rate%` | 30407, 30409 | Implemented, correct — `≤0` → `grid first`, matches spec |
| `SOLAR_STORAGE` | Battery opportunistically absorbs solar surplus (no forced target) | `remote_control=Disabled` → native `load first` self-use | 30407 | Implemented, correct today (already what happens at `discharge_rate=0`) |
| `IDLE` | No strong signal; self-use is a safe default | `remote_control=Disabled` → native `load first` | 30407 | Implemented, correct today |
| `SOLAR_EXPORT` | Battery held flat; solar bypasses to grid | `remote_control=Enabled`, `vpp_power=0` → documented `grid first` | 30407, 30409 | **Not implemented — this is the bug.** Currently maps to the same `remote_control=Disabled` self-use as `SOLAR_STORAGE`/`IDLE`, which is what lets solar recharge the battery in #355 |

The fix for `SOLAR_EXPORT` specifically is: keep `remote_control` **enabled**
and command `vpp_power=0`, landing in the spec's documented `grid first`
state, instead of disabling remote control into `load first` self-use.

**Why this can't be a blanket `discharge_rate==0 → grid first` change**
(the shortcut considered and rejected during this investigation): that would
also flip `SOLAR_STORAGE` into `grid first`, defeating its purpose (it wants
the battery to *absorb* solar, not hold flat). The three intents need a real
disambiguating signal, not a rate-based heuristic — hence the design below.

## Design

### 1. New capability-realized signal, not a new capability flag

Following the #320/#326 precedent (capability methods on `InverterController`
with defaults equal to today's behavior, overridden per platform), this adds
one new piece of information to the per-period hardware write, computed once
in the shared base class from intent — not a new `ClassVar` capability flag,
because *every* platform needs to receive this signal; only *how* they act on
it differs.

```python
# inverter_controller.py — INTENT_TO_CONTROL already encodes this; expose it
# explicitly instead of only deriving charge_rate==0 for the separate
# adjust_charging_power() channel.

def compute_rates_for_period(
    self, period: int, battery_action_kw: float
) -> tuple[bool, int, bool]:
    """Map strategic intent for a period to hardware control rates.

    Returns:
        Tuple of (grid_charge, discharge_rate_percent, block_passive_charging)
    """
    intent = self.strategic_intents[period]
    grid_charge, discharge_rate = self._map_intent_to_rates(intent, battery_action_kw)
    block_passive_charging = self.INTENT_TO_CONTROL[intent]["charge_rate"] == 0
    return grid_charge, discharge_rate, block_passive_charging
```

`block_passive_charging` is `True` exactly for the intents whose
`INTENT_TO_CONTROL["charge_rate"]` is already `0` today
(`LOAD_SUPPORT`, `BATTERY_EXPORT`, `SOLAR_EXPORT`) and `False` for the rest
(`GRID_CHARGING`, `SOLAR_STORAGE`, `IDLE`) — no new table, this reads the
existing `INTENT_TO_CONTROL` map that register-based platforms already use
for `adjust_charging_power()`. `LOAD_SUPPORT`/`BATTERY_EXPORT` already force
an active discharge whenever `discharge_rate>0`, so the flag is a no-op for
them in practice; it only changes behavior where `discharge_rate==0`, i.e.
exactly the `SOLAR_EXPORT` vs. `SOLAR_STORAGE`/`IDLE` split this design
exists to fix.

### 2. Thread it through `apply_period`

```python
# inverter_controller.py
def apply_period(
    self, controller, grid_charge: bool, discharge_rate: int,
    block_passive_charging: bool = False,
) -> tuple[bool, str]:
    return self._write_period_to_hardware(
        controller, grid_charge, discharge_rate, block_passive_charging
    )
```

Default `False` keeps every existing call site and test that doesn't pass it
compiling unchanged (matches the #320 precedent's "optional, defaulting to
today's literal value" approach). `BatterySystemManager._apply_period_schedule`
(`battery_system_manager.py:2614`) is the one production call site updated to
pass the third value from `compute_rates_for_period`.

**Register-based controllers ignore the new parameter** — they already
realize this via the separate `adjust_charging_power()`/`charge_rate`
channel, which is correct and unchanged. `InverterController._write_period_to_hardware`
(`inverter_controller.py:491-525`, the shared default used by
`GrowattMinController`/`GrowattSphController`) keeps its current two-arg
hardware write; the new parameter is accepted but unused there, exactly like
`discharge_rate_is_load_following` is already `True`/unused-in-effect for
these same controllers.

**VPP-style controllers act on it.** `SolaxModbusGrowattController._apply_period_vpp`
and `_intent_to_vpp` (`solax_modbus_growatt_controller.py:256-296`):

```python
def _intent_to_vpp(
    self, grid_charge: bool, discharge_rate: int, block_passive_charging: bool,
) -> tuple[int, bool]:
    """Map (grid_charge, discharge_rate, block_passive_charging) to
    (power_pct, remote_control_enabled).

    - grid_charge=True                      -> +100% (charge at max rate)
    - grid_charge=False, rate>0              -> -rate% (discharge/export)
    - grid_charge=False, rate=0, block=True  -> 0%, remote control ENABLED
      (spec: vpp_power<=0 with remote control enabled -> grid first, holds
      the battery instead of self-use absorbing solar — SOLAR_EXPORT)
    - grid_charge=False, rate=0, block=False -> 0%, remote control DISABLED
      (load_first self-use — SOLAR_STORAGE/IDLE, battery may absorb solar)
    """
    if grid_charge:
        return 100, True
    if discharge_rate == 0:
        return 0, block_passive_charging
    return -discharge_rate, True
```

`SolaxController` (real SolaX hardware, `solax_controller.py`) has the
*same architectural gap* — `discharge_rate=0` unconditionally calls
`set_solax_vpp_disabled()` regardless of intent, identical to
`SolaxModbusGrowattController`'s bug. **This design does not change
`SolaxController`'s behavior**, though: unlike Growatt, no SolaX vendor
protocol document has been checked here to confirm what command (if any)
achieves a "hold, don't absorb solar" state on real SolaX hardware — the
Growatt fix above is grounded in a register table verified against the
actual vendor spec; extending the same fix to SolaX without equivalent
verification would be exactly the kind of unverified assumption
`CLAUDE.md`'s Verification Before Action rules exist to prevent. SolaX VPP
is also still experimental/not real-world-validated per
`docs/agents/memory/project_platform_maturity.md`, with no open user report
analogous to #355 today. `SolaxController._write_period_to_hardware` gets
the new `block_passive_charging` parameter for signature consistency only
(accepted, currently unused) — flagged as a known, likely-real, follow-up
gap, not fixed speculatively in this PR.

### 3. Effect summary per controller

| Controller | Change |
|---|---|
| `GrowattMinController` (cloud TOU) | None — new parameter accepted, unused |
| `GrowattSphController` (cloud SPH) | None — new parameter accepted, unused |
| `SolaxModbusGrowattController`, `control_mode="tou"` | None — TOU mode already uses the register channel |
| `SolaxModbusGrowattController`, `control_mode="vpp"` | **Behavior change**: `SOLAR_EXPORT` now commands `grid first` hold instead of `load first` self-use |
| `SolaxController` (SolaX native VPP) | None in this PR — parameter accepted, not acted on; same underlying gap suspected but not spec-verified, tracked as follow-up |

## Testing

- **Refactor-safety**: existing tests for `GrowattMinController`/
  `GrowattSphController`/TOU-mode `SolaxModbusGrowattController` pass
  unchanged with the new parameter defaulted — proves this is behavior-
  preserving for every register-based platform.
- **`_intent_to_vpp` unit tests** (extends
  `core/bess/tests/unit/test_solax_modbus_growatt_vpp.py`): replace
  `test_idle_disables_remote_control` (currently asserts
  `enabled is False` for *all* `discharge_rate=0` calls — this assumption is
  what this design corrects) with two cases:
  - `block_passive_charging=False` (SOLAR_STORAGE/IDLE) → `(0, False)`,
    unchanged from today.
  - `block_passive_charging=True` (SOLAR_EXPORT) → `(0, True)`, the new
    behavior.
- **End-to-end regression** for the #355 scenario: reconstruct periods 34-36
  from `bess-debug-2026-07-20-090503.md` (the attached bundle) — `SOLAR_EXPORT`
  at period 35 should now write `remote_control=Enabled, vpp_power=0`
  instead of `remote_control=Disabled`.
- **`SolaxController` signature test**: confirms `_write_period_to_hardware`
  accepts the new parameter without behavior change (still calls
  `set_solax_vpp_disabled()` at `discharge_rate=0` regardless of
  `block_passive_charging`) — proves this PR is a deliberate no-op there,
  not an oversight.

## Open question — requires real-hardware validation, not assumable from the spec

Whether the inverter's `grid first` priority mode, entered via a *forced*
`vpp_power=0` command, holds the battery exactly flat (SOE unchanged,
100% of solar routed to load then grid) the same way TOU's `grid_first` mode
does. This is not a purely theoretical gap: TOU's `grid_first` is *only* ever
used with an active nonzero forced discharge (`BATTERY_EXPORT`) in this
codebase — there is no existing, already-validated code path exercising
`grid_first` with a *zero* target, VPP or TOU. The register table documents
mode *selection* logic; it does not document the runtime power-flow
guarantee for the zero-target case. Per the plan discussed on issue #355,
this ships as a beta build for `ridax67` (already running the beta channel,
real Growatt MID/MIN hardware with solar) to validate via a normal debug
export from a morning with solar surplus after a `SOLAR_EXPORT` period —
watching for SOE staying flat instead of climbing.

## Non-goals

- The 20-slot on-device schedule (`30411-30471`) is not exposed by
  `solax_modbus` as HA entities and is out of scope — VPP mode stays
  ephemeral/per-period (`SM-Ephemeral`, matching `SolaxController`'s existing
  model), not a persistent on-device schedule.
- No change to `SOLAR_STORAGE`'s actual charge magnitude on VPP hardware —
  it continues to rely on native self-use choosing how much solar to absorb,
  the same as today. Forcing a derived positive `vpp_power` for `SOLAR_STORAGE`
  (rather than self-use) is a separate, larger design question (would need
  real-time solar-surplus estimation per period) and is not attempted here.
- `charge_rate`-register platforms (TOU, SPH, cloud) are unaffected and
  unchanged — this design only closes the gap for forced-power/SM-Ephemeral
  hardware.
