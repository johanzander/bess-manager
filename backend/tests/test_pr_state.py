"""Tests for scripts/pr-state.sh — the derived fleet-state read.

The decision under test is: given a PR's reviews, commits, mergeability and
checks, what state is it in and whose turn is it? That is the whole value of the
script, so it is what gets exercised. `gh` is shimmed on PATH; nothing here
touches GitHub.

The classification that motivated the script is `test_619_shape`: a PR that is
BOTH conflicted and carrying an unaddressed CHANGES_REQUESTED. Reporting only
the conflict — which an earlier ordering did — hides two blocking reviews behind
a mechanical merge.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "pr-state.sh"

GREEN = [{"name": "Fast tests", "status": "COMPLETED", "conclusion": "SUCCESS"}]


def _requested(at: str) -> dict:
    """The Stage 4 trigger comment, which is the only thing that starts a review."""
    return {"body": "@claude-bot review", "createdAt": at}


def _pr(
    number: int = 1,
    *,
    reviews: list | None = None,
    commits: list | None = None,
    comments: list | None = None,
    checks: list | None = None,
    mergeable: str = "MERGEABLE",
    merge_state: str = "CLEAN",
    draft: bool = True,
) -> dict:
    return {
        "number": number,
        "title": f"pr {number}",
        "isDraft": draft,
        "mergeable": mergeable,
        "mergeStateStatus": merge_state,
        "headRefName": f"branch-{number}",
        "updatedAt": "2026-08-01T00:00:00Z",
        "reviews": reviews or [],
        "commits": commits or [{"committedDate": "2026-08-02T00:00:00Z"}],
        # Default: a request AFTER the default push, so tests that are not about
        # the request feed land on the reviewer rather than the dispatcher.
        "comments": (
            comments if comments is not None else [_requested("2026-08-03T00:00:00Z")]
        ),
        "statusCheckRollup": GREEN if checks is None else checks,
    }


def _review(state: str, at: str) -> dict:
    return {"state": state, "submittedAt": at}


def _rows(out: str) -> str:
    """Just the classification rows.

    The script's closing note names `needs-fix` and `needs-refresh` while
    explaining that liveness is not guessed, so a negative assertion against the
    whole of stdout matches the explanation rather than a classification.
    """
    return out.split("Liveness (")[0]


@pytest.fixture
def run(tmp_path: Path):
    """Shim `gh pr list` with a fixture and return the script's stdout."""

    def _run(prs: list[dict]) -> str:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "prs.json").write_text(json.dumps(prs))
        gh = bin_dir / "gh"
        gh.write_text(f"""#!/bin/sh
# Faithful about the part under test: return the fixture for --json, and let the
# script's own jq do the classifying.
cat '{bin_dir}/prs.json'
""")
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        proc = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            env=dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}"),
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    return _run


def test_619_shape_reports_the_findings_not_just_the_conflict(run) -> None:
    """PR #619 as GitHub reported it: conflicted, CI green on a head that has
    not moved since 07:34, and two CHANGES_REQUESTED at 09:40 and 10:55.

    The blocking fact is the unaddressed findings — the conflict is mechanical
    and belongs to `sweep-prs`. An ordering that put the conflict first called
    this `needs-refresh` and lost both reviews.
    """
    out = run(
        [
            _pr(
                619,
                reviews=[
                    _review("COMMENTED", "2026-08-17T09:39:21Z"),
                    _review("CHANGES_REQUESTED", "2026-08-17T09:40:12Z"),
                    _review("CHANGES_REQUESTED", "2026-08-17T10:55:21Z"),
                ],
                commits=[{"committedDate": "2026-08-17T07:34:00Z"}],
                mergeable="CONFLICTING",
                merge_state="DIRTY",
            )
        ]
    )

    assert "needs-fix" in out
    assert "[executor]" in out
    assert "UNCONSUMED" in out
    # The conflict is still reported, as a flag rather than as the headline.
    assert "+conflicted" in out


def test_a_push_after_the_verdict_is_not_needs_fix(run) -> None:
    """The same verdict means the opposite thing once HEAD moves past it: the
    findings were acted on, so it is no longer the executor's turn."""
    out = run(
        [
            _pr(
                1,
                reviews=[_review("CHANGES_REQUESTED", "2026-08-01T00:00:00Z")],
                commits=[{"committedDate": "2026-08-02T00:00:00Z"}],
                comments=[_requested("2026-08-03T00:00:00Z")],
            )
        ]
    )

    assert "awaiting-review" in out
    assert "[reviewer]" in out
    assert "needs-fix" not in _rows(out)


def test_a_review_never_requested_is_the_dispatchers_turn_not_the_reviewers(
    run,
) -> None:
    """The Stage 4 bot only acts when triggered by an `@claude-bot review`
    comment, so "green with no verdict" has two completely different meanings
    and only one of them is the reviewer's.

    Measured on the live fleet: #637 and #635 had NEVER been asked, and #620,
    #619, #614 and #490 had all been pushed to after their last request. All six
    were being reported as `awaiting-review [reviewer]` — parked on someone who
    had not been asked and was never going to act. Six of eleven open PRs.
    """
    out = run([_pr(637, comments=[])])

    assert "needs-review-request" in out
    assert "[dispatcher]" in out
    assert "NEVER been requested" in out
    assert "[reviewer]" not in _rows(out)


