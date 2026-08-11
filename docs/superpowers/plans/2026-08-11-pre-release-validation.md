# Pre-release validation: does the refactored implementation still behave?

**Purpose.** Before cutting a beta, confirm that every algorithm and
inverter-control change of the last month still renders the **same or better**
behaviour on today's `main` — one PR at a time, one pinned test at a time.

**The specific fear this addresses.** ridax67 and Frank-Leysen between them
reported 29 issues, 25 of them closed. Those fixes must not resurface. Most of
ridax's are Growatt VPP, which was the platform with the *least* automated
coverage: `inverter_simulator` is TOU-only, so until #541 merged (2026-08-11)
there was no VPP regression baseline at all, and a VPP fix was guarded by unit
tests or by nothing.

**That framing turned out to be half right, and the wrong half matters.** It is
true for *behavioural* coverage. But the single completely unguarded fix Pass 2
found (#302) is on the **TOU** side, and it is a crash — no simulator on either
platform would have caught it. Coverage thinness and platform are less
correlated than this document originally assumed; see the Pass 2 findings.

**Every verification here means: the guard was made to FAIL by reverting the
behaviour it protects.** A guard that passes both ways is not evidence, and
several in this codebase have been exactly that. This rule is now in
`rules.md` and the `implement-issue` skill so it applies to new work too,
along with its companion — assert outcomes, not the commands written to
hardware.

**Status: Passes 1, 2 and 3 done; Pass 3's five findings approved and
implemented (2026-08-11).** F1 and F5 changed how existing pins compare, F2 and
F3 added coverage that was missing, F4 was a question and is answered. See
Pass 3's Resolution table.

---

## Method (and one correction already forced on it)

For each item: *what was reported* → *what guards it today* → *does the guard
actually pin the reported symptom, or a proxy for it?*

That last question is the one that matters. This session repeatedly found
tests that passed while proving less than claimed — a bound asserted on one
side only, a comparison whose signal was swamped, a harness whose model was
wrong. A green suite is evidence that the suite is satisfied, not that the
behaviour holds.

**Correction to the first method attempted (2026-08-11).** The initial sweep
searched the test suite for each issue *number* and reported "13 of 26
reporter issues have no test". That was an overstatement, and checking one
case disproved it: #310/#311 ("wrote tou while running vpp", "not staying in
vpp") are guarded by `test_solax_modbus_growatt_vpp.py::test_no_tou_segments_written`,
which never cites either number. Guards must be found by **behaviour**, not by
issue reference.

The real defect the number-search found is therefore **traceability**: you
cannot tell, from a test, which reporter's bug it protects. That is worth
fixing, but it is not the same as being unprotected.

---

## Scope

161 PRs merged since 2026-07-11; **83** touch the algorithm or inverter
control. Filter: any change under `dp_battery_algorithm`, `action_selector`,
`pwl_window_dp`, `tie_detection`, `tie_policy`, `dp_constants`,
`strategic_intent`, `schedule_splicer`, `models`, `energy_flow_calculator`,
`battery_system_manager`, `inverter_controller`, `*_controller.py`,
`simulation/`, `growatt_schedule`.

---

## Pass 1 — do the guards still exist? ✅ DONE

Mechanical check: for each of the 83 PRs, do the test files it touched still
exist on `main`?

| Result | Count |
|---|---|
| All test files still present | **75** |
| Touched no test file | 5 |
| A test file is now missing | 3 |

**The 3 missing all point at one deleted file, and the deletion was a
strengthening — verified, not taken on trust.** #508, #510 and #511 each
touched `core/bess/tests/unit/test_flow_coherence.py`, deleted in `33f62129`.
That same commit migrated its content into `helpers.py::assert_flow_coherence`
(6 assertions: four source/destination balances, the home-consumption balance,
and non-negativity across all named flows) and wired it into the canonical
scenario harness, so it now runs over the whole corpus rather than one file.
Confirmed on `main`: the function carries 6 assertions and has 3 call sites.

**The 5 with no test** are #278 (numpy vectorization — covered by
`test_vectorized_backward_parity`), #283, #343 (logging), #361, #498 (docs).
Only #278 is a behavioural change.

