# Pre-release validation: does the refactored implementation still behave?

**Purpose.** Before cutting a beta, confirm that every algorithm and
inverter-control change of the last month still renders the **same or better**
behaviour on today's `main` — one PR at a time, one pinned test at a time.

**The specific fear this addresses.** ridax67 and Frank-Leysen between them
reported 29 issues, 25 of them closed. Those fixes must not resurface. Most of
ridax's are Growatt VPP, which is the platform with the *least* automated
coverage: `inverter_simulator` is TOU-only, so until #539/#541 lands there is
no VPP regression baseline at all. A VPP fix is guarded by unit tests or by
nothing.

**Every verification here means: the guard was made to FAIL by reverting the
behaviour it protects.** A guard that passes both ways is not evidence, and
several in this codebase have been exactly that. This rule is now in
`rules.md` and the `implement-issue` skill so it applies to new work too,
along with its companion — assert outcomes, not the commands written to
hardware.

**Status: IN PROGRESS.** Sections marked ⬜ are not yet done. Nothing here is
approved until the maintainer signs it off.

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

## Pass 2 — reporter issues, one by one ⬜ IN PROGRESS

The 25 closed ridax67 / Frank-Leysen issues, each traced to the behaviour that
must still hold. **Guard column is by behaviour, not by issue number.**

| Issue | Reported | Guard on main | Verified |
|---|---|---|---|
| #310 wrote tou while running vpp | VPP mode wrote TOU entities | `test_solax_modbus_growatt_vpp::test_no_tou_segments_written` | ✅ guard located |
| #311 not staying in vpp | fell back to TOU mode | same as #310 | ✅ guard located |
| #324 Vpp battery dump | SOC 11% → `grid_first power -100`, immediate full dump | `test_vpp_discharge_gate_capability` | ✅ **verified discriminating** — removing the `discharge_rate_is_load_following` exclusion fails 2 of its 3 tests, so it pins the mechanism, not a proxy |
| #355 lost sense of battery wear cost | SOLAR_EXPORT fell back to self-use, draining SOC | `test_solax_modbus_growatt_vpp` (hold keeps remote control enabled) | ✅ **verified discriminating** — regressing the hold to `0, False` fails 3 tests |
| #398 Vpp power percentage is off | | 2 test refs | ⬜ |
| #399 Vpp unnecessary flash writes | | 2 test refs | ⬜ |
| #404 Vpp fall back to load first | 20-min timeout lapsed | 2 test refs, 4 code | ⬜ |
| #421 Vpp power 0 before power -99 | spurious 0% command | 2 test refs | ⬜ |
| #479 Disabling of Vpp status setting | | 2 test refs, 4 code | ⬜ |
| #415 Confusing presentation | UI | 4 test refs | ⬜ |
| #309 do not scramble tou table | | 2 test refs | ⬜ |
| #302 TOU slot 1 end=00:00 | | 2 test refs | ⬜ |
| #329 flash writes | | 2 test refs | ⬜ |
| #201 critical system issues | | 2 test refs | ⬜ |
| #126 Belpex/ENTSO-e | | 10 test refs | ⬜ |
| #316 charging → 100% discharge | battery dump | likely the #324 cluster — ⬜ confirm | ⬜ |
| #192, #241, #248, #308, #376 | infra / flash / prices | ⬜ locate by behaviour | ⬜ |
| ~~#289, #300, #304, #328, #448~~ | **questions, not bugs — out of scope** (maintainer, 2026-08-11). Nothing to regress. | n/a | n/a |

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

Growatt VPP has no execution simulation until #541 merges, and #537 changes
VPP behaviour on 28.5% of LOAD_SUPPORT periods. Until both settle, ridax's
VPP fixes are guarded by unit tests only — which pin *commands*, not
*outcomes*. That is the thinnest coverage of any platform, on the platform
with the most reported history.
