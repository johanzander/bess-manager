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


def _porcelain(*worktrees: tuple[str, str | None], locked: tuple[str, ...] = ()) -> str:
    """Build `git worktree list --porcelain` output for a main checkout
    followed by the given (path, branch) pairs. branch=None means detached.

    Paths named in `locked` get a `locked` record in the real shape Claude Code
    writes it -- `locked claude session <name> (pid N start ...)`, a reason
    string rather than the bare keyword, which a `== "locked"` match would miss.
    """
    records = [
        "worktree /repo\nHEAD 0000000000000000000000000000000000000\nbranch refs/heads/main"
    ]
    for path, branch in worktrees:
        lines = [f"worktree {path}", "HEAD 1111111111111111111111111111111111111"]
        lines.append(f"branch refs/heads/{branch}" if branch else "detached")
        if path in locked:
            lines.append(
                "locked claude session wt (pid 97626 start Mon Aug 17 15:50:14 2026)"
            )
        records.append("\n".join(lines))
    return "\n\n".join(records) + "\n"


def _git_shim(porcelain: str, common_dir: str = "/nonexistent/repo/.git") -> str:
    """A `git` answering the two calls the digest makes.

    `rev-parse --git-common-dir` is how the digest locates the repo's `.env`,
    and answering it from the shim is what keeps that lookup deterministic: a
    test that let the real git through would resolve to the maintainer's
    actual checkout and read their real `.env`, so the outcome would depend on
    a gitignored file that CI does not have. The default points at a directory
    holding no `.env`, which is the "nothing to source" case every pre-existing
    test wants.
    """
    escaped = porcelain.replace("'", "'\\''")
    return f"""
case "$1 $2 $3" in
  "worktree list --porcelain") printf '%s' '{escaped}' ;;
  "rev-parse --path-format=absolute --git-common-dir") printf '%s\\n' '{common_dir}' ;;
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
    pr_files: dict[int, list[str]] | None = None,
    fail_pr_diff: list[int] | None = None,
    closed_prs: list | None = None,
) -> str:
    """A `gh` that answers the subcommands the digest calls.

    `pr list` is called three times with different `--state` values (open,
    merged, closed), so this shim branches on the whole argument string rather
    than just `$1 $2`. Matching only the subcommand returned the OPEN list for
    every call, which made every open PR look merged and reported every issue as
    having landed. `closed_prs` feeds the `--state closed` call that
    `worktree_is_stale` reads to spot a worktree abandoned behind a
    closed-unmerged PR.

    `pr diff <n> --name-only` answers from `pr_files`, keyed by PR number. The
    match requires `--name-only` literally in the call -- a shim that answered
    from the subcommand alone could not catch the digest asking for the full
    diff (or forgetting the flag entirely) and paying for -- or mis-parsing --
    the whole patch instead of a bare path list.

    `fail_pr_diff` lists PR numbers whose `pr diff --name-only` call exits
    non-zero, simulating a deleted fork head, a rate limit, or a transient
    network error -- the case `undiffable_prs` exists to record rather than
    crash on.
    """
    files_by_pr = {str(k): v for k, v in (pr_files or {}).items()}
    fail_ns = {str(n) for n in (fail_pr_diff or [])}
    return f"""
merged=$(cat <<'EOF'
{json.dumps(merged_prs or [])}
EOF
)
closed=$(cat <<'EOF'
{json.dumps(closed_prs or [])}
EOF
)
pr_files_json=$(cat <<'EOF'
{json.dumps(files_by_pr)}
EOF
)
fail_ns='{" ".join(sorted(fail_ns))}'
case "$*" in
  *"issue list"*) cat <<'EOF'
{json.dumps(issues)}
EOF
    ;;
  *"pr diff "*"--name-only"*)
    n=$(printf '%s' "$*" | awk '{{for(i=1;i<=NF;i++) if($i=="diff"){{print $(i+1); exit}}}}')
    for f in $fail_ns; do
      if [ "$f" = "$n" ]; then echo "gh: unable to diff PR $n" >&2; exit 1; fi
    done
    printf '%s' "$pr_files_json" | jq -r --arg n "$n" '(.[$n] // [])[]'
    ;;
  *"pr diff"*) echo "gh pr diff missing --name-only: $*" >&2; exit 1 ;;
  *"pr list"*"--state merged"*) printf '%s\\n' "$merged" ;;
  *"pr list"*"--state closed"*) printf '%s\\n' "$closed" ;;
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


def _pr(number: int, **over: object) -> dict:
    """A PR as `gh pr list --json ...` returns it to the digest."""
    pr: dict = {
        "number": number,
        "title": f"pr {number}",
        "body": "",
        "headRefName": f"fix/pr-{number}",
        "isDraft": True,
        "mergeable": "MERGEABLE",
    }
    pr.update(over)
    return pr


def test_an_issue_with_several_prs_reports_all_of_them(bin_dir: Path) -> None:
    """The no-auto-close rule means a beta PR and a graduation PR both point at
    one issue. Returning only the first made the second invisible to every
    board pass, and derived the column from an arbitrary one of the two.

    Branch names here deliberately carry NO issue number, so the association is
    proved by the body reference alone -- including the new `Refs` verb, which
    is the only spelling an intermediate PR is allowed."""
    _write_shim(
        bin_dir,
        "gh",
        _gh_shim(
            [_issue(500, labels=[{"name": "bug"}])],
            [
                _pr(501, body="Refs #500", headRefName="fix/beta-work"),
                _pr(
                    502,
                    body="Closes #500",
                    headRefName="fix/graduation",
                    mergeable="CONFLICTING",
                ),
            ],
            [],
        ),
    )

    item = _run(bin_dir)["items"][0]
    assert [p["number"] for p in item["prs"]] == [501, 502]
    assert item["prs"][1]["mergeable"] == "CONFLICTING"
    assert "pr" not in item