✅ **Confirmed 2026-08-11 — it discriminates, and strongly.** Four drifts were
introduced into the vectorized twin only, leaving the scalar evaluator the
selector uses untouched — which is #278's exact risk shape, since V is never
compared against anything downstream and drift is therefore silent:

| Drift injected into the vectorized pass | Tests failing (of 14) |
|---|---|
| STORE branch stops honouring the #429 import cap | 3 |
| load branch stops honouring the same cap | 3 |
| STORE wear term off by 0.1% | 12 |
| IDLE wear term off by 0.1% | 12 |

The cap mutations fail only the parametrizations that set `import_cap_kwh`,
which is the correct blast radius rather than a weakness.

---

## Pass 2 — reporter issues, one by one ✅ DONE (2026-08-11)

The closed ridax67 / Frank-Leysen issues, each traced to the behaviour that
must still hold. **Guard column is by behaviour, not by issue number.**

**Result: 17 genuine, 2 defective, 1 out of scope.** Every ✅ below means the
fix was reverted in the working tree and a named test was observed to fail.
Both defects were closed in the same session, each with a new test verified to
fail without its fix.

| Issue | Reported | Guard on main | Verified |
|---|---|---|---|
| #310 wrote tou while running vpp | VPP mode wrote TOU entities | `test_solax_modbus_growatt_vpp::test_no_tou_segments_written` | ✅ routing `apply_period` through `_apply_period_tou` in VPP mode fails it |
| #311 not staying in vpp | fell back to TOU mode | same as #310 | ✅ same revert |
| #309 do not scramble tou table | TOU slot 1 rewritten while in VPP | same as #310 | ✅ same revert |
| #324 Vpp battery dump | SOC 11% → `grid_first power -100`, immediate full dump | `test_vpp_discharge_gate_capability` | ✅ removing the `discharge_rate_is_load_following` exclusion fails 2 of its 3 tests |
| #316 charging → 100% discharge | battery dump | same as #324 — confirmed same cluster | ✅ same revert, same 2 tests |
| #355 lost sense of battery wear cost | SOLAR_EXPORT fell back to self-use, draining SOC | `test_solax_modbus_growatt_vpp` (hold keeps remote control enabled) | ✅ regressing the hold to `0, False` fails 3 tests |
| #398 Vpp power percentage is off | stale power-cap snapshot after a settings change | `test_bsm_settings_and_lifecycle::TestUpdateSettings` | ✅ dropping the snapshot refresh fails 2 tests |
| #404 Vpp fall back to load first | 20-min dead-man's-switch lapsed during a stable run | `TestApplyPeriodVpp::test_unchanged_active_command_refreshes_timer` | ✅ restoring write-on-change fails it |
| #421 Vpp power 0 before power -99 | spurious 0% command from a hardcoded `battery_action_kw=0.0` stub | `TestWriteScheduleToHardwareVpp` | ✅ restoring the stub write fails 3 tests |
| #479 Disabling of Vpp status setting | VPP stayed enabled after switching to TOU, overriding TOU writes | `TestSwitchControlMode`, `TestSwitchInverterPlatform` | ✅ making `leave_control_mode` a no-op fails 3 tests |
| #241 shutdown method | inverter left locked in VPP | `leave_control_mode` (deliberate switch) + the 20-min fallback timer (crash/stop) | ✅ folds into #479 — **but this is not the `shutdown_hardware` hook ridax asked for, and the reasoning was never explained to him** |
| #201 critical system issues | health banner stuck on ERROR after sensors recovered | `TestRefreshHealthCheck::test_updates_cached_results_from_a_fresh_run` | ✅ not clearing `_critical_sensor_failures` on a healthy run fails it |
| #415 Confusing presentation | TOU mode labels fabricated for VPP/period-list platforms | `test_mode_display_fields` + `inverter-schedule-control-model.spec.ts` | ✅ returning `batt_mode` for every CONTROL_MODEL fails 10 tests |
| #308 supports_charge_rate_control | VPP mode claimed EMS rate control it does not have | `test_platform_capabilities` | ✅ forcing it True fails 2 tests |
| #376 ENTSO-e tomorrow prices stay zero | all-zero placeholder accepted as real prices until restart | `TestEntsoeSourceFailures::test_all_zero_prices_treated_as_not_yet_available` | ✅ removing the all-zero raise fails it |
| #126 Belpex/ENTSO-e | hourly Belgian prices unsupported | 33 unit tests + e2e scenario `ci-wizard-entsoe-frank-126.json` | ✅ covered — and that filename is the per-reporter traceability Pass 1 found missing |
| #248, #329 minimize flash wear | status/AC-charging rewritten repeatedly | `TestNoRedundantWritesAcrossCycles` (same instance, two applies) | ✅ — see #399 for the case it does *not* cover |
| **#399 Vpp unnecessary flash writes** | status/AC-charging rewritten **on every restart** | was `test_seeds_state_from_hardware` | ⚠️ **PROXY GUARD.** It asserted `_vpp_status_confirmed` is seeded — the mechanism, not the write count. Stays green if the flag is seeded and then ignored. #329's write-count test never reaches the read-back path, because that instance already set the flag from its own first write. **Fixed:** `test_restart_with_status_already_enabled_writes_no_flash_registers` — fresh controller, already-Enabled inverter, zero flash writes, plus a positive assertion that the period command still goes out. **Then improved again in review** (`9b65b825`, merged with #541): the two flash registers are now confirmed *per register* and both are read back, because they can drift apart (a user toggle, a firmware reset, a write that failed between the two) and rewriting the healthy one is precisely the wear #399 asked to remove. Re-verified on merged `main` 2026-08-11: blanking both read-backs fails **4** tests, up from 1 |
| **#302 TOU slot 1 end=00:00** | HA `select_option` 500 while setting `tou_time_1_end`, on the DST fall-back day | **none** | ⚠️ **UNGUARDED.** Deleting the DST end-time cap in `_groups_to_tou_intervals` left all 1714 fast tests green; the interval is then emitted as `24:59`. The fall-back day comes once a year, so a refactor could drop the cap in September and the first signal would be a user's inverter failing on the changeover night. **Fixed:** `test_dst_fall_back_never_writes_an_invalid_end_time`, asserting the emitted interval's times are valid wall-clock values |
| #192 Check grid charge state | HA 502 Bad Gateway on a sensor read | n/a | **out of scope** — transient supervisor error, closed 2026-06-27, before the audit window; not something this refactor can regress |
| ~~#289, #300, #304, #328, #448~~ | **questions, not bugs — out of scope** (maintainer, 2026-08-11). Nothing to regress. | n/a | n/a |

