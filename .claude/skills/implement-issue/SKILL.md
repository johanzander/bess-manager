---
name: implement-issue
description: Use when asked to implement, fix, or resolve a bess-manager GitHub issue end-to-end from the command line, especially when local verification (not just CI) is wanted before the PR opens.
---

# Implement Issue

## Overview

Drive a bess-manager GitHub issue from diagnosis to a locally-verified draft
PR against `main`. This is the CLI counterpart to the `@claude-bot analyze` +
`@claude-bot fix` pipeline (`docs/agents/workflow.md`) — same diagnose-then-fix
shape, but with the one thing the bot pipeline structurally cannot do: run the
app locally and observe the fix working before the PR opens. That local
verification step is the entire reason to run this from the command line
instead of the bot, so it is never optional.

This skill orchestrates other skills — it does not re-implement them:
`superpowers:using-git-worktrees`, `superpowers:test-driven-development`,
`superpowers:finishing-a-development-branch`, `code-review`, `verify`, and
the `bess-analyst` sub-agent.

## When to Use

- User gives you a bess-manager issue number/URL and asks you to implement,
  fix, or resolve it locally.
- **Or a PR number, or a `TODO.md` item, or a refactor with no issue at all.**
  Issue-driven is the common case, not the only one. Step 0 resolves a bare
  number to whichever it is, since GitHub numbers issues and PRs from one
  sequence. Where there is no issue, the Step 2 diagnosis comes from the
  maintainer's own framing rather than a Stage 2 comment, and Step 9 records it
  in the PR body as usual.
- Not for the `feature-lifecycle` multi-release integration flow (new
  inverter/price-provider platforms) — that skill owns experimental→stable
  graduation across multiple beta cycles. Use `implement-issue` for
  single-PR bug fixes and small enhancements.
- **Also for picking an issue back up after a session died mid-flight.** Same
  invocation, `/implement-issue <n>`; Step 0 detects the prior work and
  re-enters at the right step. This is not a separate skill because the loop
  that acts on review feedback is Step 11 and lives here — a second skill
  would duplicate it, and duplicating a review loop is how one of them goes
  stale.

**Sessions die mid-issue routinely, and nothing used to pick them up.** A
fleet audit found 34 worktrees whose sessions had exited: 8 with real
unpushed commits and no PR, and three PRs sitting green-or-reviewed with
nobody left to finish them. #615 was `APPROVED` and still a draft the next
morning; #614 had `CHANGES_REQUESTED` with no owner to act on it. That is the
gap Step 0 closes.

## CI mode (GitHub Actions)

`issue-fix.yml` runs this skill on `claude-code-action` instead of duplicating
its instructions. The numbered Process below applies verbatim **except** where
an interactive-session mechanism has a pipeline equivalent, per this table.
User-level plugins (`superpowers:*`, `code-review`) are not installed on CI
runners — only repo-level `.claude/skills/` and `.claude/agents/` exist there.

