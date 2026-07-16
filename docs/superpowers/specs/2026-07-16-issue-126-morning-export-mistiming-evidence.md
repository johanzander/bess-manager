# Evidence: BESS vs. Frank's Script -- Full 2-Day Comparison, and a Confirmed Morning Export-Mistiming Defect (13-14 Jul 2026)

**Related**: #126 (Frank's original report), #275 / #276 / #285 (prior investigation
lineage into the same class of DP timing behavior, see
`docs/superpowers/specs/2026-07-12-issue-275-root-cause-investigation.md`)

**Status**: Evidence gathered and verified. No fix implemented — this document is
for review before any implementation work is scoped.

## Summary

Frank (#126) reported that once a 2-day price horizon is in view, BESS holds more
overnight SOC (~74-78%) than his own script would (drain toward the ~47% floor each
evening, self-supply overnight, minimum SOC at sunrise). Two things were tested
against his own real debug data:

1. **Is BESS's overall overnight-hold strategy wrong?** No. Simulating his policy
   in full against the same real prices/load/solar, over the complete 2-day horizon,
   BESS's actual schedule still outperforms it by **EUR 0.0451 (~2.2%)**. His
   premise that BESS is leaving money on the table by holding overnight SOC, in
   general, does not hold up on this data (full comparison below).
2. **But a specific, isolated mistiming defect is real and confirmed.** BESS
   actively discharges small amounts (0.0375 kWh/period) at 07:00-11:30 on 14 Jul,
   selling at 0.102-0.131 EUR/kWh — prices *lower* than the 21:00-21:45 window the
   evening before (0.1564 EUR/kWh), which had ~3.4 kWh of *unused* discharge
   headroom at the time (max power 1.25 kWh/period, only 0.31-0.44 kWh/period
   actually used). Selling that same 0.5625 kWh of battery-attributable export at
   the better evening price instead of the actual morning price would have earned
   **EUR 0.0880 vs. the actual EUR 0.0662 — EUR 0.0218 of avoidable value lost**,
   with idle capacity available at the better price the whole time. Reproduced in
   `scripts/repro_issue_126_morning_export_mistiming.py`.

Likely root cause (not yet investigated): the same class of DP value-function/
search-precision issue tracked under #275/#276/#285, given the pattern (selling at
a strictly worse, later price when better-priced capacity was available and
unused earlier) matches that investigation's territory. This document only
establishes and quantifies the defect — it does not diagnose the algorithmic
cause or propose a fix.

## Full 2-day comparison (supporting detail for finding 1)

Source data: `bess-debug-2026-07-13-155212.md` (real debug export attached to
issue #126, GitHub attachment id 29969502, exported 15:45 CEST 13 Jul 2026,
129 periods / 32.25h, 15-min resolution).

BESS side = actual system output (real ground truth, not simulated). Frank side = constructed simulation of his stated policy, scored through the real reward/state-transition code (`core/bess/dp_battery_algorithm.py`), not reimplemented math.

## Method

**Frank's policy, as implemented:**
1. At each evening decision point (19:00), compute the forecasted net load deficit (home_consumption minus solar_production, only when positive) from now until solar reliably covers load again (next crossover, or horizon end for the final evening).
2. Required reserve = 7.05 kWh floor + (deficit_sum / discharge_efficiency 0.95).
3. Everything above the reserve is sold immediately, greedily, into the highest sell-price periods within that evening window, capped at 1.25 kWh/period (5kW max discharge power).
4. For the remaining periods until solar recovers, discharge exactly enough to cover that period's own deficit (self-consumption, zero grid import) -- no more.
5. Once solar recovers, no further discretionary sales -- battery charges passively from solar (same physics as BESS) until the next evening decision point, or exports any solar surplus directly once at the 15 kWh cap.

This directly implements what Frank described: export all excess in the evening, keep just enough for the night, minimum SOC when the sun comes up, no selling in the morning.

**Verification:** the evening dump allocation is checked to balance exactly (kWh budgeted = kWh placed, zero remainder) for both the 13 Jul and 14 Jul evening windows. All reward/state-transition math is computed by importing and calling the actual functions from `core/bess/dp_battery_algorithm.py`, not hand-derived.

## Result

| | Total profit (EUR) |
|---|---|
| **BESS (actual)** | **2.0532** |
| **Frank's script (simulated)** | **2.0081** |
| **Delta (BESS minus Frank)** | **+0.0451** |

