---
name: Issue #275 investigation status
description: #275's "DP holds charge, exports later at a worse price" symptom appears misdiagnosed — not a discretization bug. Approach 2 (#285) paused.
type: project
---
#275 (Frank, #126) reported the DP holds battery charge past midnight and
sells it the next day at a known-worse price once a real 2-day price
horizon is in view. #276 investigated two fix approaches assuming this was
a fixed-grid discretization/interpolation artifact in the DP's value
function: Approach 1 (#282, hardware-aware breakpoint enumeration in Step
2) merged, but made **zero measurable difference** on #275's own "Worse"
reproduction scenario.

Deeper investigation (2026-07-12, full writeup in
`docs/superpowers/specs/2026-07-12-issue-275-root-cause-investigation.md`
and PR #286) found the discretization premise doesn't hold up:

1. Sweeping `SOE_STEP_KWH` 20x finer (0.05 → 0.0025) doesn't shrink the
   held-charge symptom at all — an exact value function (what the proposed
   Approach 2 would give) is exactly the limit of that sweep, so Approach 2
   would very likely have the same null result Approach 1 already had.
2. The 2-day joint optimization beats naive myopic day-by-day optimization
   by a wide margin (0.57 out of ~0.68 total cost) — the DP is doing
   something economically sound, not something broken.
3. Direct SOE-trajectory tracing shows the overnight reserve drains to
   within 0.003 kWh of the floor before the next day's solar arrives — the
   later "export at a worse price" is fresh next-day solar with no earlier
   selling opportunity, not the carried-over charge.

**Status as of 2026-07-12**: #285 (Approach 2, exact piecewise-linear value
function) is paused pending #275 being re-diagnosed through a different
mechanism. #282 remains merged as an independent hardware-safety/accuracy
fix (real bug found and fixed along the way: the DP's discharge-candidate
percent step can collide with `decision_intelligence.py`'s classification
threshold for small batteries, causing real R≠P violations — unrelated to
#275's actual symptom).

**Why this matters**: don't re-invest in a discretization-based fix for
#275 without first re-running
`scripts/repro_issue_275_worse_scenario.py --verify-mechanism` (or an
equivalent trace) against fresh real data from the reporter, to check
whether the "worse price export" is still sourced from carried-over charge
or from fresh same-day solar. If it's the latter again, this may not be a
code bug at all — see the design doc for the reserve-then-solar-cycle
explanation.

**How to apply**: before proposing or implementing any DP algorithm change
aimed at #275, read the linked design doc first — it contains a cheap,
reusable reproduction script that makes re-testing hypotheses fast without
spinning up the full mock-HA/podman stack.
