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


def _run(bin_dir: Path, **extra_env: str) -> dict:
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        PROJECT_NUMBER=extra_env.pop("PROJECT_NUMBER", "1"),
        **extra_env,
    )
    proc = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=True
    )
    # Typed intermediate: json.loads returns Any, and warn_return_any is on.
    digest: dict = json.loads(proc.stdout)
    return digest


def _run_expect_failure(bin_dir: Path, **extra_env: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", **extra_env)
    env.pop("PROJECT_NUMBER", None)
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env
    )


def _porcelain(*worktrees: tuple[str, str | None]) -> str:
    """Build `git worktree list --porcelain` output for a main checkout
    followed by the given (path, branch) pairs. branch=None means detached."""
    records = [
        "worktree /repo\nHEAD 0000000000000000000000000000000000000\nbranch refs/heads/main"
    ]
    for path, branch in worktrees:
        lines = [f"worktree {path}", "HEAD 1111111111111111111111111111111111111"]
        lines.append(f"branch refs/heads/{branch}" if branch else "detached")
        records.append("\n".join(lines))
    return "\n\n".join(records) + "\n"


def _git_shim(porcelain: str) -> str:
    escaped = porcelain.replace("'", "'\\''")
    return f"""
case "$1 $2 $3" in
  "worktree list --porcelain") printf '%s' '{escaped}' ;;
  *) echo "unexpected git call: $*" >&2; exit 1 ;;
esac
"""


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    _write_shim(d, "claude", 'echo "[]"')
    _write_shim(d, "git", _git_shim(_porcelain()))
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
        "comments": [
            {"body": "what do you mean by idle?", "author": {"login": "areader"}}
        ],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)

    assert digest["items"][0]["column"] == "Analysis"
    assert digest["items"][0]["awaiting"] == "discussion"


def test_bot_only_comment_does_not_trigger_discussion(bin_dir: Path) -> None:
    """Stage 1 triage (issue-triage.yml) posts a comment on every issue it
    processes. A bot comment alone must not read as human discussion, or the
    heuristic degenerates to 'everything is a discussion' once triage runs
    on every issue."""
    issue = {
        "number": 612,
        "title": "Only ever touched by triage",
        "labels": [],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-14T00:00:00Z",
        "comments": [
            {
                "body": "Triaged as bug, needs-debug-log.",
                "author": {"login": "bess-manager-claude-bot"},
            }
        ],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)

    assert digest["items"][0]["column"] == "Backlog"
    assert digest["items"][0]["awaiting"] is None


def test_human_comment_still_triggers_discussion(bin_dir: Path) -> None:
    issue = {
        "number": 613,
        "title": "A real human weighed in",
        "labels": [],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-14T00:00:00Z",
        "comments": [
            {
                "body": "I think this is actually two bugs.",
                "author": {"login": "areader"},
            }
        ],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)

    assert digest["items"][0]["column"] == "Analysis"
    assert digest["items"][0]["awaiting"] == "discussion"


def test_bot_and_human_comment_still_triggers_discussion(bin_dir: Path) -> None:
    issue = {
        "number": 614,
        "title": "Triaged, then a human replied",
        "labels": [],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-14T00:00:00Z",
        "comments": [
            {"body": "Triaged as bug.", "author": {"login": "bess-manager-claude-bot"}},
            {
                "body": "Actually I can't reproduce this.",
                "author": {"login": "areader"},
            },
        ],
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
    assert item["column"] == "In Review"


def test_issue_matched_by_two_prs_emits_one_item_with_a_scalar_pr(
    bin_dir: Path,
) -> None:
    """Regression test for a real bug found while implementing this script:
    the first-draft jq used `select(...) // null` to pick "the" PR for an
    issue. In jq, `EXPR // null` only substitutes `null` when EXPR produces
    *no* output — with one match it returns that match, but with two or more
    matches `select(...)` is a stream and the whole expression becomes a
    stream of PR objects rather than a single scalar. Downstream that stream
    gets cross-multiplied into the `items[]` comprehension, silently emitting
    one duplicate item row per extra match instead of picking a single PR
    deterministically. This issue has two open PRs that both match it (one by
    `Fixes #N` in the body, one by headRefName pattern), which triggers the
    bug if `pr_for` regresses back to the `// null` idiom."""
    issue = {
        "number": 606,
        "title": "Two competing fix attempts",
        "labels": [{"name": "bug"}, {"name": "has-fix-pr"}],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-10T00:00:00Z",
        "comments": [],
        "body": "",
    }
    pr_a = {
        "number": 620,
        "title": "fix: attempt A",
        "headRefName": "fix/issue-606-a",
        "mergeable": "MERGEABLE",
        "body": "Fixes #606",
    }
    pr_b = {
        "number": 621,
        "title": "fix: attempt B",
        "headRefName": "fix/issue-606-b",
        "mergeable": "MERGEABLE",
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [pr_a, pr_b], []))

    digest = _run(bin_dir)

    assert len(digest["items"]) == 1, (
        "an issue matched by two PRs must still emit exactly one item row, "
        f"got {len(digest['items'])}"
    )
    item = digest["items"][0]
    assert item["number"] == 606
    assert isinstance(item["pr"], int), (
        "pr must be a single scalar issue number, not a list — " f"got {item['pr']!r}"
    )
    assert item["pr"] == 620


