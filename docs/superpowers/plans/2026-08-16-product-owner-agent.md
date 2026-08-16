# Product Owner Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Product Owner agent that owns the bess-manager backlog —
answering reporters, driving issues to a Definition of Ready, ordering the
work on a GitHub Project board, and dispatching implementation sessions in
dependency order.

**Architecture:** A shell script (`backlog-digest.sh`) gathers all evidence in
one shot so no model ever reads 37 issue bodies to decide what is next. A
skill holds the judgment and a `.claude/agents/product-owner.md` file makes it
a first-class agent. All durable state lives on GitHub — a Project v2 board,
labels, and issue comments — never in a local file. The agent runs on three
surfaces sharing one identity: event-driven intake in CI, a local loop for
follow-up, and conversation with the maintainer.

**Tech Stack:** bash + `gh` CLI + `jq` for the digest; GitHub Projects v2;
Claude Code agent/skill markdown; pytest (subprocess + PATH shims) for tests;
GitHub Actions for the intake surface.

**Spec:** `docs/superpowers/specs/2026-08-15-backlogger-agent-design.md`

## Global Constraints

- **GitHub is the only store.** No local file mirrors board or issue state.
  A generated snapshot is forbidden, not merely discouraged.
- **No fallbacks.** Per `docs/agents/rules.md`, failures raise. A missing
  `project` scope hard-fails with the `gh auth refresh -s project`
  instruction; it never degrades to a local file.
- **The PO never creates worktrees and never implements.** Dispatch is
  `claude --bg -n "issue-<n>" "/implement-issue <n>"`; that session's Step 4
  creates its own worktree from a fresh `origin/main`.
- **Nothing is dispatched that has not met the Definition of Ready.**
- **Three identities:** `bess-product-owner` (new machine user),
  `bess-developer` (renamed from `bess-agent`), `bess-reviewer` (the existing
  `CLAUDE_REVIEWER` App). Developer and Reviewer must stay distinct.
- **Avatars are maintainer-supplied.** No task generates or specifies images.
- **Board columns:** `Backlog / Analysis / Ready / In progress / In review /
  Done`. Board fields: `Priority`, `Source`, `Awaiting`.
- **Analysis sub-states:** `reporter`, `discussion`, `upstream`, `analysis`.
- **Ordering is serialise-on-merge.** No stacked PRs; `implement-issue` is not
  modified.
- Run `./scripts/quality-check.sh` before every commit.

---

## Maintainer prerequisites (not agent tasks)

These block Tasks 3 and 6 and only the maintainer can do them:

1. `gh auth refresh -s project` for the maintainer's own token.
2. Create the `bess-product-owner` GitHub account; generate a PAT with `repo`
   **and `project`** scope.
3. Rename the `bess-agent` account to `bess-developer`.
4. Upload avatars to all three accounts.
5. Add `BESS_PO_TOKEN` and `BESS_DEVELOPER_TOKEN` to the main checkout's
   `.env`, and add `BESS_PO_TOKEN` to the repo's Actions secrets.

---

## Task 1: The backlog digest script

**Files:**
- Create: `scripts/backlog-digest.sh`
- Test: `backend/tests/test_backlog_digest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a single JSON object on stdout with this exact schema, which every
  later task reads:

```json
{
  "counts": {"issues": 37, "prs": 4, "worktrees": 31, "sessions": 2},
  "items": [
    {
      "number": 502,
      "title": "Charging power rate setting has no effect",
      "labels": ["bug", "analyzed"],
      "author": "someuser",
      "age_days": 12,
      "last_activity_days": 3,
      "comments": 4,
      "column": "Analysis",
      "awaiting": "reporter",
      "priority": "P1",
      "pr": 588,
      "pr_state": "CONFLICTING",
      "worktree": "/path/to/wt",
      "session": "issue-502",
      "blocked_by": [499]
    }
  ],
  "orphans": [
    {"kind": "worktree_merged", "ref": "fix/issue-499-foo", "detail": "PR 590 merged"}
  ]
}
```

Field rules: `column` is the **derived** column, never what the board
currently says. `awaiting` is `null` outside the Analysis column.
`priority` is `null` when unset. `blocked_by` is parsed from
`Blocked by #N` lines in the issue body.

`orphans[].kind` in v1 is one of exactly two values — `worktree_no_pr` and
`pr_no_issue` — because those are the only two the join can derive without
extra queries. `worktree_merged` needs a merged-PR lookup and `session_dead`
needs session history; both are deliberately out of v1, and `sweep-prs`
already covers merged-worktree pruning. Do not emit a kind this list does not
name.

- [ ] **Step 1: Write the failing test for the derived-column rules**

Create `backend/tests/test_backlog_digest.py`. Follow the shim pattern in
`backend/tests/test_worktree_setup_script.py` — run the real script as a
subprocess with a fake `gh` on `PATH`.

