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
  re-enters at the right step. This is not a separate skill because the
  diagnosis and scope assessment a resumed session needs live here — the
  review loop itself lives in `advance-pr`, its only copy, and Step 11
  delegates to it rather than duplicating it.

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
| 0. Resume check | Applies, and matters more here: Stage 3 is re-triggered by hand, so a second `@claude-bot fix` on an issue that already has a `has-fix-pr` PR is a resume, not a restart. Detect the existing PR and continue it — never open a second PR for one issue. The CI checkout has no worktrees, so branch existence on `origin` is the only signal available. Reading the PR's **conversation comments** matters more here too, not less: the re-trigger is itself a comment, so the maintainer has very often said *why* in the same thread. |
| 2. Diagnose | Stage 2 comment absent → STOP. Post "No deep analysis found. Run `@claude-bot analyze` first" and exit — never self-diagnose in CI; the analyze/fix split *is* the human gate. |
| 3. Confirm gate | The owner's `@claude-bot fix` comment is the go-ahead. Still perform the workaround check and scope assessment — put them in a `## Scope assessment` section of the PR body instead of chat. Escalation path (can't confidently pass the workaround check) still applies: dispatch a fresh general-purpose `Agent` to critique the design before implementing. |
| 4. Worktree | Skip — the CI checkout is already isolated. Create the branch directly (naming per Step 1). |
| 5. TDD | The substance applies verbatim (RED test first, required test shape); there is just no `superpowers:test-driven-development` skill to invoke — follow this section's own rules. |
| 6. Quality gate + code review | Run inline, no background agent (CI is one throwaway session — the cost-discipline reason to background doesn't exist). The `code-review` plugin is unavailable; the Stage-4 `@claude-bot` PR review covers it. Checks 1–3 (fast suite, slow suite, required-test-shape) still apply. |
| 7. Confirm gate 2 | Replaced by the draft PR itself — the owner reviews the draft before anything merges. |
| 8. Local run & observe | Structurally unavailable in CI — this is the documented reason the local flow exists. Skip, and say so in the PR body's test plan so the reviewer knows verification is still owed. |
| 9. Commit + draft PR | Applies verbatim, including the `CHANGELOG.md` `## [Unreleased]` entry and the documentation check. Add the `## Scope assessment` section (Step 3 above). The workflow file owns CI-only mechanics: issue comment with the PR link, `has-fix-pr` label. |
| 10. Watch this PR to green | Applies verbatim — `gh pr checks --watch` on the PR just opened, fix failures, never widen to other PRs. |
| 11. Independent review loop | Skip — CI opens the PR as a draft and the owner triggers Stage 4 by hand after reading it. A CI run that requested its own review would be the fix bot grading itself on a PR nobody has looked at yet. `advance-pr` is therefore not invoked in CI, and the PR stays a draft: `gh pr ready` belongs to that skill, and there is no approval in CI mode to earn it. |
| 12. Hard constraints | Apply verbatim. |

## Headless local mode (dispatched container)

`scripts/run-agent.sh <n>` runs this skill headless inside a Podman container,
against a private clone bind-mounted at its own host path (Phase 1 of
`docs/superpowers/specs/2026-08-20-agent-fleet-sandbox-router-design.md`).
Headless is **not** CI, and the differences run the opposite way to CI mode's:
the container is long-lived, it *can* run the app, and it answers its own
gates instead of ending the run at them. The numbered Process applies verbatim
except per this table.

**You are in this mode when `BESS_HEADLESS_MODE=1` is set.** `run-agent.sh`
sets it, along with `BESS_FLEET_CONTAINER` (this dispatch's id) and
`BESS_FLEET_DB`.

Three things that hold across every row:

- **Never exit at a gate.** The whole point of a container that lives for the
  issue's whole lifecycle is that Step 10's recovery of a PR gone
  `CONFLICTING` under a merge, and Step 11's repeated `advance-pr` rounds,
  keep running with nobody watching. A run that exited at Step 3 and waited to
  be re-dispatched would turn that working loop back into a queue of manual
  restarts. Post, block on `scripts/wait-for-reply.sh`, resume in place.
- **Report status as it changes**, so the dispatch is legible without reading
  logs: `scripts/fleet-manifest.sh update-status "$BESS_FLEET_CONTAINER" <status>`
  — `needs_input` on entering a gate and `working` again on leaving one,
  `in_review` for Step 11, `escalated` for a Step 12 bailout, `done` at a
  terminal state.
- **The plugin caveat is CI mode's, unchanged**: user-level plugins
  (`superpowers:*`, `code-review`) are not in the image. Only repo-level
  `.claude/skills/` and `.claude/agents/` exist, and those arrive inside the
  clone.

| Step | Headless local mode |
|---|---|
| 0. Resume check | Applies, with a different registry: this container has a private **clone**, not a worktree, so `git worktree list` on the host cannot see it and the host's worktrees are none of its business. `scripts/fleet-manifest.sh list` is the enumeration. The clone is reused across dispatches and is host-persistent, so prior commits in it are exactly the resumable work Step 0 exists to find — never discard them. |
| 1. Fetch & scope | Verbatim. |
| 2. Diagnose | Verbatim — **unlike CI mode**, self-diagnosis is correct here. The maintainer typing `run-agent.sh <n>` is the same explicit go-ahead as starting an interactive session; there is no analyze/fix split to protect, and no Stage 2 comment to require. |
| 3. Confirm gate | Post the design + workaround check + scope assessment with `scripts/gh-agent.sh --as dev` (to the issue; to the PR once one exists), set status `needs_input`, then `scripts/wait-for-reply.sh <n> <now-iso8601>` and continue **in this process** on its reply — accepted only from the repo owner (`--from` defaults to it), so a stranger's drive-by comment cannot steer the dispatch. Not CI's behaviour of treating a trigger comment as pre-granted consent, and not a stop. The escalation path (dispatch a general-purpose `Agent` to critique) applies verbatim. |
| 4. Worktree + branch | The clone *is* the isolation — `run-agent.sh` created it and ran `scripts/worktree-setup.sh --target-dir`, so create the branch directly and skip worktree creation. **Skip the merged-worktree prune too**: those worktrees belong to the host checkout, are not visible from in here, and are not this dispatch's to clean. Then report the branch: `scripts/fleet-manifest.sh set-branch "$BESS_FLEET_CONTAINER" <branch>` — the manifest could not know it at dispatch. |
| 5. TDD | Substance verbatim (RED test first, required test shape); as in CI there is no `superpowers:test-driven-development` skill to invoke, so follow this section's own rules. |
| 6. Quality gate + code review | Run `./scripts/quality-check.sh` inline, no background agent — one throwaway container, so the cost-discipline reason to background does not apply. The `code-review` plugin is unavailable; Step 11's independent review covers it. Checks 1–3 still apply. |
| 7. Confirm gate 2 | Same mechanism as Step 3: `gh-agent.sh --as dev`, status `needs_input`, `wait-for-reply.sh`, resume in place. Not CI's "the draft PR is the gate" — there is a live process here that can act on the answer. |
| 8. Local run & observe | **Applies only on a `--with-compose` dispatch — this is the row that most distinguishes headless from CI, and it is why the socket is opt-in.** CI skips it because a runner structurally cannot; a container *can*, but only when the dispatch was launched with `run-agent.sh --with-compose <n>`. The socket is authority over the podman host, so it is NOT mounted for a plain dispatch (see `scripts/lib/agent-dispatch.sh`); a plain dispatch cannot bring the stack up, so follow CI mode's rule for that step — say in the PR body that Step 8 was not run and why. On a `--with-compose` dispatch, `podman-compose -p <unique-name> -f docker-compose.ci.yml` brings up **sibling** containers, not nested ones (the image has `podman-compose`, not the `docker` CLI). This works because the clone is mounted at its own host path, so the compose file's relative volume paths mean the same directory inside and out. One difference from an interactive run: the siblings publish their ports on the podman host, not in this container's netns, so observe the stack via the allowlisted `host.containers.internal` host (e.g. `curl -s http://host.containers.internal:18180/api/system-health`) rather than `localhost`. Do not write "verification is still owed" in the PR body — do the verification. |
| 9. Commit + draft PR | Verbatim, including the `CHANGELOG.md` `## [Unreleased]` entry and the documentation check. The PR is authored by the role-scoped `dev` token the container was given, never the maintainer's credential. |
| 10. Watch this PR to green | Verbatim. `gh pr checks --watch` blocking for an hour is fine here; that is what a long-lived container is for. Never widen to other PRs. |
| 11. Independent review loop | Verbatim — **unlike CI**, which skips it. Set status `in_review`, invoke `advance-pr`, and let it mark the PR ready on `APPROVED`. This is an interactive-equivalent run the maintainer dispatched deliberately, not a bot grading a PR nobody asked for; the 3-round `CHANGES_REQUESTED` cap is itself a gate, so treat hitting it as Step 3's mechanism (status `escalated`, ask, wait). |
| 12. Hard constraints | Apply verbatim. On the 3-failed-quality-check bailout, set status `escalated` and post why with `gh-agent.sh --as dev` before waiting — a container that dies silently is indistinguishable from one still working. |

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
gh pr view <n> --json number,headRefName,isDraft,mergeable,reviews,comments 2>/dev/null \
  || gh issue view <n> --json number,title,labels,body,comments
```

**`comments` is in that list deliberately — do not drop it.** It is a separate
feed from `reviews`, it is where the maintainer sets direction, and omitting it
has already cost one full rework (see Rehydrate, below).

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

**If `<n>` is neither — a bare refactor or `TODO.md` item with no issue — open
one first**, so the work has a card and can carry `Priority`, `Awaiting` and a
phase like everything else:

```bash
gh issue create --title "<one line>" --body "<why, in two sentences>" --label refactor
```

One card per unit of work is the rule; a PR with no issue is a second card for
the same work, which is what made `Priority` ambiguous between the two.

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
carrying `CHANGES_REQUESTED` or `APPROVED` re-enters at Step 11, which invokes
`advance-pr` — never run `gh pr ready` directly here. The mergeability
re-check and the push-after-approval rule now live only in `advance-pr`, and
skipping straight to `gh pr ready` on a resumed `APPROVED` PR is exactly the
#609 failure: the approval can be stale or the PR newly conflicting by the
time a resumed session looks at it.

When resuming, post the handoff marker so the count is a fact rather than a
feeling — two handoffs on one issue is an escalation:

```bash
scripts/gh-agent.sh --as dev issue comment <n> \
  --body "Resuming implementation from step <k>.
<!-- resume-handoff -->"
```

**Rehydrate the diagnosis before touching code.** Step 2's analysis died with
the session, and Step 11 depends on holding it. It is recoverable only because
this skill already forces it to be written down:

- the Stage 2 `@claude-bot analyze` comment on the issue — the root cause
- the PR body's `## Test plan`, and its `## Scope assessment` **if the PR came
  from CI mode** — the agreed approach, and what the test was meant to
  discriminate. Interactive mode keeps its scope assessment conversational, so
  that heading is absent on most PRs this skill opens; the PR's existence is
  what proves Step 9 was reached, not any particular heading
- **the PR CONVERSATION comments, not only its reviews** — see below
- the diff itself, and any inline review comments

**Reviews and conversation comments are two different feeds, and `gh pr view
--json reviews` returns only the first.** Read both, every time:

```bash
gh pr view <n> --json reviews  --jq '.reviews[]  | "\(.author.login) \(.state) \(.submittedAt)\n\(.body)"'
gh pr view <n> --json comments --jq '.comments[] | "\(.author.login) \(.createdAt)\n\(.body)"'
```

**A maintainer conversation comment OUTRANKS every bot review on the PR**,
including ones submitted after it. The bot reviews the diff; the maintainer
decides the direction, and they change direction in comments — that is the
only place they can, since a review has to attach to a diff.

This is not hypothetical. On #620 the maintainer posted "**this PR should
shrink**" with a four-step plan: branch protection now rejects pushes to `main`
server-side, so the protected-ref *enumeration* should be **deleted** rather
than extended. A later session read the reviews, did not read the comments,
and spent a full rework **adding** protected-ref patterns — the exact opposite
of the standing instruction, on a PR whose own thread already said so. Two
further holes the maintainer had found by hand (`git push origin
refs/tags/v1.2.3`, `git push origin HEAD`) were in that comment too, and stayed
open because nobody read it.

So: **before touching code on a resumed PR, read the human comments first, and
newest-first.** If one sets a direction the diff contradicts, that is a
STOP-and-confirm, not something to reconcile silently — the maintainer may have
changed their mind since, and asking costs one message where guessing costs a
rework.

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
  # Directory gone = PHANTOM (`prunable`), not detached. `git -C` would fail
  # and the detached guard below would silently swallow it.
  [ -d "$wt" ] || { echo "PHANTOM (needs unsandboxed prune): $wt"; continue; }
  b=$(git -C "$wt" branch --show-current 2>/dev/null)
  [ -n "$b" ] || continue                                   # detached: leave alone
  echo "$merged" | grep -qx "$b" || continue                # not merged: leave alone
  dirty=$(git -C "$wt" status --porcelain -uno)
  if [ -n "$dirty" ]; then                                  # tracked edits: never auto-delete
    if [ -z "$(printf '%s\n' "$dirty" | grep -v '^ D ')" ]; then
      echo "CARCASS (failed prune, deletions only): $wt"    # see below -- not real edits
    else
      echo "KEEP (uncommitted changes): $wt"
    fi
    continue
  fi
  echo "PRUNE: $wt  ($b)"                                   # report; do NOT remove here
done
git fetch origin --prune
```

**Report the `PRUNE` list; do not act on it from here.** `git worktree remove`
is sandbox-denied — it deletes the working tree *first* and then fails on the
`.git/worktrees/<name>` unlink, destroying ~393 tracked files and leaving a
carcass that no later prune can clear (`git worktree prune` is denied too).
Emit one `!`-prefixed command covering every `PRUNE`, `CARCASS` and `PHANTOM`
for the maintainer to paste, exactly as `sweep-prs` Step 3 does. See
`docs/agents/local-agent-environment.md`, "git worktree remove is denied too".

Three guards that matter: never remove a worktree with **uncommitted tracked
changes** — report it and let a human decide (one such worktree held a
375-line module that existed nowhere else); never touch a **detached or
locked** worktree, which is usually another agent's live session; and never
mistake a **carcass** for either. A dirty set that is *entirely* ` D` lines is
this bug's own wreckage, not someone's work — 13 of them accumulated before
anyone read the diff.

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

Refs #<n>
```

**Every PR body carries `Refs #<issue>`** — and only the graduation PR carries
`Closes #<issue>`, per the no-auto-close rule. A beta or intermediate PR that
used a closing verb would close the reporter's issue before the fix has shipped
to them; one that referenced nothing at all would be invisible to the board,
which associates PRs with issues by that line.

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
  stays a draft *here*, because nothing has reviewed it yet; `advance-pr`,
  invoked from Step 11, is what marks it ready, and never merge — Step 12
  still holds.

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

The loop lives in **`advance-pr`**, which is its only copy. Invoke it, and keep
invoking it until it reports a terminal state:

    /advance-pr <pr-number>

Each invocation performs one transition and exits, and it never reworks a
review verdict — on a `CHANGES_REQUESTED` verdict it collects the findings and hands them back
to you rather than reworking in place, because you are the session that still
holds the Step 2 diagnosis and the Step 3 scope assessment, which is what
lets you tell a real review finding from one that contradicts a decision made
deliberately. Act on it **here**, in this session, then invoke `advance-pr`
again for the next round.

**Fetch the findings yourself — `advance-pr`'s `reviews`/`comments` read does
not carry them.** The bot posts its findings as INLINE review comments, which
show up in neither `gh pr view --json reviews` nor `--json comments`. Read
them directly, scoped to comments newer than the previous round's verdict so
a re-run doesn't re-litigate findings already addressed (on the first round,
omit the `select` — there is no prior verdict to filter against):

```bash
gh api repos/johanzander/bess-manager/pulls/<n>/comments \
  --jq '.[] | select(.created_at > "<submittedAt from the round before>") | "\(.path):\(.line) \(.body)"'
```

**Hard cap: 3 rounds.** On the third `CHANGES_REQUESTED`, stop reworking — a
fourth round will not settle a design disagreement. The escalation itself is
a derived GitHub fact, not something this skill or `advance-pr` writes:
`backlog-rhythm.sh` already reports it as `escalated` every tick, computed
from the review-round count alone. Hand over the findings verbatim; that
report — and whoever acts on it — is what sets `Awaiting: maintainer`.

### 12. Hard constraints

- **Never merge, ever** — not after a green CI run, not after an `APPROVED`
  review, not when the diff is trivial. The merge is the maintainer's final
  judgement and it is the one thing this skill never takes. `advance-pr`
  marking the PR ready once Step 11 invokes it and gets an approval (and only
  then) is not merging, and is required rather than forbidden.
- Open the PR as a draft and leave it that way until `advance-pr`, invoked
  from Step 11, marks it ready on approval.
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
   if the session is still in it. That is the harness doing it, so it is not
   sandboxed and it works.

   If the session has already left, **emit one `!`-prefixed command that
   removes the worktree and force-deletes the branch together**, in that
   order — the branch delete has to ride the same deferred command: git
   refuses `git branch -D` while the worktree registration persists, and the
   command below is what clears the registration:

   ```bash
   # Emit this; do not execute it. It must run unsandboxed.
   git worktree remove --force <path> && git branch -D <branch-name>
   ```

   Running `git worktree remove` from a sandboxed Bash half-deletes the
   worktree and then fails (see Step 4), so the agent must not run it either.

3. In-session only — when item 2 completed via `ExitWorktree`, the
   registration is gone and `git branch -D` is safe. Force-delete the local
   branch and prune stale remote refs:

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
| "I read the reviews, so I know what this PR needs" | Reviews and conversation comments are separate feeds and `--json reviews` returns only one. The maintainer sets *direction* in comments, because a review can only attach to a diff. On #620 that cost a full rework in the opposite direction. |
| "the bot approved it, so the direction must be fine" | The bot reviews the diff against a checklist; it has no idea what the maintainer asked for in the thread. An approval on a diff you were told to redo is worth nothing. |
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
- **About to change code on a resumed PR without having read its conversation
  comments** — not just its reviews. They are separate feeds, and the
  maintainer's direction lives in the one `--json reviews` does not return.
- About to implement a diff that contradicts a maintainer comment already on
  the thread. Stop and confirm; they may have moved on, but guessing costs a
  rework and asking costs one message.
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
- About to hand over an `APPROVED`, green PR still marked draft — invoke
  `advance-pr` from Step 11, which flips it with `gh pr ready`; the
  maintainer should only have to merge.
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
| 11. Independent review loop | `advance-pr`, invoked repeatedly to a terminal state, max 3 rounds | No |
