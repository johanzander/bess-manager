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
        "prs": [],
        "merged_pr": None,
        "worktree": None,
        "worktree_branch": None,
        # A live session holds its worktree locked. Defaults to unlocked so the
        # pre-existing stalled-work tests keep asserting what they always did.
        "worktree_locked": False,
        "stale_worktree": False,
        # Why a worktree is stale ("merged in #N" / "was the head of
        # closed-unmerged PR #N"); None unless stale_worktree is True.
        "stale_worktree_reason": None,
        "session": None,
        # The last `@claude-bot analyze` trigger and its age, or None. None =
        # never analyzed, which is what lets autonomous_analyze fire.
        "last_analyze_comment": None,
        "blocked_by": [],
        "blocked_by_open": [],
        "blocked": False,
        "resume_count": 0,
        # The candidate half of the collision gate -- files this item would
        # touch if dispatched, supplied by the Stage 2 analysis or the PO.
        # Empty by default: a candidate with no prediction is not dispatchable.
        "predicted_files": [],
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


def _run(
    tmp_path: Path,
    items: list,
    prs: list | None = None,
    pr_board: list | None = None,
    in_flight_files: dict | None = None,
    undiffable_prs: list | None = None,
    orphans: list | None = None,
    **env: str,
) -> dict:
    digest = tmp_path / "digest.json"
    digest.write_text(
        json.dumps(
            {
                "counts": {},
                "items": items,
                "orphans": orphans or [],
                # Board cards for PRs. Defaults to empty, which is also what an
                # older digest produces -- the script tolerates its absence, so
                # every pre-existing test exercises the no-deferral path.
                "pr_board": pr_board or [],
                # The exact half of the collision gate: {path: [pr numbers]},
                # always an object, {} when there are no open PRs.
                "in_flight_files": in_flight_files or {},
                # PRs whose diff could not be read this pass. Non-empty means
                # collision cannot be evaluated, so dispatch is held entirely.
                "undiffable_prs": undiffable_prs or [],
            }
        )
    )
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


def test_an_open_pr_suppresses_the_chase_and_the_park(tmp_path: Path) -> None:
    """Parking an item that has an open PR OSCILLATES: `park` says move the
    card to Backlog, the column derivation says an item with a PR is In Review,
    so the next pass reports `move_card` to put it back and the pass after that
    parks it again. #162 did exactly that — parked at 55 quiet days, reported
    as a mis-placed card, restored, parked again.

    The rule is also right on its own terms: an issue with a PR in flight is
    not a reporter chase whatever its Awaiting says, and the wait that matters
    is the review, which the PR half already reports.
    """
    for days, unwanted in ((28, "park"), (14, "nudge_reporter")):
        item = _item(
            162,
            labels=["b"],
            awaiting="reporter",
            prs=[{"number": 167, "mergeable": "MERGEABLE", "isDraft": True}],
            column="In Review",
            board_status="In Review",
            last_comment=_comment(days),
        )
        actions = _actions_for(_run(tmp_path, [item]), 162)
        assert unwanted not in actions, days
        # ...and no move_card either, so there is nothing to oscillate against.
        assert "move_card" not in actions, days


def test_the_chase_still_fires_without_a_pr(tmp_path: Path) -> None:
    """The suppression must not swallow the case the rule exists for."""
    item = _item(163, labels=["b"], awaiting="reporter", last_comment=_comment(28))
    assert "park" in _actions_for(_run(tmp_path, [item]), 163)


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


def test_stale_analysis_awaiting_after_stage2_is_grooming_debt(tmp_path: Path) -> None:
    # Board Awaiting still reads "analysis" (the "needs Stage 2" placeholder)
    # but Stage 2 has finished -- the analyzed label is on. Nothing else
    # contradicts an explicitly-set board value, so without this rule the item
    # sits in Analysis forever. #680/#704 were exactly this.
    item = _item(
        810,
        labels=["bug", "analyzed"],
        awaiting="analysis",
        awaiting_source="board",
        column="Analysis",
        board_status="Analysis",
    )
    assert "set_awaiting" in _actions_for(_run(tmp_path, [item]), 810)


def test_analysis_awaiting_before_stage2_is_not_flagged(tmp_path: Path) -> None:
    # Same field value, but Stage 2 genuinely has not run (no analyzed /
    # needs-human-review label). "analysis" is then an accurate wait, not a
    # stale placeholder -- do not raise grooming debt for it.
    item = _item(
        811,
        labels=["bug", "ready-for-analysis"],
        awaiting="analysis",
        awaiting_source="board",
        column="Analysis",
        board_status="Analysis",
    )
    assert "set_awaiting" not in _actions_for(_run(tmp_path, [item]), 811)


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


def test_a_locked_worktree_is_never_reported_as_stalled(tmp_path: Path) -> None:
    """`claude agents` lists background agents only, so a foreground
    `/implement-issue` started from the terminal is invisible and its worktree
    reads as abandoned. #624 was reported "no live session" while actively
    being worked, advising a second session onto the same branch. The lock is
    what a live session actually holds."""
    item = _item(
        624,
        worktree="/repo/worktrees/fix-issue-624",
        worktree_branch="fix/issue-624-pwl-window-bisect",
        worktree_locked=True,
        session=None,
    )
    assert "resume_implementation" not in _actions_for(_run(tmp_path, [item]), 624)


def test_an_unlocked_worktree_with_no_session_is_still_stalled(
    tmp_path: Path,
) -> None:
    """The lock must not swallow the case this rule exists for."""
    item = _item(
        625,
        worktree="/repo/worktrees/fix-issue-625",
        worktree_branch="fix/issue-625",
        worktree_locked=False,
        session=None,
    )
    assert "resume_implementation" in _actions_for(_run(tmp_path, [item]), 625)


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


def test_a_worktree_abandoned_behind_a_closed_pr_is_pruned_not_resumed(
    tmp_path: Path,
) -> None:
    """#428: its branch never merged, but its PR (#437) was closed unmerged and
    a different branch shipped the issue. The leftover worktree is an abandoned
    attempt -- prune it, do not propose `/implement-issue` against the dead
    branch. The digest sets `stale_worktree` for this now; the why-line quotes
    the reason so the pass says closed-unmerged rather than merged."""
    item = _item(
        428,
        worktree="/repo/wt/428",
        worktree_branch="feat/issue-428-consumption-forecast-series",
        stale_worktree=True,
        stale_worktree_reason="was the head of closed-unmerged PR #437",
        session=None,
        last_comment=_comment(1),
    )
    result = _run(tmp_path, [item])
    actions = _actions_for(result, 428)
    assert "prune_worktree" in actions
    assert "resume_implementation" not in actions
    prune = next(a for a in result["actions"] if a["action"] == "prune_worktree")
    assert "closed-unmerged PR #437" in prune["why"]