```python
"""Tests for scripts/backlog-digest.sh — the Product Owner's evidence
gatherer.

The script joins four sources (gh issues, gh PRs, git worktrees, claude
sessions) into one JSON document. Everything expensive or non-deterministic is
replaced by a shim on PATH: `gh`, `git` (worktree list only) and `claude` all
read canned fixtures, so the join logic is exercised without network or a real
fleet.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "backlog-digest.sh"


def _write_shim(bin_dir: Path, name: str, body: str) -> None:
    p = bin_dir / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def _run(bin_dir: Path) -> dict:
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    proc = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=True
    )
    return json.loads(proc.stdout)


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    _write_shim(d, "claude", 'echo "[]"')
    _write_shim(d, "git", 'echo ""')
    return d


def _gh_shim(issues: list, prs: list, project_items: list) -> str:
    """A `gh` that answers the three subcommands the digest calls."""
    return f"""
case "$1 $2" in
  "issue list") cat <<'EOF'
{json.dumps(issues)}
EOF
    ;;
  "pr list") cat <<'EOF'
{json.dumps(prs)}
EOF
    ;;
  "project item-list") cat <<'EOF'
{json.dumps({"items": project_items})}
EOF
    ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""


def test_untouched_issue_lands_in_backlog(bin_dir: Path) -> None:
    issue = {
        "number": 601,
        "title": "Wizard shows stale inverter",
        "labels": [{"name": "bug"}],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-01T00:00:00Z",
        "comments": [],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)

    assert [i["number"] for i in digest["items"]] == [601]
    assert digest["items"][0]["column"] == "Backlog"
    assert digest["items"][0]["awaiting"] is None


def test_unlabeled_issue_with_discussion_lands_in_analysis(bin_dir: Path) -> None:
    """#592 and #593 are real examples: open, actively discussed, no labels.
    A label-only rule files them under Backlog while a live conversation runs."""
    issue = {
        "number": 592,
        "title": "VPP idle mode",
        "labels": [],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-14T00:00:00Z",
        "comments": [{"body": "what do you mean by idle?"}],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)

    assert digest["items"][0]["column"] == "Analysis"
    assert digest["items"][0]["awaiting"] == "discussion"


def test_needs_debug_log_is_awaiting_reporter(bin_dir: Path) -> None:
    issue = {
        "number": 603,
        "title": "Savings look wrong",
        "labels": [{"name": "bug"}, {"name": "needs-debug-log"}],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "comments": [{"body": "please attach a debug bundle"}],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)

    assert digest["items"][0]["column"] == "Analysis"
    assert digest["items"][0]["awaiting"] == "reporter"


def test_blocked_by_is_parsed_from_body(bin_dir: Path) -> None:
    issue = {
        "number": 604,
        "title": "Second half of the migration",
        "labels": [{"name": "blocked"}],
        "author": {"login": "owner"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "comments": [],
        "body": "Blocked by #599\nrest of the description",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)

    assert digest["items"][0]["blocked_by"] == [599]


def test_conflicting_pr_is_reported_on_its_issue(bin_dir: Path) -> None:
    issue = {
        "number": 605,
        "title": "Fix the thing",
        "labels": [{"name": "bug"}, {"name": "has-fix-pr"}],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-10T00:00:00Z",
        "comments": [],
        "body": "",
    }
    pr = {
        "number": 610,
        "title": "fix: the thing",
        "headRefName": "fix/issue-605-thing",
        "mergeable": "CONFLICTING",
        "body": "Fixes #605",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [pr], []))

    digest = _run(bin_dir)

    item = digest["items"][0]
    assert item["pr"] == 610
    assert item["pr_state"] == "CONFLICTING"
    assert item["column"] == "In review"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py -v
```

Expected: every test FAILS — `scripts/backlog-digest.sh` does not exist, so
bash exits non-zero and `subprocess.run(check=True)` raises
`CalledProcessError`.

- [ ] **Step 3: Write the digest script**

Create `scripts/backlog-digest.sh`:

```bash
#!/usr/bin/env bash
#
# Gather the Product Owner's evidence in one shot: issues, PRs, worktrees,
# background sessions and board state, joined into a single JSON document.
#
# This exists so no model ever reads 37 issue bodies to answer "what's next".
# The PO reads this table and opens an individual issue only when it is
# actually deciding on that issue.
#
# Usage: scripts/backlog-digest.sh [--repo owner/name]
set -euo pipefail

repo="${REPO:-johanzander/bess-manager}"

issues=$(gh issue list --repo "$repo" --state open --limit 200 \
  --json number,title,labels,author,createdAt,updatedAt,comments,body)

prs=$(gh pr list --repo "$repo" --state open --limit 100 \
  --json number,title,headRefName,mergeable,body)

worktrees=$(git worktree list --porcelain 2>/dev/null \
  | awk '/^worktree /{print $2}' | jq -R . | jq -s .)

sessions=$(claude agents --json 2>/dev/null || echo '[]')

board=$(gh project item-list "${PROJECT_NUMBER:-1}" --owner "${PROJECT_OWNER:-johanzander}" \
  --format json 2>/dev/null || echo '{"items":[]}')

jq -n \
  --argjson issues "$issues" \
  --argjson prs "$prs" \
  --argjson worktrees "$worktrees" \
  --argjson sessions "$sessions" \
  --argjson board "$board" \
  --arg now "$(date -u +%s)" '
  def days_since($ts): (($now | tonumber) - ($ts | fromdateiso8601)) / 86400 | floor;

  def label_names: [.labels[].name];

  def pr_for($n): ($prs[] | select(
        (.body // "" | test("(?i)(fixes|closes|resolves) #\($n)\\b"))
     or (.headRefName | test("issue-\($n)(\\D|$)"))
  )) // null;

  def worktree_for($n): ($worktrees[] | select(test("issue-\($n)(\\D|$)"))) // null;

  def session_for($n): ($sessions[] | select(.name? == "issue-\($n)") | .name) // null;

  def blocked_by: [ (.body // "") | scan("(?i)blocked by #(\\d+)") | .[0] | tonumber ];

  def awaiting($labels; $comments):
      if ($labels | index("needs-debug-log")) then "reporter"
      elif ($labels | index("ready-for-analysis")) then "analysis"
      elif ($labels | index("upstream")) then "upstream"
      elif ($comments | length) > 0 then "discussion"
      else null end;

  def column($labels; $pr; $wt; $awaiting):
      if $pr != null then "In review"
      elif $wt != null then "In progress"
      elif ($labels | index("analyzed")) then "Ready"
      elif $awaiting != null then "Analysis"
      else "Backlog" end;

  {
    counts: {
      issues: ($issues | length),
      prs: ($prs | length),
      worktrees: ($worktrees | length),
      sessions: ($sessions | length)
    },
    items: [ $issues[] | . as $i
      | (label_names) as $labels
      | (pr_for(.number)) as $pr
      | (worktree_for(.number)) as $wt
      | (awaiting($labels; .comments)) as $aw
      | (column($labels; $pr; $wt; $aw)) as $col
      | {
          number: .number,
          title: .title,
          labels: $labels,
          author: .author.login,
          age_days: days_since(.createdAt),
          last_activity_days: days_since(.updatedAt),
          comments: (.comments | length),
          column: $col,
          awaiting: (if $col == "Analysis" then $aw else null end),
          priority: (
            [ $board.items[]? | select(.content.number? == $i.number) | .priority? ][0] // null
          ),
          pr: ($pr.number // null),
          pr_state: ($pr.mergeable // null),
          worktree: $wt,
          session: session_for(.number),
          blocked_by: blocked_by
        }
    ],
    orphans: (
      [ $worktrees[] | select(. as $w | ($issues | map("issue-\(.number)") | any(. as $s | $w | test($s))) | not)
        | {kind: "worktree_no_pr", ref: ., detail: "no open issue matches this worktree"} ]
      +
      [ $prs[] | select((.body // "") | test("(?i)(fixes|closes|resolves) #\\d+") | not)
        | {kind: "pr_no_issue", ref: (.number | tostring), detail: .title} ]
    )
  }
'
```

Then make it executable:

```bash
chmod +x scripts/backlog-digest.sh
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest backend/tests/test_backlog_digest.py -v
```

Expected: 5 passed. If `jq` reports a syntax error, the message names the
line — fix it in the script, not in the test.

- [ ] **Step 5: Run the digest against the real backlog**

```bash
./scripts/backlog-digest.sh | jq '.counts, (.items | length)'
```

Expected: `counts.issues` around 37 and `counts.worktrees` around 31. The
board query returns empty until Task 6 creates the board; that is correct, and
`priority` being `null` everywhere at this point is expected.

**Then verify the session key, which the script assumes but the shim cannot
prove.** `session_for` matches `.name == "issue-<n>"`; confirm that is the
actual field:

```bash
claude agents --json | jq '.[0] | keys'
```

If the display name lives under a different key (e.g. `title` or `sessionName`),
fix `session_for` in the script to match. Do not leave the assumption
untested — a wrong key silently reports every dispatched session as absent,
which reads as "the session died".

