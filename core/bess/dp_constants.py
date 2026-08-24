"""Shared discretization constants for the DP battery optimizer.

Single source of truth for the DP's state/action grid resolution. Imported by
both dp_battery_algorithm.py (which uses them to build the state/action grid)
and strategic_intent.py (which needs a "is this action real or just
floating-point noise" threshold that scales with the grid, not a hardcoded
absolute value).

Postmortem (#275): strategic_intent.py used to hardcode
`_POWER_THRESHOLD_KW = 0.1` with a comment noting "The DP uses
POWER_STEP_KW=0.2" -- an implicit, unenforced assumption. Tuning
POWER_STEP_KW to 0.1 during the #275 investigation silently collided with
that hardcoded threshold: the smallest nonzero grid action (exactly 0.1)
failed the classifier's strict `power > 0.1` check, so real grid-charging
actions fell through to a passive-charging fallback and were misclassified
as SOLAR_STORAGE -- which then produced a ~21 SEK realized-vs-planned gap,
since the hardware-command mapper trusts the (wrong) intent label. Deriving
the classification noise-floor from POWER_STEP_KW here means any future grid
resolution change can't reintroduce that exact class of bug.

Not to be confused with dp_battery_algorithm.py's own POWER_TOLERANCE_KW
(a fixed, tiny floating-point epsilon used internally by the DP's backward
search to distinguish "exactly zero" from "any nonzero grid value" -- that
one must stay far smaller than any real grid step regardless of resolution,
so it is not derived from POWER_STEP_KW and is not defined here).
"""

# State space: State of Energy grid resolution (kWh). Matched to
# POWER_STEP_KW * 0.25h (the quarterly-period reachable-state increment, the
# production resolution -- see battery_system_manager.py) so V is sampled
# only at states a single action can actually reach; a finer SOE_STEP_KWH
# than that makes shadow_price report jagged/incorrect values at intermediate
# grid points that aren't independently reachable (verified empirically during
# the #275 Option B investigation). Note this equality is also what makes V a
# staircase in the discharge-limited regime, which is why the shadow price is
# read across a whole delivery's worth of SoE rather than one cell (#683).
#
# Resolution history: 0.2 kW / 0.05 kWh until #512, whose full-corpus
# benchmark showed the coarser grid's value-function discretization left
# 0.01-0.36 SEK/day unrealized on 19/33 fixtures vs a horizon-spanning
# exact-PWL bound.
#
# Every figure below is from one measurement run over the 35-fixture
# corpus (PR #516 head vs the #511 merge base), realized cost through the
# inverter simulator -- not planned cost, and not several runs stitched
# together. Halving both steps (keeping the reachable-state invariant
# above) recovers 2.43 SEK/day: 26 fixtures better, 8 worse, 1 unchanged,
# worst single-fixture regression +0.0498 -- inside, but only just inside,
# the 0.05 SEK/fixture budget in
# docs/superpowers/plans/2026-08-09-optimizer-target-architecture.md.
# Planned and realized deltas agree to 0.001 SEK because #497/#511 made
# R == P structural. It also *reduces* solve latency (corpus 15.2s ->
# 11.2s, worst single fixture 4.79s -> 1.81s): a finer grid produces fewer
# near-ties for the #450 hybrid PWL re-solve to fire on, which more than
# offsets ~4x the backward-induction work.
#
# A further halving (0.05 kW / 0.0125 kWh) was measured in the same run
# and rejected on the budget, not on cost: it recovers 25% more
# (3.03 SEK/day) at 2.3x the latency, but breaches the 0.05 SEK/fixture
# budget on two fixtures (+0.0671 realworld_2026_04_27_211212, +0.0651
# synthetic_clear_sky_ac_clipping). Grid refinement is not per-fixture
# monotone, so a finer grid is not automatically safer -- any future
# refinement has to re-measure the per-fixture tail, not just the total.
SOE_STEP_KWH = 0.025

# Action space: power grid resolution (kW).
POWER_STEP_KW = 0.1

# Noise floor for intent classification: "is this action big enough to be a
# real, DP-chosen grid action, or a negligible residual." Set to half the
# grid step so it always sits strictly between the smallest possible nonzero
# grid action (POWER_STEP_KW) and genuine floating-point noise (observed in
# practice: ~1e-10 to 1e-14), regardless of how POWER_STEP_KW is tuned.
POWER_CLASSIFICATION_THRESHOLD_KW = POWER_STEP_KW / 2

# GRID_FLOW_RESOLUTION_KWH lives in models.py: it describes a property of the
# measurement layer (Home Assistant's lifetime counters), not of the DP -- the
# optimizer imports it from there (#497 review follow-up).

# Relative band for comparing a price against a shadow price (#602).
#
# `shadow_price` is a finite difference of the value function, so it carries V's
# accumulated rounding divided by the SoE step -- roughly a machine epsilon per
# backward step, over horizons of ~100 periods. This is that bound with headroom,
# not a tuned preference: it must swallow differencing noise and nothing that
# could change a decision. The smallest real price difference in any observed
# market is ~1e-4 SEK/kWh, eight orders of magnitude above this.
#
# It exists because the concave terminal row makes exact ties structural rather
# than occasional: the head segment gives V a constant slope equal to
# `median(buy_prices)`, and a median is by construction an element of the array
# it is taken over -- so every period whose buy price attains the horizon median
# ties against its own shadow price to the last bits. Measured on
# `realworld_2026_04_22_202249` period 85: buy 2.60425 vs shadow
# 2.60425000000005, a 5e-14 gap that closed the discharge gate.
SHADOW_PRICE_NOISE_REL = 1e-12
