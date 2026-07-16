# Investigation: #313's morning mistiming is a confirmed, quantified defect — root cause pinned, fix designed and validated

**Date**: 2026-07-16
**Status**: Investigation complete. Root cause pinned (missing DP action, not
value-function precision). Fix designed and validated against the real trace
via prototype. Not yet implemented in committed code.
**Related**: #313 (this issue, evidence gathered by the reporter), #126 (Frank's
original report), #275/#276/#285 (prior investigation lineage into the same
class of DP timing behavior — see
`docs/superpowers/specs/2026-07-12-issue-275-root-cause-investigation.md`,
which closed that batch as optimal; this doc reaches the opposite conclusion
for #313 on the strength of new evidence). #300 (a superficially similar user
report — confirmed unrelated, see "Relationship to #300" below; not pursued
further in this doc).

## Summary

Issue #313 documents that on 14 Jul, the DP schedule discharges 0.0375 kWh/period
at 07:00–11:30, selling at 0.102–0.131 EUR/kWh, instead of at a better available
price. Two analysis passes were run against this issue. The first pass concluded
"not a defect" using an argument that turned out to be incomplete. The second
pass — prompted by pushing on that argument's premise — empirically refutes the
"not a defect" conclusion. **This is a genuine, quantified defect: ~0.0218 EUR of
avoidable loss on this 129-period horizon, from picking a worse-priced slot for an
otherwise-necessary and correctly-sized action.**

## Pass 1 finding (superseded): "reporter's reference price is wrong"

The first pass observed that the reporter's comparison used 13-Jul 21:00
(sell=0.1564) as "the better price left unused," but the same price array has an
even better price 24h later at 14-Jul 21:00 (sell=0.1628), which the DP does
capture near-maximally (discharges up to 99% of max rate there). It also swept
`SOE_STEP_KWH` 10x finer (0.05→0.005) and found the ~0.5625 kWh mistimed-discharge
total unchanged — ruling out simple discretization error. From this it concluded
the residual was explainable by real round-trip cost (cycle wear + charge/
discharge efficiency loss) making immediate solar export better than store-and-
sell-later, the same disposition as #275/#276/#285.

**This was incomplete.** It correctly ruled out "sell now vs. hold for the 14-Jul
peak" as the relevant comparison, but never checked whether the *same necessary
action* (draining SOE to make headroom) could have been done at a different,
better-priced time instead of not at all. That is the question the user raised
directly, and pass 2 resolves it with a forward simulation.

## Pass 2: empirical test of the user's counterexample

**User's hypothesis, as posed:** since solar surplus reliably tops the battery
back up to 100% during the day regardless, holding the ~0.5625 kWh instead of
discharging it at 07:00–11:30 shouldn't cost anything — the cap gets hit anyway,
so why not just sell it at the actually-best price instead of dribbling it out
at a worse one?

### Step 1 — does withholding the dribble change the cap-hit time?

Built a physics-accurate forward simulation from the real 129-period trace,
using the real reward-function semantics (`core/bess/dp_battery_algorithm.py:_compute_reward`,
IDLE-branch passive solar charging capped by `(max_soe-soe)/efficiency_charge`,
no wear cost on discharge, `cycle_cost_per_kwh` on stored energy only). Battery
parameters taken from the trace: `max_soe_kwh=15.0`, `efficiency_charge=0.97`,
`efficiency_discharge=0.95`, `cycle_cost_per_kwh=0.035` (this user's actual
setting, not the code default of 0.40).

- **Actual trace** (with the 07:00–11:30 dribble): SOC hits the 15.0 kWh cap at
  **14:15** (period idx 90).
- **Counterfactual** (dribble periods forced to IDLE): SOC hits the cap at
  **11:45** (idx 80) — **2.5 hours earlier**.

So the user's premise that "solar fills it anyway" is technically true but
understates the effect: withholding the dribble does not just shift the cap-hit
by a few minutes, it opens up a 2.5-hour window (11:45–14:15) with real,
substantial solar surplus (0.72–0.90 kWh/period) that has to go somewhere.

### Step 2 — end-to-end financial comparison: dribble vs. no dribble at all

Simulated both trajectories fully (idx 61→128) with real solar/home/price data
and the real reward formula:

| | Export revenue | Wear cost | Net reward |
|---|---|---|---|
| Actual (with dribble) | 1.8767 | 0.2696 | **1.6072** |
| Counterfactual (no dribble, idle instead) | 1.7773 | 0.2488 | **1.5285** |

**Delta: +0.0787 EUR in favor of doing some form of the dribble.** Both
trajectories reconverge to identical SOE (7.0526 kWh) by end of horizon, and both
are pinned at the 15.0 kWh cap for hours before the 20:00–21:45 evening sale —
confirming the 21:00 discharge amount is capacity-bound and identical either way.
The gain comes from the 2.5 extra hours of solar surplus (11:45–14:15) that the
dribble frees up room to store instead of forcing into direct export at the
midday's cheap price (~0.09–0.10 EUR/kWh); that stored energy is cashed in later
at the 21:00 peak (0.1628 EUR/kWh). This spread comfortably exceeds the round-trip
loss (0.97×0.95≈0.92) and the 0.035 EUR/kWh wear cost.

**Conclusion: the "no purpose served" version of the user's counterexample is
refuted.** Creating headroom via a discharge before the midday solar surge is
genuinely necessary and valuable. The user's underlying instinct — that
something here is still priced wrong — was right, but not for the "no benefit
at all" reason; see step 3.

### Step 3 — is 07:00–11:30 the right slot for this necessary action?

Tested whether the same 0.5625 kWh of headroom-creating discharge could be
pulled forward to 13-Jul 21:00–21:45 instead (sell=0.1564, vs. 0.102–0.131
actually used) — the slot the original issue named, which the trace shows has
3.4 kWh of genuinely unused discharge headroom (inverter capacity 1.25 kWh/period
vs. 0.31–0.44 kWh/period actually drawn there).

Checked for side effects of moving it:
- Overnight grid import in the real trace is ~0 (0.0053 EUR across the entire
  129-period horizon) — no risk that extra draw-down forces costly grid import.
- Drawing an extra 0.592 kWh of SOE at 21:45 13-Jul leaves the trough SOE at
  7.456 kWh through the rest of the night (vs. actual 8.05 kWh) — nowhere near
  any floor (47%), no new constraint triggered.
- The headroom-creation purpose is preserved identically: the battery reaches
  the same lower SOE by 06:00 14-Jul, so the same capture of the midday solar
  surplus and the same 14:15 cap-hit / 21:00 sale still happen.

**Net effect of moving the same action to the better-priced slot: +0.0218 EUR
gain, zero offsetting cost — a strict Pareto improvement.** This matches the
number in the original issue, now verified with the side effects explicitly
checked (not assumed away).

## Why this is not the same as #275/#276/#285

The #275 investigation's residual was proven Bellman-optimal: at the actual
decision point, the DP's chosen action was verified to be the exact maximum of
`reward + V[t+1]` over every hardware-valid alternative, and the financial
comparison against Frank's proposed alternative showed the DP's plan winning.
That is not what's shown here for #313. Here, both the actually-used slot
(07:00–11:30) and the better-priced alternative slot (13-Jul 21:00–21:45) are
inside the *same* 129-period DP horizon — the algorithm has full visibility into
both simultaneously. This rules out a horizon-truncation/foresight explanation.
The DP is choosing a valid, necessary action (create headroom before the midday
solar surge) but placing it in a worse-priced slot when a strictly better,
side-effect-free slot was available and visible the whole time. That is a
search/value-function precision defect, not an optimal trade-off.

## Pass 3: ruling out value-function precision as the mechanism

Two candidate fixes matching the prior #275/#276 lineage were prototyped
against the real 129-period trace, to check whether this is the same class of
grid/interpolation-precision issue that #275 turned out to be:

