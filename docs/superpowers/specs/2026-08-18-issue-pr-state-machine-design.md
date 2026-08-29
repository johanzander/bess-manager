# Issue and PR state machine: explicit states, cheap transitions, flow policy

**Date:** 2026-08-18
**Status:** design, approved in brainstorming; not yet planned

## The problem, in evidence

The fleet on 2026-08-18: **8 open PRs, all 8 drafts, 6 CONFLICTING, none ever
approved.** No PR in the fleet had ever reached "out of draft". (#651 landed
mid-design, leaving 7.)

That is not a run of bad luck. Four structural causes, each measurable:

**1. The PR lifecycle is collapsed into one issue column.** The digest derives
an issue's column as `if $pr != null then "In Review"`, and it is the *first*
test — outranking blocked, awaiting, and every other signal. A never-reviewed
draft, a conflicted draft, an approved-and-waiting PR and a merged-but-unreleased
fix all report the identical state. The issue's column stops carrying
information the moment a PR exists.

**2. The only exit from draft costs a full session.** Every unfinished draft
resolves to one action — `resume_implementation`, i.e. a whole
`/implement-issue` run at $1–4. The rhythm pass is behaving exactly as
designed; its answer is simply too expensive to run five times in a tick, so
nobody runs it and the queue only grows. `mark_ready` is the one cheap terminal
action, and it can never fire because nothing is ever approved.

**3. The action list is sorted alphabetically.** `sort_by(.action, …)` puts
`dispatchable` first and `resume_implementation` last, because `d < m < r`.
Every pass therefore leads with "start new work" and buries "finish started
work". This is mechanical, not a judgement gone wrong.

**4. Five of the eight PRs edit the same three files.** #614, #620, #638, #645
and #651 all touch `CLAUDE.md`, `.claude/skills/backlog/SKILL.md` and
`scripts/backlog-rhythm.sh`. The skill's `Dispatch` section already says
same-file work should be queued rather than run concurrently, but it is
advisory prose with no gate, so it never fired.

A fifth defect surfaced while designing: `pr_for` returns `$matches[0]`,
silently discarding every PR after the first. The project's own rule — never
`Closes #N` on a beta or intermediate PR, only the graduation PR closes the
reporter's issue — guarantees one issue has several PRs, so this is a live bug,
not a hypothetical.

## Design goal

**Cheap forward motion.** States exist so that each one has exactly one next
action, and so that almost every action is a script rather than a session.

## 1. Two lifecycles, one card

One column was doing two jobs. Split them: **`Status` is the phase, `Awaiting`
is the wait, and the two are mostly orthogonal.**

| Status | Means | Exit |
|---|---|---|
| `Backlog` | captured, not analysed | analysis lands |
| `Analysis` | scope or approach unsettled, or a recorded wait over a worktree / draft PR | Definition of Ready met and priority set |
| `Ready for Dev` | analysed, prioritised, unblocked | dispatch |
| `In Progress` | branch exists — no open PR, or a draft PR with no review | the PR goes out of draft |
| `In Review` | one or more **non-draft** open PRs, loop running | all its PRs merge |
| `In Verification` | on main, not yet in a stable release | graduation PR closes the issue |
| `Done` | shipped stable | — |

**#707 amendment.** Refinements to the orthogonality above, from four real
mis-columned cards. The derived-column order is now, highest first:

```
non-draft open PR        -> In Review
blocked / awaiting != null -> Analysis
draft PR OR live worktree  -> In Progress
merged closing PR          -> In Verification
analysed + priority        -> Ready for Dev
analysed                   -> Analysis
else                      -> Backlog
```

- **A wait is not fully orthogonal.** A recorded `Awaiting` (or a `blocked`
  label / open `Blocked by #N`) pulls the item back to `Analysis` over a bare
  worktree, a still-draft PR, **or a merged-but-unreleased fix** — unsettled
  scope must not read as progress. It does *not* override `In Review`. This
  reverses the original "a wait never rewrites the phase" for every phase
  except `In Review`.
- **A draft PR is `In Progress`, not `In Review`.** `In Review` requires a
  PR that is out of draft — the loop has actually started. A draft PR with no
  review is a branch-plus-PR that nothing is reviewing yet.
- **Active work outranks landed work.** `In Progress` (a live worktree or an
  open draft PR) is checked before `In Verification`, so an issue with a
  merged intermediate `Part of #N` PR **and** an active follow-up branch
  reads as `In Progress`, not verified.