def test_work_with_a_pr_is_reported_once_by_the_pr_branch(tmp_path: Path) -> None:
    """Both halves could fire on the same work. The PR branch owns the handoff
    once a PR exists, so the issue rule stands down to avoid listing it twice."""
    item = _item(
        592,
        prs=[{"number": 619, "mergeable": "MERGEABLE", "isDraft": True}],
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
        10,
        labels=["analyzed"],
        column="Ready for Dev",
        last_comment=_comment(1),
        predicted_files=["core/bess/x.py"],
    )
    assert "dispatchable" in _actions_for(_run(tmp_path, [item]), 10)


# --- the autonomous Stage 2 carve-out --------------------------------------


def test_a_tier1_bug_is_surfaced_for_autonomous_analysis_even_when_awaiting_reporter(
    tmp_path: Path,
) -> None:
    """#681: a stale `Awaiting: reporter` hid #680 from the autonomous Stage 2
    carve-out, because the carve-out was only ever evaluated against items the
    rhythm pass surfaced, and the stale field suppressed the item entirely.
    The tier-1 check must run against the evidence (bug + ready-for-analysis +
    non-maintainer author), never the board field — `ready-for-analysis` is
    triage's own confirmation that the debug log is attached, so the item is
    waiting on analysis, not the reporter. And the same evidence must suppress
    the chases for that item: with the log attached the ball is NOT with the
    reporter, so parking or nudging it in the same pass would bury the exact
    bug the carve-out just un-hid."""
    item = _item(
        681,
        labels=["bug", "bot-analyzed", "ready-for-analysis"],
        author="ridax67",
        awaiting="reporter",
        awaiting_source="board",
        awaiting_suggested="analysis",
        last_comment=None,
    )
    actions = _actions_for(_run(tmp_path, [item]), 681)
    assert "autonomous_analyze" in actions
    assert "park" not in actions
    assert "nudge_reporter" not in actions
    assert "surface_discussion" not in actions


def test_a_qualifying_bug_fires_even_when_the_card_is_otherwise_quiet(
    tmp_path: Path,
) -> None:
    """The carve-out must not depend on the item producing some other action
    first — a fresh, reconciled, correctly-groomed card would otherwise be
    silent and never reach the PO."""
    item = _item(
        682,
        labels=["bug", "ready-for-analysis"],
        author="ridax67",
        column="Analysis",
        board_status="Analysis",
        awaiting=None,
        priority="P2",
    )
    assert "autonomous_analyze" in _actions_for(_run(tmp_path, [item]), 682)


def test_a_bug_still_waiting_for_its_log_does_not_fire(tmp_path: Path) -> None:
    """`needs-debug-log` means the reporter still owes the bundle — not yet a
    tier-1 bug, whatever the author."""
    item = _item(
        683,
        labels=["bug", "needs-debug-log"],
        author="ridax67",
        awaiting="reporter",
        awaiting_source="label",
    )
    assert "autonomous_analyze" not in _actions_for(_run(tmp_path, [item]), 683)


def test_a_bug_opened_by_the_maintainer_does_not_fire(tmp_path: Path) -> None:
    item = _item(684, labels=["bug", "ready-for-analysis"], author="johanzander")
    assert "autonomous_analyze" not in _actions_for(_run(tmp_path, [item]), 684)


def test_an_already_analyzed_bug_does_not_fire(tmp_path: Path) -> None:
    """`ready-for-analysis` is consumed by Stage 2 (replaced with `analyzed` or
    `needs-human-review`), so an analysed item must not match again — otherwise
    the pass would re-fire Stage 2 at $0.50-2 a shot under /loop."""
    analyzed = _item(685, labels=["bug", "analyzed"], author="ridax67")
    inconclusive = _item(686, labels=["bug", "needs-human-review"], author="ridax67")
    result = _run(tmp_path, [analyzed, inconclusive])
    assert "autonomous_analyze" not in _actions_for(result, 685)
    assert "autonomous_analyze" not in _actions_for(result, 686)


def test_autonomous_analyze_ranks_with_the_analysis_column(tmp_path: Path) -> None:
    """Analysis-column work, so it sorts with the other Analysis actions — not
    with the rank-9 catch-all an unnamed action would fall to."""
    item = _item(687, labels=["bug", "ready-for-analysis"], author="ridax67")
    result = _run(tmp_path, [item])
    action = next(a for a in result["actions"] if a.get("issue") == 687)
    assert action["action"] == "autonomous_analyze"
    assert action["rank"] == 5


def test_a_tier1_bug_at_nudge_threshold_is_analyzed_not_nudged(
    tmp_path: Path,
) -> None:
    """The same stale-field suppression at the nudge boundary: with the debug
    log attached, `nudge_reporter` would chase the reporter for something they
    already supplied — the two actions contradict, so the chase must stand
    down whenever the carve-out fires."""
    item = _item(
        688,
        labels=["bug", "ready-for-analysis"],
        author="ridax67",
        awaiting="reporter",
        last_comment=_comment(14),
    )
    actions = _actions_for(_run(tmp_path, [item]), 688)
    assert "autonomous_analyze" in actions
    assert "nudge_reporter" not in actions
    assert "park" not in actions


def test_a_tier1_bug_with_stage2_history_does_not_fire(tmp_path: Path) -> None:
    """`ready-for-analysis` is consumed by Stage 2 (replaced with `analyzed` or
    `needs-human-review`), but triage re-runs on an edited issue and re-stamps
    `ready-for-analysis` even after an inconclusive run, so the two can coexist
    on one item. The carve-out is for items with NO Stage 2 history at all —
    an item analysis has already settled must not re-fire the $0.50-2 spend
    every /loop tick, whatever labels have since accrued."""
    analyzed = _item(
        689, labels=["bug", "ready-for-analysis", "analyzed"], author="ridax67"
    )
    inconclusive = _item(
        690,
        labels=["bug", "ready-for-analysis", "needs-human-review"],
        author="ridax67",
    )
    result = _run(tmp_path, [analyzed, inconclusive])
    assert "autonomous_analyze" not in _actions_for(result, 689)
    assert "autonomous_analyze" not in _actions_for(result, 690)


