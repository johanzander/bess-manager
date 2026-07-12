# Investigation: #275's "export at a worse price" symptom is likely a misdiagnosis

**Date**: 2026-07-12
**Status**: Investigation complete — recommend pausing #276 Approach 2 (#285)
pending re-diagnosis; no code changes made in this doc
**Related**: #275 (original symptom, Frank #126), #276 (Approach 1/2 investigation),
#282 (Approach 1, merged, verified independent of this finding), #285 (Approach 2,
paused as a result of this investigation)

## Context

#282 (Approach 1 of #276 — hardware-aware breakpoint enumeration in the DP's
Step 2 reconstruction) was tested directly against #275's own "Worse"
reproduction scenario (Frank's real battery/prices/consumption/solar from
#126, tomorrow's price peak deliberately dulled ~21% below tonight's). It
made **zero measurable difference**: SOE held past midnight was bit-identical
to Option B alone (10.947 kWh either way). That result prompted this deeper
investigation, using a cheap, container-free reproduction
(`scripts/repro_issue_275_worse_scenario.py`) built directly on
`optimize_battery_schedule` rather than the full mock-HA/podman stack.

## Finding 1: this is not a discretization/interpolation artifact

Both #282 (Approach 1) and the proposed Approach 2 (#285, exact
piecewise-linear value-function tracking) share a premise: that #275's
symptom comes from the DP's value function `V` being approximated on a fixed
`SOE_STEP_KWH` grid. An exact value function is mathematically the limit of
that grid spacing going to zero — so sweeping `SOE_STEP_KWH` across a wide
range and checking whether the symptom shrinks toward zero is a direct,
cheap test of that premise.

```
SOE_STEP_KWH=0.0500  held=3.8974 kWh  total_cost=0.681595
SOE_STEP_KWH=0.0250  held=3.8447 kWh  total_cost=0.672813
SOE_STEP_KWH=0.0100  held=4.1079 kWh  total_cost=0.664171
SOE_STEP_KWH=0.0050  held=4.1079 kWh  total_cost=0.656442
SOE_STEP_KWH=0.0025  held=4.0026 kWh  total_cost=0.650301
```

Held charge stays flat (~3.9–4.1 kWh) across a 20x range of grid resolution.
Total cost improves slightly (finer grid finds marginally better actions, as
expected), but the *qualitative* behavior — holding charge past midnight —
does not change. **This directly falsifies the premise both Approach 1 and
Approach 2 were built on.**

## Finding 2: the 2-day joint optimization beats naive myopic optimization

If #275's symptom were a real bug (the DP failing to find its own optimum),
a simpler strategy should be able to beat it. Compared the actual 2-day
joint optimization against treating today and tomorrow as two independent
single-day optimizations (today's optimal schedule, then tomorrow's optimal
schedule starting from wherever today's optimal run left the battery):

```
Joint 2-day optimization total cost:       0.681595
Myopic today-alone cost:                   0.522459  (drains fully to floor)
Myopic tomorrow-alone cost (from floor):   0.727521  (pays for overnight import with zero reserve)
Myopic total:                              1.249980
```

The joint optimization beats naive myopic by **0.57** (out of a ~0.68 total
cost) — decisively better, not worse. A genuinely buggy DP could not
reliably outperform a simpler strategy by this margin; this is strong
evidence the DP is finding something economically real (a reserve worth
keeping), not something broken.

## Finding 3: what's actually being held, and where does it go

Isolation sweep (toggling solar on/off per day, `--isolate-solar`) shows
**tomorrow's solar forecast is necessary and sufficient** for the "exports
at a worse price" pattern to appear at all:

```
baseline (solar both days)      tmrwEve[disch/exp]=7.15/5.65  <- pattern present
no solar at all                 tmrwEve[disch/exp]=1.15/0.00  <- no pattern
solar TODAY only                tmrwEve[disch/exp]=1.15/0.00  <- no pattern
solar TOMORROW only              tmrwEve[disch/exp]=7.15/5.65  <- pattern present
cycle_cost=0                    tmrwEve[disch/exp]=7.15/5.65  <- unchanged (rules out cycle_cost)
```

Tracing the SOE trajectory directly (`--verify-mechanism`) resolves the
mechanism: from 10.789 kWh at midnight, the battery drains via
`LOAD_SUPPORT` (legitimate self-consumption, avoiding overnight grid import)
down to **7.0526 kWh by 07:00** — 0.0026 kWh above the 7.05 floor — right
before the next day's solar arrives. Solar then refills the battery (7.82
kWh captured via `SOLAR_STORAGE` that midday), and the 5.65 kWh exported at
"tomorrow's worse peak" (periods 180–191) is drawn from **that freshly
captured, same-day solar** — not the overnight-carried charge, which was
already drained to essentially the exact floor before that solar existed.

## Conclusion

The original #275 diagnosis conflated two distinct energy flows that happen
to pass through the same battery:

1. **The overnight reserve** — correctly sized to cover self-consumption
   until the next solar cycle, and drained almost exactly to floor by then.
2. **Fresh next-day solar** — which has no earlier, better-priced selling
   opportunity (today's peak is in the past by the time that energy exists),
   and is sold at the best price available *to it*.

There does not appear to be a missed arbitrage here. The DP's behavior is
consistent with an economically sound reserve-then-solar-cycle policy, not a
bug in the value function or its discretization.

This does not rule out every possible defect in this area — only that
neither #282 (Approach 1, already merged, kept as an independent
hardware-safety/accuracy improvement) nor a prospective Approach 2 (exact
value-function tracking) address the actual reported symptom, because the
symptom's premise (the same energy sold later at a worse known price)
doesn't hold up under direct tracing.

## Recommendation

- Pause #285 (Approach 2) — it targets a mechanism this investigation shows
  is not the actual cause. Revisit only if #275 is re-confirmed as a real
  defect through a different mechanism.
- Before further engineering investment, get a fresh real debug bundle from
  Frank at the moment he next observes the pattern, and directly check (via
  `scripts/repro_issue_275_worse_scenario.py --verify-mechanism`, adapted to
  his real data) whether the SOE trajectory drains to floor before the next
  solar cycle, with the "worse price" export sourced from fresh solar rather
  than carried-over charge. If so, this may not need a code fix at all — it
  may be a display/expectation issue (showing users that a battery holding
  charge past midnight hasn't necessarily lost value).
- If a *different* real defect is found, `scripts/repro_issue_275_worse_scenario.py`
  makes it cheap to test further hypotheses without spinning up mock-HA.

## Out of scope for this doc

- Any code changes — this is a diagnosis-only investigation.
- A full resolution of #275 — that depends on what, if anything, is actually
  wrong once the misdiagnosed mechanism is set aside.
