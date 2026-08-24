---
name: advance-pr
description: Use when a single open PR needs moving one step closer to merge — requesting its review, acting on a verdict, resolving a conflict, or flipping it ready. Advances exactly one PR by exactly one state and exits.
---

# Advance PR

## Overview

This is the *only* copy of the review loop. It used to live twice — once as
`implement-issue` Step 11, and once threatened to be re-built inside the
rhythm pass, which is exactly what `backlog/SKILL.md` warns against: "two
copies of one loop means one of them goes stale." The fix here is not to
copy the loop a second time, it is to **move** it, so there is still exactly
one copy, and three callers reach it: `implement-issue` Step 11 delegates to
it, `backlog-rhythm.sh`'s `In Review` actions delegate to it, and the
maintainer can run `/advance-pr <n>` directly.

**Every open PR in this repo resolves to one action today: run
`/implement-issue`, at $1–4 a session.** The maintainer will not spend five
of those in a sitting, so the queue only grows — 8 open PRs, all drafts, 6
conflicting, none ever approved, is what that produced. The reason this skill
is cheap enough to actually get run is that it does less: it reads the PR's
current facts off GitHub, executes the single transition-table row those
facts match, and stops. It does **not** re-read the diagnosis, the scope
assessment, or any of the reasoning that produced the diff — that re-reading
is where `implement-issue`'s cost went, and none of it is needed to decide
whether to request a review, flip a PR ready, or fix a merge conflict.

**Advances exactly one PR by exactly one state, then exits.** Concretely:
read the PR's facts, find the single row of the table below that they match,
perform that row's action, and stop — even when the action you just took
would, if you re-read the PR right now, match a *different* row. Don't
re-read and don't chain into that next row. That next row belongs to the next
invocation, whether that is this same skill run a minute from now by the
rhythm pass, or a maintainer typing `/advance-pr <n>` again. A PR that needs
three transitions to reach `gh pr ready` costs three cheap invocations, never
one expensive one that loops internally — that internal loop is the thing
that used to make this a full session.

The one exception where a single invocation genuinely spans a wait: the
`request review` row runs `scripts/request-pr-review.sh`, which blocks until
a verdict lands. That block is still *one* row's action (`request review`) — the
review script existing as a background-able script rather than inline
polling is what keeps the wait free of tokens. Acting on the verdict it
returns is the *next* invocation's job, not this one's.

## The transition table

One row per PR fact. Read the state first (below), find the row that
matches, do that and only that.

| PR fact | Step | Cost |
|---|---|---|
| CONFLICTING, textual conflicts | merge main, resolve, push | script |
| CONFLICTING, semantic conflicts | abort → escalate | script |
| draft, no review, checks green | `request-pr-review.sh` | script |
| draft, review in flight | nothing | free |
| draft, CHANGES_REQUESTED, < 3 rounds | collect findings, hand back to `/implement-issue <n>` | script |
| draft, CHANGES_REQUESTED, ≥ 3 rounds | report the round count and stop — this cap escalation is a derived GitHub fact `backlog-rhythm.sh` already reports every tick from the review-round count alone; writing `Awaiting: maintainer` is a judgement call for whoever reads that report, not mechanical work this skill performs | free |
| draft, APPROVED, green | `gh pr ready` | script |
| draft, APPROVED, checks red | fix; escalate on the second failure | model / script |
| out of draft, no review | request review | script |
| out of draft, APPROVED | report, stop | free |
| merged | if it was the issue's **last** open PR, move the issue to `In Verification` | script |

**This skill never reworks a review verdict — it never edits code in
response to review findings.** Merging main to resolve a textual conflict and
fixing a red check on an approved PR are mechanical repairs, not reworks, and
stay rows in this table. Even a
`CHANGES_REQUESTED` PR is a script step here: collect the findings and hand
them back to `/implement-issue <n>`, which is the session that holds the Step
2 diagnosis and Step 3 scope assessment needed to tell a real review finding
from a decision Step 3 already made and rejected on purpose (see the
dedicated bullet below — this is not optional and not a formality). An
earlier version of this table had a "rework in place" row for the caller that
already held that context; it is gone, because a rework is not one mechanical
step, and `implement-issue` Step 11 already reworks in its own session before
calling back in here for the next transition. Against the real fleet at
design time, 8 open PRs cost 8 script steps here plus however many
`implement-issue` reworks the findings actually need.

If none of the rows match — e.g. `mergeable: UNKNOWN`, which GitHub computes
lazily on a cold PR — re-read once (`gh pr view` again after a few seconds).
If it still doesn't resolve, report the raw facts and stop; guessing at a row
that isn't there is worse than reporting nothing.

## Read the state first

```bash
git fetch origin
gh pr view <n> --json number,isDraft,mergeable,mergeStateStatus,reviews,comments,statusCheckRollup,headRefName
```