- **`matches_issue` ignores scratch worktrees.** `pin-<n>-…`, `design-<n>-…`
  and `bench-…` worktrees (optionally under the `worktree-` prefix) carry an
  issue number but are pinning / design scratch, not implementation branches;
  joining them pinned an issue to `In Progress` for good (#602). This, plus
  `worktree_is_stale` for genuinely merged branches, is why the rot-worktree
  case does not need `In Verification` ranked above `In Progress`.
- **A stale board card is surfaced in `orphans`.** A `PullRequest` card whose
  PR closed or merged → `stale_pr_card` → rhythm `archive_pr_card`; an
  `Issue` card whose issue closed → `stale_issue_card` → rhythm `move_card`
  (to *Done*). `pr_board` is joined only against open PRs and `items`
  iterates only open issues, so nothing reconciled either before.
- **`escalated` on `resume_count >= 2` is suppressed once a fix has merged.**
  `resume_count` never decrements, so an issue handed back twice before a
  third reframed attempt landed (#683 → #686) kept firing the escalation on a
  fix already on `main`.
- **`In Verification` gets an issue-facing signal.** The column lives only in
  the Project field, so a reporter reading the issue sees no sign it is
  fixed. New rhythm action `announce_verification` (rank 1) fires once per
  issue: the PO comments the fix status and applies an `awaiting-release`
  label, which suppresses it thereafter. Closing still waits for the
  graduation PR.

`In Verification` is new. It sits **after merge to main and before release** —
the fast-forward rule makes `beta/main` strictly downstream of `origin/main`,
so a fix is on main first, reaches a beta build, is run for real, and only then
graduates. The digest already refuses to move a column for a merged PR, with
the comment "until the fix graduates to a stable release"; that period now has
a name.

### `Awaiting` becomes signed

Escalation and deferral are the same axis pointed in opposite directions.
Today every `Awaiting` value suppresses, which means an item blocked on the
maintainer gets **quieter**. That is inverted.

| Value | Direction | Effect |
|---|---|---|
| `reporter`, `upstream`, `discussion` | they owe us | quiet — suppressed from actions, still counted and listed |
| `maintainer` | **we owe them nothing; you owe us a decision** | **loud — ranked above every other action, with the open question attached** |

One field, one new value. No `Escalated` column is needed, because escalation
is not a phase: an escalated item is still in whatever phase it was in, it just
cannot advance without you.

## 2. `advance-pr` — one loop, one step, then exit

`backlog/SKILL.md` argues, correctly, that the rhythm pass must not learn to
drive the review loop: "two copies of one loop means one of them goes stale."
The fix is therefore **not** to copy the loop, but to extract it so there is
still exactly one copy, callable without a full session.

`advance-pr` is a new skill holding what is today `implement-issue` Step 11.
Three callers — `implement-issue`, the rhythm pass, and you directly. It
**advances exactly one PR by exactly one state and exits.** No implementation
context is ever re-read, which is where the cost went.

| PR fact | Step | Cost |
|---|---|---|
| CONFLICTING, textual conflicts | merge main, resolve, push | script |
| CONFLICTING, semantic conflicts | abort → escalate | script |
| draft, no review, checks green | `request-pr-review.sh` | script |
| draft, review in flight | nothing | free |
| draft, CHANGES_REQUESTED, < 3 rounds | **rework** | **model** |
| draft, CHANGES_REQUESTED, ≥ 3 rounds | escalate | script |
| draft, APPROVED, green | `gh pr ready` | script |
| draft, APPROVED, checks red | fix; escalate on the second failure | model / script |
| out of draft, no review | request review | script |
| out of draft, APPROVED | report, stop | free |
| merged | if it was the issue's **last** open PR, move the issue to `In Verification` | script |

Exactly one row needs a model.

**Sizing, against the real fleet.** 8 open PRs → 2 model steps (#614 and #620
are the only CHANGES_REQUESTED) and 6 script steps. The same fleet today costs
5 × `implement-issue` at $1–4 each, which is precisely why none of them ran.

The existing guards carry over unchanged and must not be weakened:

- CI must be **green**, not merely unconflicted, before `gh pr ready` — a
  `MERGEABLE` PR with checks still running is not ready.
- Out of draft is **not** the same as reviewed. `reviewDecision` is trusted
  when set; otherwise fall back to the **last** non-`COMMENTED` review, never
  to any review, because GitHub never rewrites a stale `APPROVED`.
- A Stage 3 CI-mode PR still stays draft until you flip it.

## 3. Escalation is derived, not bookkept

All four triggers, and three of them are already facts on GitHub:

| Trigger | Source |
|---|---|
| review loop not converging (≥ 3 `CHANGES_REQUESTED` without an `APPROVED`) | count reviews on the PR — derived |
| CI red after a retry | count failed check runs across head commits — derived |
| semantic conflict abort | `advance-pr` writes `Awaiting: maintainer` and posts the conflict summary |
| implementation session died twice | count the handoff comments the dev identity posts on each resume — GitHub-native |

Nothing lands in a local file, so **state lives on GitHub, nowhere else**
survives intact.

The session-died counter is the only one that needs a new write, and it is a
comment rather than a file: each resume posts one, so counting them is
counting GitHub history.

## 4. PR → issue: reference many, close one

- Every PR body carries `Refs #N`.
- **At most one** PR carries `Closes #N` — the graduation PR, per the standing
  no-auto-close rule.
- **`pr_for` returns the set, not `$matches[0]`.** An issue's column derives
  from all of its open PRs; it leaves `In Review` only when every one of them
  has merged.
- **PR board cards go away.** One card per unit of work. `Priority` and
  `Awaiting` — the deferral machinery that exists so a decision is recorded
  once instead of re-argued every tick — move onto the issue, where they cannot
  be ambiguous between two cards for the same work.
- `implement-issue` opens a one-line issue itself when started from a bare
  refactor or TODO item, so the rule costs nothing at the point of use. Orphan
  PRs become a reported defect rather than a normal case.

## 5. Collide at scheduling time, not at merge time

The gate belongs **before** dispatch. Detecting a collision among open PRs is
detecting a fire; the requirement is not to start work that touches a file
already in flight. Half the check is exact:

**In-flight set (computed, exact):** the union of `gh pr diff --name-only` over
every open PR and `git diff --name-only main...` over every live worktree
branch.

**Candidate set (predicted):** named by the Stage 2 analysis, or stated by the
PO at dispatch. **A `dispatchable` proposal must carry its predicted touch-set;
no touch-set, no dispatch.**

| Outcome | Result |
|---|---|
| predicted ∩ in-flight = ∅ | dispatchable |
| predicted ∩ in-flight ≠ ∅ | `queued behind #N` — reported, never dropped |
| two Ready items predict overlapping sets | **cluster** — propose them as one dispatch, one branch, one PR |

Clustering is the cheaper shape: two issues that will fight over the same file
cost less as one unit of work than as two PRs plus a conflict resolution.

## 6. Flow policy: empty the board from the right

Replaces the alphabetical sort.

### Rule 1 — Pull from the right

Finish started work before starting new work. Actions rank by the column of the
item they serve, rightmost first:

```
Awaiting: maintainer  ->  read first, always — the escalation valve
In Verification       ->  graduate: cut the release, close the issue
In Review             ->  advance-pr toward merge
In Progress           ->  finish the branch into a PR
Ready for Dev         ->  dispatch  (gated by Rules 2 and 3)
Analysis              ->  groom
Backlog               ->  triage
```

Escalations sit above the column order. An escalation that ranks by column is
an escalation that waits, which defeats the valve.

### Rule 2 — Bugs pre-empt, they do not add

A `bug` opened by someone other than the maintainer jumps the queue **at
analysis**, and enters at the front of `Ready for Dev`. But it **displaces** a
feature from dispatch rather than being dispatched alongside one.

Bugs beat the pull order. Nothing beats the WIP limit. This is what stops
"prioritise bugs" from quietly becoming "unbounded WIP" — which is the state
the fleet is in now.

### Rule 3 — Nothing starts that collides

Section 5, applied at dispatch.

### The WIP limit: 3

WIP counts `In Progress` + `In Review` **together** — a branch and its PR are
one piece of work, not two.

Above the limit, `dispatchable` is suppressed entirely and the pass reports:

```
WIP 7/3 — finish before starting
```

Three is deliberately aggressive. With 7 in flight, dispatch stays shut until
the fleet drains to 2, which is the point: the current jam must clear before
anything new starts. A limit low enough to hold also makes same-file collisions
rare without the gate having to catch them.

## Migration: the existing jam

The new machine does not unjam itself.

1. Order the pipeline cluster (#614, #620, #638, #645 — all editing the same
   three files) lowest-number-first.
2. Land them one at a time, so each subsequent one merges against a main that
   is moving by one PR rather than five.
3. Record a decision on the three long-lived deferrals (#437 P4, #354 and #167
   awaiting discussion) — either they are `Awaiting: maintainer` and want your
   decision, or they are genuinely parked and stay quiet.
4. Only once WIP ≤ 2 does dispatch reopen.

## What changes where

| Component | Change |
|---|---|
| Project #1 `Status` field | add `In Verification` |
| Project #1 `Awaiting` field | add `maintainer` |
| Project #1 | remove PR cards; issues only |
| `backlog-digest.sh` | `pr_for` returns a set; column derives from all PRs; add `In Verification`; compute the in-flight file set |
| `backlog-rhythm.sh` | rank by column right-to-left, escalations first; WIP limit; collision gate on `dispatchable`; derive the four escalation triggers |
| `advance-pr` (new skill) | the extracted review loop, one PR one step |
| `implement-issue` | Step 11 delegates to `advance-pr`; opens its own issue when given none; PR body carries `Refs #N` |
| `backlog/SKILL.md` | the state table, signed `Awaiting`, the flow policy, the dispatch gate |

## Open questions

None. Every fork raised in brainstorming was decided.