def test_a_tier1_bug_awaiting_the_maintainer_escalates_instead_of_firing(
    tmp_path: Path,
) -> None:
    """`Awaiting: maintainer` is the one deliberate board hold — the loop
    cannot advance without a decision, so the spend is not the point. The
    carve-out must stand down and let the escalation be the loudest (rank 0)
    action."""
    item = _item(
        691,
        labels=["bug", "ready-for-analysis"],
        author="ridax67",
        awaiting="maintainer",
        awaiting_source="board",
    )
    actions = _actions_for(_run(tmp_path, [item]), 691)
    assert "escalated" in actions
    assert "autonomous_analyze" not in actions


def test_a_tier1_bug_in_discussion_is_analyzed_not_surfaced(tmp_path: Path) -> None:
    """`discussion` is a "someone else owes us" state like `reporter`, so it is
    stale-field material too: the evidence says ready, so the carve-out fires
    and the surface-to-maintainer action stands down rather than contradicting
    it."""
    item = _item(
        692,
        labels=["bug", "ready-for-analysis"],
        author="ridax67",
        awaiting="discussion",
        last_comment=_comment(40),
    )
    actions = _actions_for(_run(tmp_path, [item]), 692)
    assert "autonomous_analyze" in actions
    assert "surface_discussion" not in actions


def test_a_stalled_stage2_run_is_refired_not_escalated(tmp_path: Path) -> None:
    """#704: `@claude-bot analyze` was posted ~34h ago, the item is still
    `ready-for-analysis` with no analyzed/needs-human-review label -- the run
    never completed (commonly: the workflow had no API credit). Under the loop
    that is a plain retry: `refire_analyze`, not a maintainer escalation.
    `autonomous_analyze` stands down because a prior analyze comment exists."""
    item = _item(
        704,
        labels=["bug", "ready-for-analysis"],
        author="valexi7",
        column="Analysis",
        board_status="Analysis",
        last_analyze_comment={"days": 1, "hours": 34},
    )
    actions = _actions_for(_run(tmp_path, [item]), 704)
    assert "refire_analyze" in actions
    assert "autonomous_analyze" not in actions
    assert "escalated" not in actions


def test_an_analyze_still_in_flight_fires_neither(tmp_path: Path) -> None:
    """A trigger younger than the staleness window is a run that may still be
    working. Neither re-fire it nor start a fresh one -- wait."""
    item = _item(
        705,
        labels=["bug", "ready-for-analysis"],
        author="valexi7",
        column="Analysis",
        board_status="Analysis",
        last_analyze_comment={"days": 0, "hours": 2},
    )
    actions = _actions_for(_run(tmp_path, [item]), 705)
    assert "refire_analyze" not in actions
    assert "autonomous_analyze" not in actions


def test_analysis_wip_limit_holds_new_autonomous_analysis(tmp_path: Path) -> None:
    """Empty the board from the right, one column further left: an Analysis
    column already at its WIP limit does not pull a new bug in for analysis.
    The tier-1 bug is still counted and listed (`analysis_deferred`), never
    dropped, and `autonomous_analyze` does not fire until Analysis drains."""
    fillers = [
        _item(100 + n, column="Analysis", board_status="Analysis") for n in range(8)
    ]
    bug = _item(
        720,
        labels=["bug", "ready-for-analysis"],
        author="valexi7",
    )
    result = _run(tmp_path, [*fillers, bug], RHYTHM_ANALYSIS_WIP_LIMIT="8")
    assert result["analysis"] == {"count": 8, "limit": 8, "over": True}
    actions = _actions_for(result, 720)
    assert "autonomous_analyze" not in actions
    assert "analysis_deferred" in actions


def test_analysis_under_the_limit_still_analyses(tmp_path: Path) -> None:
    fillers = [
        _item(100 + n, column="Analysis", board_status="Analysis") for n in range(3)
    ]
    bug = _item(721, labels=["bug", "ready-for-analysis"], author="valexi7")
    result = _run(tmp_path, [*fillers, bug], RHYTHM_ANALYSIS_WIP_LIMIT="8")
    assert result["analysis"]["over"] is False
    assert "autonomous_analyze" in _actions_for(result, 721)


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
        # Defaults to green, so a test that cares about checks says so. An
        # empty rollup also reads as green, which is correct: a PR with no
        # checks configured has nothing failing.
        "statusCheckRollup": [{"name": "CI", "conclusion": "SUCCESS"}],
    }
    pr.update(over)
    return pr


def test_every_unfinished_draft_resolves_to_resume_implementation(
    tmp_path: Path,
) -> None:
    """This pass does NOT drive the review loop; `advance-pr` owns the
    one-step mechanical moves, and `implement-issue` owns the one step that
    needs the Step 2/3 context.

    So a draft needing a FIRST review and a draft needing REWORK both still
    report the same action name, `resume_implementation` — but they now route
    to different commands (see the two tests below), which is the fix for the
    fleet that used to hand every draft PR to a whole `implement-issue`
    session at $1-4 a shot.

    THE APPROVED-BUT-DRAFT CASE IS STILL CARVED OUT — see
    `test_an_approved_draft_is_never_deferred`. It used to route here too, and
    that is precisely why #629 sat approved, green and draft: the remedy on
    offer was a whole `implement-issue` session, and nobody spends one of those
    to run a single command. `gh pr ready` is not a review loop, so naming it
    directly does not duplicate one.
    """
    never_reviewed = _pr(619, reviews=[])
    changes_requested = _pr(
        614, reviews=[{"state": "APPROVED"}, {"state": "CHANGES_REQUESTED"}]
    )

    for pr in (never_reviewed, changes_requested):
        actions = _actions_for(_run(tmp_path, [], [pr]), pr["number"])
        assert actions == {"resume_implementation"}, pr["number"]


def test_draft_pr_with_no_review_routes_to_advance_pr(tmp_path: Path) -> None:
    """A draft with no review yet needs only a mechanical next step —
    request the review, resolve a conflict, or flip it ready — none of which
    needs the Step 2/3 context that only `implement-issue` holds. Handing this
    to a whole session was the gap between the design and its own headline
    promise: advancing a PR costs a step, not a session.
    """
    pr = _pr(619, reviews=[])
    action = next(a for a in _run(tmp_path, [], [pr])["actions"] if a.get("pr") == 619)

    assert action["action"] == "resume_implementation"
    assert "/advance-pr 619" in action["detail"]
    assert "/implement-issue" not in action["detail"]