def test_worktree_branch_without_issue_prefix_joins_by_delimited_number(
    bin_dir: Path,
) -> None:
    """Real fleet shape: `fix-542-signed-power-display` has no `issue-`
    substring at all, and the issue number lives only in the branch, not the
    path. The join must match on branch as well as path, at a delimited
    position (not merely 'contains the digits')."""
    issue = {
        "number": 542,
        "title": "Signed power display",
        "labels": [{"name": "bug"}],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-01T00:00:00Z",
        "comments": [],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(_porcelain(("/repo/worktrees/wt1", "fix-542-signed-power-display"))),
    )

    digest = _run(bin_dir)

    item = digest["items"][0]
    assert item["column"] == "In Progress"
    assert item["worktree"] == "/repo/worktrees/wt1"


def test_worktree_with_no_matching_issue_is_an_orphan(bin_dir: Path) -> None:
    issue = {
        "number": 999,
        "title": "Unrelated issue",
        "labels": [],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-01T00:00:00Z",
        "comments": [],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(_porcelain(("/repo/worktrees/bench", "bench-pwl-everywhere"))),
    )

    digest = _run(bin_dir)

    orphans = [o for o in digest["orphans"] if o["kind"] == "worktree_no_issue"]
    assert len(orphans) == 1
    assert orphans[0]["ref"] == "/repo/worktrees/bench"
    assert orphans[0]["detail"] == "no open issue matches this worktree"


def test_main_checkout_is_never_reported_as_an_orphan(bin_dir: Path) -> None:
    """The main checkout is always `git worktree list`'s first record and is
    an orphan by construction (its branch is 'main', matching no issue) — it
    must be excluded from the orphan scan entirely."""
    _write_shim(bin_dir, "gh", _gh_shim([], [], []))
    # Default bin_dir git shim already emits only the main checkout.

    digest = _run(bin_dir)

    assert digest["orphans"] == []


def test_worktree_matched_only_by_similar_number_is_not_joined(bin_dir: Path) -> None:
    """15420 must not join to issue 542 — the boundary check must reject a
    non-delimited digit run."""
    issue = {
        "number": 542,
        "title": "Signed power display",
        "labels": [{"name": "bug"}],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-01T00:00:00Z",
        "comments": [],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(_porcelain(("/repo/worktrees/wt2", "fix-15420-something"))),
    )

    digest = _run(bin_dir)

    assert digest["items"][0]["column"] != "In Progress"
    assert digest["items"][0]["worktree"] is None


def test_pr_joined_only_by_headref_is_not_an_orphan(bin_dir: Path) -> None:
    """The `pr_no_issue` orphan check must be the exact negation of the
    issue<->PR join (`pr_for`), which matches on EITHER a body reference OR
    `headRefName`. A PR joined purely by branch name (no fixes/closes/resolves
    phrase in the body) must NOT be reported as an orphan.

    Every other PR fixture in this suite includes a fixes/closes/resolves
    phrase in its body, which is why this false positive wasn't caught
    earlier: the orphan check used to test only the body."""
    issue = {
        "number": 607,
        "title": "Joined by branch name only",
        "labels": [{"name": "bug"}],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-01T00:00:00Z",
        "comments": [],
        "body": "",
    }
    pr = {
        "number": 630,
        "title": "fix: joined by branch only",
        "headRefName": "fix/issue-607-branch-only",
        "mergeable": "MERGEABLE",
        "body": "No magic phrase here, just a description.",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [pr], []))

    digest = _run(bin_dir)

    item = digest["items"][0]
    assert item["pr"] == 630, "PR must still join the issue via headRefName"
    pr_orphans = [o for o in digest["orphans"] if o["kind"] == "pr_no_issue"]
    assert pr_orphans == [], (
        "a PR joined to an open issue by headRefName must not be reported as "
        f"pr_no_issue, got {pr_orphans!r}"
    )


def test_board_priority_is_joined_onto_matching_issue(bin_dir: Path) -> None:
    issue = {
        "number": 608,
        "title": "Has a board entry",
        "labels": [],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-01T00:00:00Z",
        "comments": [],
        "body": "",
    }
    project_item = {"content": {"number": 608}, "priority": "P1"}
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [project_item]))

    digest = _run(bin_dir)

    assert digest["items"][0]["priority"] == "P1"


def test_issue_with_no_board_entry_has_null_priority(bin_dir: Path) -> None:
    issue = {
        "number": 609,
        "title": "No board entry",
        "labels": [],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-01T00:00:00Z",
        "comments": [],
        "body": "",
    }
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)

    assert digest["items"][0]["priority"] is None


def test_board_entry_for_unknown_issue_does_not_spurious_or_crash(
    bin_dir: Path,
) -> None:
    """A board entry referencing an issue number that isn't in the open-issue
    list (e.g. a closed issue still on the board) must be ignored, not
    produce a spurious item or crash the join."""
    issue = {
        "number": 611,
        "title": "The only real open issue",
        "labels": [],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-01T00:00:00Z",
        "comments": [],
        "body": "",
    }
    project_item = {"content": {"number": 9999}, "priority": "P2"}
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [project_item]))

    digest = _run(bin_dir)

    assert len(digest["items"]) == 1
    assert digest["items"][0]["number"] == 611
    assert digest["items"][0]["priority"] is None


def test_missing_project_number_fails_loudly(bin_dir: Path) -> None:
    """No fallback: PROJECT_NUMBER must be required, not defaulted to 1 and
    silently masked by a swallowed `gh` error."""
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

    result = _run_expect_failure(bin_dir)

    assert result.returncode != 0
    assert "PROJECT_NUMBER" in result.stderr