def test_a_part_of_pr_is_linked_to_its_issue(bin_dir: Path) -> None:
    """The no-auto-close rule forbids `Closes #N` on an intermediate PR, so a
    beta PR says `Part of #N` (or `tracking #N`, or nothing but a bare `#N`)
    instead. A digest that links by closing keyword only therefore makes that
    PR invisible: #409 reported In Progress while its PR #490 sat approved,
    because `prs_for` resolved to nothing and the column fell through to the
    live worktree. Linkage must match any `#N` reference, not just
    `fixes/closes/resolves/refs`.

    The branch name deliberately carries no issue number, so the association
    is proved by the body reference alone -- the headRefName fallback is
    exercised by its own test and must not mask this one."""
    issue = _issue(409, labels=[{"name": "bug"}])
    pr = _pr(
        490,
        body="Part of #409 — this PR covers PredictionSnapshotStore only.",
        headRefName="feat/prediction-snapshot-store",
        isDraft=False,
        mergeable="MERGEABLE",
    )
    _write_shim(bin_dir, "gh", _gh_shim([issue], [pr], []))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(
            _porcelain(
                ("/repo/wt/409", "feat/issue-409-prediction-snapshot-consolidation")
            )
        ),
    )

    digest = _run(bin_dir)
    item = digest["items"][0]

    assert [p["number"] for p in item["prs"]] == [490]
    assert item["column"] == "In Review"  # was In Progress before the fix
    # ...and the PR is no longer reported as belonging to no issue.
    assert [o for o in digest["orphans"] if o["kind"] == "pr_no_issue"] == []


def test_a_bare_number_reference_links_a_pr_to_its_issue(bin_dir: Path) -> None:
    """`tracking #N` and a bare `#N` are the other spellings the no-auto-close
    rule leaves an intermediate PR with. Any `#N` in the body must link."""
    issue = _issue(633, labels=[{"name": "bug"}])
    pr = _pr(
        634,
        body="First of two PRs tracking #633; the issue stays open until the second lands.",
        headRefName="feat/split-work-a",
        isDraft=False,
    )
    _write_shim(bin_dir, "gh", _gh_shim([issue], [pr], []))

    item = _run(bin_dir)["items"][0]

    assert [p["number"] for p in item["prs"]] == [634]
    assert item["column"] == "In Review"


def test_a_blocked_by_reference_does_not_link_a_pr_to_its_issue(bin_dir: Path) -> None:
    """`Blocked by #N` is a documented convention -- a PR that waits on issue N
    is not part of N's work. The widened `any #N` linkage must not grab it, or
    a PR that merely names its blocker would flip the blocked issue to
    In Review and clear the PR's orphan status."""
    issue = _issue(900, labels=[{"name": "bug"}])
    pr = _pr(
        901,
        body="Blocked by #900 \u2014 landing once the price-provider decision is made.",
        headRefName="feat/price-provider-wait",
        isDraft=True,
    )
    _write_shim(bin_dir, "gh", _gh_shim([issue], [pr], []))

    digest = _run(bin_dir)
    item = digest["items"][0]

    assert item["prs"] == []
    assert item["column"] == "Backlog"
    assert [o for o in digest["orphans"] if o["kind"] == "pr_no_issue"] != []


def test_a_blocked_by_side_reference_still_links_the_prs_own_issue(
    bin_dir: Path,
) -> None:
    """Phrase-stripping removes only the blocker reference, not the whole line:
    "- Blocked by #900 \u2014 part of #905" links the PR to #905 while leaving
    #900 untouched."""
    issues = [
        _issue(900, labels=[{"name": "bug"}]),
        _issue(905, labels=[{"name": "bug"}]),
    ]
    pr = _pr(
        901,
        body="- Blocked by #900 \u2014 part of #905",
        headRefName="feat/prediction-snapshot-store",
        isDraft=False,
    )
    _write_shim(bin_dir, "gh", _gh_shim(issues, [pr], []))

    items = {i["number"]: i for i in _run(bin_dir)["items"]}

    assert [p["number"] for p in items[905]["prs"]] == [901]
    assert items[900]["prs"] == []


@pytest.mark.parametrize(
    "body",
    [
        "Related to #900. Not closing it.",
        "Not blocked by #900 anymore \u2014 resuming.",
        "Depends on #900.",
        "Unblocks #900.",
        "Unblocking #900.",
        "See also #900.",
        "See #900 for the original report.",
        "Relationship to #900.",
        "Unrelated to #900.",
        "Not part of #900 anymore.",
    ],
)
def test_a_non_work_reference_does_not_link_a_pr_to_its_issue(
    bin_dir: Path, body: str
) -> None:
    """Phrases that name an issue without claiming to work on it must not link
    -- real bodies say "Related to #403. Not closing it", "unblocks #485",
    "unrelated to #402". Linking on them would flip an unrelated issue to
    In Review and clear the PR's orphan status."""
    issue = _issue(900, labels=[{"name": "bug"}])
    pr = _pr(901, body=body, headRefName="feat/price-provider-wait", isDraft=True)
    _write_shim(bin_dir, "gh", _gh_shim([issue], [pr], []))

    digest = _run(bin_dir)
    item = digest["items"][0]

    assert item["prs"] == []
    assert item["column"] == "Backlog"
    assert [o for o in digest["orphans"] if o["kind"] == "pr_no_issue"] != []