def test_draft_pr_with_changes_requested_stays_on_implement_issue(
    tmp_path: Path,
) -> None:
    """A draft carrying CHANGES_REQUESTED is the one shape that stays on
    `implement-issue`: only that session holds the Step 2 diagnosis and the
    Step 3 scope assessment needed to tell a real review finding apart from a
    decision Step 3 already made and rejected on purpose. Routing this to
    `advance-pr` cold would be a blind rework.
    """
    pr = _pr(614, reviews=[{"state": "APPROVED"}, {"state": "CHANGES_REQUESTED"}])
    action = next(a for a in _run(tmp_path, [], [pr])["actions"] if a.get("pr") == 614)

    assert action["action"] == "resume_implementation"
    assert "/implement-issue 614" in action["detail"]
    assert "/advance-pr" not in action["detail"]


def test_draft_changes_requested_verdict_trusts_review_decision_over_reviews(
    tmp_path: Path,
) -> None:
    """The CHANGES_REQUESTED check trusts `reviewDecision` when GitHub sets
    it, and only falls back to the last non-COMMENTED review when it does
    not — the same seam the out-of-draft branch already uses, never a second
    way of reading a verdict. Here `reviewDecision` says CHANGES_REQUESTED
    while the raw `reviews` list would read APPROVED taken alone, so this
    pins that `reviewDecision` wins.
    """
    pr = _pr(
        614,
        reviewDecision="CHANGES_REQUESTED",
        reviews=[{"state": "APPROVED"}],
    )
    action = next(a for a in _run(tmp_path, [], [pr])["actions"] if a.get("pr") == 614)

    assert "/implement-issue 614" in action["detail"]


def test_the_handoff_names_the_issue_to_resume(tmp_path: Path) -> None:
    """`/implement-issue <n>` takes an issue number, so the action has to carry
    one — otherwise the loop reports work nobody can pick up."""
    item = _item(
        592,
        prs=[{"number": 615, "mergeable": "MERGEABLE", "isDraft": True}],
        column="In Review",
        last_comment=_comment(1),
    )
    # Not an approved draft: that case is `mark_ready` now and carries no
    # issue, because `gh pr ready <n>` needs only the PR number.
    pr = _pr(615, reviews=[{"state": "CHANGES_REQUESTED"}])

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
    hand. Uses a CHANGES_REQUESTED PR so it still exercises the
    `implement-issue` branch — a no-review draft with no linked issue routes
    to `advance-pr` instead, which needs no issue at all.

    No flag distinguishes the two: GitHub numbers issues and PRs from one
    sequence per repo, so a bare number is unambiguous and Step 0 resolves
    whichever it is.
    """
    pr = _pr(700, reviews=[{"state": "CHANGES_REQUESTED"}])
    action = next(a for a in _run(tmp_path, [], [pr])["actions"] if a.get("pr") == 700)

    assert action["issue"] is None
    assert "/implement-issue 700" in action["detail"]
    assert "--pr" not in action["detail"]


def test_a_mechanical_draft_with_no_linked_issue_needs_no_issue(
    tmp_path: Path,
) -> None:
    """`advance-pr` operates on the PR number alone, so a mechanical draft
    with no linked issue is not a gap the way an `implement-issue` handoff
    would be — there is nothing here that needs an issue number at all."""
    pr = _pr(700, reviews=[])
    action = next(a for a in _run(tmp_path, [], [pr])["actions"] if a.get("pr") == 700)

    assert "/advance-pr 700" in action["detail"]


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


def test_a_stale_approval_does_not_survive_a_later_changes_requested(
    tmp_path: Path,
) -> None:
    """GitHub never rewrites an old review when a later round requests
    changes, so an approved-then-reworked PR keeps its APPROVED entry forever.
    Asking "is there an APPROVED anywhere" reported a PR with changes
    outstanding as ready to merge — the same failure, reintroduced by the first
    attempt at fixing it."""
    pr = _pr(
        700,
        isDraft=False,
        reviewDecision="CHANGES_REQUESTED",
        reviews=[{"state": "APPROVED"}, {"state": "CHANGES_REQUESTED"}],
    )
    actions = _actions_for(_run(tmp_path, [], [pr]), 700)
    assert "rework_review" in actions
    assert "awaiting_maintainer" not in actions


def test_an_approval_is_honoured_when_review_decision_is_empty(
    tmp_path: Path,
) -> None:
    """`reviewDecision` is only populated when the repo REQUIRES reviews, and
    this one does not — #490 carries two real APPROVED reviews and still reads
    "". Keying on reviewDecision alone would report it as never reviewed."""
    pr = _pr(
        490,
        isDraft=False,
        reviewDecision="",
        reviews=[
            {"state": "COMMENTED"},
            {"state": "APPROVED"},
            {"state": "COMMENTED"},
            {"state": "APPROVED"},
        ],
    )
    actions = _actions_for(_run(tmp_path, [], [pr]), 490)
    assert "awaiting_maintainer" in actions
    assert "request_review" not in actions


def test_a_stale_approval_loses_to_changes_requested_without_review_decision(
    tmp_path: Path,
) -> None:
    """The same staleness trap with no reviewDecision to lean on: the LAST
    non-COMMENTED verdict decides, not the presence of an APPROVED."""
    pr = _pr(
        701,
        isDraft=False,
        reviewDecision="",
        reviews=[
            {"state": "APPROVED"},
            {"state": "COMMENTED"},
            {"state": "CHANGES_REQUESTED"},
        ],
    )
    actions = _actions_for(_run(tmp_path, [], [pr]), 701)
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


def test_a_conflicting_draft_routes_to_advance_pr(tmp_path: Path) -> None:
    """C1: a CONFLICTING draft used to hand to sweep-prs, which writes nothing
    -- only advance-pr performs the board write that records a semantic
    conflict escalation, so the old detail re-emitted forever. Only
    advance-pr's rows 1/2 actually resolve a CONFLICTING draft."""
    pr = _pr(437, isDraft=True, mergeable="CONFLICTING")
    result = _run(tmp_path, [], [pr])

    action = next(a for a in result["actions"] if a.get("pr") == 437)
    assert action["action"] == "resolve_conflict"
    assert action["detail"] == "/advance-pr 437"