def test_a_push_after_the_last_request_owes_a_new_round(run) -> None:
    """The subtler half of the same bug. A request exists, so the feed is not
    empty — but it predates the code, so the bot already returned its verdict on
    a diff that no longer exists. #620 requested at 17:40 and pushed at 18:33."""
    out = run(
        [
            _pr(
                620,
                commits=[{"committedDate": "2026-08-17T18:33:05Z"}],
                comments=[_requested("2026-08-17T17:40:53Z")],
            )
        ]
    )

    assert "needs-review-request" in out
    assert "[dispatcher]" in out
    assert "round owed" in out


def test_a_request_newer_than_the_push_really_is_the_reviewers_turn(run) -> None:
    """The gate must not label everything the dispatcher's job: once the request
    postdates the code, waiting on the bot is genuinely the correct state."""
    out = run(
        [
            _pr(
                3,
                commits=[{"committedDate": "2026-08-02T00:00:00Z"}],
                comments=[_requested("2026-08-04T00:00:00Z")],
            )
        ]
    )

    assert "awaiting-review" in out
    assert "[reviewer]" in out
    assert "needs-review-request" not in _rows(out)


def test_approved_and_still_draft_is_the_maintainers_turn(run) -> None:
    """#615 sat in this state overnight with only the merge left to do. It is
    nobody's bug and nobody's review — it is a flag someone has to flip."""
    out = run(
        [
            _pr(
                2,
                reviews=[_review("APPROVED", "2026-08-03T00:00:00Z")],
                commits=[{"committedDate": "2026-08-02T00:00:00Z"}],
            )
        ]
    )

    assert "awaiting-ready" in out
    assert "[maintainer]" in out


def test_a_commented_placeholder_is_not_a_verdict(run) -> None:
    """The bot posts permission-check and inline-note reviews as COMMENTED.
    Counting those as verdicts is how #615 was misread; this classifier looks
    only at APPROVED/CHANGES_REQUESTED."""
    out = run(
        [
            _pr(
                7,
                reviews=[_review("COMMENTED", "2026-08-09T00:00:00Z")],
                commits=[{"committedDate": "2026-08-02T00:00:00Z"}],
            )
        ]
    )

    assert "not returned a verdict yet" in out
    assert "UNCONSUMED" not in out


def test_a_conflict_outranks_ci_because_a_conflicted_pr_has_no_run(run) -> None:
    """`sweep-prs` found two PRs sitting conflicted with nobody aware, because a
    CONFLICTING PR creates no workflow run at all and so presents as "CI never
    fired". An empty check list must not read as green."""
    out = run([_pr(5, mergeable="CONFLICTING", merge_state="DIRTY", checks=[])])

    assert "needs-refresh" in out
    assert "[sweep]" in out


def test_unknown_mergeability_is_never_reported_as_clean(run) -> None:
    """`mergeable` is computed LAZILY: the first query on a cold PR returns
    UNKNOWN and only then triggers the computation.

    This was measured, not theorised. A first live fleet run classified #167 and
    #619 with no conflict flag; once earlier queries had warmed them, the
    identical command returned `needs-refresh` for both. They were CONFLICTING
    throughout. Treating UNKNOWN as "not conflicted" therefore hides exactly the
    stale PRs this script exists to surface — the same trap `sweep-prs`
    documents and retries for.

    The script retries while anything is UNKNOWN. This pins the fallback: if it
    still is, say so rather than falling through to the clean branch.
    """
    out = run([_pr(9, mergeable="UNKNOWN", merge_state="UNKNOWN")])

    assert "UNKNOWN" in _rows(out)
    assert "re-run" in _rows(out)


def test_red_ci_belongs_to_the_executor(run) -> None:
    out = run(
        [
            _pr(
                3,
                checks=[
                    {
                        "name": "Algorithm tests",
                        "status": "COMPLETED",
                        "conclusion": "FAILURE",
                    }
                ],
            )
        ]
    )

    assert "needs-fix" in out
    assert "Algorithm tests" in out


def test_running_ci_is_nobodys_turn(run) -> None:
    """Distinct from needs-fix: there is nothing to do but wait, and a state
    read that says "act" here produces churn."""
    out = run(
        [_pr(4, checks=[{"name": "E2E", "status": "IN_PROGRESS", "conclusion": None}])]
    )

    assert "in-flight" in out


def test_liveness_is_reported_as_unknown_rather_than_guessed(run) -> None:
    """The whole point. A fresh session previously answered "is anyone working
    on this" from `git worktree list` and `claude agents --json` — local signals
    that see nothing when the executor is a container or a GitHub Action, and
    that reported #619's REVIEWER timestamp as the agent's last activity.
    """
    out = run([_pr(1)])

    assert "not a GitHub fact and is not" in out
    assert "guessed here" in out