def test_open_pr_list_actually_requests_isdraft(bin_dir: Path) -> None:
    """`prs_for` emits `isDraft` on every PR object, but jq can only surface a
    field the `gh pr list --json ...` call actually requested -- a fixture
    that hands `isDraft` over regardless of the requested field list (like
    `_gh_shim` does) cannot catch a `--json` selection that omits it. This
    shim inspects the real invocation instead of trusting the fixture: it
    fails loudly, naming the missing field, if the open-PR `gh pr list` call
    does not ask for `isDraft` -- and only then hands back a PR whose
    `isDraft` is `False`, so the assertion below also proves the value flows
    through end to end rather than resolving to a silent null."""
    issue = _issue(650, labels=[{"name": "bug"}])
    pr = _pr(651, body="Fixes #650", isDraft=False)
    shim = f"""
case "$*" in
  *"issue list"*) cat <<'EOF'
{json.dumps([issue])}
EOF
    ;;
  *"pr diff "*"--name-only"*) : ;;
  *"pr list"*"--state merged"*) printf '%s\\n' '[]' ;;
  *"pr list"*"--state closed"*) printf '%s\\n' '[]' ;;
  *"pr list"*)
    case "$*" in
      *isDraft*) : ;;
      *) echo "gh pr list --json is missing isDraft: $*" >&2; exit 1 ;;
    esac
    cat <<'EOF'
{json.dumps([pr])}
EOF
    ;;
  *"project item-list"*) printf '%s\\n' '{{"items": []}}' ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""
    _write_shim(bin_dir, "gh", shim)

    item = _run(bin_dir)["items"][0]
    assert item["prs"][0]["isDraft"] is False


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


def test_board_awaiting_does_not_promote_a_backlog_item(bin_dir: Path) -> None:
    """#703: a raw "to consider" enhancement with `Awaiting: discussion` on its
    card and nothing else -- no worktree, no PR, no `analyzed` label. The wait
    is a floor-lower, not a set (#707 says "pulls BACK to Analysis"), so from
    Backlog it is a no-op. Before this, `column` came back `Analysis`, which did
    not match the card's `Backlog`, so `move_card` yanked the card to Analysis
    minutes after a human moved it back -- forever.
    """
    issue = _issue(703, labels=[{"name": "enhancement"}])
    board = [
        {
            "content": {"number": 703},
            "status": "Backlog",
            "priority": "P3",
            "awaiting": "discussion",
        }
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], board))

    item = _run(bin_dir)["items"][0]

    assert item["column"] == "Backlog"
    assert item["board_status"] == "Backlog"  # no mismatch -> no move_card fight
    assert item["awaiting"] == "discussion"  # the wait is still recorded


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


def test_open_blocked_by_reference_is_never_ready(bin_dir: Path) -> None:
    """The blocker (#500) is itself open, so the wait is real."""
    issue = _issue(702, labels=[{"name": "analyzed"}], body="Blocked by #500\n")
    blocker = _issue(500)
    board = [{"content": {"number": 702}, "priority": "P1"}]
    _write_shim(bin_dir, "gh", _gh_shim([issue, blocker], [], board))

    item = next(i for i in _run(bin_dir)["items"] if i["number"] == 702)
    assert item["column"] == "Analysis"
    assert item["blocked_by"] == [500]
    assert item["blocked_by_open"] == [500]
    assert item["blocked"] is True


def test_a_bulleted_blocked_by_line_still_counts(bin_dir: Path) -> None:
    """Anchoring to the line start must still allow the markdown form people
    actually write."""
    issue = _issue(705, labels=[{"name": "analyzed"}], body="- Blocked by #500\n")
    board = [{"content": {"number": 705}, "priority": "P1"}]
    _write_shim(bin_dir, "gh", _gh_shim([issue, _issue(500)], [], board))

    item = next(i for i in _run(bin_dir)["items"] if i["number"] == 705)
    assert item["blocked_by"] == [500]
    assert item["blocked"] is True


def test_a_negated_blocked_by_is_not_a_blocker(bin_dir: Path) -> None:
    """ "not blocked by #500 anymore" and "no longer blocked by #500" are the
    natural way to update an issue once its blocker resolves — so a free
    substring scan fires exactly when the blocker is GONE.

    Matched per line and anchored to the line start, which rejects these without
    a negation blacklist that would only cover the phrasings someone thought of.
    This was inert on main (`blocked_by` was extracted and never used); gating
    `column()` on it is what gave the bad parse teeth.
    """
    for body in (
        "This is not blocked by #500 anymore.\n",
        "We are no longer blocked by #500.\n",
        "Was blocked by #500 but that shipped.\n",
    ):
        issue = _issue(706, labels=[{"name": "analyzed"}], body=body)
        board = [{"content": {"number": 706}, "priority": "P1"}]
        _write_shim(bin_dir, "gh", _gh_shim([issue, _issue(500)], [], board))

        item = next(i for i in _run(bin_dir)["items"] if i["number"] == 706)
        assert item["blocked_by"] == [], body
        assert item["blocked"] is False, body
        assert item["column"] == "Ready for Dev", body


def test_an_incidental_mid_sentence_mention_does_not_reclassify(bin_dir: Path) -> None:
    """`$blocked` is tested before the analyzed/priority branch, so an untriaged
    issue that merely mentions a blocker in prose would move Backlog -> Analysis
    with no human triage behind it."""
    issue = _issue(707, labels=[], body="Might be blocked by #500, not sure yet.\n")
    _write_shim(bin_dir, "gh", _gh_shim([issue, _issue(500)], [], []))

    item = next(i for i in _run(bin_dir)["items"] if i["number"] == 707)
    assert item["blocked"] is False
    assert item["column"] == "Backlog"


def test_closed_blocked_by_reference_does_not_block(bin_dir: Path) -> None:
    """A `Blocked by #N` line is never edited out once N lands, so a pure text
    scan pins the item out of Ready for Dev forever.

    That is the same failure this script exists to fix, pointing the other way:
    an item reading wrong relative to its real state. Only blockers still on the
    open-issue list count. The reference stays visible in `blocked_by`.
    """
    issue = _issue(703, labels=[{"name": "analyzed"}], body="Blocked by #499\n")
    board = [{"content": {"number": 703}, "priority": "P1"}]
    # #499 is absent from the open-issue list, i.e. closed.
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], board))

    item = _run(bin_dir)["items"][0]
    assert item["blocked_by"] == [499]
    assert item["blocked_by_open"] == []
    assert item["blocked"] is False
    assert item["column"] == "Ready for Dev"


def test_a_wait_outranks_a_live_worktree(
    bin_dir: Path,
) -> None:
    """#707 reverses Task 3's Status/Awaiting orthogonality for the
    worktree-vs-wait case: a recorded wait (here `needs-debug-log` ->
    `reporter`) pulls the item back to Analysis even with a worktree checked
    out, because unsettled scope must not read as progress. The worktree is
    still reported alongside so active undelivered code stays visible -- the
    wait changes the column, not the evidence.
    """
    issue = _issue(704, labels=[{"name": "needs-debug-log"}])
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], []))
    _write_shim(
        bin_dir, "git", _git_shim(_porcelain(("/repo/wt/704", "fix/issue-704-live")))
    )

    item = _run(bin_dir)["items"][0]

    assert item["column"] == "Analysis"
    assert item["awaiting"] == "reporter"
    # The code is still visible — the wait is reported, not the column erasing it.
    assert item["worktree"] == "/repo/wt/704"
    assert item["worktree_branch"] == "fix/issue-704-live"
    assert item["stale_worktree"] is False


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


def test_worktree_abandoned_behind_a_closed_unmerged_pr_is_stale(
    bin_dir: Path,
) -> None:
    """#428: the branch never merged, but its PR (#437) was closed unmerged and
    a differently-named branch shipped the issue. A worktree left on that dead
    branch is an abandoned attempt, not resumable work -- the same as a merged
    branch for staleness, with a reason string that says which."""
    issue = _issue(428, labels=[{"name": "enhancement"}])
    closed = [
        {
            "number": 437,
            "headRefName": "feat/issue-428-consumption-forecast-series",
            "mergedAt": None,
        }
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], [], closed_prs=closed))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(
            _porcelain(("/repo/wt/428", "feat/issue-428-consumption-forecast-series"))
        ),
    )

    item = _run(bin_dir)["items"][0]

    assert item["stale_worktree"] is True
    assert item["stale_worktree_reason"] == "was the head of closed-unmerged PR #437"
    assert item["column"] != "In Progress"


