---
name: sweep-prs
description: Use when asked to check, refresh, or keep the open bess-manager PRs green and mergeable across the whole fleet — pruning merged worktrees, merging main into stale branches, and reporting red CI. Reports only by default; pass PR numbers to act on those, or --all (pair with /loop) for unattended maintenance.
---

# Sweep PRs

## Overview

Walk every git worktree in the repo and bring the fleet back to a known
state: prune the ones whose PR has merged, refresh the ones whose PR has
gone stale, report everything else.

This exists because a PR rots without anyone touching it. A branch that was
green and mergeable when its session ended goes `CONFLICTING` the moment two
or three others merge into `main` ahead of it — and a `CONFLICTING` PR
**creates no workflow run at all**, so it presents as "CI never fired", not
as a conflict. Nobody investigates a PR that appears to have no checks. The
first dry run of this sweep found two such PRs (#437, #579) sitting
conflicted with no one aware.

## When to Use

- Asked to check whether the open PRs are green/mergeable, or to fix up the
  ones that aren't.
- Under `/loop /sweep-prs --all` to hold the fleet green between issues.
  Self-paced is right: a fully-green fleet costs a noop tick. `--all` is
  required here — a bare `/sweep-prs` on a loop just re-reports the same
  fleet forever without fixing anything.
- **Not** from inside an `implement-issue` session. That skill owns exactly
  one PR — its own — and deliberately does not widen into fleet cleanup
  (see its Step 10). Run this separately.

## Modes

Classification always covers every worktree in `git worktree list`. What
differs is **what gets acted on**, and that is chosen by the invocation:

| Invocation | Behaviour |
|---|---|
| `/sweep-prs` | **Report only — the default.** Classify the whole fleet, print what each PR *would* get, change nothing. No merges, no pushes. |
| `/sweep-prs 437 579` | Act, restricted to the listed PR numbers. Everything else is classified and reported, untouched. This is the normal way to use it: read the report, pick. |
| `/sweep-prs --all` | Act on every PR that survives the skip gate. Pair this one with `/loop` for unattended maintenance. |

**Report-only is the default on purpose.** Merging and pushing to a PR the
user has not looked at is not something to do because they forgot to pass a
flag. The safe mode is the one you get when you don't think about it; acting
is the one you have to ask for.

**Pruning merged worktrees runs in every mode, including report-only.** It
is not gated, because it deletes only work that is already merged into
`main` — nothing is at risk — and because gating it recreates exactly the
failure it was introduced to fix: a cleanup that depends on someone choosing
to run it doesn't run. That is how 39 worktrees accumulated on disk, 24 of
them long merged. The uncommitted-changes and live-session guards still
apply to it.

Whatever the mode, a branch is only ever *acted on* when it survives the
skip gate below; everything else is reported with its reason.

## Process

### 1. Skip gate (before anything else)

Another agent may be mid-`implement-issue` in any of these worktrees.
Merging `origin/main` underneath it moves its HEAD mid-run and puts two
sessions on the same branch pushing to the same PR. Leave a worktree alone
when any of these hold:

| Condition | Why |
|---|---|
| A live Claude session has its `cwd` at or under the worktree | Owned. **Any status counts — `idle` and `blocked` included.** An agent parked between Step 6 and Step 8 reads as idle and still holds that branch. |
| `git status --porcelain -uno` is non-empty | Uncommitted tracked work. One such worktree held a 375-line module that existed nowhere else. |
| HEAD commit is under 30 minutes old | Likely active even if its session already exited. |
| Detached or locked | Almost always another agent's live session. |

Read ownership with `claude agents --json` run **unscoped** (from `~`) —
per `docs/agents/local-agent-environment.md`'s Worktree Conventions, sibling
worktrees never appear in the project-scoped view, and missing one is exactly
the collision this gate exists to prevent.

### 2. Classify

```bash
git fetch origin --prune
# NOTE: `git branch --merged` / `rev-list origin/main..branch` DO NOT WORK
# here -- this repo squash-merges, so a merged branch's commits are never
# reachable from main and every worktree looks unmerged forever. PR state is
# the only authoritative signal.
merged=$(gh pr list --state merged --limit 200 --json headRefName -q '.[].headRefName')
owned=$(cd ~ && claude agents --json 2>/dev/null | jq -r '.[].cwd')

git worktree list | awk 'NR>1 {print $1}' | while read -r wt; do
  # A registration whose directory is gone is a PHANTOM, not a detached HEAD:
  # `git -C` fails, so $b comes back empty and the detached branch below would
  # swallow it. `git worktree list` tags these `prunable`.
  [ -d "$wt" ] || { echo "PHANTOM (prunable, needs unsandboxed prune): $wt"; continue; }
  b=$(git -C "$wt" branch --show-current 2>/dev/null)
  [ -n "$b" ] || { echo "SKIP (detached): $wt"; continue; }
  if echo "$owned" | grep -qF "$wt"; then
    echo "SKIP (live session): $b"; continue
  fi
  dirty=$(git -C "$wt" status --porcelain -uno)
  if [ -n "$dirty" ]; then
    # A worktree whose dirty set is ENTIRELY deletions is not someone's work
    # in progress -- it is a carcass left by a `git worktree remove` that the
    # sandbox killed halfway (see below). Say so, or the sweep reports its own
    # wreckage back as a backlog of stranded edits.
    if [ -z "$(printf '%s\n' "$dirty" | grep -v '^ D ')" ]; then
      echo "CARCASS (failed prune, $(printf '%s\n' "$dirty" | grep -c .) deletions): $wt  ($b)"
    else
      echo "SKIP (uncommitted changes): $b"
    fi
    continue
  fi
  if echo "$merged" | grep -qx "$b"; then
    echo "PRUNE: $wt  ($b)"; continue
  fi
  age=$(( ($(date +%s) - $(git -C "$wt" log -1 --format=%ct)) / 60 ))
  if [ "$age" -lt 30 ]; then
    echo "SKIP (HEAD ${age}m old, likely active): $b"; continue
  fi
  # GitHub computes `mergeable` LAZILY: the first query on a cold PR returns
  # UNKNOWN *and* triggers the computation, so a single pass reports UNKNOWN
  # for every stale PR -- i.e. exactly the ones this sweep exists to find.
  # Ask again until it resolves. Verified: all three resolved on retry.
  for _ in 1 2 3; do
    pr=$(gh pr view "$b" --json number,mergeable,mergeStateStatus,statusCheckRollup \
         -q '"#\(.number) \(.mergeable) \(.mergeStateStatus) " +
             ([.statusCheckRollup[]?|select(.conclusion=="FAILURE").name]|join(","))' \
         2>/dev/null)
    [ -z "$pr" ] && { echo "NO PR (never pushed): $b"; break; }
    case "$pr" in *UNKNOWN*) sleep 3; continue;; esac
    echo "OPEN $pr <- $wt"; break
  done
done
```

### 3. Act

**`PRUNE`** — the PR merged. **Do not run `git worktree remove` yourself.**
The sandbox denies the `.git/worktrees/<name>` unlink that removal ends with,
and removal deletes the working tree *before* it gets there, so a run from
here does not fail cleanly — it destroys ~393 tracked files and leaves a
carcass that can never be pruned again. `git worktree prune` is denied by the
same unlink **and exits 0 while failing**, so there is no in-sandbox recovery
either — and no exit status you can trust. This is not a hypothetical: three
sweeps did exactly that to 13 worktrees before it was diagnosed. See
`docs/agents/local-agent-environment.md`, "git worktree remove is denied too".

Collect every `PRUNE`, `CARCASS` and `PHANTOM` instead, and emit **one**
command for the maintainer to paste with a `!` prefix, which runs unsandboxed:

```bash
# Emit this; do not execute it. It must run from a NON-worktree-isolated
# session -- an isolated one refuses the `cd` to the shared checkout.
cd /Users/johanzander/GitHub/bess-manager && for wt in <paths>; do
  b=$(git -C "$wt" symbolic-ref --short HEAD 2>/dev/null)
  git worktree remove --force "$wt"
  [ -n "$b" ] && git branch -D "$b"
done; git worktree prune; git worktree list | wc -l
```

`<paths>` is the space-separated list of full worktree paths from the reported
`PRUNE`/`CARCASS`/`PHANTOM` lines. Report the path, not the branch name: `git
worktree list` yields paths, and a sibling worktree (`../bess-manager-feature/`)
does not live under `.claude/worktrees/`, so the branch name alone cannot
reconstruct the path to remove.

The trailing `git worktree prune` is what clears any `PHANTOM`, whose
directory is already gone so `remove` has nothing to work with. `[ -n "$b" ]`
rather than `&&` because a phantom yields no branch name.

`--force` is required for a `CARCASS` (its own damage reads as uncommitted
changes) and harmless for a clean `PRUNE`. Force-deleting the *branch* is
expected too, and is a separate thing: squash-merge means the branch's commits
never become reachable from `main`, so `git branch -d`'s ancestry check always
refuses.

Before listing a `CARCASS`, confirm its branch is genuinely spent — the PR
merged, and any commits past the merged head are already in `origin/main`.
A carcass has no recoverable working-tree content by definition (deletions
only), but the *branch* may still hold commits that never landed.

**`OPEN`** — in report-only mode (the default), print the row from the table
below that this PR matches and take no action. In `--all` mode, or when the
PR number was listed explicitly, act on it. This is judgment, not script:

| State | Action |
|---|---|
| `CONFLICTING`, or `mergeStateStatus: BEHIND` | In that worktree: `git merge origin/main`. Auto-resolve **mechanical** conflicts only — `CHANGELOG.md` under `## [Unreleased]` (keep both bullets), import ordering, lockfiles. Then `./scripts/quality-check.sh`, then push. |
| Conflict is semantic | `git merge --abort` and report it. Do not guess at someone else's fix. |
| Checks `FAILURE` | Read the failing job log (`gh run view --log-failed`). Auto-fix only Black/Ruff formatting and a missing `## [Unreleased]` changelog entry — the mechanical CI failures. A real test failure belongs to whoever wrote the diff; report it, never patch it blind. |
| Green and mergeable | Nothing. |
| `NO PR (never pushed)` | Report only, never delete. A branch with local commits and no PR is abandoned work or someone's parked experiment; the first dry run found 11. The sweep is not what decides their fate. |

### 4. Report

In report-only mode, end with the invocation that would act on what you
found — `/sweep-prs 437 579` — so choosing is one paste, not a re-read.

Print what was pruned, what was refreshed and pushed (or *would* be), what
failed, and **what was skipped with the reason** — "3 skipped: #589 owned by live
session `bess-manager-34`" is the useful output. A sweep that silently does
nothing is indistinguishable from a broken one.

## Hard constraints

- Never push without `./scripts/quality-check.sh` green.
- Never `git stash` — denied repo-wide, one shared stack
  (`docs/agents/local-agent-environment.md`).
- Never `--force` / `--force-with-lease` on someone else's branch.
- Never merge a PR, take it out of draft, or close it.
- One commit per PR per sweep: `chore: merge main into <branch>`.
- Never resolve a semantic conflict or fix a real test failure on a PR that
  isn't yours to diagnose. Report and move on.
- **Run one sweep at a time.** Two collide with each other for exactly the
  reason the skip gate exists, and nothing enforces it.
- Never act on a PR the invocation didn't select. A bare `/sweep-prs`
  reports; it does not merge or push.

## Rationalizations — Reality

| Excuse | Reality |
|---|---|
| "that worktree's session is idle, so nobody's using it" | Idle and blocked both mean owned. An agent parked between Step 6 and Step 8 is idle and still holds that branch. |
| "the PR shows no CI checks, so the workflow must have failed to trigger" | Two causes, never a dropped event. A CONFLICTING PR creates no run at all; a just-pushed PR has a run that hasn't registered yet. Check `mergeable`, then `gh run list --branch`. |
| "`mergeable` came back UNKNOWN, so gh can't tell" | It's computed lazily — the first query only triggers the computation. Ask again. A single pass reports UNKNOWN for precisely the stale PRs you're looking for. |
| "`git branch --merged` will tell me what's safe to delete" | Not in this repo. Squash-merge means a merged branch is never an ancestor of main, so that check reports everything as unmerged and cleanup never fires. Use `gh pr list --state merged`. |
| "they asked me to sweep, obviously they want it fixed" | A bare `/sweep-prs` reports. Merging and pushing to a PR the user hasn't looked at is not something to infer from a missing flag — hand back the report and the `/sweep-prs <numbers>` line. |
| "they named #437, and #579 has the same problem, I'll do both" | They picked one. Selecting PRs is the whole point of the mode; extending the selection silently makes it meaningless. |
| "this conflict is small, I can see what they meant" | Mechanical means CHANGELOG/imports/lockfiles. Anything touching logic is a guess at someone else's fix — abort and report. |
| "I'm already in an implement-issue session, I'll sweep while I'm here" | That session owns one PR and lacks the skip gate. Widening it is how two sessions end up pushing to one branch. |

## Red Flags — Stop and Go Back

- About to act on a worktree with a live session, uncommitted tracked
  changes, or a HEAD under 30 minutes old.
- About to treat `mergeable: UNKNOWN` as a final answer.
- About to push a merge without `quality-check.sh` green.
- About to fix a real test failure on a PR you didn't write.
- About to run this from inside an `implement-issue` session.
- About to merge or push on a bare `/sweep-prs` — that mode reports only.
- About to act on a PR the user didn't list.
