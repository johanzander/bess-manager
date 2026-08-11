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

**Status: Passes 1 and 2 done, Pass 3 not started.** Sections marked ⬜ are not
yet done. Nothing here is approved until the maintainer signs it off.

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
Only #278 is a behavioural change; ⬜ confirm its parity test still
discriminates.

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

**One open item for the maintainer, not a defect:** #241 asked for a
`shutdown_hardware` hook. What exists instead is `leave_control_mode` on a
deliberate platform/control-mode switch, plus the VPP fallback timer covering
crash and stop. That is sound engineering — the dead-man's-switch is a better
guarantee than a shutdown hook, which cannot run on a crash — but ridax was
never told, so from his side the request looks silently dropped. Worth a
comment on #241.

---

## Pass 3 — every pinned test ⬜ NOT STARTED

For each pinned/golden test: what does it actually assert, can it pass
vacuously, and was it verified to fail without its fix? **Maintainer approves
each one individually.**

Known entries to cover: the action-selector goldens (36 fixtures), the VPP
baseline (#541), `assert_flow_coherence`, the plan-faithfulness R==P corpus,
`test_scenarios` expected_results, `KNOWN_PLAN_EXECUTION_GAP_SEK`, and the
per-issue regression files.

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