def test_a_merged_pr_on_the_issue_branch_reads_as_in_verification(
    bin_dir: Path,
) -> None:
    """#428/#705: the shipping PR merged on `feat/issue-428-consumption-overlay`
    and, under the no-auto-close rule, its body links the issue only as a bare
    `#428` -- no work verb. Branch convention plus a non-cross-ref body mention
    of the same number is enough to place the issue In Verification, so a board
    pass stops reading a shipped-to-beta issue as un-started."""
    issue = _issue(428, labels=[{"name": "enhancement"}])
    merged = [
        {
            "number": 705,
            "headRefName": "feat/issue-428-consumption-overlay",
            "body": "Redesign from the discussion on #428. Ships the overlay.",
        }
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))

    item = _run(bin_dir)["items"][0]

    assert item["merged_pr"] == 705
    assert item["merged_prs"] == [705]
    assert item["column"] == "In Verification"


def test_a_merged_pr_on_the_issue_branch_with_only_a_cross_ref_does_not_flip(
    bin_dir: Path,
) -> None:
    """The `mentions` guard: a merged PR on `fix/issue-403-logging` whose body
    only cross-references #403 ("Related to #403. Not closing it") still must
    not move #403 -- branch convention alone is not trusted on the merged path,
    the same caution `test_a_merged_cross_ref_does_not_move_an_issue...` pins."""
    issue = _issue(403, labels=[{"name": "bug"}])
    merged = [
        {
            "number": 453,
            "headRefName": "fix/issue-403-logging",
            "body": "Related to #403. Not closing it -- leaving it open until "
            "#456 and #457 land.",
        }
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))

    item = _run(bin_dir)["items"][0]

    assert item["merged_pr"] is None
    assert item["column"] != "In Verification"


def test_last_analyze_comment_reports_the_trigger_age(bin_dir: Path) -> None:
    """`refire_analyze` and the no-double-spend guard on `autonomous_analyze`
    both read this: the most recent `@claude-bot analyze` comment and how long
    ago it landed. Absent when the issue was never analyzed."""
    never = _issue(600, labels=[{"name": "bug"}])
    _write_shim(bin_dir, "gh", _gh_shim([never], [], []))
    assert _run(bin_dir)["items"][0]["last_analyze_comment"] is None

    fired = _issue(
        601,
        labels=[{"name": "bug"}],
        comments=[
            {
                "body": "@claude-bot analyze",
                "author": {"login": "bess-product-owner"},
                "createdAt": "2000-01-01T00:00:00Z",
            }
        ],
    )
    _write_shim(bin_dir, "gh", _gh_shim([fired], [], []))
    lac = _run(bin_dir)["items"][0]["last_analyze_comment"]
    assert lac is not None
    assert lac["hours"] > 24 and lac["days"] > 1


def test_a_draft_pr_with_no_review_is_in_progress_not_in_review(bin_dir: Path) -> None:
    """#707 / #162: a draft PR linked to its own issue has not entered the
    review loop -- the branch and PR exist but nothing is reviewing them, so
    the issue is In Progress. Only a non-draft PR promotes it to In Review."""
    issue = _issue(162, labels=[{"name": "enhancement"}])
    prs = [
        _pr(
            167,
            body="Closes #162",
            headRefName="feat/external-solar-mode",
            isDraft=True,
        )
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], prs, []))

    item = _run(bin_dir)["items"][0]

    assert [p["number"] for p in item["prs"]] == [167]
    assert item["prs"][0]["isDraft"] is True
    assert item["column"] == "In Progress"


def test_a_scratch_prefixed_worktree_does_not_join_an_issue(bin_dir: Path) -> None:
    """#707 / #602: `pin-`, `design-` and `bench-` worktrees are scenario
    pinning and design scratch, not implementation branches. Fuzzy-matching
    them to an issue by embedded number made a stray pin worktree pin the
    issue to In Progress for good."""
    issue = _issue(466, labels=[{"name": "bug"}])
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], []))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(
            _porcelain(
                ("/repo/wt/design-466-idle-tie-break", "design-466-idle-tie-break")
            )
        ),
    )

    item = _run(bin_dir)["items"][0]

    assert item["worktree"] is None
    assert item["column"] == "Backlog"


def test_a_merged_fix_outranks_a_stray_pin_worktree(bin_dir: Path) -> None:
    """#707 / #602: the fix merged, but a leftover `pin-<n>-...` worktree
    (whose own branch never became a PR, so stale-detection misses it) must
    not keep reading as live work. With the scratch prefix excluded the merged
    PR wins and the issue is In Verification."""
    issue = _issue(602, labels=[{"name": "bug"}])
    merged = [_pr(693, body="Closes #602", headRefName="fix/issue-602-terminal-value")]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(
            _porcelain(
                ("/repo/wt/pin-602-evening-carry", "worktree-pin-602-evening-carry")
            )
        ),
    )

    item = _run(bin_dir)["items"][0]

    assert item["worktree"] is None
    assert item["column"] == "In Verification"


def test_a_merged_pr_with_the_issue_open_is_in_verification(bin_dir: Path) -> None:
    """Merged to main, not yet in a stable release. The digest used to leave
    this period unnamed, so a fix awaiting real-world confirmation sat in
    whatever column it happened to be in."""
    issue = _issue(510, labels=[{"name": "bug"}, {"name": "analyzed"}])
    merged = [_pr(511, body="Closes #510", headRefName="fix/issue-510")]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))

    assert _run(bin_dir)["items"][0]["column"] == "In Verification"


def test_active_follow_up_work_over_a_merged_pr_is_in_progress(bin_dir: Path) -> None:
    """#707: a merged intermediate PR plus a genuine (non-scratch) live
    worktree is active follow-up work, not verified work. In Progress is
    checked before In Verification so the branch does not read as done. The
    #602 case does not hit this -- its worktree is a `pin-` scratch and is
    excluded from the join entirely."""
    issue = _issue(530, labels=[{"name": "bug"}])
    merged = [_pr(531, body="Part of #530", headRefName="fix/issue-530-a")]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(_porcelain(("/repo/wt/530", "fix/issue-530-b"))),
    )

    item = _run(bin_dir)["items"][0]
    assert item["worktree"] == "/repo/wt/530"
    assert item["column"] == "In Progress"


