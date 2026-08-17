"""Tests for scripts/backlog-rhythm.sh — the Product Owner's "what is due now" pass.

Every rule in `.claude/skills/backlog` had been written down and none had ever
fired, because noticing them required a model and nothing scheduled one. The
noticing now lives in this script as pure comparisons over the digest, so it
can run on a timer for the cost of a process. These tests pin the comparisons.

`RHYTHM_DIGEST_FILE` / `RHYTHM_PRS_FILE` are the script's test seams (the same
shape as `BESS_ENV_FILE` in gh-agent.sh), so no network or live board is needed.
"""

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "backlog-rhythm.sh"


def _item(number: int, **over: object) -> dict:
    """A digest item with every field the rhythm rules read."""
    item: dict = {
        "number": number,
        "title": f"issue {number}",
        "labels": ["bug"],
        "author": "reporter",
        "age_days": 30,
        "last_activity_days": 1,
        "comments": 0,
        "column": "Backlog",
        "awaiting": None,
        "awaiting_source": None,
        "awaiting_suggested": None,
        "last_comment": None,
        "priority": "P2",
        "pr": None,
        "pr_state": None,
        "merged_pr": None,
        "worktree": None,
        "worktree_branch": None,
        "stale_worktree": False,
        "session": None,
        "blocked_by": [],
        "blocked_by_open": [],
        "blocked": False,
    }
    item.update(over)
    return item


def _comment(days: int, *, is_reporter: bool = False, is_bot: bool = False) -> dict:
    return {
        "author": "someone",
        "days": days,
        "is_reporter": is_reporter,
        "is_bot": is_bot,
    }


def _run(tmp_path: Path, items: list, prs: list | None = None, **env: str) -> dict:
    digest = tmp_path / "digest.json"
    digest.write_text(json.dumps({"counts": {}, "items": items, "orphans": []}))
    prs_file = tmp_path / "prs.json"
    prs_file.write_text(json.dumps(prs or []))

    proc = subprocess.run(
        ["bash", str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "RHYTHM_DIGEST_FILE": str(digest),
            "RHYTHM_PRS_FILE": str(prs_file),
            **env,
        },
    )
    if proc.returncode != 0:
        raise AssertionError(f"exited {proc.returncode}\nstderr:\n{proc.stderr}")
    result: dict = json.loads(proc.stdout)
    return result


def _actions_for(result: dict, number: int) -> set[str]:
    return {
        a["action"]
        for a in result["actions"]
        if a.get("issue") == number or a.get("pr") == number
    }


def test_quiet_backlog_is_a_noop(tmp_path: Path) -> None:
    """A quiet fleet must cost nothing to observe, or the loop is not worth
    running on a timer."""
    result = _run(tmp_path, [_item(1, labels=["bug"], last_comment=_comment(1))])
    assert result["due"] == 0
    assert result["actions"] == []


def test_reporter_reply_beats_the_chase(tmp_path: Path) -> None:
    """The worst output this pass could produce is nudging someone who has
    already answered. A reply must win over the quiet-time chase, even when the
    issue is well past the nudge threshold."""
    item = _item(
        621,
        labels=["bug"],
        awaiting="reporter",
        last_comment=_comment(20, is_reporter=True),
    )
    actions = _actions_for(_run(tmp_path, [item]), 621)

    assert "recheck_ready" in actions
    assert "nudge_reporter" not in actions
    assert "park" not in actions


def test_nudge_at_threshold_then_park(tmp_path: Path) -> None:
    ours = _comment(14)  # last word was ours, so the ball is with them
    nudge = _actions_for(
        _run(
            tmp_path, [_item(2, labels=["b"], awaiting="reporter", last_comment=ours)]
        ),
        2,
    )
    assert "nudge_reporter" in nudge and "park" not in nudge

    parked = _actions_for(
        _run(
            tmp_path,
            [_item(3, labels=["b"], awaiting="reporter", last_comment=_comment(28))],
        ),
        3,
    )
    assert "park" in parked and "nudge_reporter" not in parked


def test_below_threshold_does_not_chase(tmp_path: Path) -> None:
    item = _item(4, labels=["b"], awaiting="reporter", last_comment=_comment(13))
    assert _actions_for(_run(tmp_path, [item]), 4) == set()


def test_quiet_time_is_measured_from_the_last_comment(tmp_path: Path) -> None:
    """Not from updatedAt. A label change, a board move or a bot touch all bump
    updatedAt, so an issue nobody has spoken on for a month can look active and
    never age into a chase."""
    item = _item(
        5,
        labels=["b"],
        awaiting="reporter",
        last_activity_days=0,  # something touched it today...
        last_comment=_comment(40),  # ...but nobody has spoken in 40 days
    )
    assert "park" in _actions_for(_run(tmp_path, [item]), 5)


