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
        # Defaults to matching `column`, so the default item is a reconciled
        # card and no board action fires. A test that overrides one and not the
        # other is asserting a mismatch on purpose.
        "board_status": "Backlog",
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


def test_an_issue_with_no_card_asks_for_a_card_not_a_priority(
    tmp_path: Path,
) -> None:
    """Both causes leave Priority null, and conflating them sent the PO to set
    a field on a card that does not exist."""
    item = _item(621, board_status=None, priority=None)
    actions = _actions_for(_run(tmp_path, [item]), 621)
    assert "add_card" in actions
    assert "set_priority" not in actions


def test_a_card_in_the_wrong_column_is_a_move(tmp_path: Path) -> None:
    item = _item(602, board_status="Ready for Dev", column="In Progress")
    result = _run(tmp_path, [item])
    assert "move_card" in _actions_for(result, 602)
    move = next(
        a
        for a in result["actions"]
        if a.get("issue") == 602 and a["action"] == "move_card"
    )
    assert "In Progress" in move["detail"]


def test_a_reconciled_card_is_not_moved(tmp_path: Path) -> None:
    item = _item(603, board_status="Analysis", column="Analysis")
    assert "move_card" not in _actions_for(_run(tmp_path, [item]), 603)


def test_stale_worktree_is_handed_to_sweep_prs(tmp_path: Path) -> None:
    item = _item(
        9,
        labels=["b"],
        stale_worktree=True,
        worktree_branch="fix/issue-9",
        last_comment=_comment(1),
    )
    assert "prune_worktree" in _actions_for(_run(tmp_path, [item]), 9)


def test_a_worktree_with_no_session_is_stalled_work(tmp_path: Path) -> None:
    """The machine-died case, and the one the fleet was full of.

    A live worktree with no session behind it is an implementation that stopped
    mid-flight — restart, kill, or an agent that exited between steps. An audit
    found 34 such worktrees, 8 holding real unpushed commits (one with 32), and
    nothing picked any of them up.
    """
    item = _item(
        589,
        worktree="/repo/wt/589",
        worktree_branch="feat/issue-589",
        session=None,
        last_comment=_comment(1),
    )
    action = next(
        a
        for a in _run(tmp_path, [item])["actions"]
        if a["action"] == "resume_implementation"
    )
    assert action["issue"] == 589
    # A resume, never a restart: Step 4 would branch fresh from origin/main and
    # delete the commits that only exist on this branch.
    assert "never restart" in action["detail"]


def test_a_worktree_with_a_live_session_is_left_alone(tmp_path: Path) -> None:
    item = _item(
        590,
        worktree="/repo/wt/590",
        worktree_branch="feat/issue-590",
        session="issue-590",
        last_comment=_comment(1),
    )
    assert "resume_implementation" not in _actions_for(_run(tmp_path, [item]), 590)


def test_a_stale_worktree_is_pruned_not_resumed(tmp_path: Path) -> None:
    """Its branch already merged, so there is nothing to resume — only rot to
    clear. Resuming here would re-enter a finished issue."""
    item = _item(
        593,
        worktree="/repo/wt/593",
        worktree_branch="fix/issue-593",
        stale_worktree=True,
        session=None,
        last_comment=_comment(1),
    )
    actions = _actions_for(_run(tmp_path, [item]), 593)
    assert "prune_worktree" in actions
    assert "resume_implementation" not in actions


def test_work_with_a_pr_is_reported_once_by_the_pr_branch(tmp_path: Path) -> None:
    """Both halves could fire on the same work. The PR branch owns the handoff
    once a PR exists, so the issue rule stands down to avoid listing it twice."""
    item = _item(
        592,
        pr=619,
        worktree="/repo/wt/592",
        worktree_branch="fix/issue-592",
        session=None,
        column="In Review",
        last_comment=_comment(1),
    )
    pr = _pr(619, reviews=[])

    result = _run(tmp_path, [item], [pr])
    resumes = [a for a in result["actions"] if a["action"] == "resume_implementation"]
    assert len(resumes) == 1
    assert resumes[0]["pr"] == 619


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


def test_every_unfinished_draft_resolves_to_one_handoff(tmp_path: Path) -> None:
    """This pass does NOT drive the review loop; `implement-issue` owns a PR
    through to `gh pr ready`, and its Step 11 already requests the review, acts
    on the verdict and flips the PR.

    So a draft needing a FIRST review, a draft needing REWORK, and a draft that
    is already APPROVED but never got flipped all resolve to the same action:
    hand it back to the skill that owns it. Step 0 re-enters at the right step.
    Re-implementing any of that here would be a second copy of one loop, which
    is how one of them goes stale.
    """
    approved_but_draft = _pr(615, reviews=[{"state": "APPROVED"}])
    never_reviewed = _pr(619, reviews=[])
    changes_requested = _pr(
        614, reviews=[{"state": "APPROVED"}, {"state": "CHANGES_REQUESTED"}]
    )

    for pr in (approved_but_draft, never_reviewed, changes_requested):
        actions = _actions_for(_run(tmp_path, [], [pr]), pr["number"])
        assert actions == {"resume_implementation"}, pr["number"]