def test_a_merged_intermediate_pr_keeps_the_issue_in_verification(
    bin_dir: Path,
) -> None:
    """A merged intermediate PR (`Part of #N`) means the work has landed on main
    and is awaiting graduation -- In Verification, never re-dispatchable.

    This is the no-auto-close contract: beta PRs omit `Closes #N` until the
    fix graduates, so `Part of`/`Refs` are how a fix normally reads on merge.
    When the merged scan was narrowed to closing keywords only, issues whose
    fix had already merged (#643 -> #675, #571 -> #584, #592 -> #619, #666 ->
    #672, #542 -> #591) fell through to Backlog / Ready for Dev, so a backlog
    pass could re-dispatch an issue whose partial work already landed."""
    issue = _issue(517, labels=[{"name": "bug"}, {"name": "analyzed"}])
    merged = [_pr(518, body="Part of #517", headRefName="fix/issue-517-a")]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))

    item = _run(bin_dir)["items"][0]

    assert item["merged_pr"] == 518
    assert item["merged_prs"] == [518]
    assert item["column"] == "In Verification"


def test_a_merged_cross_ref_does_not_move_an_issue_to_in_verification(
    bin_dir: Path,
) -> None:
    """The merged scan is deliberately narrower than the open-PR one: it uses
    work verbs only (`fixes/closes/resolves/refs/part of/tracking`), never bare
    `#N`. A merged PR that merely names another issue -- "Related to #403. Not
    closing it -- leaving it open until #456 and #457 are also resolved" --
    must not flip that issue to In Verification."""
    issue = _issue(403, labels=[{"name": "bug"}])
    merged = [
        _pr(
            453,
            body="Related to #403. Not closing it -- leaving it open until "
            "#456 and #457 are also resolved.",
            headRefName="fix/issue-403-logging",
        )
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))

    item = _run(bin_dir)["items"][0]

    assert item["merged_pr"] is None
    assert item["merged_prs"] == []
    assert item["column"] != "In Verification"


def test_a_backticked_worked_example_does_not_flip_an_issue(bin_dir: Path) -> None:
    """Inline-code spans in a PR body are examples, not linkage declarations.
    PR #679 explained its own linkage fix with the literal line
    `- Blocked by #100 -- part of #409` (a worked example inside backticks),
    and the merged scan read `part of #409` as a work reference -- bouncing
    issue #409 to In Verification for work it never did. A real `Part of #N`
    intermediate PR
    (test_a_merged_intermediate_pr_keeps_the_issue_in_verification) carries
    no code markup, so stripping backticked spans before scanning leaves that
    linkage intact."""
    issue = _issue(409, labels=[{"name": "bug"}])
    merged = [
        _pr(
            679,
            body="Stripping the phrase (not the line) keeps combined "
            "references like `- Blocked by #100 -- part of #409` working.",
            headRefName="fix/backlog-digest-linkage",
        )
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [], merged))

    item = _run(bin_dir)["items"][0]

    assert item["merged_pr"] is None
    assert item["merged_prs"] == []
    assert item["column"] != "In Verification"


def test_a_backticked_worked_example_does_not_link_an_open_pr(
    bin_dir: Path,
) -> None:
    """The same rule holds for the OPEN-PR scan, which is a separate code path
    (`linkage_body`/`pr_matches_issue`) from the merged one. `part of #N` is
    deliberately not a stripped cross-reference phrase -- it is real linkage on
    a real intermediate PR -- so without code-span stripping a PR that merely
    QUOTES that phrase as an example links itself to the quoted issue and
    reports it In Review. PR #684 did exactly that to issue #409 while
    describing the merged-scan fix."""
    issue = _issue(409, labels=[{"name": "bug"}])
    pr = _pr(
        684,
        body="Stripping the phrase (not the line) keeps combined "
        "references like `- Blocked by #100 -- part of #409` working.",
        headRefName="fix/backlog-dispatch-and-linkage-regex",
        isDraft=False,
        mergeable="MERGEABLE",
    )
    _write_shim(bin_dir, "gh", _gh_shim([issue], [pr], []))

    digest = _run(bin_dir)
    item = digest["items"][0]

    assert item["prs"] == []
    assert item["column"] != "In Review"


def test_an_open_pr_outranks_a_merged_one(bin_dir: Path) -> None:
    """A graduation PR still open and out of draft means the work is In Review,
    not verified."""
    issue = _issue(512, labels=[{"name": "bug"}])
    prs = [_pr(514, body="Closes #512", headRefName="fix/issue-512-b", isDraft=False)]
    merged = [_pr(513, body="Refs #512", headRefName="fix/issue-512-a")]
    _write_shim(bin_dir, "gh", _gh_shim([issue], prs, [], merged))

    assert _run(bin_dir)["items"][0]["column"] == "In Review"


def test_a_non_draft_pr_still_reports_in_review_when_blocked(bin_dir: Path) -> None:
    """A PR that is out of draft is genuinely in the review loop, so the phase
    is In Review even with a block recorded -- the block is reported alongside
    (`blocked`) and the rhythm pass ranks it, it does not erase the column."""
    issue = _issue(515, labels=[{"name": "bug"}, {"name": "blocked"}])
    prs = [_pr(516, body="Refs #515", headRefName="fix/issue-515", isDraft=False)]
    _write_shim(bin_dir, "gh", _gh_shim([issue], prs, []))

    item = _run(bin_dir)["items"][0]
    assert item["column"] == "In Review"
    assert item["blocked"] is True


def test_a_draft_pr_carrying_a_wait_is_pulled_back_to_analysis(bin_dir: Path) -> None:
    """#707 / #162: a draft PR has not entered review, so a recorded wait
    (here the `blocked` label) outranks it and the issue reports Analysis. The
    PR is still reported so the branch stays visible."""
    issue = _issue(521, labels=[{"name": "bug"}, {"name": "blocked"}])
    prs = [_pr(522, body="Refs #521", headRefName="fix/issue-521", isDraft=True)]
    _write_shim(bin_dir, "gh", _gh_shim([issue], prs, []))

    item = _run(bin_dir)["items"][0]
    assert item["column"] == "Analysis"
    assert item["blocked"] is True
    assert [p["number"] for p in item["prs"]] == [522]


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

    # `needs-debug-log` sets `awaiting: reporter`. It does NOT move the column:
    # the wait override is a floor-lower (#707 says "pulls BACK to Analysis"),
    # and there is nothing to pull back -- no worktree, no PR, no `analyzed`
    # label -- so the item stays in Backlog. The nudge/park timers key off
    # `.awaiting`, not the column, so nothing downstream regresses.
    assert digest["items"][0]["column"] == "Backlog"
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
    assert [p["number"] for p in item["prs"]] == [610]
    assert item["prs"][0]["mergeable"] == "CONFLICTING"
    assert item["column"] == "In Review"