def test_a_conflicting_non_draft_still_goes_to_sweep_prs(tmp_path: Path) -> None:
    """A conflicted PR that already left the review loop is not advance-pr's
    concern -- that carve-out stays sweep-prs."""
    pr = _pr(438, isDraft=False, mergeable="CONFLICTING")
    result = _run(tmp_path, [], [pr])

    action = next(a for a in result["actions"] if a.get("pr") == 438)
    assert action["action"] == "resolve_conflict"
    assert "sweep-prs" in action["detail"]


def _card(number: int, **over: object) -> dict:
    card: dict = {
        "number": number,
        "board_status": "Backlog",
        "priority": None,
        "awaiting": None,
    }
    card.update(over)
    return card


def test_a_pr_awaiting_something_is_deferred_not_reported(tmp_path: Path) -> None:
    """The reason the board holds PRs at all. "#167 and #354 are blocked" was a
    real decision with nowhere to live, so every pass re-reported them as
    conflicts needing action and the same conversation happened every tick."""
    pr = _pr(167, mergeable="CONFLICTING")
    result = _run(tmp_path, [], [pr], pr_board=[_card(167, awaiting="discussion")])

    assert _actions_for(result, 167) == set()
    assert [d["pr"] for d in result["deferred"]] == [167]
    assert result["deferred"][0]["why"] == "awaiting discussion"


def test_a_p4_pr_is_deferred(tmp_path: Path) -> None:
    """ "Lower priority, I intend to get to it later" — #437 and #490."""
    pr = _pr(437, mergeable="CONFLICTING")
    result = _run(tmp_path, [], [pr], pr_board=[_card(437, priority="P4")])

    assert _actions_for(result, 437) == set()
    assert result["deferred"][0]["why"] == "priority P4"


def test_an_approved_pr_can_be_deferred(tmp_path: Path) -> None:
    """An approved PR waiting on a merge is not broken — it is the maintainers
    call when to take it, and P4 is how they say later. #490 sat approved for a
    day and was reported every tick as though that were news."""
    pr = _pr(490, isDraft=False, reviews=[{"state": "APPROVED"}])
    result = _run(tmp_path, [], [pr], pr_board=[_card(490, priority="P4")])

    assert "awaiting_maintainer" not in _actions_for(result, 490)
    assert [d["pr"] for d in result["deferred"]] == [490]


def test_an_approved_draft_is_never_deferred(tmp_path: Path) -> None:
    """The one carve-out. APPROVED-and-still-draft is a pipeline failure, not a
    priority: the loop stopped one command short of finishing. #629 sat in
    exactly this state while every pass reported it as ordinary unfinished
    work, because the session that owned it went idle before gh pr ready."""
    pr = _pr(629, isDraft=True, reviews=[{"state": "APPROVED"}])
    result = _run(tmp_path, [], [pr], pr_board=[_card(629, priority="P4")])

    assert "mark_ready" in _actions_for(result, 629)
    assert result["deferred"] == []


def test_mark_ready_routes_through_advance_pr(tmp_path: Path) -> None:
    """I7: a bare `gh pr ready` in the detail string is the exact #609
    failure re-opened at the one call site an unattended pass actually reads
    -- it skips advance-pr's mandatory mergeability re-check and the
    push-after-approval rule. The detail must name the skill, not the
    command."""
    pr = _pr(629, isDraft=True, reviews=[{"state": "APPROVED"}])
    result = _run(tmp_path, [], [pr])

    action = next(a for a in result["actions"] if a.get("pr") == 629)
    assert action["action"] == "mark_ready"
    assert action["detail"].startswith("/advance-pr 629")
    assert "gh pr ready" not in action["detail"]


def test_approved_draft_is_reported_even_with_no_card(tmp_path: Path) -> None:
    pr = _pr(629, isDraft=True, reviews=[{"state": "APPROVED"}])
    assert "mark_ready" in _actions_for(_run(tmp_path, [], [pr]), 629)


def test_a_stale_approval_does_not_earn_mark_ready(tmp_path: Path) -> None:
    """The same staleness trap the non-draft rules already guard: an
    approved-then-reworked draft keeps its APPROVED entry forever."""
    pr = _pr(
        700,
        isDraft=True,
        reviewDecision="CHANGES_REQUESTED",
        reviews=[{"state": "APPROVED"}, {"state": "CHANGES_REQUESTED"}],
    )
    actions = _actions_for(_run(tmp_path, [], [pr]), 700)
    assert "mark_ready" not in actions
    assert "resume_implementation" in actions


def test_a_conflicting_approved_draft_is_not_mark_ready(tmp_path: Path) -> None:
    """A conflicted PR cannot be merged and gets no CI run, so flipping it
    ready would hand over something unmergeable."""
    pr = _pr(
        701, isDraft=True, mergeable="CONFLICTING", reviews=[{"state": "APPROVED"}]
    )
    actions = _actions_for(_run(tmp_path, [], [pr]), 701)
    assert "mark_ready" not in actions
    assert "resolve_conflict" in actions


def test_a_deferral_recorded_on_the_issue_card_suppresses_the_pr(
    tmp_path: Path,
) -> None:
    """I11: backlog SKILL.md documents "One card per unit of work, on the
    issue -- PR cards go away", but only pr_board suppression was ever
    implemented. A PO following the shipped doc records `Awaiting` on the
    issue, where nothing read it."""
    item = _item(
        592,
        prs=[{"number": 619, "mergeable": "CONFLICTING", "isDraft": True}],
        awaiting="discussion",
    )
    pr = _pr(619, mergeable="CONFLICTING")
    result = _run(tmp_path, [item], [pr])

    assert _actions_for(result, 619) == set()
    assert [d["pr"] for d in result["deferred"]] == [619]
    assert result["deferred"][0]["why"] == "issue awaiting discussion"


def test_an_issue_side_p4_also_suppresses_the_pr(tmp_path: Path) -> None:
    item = _item(
        593,
        prs=[{"number": 620, "mergeable": "CONFLICTING", "isDraft": True}],
        priority="P4",
    )
    pr = _pr(620, mergeable="CONFLICTING")
    result = _run(tmp_path, [item], [pr])

    assert _actions_for(result, 620) == set()
    assert result["deferred"][0]["why"] == "issue priority P4"