def test_the_handoff_names_the_issue_to_resume(tmp_path: Path) -> None:
    """`/implement-issue <n>` takes an issue number, so the action has to carry
    one — otherwise the loop reports work nobody can pick up."""
    item = _item(592, pr=615, column="In Review", last_comment=_comment(1))
    pr = _pr(615, reviews=[{"state": "APPROVED"}])

    action = next(
        a for a in _run(tmp_path, [item], [pr])["actions"] if a.get("pr") == 615
    )
    assert action["issue"] == 592
    assert "/implement-issue 592" in action["detail"]


def test_a_draft_with_no_linked_issue_resumes_by_pr(tmp_path: Path) -> None:
    """`implement-issue` is used for TODO.md items and refactors too, so a PR
    with no linked issue is normal, not a defect.

    Reporting "no issue, finish it by hand" left every self-directed PR with no
    owner in the loop — which is how #620, #622 and #623 all ended up driven by
    hand.

    No flag distinguishes the two: GitHub numbers issues and PRs from one
    sequence per repo, so a bare number is unambiguous and Step 0 resolves
    whichever it is.
    """
    pr = _pr(700, reviews=[])
    action = next(a for a in _run(tmp_path, [], [pr])["actions"] if a.get("pr") == 700)

    assert action["issue"] is None
    assert "/implement-issue 700" in action["detail"]
    assert "--pr" not in action["detail"]


def test_approved_non_draft_is_the_maintainers(tmp_path: Path) -> None:
    pr = _pr(490, isDraft=False, reviews=[{"state": "APPROVED"}])
    assert "awaiting_maintainer" in _actions_for(_run(tmp_path, [], [pr]), 490)


def test_an_unreviewed_non_draft_is_never_reported_as_mergeable(
    tmp_path: Path,
) -> None:
    """The draft flag is not a review. #626 was flipped out of draft by hand
    because it looked stuck, had zero reviews, and was reported as "nothing
    left but your merge" — routing straight around Stage 4, which is the gate
    the whole pipeline is built on."""
    pr = _pr(626, isDraft=False, reviews=[])
    actions = _actions_for(_run(tmp_path, [], [pr]), 626)
    assert "request_review" in actions
    assert "awaiting_maintainer" not in actions


def test_a_commented_review_alone_is_not_an_approval(tmp_path: Path) -> None:
    """The bot posts its inline notes as a COMMENTED review BEFORE its real
    verdict, so COMMENTED alone means the review is still in flight."""
    pr = _pr(627, isDraft=False, reviews=[{"state": "COMMENTED"}])
    actions = _actions_for(_run(tmp_path, [], [pr]), 627)
    assert "request_review" in actions
    assert "awaiting_maintainer" not in actions


def test_a_non_draft_with_changes_requested_needs_rework(tmp_path: Path) -> None:
    pr = _pr(
        628,
        isDraft=False,
        reviewDecision="CHANGES_REQUESTED",
        reviews=[{"state": "CHANGES_REQUESTED"}],
    )
    actions = _actions_for(_run(tmp_path, [], [pr]), 628)
    assert "rework_review" in actions
    assert "awaiting_maintainer" not in actions


def test_an_approval_followed_by_notes_still_counts(tmp_path: Path) -> None:
    """A trailing COMMENTED must not un-approve a PR — #490 carries exactly
    this shape (COMMENTED, APPROVED, COMMENTED, APPROVED)."""
    pr = _pr(
        490,
        isDraft=False,
        reviews=[
            {"state": "COMMENTED"},
            {"state": "APPROVED"},
            {"state": "COMMENTED"},
        ],
    )
    assert "awaiting_maintainer" in _actions_for(_run(tmp_path, [], [pr]), 490)


def test_conflicting_pr_is_flagged_over_its_review_state(tmp_path: Path) -> None:
    """A CONFLICTING PR produces no CI run at all, so it presents as "checks
    never fired" and nobody investigates."""
    pr = _pr(437, mergeable="CONFLICTING", reviews=[])
    assert "resolve_conflict" in _actions_for(_run(tmp_path, [], [pr]), 437)