**Over the full 2-day horizon, BESS outperforms Frank's script by EUR 0.0451 (~2.2%).**

This is despite Frank's approach winning the first night in isolation (see segment breakdown below) -- the full-horizon picture is more nuanced than either 'BESS always wins' or 'Frank always wins'.

## Segment breakdown

| Segment | BESS (EUR) | Frank (EUR) | Delta (BESS-Frank) |
|---|---|---|---|
| Pre-evening idle, 15:45-18:45 13 Jul | 0.2340 | 0.2340 | +0.0000 |
| Night 1: evening dump + overnight self-supply, 19:00 13Jul -> 07:00 14Jul | 0.2120 | 0.3554 | -0.1434 |
| Daytime: solar recharge, 07:00 -> 19:00 14 Jul | 0.7568 | 0.5647 | +0.1921 |
| Night 2: evening dump + self-supply, 19:00 -> 23:45 14 Jul (horizon end) | 0.8503 | 0.8540 | -0.0037 |
| **TOTAL** | **2.0532** | **2.0081** | **+0.0451** |

**Why the segments swing the way they do:**

- **Night 1**: Frank sells the full available surplus (2.1499 kWh) into the 21:00-21:30 peak (sell price 0.156 EUR/kWh) and self-supplies the rest of the night at zero grid-import cost, landing exactly at the 47% floor at the 07:00 crossover. BESS paces a smaller export across the evening and holds more (52.6% at the same crossover point), so it captures less of the peak price up front.
- **Daytime**: BESS's real schedule keeps making small discharges into 07:00-09:45 at sell prices (0.109-0.131 EUR/kWh) that are *lower* than the evening before (0.134-0.156) or the overnight window (0.117-0.129) -- objectively mistimed sales, confirmed against the real price data. Frank's policy makes no such sales (matching his stated rule). Despite that, Frank's battery reaches the 15 kWh cap earlier (12:00 vs BESS's 14:15, because Frank isn't depleting SOE further with those small morning sales), which forces Frank into more direct low-price solar export at midday instead of storing it for the evening peak -- while BESS keeps absorbing solar into storage for longer (paying cycle-cost wear for it) and cashes it in later at the better evening price. This second effect outweighs the first and is the dominant reason BESS wins the daytime segment overall.
- **Night 2**: essentially tied -- both reach the 14 Jul evening at 100% SOC and apply the same dump-and-self-supply logic against the same prices.

**Bottom line:** BESS's early-morning sales (07:00-09:45) are genuinely mistimed against the price curve -- that part of Frank's critique is confirmed. But BESS more than makes up for it over the full 2 days by holding more capacity in reserve through midday, avoiding low-price direct solar export, and cashing that capacity in at the better evening price later -- a trade-off Frank's simpler evening-dump-then-hold rule doesn't make as well.

## Full 129-period table

Action columns: negative = discharge (kWh), positive = charge (kWh), 0 = idle/passive. SOC% = state of charge at end of period (15 kWh capacity, 47% floor).