### Re-verified against merged `main` (2026-08-11)

Pass 2 ran on a branch. After #540 and #541 merged, both defect fixes were
re-checked against `main` as a reader would find it — the fix reverted, the
suite run, the named test observed to fail, the tree restored:

| | on branch | on merged `main` |
|---|---|---|
| #302 — delete the DST end-time cap | 1 test fails | 1 test fails ✅ |
| #399 — blank the hardware read-back | 1 test fails | **4** tests fail ✅ |

The #399 improvement came from review, not from this audit
(`9b65b825`). Worth recording because it is the counter-example to the
pattern below: a guard that got *stronger* between being written and being
merged, because someone asked what else could drift.

### What Pass 2 established beyond the individual results

**Both defects were guards that asserted what the fix changed rather than what
the reporter measured.** #399 asserted an internal flag instead of a write
count; #302 asserted nothing at all. That is the same failure this audit found
in `test_real_day_has_charge_neither_source_explains` earlier in the session.
Three instances is a pattern, and it is now a rule in `rules.md` and the
`implement-issue` skill rather than a habit.

**#324's revert fails 2 of 3 tests, and the surviving one is the VPP mapping
lossiness.** The LOAD_SUPPORT case does not fail because `_intent_to_vpp`
returns `(0, False)` for LOAD_SUPPORT regardless of `discharge_rate`, so the
gate raising the ceiling cannot change the VPP command at all. This is the same
101-rates-to-1-command collapse that killed #537's design, surfacing
independently in a test written months earlier. See
`test_platform_mapping_fidelity.py`.

