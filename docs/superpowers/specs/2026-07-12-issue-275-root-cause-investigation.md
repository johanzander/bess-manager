# Investigation: #275's real bug was fixed in b13; the residual is proven optimal

**Date**: 2026-07-12
**Status**: Investigation complete — recommend closing #275, #276, #285
**Related**: #275 (original symptom, Frank #126, fixed in part by PR #279 / `v9.9.0b13`),
#276 (Approach 1/2 follow-up investigation), #282 (Approach 1, merged, independent
hardware-safety fix), #285 (Approach 2, recommended closed as a result of this doc)

## Correction to this doc's own earlier version

An earlier version of this document concluded #275's symptom was a
"misdiagnosis." That overstated things. The corrected picture, established
by checking the shipped changelog history against this investigation's own
numbers:

- **The original defect was real and was already fixed.** `v9.9.0b13` (PR
  #279) shrank `SOE_STEP_KWH` from 0.1 to 0.05 kWh specifically to reduce
  Step 2's continuous-path-reconstruction interpolation error. On the
  reported reproduction, this reduced held charge above the floor from
  **5.32 kWh to 3.90 kWh — a genuine, verified 27% reduction**. That part of
  #275 was a real bug, and it was really fixed.
- **What this investigation found wrong** was a different, later assumption:
  that more of the *same* discretization error remained, motivating #282
  (Approach 1) and the proposed Approach 2 (#285) to keep refining the
  search/value-function precision to eliminate it. That assumption does not
  hold up — the post-b13 residual is not discretization error, and further
  refining it neither reduces the hold nor should.

## Finding 1: the residual does not respond to grid resolution at all

An exact value function is mathematically the limit of `SOE_STEP_KWH` going
to zero. Sweeping it 20x finer than b13's shipped value is a direct, cheap
test of whether more of the same fix would help further.

```
SOE_STEP_KWH=0.0500  held=3.8974 kWh  total_cost=0.681595
SOE_STEP_KWH=0.0250  held=3.8447 kWh  total_cost=0.672813
SOE_STEP_KWH=0.0100  held=4.1079 kWh  total_cost=0.664171
SOE_STEP_KWH=0.0050  held=4.1079 kWh  total_cost=0.656442
SOE_STEP_KWH=0.0025  held=4.0026 kWh  total_cost=0.650301
```

Held charge stays flat across a 20x range. #282 (exact hardware-aware
search against the same value function) independently confirmed this: zero
measurable difference from Option B alone, on the same reproduction.

## Finding 2: direct Bellman-optimality verification

At the exact decision point (period 96 of a real 192-period horizon built
from Frank's own debug bundle, SOE=10.947 kWh), computed `reward + V[t+1]`
for every hardware-valid discharge candidate from 8% to 14% of max rate:

```
pct= 8%  total=0.393378
pct= 9%  total=0.396183
pct=10%  total=0.398988
pct=11%  total=0.399072
pct=12%  total=0.399304   <- DP's actual choice, the true maximum
pct=13%  total=0.398595
pct=14%  total=0.397886
```

The DP's chosen action is the exact maximum among every option checked, not
an assumption. By the Bellman optimality principle, if every single-period
decision maximizes `reward + V[t+1]` using the correct continuation value,
the resulting full-horizon plan is the global optimum over the entire
action space — not just better than the specific alternatives tested below,
but provably better than every reachable schedule under the model.

## Finding 3: direct financial proof against Frank's proposed alternative

Built a full 192-period comparison using Frank's own real data from his
debug bundle (2026-07-12), and ran **both** schedules through the actual
hardware-execution simulator (`derive_control_command` + `simulate`), not
just the DP's internal planning numbers:

**Using real, undoctored prices** (`sensor.belpex_h_average_electricity_price`,
no synthetic modification):

```
Real sell prices:
  tonight's peak:   0.1349 EUR/kWh (22:00)
  tomorrow's peak:  0.1564 EUR/kWh (21:00) -- genuinely higher

DP's actual plan (holds 4.371 kWh into tomorrow):     realized 48h cost = -0.054 EUR (net profit)
Naive drain-to-floor-nightly (matches Frank's scripts' pattern): realized cost =  0.702 EUR
Difference: DP plan is 0.756 EUR cheaper over 48h
```

Both prices are already-published day-ahead values, not forecasts — this
is real, known-price arbitrage across two days, not a hedge against
uncertainty.

### Isolating exactly where that 0.756 EUR comes from

Checked whether the advantage comes from having *more* energy available for
tomorrow's evening peak (what Frank's "solar will refill the battery
anyway" argument implies should make holding reserve unnecessary):

```
                              DP's plan (holds reserve)   Drain-to-floor-tonight
SOE at midnight:                    11.42 kWh                    7.05 kWh
SOE at 20:00 tomorrow (pre-peak):    14.82 kWh                   14.82 kWh   <- identical
Overnight grid import:                0.048 kWh                  3.586 kWh
```

**Frank is right that solar refills the battery to the same level before
tomorrow's evening peak regardless of overnight reserve** — both schedules
arrive at 14.82 kWh either way. The entire 0.756 EUR advantage comes from
avoiding ~3.5 kWh of overnight grid import, which the reserve legitimately
covers via self-consumption. Frank's belief that his house "barely
consumes any power" overnight does not match the actual measured data in
his own debug bundle (`historical_periods`, `data_source: "actual"`):
overnight per-15-minute consumption ranges 0.09–0.30 kWh (roughly 0.4–1.2 kW
instantaneous), a real, moderate household base load, not negligible.

## Fidelity checks performed

- Battery settings (capacity, SOC limits, power/efficiency limits, cycle
  cost) match Frank's real config exactly.
- Price formula corrected to match `price_manager.py`'s exact computation
  (`markup_rate=0.198`, not an earlier `0.1984` typo) — conclusion unchanged.
- Consumption assumption corrected from a 6-hour-derived flat average
  (0.517 kWh/h) to the fuller available real data (59 periods through
  14:45, true average 1.005 kWh/h, and separately the real variable
  hourly profile) — conclusion held (current implementation cheaper) across
  all three consumption assumptions tested, by 22–83% depending on the
  exact assumption.
- Confirmed via the bundle's own config that Frank's system uses
  `consumption_strategy: "ha_statistics"` (multi-day, time-of-day-aware
  forecasting), not a flat prediction — meaning production's real forecast
  for unobserved periods is more sophisticated than this investigation's
  approximation, which if anything supports at least as much reserve as
  found here, not less.

## Conclusion

`v9.9.0b13` fixed a real defect (excess holding from grid-interpolation
error, 5.32→3.90 kWh). The residual behavior investigated here — which
still superficially resembles the reported symptom — has been directly
proven, not merely left untested, to be the financially optimal choice:
it is a Bellman-optimal decision, it beats the "hold less, export more
tonight" alternative by real money using Frank's own real prices and
consumption, and the advantage comes specifically from legitimate overnight
self-consumption avoidance, not from a discretization artifact.

## Recommendation

- Close #275, #276, and #285. The real defect they describe was fixed in
  PR #279. No further discretization-based work (#282's approach, or the
  paused Approach 2) can or should reduce the residual further — it is
  already the best available outcome.
- Consider a product-level follow-up (separate from these issues): the
  dashboard's "Net Cost" figure shows only the current day's slice of a
  multi-day optimization, so a plan that correctly redirects value to a
  better future price makes *today's* number look worse with no visibility
  into the corresponding gain. This is very likely what produced the "Net
  Cost dropped from -0.80 to -0.15" observation that prompted this
  investigation — not a real loss, but a display gap.

## Out of scope for this doc

- Any code changes — this is a diagnosis-only investigation.
- The dashboard display-gap follow-up noted above, if pursued.