def test_pr_board_deferral_still_wins_when_both_are_set(tmp_path: Path) -> None:
    """The pr_board reason is reported first when both a card and the issue
    carry a deferral -- either is sufficient to suppress, but the message
    should not silently prefer one over the other for no stated reason: it
    prefers the pr_board card because that is the older, still-supported
    mechanism."""
    item = _item(
        594,
        prs=[{"number": 621, "mergeable": "CONFLICTING", "isDraft": True}],
        awaiting="discussion",
    )
    pr = _pr(621, mergeable="CONFLICTING")
    result = _run(tmp_path, [item], [pr], pr_board=[_card(621, priority="P4")])

    assert _actions_for(result, 621) == set()
    assert result["deferred"][0]["why"] == "priority P4"


def test_removing_pr_cards_does_not_un_park_an_issue_side_deferral(
    tmp_path: Path,
) -> None:
    """The safety property I11 is actually for: with only pr_board
    suppression, deleting PR cards entirely would silently un-defer every PR
    parked on its issue. An empty pr_board must not do that."""
    item = _item(
        595,
        prs=[{"number": 622, "mergeable": "CONFLICTING", "isDraft": True}],
        priority="P4",
    )
    pr = _pr(622, mergeable="CONFLICTING")
    result = _run(tmp_path, [item], [pr], pr_board=[])

    assert _actions_for(result, 622) == set()
    assert [d["pr"] for d in result["deferred"]] == [622]


def test_a_pr_with_no_card_is_reported_as_before(tmp_path: Path) -> None:
    """Deferral is opt-in: absent a card, nothing changes."""
    pr = _pr(614, mergeable="CONFLICTING")
    result = _run(tmp_path, [], [pr], pr_board=[])

    assert "resolve_conflict" in _actions_for(result, 614)
    assert result["deferred"] == []


def test_mark_ready_needs_green_checks_not_just_a_clean_merge(
    tmp_path: Path,
) -> None:
    """`mergeable` reports only whether the branch merges cleanly, so it reads
    MERGEABLE while checks are still running. #633 was APPROVED and MERGEABLE
    with Algorithm tests and E2E in progress, and the first version of this
    rule duly said to flip it — which would hand the maintainer a PR marked
    ready whose CI had not finished."""
    pr = _pr(
        633,
        isDraft=True,
        reviews=[{"state": "APPROVED"}],
        statusCheckRollup=[
            {"name": "Fast tests", "conclusion": "SUCCESS"},
            {"name": "Algorithm tests", "conclusion": ""},
        ],
    )
    actions = _actions_for(_run(tmp_path, [], [pr]), 633)
    assert "mark_ready" not in actions
    assert "resume_implementation" in actions


def test_mark_ready_is_withheld_on_a_failing_check(tmp_path: Path) -> None:
    pr = _pr(
        634,
        isDraft=True,
        reviews=[{"state": "APPROVED"}],
        statusCheckRollup=[
            {"name": "Fast tests", "conclusion": "SUCCESS"},
            {"name": "E2E tests", "conclusion": "FAILURE"},
        ],
    )
    assert "mark_ready" not in _actions_for(_run(tmp_path, [], [pr]), 634)


def test_a_skipped_check_still_counts_as_green(tmp_path: Path) -> None:
    """Path-filtered jobs correctly do not run — every backend-only PR in this
    repo skips Algorithm tests and Docker build, so treating SKIPPED as
    not-green would withhold mark_ready from almost every PR."""
    pr = _pr(
        635,
        isDraft=True,
        reviews=[{"state": "APPROVED"}],
        statusCheckRollup=[
            {"name": "Fast tests", "conclusion": "SUCCESS"},
            {"name": "Algorithm tests", "conclusion": "SKIPPED"},
        ],
    )
    assert "mark_ready" in _actions_for(_run(tmp_path, [], [pr]), 635)


def test_a_pending_approved_draft_is_not_counted_as_deferred(
    tmp_path: Path,
) -> None:
    """The deferred list mirrors the mark_ready carve-out, so a card-deferred
    PR that is approved-but-pending must appear in exactly one place."""
    pr = _pr(
        636,
        isDraft=True,
        reviews=[{"state": "APPROVED"}],
        statusCheckRollup=[{"name": "CI", "conclusion": ""}],
    )
    result = _run(tmp_path, [], [pr], pr_board=[_card(636, priority="P4")])

    assert _actions_for(result, 636) == set()
    assert [d["pr"] for d in result["deferred"]] == [636]


def test_awaiting_maintainer_escalates_instead_of_suppressing(tmp_path: Path) -> None:
    """Awaiting is signed. reporter/upstream/discussion mean they owe us, and
    stay quiet; maintainer means YOU owe us, and must be loud. Today every
    value suppresses, so an item blocked on the maintainer gets quieter."""
    item = _item(700, awaiting="maintainer", awaiting_source="board")
    result = _run(tmp_path, [item])
    assert "escalated" in _actions_for(result, 700)
    assert result["actions"][0]["issue"] == 700


def test_three_changes_requested_rounds_escalate(tmp_path: Path) -> None:
    """Three rounds of disagreement is a design argument, not a bug -- the
    implement-issue cap already says so. Another round will not settle it."""
    pr = _pr(
        701,
        isDraft=True,
        reviews=[
            {"state": "CHANGES_REQUESTED"},
            {"state": "CHANGES_REQUESTED"},
            {"state": "CHANGES_REQUESTED"},
        ],
    )
    actions = _actions_for(_run(tmp_path, [], prs=[pr]), 701)
    assert "escalated" in actions
    assert "resume_implementation" not in actions


def test_two_resume_handoffs_escalate(tmp_path: Path) -> None:
    item = _item(702, resume_count=2, worktree="/wt", worktree_branch="fix/issue-702")
    actions = _actions_for(_run(tmp_path, [item]), 702)
    assert "escalated" in actions
    assert "resume_implementation" not in actions


def test_one_handoff_is_not_yet_an_escalation(tmp_path: Path) -> None:
    item = _item(703, resume_count=1, worktree="/wt", worktree_branch="fix/issue-703")
    actions = _actions_for(_run(tmp_path, [item]), 703)
    assert "escalated" not in actions
    assert "resume_implementation" in actions


