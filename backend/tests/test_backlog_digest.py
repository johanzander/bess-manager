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
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env
    )
    # `check=True` raised a CalledProcessError whose message carries only the
    # exit status, so a jq failure inside the digest surfaced as a bare
    # "returned non-zero exit status 5" with the actual error swallowed. The
    # digest writes its diagnostics to stderr; a test harness that hides them
    # makes every failure a guessing game.
    if proc.returncode != 0:
        raise AssertionError(
            f"backlog-digest.sh exited {proc.returncode}\n"
            f"--- stderr ---\n{proc.stderr}\n--- stdout ---\n{proc.stdout[:2000]}"
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


def _gh_shim(
    issues: list,
    prs: list,
    project_items: list,
    merged_prs: list | None = None,
) -> str:
    """A `gh` that answers the four subcommands the digest calls.

    `pr list` is called twice with different `--state` values, so this shim
    branches on the whole argument string rather than just `$1 $2`. Matching
    only the subcommand returned the OPEN list for both calls, which made every
    open PR look merged and reported every issue as having landed.
    """
    return f"""
merged=$(cat <<'EOF'
{json.dumps(merged_prs or [])}
EOF
)
case "$*" in
  *"issue list"*) cat <<'EOF'
{json.dumps(issues)}
EOF
    ;;
  *"pr list"*"--state merged"*) printf '%s\\n' "$merged" ;;
  *"pr list"*) cat <<'EOF'
{json.dumps(prs)}
EOF
    ;;
  *"project item-list"*) cat <<'EOF'
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


def _issue(number: int, **over: object) -> dict:
    """An issue as `gh issue list --json ...` really returns it.

    Every field the digest reads is present, `createdAt` on comments included —
    real gh always sends it, and fixtures that omitted it made `days_since`
    fail with "strptime/1 requires string inputs" rather than exercising
    anything.
    """
    issue: dict = {
        "number": number,
        "title": f"issue {number}",
        "labels": [],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-14T00:00:00Z",
        "comments": [],
        "body": "",
    }
    issue.update(over)
    return issue


def _comment(login: str, body: str = "...", at: str = "2026-08-10T00:00:00Z") -> dict:
    return {"body": body, "author": {"login": login}, "createdAt": at}


def test_human_comment_alone_does_not_move_the_column(bin_dir: Path) -> None:
    """A human comment is NOT a blocker, and used to be treated as one.

    `awaiting: discussion` was returned whenever any human comment existed,
    which pushed an item to Analysis for ordinary traffic — reporter thanks, a
    follow-up question, a "me too". Only a genuine wait belongs in Analysis;
    who spoke last is reported separately so the PO can judge.
    """
    issue = _issue(592, labels=[], comments=[_comment("areader", "what is idle?")])
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)
    item = digest["items"][0]

    assert item["column"] == "Backlog"
    assert item["awaiting"] is None
    # ...but the comment is still visible, which is the point.
    assert item["last_comment"]["author"] == "areader"
    assert item["last_comment"]["is_bot"] is False


def test_bot_comment_is_marked_as_bot(bin_dir: Path) -> None:
    """Stage 1 triage comments on every issue it processes, so a bot comment
    must never read as a human signal."""
    issue = _issue(612, comments=[_comment("bess-manager-claude-bot", "Triaged.")])
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)
    item = digest["items"][0]

    assert item["column"] == "Backlog"
    assert item["awaiting"] is None
    assert item["last_comment"]["is_bot"] is True
    assert item["last_comment"]["is_reporter"] is False


def test_reporter_reply_is_identifiable(bin_dir: Path) -> None:
    """The transition the digest could not previously represent.

    #621 crossed the Definition of Ready line when its reporter attached a
    debug bundle. A comment COUNT and a last-activity DATE cannot distinguish
    that from a nudge we posted ourselves, so the follow-up chase had nothing
    to select on.
    """
    issue = _issue(
        621,
        author={"login": "valexi7"},
        labels=[{"name": "bug"}],
        comments=[
            _comment(
                "bess-product-owner", "please attach a bundle", "2026-08-09T00:00:00Z"
            ),
            _comment("valexi7", "here is the export", "2026-08-12T00:00:00Z"),
        ],
    )
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)
    last = digest["items"][0]["last_comment"]

    assert last["author"] == "valexi7"
    assert last["is_reporter"] is True
    assert last["is_bot"] is False


def test_board_awaiting_overrides_analyzed(bin_dir: Path) -> None:
    """#96, exactly: labelled `analyzed`, prioritised, no blocking label — and
    still not implementable, because its approach was undecided. It reported
    Ready, an implementation session was dispatched at it, and that session
    deadlocked on three design questions it had no way to answer.

    A wait recorded on the board must outrank `analyzed`.
    """
    issue = _issue(96, labels=[{"name": "analyzed"}])
    board = [{"content": {"number": 96}, "priority": "P2", "awaiting": "discussion"}]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], board))

    digest = _run(bin_dir)
    item = digest["items"][0]

    assert item["column"] == "Analysis"
    assert item["awaiting"] == "discussion"
    assert item["awaiting_source"] == "board"


def test_analyzed_with_priority_is_ready_for_dev(bin_dir: Path) -> None:
    issue = _issue(700, labels=[{"name": "analyzed"}])
    board = [{"content": {"number": 700}, "priority": "P1"}]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], board))

    assert _run(bin_dir)["items"][0]["column"] == "Ready for Dev"


def test_analyzed_without_priority_is_not_ready(bin_dir: Path) -> None:
    """The design always required a Priority for Ready. The condition was left
    out because no board existed, and never added once one did."""
    issue = _issue(701, labels=[{"name": "analyzed"}])
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    assert _run(bin_dir)["items"][0]["column"] == "Analysis"


def test_blocked_label_is_never_ready(bin_dir: Path) -> None:
    """Definition of Ready criterion 5. #571 reported `Ready for Dev` while
    carrying the `blocked` label."""
    issue = _issue(571, labels=[{"name": "analyzed"}, {"name": "blocked"}])
    board = [{"content": {"number": 571}, "priority": "P2"}]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], board))

    item = _run(bin_dir)["items"][0]
    assert item["column"] == "Analysis"
    assert item["blocked"] is True


def test_blocked_by_reference_is_never_ready(bin_dir: Path) -> None:
    issue = _issue(702, labels=[{"name": "analyzed"}], body="Blocked by #500\n")
    board = [{"content": {"number": 702}, "priority": "P1"}]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], board))

    item = _run(bin_dir)["items"][0]
    assert item["column"] == "Analysis"
    assert item["blocked_by"] == [500]


def test_worktree_whose_branch_merged_is_not_in_progress(bin_dir: Path) -> None:
    """#593, #571, #542 and #466 all reported In Progress while their PRs had
    already merged, because an un-pruned worktree was treated as live work."""
    issue = _issue(593, labels=[{"name": "bug"}])
    merged = [
        {"number": 618, "headRefName": "fix/issue-593-vpp-write-order", "body": ""}
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(_porcelain(("/repo/wt/593", "fix/issue-593-vpp-write-order"))),
    )

    item = _run(bin_dir)["items"][0]

    assert item["stale_worktree"] is True
    assert item["column"] != "In Progress"
    assert item["column"] == "Backlog"


def test_worktree_on_an_unmerged_branch_is_in_progress(bin_dir: Path) -> None:
    """The other half: a live worktree must still read as In Progress, or the
    stale-detection fix would hide real work."""
    issue = _issue(594, labels=[{"name": "bug"}])
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], []))
    _write_shim(
        bin_dir, "git", _git_shim(_porcelain(("/repo/wt/594", "fix/issue-594-live")))
    )

    item = _run(bin_dir)["items"][0]

    assert item["stale_worktree"] is False
    assert item["column"] == "In Progress"


def test_merged_pr_does_not_close_an_open_issue(bin_dir: Path) -> None:
    """A merged PR that closes an issue must NOT be read as Done while the
    issue is open. This project's beta PRs deliberately omit `Closes #N` until
    the fix graduates, so an open issue with a merged fix is the normal state —
    treating it as finished reclassified 7 live issues, #118 and #403 included.
    """
    issue = _issue(118, labels=[{"name": "bug"}])
    merged = [{"number": 504, "headRefName": "fix/whatever", "body": "fixes #118"}]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))

    item = _run(bin_dir)["items"][0]

    assert item["merged_pr"] == 504
    assert item["column"] != "Done"


def test_needs_debug_log_is_awaiting_reporter(bin_dir: Path) -> None:
    issue = {
        "number": 603,
        "title": "Savings look wrong",
        "labels": [{"name": "bug"}, {"name": "needs-debug-log"}],
        "author": {"login": "reporter"},
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "comments": [_comment("owner", "please attach a debug bundle")],
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