- [ ] **Step 6: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-digest.sh backend/tests/test_backlog_digest.py
git commit -m "feat: add backlog digest script for the Product Owner agent"
```

---

## Task 2: Role-aware `gh` identity

**Files:**
- Modify: `scripts/gh-agent.sh`
- Modify: `.github/workflows/pr-review.yml:17-19`
- Modify: `scripts/request-pr-review.sh:41`
- Modify: `CLAUDE.md` (the "General bot rules" section)
- Test: `backend/tests/test_gh_agent_roles.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `scripts/gh-agent.sh --as po|dev <gh args...>`, which runs `gh`
  with `GH_TOKEN` set from `BESS_PO_TOKEN` or `BESS_DEVELOPER_TOKEN`
  respectively. Invoked with no `--as`, it defaults to `dev` so existing
  callers keep working.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_gh_agent_roles.py`:

```python
"""Tests for scripts/gh-agent.sh role routing.

The script's whole job is choosing which token `gh` runs with, so the test
replaces `gh` with a shim that prints the token it was handed. That makes the
routing assertable without a network call or a real credential.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "gh-agent.sh"


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    shim = d / "gh"
    shim.write_text('#!/bin/sh\necho "token=$GH_TOKEN args=$*"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return d


def _run(bin_dir: Path, env_file: Path, args: list[str]) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        BESS_ENV_FILE=str(env_file),
    )
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env
    )


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    f = tmp_path / ".env"
    f.write_text("BESS_PO_TOKEN=po-secret\nBESS_DEVELOPER_TOKEN=dev-secret\n")
    return f


def test_po_role_uses_po_token(bin_dir: Path, env_file: Path) -> None:
    result = _run(bin_dir, env_file, ["--as", "po", "issue", "comment", "1"])
    assert "token=po-secret" in result.stdout
    assert "args=issue comment 1" in result.stdout


def test_dev_role_uses_developer_token(bin_dir: Path, env_file: Path) -> None:
    result = _run(bin_dir, env_file, ["--as", "dev", "pr", "comment", "2"])
    assert "token=dev-secret" in result.stdout


def test_default_role_is_dev(bin_dir: Path, env_file: Path) -> None:
    """Existing callers (request-pr-review.sh) pass no --as and must keep
    posting as the developer identity."""
    result = _run(bin_dir, env_file, ["pr", "comment", "3"])
    assert "token=dev-secret" in result.stdout


def test_unknown_role_fails_loudly(bin_dir: Path, env_file: Path) -> None:
    result = _run(bin_dir, env_file, ["--as", "reviewer", "pr", "list"])
    assert result.returncode != 0
    assert "reviewer" in result.stderr


def test_missing_token_fails_loudly(bin_dir: Path, tmp_path: Path) -> None:
    """No fallback: an absent token raises rather than silently posting as
    whoever `gh` happens to be authenticated as."""
    empty = tmp_path / "empty.env"
    empty.write_text("")
    result = _run(bin_dir, empty, ["--as", "po", "issue", "list"])
    assert result.returncode != 0
    assert "BESS_PO_TOKEN" in result.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest backend/tests/test_gh_agent_roles.py -v
```

Expected: all five FAIL — the script has no `--as` flag, so it treats `--as`
as a `gh` argument and the token assertions do not match.

- [ ] **Step 3: Read the current script before editing**

```bash
cat scripts/gh-agent.sh
```

Note how it resolves the main checkout's `.env` from a linked worktree. That
logic is preserved; only token selection changes, and `BESS_ENV_FILE` is added
as a test seam.

- [ ] **Step 4: Add role routing**

Edit `scripts/gh-agent.sh`. Replace the fixed `BESS_AGENT_TOKEN` lookup with:

```bash
# Role selection. Default `dev` keeps existing callers (request-pr-review.sh)
# posting as the developer identity, which is what pr-review.yml's gate expects.
role="dev"
if [ "${1:-}" = "--as" ]; then
  role="${2:?--as requires a role}"
  shift 2
fi

case "$role" in
  po)  token_var="BESS_PO_TOKEN" ;;
  dev) token_var="BESS_DEVELOPER_TOKEN" ;;
  *)   echo "gh-agent.sh: unknown role '$role' (expected po or dev)" >&2; exit 2 ;;
esac

env_file="${BESS_ENV_FILE:-$repo_root/.env}"
token=$(grep -E "^${token_var}=" "$env_file" 2>/dev/null | cut -d= -f2- || true)
if [ -z "$token" ]; then
  echo "gh-agent.sh: ${token_var} is not set in ${env_file}" >&2
  exit 1
fi

GH_TOKEN="$token" exec gh "$@"
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest backend/tests/test_gh_agent_roles.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Update the review gate to the renamed account**

In `.github/workflows/pr-review.yml`, change the actor gate:

```yaml
      (github.event.comment.user.login == github.repository_owner ||
       github.event.comment.user.login == 'bess-developer') &&
```

Update the comment block at the top of that file to say `bess-developer`
instead of `bess-agent`. Do the same in `scripts/request-pr-review.sh`'s
header comment.

- [ ] **Step 7: Update CLAUDE.md's identity rule**

In the "General bot rules" section, replace the `bess-agent` description with:

```markdown
- Automation writes carry a **role** identity, and role is the axis:
  `bess-product-owner` (intake, backlog, board, reporter comments),
  `bess-developer` (analyze, fix, PR authorship, requesting review),
  `bess-reviewer` (Stage 4 review only). Developer and Reviewer are
  deliberately distinct — Stage 4 reviews Stage 3's own output, and one shared
  face would read as an account approving its own PR. Post via
  `scripts/gh-agent.sh --as po|dev`. Genuine maintainer voice still uses plain
  `gh`.
```

- [ ] **Step 8: Verify the rename end-to-end**

```bash
scripts/gh-agent.sh --as po issue list --limit 1
scripts/gh-agent.sh --as dev issue list --limit 1
```

Expected: both succeed. If either reports a bad credential, the account or
`.env` entry from the maintainer prerequisites is missing — stop and say so
rather than falling back to plain `gh`.

- [ ] **Step 9: Commit**

```bash
./scripts/quality-check.sh
git add scripts/gh-agent.sh scripts/request-pr-review.sh \
        .github/workflows/pr-review.yml CLAUDE.md \
        backend/tests/test_gh_agent_roles.py
git commit -m "feat: role-aware gh identity for product owner and developer"
```

---

## Task 3: The Product Owner skill

**Files:**
- Create: `.claude/skills/backlog/SKILL.md`

**Interfaces:**
- Consumes: `scripts/backlog-digest.sh` JSON (Task 1),
  `scripts/gh-agent.sh --as po` (Task 2).
- Produces: the three verbs `triage`, `board`, `next`, which Task 4's agent
  file and Task 5's workflow both reference by name.

- [ ] **Step 1: Write the skill**

Create `.claude/skills/backlog/SKILL.md`. Follow the structure of
`.claude/skills/sweep-prs/SKILL.md` — frontmatter, Overview, When to Use,
then the procedure.

```markdown
---
name: backlog
description: Use when acting as the bess-manager Product Owner — reviewing the backlog, triaging or refining issues, reconciling the board, deciding what to work on next, or dispatching an implementation session.
---

# Backlog (Product Owner)

## Overview

You own the product backlog. You face the reporter, drive issues to a
Definition of Ready, order the work, and dispatch implementation — but you
never implement, and you never assign. Implementers pull the top of Ready.

Every pass starts from one command. Do not read issues one by one to build a
picture:

    ./scripts/backlog-digest.sh

Open an individual issue only when you are deciding about that issue.

## When to Use

- Reviewing or refining the backlog, triaging a report, chasing a reporter
- Reconciling the board, deciding what is next, dispatching work
- Under `/loop /backlog` as the unattended Rhythm surface

**Not** for implementing anything. That is `implement-issue`, in its own
session.

## State lives on GitHub, nowhere else

Never write a local file that mirrors board or issue state. Priority is a
board field, rationale is an issue comment, dedupe is close-as-duplicate,
blocked-by is a `Blocked by #N` line in the issue body.

Post as the PO identity: `scripts/gh-agent.sh --as po issue comment ...`.
If a board write fails for missing scope, stop and report
`gh auth refresh -s project`. Never fall back to a file.

## Definition of Ready

Nothing is dispatched that has not crossed this line. A bug is Ready when:

1. A debug log or bundle is attached
2. There is a reproduction, or enough real data to replay one
3. Expected versus actual behaviour is stated explicitly, in system terms
4. An approach is agreed (Stage 2 analysis, or the maintainer's say-so)
5. No unresolved blocker

An enhancement is Ready when 3–5 hold and the user-visible outcome is stated.
An item failing any criterion stays in Backlog or Analysis and becomes your
follow-up, not a developer's problem.

## Verb: triage

For each item the digest puts in Backlog or Analysis:

1. Apply missing labels. An open issue with comment activity and no labels is
   a real and common case — #592 and #593 are examples — and it is yours to
   fix.
2. Set the `Awaiting` field: `reporter`, `discussion`, `upstream`, `analysis`.
3. Flag likely duplicates by comparing titles and symptoms across the digest.
   Close as duplicate only when the overlap is unambiguous; otherwise comment
   and ask.
4. Promote real `TODO.md` items to issues; mark never-issues as such. TODO.md
   is an input to drain, not a store to sync.
5. Set `Priority` per the ranking policy below.

## Verb: board

Reconcile every card against the digest's derived `column`. **The digest
always wins** — never trust a card's current position. Act on each mismatch:

| Mismatch | Action |
|---|---|
| card *In progress*, no worktree, no PR | abandoned — move to *Ready*, report it |
| worktree present, no session, no PR | the session died mid-issue. Report it and offer to relaunch; the branch's commits survive. **Never silently relaunch** — a session that died twice is telling you something |
| PR `CONFLICTING` | hand to `sweep-prs` |
| worktree whose PR merged | prune via `sweep-prs` |
| issue closed, card not *Done* | move the card |
| *Analysis*/`reporter` quiet 14 days | nudge once; park to *Backlog* at 28 |
| *Analysis*/`discussion` quiet 14 days | summarise the thread, put the open question to the maintainer |
| open issue, comment activity, no labels | file into *Analysis*, assign a sub-state, apply labels |

Never auto-park an active conversation, and never chase a reporter for
something an upstream vendor owns.

## Verb: next

Rank Backlog and Ready items in this order:

1. **User-facing breakage** — `bug` opened by someone other than the
   maintainer. A wrong number on a real dashboard outranks everything.
2. **Roadmap direction** — advances a theme in
   `docs/agents/product-roadmap.md`, or moves an experimental platform toward
   stable.
3. **Cheap wins and batching** — prefer small and low-risk; group items
   touching the same subsystem.

Tiebreaker: release-blocking. Suppressed: `blocked`, anything awaiting a
reporter, duplicates.

Propose the top 1–3 with reasoning. Then stop and wait — dispatch needs the
maintainer's go-ahead.

## Dispatch

Only after approval, and only for an item that meets the Definition of Ready:

    claude --bg -n "issue-<n>" "/implement-issue <n>"

**Never create a worktree.** That session's Step 4 creates its own from a
fresh `origin/main`.

Serialise, do not stack:

- An item with an unmet `blocked_by` stays put. When the blocker's PR merges,
  drop `blocked`, move it to *Ready*, and dispatch fresh.
- Two items likely to touch the same file are queued, not run concurrently —
  the second would eat a merge conflict it did nothing to earn. Predict the
  touch-set from the Stage 2 analysis or the issue text. Warn and queue; this
  is not a hard block.

## Autonomous spend

Exactly one action costs money without asking: firing Stage 2
(`@claude-bot analyze`, ~$0.50–2) on an item entering Analysis that is a
user-facing bug, has its debug log, and ranks in the top priority tier. Every
other item entering Analysis gets a proposal instead.

## Close the loop

When a fix reaches a release, comment on the originating issue to tell the
reporter, as the PO identity.
```

- [ ] **Step 2: Verify the skill loads**

```bash
ls .claude/skills/backlog/SKILL.md
head -4 .claude/skills/backlog/SKILL.md
```

Expected: the frontmatter shows `name: backlog` and a description starting
"Use when acting as the bess-manager Product Owner".

- [ ] **Step 3: Dry-run the digest-first rule**

```bash
./scripts/backlog-digest.sh | jq '[.items[] | select(.column == "Analysis")] | length'
```

Expected: a number greater than zero, since #592 and #593 both derive to
Analysis. If it is zero, the sub-state rules in Task 1 are wrong — fix Task 1
rather than working around it here.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/backlog/SKILL.md
git commit -m "feat: add backlog skill encoding the Product Owner procedure"
```

---

## Task 4: The Product Owner agent

**Files:**
- Create: `.claude/agents/product-owner.md`
- Modify: `.claude/agents/bess-analyst.md` (add `color: cyan`)

**Interfaces:**
- Consumes: the `backlog` skill (Task 3).
- Produces: an agent invocable as `claude --agent product-owner`.

- [ ] **Step 1: Write the agent file**

Create `.claude/agents/product-owner.md`. Every frontmatter field below is
verified against the Claude Code subagent documentation; `color` accepts only
`red, blue, green, yellow, purple, orange, pink, cyan`.

```markdown
---
name: product-owner
description: The bess-manager Product Owner. Owns the backlog — intake, refinement to Definition of Ready, prioritisation, board reconciliation, and dispatching implementation sessions. Use when reviewing the backlog or deciding what to work on next.
color: purple
memory: project
skills: backlog, sweep-prs
initialPrompt: Run a backlog pass. Start with ./scripts/backlog-digest.sh, reconcile the board, then report what changed and propose what to work on next.
---

# Product Owner

You are the Product Owner for bess-manager, in the SCRUM sense. You own the
product backlog: you face the customer, get reports into a state a developer
can act on, order the backlog, and decide what is Ready.

You do not implement, and you do not assign. Implementers pull the top of the
Ready column. Your leverage is entirely in what reaches that column and in
what order.

Follow the `backlog` skill for every pass. Its Definition of Ready is the line
between your work and a developer's.

## Your duties, in the order a report travels

1. **Intake** — answer the reporter, ask for the debug log, classify.
2. **Readiness** — chase what is missing until the item meets the Definition
   of Ready. Nothing is handed to a developer before that line.
3. **Ordering** — dedupe, prioritise, hold a coherent roadmap.
4. **Flow** — keep the board honest, keep the PR fleet unblocked.
5. **Close the loop** — tell the reporter when their fix ships.

## Voice

You speak to real users, several of whom run this on real hardware. Be
concrete and brief. Ask for exactly the artefact you need and say why it
helps. Never speculate about a root cause in a reporter-facing comment — that
is the developer's job, after analysis.

Post as the PO identity: `scripts/gh-agent.sh --as po ...`.
```

- [ ] **Step 2: Add the analyst's colour**

Edit `.claude/agents/bess-analyst.md` frontmatter, adding one line after
`description:`:

```yaml
color: cyan
```

- [ ] **Step 3: Verify both agents parse**

```bash
claude agents --json >/dev/null && echo "agent config parses"
```

Expected: `agent config parses`. A YAML error here names the file and line.

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/product-owner.md .claude/agents/bess-analyst.md
git commit -m "feat: add product-owner agent, colour the analyst"
```

---

## Task 5: Stage 1 rewritten as PO intake

**Files:**
- Modify: `.github/workflows/issue-triage.yml`
- Modify: `CLAUDE.md` (the pipeline table)

**Interfaces:**
- Consumes: the Definition of Ready and Analysis sub-states (Task 3).
- Produces: intake comments posted as `bess-product-owner`.

**What must not change:** the `issues: opened/edited/reopened` trigger,
`allowed_non_write_users: "*"` (external reporters must be answered), and the
Haiku model. This runs on every issue edit; it stays cheap.

- [ ] **Step 1: Read the current workflow in full**

```bash
cat .github/workflows/issue-triage.yml
```

Note the existing four classification buckets and their labels — the rewrite
keeps the same labels so the board's derivation keeps working.

- [ ] **Step 2: Give the workflow the PO token**

In the `claude-code-action` step, replace the app-token `github_token` with
the PO identity:

```yaml
          github_token: ${{ secrets.BESS_PO_TOKEN }}
```

Delete the now-unused `create-github-app-token` step from this workflow only.
Leave it in place in `issue-analyze.yml`, `issue-fix.yml` and `pr-review.yml`.

- [ ] **Step 3: Rewrite the prompt as the PO persona**

Replace the prompt's opening line and add a duplicate-detection step:

```yaml
          prompt: |
            You are the **Product Owner** for johanzander/bess-manager, doing
            first-contact intake on issue #${{ github.event.issue.number || github.event.inputs.issue_number }}.

            Run first:
              gh issue view ${{ github.event.issue.number || github.event.inputs.issue_number }} --json title,body,labels,comments
              gh issue list --state open --limit 200 --json number,title,labels

            The second command is your backlog context. Use it to spot a
            likely duplicate — if one exists, say so in your comment and link
            it. Do not close anything; flagging is enough at this stage.

            Your job is to get this report to the point where a developer can
            act on it. A bug needs: a debug log, a reproduction, and an
            explicit statement of expected versus actual behaviour. Ask for
            exactly what is missing and say why it helps. Never speculate
            about a root cause — that comes after analysis.

            Classify into one of four buckets and act. Use
            `gh issue edit <n> --add-label <label>` for labels and
            `gh issue comment <n> -b "..."` for comments.
```

Keep the four existing bucket definitions and their labels verbatim below
this. Add one line to the bucket that currently sets `ready-for-analysis`:

```
              - If the report is a discussion about intended behaviour rather
                than a defect, label `question` instead and do not ask for a
                debug log.
```

- [ ] **Step 4: Update the pipeline table in CLAUDE.md**

Change the Stage 1 row to name the PO:

```markdown
| 1. Intake (PO) | `issues: opened/edited` (auto) | `issue-triage.yml` | ~$0.05 | Product Owner first contact: classify, label, request debug log, flag duplicates. Posts as `bess-product-owner`. |
```

- [ ] **Step 5: Verify the workflow is valid and fires**

```bash
gh workflow view issue-triage.yml
gh workflow run issue-triage.yml -f issue_number=592
sleep 30 && gh run list --workflow=issue-triage.yml --limit 1
```

Expected: the run completes successfully, and a comment appears on #592 from
`bess-product-owner`. #592 is a good probe precisely because it is an
unlabelled discussion — the rewritten prompt should label it `question`
rather than demand a debug log.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/issue-triage.yml CLAUDE.md
git commit -m "feat: rewrite Stage 1 triage as Product Owner intake"
```

---

## Task 6: Board bootstrap

**Files:**
- Create: `scripts/backlog-board-init.sh`

**Interfaces:**
- Consumes: `scripts/gh-agent.sh --as po` (Task 2).
- Produces: a GitHub Project v2 whose number the digest reads via
  `PROJECT_NUMBER`.

This task is idempotent by construction — re-running it must not create a
second board.

- [ ] **Step 1: Write the bootstrap script**

Create `scripts/backlog-board-init.sh`:

```bash
#!/usr/bin/env bash
#
# Create the Product Owner's kanban board, once. Idempotent: if a project with
# this title already exists, print its number and exit without touching it.
#
# Requires the PO token to carry `project` scope.
set -euo pipefail

owner="${PROJECT_OWNER:-johanzander}"
title="BESS Manager Backlog"

existing=$(scripts/gh-agent.sh --as po project list --owner "$owner" --format json \
  | jq -r --arg t "$title" '.projects[] | select(.title == $t) | .number')

if [ -n "$existing" ]; then
  echo "$existing"
  exit 0
fi

number=$(scripts/gh-agent.sh --as po project create --owner "$owner" --title "$title" \
  --format json | jq -r '.number')

# Status is created with default options; replace them with our columns.
scripts/gh-agent.sh --as po project field-create "$number" --owner "$owner" \
  --name "Priority" --data-type SINGLE_SELECT \
  --single-select-options "P0,P1,P2" >/dev/null

scripts/gh-agent.sh --as po project field-create "$number" --owner "$owner" \
  --name "Source" --data-type SINGLE_SELECT \
  --single-select-options "issue,TODO" >/dev/null

scripts/gh-agent.sh --as po project field-create "$number" --owner "$owner" \
  --name "Awaiting" --data-type SINGLE_SELECT \
  --single-select-options "reporter,discussion,upstream,analysis" >/dev/null

echo "$number"
```

```bash
chmod +x scripts/backlog-board-init.sh
```

- [ ] **Step 2: Run it**

```bash
./scripts/backlog-board-init.sh
```

Expected: a project number on stdout. If this fails with a scope error, the
PO token was created without `project` scope — regenerate it. Do not work
around it.

- [ ] **Step 3: Verify idempotency**

```bash
first=$(./scripts/backlog-board-init.sh)
second=$(./scripts/backlog-board-init.sh)
test "$first" = "$second" && echo "idempotent: $first"
```

Expected: `idempotent: <number>`, and exactly one project in
`gh project list`.

- [ ] **Step 4: Create the Status column options**

The default Status field ships with `Todo / In Progress / Done`. Rename and
extend it to the six columns through the web UI — `gh` cannot edit
single-select options on the built-in Status field:

`Backlog`, `Analysis`, `Ready`, `In progress`, `In review`, `Done`

- [ ] **Step 5: Point the digest at the board**

```bash
PROJECT_NUMBER=<number> ./scripts/backlog-digest.sh | jq '.items[0].priority'
```

Expected: `null` (no priorities set yet) rather than an error. An error here
means the board query in Task 1 is malformed.

- [ ] **Step 6: Commit**

```bash
./scripts/quality-check.sh
git add scripts/backlog-board-init.sh
git commit -m "feat: idempotent board bootstrap for the Product Owner"
```

---

## Task 7: The roadmap bootstrap

**Files:**
- Create: `docs/agents/product-roadmap.md`

**Interfaces:**
- Consumes: the digest (Task 1) and the ranking policy (Task 3).
- Produces: the file the skill's ranking axis 2 reads.

This is the one task whose output is a judgment, not code. It is a one-time
step: afterwards the file is read-only input that only the maintainer changes.

- [ ] **Step 1: Gather the material**

```bash
./scripts/backlog-digest.sh | jq -r '.items[] | "\(.number)\t\(.labels | join(","))\t\(.title)"'
grep -n '^#' TODO.md
```

- [ ] **Step 2: Draft the themes**

Write `docs/agents/product-roadmap.md` with 5–8 themes, each with a one-line
statement of the user-visible outcome, a rough order, and the issue and TODO
numbers that serve it. Use this structure:

```markdown
# Product Roadmap

Direction, not a task list. The Product Owner reads this to rank the backlog
and never edits it — changes here are the maintainer's alone. Per-item
priority lives on the board, not here.

## 1. <Theme name>

<One sentence: what a user can do afterwards that they cannot do now.>

Serves: #NNN, #NNN, TODO "<heading>"

## 2. ...
```

Do not invent direction. Every theme must be traceable to issues or TODO
headings that already exist; if a cluster of items has no coherent theme, say
so in the draft rather than inventing one.

- [ ] **Step 3: Hand the draft to the maintainer**

Present the draft and ask for edits. **Do not commit an unapproved roadmap** —
this file is the input to every future ranking decision, so an unreviewed one
silently steers the whole backlog.

- [ ] **Step 4: Commit the approved version**

```bash
git add docs/agents/product-roadmap.md
git commit -m "docs: add product roadmap themes guiding backlog ranking"
```

---

## Task 8: End-to-end verification

**Files:** none created; this task proves the whole thing works.

- [ ] **Step 1: Full digest against real state**

```bash
PROJECT_NUMBER=<number> ./scripts/backlog-digest.sh | jq '{counts, orphans}'
```

Expected: real counts, and an `orphans` list. With 31 worktrees live, expect
several `worktree_no_pr` entries — that is the fleet rot this design exists to
surface, not a bug.

- [ ] **Step 2: One triage pass**

```bash
claude --agent product-owner
```

Let it run its `initialPrompt` pass. Expected: it reads the digest first (not
individual issues), reports board mismatches, and proposes a next item with
reasoning. Confirm it did **not** write any local state file.

- [ ] **Step 3: Verify identity separation on a real issue**

Check that the intake comment on #592 shows `bess-product-owner` with its
avatar, and that a Stage 4 review comment shows `bess-reviewer` — two visibly
different actors.

- [ ] **Step 4: One dispatch, end to end**

Pick the smallest Ready item. Approve dispatch and confirm:

```bash
claude agents --json | jq '.[] | select(.name | startswith("issue-"))'
```

Expected: a background session named `issue-<n>`, in its own worktree that
**the PO did not create**. Let it reach a draft PR, then re-run the digest and
confirm the item derives to *In review*.

- [ ] **Step 5: Run the full test suite**

```bash
.venv/bin/pytest -m "not slow"
./scripts/quality-check.sh
```

Expected: green.

- [ ] **Step 6: Commit any fixes and open the PR**

```bash
git add -A && git commit -m "test: end-to-end verification of the Product Owner agent"
git push -u origin HEAD
gh pr create --draft --title "feat: Product Owner agent" \
  --body "Implements docs/superpowers/specs/2026-08-15-backlogger-agent-design.md"
```