| Step | CI mode |
|---|---|
| 0. Resume check | Applies, and matters more here: Stage 3 is re-triggered by hand, so a second `@claude-bot fix` on an issue that already has a `has-fix-pr` PR is a resume, not a restart. Detect the existing PR and continue it — never open a second PR for one issue. The CI checkout has no worktrees, so branch existence on `origin` is the only signal available. |
| 2. Diagnose | Stage 2 comment absent → STOP. Post "No deep analysis found. Run `@claude-bot analyze` first" and exit — never self-diagnose in CI; the analyze/fix split *is* the human gate. |
| 3. Confirm gate | The owner's `@claude-bot fix` comment is the go-ahead. Still perform the workaround check and scope assessment — put them in a `## Scope assessment` section of the PR body instead of chat. Escalation path (can't confidently pass the workaround check) still applies: dispatch a fresh general-purpose `Agent` to critique the design before implementing. |
| 4. Worktree | Skip — the CI checkout is already isolated. Create the branch directly (naming per Step 1). |
| 5. TDD | The substance applies verbatim (RED test first, required test shape); there is just no `superpowers:test-driven-development` skill to invoke — follow this section's own rules. |
| 6. Quality gate + code review | Run inline, no background agent (CI is one throwaway session — the cost-discipline reason to background doesn't exist). The `code-review` plugin is unavailable; the Stage-4 `@claude-bot` PR review covers it. Checks 1–3 (fast suite, slow suite, required-test-shape) still apply. |
| 7. Confirm gate 2 | Replaced by the draft PR itself — the owner reviews the draft before anything merges. |
| 8. Local run & observe | Structurally unavailable in CI — this is the documented reason the local flow exists. Skip, and say so in the PR body's test plan so the reviewer knows verification is still owed. |
| 9. Commit + draft PR | Applies verbatim, including the `CHANGELOG.md` `## [Unreleased]` entry and the documentation check. Add the `## Scope assessment` section (Step 3 above). The workflow file owns CI-only mechanics: issue comment with the PR link, `has-fix-pr` label. |
| 10. Watch this PR to green | Applies verbatim — `gh pr checks --watch` on the PR just opened, fix failures, never widen to other PRs. |
| 11. Independent review loop | Skip — CI opens the PR as a draft and the owner triggers Stage 4 by hand after reading it. A CI run that requested its own review would be the fix bot grading itself on a PR nobody has looked at yet. Since the loop never runs here, the PR also stays a draft: `gh pr ready` is Step 11's, and there is no approval in CI mode to earn it. |
| 12. Hard constraints | Apply verbatim. |

## Process

### 0. Resume check — is there prior work for this number?

Run this before Step 1, every time. A fresh issue costs one cheap check; a
resumed one would otherwise lose work.

**`<n>` may be an issue OR a pull request, and you resolve which.** GitHub
numbers issues and PRs from one sequence per repository, so a bare number is
unambiguous and no flag is needed. This is not an edge case: this skill is used
for `TODO.md` items and for refactors that never had an issue, so a PR with no
linked issue is the normal shape for that work, not a defect.

```bash
gh pr view <n> --json number,headRefName,isDraft,mergeable,reviews 2>/dev/null \
  || gh issue view <n> --json number,title,labels,body,comments
```

If `<n>` is a **PR**, resume from it directly — it is the stronger handle,
carrying the branch, the diff, the `## Scope assessment` and the review verdict,
which is everything the table below reads. Read its linked issue too if it
references one, for the diagnosis.

If `<n>` is an **issue**, find its work the usual way:

```bash
gh pr list --state open --search "<n>" --json number,headRefName,isDraft,mergeable,reviews
git worktree list                       # a worktree already on this issue's branch?
git branch --list '*issue-<n>*'         # a branch even without a worktree?
```

**Completion is observable from outside the dead session — read state, never
assume it:**

| Evidence | The dead session got at least to |
|---|---|
| branch or worktree exists | Step 4 |
| commits ahead of `origin/main`, RED test in the diff | Step 5–7 |
| an open PR exists for the branch | Step 9 |
| `gh pr checks` green | Step 10 |
| a terminal review verdict on the PR | Step 11, mid-loop |

Re-enter at the **earliest incomplete** step and run forward normally. A PR
carrying `CHANGES_REQUESTED` re-enters at Step 11's `CHANGES_REQUESTED` branch;
one carrying `APPROVED` needs only `gh pr ready`.

**Rehydrate the diagnosis before touching code.** Step 2's analysis died with
the session, and Step 11 depends on holding it. It is recoverable only because
this skill already forces it to be written down:

- the Stage 2 `@claude-bot analyze` comment on the issue — the root cause
- the PR body's `## Test plan`, and its `## Scope assessment` **if the PR came
  from CI mode** — the agreed approach, and what the test was meant to
  discriminate. Interactive mode keeps its scope assessment conversational, so
  that heading is absent on most PRs this skill opens; the PR's existence is
  what proves Step 9 was reached, not any particular heading
- the diff itself, and any inline review comments

**If those sources do not reconstruct a coherent diagnosis, STOP and report
it.** Do not re-diagnose from scratch on top of someone else's half-finished
branch: you would be building on a design you cannot see, and the commits
already there encode decisions you would silently contradict.

Hard rules, each from an observed failure:

- **Never create a fresh worktree when a branch for this issue already has
  commits.** Step 4 branches from `origin/main`, which discards them. One
  abandoned branch held 32 commits that existed nowhere else.
- **Never `git reset` or force-push a resumed branch.** Its commits are the
  only copy; the session that made them is gone.
- **Check for a live session on that worktree first** (`claude agents --json`,
  run unscoped **and unsandboxed** — the sandbox denies `~/.claude/jobs`, so a
  sandboxed listing silently truncates and a session reads as dead). Two
  sessions on one branch is worse than a stalled one.
- **A worktree with uncommitted tracked changes is unfinished work, not
  debris.** Commit it as a WIP commit before doing anything else, so it is
  recoverable by SHA.
- **If the same issue has died twice, say so and stop.** A second silent
  relaunch is how a real blocker gets mistaken for bad luck.

### 1. Fetch & scope

```bash
gh issue view <n> --json title,body,labels,comments
```

Read chronologically for the CURRENT problem — issues evolve, don't fix a
stale complaint. Branch prefix from label: `bug` → `fix/`, `enhancement` →
`feat/`. Branch name: `<prefix>/issue-<n>-<slug>`.

### 2. Diagnose (conditional)

Check the issue comments for an existing Stage 2 diagnosis: a bot comment
with `## Root cause` / `## Evidence` / `## Proposed fix` sections (label
`analyzed`). This is the common case — issues are usually run through
`@claude-bot analyze` first.

- **Comment present:** use it as the diagnosis. Independently verify by
  reading the cited `file:line` locations against current code — quote real
  code, don't just trust the summary. Do NOT re-run `bess-analyst` from
  scratch.
- **Comment absent:** dispatch `bess-analyst` as a sub-agent (`Agent` tool,
  `subagent_type: bess-analyst`) for a full independent diagnosis — pass it
  the issue title, body, and comment history, and the task: "diagnose
  independently; the reporter's explanation is a hypothesis, not a
  conclusion."

### 3. Confirm gate

Present the root cause, proposed fix, AND its scope assessment per
`docs/agents/rules.md`'s Debugging Protocol step 8. That includes the
**workaround check**: state explicitly that the diff adds nothing — no
parameter, flag, default-fallback, second construction site, extra trigger
or branch — whose only job is to route around an ordering/timing/dependency
problem instead of fixing it. If you can't state that confidently, dispatch
a fresh `Plan`/general-purpose agent to critique the design before
presenting anything. Then the scope category: does the fix stay within
the target method's existing contract (local), does it need a different/new
owner (structural), or does it have multiple plausible owners worth a second
opinion? State which, explicitly — don't let the user infer it from the diff
description. A structural assessment with no stated reason for the chosen
owner is not ready to present. Wait for explicit go-ahead before touching
code. One message — cheap insurance against building an entire
implementation on a wrong diagnosis *or* a wrong placement.

### 4. Worktree + branch

**Prune merged worktrees FIRST — this is the cleanup step, and it lives here
on purpose.** The "After Merge" section at the bottom also removes a
worktree, but it is defined as a separate later invocation, so it depends on
someone choosing to come back — and nobody does. That postcondition ran zero
times in ~40 issues and left 39 worktrees on disk, 24 of them long merged.
Running the prune as a *precondition* of the next issue needs no memory: the
next person to do issue work cleans up the last one's mess automatically.

```bash
# Worktrees whose PR has merged. NOTE: `git branch --merged` / `rev-list
# origin/main..branch` DO NOT WORK here -- this repo squash-merges, so a
# merged branch's commits are never reachable from main and every worktree
# looks unmerged forever. PR state is the only authoritative signal.
merged=$(gh pr list --state merged --limit 200 --json headRefName -q '.[].headRefName')
git worktree list | awk 'NR>1 {print $1}' | while read -r wt; do
  b=$(git -C "$wt" branch --show-current 2>/dev/null)
  [ -n "$b" ] || continue                                   # detached: leave alone
  echo "$merged" | grep -qx "$b" || continue                # not merged: leave alone
  if [ -n "$(git -C "$wt" status --porcelain -uno)" ]; then # tracked edits: never auto-delete
    echo "KEEP (uncommitted changes): $wt"; continue
  fi
  git worktree remove "$wt" && git branch -D "$b"
done
git fetch origin --prune
```

Two guards that matter: never remove a worktree with **uncommitted tracked
changes** — report it and let a human decide (one such worktree held a
375-line module that existed nowhere else) — and never touch a **detached or
locked** worktree, which is usually another agent's live session.

Then `git fetch origin main` — `using-git-worktrees`' git fallback branches
from the current local `HEAD`, not `origin/main`, so a stale local checkout
silently cuts the branch behind main (missed release cuts, changelog
rewrites, other merged fixes), surfacing later as an avoidable merge
conflict. Then invoke `superpowers:using-git-worktrees`, basing the new
branch on `origin/main`.

Then run `./scripts/worktree-setup.sh` in the new worktree — once, before any
test, build or `verify` step. It shares `.venv` and both `node_modules` trees
with the main checkout and repairs a stale Playwright browser cache. Skipping
it means paying ~35 minutes of reinstall against ~5 minutes of real testing,
which is what makes Step 8 feel skippable (#556).

**Do not change the session's worktree while a background agent spawned from
it is still running.** The agent's isolation follows the session, so
switching drags it into the new worktree mid-run — observed in practice: a
`code-review` invocation resolved against the wrong worktree and reviewed an
unrelated docs file instead of the diff. Finish or await the agent first.

### 5. TDD implementation

Invoke `superpowers:test-driven-development`. Write a test that reproduces
the bug (from the diagnosis's evidence — the specific period/scenario/input)
and watch it fail, then write the minimal fix. No refactors outside the bug
— match `docs/agents/patterns.md`.

**Required test shape — checked against the diff, not optional:**

If the fix touches the DP (`dp_battery_algorithm.py`), intent classification
(`strategic_intent.py`), or control/rate mapping (`inverter_controller.py`
/ `battery_system_manager.py`), the PRIMARY RED test — not an extra test
alongside it, the one that proves the bug — is a plan-faithfulness scenario,
not a unit test calling the changed function with hand-built arguments. Write
it as:

```python
from core.bess.tests.helpers import run_scenario_realized
# scenario is a full DP-optimized schedule, not a hand-built period/decision
result, realized_cost = run_scenario_realized(scenario)
assert realized_cost == pytest.approx(result.total_cost, ...)  # R == P
```

A unit test on the changed function directly (e.g. calling
`_apply_period_schedule` or `intra_period_discharge_gate` with stubbed
arguments) can pass while the new branch is unreachable by any real
DP-produced schedule — that is exactly the coverage gap that shipped
undetected in PR #385 (`docs/agents/simulator.md`). Add such a unit test only
as a supplement, never as the sole RED test, for this category of fix.

**Assert the outcome, not the command.** The same rule stated the way it
usually fails: a test that pins the value written to hardware —
`vpp_power=+1`, `discharge_rate=100`, a TOU segment — proves the *mapping* is
unchanged. It does not prove the battery held, the spike was covered, or the
cost moved. Assert realized cost, SoE trajectory, or resulting flows wherever
an execution model exists.

Command-level assertions are legitimate **only** where no execution model
does exist — Growatt VPP before #539, for instance, where
`inverter_simulator` is TOU-only. When you write one, say in the test *why*
the outcome could not be asserted. That note is what stops the next reader
treating a mapping check as behavioural evidence, and it is the seam where
the coverage should later be upgraded.

**Verify the test fails without the fix.** Write it RED first, or revert the
fix and watch it break — then say which you did in the PR body. This is not
ceremony: in this codebase tests have repeatedly passed while proving less
than claimed. A bound asserted on one side only missed the realistic middle;
a whole-day comparison had its signal swamped by a second varying term; a
fixture named a branch it could not reach. Each looked green. "The suite
passes" is evidence the suite is satisfied, never that the behavior holds.

If the diagnosis's evidence is a user-supplied debug log/bundle, build the
scenario from that real data instead of a hand-assembled fixture:

```bash
python scripts/mock_ha/scenarios/from_debug_log.py <bundle.md>
```

(`docs/agents/testing.md` → Bug Reproduction with Mock HA). Do this before
writing the RED test — the bundle already contains the exact conditions that
reproduced the bug.

**If the fix changes optimizer economics or behavior, the fixture from
`from_debug_log.py --issue <N>` also needs its `expected_results`/
`expected_behavior` set from the fixed code's output** (`docs/agents/testing.md`
→ Test Data) — this wires it into `test_scenarios.py::test_all_scenarios`,
the codebase's existing auto-discovered, always-run regression harness for
every `*.json` fixture in `core/bess/tests/unit/data/`. Do this instead of
writing a standalone test file that re-derives `_scenario_inputs` and
hand-asserts cost numbers — that duplicates a mechanism the codebase already
has and runs on every test invocation. Verify the pin actually discriminates
(temporarily feed it the pre-fix/buggy input, confirm it fails) before
trusting it. Reserve a standalone test file for what that harness genuinely
can't express: a private method's internal formula, or plan-faithfulness
(`R == P`) — `test_all_scenarios` never runs the inverter simulator.

**Adding a fixture also means regenerating two artefacts (since #544).** Two
meta-tests will fail the moment a new `*.json` lands in
`core/bess/tests/unit/data/`, by design — they exist so a fixture cannot
silently escape the pins:

```bash
.venv/bin/python scripts/capture_selector_goldens.py       # test_every_fixture_has_a_golden
.venv/bin/python scripts/capture_vpp_baseline.py --add-new # test_every_fixture_has_a_vpp_baseline
```

`--add-new` records only the new fixture's plan. **Never run a full VPP
re-baseline to make that test go green** — the script warns about this
because a full re-baseline regenerates both halves of every entry, collapsing
the recorded v10.0.2 drift to zero and destroying the signal
`test_drift_from_the_released_version_is_recorded` exists to hold.

Note what the goldens now pin per period, because it changes what counts as a
behaviour change: `actions`, `strategic_intent`, `intra_period_discharge_allowed`
and the SoE trajectory, all bit-exact, plus cost at 1e-9. So a fix that
reclassifies an intent or flips the discharge gate — without moving a single
kWh — is a golden diff and must be re-pinned deliberately, with the measured
delta stated in the PR. That is the intended behaviour, not a broken test.

### 6. Quality gate + code review (background)

Every PR must pass both the fast and slow suites, plus code review. This is
the long-wait step (slow suite ~4 min, measured 2026-08-11; the "~30 min"
this used to claim predates the vectorized backward pass) — per `CLAUDE.md`'s Cost
Discipline, do NOT hold the session open watching it run. Always a
background `Agent` — this is not a choice to put to the user; asking
"subagent or inline?" is itself the thing to stop doing (no `isolation` —
it must operate in the Step 4 worktree, not spawn a new one;
`run_in_background: true`, the default) with a self-contained prompt
covering:

1. `./scripts/quality-check.sh` (fast suite) — if it fails, fix and re-run,
   do not proceed with failures.
2. `.venv/bin/pytest -m slow` (slow suite) — same failure handling.
3. If the diff touches the DP, intent classification, or control/rate
   mapping (the Step 5 table): confirm the diff's new/changed tests include
   a `run_scenario_realized` / `verify_plan_faithfulness` call, not only a
   unit test on the changed function with hand-built arguments. If missing,
   this is a required-before-continuing gap, not a nice-to-have — report it
   as a blocking finding alongside the suite results, same severity as a
   failing test.
4. Invoke the `code-review` skill on the diff.
5. Report back: pass/fail on both suites, whether check 3 passed, and any
   CONFIRMED code-review
   findings verbatim (everything else goes to `TODO.md`).

Do not poll — you'll be notified on completion. This is a hard session
boundary: don't keep re-touching the diagnosis/TDD context while it runs.

### 7. Confirm gate 2 (conditional)

Fix any CONFIRMED findings and any failing suite in the same worktree,
re-running the check if the fix was non-trivial, before this step is
considered clean — regardless of what happens next.

- **Diff is backend-only (no `frontend/**`, no `*.tsx`/`*.jsx`/`*.css`) and
  the report is fully clean:** don't stop. State what passed in one line
  and continue straight through Step 8 into Step 9 — this is the
  fully-automatic path for non-UI work.
- **Diff touches the frontend, OR the report isn't fully clean and you
  can't get it clean yourself:** stop and present the report to the user
  (suite results, any findings, what you fixed). Wait for explicit
  go-ahead before Step 8 — same reasoning as Step 3, cheap insurance
  against shipping a finding-blocked, slow-suite-broken, or unreviewed UI
  change.

### 8. Local run & observe (never skip this)

Invoke the `verify` skill: actually exercise the fix and capture real
output — the reproducing mock-HA scenario via
`docker compose -f docker-compose.ci.yml`, a dev-server flow for frontend
changes, or the relevant CLI/pytest path with output inspected, not just its
exit code. A green test suite is necessary, not sufficient — this step is
what makes this skill worth running instead of the bot pipeline, and it is
not satisfied by re-stating that `quality-check.sh` passed.

### 9. Commit + draft PR

Add a `CHANGELOG.md` entry under `## [Unreleased]` (create that heading at
the top if it's not already there), in the matching `### Added` / `### Changed`
/ `### Fixed` subsection — one line, per `docs/agents/workflow.md`'s CHANGELOG
Format (bold lead-in, issue/PR link, ~25-word cap; no root cause or
file/function names — that's the PR description's job, not the changelog's).
Match existing entries' *format* only, never their *length* — several past
entries are multi-sentence root-cause essays; do not use those as a length
precedent. This is a normal part of the PR, not a release
step — per `docs/superpowers/specs/2026-07-09-release-workflow-design.md`,
`Unreleased` entries accumulate as each PR merges; the release skill only
ever renames or copies that section, it never authors it. Skipping this here
means the release skill has to backfill it later from a colder context.

**Documentation check (mandatory, not optional):** if the fix changed a
mechanism, formula, threshold, or code path that `docs/agents/bess-knowledge.md`
or `docs/SOFTWARE_DESIGN.md` describes, update the affected section in this
same PR. These two files are read as ground truth by the AI chat, the
GitHub analysis agent, and future implementers — a removed/changed mechanism
left undocumented silently rots into a wrong answer later (found in practice:
a "Bellman-optimality guardrail removal" refactor left both docs describing a
profit-threshold gate and a reward floor that no longer existed, and a FIFO
cost-basis claim that was never true). Concretely: grep both files for any
function/field/formula your diff touches before opening the PR, not after.
If neither file mentions anything your change touches, say so explicitly in
the PR description rather than silently skipping — a reviewer shouldn't have
to guess whether it was checked.

Commit per `docs/agents/workflow.md` format (subject + blank line + body
explaining WHY).

**Then bring the branch up to date before pushing — not after.**

```bash
git fetch origin && git merge origin/main
```

Resolve any conflicts here, in the worktree, where you have the context; if
the merge brought changes in, re-run `./scripts/quality-check.sh` before
pushing. Step 4 cut this branch from a current `origin/main`, but Steps 5–8
take hours (slow suite, `verify`) and other PRs merge during them. Opening a
PR that is already `CONFLICTING` is worse than it sounds: GitHub creates **no
workflow run at all** for it, so the PR shows no checks rather than a
conflict, and the first reader concludes CI dropped the event.

**Frontend diffs only:** before pushing, show the user the diff and the
Step 8 verification output (screenshot/dev-server observation) and wait for
explicit go-ahead. This is the one point in the fully-automatic flow where a
human looks before anything is pushed — backend-only diffs skip straight to
push, no pause here.

Open a draft PR against `main` via
`superpowers:finishing-a-development-branch` (Option 2: push + PR) —
go straight to executing Option 2, do not present its 3-option menu, body:

```
## Summary
- <bullet>

## Root cause
<quote from the Step 2 diagnosis>

## Fix
<what changed and why>

## Test plan
- [ ] `./scripts/quality-check.sh` passes locally (already done)
- [ ] <what you actually observed in Step 8 — be concrete>

## Evidence the test discriminates
<REQUIRED. Not "the suite passes". The mutation you ran and what broke:>
- Reverted: <the exact line/behaviour you undid>
- Result: `<test name>` FAILED, <N> test(s) total
- Restored: tree clean

## Outcome-level coverage
<REQUIRED. Which outcome pin now covers this behaviour:>
- <expected_results on fixture X | intents/gate in the goldens | R == P via
  run_scenario_realized | none, because …>

Closes #<n>
```

**These two sections are the point of the PR, not paperwork.** A reviewer
cannot tell a real guard from a vacuous one by reading it — three times in
this codebase a test has passed while proving nothing (#399 asserted an
internal flag instead of a write count; #302 asserted nothing at all; a
gate-outcome test written during the 2026-08-11 audit went green on its first
run while catching neither of the two mutations it claimed to catch). Every
one of those looked fine in review. The mutation result is the only cheap
thing that separates them, so it is stated where the reviewer reads, not left
in a terminal scrollback.

If you cannot produce a mutation that reddens your test, you have not
demonstrated the bug — say so in the PR and stop, rather than filling the
section in with the suite result.

### 10. Watch this PR to green (and only this PR)

The draft PR is open, but CI has not run yet. Local `quality-check.sh` and
the slow suite are not the same as the CI matrix, and a PR left red or
`CONFLICTING` is a PR the user cannot review.

```bash
gh pr checks <n> --watch --fail-fast     # blocks until the run settles
gh pr view <n> --json mergeable,mergeStateStatus
```

**`no checks reported on the '<branch>' branch` is not a result.** It has
two entirely different causes and you must tell them apart before doing
anything else:

```bash
gh pr view <n> --json mergeable,mergeStateStatus   # CONFLICTING -> merge origin/main
gh run list --branch <branch> --limit 3            # in_progress -> --watch just raced it
gh run watch <run-id> --exit-status                # then wait on the run directly
```

If `mergeable` is `CONFLICTING`, there is genuinely no run and never will
be — GitHub does not build a conflicted PR. If a run is `in_progress`,
`--watch` simply returned before the run was registered (observed on this
skill's own PR, ~8s after the push) and you wait on the run id instead.
Reading "no checks" as green is how a red PR gets handed over as finished.

Then, on this PR only:

- **Checks fail:** read `gh run view --log-failed`, fix in the worktree,
  re-run `./scripts/quality-check.sh`, push. This is your diff, so a real
  test failure is yours to fix — not merely to report.
- **Went `CONFLICTING`** (another PR merged in the minutes since Step 9):
  `git merge origin/main`, resolve, `quality-check.sh`, push.
- **Green and mergeable:** continue to Step 11's review loop — a green PR is
  the precondition for asking the bot to review it, not the finish line. It
  stays a draft *here*, because nothing has reviewed it yet; Step 11 is what
  marks it ready, and never merge — Step 12 still holds.

**Scope: this issue's PR, nothing else.** If the sweep in Step 4 or your own
`gh pr list` shows other PRs red or conflicted, that is not this session's
job — hand it to the `sweep-prs` skill, which owns fleet-wide maintenance
and has the ownership skip gate needed to touch a worktree another agent may
be sitting in. Widening a single-issue session into fleet cleanup is how two
sessions end up pushing to the same branch.

`gh pr checks --watch` blocks rather than polls, so this costs one wait, not
a re-read of the whole session context every 60s. If CI is badly backed up,
say so and leave the PR — don't hold the session open indefinitely.

### 11. Independent review loop (never skip this)

Step 6's `code-review` is your own review of your own diff, and it is not
enough on its own — in practice this PR needs two to four rounds of the
independent Stage 4 bot before only nits remain. That loop is mechanical, so
run it here rather than leaving it to a second session.

**Only enter this loop once Step 10 says the PR is green and mergeable.**
Asking for a review of a red or `CONFLICTING` PR burns a paid review round on
a diff that is about to change.

Each round:

```bash
scripts/request-pr-review.sh <n>     # run_in_background: true
```

The script posts `@claude-bot review` as `bess-agent` and blocks until a
verdict lands, printing `VERDICT <APPROVED|CHANGES_REQUESTED|COMMENTED>
<submittedAt> <author>` (exit 2 on a 15-minute timeout, after dumping recent
`PR Review` runs).

**`COMMENTED` is ambiguous, and the script resolves it for you — don't
second-guess it.** `pr-review.yml` allows three final verdicts (`APPROVE`,
`REQUEST_CHANGES`, `COMMENT`), so a real `COMMENT` verdict is possible and
carries findings. But the bot historically also submitted its inline notes as
a separate `COMMENTED` review ("Inline notes below; summary review to follow")
16–50 seconds ahead of the summary, and the two are identical by state.
Acting on that placeholder is how PR #615 sat `APPROVED` but still a draft
overnight. The script holds a `COMMENTED`-only state for 180s to let a summary
supersede it, so a `COMMENTED` that reaches you **is** the verdict: treat it
like `CHANGES_REQUESTED` — collect the findings, do not flip the PR ready.
Like Step 10's
`--watch`, it blocks rather than polls — so **do not poll it and do not
re-touch the diagnosis/TDD context while it runs.** You are notified once,
when it exits. This is a hard session boundary, same as Step 6.

On the verdict:

- **`APPROVED`** — the review is done, but the PR's *state* is not yet
  established. **Re-check mergeability before doing anything else:**

  ```bash
  git fetch origin
  gh pr view <n> --json mergeable,mergeStateStatus
  ```

  Step 10's green/`CLEAN` verdict is stale by now — a review round takes
  minutes (8 in the run that motivated this), and other PRs merge during it.
  A `CONFLICTING` PR cannot be merged and gets no new workflow run, so
  reporting Step 10's reading as if it still held hands the maintainer a
  conflicted PR described as clean. That is what happened on #609, and the
  reason this check exists here and not only in Step 10.

  If it is `CONFLICTING` / `DIRTY`: `git merge origin/main`, resolve, re-run
  `./scripts/quality-check.sh` (and the slow suite if the merge pulled in
  optimizer changes), push, and re-watch CI per Step 10. Then apply the
  push-after-approval rule below to the merge commit — a clean merge that
  changed nothing under review does not need another round, one that touched
  reviewed code does.

  **Then mark the PR ready for review and report the link:**

  ```bash
  gh pr ready <n>
  ```

  This is the one status change the skill makes on its own, and the approval
  is what earns it. A draft says "not finished"; once the bot has approved a
  green PR, that is no longer true, and leaving it draft means the maintainer
  has to notice it, judge whether it is actually done, and flip it by hand
  before merging — three steps to re-derive something the loop already
  established. Ready says "reviewed, green, and waiting on your judgement",
  which is exactly the state it is in.

  Two things this does *not* license, both still hard constraints (Step 12):
  never merge it, and never flip it early — an unreviewed or red PR stays a
  draft, no matter how confident you are in the diff.

  **If you push anything after the approval, the approval covers a diff that
  no longer exists, and what you do next depends on what you pushed.** Ask
  whether the new commits touched code the reviewer actually reviewed:

  - **They didn't** (parking a nit in `TODO.md`, a `CHANGELOG.md` line, a
    clean `git merge origin/main` that changed nothing under review):
    re-check `gh pr checks` and `mergeable`/`mergeStateStatus`, then flip.
    Name those commits in your report and say why they fall outside the
    reviewed diff, so the maintainer can check that call rather than take
    it on trust.
  - **They did:** do NOT flip. Go back and run another review round — the
    approval you are holding was for different code, and `gh pr ready` on a
    stale-approved diff is the one way this step can actively mislead. A
    round costs minutes; a wrongly-ready PR spends the maintainer's trust in
    the ready flag, which is the only thing that makes it worth setting.

  The round cap counts this round like any other. If it lands you on the cap,
  say so and hand over a draft PR with the outstanding state — an honest
  draft beats a ready flag that means less than it claims.
- **`CHANGES_REQUESTED` / `COMMENTED`** — both carry findings and neither earns
  the ready flag. Collect them:

  ```bash
  gh api repos/johanzander/bess-manager/pulls/<n>/comments \
    --jq '.[] | select(.created_at > "<submittedAt from the round before>") | "\(.path):\(.line) \(.body)"'
  ```

  Then invoke `superpowers:receiving-code-review`. This is the reason the loop
  lives in the main session and not in a subagent: you still hold the Step 2
  diagnosis and the Step 3 scope assessment, so you can tell a real finding
  from one that contradicts a decision already made deliberately. Verify each
  finding against the code before acting on it. Where the reviewer is wrong,
  reply on the PR saying why — do not silently implement it, and do not
  silently ignore it either.
- **A review from the maintainer rather than the bot** (the `<author>` field):
  treat it as authoritative and stop the loop — a human has taken over.

Fix the blockers, park genuine nits in `TODO.md`, run
`./scripts/quality-check.sh`, commit, and push. Step 9's frontend rule carries
over unchanged: if the diff touches `frontend/**` or `*.tsx`/`*.jsx`/`*.css`,
show the user the fixes and wait for go-ahead before pushing. Then start the
next round.

**Hard cap: 3 rounds.** On the third `CHANGES_REQUESTED`, or on any script
timeout, stop and hand the outstanding findings to the user verbatim. Three
rounds of disagreement means the reviewer and you disagree about the design,
not about a bug, and another round will not settle it.

### 12. Hard constraints

- **Never merge, ever** — not after a green CI run, not after an `APPROVED`
  review, not when the diff is trivial. The merge is the maintainer's final
  judgement and it is the one thing this skill never takes. Marking the PR
  ready once Step 11 approves it (and only then) is not merging, and is
  required rather than forbidden.
- Open the PR as a draft and leave it that way until Step 11's approval.
- Never push directly to `main`.
- Do NOT modify the version in `bess_manager/config.yaml` — bumping it is a
  release-time step, not a per-PR one. DO add a `CHANGELOG.md` entry under
  `## [Unreleased]` per Step 9 — this is the one CHANGELOG.md edit expected
  in every PR.
- If `quality-check.sh` keeps failing after 3 fix attempts, or Step 8 can't
  demonstrate the fix actually works, stop, push the branch as-is, and
  report what failed — don't force a PR through.
- If this work went through `superpowers:writing-plans` (a `docs/superpowers/plans/`
  file exists for it), delete that plan file before the Step 9 commit. Keep
  the spec (if any); the plan is execution scaffolding that only drifts once
  the code is the source of truth. Never commit a plan doc into the PR.

## After Merge

A **separate, later invocation** — often a different session, sometimes days
later once CI is green and the user has reviewed. Not part of the numbered
flow above, which stops at a green, bot-approved, ready-for-review PR that
the maintainer has not merged yet, per the Step 12 constraints.

**Treat this as best-effort, not the cleanup mechanism.** Because it depends
on someone returning after the merge, it reliably does not happen; Step 4's
prune is the one that actually runs. If you are here, do it — but the safety
net is upstream, not this section.

1. Confirm the merge:

   ```bash
   gh pr view <n> --json state,mergedAt,mergeCommit
   ```

   `state == "MERGED"` is authoritative — that's the standard signal, no need
   to separately diff branch content against `main`. Squash merges break
   `git branch -d`'s normal ancestry check (the branch's commits never become
   reachable from `main`), so force-delete below is expected, not a sign
   something's wrong.

2. Remove the worktree — via `ExitWorktree action=remove discard_changes=true`
   if the session is still in it, or `git worktree remove <path>` from the
   main repo root for a `.worktrees/`-created one.

3. Force-delete the local branch and prune stale remote refs:

   ```bash
   git branch -D <branch-name>
   git fetch origin --prune
   ```

   GitHub auto-deletes the remote branch on merge by default; `--prune` just
   clears the now-stale local tracking ref.

## Rationalizations — Reality

| Excuse | Reality |
|---|---|
| "the test asserts the exact command we write to hardware, that's precise" | Precise about the mapping, silent about the outcome. It stays green when the mapping is right and the physics is wrong. Assert realized cost / SoE / flows wherever an execution model exists. |
| "it's green, so the fix works" | Green means the suite is satisfied. Revert the fix and watch the test fail — if it doesn't, it was never evidence. |
| "this issue has no PR yet, so I'm starting fresh" | Step 0 checks branches and worktrees too, not just PRs. 8 abandoned branches in one audit had real commits and no PR — one with 32. Starting fresh from `origin/main` deletes them. |
| "there's no issue for this PR, so it isn't mine to resume" | This skill covers `TODO.md` items and refactors, which never had an issue. A bare number resolves to either — that dead end left #620, #622 and #623 with no owner in the loop. |
| "the old branch is a mess, cleaner to redo it" | Its commits are the only copy of a diagnosis you no longer have. If you genuinely cannot reconstruct the approach, that is a STOP-and-report, not a licence to reset. |
| "that worktree's session shows dead, so it's mine to take" | Check unsandboxed. A sandboxed `claude agents --json` returned 1 session where the real answer was 17, because `~/.claude/jobs` is sandbox-denied — every other session read as dead. |
| "the review said CHANGES_REQUESTED but nobody assigned it to me" | Nothing else will pick it up. Once the opening session exits, an orphaned PR has no owner at all — `sweep-prs` refuses the job by design. Resuming is how it gets one. |
| "I can see the assertion is right, no need to run it red" | Assertions that look right have repeatedly bounded only one side, or compared a quantity a second varying term swamped. Seeing it fail is the cheap part. |
| "quality-check.sh passed, that's enough" | Green tests prove the suite is satisfied, not that the fix behaves correctly against the real scenario. Step 8 requires observed output, every time. |
| "the diagnosis is obviously right, skip the confirm gate" | Wrong diagnoses are exactly when confidence is highest. One message, cheap insurance. |
| "I'll clean up this other thing while I'm in here" | Out of scope. Minimal fix only. |
| "code review can wait until after I've verified it works" | Reordered on purpose — catch cheap issues before spending time on manual verification, not after. |
| "there's already a bot diagnosis, let me re-derive it anyway to be safe" | Re-verify the cited evidence; don't redo the whole investigation. |
| "the branch was current when I cut it, no need to merge before pushing" | Steps 5–8 take hours and other PRs merge during them. And a CONFLICTING PR gets no workflow run at all, so it reads as "CI never fired" — the conflict stays invisible until someone digs. |
| "while I'm watching my PR I may as well fix the other red ones" | That's `sweep-prs`, which has the ownership skip gate this skill doesn't. Another agent may be sitting in that worktree; merging under it puts two sessions on one branch. |
| "the PR is open, my job is done" | Open isn't green. CI runs a matrix `quality-check.sh` doesn't, and the user can't review a red or conflicted PR. Step 10 finishes the job. |
| "Step 10 said MERGEABLE/CLEAN, so I can report that" | Not after Step 11. The review round takes minutes and other PRs merge in minutes — #609 went `CONFLICTING` during its own approval round and was handed over described as clean. Re-check after the verdict, not before it. |
| "it's approved, but flipping it out of draft is the maintainer's call" | Merging is their call; marking it ready is just reporting the state the loop already established. Leaving it draft makes them re-derive "is this finished?" by hand. |
| "Step 6's code review already covered this, skip Step 11" | Step 6 is you reviewing your own diff with the reasoning that produced it. The Stage 4 bot reads the diff cold against the checklist, and in practice takes two to four rounds to run out of real findings. |
| "the reviewer asked for it, so change it" | The reviewer has the diff, not the diagnosis. A finding that contradicts a deliberate Step 3 scope decision gets a reply explaining why, not a commit. |
| "the plan doc is useful context, keep it in the PR" | Once code and tests exist, the plan only drifts — it's not the source of truth. Delete it before Step 9; keep the spec if one exists. |
| "the user is in a hurry, just open the PR" | Time pressure from the user is not permission to skip Step 8 — it's the reason to say so explicitly and give a real ETA instead. |
| "I'll clean up the worktree after it merges" | You won't — that's the postcondition that already failed 24 times. Prune at Step 4, before creating the next one. |
| "`git branch --merged` will tell me what's safe to delete" | Not in this repo. Squash-merge means a merged branch is never an ancestor of main, so that check reports *everything* as unmerged and the cleanup silently never fires. Use `gh pr list --state merged`. |
| "I'll just hop into the other worktree for a second" | Not while a background agent spawned from this session is running — its isolation follows you and its tooling starts resolving against the wrong checkout. |
| "I'll just watch the background agent run" | Defeats the point — the whole reason it's backgrounded is so the session isn't held open through the slow suite. Let the notification bring you back. |
| "the fix is small, docs don't need touching" | Small fixes are exactly what silently invalidates a one-line doc claim (a removed threshold, a renamed formula). Grep the two design docs before opening the PR, every time. |
| "a unit test on the changed function is enough" | Not for DP/intent/control-mapping changes — a synthetic-input unit test can pass while the new branch is unreachable by any real optimizer-derived scenario. `docs/agents/simulator.md` requires `R == P` for exactly this class of change. |
| "the existing suite still passes, so nothing broke" | Passing unchanged means the new code path may simply be untested, not unbroken — check whether any existing fixture actually reaches the new branch before treating a green suite as coverage. |

## Red Flags — Stop and Go Back

- About to run Step 4 (fresh worktree from `origin/main`) when a branch for
  this issue already carries commits. That deletes them.
- About to `git reset` or force-push a branch a dead session left behind.
- About to re-diagnose from scratch on top of someone else's half-finished
  branch because the Stage 2 comment and PR body didn't reconstruct the
  approach. That is a STOP-and-report.
- About to open a second PR for an issue that already has one.
- About to relaunch an issue that has already died twice without saying so.
- About to commit or open the PR without having actually run/observed the
  fix — only ran automated tests.
- About to skip the Step 3 confirm gate, or the Step 7 gate for a frontend
  diff or an unresolved-findings diff, because of time pressure. (Skipping
  Step 7 for a clean, backend-only diff is the intended fully-automatic
  path — that's not this red flag.)
- About to open the PR before `/code-review` CONFIRMED findings are
  resolved.
- About to re-run the full `bess-analyst` diagnosis when a verified bot
  comment already exists.
- About to run the slow suite inline in the main session instead of
  dispatching the Step 6 background agent.
- About to open the PR without checking whether the fix invalidates a claim
  in `docs/agents/bess-knowledge.md` or `docs/SOFTWARE_DESIGN.md`.
- About to write only a synthetic-input unit test for a DP/intent/control-
  mapping change instead of a plan-faithfulness (`R == P`) scenario test.
- About to push the branch without having merged `origin/main` since Step 4.
- About to stop at "draft PR opened" without watching CI settle (Step 10).
- About to stop at "CI is green" without running the Step 11 review loop.
  Your own Step 6 review is not the independent one.
- About to hand over an `APPROVED`, green PR still marked draft — Step 11
  flips it with `gh pr ready`; the maintainer should only have to merge.
- About to report `mergeable` from Step 10's check after Step 11's review
  round. That reading is minutes old and other PRs merge in minutes — re-run
  `gh pr view --json mergeable,mergeStateStatus` before flipping or reporting.
- About to run `gh pr ready` before an approval, or `gh pr merge` at all.
- About to implement a review finding because the bot said so, without
  checking it against the Step 2 diagnosis and the Step 3 scope assessment.
- About to read `no checks reported` as green. It means either a conflict
  or a run that hasn't registered yet — distinguish before reporting.
- About to touch another PR or another worktree from inside this session —
  that is `sweep-prs`, not this skill.
- About to write a repro test from hand-built data when a user debug log/
  bundle is available and `from_debug_log.py` could build it from real data.

## Quick Reference

| Step | Skill/Tool | Skippable? |
|---|---|---|
| 0. Resume check | `gh pr list` + `git worktree list` + unscoped/unsandboxed `claude agents --json` | No |
| 1. Fetch & scope | `gh issue view` | No |
| 2. Diagnose | `bess-analyst` (if no bot comment) | Conditional |
| 3. Confirm gate | — | No |
| 4. Worktree | `using-git-worktrees` | No |
| 5. TDD | `test-driven-development` | No |
| 6. Quality gate + code review | `quality-check.sh` + slow suite + `code-review` (background agent) | No |
| 7. Confirm gate 2 | — | Conditional (auto-continue if backend-only + clean; otherwise No) |
| 8. Local run & observe | `verify` | **Never** |
| 9. Commit + PR | `finishing-a-development-branch` (incl. pre-push `git merge origin/main`) | No |
| 10. Watch this PR to green | `gh pr checks --watch` — this PR only | No |
| 11. Independent review loop | `scripts/request-pr-review.sh` (background) + `receiving-code-review`, max 3 rounds; `gh pr ready` on `APPROVED` | No |