- **Approach 1, finished properly**: replaced the backward pass's fixed
  `POWER_STEP_KW` grid search with the same breakpoint-enumeration candidate
  generator the forward reconstruction already uses (shipped for the forward
  pass in PR #282/#284, never applied to the backward pass). Measured: **0%
  reduction** in the mistimed-discharge total, at ~150-165x backward-pass
  runtime cost.
- **Approach 2 proxy**: a 10x finer `SOE_STEP_KWH` grid (1592 vs 159 states) as
  a numerical stand-in for exact piecewise-linear `V` propagation. Measured:
  **0% reduction**, ~1600x runtime cost. Breakpoint density near the decision
  cell (56/kWh) matched the same order of magnitude found in the original
  #276 design-doc prototype, so this real solar-heavy trace isn't a special
  case — the earlier `SOE_STEP_KWH` sweep from Pass 1 (which showed a 73%
  reduction) was a false lead: that sweep was incidentally shrinking a
  hardware discharge-floor threshold derived from the same constant, not
  improving value-function precision. Holding that threshold fixed while
  properly refining the grid changes nothing.

**Conclusion: this is not a search/value-function precision defect.** Both
established fix directions from the #276 lineage were built for real and
measured zero effect. The mechanism is elsewhere.

## Pass 4: the actual mechanism — a missing action, not a precision gap

Digging into *why* neither prototype moved the residual: `_compute_reward`'s
branch structure ties two decisions to a single `power` variable's sign —
whether solar surplus routes into the battery (IDLE branch) or bypasses
directly to grid export (discharge branch) is decided purely by whether
`power` is exactly zero or nonzero. The instant any discharge is chosen,
however small, solar routing to the battery switches off entirely for that
period. This creates a genuine reward *jump* at `power=0` whenever solar
surplus exists (measured +0.016 to +0.084 EUR/period across the mistimed
window) — not a kink any grid resolution can resolve, because it isn't an
interpolation error.

The real defect: the DP's action space conflates two logically separate
decisions — (a) whether to let solar bypass the battery this period, and (b)
how much *extra* battery SOE to drain — into one continuous `power` variable.
Whenever (a) is worth doing (e.g. to free room for incoming solar), the DP is
forced to also decide (b) in that same period, rather than being able to defer
the drain-amount decision to whichever period has the best price while still
capturing the bypass benefit as soon as it's warranted.

## Pass 5: fix designed and validated

**A distinct third action** — "solar bypasses to grid, battery completely
untouched (`next_soe == soe`)" — was added to a scratch DP prototype alongside
the existing IDLE/STORE/discharge candidates, vectorized (one extra
O(n_states) column, not O(n_states×actions)).

Result against the real 129-period trace:

| | Backward-pass time | Mistimed dribble | Total profit |
|---|---|---|---|
| Baseline (production) | 0.0241s | 0.5625 kWh | 2.0532 EUR |
| + third candidate (vectorized) | 0.0244s (**1.01x**) | **0.0000 kWh (100% eliminated)** | **2.0839 EUR (+0.0307)** |

The legitimate headroom-creation drain is preserved, just correctly repriced:
at 13-Jul 21:00–21:45 (the better slot identified in Pass 2), discharge rises
from 0.786→1.7235 kWh; end-of-horizon SOE is bit-identical (7.0526 kWh) either
way — same energy trajectory, better timing. This is a clean, near-zero-cost
fix, not a hack.

### Existing intent, not a new one

`StrategicIntent.SOLAR_EXPORT` (`dp_battery_algorithm.py:107`, "Solar surplus
exporting to grid, battery idle") already names this exact state and already
appears in `classify_strategic_intent` (`decision_intelligence.py:454-459`).
Today it only ever falls out when the battery happens to be at 100% SOC
(`battery_charged` is naturally 0 with no room left) — an emergent side
effect of being full, never a state the DP can deliberately choose while
there's still headroom. The fix makes an *existing* intent genuinely
selectable, rather than introducing a new concept.

### Hardware mapping: no mode change needed

Initial framing (superseded, see below) assumed this needed a mode switch to
`grid_first` + `discharge_rate=0`, and treated that as a hardware-capability
question requiring outside confirmation. Checking `inverter_controller.py`
directly shows this is unnecessary:

- `LOAD_SUPPORT` and `BATTERY_EXPORT` already set `charge_rate=0` while
  discharging (`INTENT_TO_CONTROL`, `inverter_controller.py:34-49`) — a
  proven, already-relied-upon primitive for blocking passive solar→battery
  routing, independent of `mode`.
- Today's `SOLAR_EXPORT`/`IDLE` mapping sets `charge_rate=100,
  discharge_rate=0` — `charge_rate=100` is backwards for what `SOLAR_EXPORT`
  is supposed to mean, which is exactly why it's indistinguishable from
  `IDLE` today.
- **The fix is one value**: `SOLAR_EXPORT → charge_rate=0, discharge_rate=0`,
  `mode` stays `load_first` (`INTENT_TO_MODE` unchanged). No mode switch, and
  this also sidesteps the unrelated `grid_first` self-consumption-drain
  behavior independently reported in #300.
- **Cross-platform gating already exists**: `supports_charge_rate_control`
  (`inverter_controller.py:77`) is `True` by default (Growatt MIN cloud +
  GEN4 modbus — the two real-world-tested platforms) and already overridden
  `False` on `GrowattSphController` (GEN3, `growatt_sph_controller.py:37`) and
  `SolaxController` (native VPP, `solax_controller.py:51`), both of which
  bake rates into atomic TOU writes instead of exposing a per-period lever.
  The DP's new `SOLAR_EXPORT`-below-max candidate should be gated on this
  same, already-existing flag — no new capability concept needed.

## Relationship to #300 (ruled out, not pursued further)

#300's reporter describes battery drain during solar export and proposes a
fix that superficially resembles this one. Checked directly: #300's own
debug bundle shows `select_option` calls failing with repeated 500 errors and
a required sensor entity 404ing for the entire period in question — BESS had
no control authority that day; the "Intent" column shows `IDLE` commanded
throughout while the inverter did its own thing independent of any command.
#300 is a control-authority/integration failure, unrelated to #313's DP
reward-function defect, and is being tracked separately.

## Confidence

- **High**: the headroom-creation purpose is real (Pass 2, direct simulation).
- **High**: the specific timing is suboptimal relative to an available,
  side-effect-free, better-priced slot — verified by direct simulation.
- **High**: this is not a value-function/discretization precision issue —
  both established fix directions from the #276 lineage were built for real
  and measured zero effect (Pass 3).
- **High**: the actual mechanism (solar-routing/drain-amount conflation at
  `power=0`) and the fix (third DP action + one-value mapping change) are
  confirmed by a working prototype that eliminates the defect at ~1x runtime
  cost (Pass 5), not inferred.

## Conclusion

#313 is a real, quantified defect caused by a missing action in the DP's
model, not by search/value-function imprecision (ruled out directly, unlike
#275/#276/#285 where refining precision was the right direction). The fix —
add a `SOLAR_EXPORT`-below-max candidate to the DP, and correct
`SOLAR_EXPORT`'s `charge_rate` mapping from 100 to 0 — is small, cheap,
validated against the real trace, reuses an existing intent and an existing
hardware-capability flag, and requires no new mode plumbing.

## Recommendation

Proceed to implementation (PR). Scope:

1. `core/bess/dp_battery_algorithm.py`: add the third candidate/reward branch
   to `_compute_reward`/`_compute_reward_grid`, `_run_dynamic_programming`
   (backward pass), and `_best_action_at_continuous_state`/
   `_discharge_candidates` (forward reconstruction) — gated on
   `supports_charge_rate_control`.
2. `core/bess/inverter_controller.py`: change `INTENT_TO_CONTROL["SOLAR_EXPORT"]`
   `charge_rate` from `100` to `0`. `INTENT_TO_MODE` unchanged.
3. `classify_strategic_intent` (`decision_intelligence.py`): no change needed —
   already classifies this state correctly.
4. Test surface to verify (broad — the new candidate competes in every period
   with solar surplus, not just this trace's window): `test_surplus_disposition.py`
   (explicitly documents today's binary IDLE-vs-discharge disposition as
   "CURRENT" behavior under #145 — must be deliberately updated, not
   accidentally broken), `test_idle_solar_charging.py`,
   `test_solar_export_discharge_gate.py`, `test_dp_no_guardrails.py`,
   `test_dp_breakpoint_search.py`, `test_optimization_algorithm.py`,
   `test_below_min_soe_intent.py`, `test_scenarios.py`,
   `test_quarterly_vs_hourly.py`, `test_terminal_value.py`,
   `test_plan_faithfulness.py` (R==P suite), `test_battery_system_core.py`,
   `test_cost_savings_flow.py`. Full pinned-fixture suite run required before
   merging, not just the #313 repro.

## Out of scope for this doc

- The actual code change — this remains a diagnosis/design doc; implementation
  happens in a PR.
- #300's integration failure (`select_option` 500s, missing sensor entity) —
  tracked separately, not part of this fix.
- GEN3/SolaX capability confirmation beyond the existing
  `supports_charge_rate_control` flag — trusted as already-correct per the
  codebase's existing platform-capability design; not independently
  re-verified against real GEN3/SolaX hardware in this investigation.
