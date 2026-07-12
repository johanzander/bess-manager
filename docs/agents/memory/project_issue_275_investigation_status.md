---
name: Issue #275 investigation status
description: #275's real defect was fixed in v9.9.0b13 (PR #279); the residual behavior was directly proven financially optimal, not a bug. #276/#285 closed.
type: project
---
#275 (Frank, #126) reported the DP holds battery charge past midnight and
sells it the next day at a known-worse price once a real 2-day price
horizon is in view.

**The real defect was fixed.** `v9.9.0b13` (PR #279) shrank `SOE_STEP_KWH`
(0.1→0.05) specifically to reduce Step 2's continuous-path-reconstruction
interpolation error, and it worked: held charge above the floor dropped
from 5.32 kWh to 3.90 kWh on the reported reproduction — a genuine, verified
27% reduction.

**What was wrong was a later assumption**: that more of the same
discretization error remained, motivating #276's two follow-ups — Approach
1 (#282, merged) and Approach 2 (#285). Direct investigation (2026-07-12,
full writeup in
`docs/superpowers/specs/2026-07-12-issue-275-root-cause-investigation.md`
and PR #286) found that assumption doesn't hold up:

1. Sweeping `SOE_STEP_KWH` 20x finer than b13's value doesn't shrink the
   residual at all.
2. Direct Bellman-optimality check at the exact decision point: the DP's
   chosen action is the true `reward + V[t+1]` maximum among every
   hardware-valid candidate, verified by computing all of them, not assumed.
3. Direct financial proof using Frank's own real prices/consumption/solar,
   verified through the actual hardware simulator (not just planning
   numbers): the current implementation beats a "drain fully tonight"
   hypothesis (matched to Frank's stated goal, not his scripts' actual
   unverified logic) by 0.756 EUR over 48h. Solar refills the battery to
   the *same* level before tomorrow's evening peak regardless of overnight
   reserve — the reserve provides zero extra capacity for that peak. The
   entire advantage comes from avoiding real overnight grid import: Frank's
   own posted debug bundle (`historical_periods`, `data_source: "actual"`)
   shows 3.89 kWh of measured consumption 00:00-07:00 on 12 July, closely
   matching the 4.37 kWh reserve held. (Careful: Frank's own separate claim
   of "~0.1 kWh/day" net import is over a different set of days, 2-11 Jul,
   under his own scripts' unverified behavior — this doesn't contradict
   that claim, it's a different measurement on a different night.)

**Status as of 2026-07-12**: #275, #276, #285 recommended closed. The real
defect was fixed in PR #279; the residual is proven financially optimal, not
an open defect. #282 remains merged as an independent hardware-safety/
accuracy fix (real bug found and fixed along the way: the DP's
discharge-candidate percent step can collide with
`decision_intelligence.py`'s classification threshold for small batteries,
causing real R≠P violations — unrelated to #275's symptom).

**Separate product follow-up worth considering**: the dashboard's "Net
Cost" shows only the current day's slice of a multi-day optimization, so a
plan that correctly redirects value to a better future price makes today's
number look worse with no visibility into the corresponding gain. This is
very likely what produced the original "Net Cost dropped" observation that
prompted the whole investigation chain — not a real loss, a display gap.

**How to apply**: before proposing or implementing any DP algorithm change
aimed at a similar "holds charge" report in the future, read the linked
design doc first — it contains a cheap, reusable reproduction script
(`scripts/repro_issue_275_worse_scenario.py`) and the financial-proof
methodology (Bellman-optimality check + realized-cost simulator comparison)
that settled this one, rather than re-deriving it from scratch.
