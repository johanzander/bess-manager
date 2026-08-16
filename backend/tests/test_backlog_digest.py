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