def test_two_handoffs_do_not_escalate_once_a_fix_has_merged(tmp_path: Path) -> None:
    """#707 / #683: `resume_count` never decrements, so an issue handed back
    twice before a third, reframed attempt merged kept firing `escalated` on a
    fix already on main. A merged PR means the handbacks are history."""
    item = _item(
        683,
        resume_count=2,
        merged_pr=686,
        column="In Verification",
        board_status="In Verification",
    )
    actions = _actions_for(_run(tmp_path, [item]), 683)
    assert "escalated" not in actions


def test_in_verification_with_no_status_signal_fires_announce(tmp_path: Path) -> None:
    """#707 / #683: In Verification lives only in a Project field. Fire once to
    put a visible fix-status comment + `awaiting-release` label on the issue,
    ranked right after escalations."""
    item = _item(
        683,
        column="In Verification",
        board_status="In Verification",
        merged_pr=686,
        labels=["bug", "analyzed"],
    )
    result = _run(tmp_path, [item])
    action = next(
        a for a in result["actions"] if a["action"] == "announce_verification"
    )
    assert action["issue"] == 683
    assert action["rank"] == 1
    assert "686" in action["detail"]


def test_announce_verification_is_suppressed_once_labelled(tmp_path: Path) -> None:
    item = _item(
        683,
        column="In Verification",
        board_status="In Verification",
        merged_pr=686,
        labels=["bug", "analyzed", "awaiting-release"],
    )
    assert "announce_verification" not in _actions_for(_run(tmp_path, [item]), 683)


def test_finishing_outranks_starting(tmp_path: Path) -> None:
    """Empty the board from the right. The alphabetical sort put dispatchable
    first and resume_implementation last purely because d < m < r."""
    ready = _item(
        800,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["bug", "analyzed"],
        priority="P2",
        predicted_files=["core/bess/x.py"],
    )
    stalled = _item(
        801,
        column="In Progress",
        board_status="In Progress",
        worktree="/wt",
        worktree_branch="fix/issue-801",
    )
    order = [a["action"] for a in _run(tmp_path, [ready, stalled])["actions"]]
    assert order.index("resume_implementation") < order.index("dispatchable")


def test_an_escalation_outranks_every_column(tmp_path: Path) -> None:
    escalated = _item(802, awaiting="maintainer", awaiting_source="board")
    verifying = _item(803, column="In Verification", board_status="In Verification")
    first = _run(tmp_path, [escalated, verifying])["actions"][0]
    assert first["action"] == "escalated"


def test_grooming_actions_rank_together_after_dispatchable(tmp_path: Path) -> None:
    """set_awaiting, add_card, set_priority, move_card and triage_labels are
    board-hygiene, not column-driven flow work, so they all land at the same
    rank and strictly after dispatchable. There is no way to make the script
    emit an action name with no rank branch without editing the script
    itself, so this pins the five named branches directly rather than
    fabricating an unreachable case."""
    awaiting_item = _item(
        900,
        labels=["needs-debug-log"],
        awaiting="reporter",
        awaiting_source="label",
        awaiting_suggested="reporter",
        last_comment=_comment(1),
    )
    no_card_item = _item(901, board_status=None, priority=None)
    no_priority_item = _item(902, priority=None)
    mismatched_column_item = _item(
        903, board_status="Ready for Dev", column="In Progress"
    )
    unlabeled_item = _item(904, labels=[])
    dispatchable_item = _item(
        905,
        column="Ready for Dev",
        board_status="Ready for Dev",
        predicted_files=["core/bess/x.py"],
    )

    result = _run(
        tmp_path,
        [
            awaiting_item,
            no_card_item,
            no_priority_item,
            mismatched_column_item,
            unlabeled_item,
            dispatchable_item,
        ],
    )

    rank_by_action = {a["action"]: a["rank"] for a in result["actions"]}
    grooming_actions = [
        "set_awaiting",
        "add_card",
        "set_priority",
        "move_card",
        "triage_labels",
    ]
    for action in grooming_actions:
        assert action in rank_by_action, action

    grooming_ranks = {rank_by_action[a] for a in grooming_actions}
    assert len(grooming_ranks) == 1, rank_by_action
    (grooming_rank,) = grooming_ranks
    assert grooming_rank > rank_by_action["dispatchable"]


# --- tooling freshness ---------------------------------------------------


def test_tooling_freshness_check_is_inert_under_the_test_seam(tmp_path: Path) -> None:
    """`RHYTHM_DIGEST_FILE` is set here, so the fetch + behind-count is skipped
    entirely -- `behind` is null and no TOOLING line can print. This pins that
    `--argjson tooling_behind null` round-trips and the every-path print stays
    guarded; the live behind-count is exercised by the git plumbing, not here
    (it would need a network fetch)."""
    result = _run(tmp_path, [_item(1, labels=["bug"], last_comment=_comment(1))])
    assert result["tooling"] == {"behind": None, "ref": "origin/main"}


# --- the WIP limit --------------------------------------------------------


def test_over_the_wip_limit_suppresses_dispatch(tmp_path: Path) -> None:
    """Unbounded WIP is the state that produced 8 open drafts, 6 of them
    conflicting. Above the limit, nothing new starts."""
    in_flight = [
        _item(
            900 + i,
            column="In Review",
            board_status="In Review",
            prs=[{"number": 950 + i, "mergeable": "MERGEABLE", "isDraft": True}],
        )
        for i in range(3)
    ]
    ready = _item(
        910,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["bug", "analyzed"],
        priority="P2",
    )
    result = _run(tmp_path, [*in_flight, ready])
    assert result["wip"] == {"count": 3, "limit": 3, "over": True}
    assert "dispatchable" not in _actions_for(result, 910)


def test_under_the_limit_dispatch_is_allowed(tmp_path: Path) -> None:
    ready = _item(
        911,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["bug", "analyzed"],
        priority="P2",
        predicted_files=["core/bess/x.py"],
    )
    result = _run(tmp_path, [ready])
    assert result["wip"]["over"] is False
    assert "dispatchable" in _actions_for(result, 911)


def test_a_branch_and_its_pr_count_as_one(tmp_path: Path) -> None:
    """In Progress and In Review are the same piece of work at two stages;
    counting them separately would double the effective limit."""
    items = [
        _item(920, column="In Progress", board_status="In Progress"),
        _item(
            921,
            column="In Review",
            board_status="In Review",
            prs=[{"number": 960, "mergeable": "MERGEABLE", "isDraft": True}],
        ),
    ]
    assert _run(tmp_path, items)["wip"]["count"] == 2