**The thin coverage was not where it was predicted to be.** Going in, the
assumption was that VPP was exposed because `inverter_simulator` is TOU-only.
That holds for *behavioural* coverage — but the one completely unguarded fix
(#302) is on the TOU side, and it is a crash rather than a behaviour. Crash
paths are thin on both platforms, and no simulator would have caught it.

**#241 — right conclusion, wrong reason. Corrected 2026-08-11.** Pass 2
recorded that a `shutdown_hardware` hook was unnecessary because
`leave_control_mode` covers the deliberate switch *and the VPP fallback timer
covers crash and stop* — "the dead-man's-switch is a better guarantee than a
shutdown hook, which cannot run on a crash."

The second clause is false. Maintainer, on #241: *"leave_control_mode is the
correct method, the VPP timer would not turn off VPP mode."* The timer stops
the inverter obeying a stale power command (#404's mechanism); it does not
clear `vpp_status`. Nothing runs `leave_control_mode` on stop either — both
call sites (`battery_system_manager.py:386`, `:439`) fire only on a deliberate
platform or control-mode switch, and `backend/app.py`'s `lifespan` has no
shutdown body.

**But not disabling VPP on shutdown is correct, for a reason neither Pass 2 nor
the first correction to it gave.** `leave_control_mode` clears VPP Status
(`solax_modbus_growatt_controller.py:443`), and ridax confirmed on #520
(2026-08-11, from Growatt's V2.01 protocol) that `vpp_status` is a **flash**
register. Clearing it on shutdown would mean a flash write on every add-on
stop — every config change, every HA restart, every update — which is the wear
ridax opened #399 about. A shutdown hook here would be a regression, not a
fix. Disabling VPP only on a deliberate switch is the design, and it is right.

Recorded because the audit reached the correct verdict twice while reasoning
from a hardware property nobody had checked, and the honest version of "this is
fine" is a different sentence from the one that was written.

---

## Pass 3 — every pinned test ⚠️ DONE (2026-08-11), 7 items for sign-off

For each pinned/golden test: what does it actually assert, can it pass
vacuously, and was it verified to fail without its fix? **Maintainer approves
each one individually — nothing below has been re-pinned or changed.**

### Method: measured, not read

Vacuity is not decidable by reading a test. Four reversions of real merged
fixes were applied one at a time, each instrument re-run against each, and the
failures counted. Every mutant was reverted in a `finally` block and the tree
verified clean afterwards.

| Mutant — fix reverted | goldens (actions+SoE) | `test_scenarios` | strict R==P | VPP baseline | fast suite |
|---|---|---|---|---|---|
| M1 — #466 off-lattice residual-cover candidate removed | 2 / 36 | 2 | 0 | 2 | — |
| M2 — #497 executability filter removed | 25 / 36 | 26 | 1 | 25 | — |
| M3 — #526 gate forced always-allowed | **0** | **0** | **0** | **0** | **4** |
| M4 — battery discharge split broken (reporting only) | 0 | 29 | 2 | 11 | — |

The goldens report a constant 27 raw failures under every mutant *including no
mutant at all*; see the environment defect below. The column above counts only
fixtures whose `actions`/`soe_trajectory` moved, which is the portable signal.

### The instruments, one by one

| # | Pin | What it actually asserts | Can it pass vacuously? | Ever seen to fail? |
|---|---|---|---|---|
| 1 | **Action-selector goldens** — 36 fixtures, `golden_capture.py` / `test_action_selector_parity.py` | Per fixture: `battery_action` per period, the SoE trajectory, and `battery_solar_cost`, bit-identical `==` | **Partly.** It pins the *plan's magnitudes only*. It does not pin `strategic_intent`, `intra_period_discharge_allowed`, or any flow — M3 rewrote the gate on every period and moved 0 of 36. One fixture (`historical_2025_01_05_no_spread_no_solar`) is all-IDLE with a flat SoE, so its golden can only ever detect *spurious* activity, never lost activity | Yes — M1 fails 2, M2 fails 25. Never regenerated since creation (`1930547`, #521); Phase 2 (#525), #526/#530, Phase 3 (#534) and #524 all landed after it and moved no fixture's actions or SoE |
| 2 | **`test_scenarios` `expected_results`** — 33 of 36 fixtures | 4 economic scalars vs pinned, `abs=0.001` SEK (0.01 for pct) | **No, since the 2026-08-11 tightening.** Measured headroom across all 33: median 0.000002, max 0.000005 on every one of the four fields — a 200x margin to the gate. 3 fixtures carry no `expected_results` at all | Yes — M1 fails 2, M2 fails 26, M4 fails 29 |
| 3 | **Plan-faithfulness R==P, strict** — `test_realized_matches_planned_across_all_fixtures` | R − P == the fixture's known gap, `abs=0.001` SEK, no per-fixture exemptions | **No.** Measured gaps: 0.00000 on 35 of 36, +0.02140 on the 36th | Yes — M2 fails 1, M4 fails 2 |
| 4 | **Plan-faithfulness R==P, in-scenario copy** — inside `test_all_scenarios` | Same comparison, tolerance `max(0.5, 1% of P)` | **Yes — it is subsumed.** It carries 0.5 SEK of slack against a measured 0.0 SEK signal, 500x looser than instrument 3 over the same corpus. It also derives commands *without* `intra_period_discharge_allowed` where instrument 3 passes it — measured, the two produce identical realized cost on 36 of 36, so the difference is currently inert rather than a second opinion | Never independently — every mutant that moves it also moves instrument 3 first |
| 5 | **`assert_flow_coherence`** — `helpers.py`, 3 call sites | 5 balance identities (export sources, home supply, discharge split, charge split, import destinations) at 1e-6, plus non-negativity over 7 named flows | **The 5 balances, no** — M4 breaks one and 29 scenarios fail. **The 7 non-negativity checks, yes:** every flow is produced in `models.py::_calculate_detailed_flows` as a `min`/`max` clamp of non-negative quantities (`solar_to_home = min(solar_production, home_consumption)` onward), so none can be negative on the only path that builds these records | Yes, for the balances (M4) |
| 6 | **`KNOWN_PLAN_EXECUTION_GAP_SEK`** | One entry: `regression_2026_08_08_143843` = +0.0214, asserted from 2 places | **No, and it is tight.** Measured +0.021401 against the pin, `abs(Δ)` = 0.000001 against a 0.001 tolerance | It is a pin on a known simulator blindness (#502 curtailment), not on a fix. Its stated exit condition is deletion when the simulator learns curtailment |
| 7 | **VPP baseline (#541)** — 3 tests × 36 fixtures, 74 total | Replay of v10.0.2's plan through today's VPP model (commands, realized cost, SoE); today's plan pinned per fixture; a drift count of 35 | **Mostly no.** All 36 have a real v10.0.2 plan, so `plan: null` skips 0 — the skip path is currently unreachable. 4 fixtures have ≤2 distinct VPP commands across the whole horizon and 1 (`historical_2025_01_05...`) has exactly one, `(1, True)` × 24 | Yes — M2 fails 25, M4 fails 11 |

### Per-issue regression fixtures

All 8 `regression_*.json` files in `core/bess/tests/unit/data/` are reachable
from at least one named test; 7 of 8 from a test whose name or docstring cites
the issue. `regression_bess_debug_2026_08_07` is referenced only from
`test_scenarios.py`, but that reference is
`test_466_sunrise_crossover_covers_residual_load_instead_of_idle`, a named
symptom test — not the generic corpus sweep.

### Findings for sign-off

**F1 — the goldens' cost pin is not portable, and `numpy` is unpinned.**
`battery_solar_cost` is compared with `==`. On Python 3.11.15 / numpy 2.4.6,
27 of 36 fixtures differ from the recorded value by 1e-16 to 5.7e-14 — actions
and SoE trajectories are bit-identical on all 36, and CI is green on `main` at
`d09b394a` (py3.13, algorithm job included). So this is last-ulp summation
order, not behaviour. `backend/requirements.txt` pins no numpy version, so a
numpy bump reproduces this in CI. The hazard is not the red run, it is the
trained response to it — "goldens are red again, re-capture" is how a real
change gets absorbed. The smallest genuine cost movement recorded anywhere in
this audit is 0.0181 SEK, twelve orders of magnitude above the noise.
*Options, for the maintainer:* (a) pin `battery_solar_cost` at `abs=1e-9` and
keep `actions`/`soe_trajectory` bit-exact — note this contradicts the test's
own docstring, which argues bit-exactness deliberately for Phase 1's purpose;
(b) pin numpy; (c) both. Phase 1 is merged, and the goldens' remaining job is
ongoing regression detection, where cross-environment reproducibility is worth
more than ULP-exactness — but that is a judgement call, not a defect.

**F2 — no pinned instrument covers the intra-period discharge gate.**
M3 forced `intra_period_discharge_allowed = True` on every period, destroying
#526's shadow-price authorization — the mechanism #520 and #524 rest on — and
all four pinned instruments stayed green. Coverage is real but rests entirely
on 4 named unit tests
(`test_discharge_gate_authorization_526.py` ×2,
`test_load_support_gate_regression_393.py`,
`test_solar_export_discharge_gate.py`), none of which is a pin or golden. This
is the area carrying #537's withdrawn design and 118.11 kWh across 172
gate-closed periods, and it is the one place where "the corpus pins are green"
carries no information at all.

**F3 — 27 fixtures record an energy-throughput pin that no test reads.**
`expected_results.total_charged` / `total_discharged` exist in 27 fixtures and
are asserted nowhere. Measured against today's plans, all 27 are still
*accurate* to <0.001 kWh — so this is unused correct data, not rot. Wiring
them up is a zero-cost strengthening that adds a physical quantity the cost
scalars cannot express: two plans can cost the same and cycle the battery
differently.

**F4 — one fixture is degenerate across every instrument at once.**
`historical_2025_01_05_no_spread_no_solar`: all 24 actions 0.0, SoE flat at
3.0, `battery_solar_cost` == `grid_only_cost` == 282.789, savings 0.0, a single
distinct VPP command for the whole horizon, and R == P by construction. Its
golden, its `expected_results`, its R==P entry and its VPP baseline entry are
all satisfied without the optimizer doing anything.

*Root cause (`bess-analyst`, 2026-08-11): all-IDLE is economically correct, and
the fixture sits on a knife-edge.* Three things stack up. The battery starts at
`initial_soe == min_soe_kwh == 3.0`, so it has **zero usable energy** and must
buy before it can deliver. The cheap hours (20-23, down to 0.40 raw) all fall
*after* the expensive ones (08-12, up to 1.30), so the obvious arbitrage runs
backwards in time — despite the name, the raw spread is 0.9 SEK, not flat. And
of all 276 ordered charge→discharge pairs, exactly one is positive: h0→h11, at
**+0.0015 SEK/kWh**. Breakeven cycle cost for that pair is 0.4014 against the
configured 0.40 — the fixture is 0.4% on the dead side. Even that margin is
unrealizable, because the STORE disposition is rate-quantized (`_period_flows`
ignores the candidate's power magnitude), so a charge hour is all-or-nothing
6.0 kWh against only 5.2 kWh of displaceable load at h11, making the executable
version **0.018 SEK worse than idling**. Confirmed by construction: dropping
`cycle_cost_per_kwh` to 0.35 immediately produces a trade (0.196 SEK saved).

Two corrections this forced on the audit's own first arithmetic, both worth
recording because they are easy to repeat: wear is charged per kWh **stored**,
so per kWh *delivered* it is `cycle_cost / η_discharge` = 0.4211, not 0.40; and
this fixture overrides `additional_costs` to 1.03 in its own `price_data`, not
the 0.773 default — an additive grid fee is paid on `1/η²` kWh bought but
recovered on only 1 kWh delivered. Together those turned a hand-computed
"+0.0504 SEK/kWh, apparently profitable" into breakeven. This is exactly why
profitability figures go to `bess-analyst` rather than being derived in the
main session.

The fixture still earns its place — it detects spurious cycling on a
genuinely-breakeven day, and being 0.4% from the edge makes it *sensitive* in
that direction — but it is one-sided, and its own `expected_behavior`
description ("mostly idle with some load support") describes a plan with zero
LOAD_SUPPORT periods.

**F5 — `expected_behavior` intent assertions are existence-only.**
`assert_intent_present` passes on a single period out of up to 134, so it
detects an intent class disappearing entirely and nothing short of that. Two
are satisfied by ≥80% of periods (`historical_2025_01_05` IDLE at 100%,
`realworld_2026_03_24_225535` IDLE at 88%). Several `intents_absent` entries
are unfalsifiable by construction — SOLAR_STORAGE declared absent on a
fixture with no solar.

### Resolution — approved and implemented (2026-08-11)

All five were put to the maintainer and approved. What changed:

| | Decision | Implementation | Seen to fail? |
|---|---|---|---|
| **F1** | Both halves: tolerance *and* the numpy pin | `battery_solar_cost` compared at `abs=1e-9` (`actions`, `intents`, `soe_trajectory` stay `==`), and `numpy==2.5.2` in `backend/requirements.txt` | n/a — this *removes* a false red. Validated in the other direction instead: green on py3.12.13/numpy 2.5.2 and py3.13, red on 27 of 36 at py3.11.15/numpy 2.4.6, same commit, plan bit-identical in all three |
| **F2** | Add the missing pin | `intra_period_discharge_allowed` pinned per period in the goldens (2168 periods, 1203 open / 965 closed, 31 of 36 fixtures mixed), plus `test_intra_period_gate_outcome.py` asserting the gate's effect on realized cost and SoE | ✅ both, and they are complementary — see below |
| **F3** | Wire it up | `total_charged` / `total_discharged` asserted at 0.001 kWh for the 27 fixtures that carry them | Pins what was already measured true; the 6 `regression_*` fixtures without the keys are skipped explicitly, not defaulted to 0.0 |
| **F4** | Understand it | Root cause established above; no code or fixture changed | n/a |
| **F5** | Replace existence checks with per-period pinning | `intents` pinned per period in the goldens (2168 periods); the `intents_present`/`intents_absent` loops removed from `test_all_scenarios` | ✅ strictly stronger — the old check passed on 1 period out of up to 134 |

**The two F2 guards catch different mutations, which is the point.** Measured:

| Mutation | goldens | `test_intra_period_gate_outcome` |
|---|---|---|
| `intra_period_discharge_gate` returns 100 unconditionally | 37 passed | **2 of 3 fail** |
| DP forces `intra_period_discharge_allowed = True` (Pass 3's M3) | **29 of 37 fail** | 3 passed |

Neither covers the gate alone: the goldens pin *what the DP decided*, the
outcome test pins *that the decision is worth deciding*. An earlier draft of
the outcome test drove `simulate` with a rate directly and would have caught
neither — it was rerouted through `derive_control_command` so the ceiling comes
from the real `_gated_discharge_rate` path.

Goldens were regenerated to add the two new fields, verified additive:
`actions` and `soe_trajectory` bit-identical to the pre-audit goldens on all
36, max cost delta 0. Full suite green afterwards — 1721 fast, 534 slow.

**On pinning numpy as well as loosening the pin.** These fix different
failures and neither subsumes the other. The tolerance stops a numpy bump
reddening the goldens over noise; the pin stops a numpy bump moving *reported
costs* — the savings figures users read — silently and without any test
objecting, which no tolerance can catch because the tolerance is precisely
what lets it through. `numpy==2.5.2` has manylinux, musllinux (the Alpine
add-on image) and macOS wheels for cp312/313/314, and resolves cleanly
alongside `pandas`.

### Pass 2 re-verified against current `main`

`solax_modbus_growatt_controller.py` changed in `9a05009` (#541) after Pass 2
measured it, so its four checks in that file were re-run on `main`:

| Reverted fix | Tests failing in `test_solax_modbus_growatt_vpp.py` | Named guard |
|---|---|---|
| #404 drop the timer refresh | 2 | `test_unchanged_active_command_refreshes_timer` fails ✅ |
| #421 restore the power=0 stub write | 2 | `TestWriteScheduleToHardwareVpp`, 2 of 4 fail ✅ |
| #355 regress the hold to `(0, False)` | 3 | matches Pass 2's recorded 3 ✅ |
| #310/#311 route `apply_period` through TOU | 13 | `test_no_tou_segments_written` fails ✅ |

All four still discriminate. Pass 2 recorded #421 as failing 3 tests where this
run measures 2; the revert here was reconstructed from the docstring rather
than replaying Pass 2's exact edit, so the difference is at least as likely to
be the reconstruction as a weakening.

---

## Standing risk, independent of this audit

**Closed 2026-08-11: #541 merged**, so Growatt VPP now has an execution
simulation and a v10.0.2 baseline. Before it, ridax's VPP fixes were guarded by
unit tests only — which pin *commands*, not *outcomes* — the thinnest coverage
of any platform, on the platform with the most reported history.

Two limits on what that closure buys, both load-bearing for Pass 3:

- **The harness reads "changed", never "worse".** At 15-minute point forecasts
  there is no within-period load spike, so it models the intra-period gate's
  cost but never its benefit, and will score any gate-closed change as a loss
  whether or not it is one. Against a fixed baseline the bias cancels; quoting
  a delta as an economic verdict is the misuse to guard against.
- **It would not have caught #537.** The defect was in what a platform can
  *execute*, not in what the plan costs. That gap is now covered separately by
  `test_platform_mapping_fidelity.py`, which is a different instrument
  answering a different question — see the #537 note below.

**#537 is no longer a standing risk — it is a withdrawn design (2026-08-11).**
It mapped #520's closed discharge gate onto VPP as a `battery_first` hold. On
TOU, gate-closed still delivers the planned discharge and merely declines to
raise the ceiling; on VPP a hold delivers nothing. Measured on the corpus, all
172 gate-closed LOAD_SUPPORT periods carry a real planned discharge totalling
**118.11 kWh**, every one of which the PR would have abandoned. Converted to
draft pending redesign.

The cause was one inference: VPP carries BATTERY_EXPORT's planned magnitude
faithfully (`power_pct` is the plan-scaled rate, negated), so it looked as if
VPP could express "discharge, but only this much" generally. LOAD_SUPPORT is
the single intent where it cannot — 101 distinct planned rates collapse to 1
command. `test_platform_mapping_fidelity.py` now sweeps the full planned-action
range per intent and pins which intents are lossy, so that asymmetry is stated
rather than rediscovered.

Note what caught it: not a test, and not the VPP simulator built for exactly
this question — by its own docstring that harness scores a gate-closed change
as a loss whether or not it is one. It was ridax's #520 comment, *"I feel it
should do this in all modes except IDLE."* The instrument now exists, but the
signal came from the person running the hardware.