def test_stalled_discussion_is_surfaced_never_parked(tmp_path: Path) -> None:
    """An open conversation is not an unanswered chase."""
    item = _item(6, labels=["b"], awaiting="discussion", last_comment=_comment(40))
    actions = _actions_for(_run(tmp_path, [item]), 6)
    assert "surface_discussion" in actions
    assert "park" not in actions


def test_label_derived_awaiting_asks_for_the_board_field(tmp_path: Path) -> None:
    item = _item(
        7,
        labels=["needs-debug-log"],
        awaiting="reporter",
        awaiting_source="label",
        awaiting_suggested="reporter",
        last_comment=_comment(1),
    )
    assert "set_awaiting" in _actions_for(_run(tmp_path, [item]), 7)


def test_missing_priority_and_missing_labels_are_grooming_debt(tmp_path: Path) -> None:
    item = _item(8, labels=[], priority=None, last_comment=_comment(1))
    actions = _actions_for(_run(tmp_path, [item]), 8)
    assert {"set_priority", "triage_labels"} <= actions


def test_stale_worktree_is_handed_to_sweep_prs(tmp_path: Path) -> None:
    item = _item(
        9,
        labels=["b"],
        stale_worktree=True,
        worktree_branch="fix/issue-9",
        last_comment=_comment(1),
    )
    assert "prune_worktree" in _actions_for(_run(tmp_path, [item]), 9)


def test_ready_for_dev_is_reported_as_dispatchable(tmp_path: Path) -> None:
    item = _item(
        10, labels=["analyzed"], column="Ready for Dev", last_comment=_comment(1)
    )
    assert "dispatchable" in _actions_for(_run(tmp_path, [item]), 10)


# --- the PR half: reaching a READY PR ------------------------------------


def _pr(number: int, **over: object) -> dict:
    pr: dict = {
        "number": number,
        "title": f"pr {number}",
        "isDraft": True,
        "mergeable": "MERGEABLE",
        "reviewDecision": None,
        "reviews": [],
        "author": {"login": "johanzander"},
    }
    pr.update(over)
    return pr


def test_approved_draft_is_flagged_to_mark_ready(tmp_path: Path) -> None:
    """The step that actually hands the maintainer something to approve.

    #615 was APPROVED and still a draft overnight; #617 the same. Nothing was
    watching for this transition, which is the entire point of the loop.
    """
    pr = _pr(615, isDraft=True, reviews=[{"state": "APPROVED"}])
    actions = _actions_for(_run(tmp_path, [], [pr]), 615)
    assert actions == {"mark_ready"}


def test_approved_non_draft_is_the_maintainers(tmp_path: Path) -> None:
    pr = _pr(490, isDraft=False, reviews=[{"state": "APPROVED"}])
    assert "awaiting_maintainer" in _actions_for(_run(tmp_path, [], [pr]), 490)


def test_draft_with_no_review_asks_for_one(tmp_path: Path) -> None:
    """A draft cannot become ready without a review, and #619 sat unreviewed."""
    assert "request_review" in _actions_for(_run(tmp_path, [], [_pr(619)]), 619)


def test_changes_requested_becomes_rework(tmp_path: Path) -> None:
    pr = _pr(614, reviews=[{"state": "APPROVED"}, {"state": "CHANGES_REQUESTED"}])
    assert "rework" in _actions_for(_run(tmp_path, [], [pr]), 614)


def test_a_bare_commented_review_does_not_count_as_a_verdict(tmp_path: Path) -> None:
    """The review bot posts its inline notes as a COMMENTED review before the
    summary, so COMMENTED alone decides nothing — the PR still needs a review.
    Treating it as a verdict is how an approved PR stayed a draft.
    """
    pr = _pr(623, reviews=[{"state": "COMMENTED"}])
    actions = _actions_for(_run(tmp_path, [], [pr]), 623)
    assert "mark_ready" not in actions
    assert "rework" not in actions


def test_conflicting_pr_is_flagged_over_its_review_state(tmp_path: Path) -> None:
    """A CONFLICTING PR produces no CI run at all, so it presents as "checks
    never fired" and nobody investigates."""
    pr = _pr(437, mergeable="CONFLICTING", reviews=[])
    assert "resolve_conflict" in _actions_for(_run(tmp_path, [], [pr]), 437)