def test_mergeable_is_requeried_until_it_leaves_unknown(bin_dir: Path) -> None:
    """GitHub computes `mergeable` LAZILY: the first query on a cold PR returns
    UNKNOWN and triggers the computation, so a single query reports UNKNOWN as
    if it were a verdict (measured on #490: six consecutive UNKNOWN passes).
    The digest must re-query until the value settles, exactly as sweep-prs
    does. This shim returns UNKNOWN on the first `pr list` and MERGEABLE on
    the second, so only a re-query produces the asserted value."""
    issue = _issue(801, labels=[{"name": "bug"}])
    # `Refs #N` (not `Part of #N`): this test isolates the mergeable retry,
    # and `Refs` already links under both the old and new linkage rules.
    unknown_pr = _pr(
        802, body="Refs #801", headRefName="fix/part-a", mergeable="UNKNOWN"
    )
    mergeable_pr = dict(unknown_pr, mergeable="MERGEABLE")
    counter = bin_dir / "gh_pr_list_calls"
    shim = f"""
case "$*" in
  *"issue list"*) cat <<'EOF'
{json.dumps([issue])}
EOF
    ;;
  *"pr diff "*"--name-only"*) : ;;
  *"pr list"*"--state merged"*) printf '%s\\n' '[]' ;;
  *"pr list"*"--state closed"*) printf '%s\\n' '[]' ;;
  *"pr list"*)
    if [ -f '{counter}' ]; then
      cat <<'EOF'
{json.dumps([mergeable_pr])}
EOF
    else
      touch '{counter}'
      cat <<'EOF'
{json.dumps([unknown_pr])}
EOF
    fi
    ;;
  *"project item-list"*) printf '%s\\n' '{{"items": []}}' ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""
    _write_shim(bin_dir, "gh", shim)

    item = _run(bin_dir, MERGE_RETRY_SLEEP="0")["items"][0]

    assert item["prs"][0]["mergeable"] == "MERGEABLE"


def test_mergeable_still_unknown_after_retries_is_reported_null(bin_dir: Path) -> None:
    """If GitHub has still not computed `mergeable` inside the retry budget,
    the digest must not pass UNKNOWN through as if it were a definite state --
    it emits null, so no consumer can read it as a verdict."""
    issue = _issue(803, labels=[{"name": "bug"}])
    pr = _pr(804, body="Refs #803", headRefName="fix/part-b", mergeable="UNKNOWN")
    _write_shim(bin_dir, "gh", _gh_shim([issue], [pr], []))

    item = _run(bin_dir, MERGE_RETRY_SLEEP="0")["items"][0]

    assert item["prs"][0]["mergeable"] is None


def test_issue_matched_by_two_prs_emits_one_item_with_both_prs(
    bin_dir: Path,
) -> None:
    """Regression test for a real bug found while implementing this script:
    the first-draft jq used `select(...) // null` to pick "the" PR for an
    issue. In jq, `EXPR // null` only substitutes `null` when EXPR produces
    *no* output — with one match it returns that match, but with two or more
    matches `select(...)` is a stream and the whole expression becomes a
    stream of PR objects rather than a single scalar. Downstream that stream
    gets cross-multiplied into the `items[]` comprehension, silently emitting
    one duplicate item row per extra match instead of joining all of them onto
    one item. This issue has two open PRs that both match it (one by
    `Fixes #N` in the body, one by headRefName pattern), which triggers the
    bug if `prs_for` regresses back to a `// null`-style single-scalar pick."""
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
    assert [p["number"] for p in item["prs"]] == [620, 621]


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
    assert [p["number"] for p in item["prs"]] == [
        630
    ], "PR must still join the issue via headRefName"
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


def _dotenv(bin_dir: Path, tmp_path: Path, contents: str) -> None:
    """Point the git shim at a repo root holding the given `.env`."""
    repo_root = tmp_path / "checkout"
    repo_root.mkdir(exist_ok=True)
    (repo_root / ".env").write_text(contents)
    _write_shim(
        bin_dir, "git", _git_shim(_porcelain(), common_dir=str(repo_root / ".git"))
    )


def test_project_number_is_read_from_dotenv(bin_dir: Path, tmp_path: Path) -> None:
    """The whole point: an unattended pass exports nothing, so the digest has
    to find PROJECT_NUMBER itself or it never runs at all. `.env` is
    gitignored, so no caller inherits it."""
    _write_shim(bin_dir, "gh", _gh_shim([], [], []))
    _dotenv(bin_dir, tmp_path, "PROJECT_NUMBER=1\nBESS_PO_TOKEN=tok\n")

    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    env.pop("PROJECT_NUMBER", None)
    proc = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["counts"]["issues"] == 0


def test_environment_wins_over_dotenv(bin_dir: Path, tmp_path: Path) -> None:
    """An explicit PROJECT_NUMBER must not be overwritten by the file, or the
    variable becomes un-overridable and a pinned value silently reads the
    maintainer's real board."""
    _dotenv(bin_dir, tmp_path, "PROJECT_NUMBER=1\n")
    # A `gh` that refuses any project but 7. The assertion is that the digest
    # asked for 7, which is observable nowhere except in the call itself.
    _write_shim(
        bin_dir,
        "gh",
        'case "$*" in\n'
        '  *"project item-list 7"*) echo \'{"items": []}\' ;;\n'
        '  *"project item-list"*) echo "wrong project: $*" >&2; exit 1 ;;\n'
        '  *"issue list"*|*"pr list"*) echo \'[]\' ;;\n'
        '  *) echo "unexpected gh call: $*" >&2; exit 1 ;;\n'
        "esac\n",
    )

    digest = _run(bin_dir, PROJECT_NUMBER="7")

    assert digest["counts"]["issues"] == 0


def test_a_dotenv_without_the_variable_still_fails_loudly(
    bin_dir: Path, tmp_path: Path
) -> None:
    """A `.env` that exists but carries no PROJECT_NUMBER must not be mistaken
    for a configured one."""
    _write_shim(bin_dir, "gh", _gh_shim([], [], []))
    _dotenv(bin_dir, tmp_path, "BESS_PO_TOKEN=tok\n")

    result = _run_expect_failure(bin_dir)

    assert result.returncode != 0
    assert "PROJECT_NUMBER" in result.stderr