| Time | Home | Solar | Buy | Sell | BESS act | BESS SOC% | BESS EUR | Frank act | Frank SOC% | Frank EUR | Cum Delta |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 15:45 13Jul | 0.485 | 0.900 | 0.3052 | 0.0773 | +0.0000 | 100.00% | +0.0321 | +0.0000 | 100.00% | +0.0321 | +0.0000 |
| 16:00 13Jul | 0.440 | 0.744 | 0.3133 | 0.0849 | +0.0000 | 100.00% | +0.0258 | +0.0000 | 100.00% | +0.0258 | +0.0000 |
| 16:15 13Jul | 0.440 | 0.744 | 0.3133 | 0.0849 | +0.0000 | 100.00% | +0.0258 | +0.0000 | 100.00% | +0.0258 | +0.0000 |
| 16:30 13Jul | 0.440 | 0.744 | 0.3133 | 0.0849 | +0.0000 | 100.00% | +0.0258 | +0.0000 | 100.00% | +0.0258 | +0.0000 |
| 16:45 13Jul | 0.440 | 0.744 | 0.3133 | 0.0849 | +0.0000 | 100.00% | +0.0258 | +0.0000 | 100.00% | +0.0258 | +0.0000 |
| 17:00 13Jul | 0.440 | 0.590 | 0.3411 | 0.1112 | +0.0000 | 100.00% | +0.0167 | +0.0000 | 100.00% | +0.0167 | +0.0000 |
| 17:15 13Jul | 0.440 | 0.590 | 0.3411 | 0.1112 | +0.0000 | 100.00% | +0.0167 | +0.0000 | 100.00% | +0.0167 | +0.0000 |
| 17:30 13Jul | 0.440 | 0.590 | 0.3411 | 0.1112 | +0.0000 | 100.00% | +0.0167 | +0.0000 | 100.00% | +0.0167 | +0.0000 |
| 17:45 13Jul | 0.440 | 0.590 | 0.3411 | 0.1112 | +0.0000 | 100.00% | +0.0167 | +0.0000 | 100.00% | +0.0167 | +0.0000 |
| 18:00 13Jul | 0.360 | 0.427 | 0.3493 | 0.1189 | +0.0000 | 100.00% | +0.0080 | +0.0000 | 100.00% | +0.0080 | +0.0000 |
| 18:15 13Jul | 0.360 | 0.427 | 0.3493 | 0.1189 | +0.0000 | 100.00% | +0.0080 | +0.0000 | 100.00% | +0.0080 | +0.0000 |
| 18:30 13Jul | 0.360 | 0.427 | 0.3493 | 0.1189 | +0.0000 | 100.00% | +0.0080 | +0.0000 | 100.00% | +0.0080 | +0.0000 |
| 18:45 13Jul | 0.360 | 0.427 | 0.3493 | 0.1189 | +0.0000 | 100.00% | +0.0080 | +0.0000 | 100.00% | +0.0080 | +0.0000 |
| 19:00 13Jul | 0.220 | 0.256 | 0.3620 | 0.1309 | +0.0000 | 100.00% | +0.0048 | +0.0000 | 100.00% | +0.0048 | +0.0000 |
| 19:15 13Jul | 0.220 | 0.256 | 0.3620 | 0.1309 | +0.0000 | 100.00% | +0.0048 | +0.0000 | 100.00% | +0.0048 | +0.0000 |
| 19:30 13Jul | 0.220 | 0.256 | 0.3620 | 0.1309 | -0.0375 | 99.74% | +0.0097 | +0.0000 | 100.00% | +0.0048 | +0.0049 |
| 19:45 13Jul | 0.220 | 0.256 | 0.3620 | 0.1309 | +0.0000 | 99.97% | -0.0012 | +0.0000 | 100.00% | +0.0048 | -0.0011 |
| 20:00 13Jul | 0.200 | 0.100 | 0.3798 | 0.1477 | -0.1000 | 99.27% | +0.0000 | -0.0998 | 99.30% | -0.0000 | -0.0011 |
| 20:15 13Jul | 0.200 | 0.100 | 0.3798 | 0.1477 | -0.1000 | 98.57% | +0.0000 | -0.0998 | 98.60% | -0.0000 | -0.0010 |
| 20:30 13Jul | 0.200 | 0.100 | 0.3798 | 0.1477 | -0.1000 | 97.87% | +0.0000 | -0.0998 | 97.90% | -0.0000 | -0.0010 |
| 20:45 13Jul | 0.200 | 0.100 | 0.3798 | 0.1477 | -0.1000 | 97.17% | +0.0000 | -0.0998 | 97.20% | -0.0000 | -0.0010 |
| 21:00 13Jul | 0.215 | 0.011 | 0.3891 | 0.1564 | -0.3125 | 94.97% | +0.0171 | -1.2500 | 88.43% | +0.1637 | -0.1476 |
| 21:15 13Jul | 0.215 | 0.011 | 0.3891 | 0.1564 | -0.4250 | 91.99% | +0.0347 | -1.2500 | 79.65% | +0.1637 | -0.2767 |
| 21:30 13Jul | 0.215 | 0.011 | 0.3891 | 0.1564 | -0.4250 | 89.01% | +0.0347 | -0.2604 | 77.83% | +0.0089 | -0.2510 |
| 21:45 13Jul | 0.215 | 0.011 | 0.3891 | 0.1564 | -0.4375 | 85.94% | +0.0366 | -0.2035 | 76.40% | -0.0000 | -0.2143 |
| 22:00 13Jul | 0.240 | 0.000 | 0.3814 | 0.1492 | -0.2625 | 84.10% | +0.0034 | -0.2400 | 74.72% | -0.0000 | -0.2110 |
| 22:15 13Jul | 0.240 | 0.000 | 0.3814 | 0.1492 | -0.2625 | 82.25% | +0.0034 | -0.2400 | 73.03% | -0.0000 | -0.2076 |
| 22:30 13Jul | 0.240 | 0.000 | 0.3814 | 0.1492 | -0.2625 | 80.41% | +0.0034 | -0.2400 | 71.35% | -0.0000 | -0.2043 |
| 22:45 13Jul | 0.240 | 0.000 | 0.3814 | 0.1492 | -0.3375 | 78.04% | +0.0146 | -0.2400 | 69.66% | -0.0000 | -0.1897 |
| 23:00 13Jul | 0.130 | 0.000 | 0.3653 | 0.1340 | -0.1500 | 76.99% | +0.0027 | -0.1300 | 68.75% | -0.0000 | -0.1870 |
| 23:15 13Jul | 0.130 | 0.000 | 0.3653 | 0.1340 | -0.1500 | 75.94% | +0.0027 | -0.1300 | 67.84% | -0.0000 | -0.1844 |
| 23:30 13Jul | 0.130 | 0.000 | 0.3653 | 0.1340 | -0.1500 | 74.88% | +0.0027 | -0.1300 | 66.93% | -0.0000 | -0.1817 |
| 23:45 13Jul | 0.130 | 0.000 | 0.3653 | 0.1340 | -0.1250 | 74.01% | -0.0018 | -0.1300 | 66.01% | -0.0000 | -0.1835 |
| 00:00 14Jul | 0.110 | 0.000 | 0.3604 | 0.1294 | -0.1250 | 73.13% | +0.0019 | -0.1100 | 65.24% | -0.0000 | -0.1816 |
| 00:15 14Jul | 0.110 | 0.000 | 0.3604 | 0.1294 | -0.1250 | 72.25% | +0.0019 | -0.1100 | 64.47% | -0.0000 | -0.1796 |
| 00:30 14Jul | 0.110 | 0.000 | 0.3604 | 0.1294 | -0.1250 | 71.38% | +0.0019 | -0.1100 | 63.70% | -0.0000 | -0.1777 |
| 00:45 14Jul | 0.110 | 0.000 | 0.3604 | 0.1294 | -0.1250 | 70.50% | +0.0019 | -0.1100 | 62.93% | -0.0000 | -0.1757 |
| 01:00 14Jul | 0.115 | 0.000 | 0.3543 | 0.1236 | -0.1375 | 69.53% | +0.0028 | -0.1150 | 62.12% | -0.0000 | -0.1730 |
| 01:15 14Jul | 0.115 | 0.000 | 0.3543 | 0.1236 | -0.1375 | 68.57% | +0.0028 | -0.1150 | 61.31% | -0.0000 | -0.1702 |
| 01:30 14Jul | 0.115 | 0.000 | 0.3543 | 0.1236 | -0.1375 | 67.60% | +0.0028 | -0.1150 | 60.50% | -0.0000 | -0.1674 |
| 01:45 14Jul | 0.115 | 0.000 | 0.3543 | 0.1236 | -0.1375 | 66.64% | +0.0028 | -0.1150 | 59.70% | -0.0000 | -0.1646 |
| 02:00 14Jul | 0.115 | 0.000 | 0.3472 | 0.1170 | -0.1125 | 65.85% | -0.0009 | -0.1150 | 58.89% | -0.0000 | -0.1655 |
| 02:15 14Jul | 0.115 | 0.000 | 0.3472 | 0.1170 | -0.1125 | 65.06% | -0.0009 | -0.1150 | 58.08% | -0.0000 | -0.1664 |
| 02:30 14Jul | 0.115 | 0.000 | 0.3472 | 0.1170 | -0.1125 | 64.27% | -0.0009 | -0.1150 | 57.28% | -0.0000 | -0.1672 |
| 02:45 14Jul | 0.115 | 0.000 | 0.3472 | 0.1170 | -0.1125 | 63.48% | -0.0009 | -0.1150 | 56.47% | -0.0000 | -0.1681 |
| 03:00 14Jul | 0.100 | 0.000 | 0.3471 | 0.1168 | -0.1000 | 62.78% | +0.0000 | -0.1000 | 55.77% | -0.0000 | -0.1681 |
| 03:15 14Jul | 0.100 | 0.000 | 0.3471 | 0.1168 | -0.1000 | 62.08% | +0.0000 | -0.1000 | 55.07% | -0.0000 | -0.1681 |
| 03:30 14Jul | 0.100 | 0.000 | 0.3471 | 0.1168 | -0.1000 | 61.38% | +0.0000 | -0.1000 | 54.36% | -0.0000 | -0.1681 |
| 03:45 14Jul | 0.100 | 0.000 | 0.3471 | 0.1168 | -0.1000 | 60.67% | +0.0000 | -0.1000 | 53.66% | -0.0000 | -0.1681 |
| 04:00 14Jul | 0.120 | 0.000 | 0.3476 | 0.1173 | -0.1375 | 59.71% | +0.0021 | -0.1200 | 52.82% | -0.0000 | -0.1660 |
| 04:15 14Jul | 0.120 | 0.000 | 0.3476 | 0.1173 | -0.1375 | 58.74% | +0.0021 | -0.1200 | 51.98% | -0.0000 | -0.1640 |
| 04:30 14Jul | 0.120 | 0.000 | 0.3476 | 0.1173 | -0.1375 | 57.78% | +0.0021 | -0.1200 | 51.14% | -0.0000 | -0.1619 |
| 04:45 14Jul | 0.120 | 0.000 | 0.3476 | 0.1173 | -0.1375 | 56.81% | +0.0021 | -0.1200 | 50.29% | -0.0000 | -0.1599 |
| 05:00 14Jul | 0.085 | 0.001 | 0.3555 | 0.1248 | -0.1000 | 56.11% | +0.0020 | -0.0842 | 49.70% | -0.0000 | -0.1579 |
| 05:15 14Jul | 0.085 | 0.001 | 0.3555 | 0.1248 | -0.1000 | 55.41% | +0.0020 | -0.0842 | 49.11% | -0.0000 | -0.1559 |
| 05:30 14Jul | 0.085 | 0.001 | 0.3555 | 0.1248 | -0.1000 | 54.71% | +0.0020 | -0.0842 | 48.52% | -0.0000 | -0.1540 |
| 05:45 14Jul | 0.085 | 0.001 | 0.3555 | 0.1248 | -0.1000 | 54.01% | +0.0020 | -0.0842 | 47.93% | -0.0000 | -0.1520 |
| 06:00 14Jul | 0.095 | 0.062 | 0.3591 | 0.1282 | -0.0500 | 53.66% | +0.0022 | -0.0332 | 47.70% | -0.0000 | -0.1498 |
| 06:15 14Jul | 0.095 | 0.062 | 0.3591 | 0.1282 | -0.0500 | 53.31% | +0.0022 | -0.0332 | 47.47% | -0.0000 | -0.1477 |
| 06:30 14Jul | 0.095 | 0.062 | 0.3591 | 0.1282 | -0.0500 | 52.95% | +0.0022 | -0.0332 | 47.23% | -0.0000 | -0.1455 |
| 06:45 14Jul | 0.095 | 0.062 | 0.3591 | 0.1282 | -0.0500 | 52.60% | +0.0022 | -0.0332 | 47.00% | -0.0000 | -0.1434 |
| 07:00 14Jul | 0.115 | 0.209 | 0.3624 | 0.1313 | -0.0375 | 52.34% | +0.0173 | +0.0000 | 47.61% | -0.0032 | -0.1228 |
| 07:15 14Jul | 0.115 | 0.209 | 0.3624 | 0.1313 | -0.0375 | 52.08% | +0.0173 | +0.0000 | 48.22% | -0.0032 | -0.1023 |
| 07:30 14Jul | 0.115 | 0.209 | 0.3624 | 0.1313 | -0.0375 | 51.81% | +0.0173 | +0.0000 | 48.83% | -0.0032 | -0.0818 |
| 07:45 14Jul | 0.115 | 0.209 | 0.3624 | 0.1313 | -0.0375 | 51.55% | +0.0173 | +0.0000 | 49.44% | -0.0032 | -0.0612 |
| 08:00 14Jul | 0.135 | 0.389 | 0.3551 | 0.1244 | -0.0375 | 51.29% | +0.0362 | +0.0000 | 51.08% | -0.0086 | -0.0164 |
| 08:15 14Jul | 0.135 | 0.389 | 0.3551 | 0.1244 | -0.0375 | 51.02% | +0.0362 | +0.0000 | 52.72% | -0.0086 | +0.0284 |
| 08:30 14Jul | 0.135 | 0.389 | 0.3551 | 0.1244 | -0.0375 | 50.76% | +0.0362 | +0.0000 | 54.37% | -0.0086 | +0.0732 |
| 08:45 14Jul | 0.135 | 0.389 | 0.3551 | 0.1244 | -0.0375 | 50.50% | +0.0362 | +0.0000 | 56.01% | -0.0086 | +0.1181 |
| 09:00 14Jul | 0.150 | 0.565 | 0.3392 | 0.1093 | -0.0375 | 50.24% | +0.0495 | +0.0000 | 58.69% | -0.0141 | +0.1817 |
| 09:15 14Jul | 0.150 | 0.565 | 0.3392 | 0.1093 | -0.0375 | 49.97% | +0.0495 | +0.0000 | 61.38% | -0.0141 | +0.2453 |
| 09:30 14Jul | 0.150 | 0.565 | 0.3392 | 0.1093 | -0.0375 | 49.71% | +0.0495 | +0.0000 | 64.06% | -0.0141 | +0.3089 |
| 09:45 14Jul | 0.150 | 0.565 | 0.3392 | 0.1093 | -0.0375 | 49.45% | +0.0495 | +0.0000 | 66.75% | -0.0141 | +0.3725 |
| 10:00 14Jul | 0.165 | 0.716 | 0.3245 | 0.0955 | +0.0000 | 53.01% | -0.0187 | +0.0000 | 70.31% | -0.0187 | +0.3725 |
| 10:15 14Jul | 0.165 | 0.716 | 0.3245 | 0.0955 | +0.0000 | 56.57% | -0.0187 | +0.0000 | 73.87% | -0.0187 | +0.3725 |
| 10:30 14Jul | 0.165 | 0.716 | 0.3245 | 0.0955 | +0.0000 | 60.13% | -0.0187 | +0.0000 | 77.43% | -0.0187 | +0.3725 |
| 10:45 14Jul | 0.165 | 0.716 | 0.3245 | 0.0955 | +0.0000 | 63.69% | -0.0187 | +0.0000 | 80.99% | -0.0187 | +0.3725 |
| 11:00 14Jul | 0.210 | 0.827 | 0.3313 | 0.1020 | -0.0375 | 63.42% | +0.0667 | +0.0000 | 84.97% | -0.0209 | +0.4601 |
| 11:15 14Jul | 0.210 | 0.827 | 0.3313 | 0.1020 | -0.0375 | 63.16% | +0.0667 | +0.0000 | 88.96% | -0.0209 | +0.5478 |
| 11:30 14Jul | 0.210 | 0.827 | 0.3313 | 0.1020 | -0.0375 | 62.90% | +0.0667 | +0.0000 | 92.95% | -0.0209 | +0.6354 |
| 11:45 14Jul | 0.210 | 0.827 | 0.3313 | 0.1020 | +0.0000 | 66.88% | -0.0209 | +0.0000 | 96.94% | -0.0209 | +0.6354 |
| 12:00 14Jul | 0.330 | 0.897 | 0.3217 | 0.0928 | +0.0000 | 70.55% | -0.0193 | +0.0000 | 100.00% | -0.0074 | +0.6235 |
| 12:15 14Jul | 0.330 | 0.897 | 0.3217 | 0.0928 | +0.0000 | 74.22% | -0.0193 | +0.0000 | 100.00% | +0.0527 | +0.5515 |
| 12:30 14Jul | 0.330 | 0.897 | 0.3217 | 0.0928 | +0.0000 | 77.89% | -0.0193 | +0.0000 | 100.00% | +0.0527 | +0.4796 |
| 12:45 14Jul | 0.330 | 0.897 | 0.3217 | 0.0928 | +0.0000 | 81.56% | -0.0193 | +0.0000 | 100.00% | +0.0527 | +0.4076 |
| 13:00 14Jul | 0.305 | 0.905 | 0.3194 | 0.0906 | +0.0000 | 85.44% | -0.0204 | +0.0000 | 100.00% | +0.0544 | +0.3329 |
| 13:15 14Jul | 0.305 | 0.905 | 0.3194 | 0.0906 | +0.0000 | 89.32% | -0.0204 | +0.0000 | 100.00% | +0.0544 | +0.2582 |
| 13:30 14Jul | 0.305 | 0.905 | 0.3194 | 0.0906 | +0.0000 | 93.20% | -0.0204 | +0.0000 | 100.00% | +0.0544 | +0.1835 |
| 13:45 14Jul | 0.305 | 0.905 | 0.3194 | 0.0906 | +0.0000 | 97.07% | -0.0204 | +0.0000 | 100.00% | +0.0544 | +0.1088 |
| 14:00 14Jul | 0.550 | 0.862 | 0.3279 | 0.0987 | +0.0000 | 99.09% | -0.0106 | +0.0000 | 100.00% | +0.0308 | +0.0673 |
| 14:15 14Jul | 0.550 | 0.862 | 0.3279 | 0.0987 | +0.0000 | 100.00% | +0.0122 | +0.0000 | 100.00% | +0.0308 | +0.0487 |
| 14:30 14Jul | 0.550 | 0.862 | 0.3279 | 0.0987 | +0.0000 | 100.00% | +0.0308 | +0.0000 | 100.00% | +0.0308 | +0.0487 |
| 14:45 14Jul | 0.550 | 0.862 | 0.3279 | 0.0987 | +0.0000 | 100.00% | +0.0308 | +0.0000 | 100.00% | +0.0308 | +0.0487 |
| 15:00 14Jul | 0.485 | 0.793 | 0.3238 | 0.0949 | +0.0000 | 100.00% | +0.0292 | +0.0000 | 100.00% | +0.0292 | +0.0487 |
| 15:15 14Jul | 0.485 | 0.793 | 0.3238 | 0.0949 | +0.0000 | 100.00% | +0.0292 | +0.0000 | 100.00% | +0.0292 | +0.0487 |
| 15:30 14Jul | 0.485 | 0.793 | 0.3238 | 0.0949 | +0.0000 | 100.00% | +0.0292 | +0.0000 | 100.00% | +0.0292 | +0.0487 |
| 15:45 14Jul | 0.485 | 0.793 | 0.3238 | 0.0949 | +0.0000 | 100.00% | +0.0292 | +0.0000 | 100.00% | +0.0292 | +0.0487 |
| 16:00 14Jul | 0.440 | 0.706 | 0.3185 | 0.0898 | +0.0000 | 100.00% | +0.0239 | +0.0000 | 100.00% | +0.0239 | +0.0487 |
| 16:15 14Jul | 0.440 | 0.706 | 0.3185 | 0.0898 | +0.0000 | 100.00% | +0.0239 | +0.0000 | 100.00% | +0.0239 | +0.0487 |
| 16:30 14Jul | 0.440 | 0.706 | 0.3185 | 0.0898 | +0.0000 | 100.00% | +0.0239 | +0.0000 | 100.00% | +0.0239 | +0.0487 |
| 16:45 14Jul | 0.440 | 0.706 | 0.3185 | 0.0898 | +0.0000 | 100.00% | +0.0239 | +0.0000 | 100.00% | +0.0239 | +0.0487 |
| 17:00 14Jul | 0.440 | 0.598 | 0.3436 | 0.1136 | +0.0000 | 100.00% | +0.0179 | +0.0000 | 100.00% | +0.0179 | +0.0487 |
| 17:15 14Jul | 0.440 | 0.598 | 0.3436 | 0.1136 | +0.0000 | 100.00% | +0.0179 | +0.0000 | 100.00% | +0.0179 | +0.0487 |
| 17:30 14Jul | 0.440 | 0.598 | 0.3436 | 0.1136 | +0.0000 | 100.00% | +0.0179 | +0.0000 | 100.00% | +0.0179 | +0.0487 |
| 17:45 14Jul | 0.440 | 0.598 | 0.3436 | 0.1136 | +0.0000 | 100.00% | +0.0179 | +0.0000 | 100.00% | +0.0179 | +0.0487 |
| 18:00 14Jul | 0.360 | 0.462 | 0.3567 | 0.1259 | +0.0000 | 100.00% | +0.0129 | +0.0000 | 100.00% | +0.0129 | +0.0487 |
| 18:15 14Jul | 0.360 | 0.462 | 0.3567 | 0.1259 | +0.0000 | 100.00% | +0.0129 | +0.0000 | 100.00% | +0.0129 | +0.0487 |
| 18:30 14Jul | 0.360 | 0.462 | 0.3567 | 0.1259 | +0.0000 | 100.00% | +0.0129 | +0.0000 | 100.00% | +0.0129 | +0.0487 |
| 18:45 14Jul | 0.360 | 0.462 | 0.3567 | 0.1259 | +0.0000 | 100.00% | +0.0129 | +0.0000 | 100.00% | +0.0129 | +0.0487 |
| 19:00 14Jul | 0.220 | 0.293 | 0.3761 | 0.1442 | +0.0000 | 100.00% | +0.0105 | +0.0000 | 100.00% | +0.0105 | +0.0487 |
| 19:15 14Jul | 0.220 | 0.293 | 0.3761 | 0.1442 | +0.0000 | 100.00% | +0.0105 | +0.0000 | 100.00% | +0.0105 | +0.0487 |
| 19:30 14Jul | 0.220 | 0.293 | 0.3761 | 0.1442 | +0.0000 | 100.00% | +0.0105 | +0.0000 | 100.00% | +0.0105 | +0.0487 |
| 19:45 14Jul | 0.220 | 0.293 | 0.3761 | 0.1442 | +0.0000 | 100.00% | +0.0105 | +0.0000 | 100.00% | +0.0105 | +0.0487 |
| 20:00 14Jul | 0.200 | 0.131 | 0.3862 | 0.1537 | -0.0875 | 99.39% | +0.0029 | -0.0687 | 99.52% | -0.0000 | +0.0516 |
| 20:15 14Jul | 0.200 | 0.131 | 0.3862 | 0.1537 | -0.1500 | 98.33% | +0.0125 | -0.0687 | 99.04% | -0.0000 | +0.0641 |
| 20:30 14Jul | 0.200 | 0.131 | 0.3862 | 0.1537 | -0.0875 | 97.72% | +0.0029 | -0.0687 | 98.55% | -0.0000 | +0.0670 |
| 20:45 14Jul | 0.200 | 0.131 | 0.3862 | 0.1537 | -0.0875 | 97.11% | +0.0029 | -0.0687 | 98.07% | -0.0000 | +0.0699 |
| 21:00 14Jul | 0.215 | 0.017 | 0.3958 | 0.1628 | -1.1125 | 89.30% | +0.1488 | -1.2500 | 89.30% | +0.1712 | +0.0475 |
| 21:15 14Jul | 0.215 | 0.017 | 0.3958 | 0.1628 | -1.2375 | 80.61% | +0.1692 | -1.2500 | 80.53% | +0.1712 | +0.0455 |
| 21:30 14Jul | 0.215 | 0.017 | 0.3958 | 0.1628 | -1.2250 | 72.02% | +0.1672 | -1.2500 | 71.76% | +0.1712 | +0.0414 |
| 21:45 14Jul | 0.215 | 0.017 | 0.3958 | 0.1628 | -1.2375 | 63.33% | +0.1692 | -1.2500 | 62.98% | +0.1712 | +0.0394 |
| 22:00 14Jul | 0.240 | 0.000 | 0.3919 | 0.1591 | -0.4250 | 60.35% | +0.0294 | -1.0376 | 55.70% | +0.1269 | -0.0581 |
| 22:15 14Jul | 0.240 | 0.000 | 0.3919 | 0.1591 | -0.4250 | 57.37% | +0.0294 | -0.2400 | 54.02% | -0.0000 | -0.0287 |
| 22:30 14Jul | 0.240 | 0.000 | 0.3919 | 0.1591 | -0.4375 | 54.30% | +0.0314 | -0.2400 | 52.33% | -0.0000 | +0.0028 |
| 22:45 14Jul | 0.240 | 0.000 | 0.3919 | 0.1591 | -0.4125 | 51.40% | +0.0274 | -0.2400 | 50.65% | -0.0000 | +0.0302 |
| 23:00 14Jul | 0.130 | 0.000 | 0.3733 | 0.1416 | -0.1500 | 50.35% | +0.0028 | -0.1300 | 49.74% | -0.0000 | +0.0330 |
| 23:15 14Jul | 0.130 | 0.000 | 0.3733 | 0.1416 | -0.1500 | 49.30% | +0.0028 | -0.1300 | 48.82% | -0.0000 | +0.0359 |
| 23:30 14Jul | 0.130 | 0.000 | 0.3733 | 0.1416 | -0.1375 | 48.33% | +0.0011 | -0.1300 | 47.91% | -0.0000 | +0.0369 |
| 23:45 14Jul | 0.130 | 0.000 | 0.3733 | 0.1416 | -0.1875 | 47.02% | +0.0081 | -0.1300 | 47.00% | -0.0000 | +0.0451 |