def test_in_verification_does_not_count_as_wip(tmp_path: Path) -> None:
    """In Verification is already merged to main and only waiting on a
    release -- it occupies no implementation slot, so it must not count
    toward the limit or suppress dispatch. Four such items alone exceed the
    default limit of 3, so a filter that widened to include this column
    would both inflate the count and suppress the ready item below."""
    verifying = [
        _item(930 + i, column="In Verification", board_status="In Verification")
        for i in range(4)
    ]
    ready = _item(
        940,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["bug", "analyzed"],
        priority="P2",
        predicted_files=["core/bess/x.py"],
    )
    result = _run(tmp_path, [*verifying, ready])
    assert result["wip"] == {"count": 0, "limit": 3, "over": False}
    assert "dispatchable" in _actions_for(result, 940)


# --- the collision gate ----------------------------------------------------


def test_a_candidate_touching_an_in_flight_file_is_queued(tmp_path: Path) -> None:
    """Five PRs raced to rewrite the same three files. The gate belongs before
    dispatch -- detecting the clash at merge time is detecting a fire."""
    ready = _item(
        1000,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["bug", "analyzed"],
        priority="P2",
        predicted_files=["CLAUDE.md"],
    )
    result = _run(tmp_path, [ready], in_flight_files={"CLAUDE.md": [614]})
    actions = _actions_for(result, 1000)
    assert "queued_behind" in actions
    assert "dispatchable" not in actions


def test_a_candidate_with_no_predicted_files_is_not_dispatchable(
    tmp_path: Path,
) -> None:
    """No touch-set, no dispatch. A proposal that cannot be checked against the
    in-flight set is a proposal to find out by colliding."""
    ready = _item(
        1001,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["bug", "analyzed"],
        priority="P2",
        predicted_files=[],
    )
    actions = _actions_for(_run(tmp_path, [ready]), 1001)
    assert "dispatchable" not in actions
    assert "needs_touch_set" in actions


def test_two_ready_items_that_overlap_are_clustered(tmp_path: Path) -> None:
    """Two issues that will fight over one file cost less as one unit of work
    than as two PRs plus a conflict resolution."""
    a = _item(
        1002,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["analyzed"],
        priority="P2",
        predicted_files=["core/bess/x.py"],
    )
    b = _item(
        1003,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["analyzed"],
        priority="P2",
        predicted_files=["core/bess/x.py"],
    )
    result = _run(tmp_path, [a, b])
    assert "cluster" in _actions_for(result, 1002)


# --- undiffable PRs suppress the whole collision gate -----------------------


def test_an_undiffable_pr_suppresses_dispatchable_entirely(tmp_path: Path) -> None:
    """One PR whose diff could not be read means the in-flight file set is
    incomplete, so collision cannot be safely evaluated for ANY candidate --
    not just the ones that would clash with the missing PR's files. Dispatch
    is held fleet-wide, the same way over-WIP holds it."""
    ready = _item(
        1010,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["bug", "analyzed"],
        priority="P2",
        predicted_files=["core/bess/x.py"],
    )
    result = _run(tmp_path, [ready], undiffable_prs=[614])
    actions = _actions_for(result, 1010)
    assert "dispatchable" not in actions


def test_an_undiffable_pr_emits_one_action_per_pr(tmp_path: Path) -> None:
    result = _run(tmp_path, [], undiffable_prs=[614, 620])
    prs_reported = {
        a["pr"] for a in result["actions"] if a["action"] == "undiffable_pr"
    }
    assert prs_reported == {614, 620}


def test_undiffable_pr_ranks_with_pr_side_actions(tmp_path: Path) -> None:
    """Named rank 2, alongside the other PR-side actions, so it sorts with
    work in flight rather than falling to the unranked catch-all rank."""
    result = _run(tmp_path, [], undiffable_prs=[614])
    action = next(a for a in result["actions"] if a["action"] == "undiffable_pr")
    assert action["rank"] == 2


def test_no_undiffable_prs_does_not_suppress_dispatch(tmp_path: Path) -> None:
    ready = _item(
        1011,
        column="Ready for Dev",
        board_status="Ready for Dev",
        labels=["bug", "analyzed"],
        priority="P2",
        predicted_files=["core/bess/x.py"],
    )
    result = _run(tmp_path, [ready], undiffable_prs=[])
    assert "dispatchable" in _actions_for(result, 1011)


def test_a_stale_pr_card_orphan_becomes_an_archive_action(tmp_path: Path) -> None:
    """#707 / #638: a PullRequest card whose PR has closed or merged is
    reconciled by nothing else -- the digest surfaces it in `orphans` and the
    rhythm pass turns it into a board action so it does not sit forever in
    whatever column it was last in."""
    result = _run(
        tmp_path,
        [],
        orphans=[
            {
                "kind": "stale_pr_card",
                "ref": "638",
                "detail": "PR #638 is closed; card still in In Review",
            }
        ],
    )
    actions = [a for a in result["actions"] if a["action"] == "archive_pr_card"]
    assert [a["pr"] for a in actions] == [638]
    assert actions[0]["rank"] == 6
    assert "closed" in actions[0]["why"]


def test_other_orphan_kinds_do_not_become_archive_actions(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [],
        orphans=[
            {"kind": "worktree_no_issue", "ref": "/wt/x", "detail": "x"},
            {"kind": "issue_no_card", "ref": "700", "detail": "y"},
        ],
    )
    assert [a for a in result["actions"] if a["action"] == "archive_pr_card"] == []


def test_a_stale_issue_card_orphan_becomes_a_move_card_action(tmp_path: Path) -> None:
    """#707: a card whose issue has closed is reconciled by nothing else --
    the digest surfaces it in `orphans` and the rhythm pass turns it into a
    move to Done."""
    result = _run(
        tmp_path,
        [],
        orphans=[
            {
                "kind": "stale_issue_card",
                "ref": "555",
                "detail": "issue #555 is closed; card still in In Review",
            }
        ],
    )
    actions = [
        a
        for a in result["actions"]
        if a["action"] == "move_card" and a.get("issue") == 555
    ]
    assert len(actions) == 1
    assert "Done" in actions[0]["detail"]
    assert actions[0]["rank"] == 6