def test_board_status_reports_the_cards_current_column(bin_dir: Path) -> None:
    """`column` is where the evidence says the card belongs; `board_status` is
    where it actually sits. The board verb reconciles the two, so the digest
    has to carry both — otherwise reconciling means a second API call by
    hand, which is the one thing this script exists to prevent."""
    issue = _issue(602, labels=[{"name": "bug"}])
    card = {"content": {"number": 602}, "status": "Ready for Dev", "priority": "P1"}
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [card]))

    item = _run(bin_dir)["items"][0]

    assert item["board_status"] == "Ready for Dev"
    assert item["column"] == "Backlog"


def test_issue_with_no_card_reports_null_status_and_is_an_orphan(
    bin_dir: Path,
) -> None:
    """An off-board issue carries no Priority, and `Ready for Dev` requires
    one — so it can never become dispatchable however well it is analysed. It
    has to be surfaced, not read as a quiet Backlog item."""
    issue = _issue(624, labels=[{"name": "bug"}])
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    digest = _run(bin_dir)

    assert digest["items"][0]["board_status"] is None
    orphans = [o for o in digest["orphans"] if o["kind"] == "issue_no_card"]
    assert [o["ref"] for o in orphans] == ["624"]


def test_pr_cards_are_emitted_separately_from_issue_cards(bin_dir: Path) -> None:
    """`content.type` is the load-bearing bit, and it is confirmed against a
    real card rather than assumed: an added PR reports "PullRequest" with
    number/title/url/repository alongside it.

    Board membership for PRs is what gives a decision about a PR somewhere to
    live -- without it "#437 is lower priority" had nowhere to be recorded, so
    every rhythm pass re-reported it as due.
    """
    issue = _issue(601)
    cards = [
        {
            "content": {"number": 601, "type": "Issue"},
            "status": "Backlog",
            "priority": "P2",
        },
        {
            "content": {"number": 437, "type": "PullRequest"},
            "status": "In Review",
            "priority": "P4",
        },
        {
            "content": {"number": 167, "type": "PullRequest"},
            "status": "Backlog",
            "awaiting": "discussion",
        },
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], cards))

    digest = _run(bin_dir)

    assert digest["pr_board"] == [
        {
            "number": 437,
            "board_status": "In Review",
            "priority": "P4",
            "awaiting": None,
        },
        {
            "number": 167,
            "board_status": "Backlog",
            "priority": None,
            "awaiting": "discussion",
        },
    ]
    # The issue card is untouched by the split and still drives the item.
    assert digest["items"][0]["priority"] == "P2"


def test_pr_board_is_empty_when_no_prs_are_carded(bin_dir: Path) -> None:
    issue = _issue(601)
    card = {"content": {"number": 601, "type": "Issue"}, "status": "Backlog"}
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [card]))

    assert _run(bin_dir)["pr_board"] == []


def test_a_closed_prs_card_is_flagged_as_a_stale_pr_card(bin_dir: Path) -> None:
    """#707 / #638: a PR card exists only to carry a deferral decision while
    the PR is open. When the PR is closed unmerged it is in neither the open
    nor the merged list, and nothing -- not `items`, not the rest of
    `orphans` -- ever reconciles it, so its card sits in whatever column it
    was last in. Surface it so the board verb can archive it."""
    issue = _issue(601)
    cards = [
        {"content": {"number": 601, "type": "Issue"}, "status": "Backlog"},
        {"content": {"number": 638, "type": "PullRequest"}, "status": "In Review"},
    ]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], cards))

    orphans = [o for o in _run(bin_dir)["orphans"] if o["kind"] == "stale_pr_card"]
    assert [o["ref"] for o in orphans] == ["638"]
    assert "closed" in orphans[0]["detail"]


def test_a_merged_prs_card_not_marked_done_is_a_stale_pr_card(bin_dir: Path) -> None:
    """#707: a PR card whose PR has merged is equally stale unless the card is
    already in Done -- the deferral it recorded is moot once the PR lands."""
    issue = _issue(601)
    cards = [
        {"content": {"number": 601, "type": "Issue"}, "status": "Backlog"},
        {"content": {"number": 640, "type": "PullRequest"}, "status": "In Review"},
    ]
    merged = [_pr(640, body="Closes #601", headRefName="fix/issue-601")]
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], cards, merged))

    orphans = [o for o in _run(bin_dir)["orphans"] if o["kind"] == "stale_pr_card"]
    assert [o["ref"] for o in orphans] == ["640"]
    assert "merged" in orphans[0]["detail"]


def test_an_open_prs_card_is_not_a_stale_pr_card(bin_dir: Path) -> None:
    """The carve-out: while the PR is genuinely open its card is doing its job
    (carrying a Priority / Awaiting decision) and must not be flagged."""
    issue = _issue(601)
    cards = [
        {"content": {"number": 601, "type": "Issue"}, "status": "Backlog"},
        {"content": {"number": 642, "type": "PullRequest"}, "status": "In Review"},
    ]
    prs = [_pr(642, body="Refs #601", headRefName="fix/issue-601")]
    _write_shim(bin_dir, "gh", _gh_shim([issue], prs, cards))

    orphans = [o for o in _run(bin_dir)["orphans"] if o["kind"] == "stale_pr_card"]
    assert orphans == []


def test_a_pr_card_already_in_done_is_not_flagged(bin_dir: Path) -> None:
    """Done is the terminal resting column -- neither a merged nor a
    closed-unmerged PR card there is noise worth surfacing."""
    issue = _issue(601)
    cards = [
        {"content": {"number": 601, "type": "Issue"}, "status": "Backlog"},
        {"content": {"number": 644, "type": "PullRequest"}, "status": "Done"},
        {"content": {"number": 645, "type": "PullRequest"}, "status": "Done"},
    ]
    merged = [_pr(644, body="Closes #601", headRefName="fix/issue-601")]
    # #645 is neither open nor merged -> closed unmerged, but it is already in Done.
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], cards, merged))

    orphans = [o for o in _run(bin_dir)["orphans"] if o["kind"] == "stale_pr_card"]
    assert orphans == []