`comments` is not the same feed as `reviews`, and it is not optional to skip.
A maintainer can leave direction as an ordinary conversation comment —
"hold off, I want to rework the approach" — and that carries no `review`
state at all, so `reviews` alone will never show it. Read both, every
invocation, not only the first one for this PR: a comment posted mid-loop
is invisible to whichever caller invoked you unless you check for it here.
If a maintainer comment or a maintainer *review* (author is not the bot)
exists newer than anything else on the PR, that is authoritative — stop,
report it, do not act on GitHub's mechanical state underneath it.

## The verdict rules, carried over unchanged from Step 11

These came from real failures on this repo's own PRs. Weakening any of them
reopens the failure it fixed.

- **Trust `reviewDecision` when GitHub sets it; otherwise fall back to the
  last non-`COMMENTED` review, never to any review.** GitHub does not
  rewrite a stale `APPROVED` when new commits land, so an old approval
  sitting in the list is not evidence the current diff was reviewed.
- **CI must be green, not merely unconflicted, before `gh pr ready`.** A
  `MERGEABLE` PR with checks still running is not ready — `mergeable` only
  says the diff applies cleanly, it says nothing about whether it passes.
- **`COMMENTED` is not a verdict, and `request-pr-review.sh` resolves it for
  you — do not second-guess it.** `pr-review.yml` has exactly two legal
  verdicts, `APPROVE` and `REQUEST_CHANGES`; findings that do not block merge
  are an approval with the nits in the body, because a `COMMENTED` review
  leaves GitHub's `reviewDecision` showing the previous round's
  `CHANGES_REQUESTED`. The bot also posts an early placeholder review as
  `COMMENTED` before its real summary, so a `COMMENTED` seen while the review
  run is still going decides nothing. The script asks whether the
  workflow run is still live, not how long has elapsed, because no fixed
  timer is both short enough to report a finished `COMMENTED` promptly and
  long enough to never pre-empt a summary — this was tried and measured
  wrong in both directions (see the script's own comments for the incident
  history: #617, #622, #615, #636, #623). A `COMMENTED` that reaches you from
  the script arrived *after* the run finished, so it is the reviewer's last
  word without being a verdict: treat it exactly like `CHANGES_REQUESTED` —
  collect findings, do not flip the PR ready — and say in your report that
  the bot broke its own two-verdict contract, because the stale
  `reviewDecision` will still be blocking the merge.
- **On `APPROVED`, re-check mergeability before doing anything else** — do
  not trust whatever mergeability you read at the top of this invocation.
  A review round takes minutes, other PRs merge during it, and a
  `CONFLICTING` PR gets no new workflow run to signal the change:

  ```bash
  git fetch origin
  gh pr view <n> --json mergeable,mergeStateStatus
  ```

  This exact gap — reporting a stale "clean" reading after the state moved
  under it — handed the maintainer a conflicted PR described as green on
  #609. If it now reads `CONFLICTING`/`DIRTY`, that is the CONFLICTING row
  above, not the APPROVED row: resolve it first, and treat the merge commit
  under the push-after-approval rule next.
- **The push-after-approval rule.** If you push commits after an `APPROVED`
  verdict, ask whether they touched code the reviewer actually reviewed.
  If they didn't — a `CHANGELOG.md` line, a nit parked in `TODO.md`, a clean
  `git merge origin/main` that changed nothing under review — re-check
  `gh pr checks` and mergeability, then flip, and name those commits in your
  report so the maintainer can check the call rather than take it on trust.
  If they did, do **not** flip: the approval was for a diff that no longer
  exists, and `gh pr ready` on a stale-approved diff is the one way this
  skill can actively mislead. That is the next invocation's `request review`
  row, not this one's `gh pr ready` row.
- **A review from the maintainer, or a maintainer conversation comment,
  stops everything and is authoritative** — see "Read the state first"
  above. A bot `APPROVED` sitting on top of a maintainer direction to redo
  the work is worth nothing.
- **The `< 3` / `≥ 3` round count is derived, not tracked locally** — count
  `CHANGES_REQUESTED` reviews on the PR with no later `APPROVED`. Three
  rounds of disagreement means the reviewer and the diff disagree about the
  design, not about a bug, and a fourth round will not settle it — that's
  the escalate row, not another rework.
- **This skill never reworks a review verdict — on EVERY `CHANGES_REQUESTED` verdict,
  collect the findings and hand back to `/implement-issue <n>`, whatever
  caller invoked you and however much context it holds.** This supersedes an
  earlier ruling that let a caller holding the Step 2 diagnosis and Step 3
  scope assessment rework in place here. Two unsupervised runbooks disagreeing
  about who reworks a review — this skill saying "rework in place" and
  `implement-issue` Step 11 saying "act on it in this session" — realistically
  produced a double rework, and a rework is not one mechanical step in the
  first place, which is the property this whole skill is built on. Collecting
  findings and hand back is a script step regardless of context; the actual
  rework is Step 11's job, done in the session that holds the Step 2 diagnosis
  and Step 3 scope assessment needed to tell a real review finding from a
  decision Step 3 already made and rejected on purpose —
  `superpowers:receiving-code-review` exists precisely to make that call case
  by case, and it cannot make it from a bare diff and a review comment; it
  needs the reasoning behind the diff, which only `implement-issue` holds.
  When Step 11 invokes this skill again for the next transition, it has
  already done that rework itself, in its own session, before calling in.

## The two escalations this skill owns

Every other escalation trigger is a GitHub fact something else can derive by
reading history — a review-round count, a failed-check count, a doubled
resume comment. These two can only be known by the thing doing the work, so
this skill is where they get written. Both end the same way: **stop, write
`Awaiting: maintainer`, post a comment naming why.**

Since PR cards do not exist on the board — `Priority` and `Awaiting` live on
the issue, so they cannot be ambiguous between two cards for one piece of
work — resolve the PR's issue first. **If the PR body carries no `Refs #N`
or `Closes #N` at all, stop here and report it rather than let the lookup
degrade into an empty `$item`** — spec §4 calls an orphan PR a reported
defect, not a normal shape this skill should paper over.

`gh project item-edit`'s ID-based form needs **three** GraphQL node IDs, not
two — `--id` (the item), `--field-id`, and `--single-select-option-id` all
need a `--project-id` alongside them or it fails outright with
`project-id must be provided`. Nothing else in this repo's scripts resolves
`PROJECT_NUMBER` to that id, so do it explicitly:

```bash
project_id=$(gh project view "$PROJECT_NUMBER" --owner johanzander --format json --jq .id)

# --limit 200: item-list defaults to 30 and TRUNCATES SILENTLY past it — no
# error, just a shorter list, exactly the failure mode CLAUDE.md calls out
# ("a short list looks like a correct answer"). backlog-digest.sh:178 passes
# the same --limit 200 for the same reason. At 57 items today, the default
# would already have missed roughly half the board.
item=$(gh project item-list "$PROJECT_NUMBER" --owner johanzander --format json --limit 200 \
  | jq -r --argjson n <issue-number> '.items[] | select(.content.number == $n) | .id')

gh project item-edit --id "$item" --project-id "$project_id" \
  --field-id <awaiting-field-id> --single-select-option-id <maintainer-option-id>
scripts/gh-agent.sh --as dev pr comment <n> --body "..."
```

Resolve `<awaiting-field-id>` and `<maintainer-option-id>` once via
`gh project field-list "$PROJECT_NUMBER" --owner johanzander --format json` —
don't hardcode them, the board is the source of truth for its own field
shape. (As of this writing the `maintainer` option itself does not exist yet
on the live board — adding it is the Task 1 board migration, held for the
maintainer to run by hand per this plan's own review Ruling 6. This skill's
job is to write to it correctly once it exists, not to create it.)

- **Semantic conflict.** `git merge origin/main` produced conflicts that are
  not textual — the two sides disagree about *behaviour*, not just about
  which lines sit where (a mechanical conflict — `CHANGELOG.md` under
  `## [Unreleased]`, import ordering, a lockfile — is not this row; resolve
  those and move on, same as `sweep-prs` does). **Abort the merge, do not
  guess:**

  ```bash
  git merge --abort
  ```

  Then escalate, quoting the conflicting hunks in the comment so the
  maintainer sees exactly what disagreed rather than being told a conflict
  happened. Guessing at someone else's intended behaviour to make a merge go
  green is how a resolved conflict silently reverts a decision nobody
  revisited.
- **CI red after a retry.** This skill pushed a fix for a failing check and
  the checks failed again on the next commit. One retry is enough to tell a
  flake from a real breakage — a second failing run is not bad luck, it's a
  finding. Escalate rather than attempt a third fix; a model guessing twice
  at what broke CI is not more likely to be right the third time, it's
  guessing.

## Hard constraints

- **Never merge.** Not after green CI, not after `APPROVED`, not for a
  trivial diff. The merge is the maintainer's judgement and this skill never
  takes it.
- **Never `gh pr ready` a PR that is red, conflicted, or unreviewed.** Out of
  draft is not the same thing as reviewed — `reviewDecision` unset or stale
  is still unreviewed, whatever the draft flag says.
- **Never flip a PR whose approval predates commits that touched reviewed
  code.** See the push-after-approval rule above; this is the one way
  flipping the ready flag can mislead, and the ready flag is only worth
  anything if it never does.
- **Never re-trigger a review that is already in flight.** `request review`
  only applies to the "no review yet" row. If a review is running, the row
  is "nothing, free" — re-triggering starts a second paid review round on a
  diff the first one hasn't finished looking at.
- **Never chain into a second row.** One PR, one state, then exit — that
  property is what makes this skill cheap enough to be the default action
  instead of a whole session. If the action you took changed the PR into a
  state that itself needs advancing, that is the next invocation's job.