def test_a_card_for_a_closed_issue_is_a_stale_issue_card(bin_dir: Path) -> None:
    """#707: the mirror of `issue_no_card`. `items` iterates only open issues,
    so the card of a closed issue is reconciled by nothing and sits in
    whatever column it held -- surface it so the board verb can move it to
    Done."""
    open_issue = _issue(601)
    cards = [
        {"content": {"number": 601, "type": "Issue"}, "status": "Backlog"},
        {"content": {"number": 555, "type": "Issue"}, "status": "In Review"},
    ]
    _write_shim(bin_dir, "gh", _gh_shim([open_issue], [], cards))

    orphans = [o for o in _run(bin_dir)["orphans"] if o["kind"] == "stale_issue_card"]
    assert [o["ref"] for o in orphans] == ["555"]
    assert "closed" in orphans[0]["detail"]


def test_a_closed_issue_card_already_in_done_is_not_flagged(bin_dir: Path) -> None:
    open_issue = _issue(601)
    cards = [
        {"content": {"number": 601, "type": "Issue"}, "status": "Backlog"},
        {"content": {"number": 556, "type": "Issue"}, "status": "Done"},
    ]
    _write_shim(bin_dir, "gh", _gh_shim([open_issue], [], cards))

    orphans = [o for o in _run(bin_dir)["orphans"] if o["kind"] == "stale_issue_card"]
    assert orphans == []


def test_an_open_issue_card_is_not_a_stale_issue_card(bin_dir: Path) -> None:
    issue = _issue(601)
    card = {"content": {"number": 601, "type": "Issue"}, "status": "Backlog"}
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [card]))

    orphans = [o for o in _run(bin_dir)["orphans"] if o["kind"] == "stale_issue_card"]
    assert orphans == []


def test_a_locked_worktree_is_reported_as_locked(bin_dir: Path) -> None:
    """The lock is the liveness signal `claude agents` cannot provide: it lists
    background agents only, so a foreground `/implement-issue` is invisible and
    its worktree reads as abandoned."""
    issue = _issue(624)
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(
            _porcelain(
                ("/repo/worktrees/issue-624", "fix/issue-624-pwl"),
                locked=("/repo/worktrees/issue-624",),
            )
        ),
    )

    item = _run(bin_dir)["items"][0]

    assert item["worktree"] == "/repo/worktrees/issue-624"
    assert item["worktree_locked"] is True
    # ...and the name-matched session is still null, which is the whole point.
    assert item["session"] is None


def test_an_unlocked_worktree_is_reported_as_unlocked(bin_dir: Path) -> None:
    issue = _issue(625)
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))
    _write_shim(
        bin_dir,
        "git",
        _git_shim(_porcelain(("/repo/worktrees/issue-625", "fix/issue-625"))),
    )

    item = _run(bin_dir)["items"][0]

    assert item["worktree"] == "/repo/worktrees/issue-625"
    assert item["worktree_locked"] is False


def test_issue_with_a_card_is_not_an_orphan(bin_dir: Path) -> None:
    issue = _issue(602)
    card = {"content": {"number": 602}, "status": "Backlog", "priority": "P1"}
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], [card]))

    digest = _run(bin_dir)

    assert [o for o in digest["orphans"] if o["kind"] == "issue_no_card"] == []


def test_resume_handoffs_are_counted(bin_dir: Path) -> None:
    """A session that died twice is telling you something -- but nothing
    counted, so nothing could act on it. The marker is an HTML comment so the
    handoff still reads as prose on GitHub."""
    _write_shim(
        bin_dir,
        "gh",
        _gh_shim(
            [
                _issue(
                    520,
                    labels=[{"name": "bug"}],
                    comments=[
                        _comment(
                            "bess-developer",
                            "Resuming implementation.\n<!-- resume-handoff -->",
                        ),
                        _comment("johanzander", "thanks"),
                        _comment(
                            "bess-developer",
                            "Resuming implementation.\n<!-- resume-handoff -->",
                        ),
                    ],
                )
            ],
            [],
            [],
        ),
    )

    assert _run(bin_dir)["items"][0]["resume_count"] == 2


def test_in_flight_files_map_paths_to_the_prs_touching_them(bin_dir: Path) -> None:
    """The collision gate needs to know what is already being edited. Half of
    that is exact -- the changed-file set of every open PR -- and only the
    candidate's own touch-set has to be predicted."""
    _write_shim(
        bin_dir,
        "gh",
        _gh_shim(
            [_issue(530, labels=[{"name": "bug"}])],
            [
                _pr(531, body="Refs #530", headRefName="fix/a-530"),
                _pr(532, body="Refs #530", headRefName="fix/b-530"),
            ],
            [],
            pr_files={
                531: ["CLAUDE.md", "scripts/backlog-rhythm.sh"],
                532: ["CLAUDE.md"],
            },
        ),
    )

    in_flight = _run(bin_dir)["in_flight_files"]
    assert in_flight["CLAUDE.md"] == [531, 532]
    assert in_flight["scripts/backlog-rhythm.sh"] == [531]


def test_no_open_prs_gives_empty_in_flight_files(bin_dir: Path) -> None:
    """Pre-existing shims report no open PRs; the map must still be an empty
    object, not null, so a caller can index into it unconditionally."""
    issue = _issue(601, labels=[{"name": "bug"}])
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    assert _run(bin_dir)["in_flight_files"] == {}


def test_undiffable_pr_is_recorded_not_a_crash(bin_dir: Path) -> None:
    """A PR whose diff cannot be read (deleted fork head, rate limit,
    transient network error) must not abort the whole digest -- that would
    take down issue triage and dispatch for everyone over one stale PR. It
    also must not be silently treated as touching no files, which the
    collision gate would read as safe to dispatch against. It is recorded as
    data instead."""
    _write_shim(
        bin_dir,
        "gh",
        _gh_shim(
            [_issue(530, labels=[{"name": "bug"}])],
            [
                _pr(531, body="Refs #530", headRefName="fix/a-530"),
                _pr(532, body="Refs #530", headRefName="fix/b-530"),
            ],
            [],
            pr_files={532: ["CLAUDE.md"]},
            fail_pr_diff=[531],
        ),
    )

    digest = _run(bin_dir)

    assert digest["undiffable_prs"] == [531]
    # The readable PR is still processed -- one bad PR does not blank the
    # whole in-flight set.
    assert digest["in_flight_files"]["CLAUDE.md"] == [532]


def test_no_undiffable_prs_gives_empty_list(bin_dir: Path) -> None:
    issue = _issue(601, labels=[{"name": "bug"}])
    _write_shim(bin_dir, "gh", _gh_shim([issue], [], []))

    assert _run(bin_dir)["undiffable_prs"] == []
