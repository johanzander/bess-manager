"""Tests for scripts/request-pr-review.sh — the Step 11 verdict wait.

This file exists because the same correctness bug survived THREE review rounds.
Verification was `quality-check.sh` plus `bash -n`, neither of which exercises
the decision path, so each "fix" was asserted rather than demonstrated. The
decision is: given some reviews and a workflow-run state, what does this script
report?

`gh` and `scripts/gh-agent.sh` are shimmed on PATH, so nothing here touches
GitHub. `interval` is driven down via REVIEW_POLL_INTERVAL so a test costs
milliseconds rather than a minute.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "request-pr-review.sh"


def _write(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    return d


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    """A fixture `.env` for `scripts/gh-agent.sh`, via its `BESS_ENV_FILE` seam.

    The script posts its trigger comment through gh-agent.sh, which reads a real
    token and exits 1 before `gh` is ever reached:

        token="${!token_var:-}"
        if [ -z "$token" ]; then echo "... is not set in ${env_file}"; exit 1; fi

    Shimming `gh` on PATH does not help, because gh-agent.sh is invoked by a
    repo-relative path rather than looked up on PATH. Without this the suite
    needs a real `BESS_AGENT_TOKEN` in the gitignored `.env`, so it passes on a
    developer machine and fails unconditionally in CI — which is exactly what
    happened: `Fast tests` went red while local `quality-check.sh` was green,
    because a real local `.env` papered over the gap.
    """
    p = tmp_path / "fixture.env"
    p.write_text("BESS_AGENT_TOKEN=dummy-token-for-tests\n")
    return p


PR_TITLE = "fix: the pr under review"


def _gh(
    bin_dir: Path,
    reviews: list,
    run_state: str,
    extra_runs: list | None = None,
    title: str = PR_TITLE,
) -> None:
    """A `gh` answering the two queries the script makes.

    `reviews` is returned for `pr view --json reviews`; `run_state` drives
    `run list`, which is how the script decides whether the reviewer is still
    working.
    """
    # `unknown` is not a run shape but a FAILURE to read one: `gh run list`
    # exits non-zero, which is what a network blip or rate limit looks like.
    runs_fail = run_state == "unknown"
    runs = (
        []
        if runs_fail
        else {
            "running": [{"status": "in_progress", "conclusion": None}],
            "finished": [{"status": "completed", "conclusion": "success"}],
            "failed": [{"status": "completed", "conclusion": "failure"}],
            "none": [],
        }[run_state]
    )
    # createdAt must sort after the script's `since`, which it computes at start.
    # displayTitle is what scopes a run to THIS PR — a run carrying any other
    # title belongs to a different PR (or to an issue comment, which spawns a
    # gated-out `skipped` run) and must be ignored.
    for r in runs:
        r["createdAt"] = "2099-01-01T00:00:00Z"
        r.setdefault("displayTitle", title)

    # `extra_runs` are NEWER runs belonging to something else. Real gh returns
    # newest-first, so they go in front — which is exactly how they used to be
    # mistaken for this PR's run.
    runs = (extra_runs or []) + runs

    # The shim must APPLY --jq, like real gh does. An earlier version echoed the
    # raw JSON and the script happily reported it as a verdict — the shim has to
    # be faithful about the part under test, which here is the jq filter.
    (bin_dir / "reviews.json").write_text(json.dumps({"reviews": reviews}))
    (bin_dir / "runs.json").write_text(json.dumps(runs))
    (bin_dir / "title.json").write_text(json.dumps({"title": title}))

    _write(
        bin_dir / "gh",
        f"""#!/bin/sh
# Pull the --jq filter out of the argument list, then apply it to the fixture.
filter=''
prev=''
for a in "$@"; do
  if [ "$prev" = "--jq" ]; then filter="$a"; fi
  prev="$a"
done

case "$*" in
  *'pr view'*'--json title'*) src='{bin_dir}/title.json' ;;
  *'pr view'*)  src='{bin_dir}/reviews.json' ;;
  *'run list'*)
      if [ "{int(runs_fail)}" = "1" ]; then
          echo "simulated transient gh failure" >&2
          exit 1
      fi
      src='{bin_dir}/runs.json' ;;
  *'pr comment'*) exit 0 ;;
  *) echo "unexpected gh: $*" >&2; exit 1 ;;
esac

if [ -n "$filter" ]; then
  jq -r "$filter" < "$src"
else
  cat "$src"
fi
""",
    )


def _review(state: str, at: str = "2099-01-01T00:00:01Z", body: str = "x") -> dict:
    return {"state": state, "submittedAt": at, "body": body, "author": {"login": "bot"}}


def _run(
    bin_dir: Path, env_file: Path, timeout: int = 2
) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        REVIEW_POLL_INTERVAL="1",
        BESS_ENV_FILE=str(env_file),
    )
    return subprocess.run(
        ["bash", str(SCRIPT), "622", str(timeout)],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


def test_a_missing_token_fails_loudly_and_is_why_the_seam_exists(
    bin_dir: Path, tmp_path: Path
) -> None:
    """Pins the dependency the other tests satisfy, so the seam cannot be
    quietly dropped again.

    Every other test passes its own `BESS_ENV_FILE`. Without one, gh-agent.sh
    resolves the env file from the MAIN checkout — `dirname $(git
    rev-parse --git-common-dir)` — so a worktree with no `.env` of its own still
    read the developer's real token and the suite passed locally while failing
    unconditionally in CI, where no `.env` is provisioned.

    Point the seam at an empty file and the script must fail before polling,
    with the reason named.
    """
    empty = tmp_path / "empty.env"
    empty.write_text("")
    _gh(bin_dir, [_review("APPROVED")], "finished")

    proc = _run(bin_dir, empty)

    assert proc.returncode != 0
    assert "VERDICT" not in proc.stdout
    assert "BESS_AGENT_TOKEN is not set" in proc.stderr


def test_approved_returns_immediately(bin_dir: Path, env_file: Path) -> None:
    _gh(bin_dir, [_review("APPROVED")], "running")
    proc = _run(bin_dir, env_file)
    assert proc.returncode == 0
    assert "VERDICT APPROVED" in proc.stdout


def test_changes_requested_returns_immediately(bin_dir: Path, env_file: Path) -> None:
    _gh(bin_dir, [_review("CHANGES_REQUESTED")], "running")
    proc = _run(bin_dir, env_file)
    assert proc.returncode == 0
    assert "VERDICT CHANGES_REQUESTED" in proc.stdout


def test_commented_while_running_is_not_a_verdict(
    bin_dir: Path, env_file: Path
) -> None:
    """The bug, three rounds running.

    The bot posts an early permission-check comment and keeps working for
    minutes. Returning that COMMENTED makes Step 11 see a non-APPROVED verdict
    and skip `gh pr ready` — how #615 sat approved-but-draft overnight. On #622
    the stub landed at 12:15:14 and the real CHANGES_REQUESTED at 12:16:39.
    """
    _gh(
        bin_dir,
        [_review("COMMENTED", body="test permission check - ignore")],
        "running",
    )
    proc = _run(bin_dir, env_file)

    assert proc.returncode == 2
    assert "VERDICT" not in proc.stdout
    assert "the review is running" in proc.stderr


def test_commented_after_the_run_finished_is_reported(
    bin_dir: Path, env_file: Path
) -> None:
    """The opposite failure. COMMENT is no longer a legal verdict —
    `pr-review.yml` allows only APPROVE and REQUEST_CHANGES — but once the run
    is over, a COMMENTED last word is still the reviewer's last word and must
    reach the caller. Swallowing it made the script report "no summary" while
    findings sat on the PR."""
    _gh(bin_dir, [_review("COMMENTED")], "finished")
    proc = _run(bin_dir, env_file)

    assert proc.returncode == 0
    assert "VERDICT COMMENTED" in proc.stdout


def test_a_failed_run_reports_at_once_instead_of_waiting(
    bin_dir: Path, env_file: Path
) -> None:
    """A dead run and a thinking one are both silence if you only poll reviews.
    #623's run died on `Reached maximum number of turns (60)` and the wait
    continued for 16 minutes."""
    _gh(bin_dir, [], "failed")
    proc = _run(bin_dir, env_file, timeout=60)

    assert proc.returncode == 2
    assert "FAILED" in proc.stderr
    assert "not a slow one" in proc.stderr


def test_no_run_at_all_is_reported_as_a_trigger_fault(
    bin_dir: Path, env_file: Path
) -> None:
    """#619 failed this way twice: the trigger never reached the workflow, which
    needs a different response from a stalled review."""
    _gh(bin_dir, [], "none")
    proc = _run(bin_dir, env_file)

    assert proc.returncode == 2
    assert "No PR Review run started at all" in proc.stderr
    assert "actor gate" in proc.stderr


def test_an_unreadable_run_state_does_not_promote_a_placeholder(
    bin_dir: Path, env_file: Path
) -> None:
    """ "I could not tell" must never mean "it finished".

    `review_run_state` falls back to `unknown` when `gh run list` itself fails —
    a network blip, a rate limit, a transient auth error. An earlier version
    tested only `state = running` and let everything else through, so `unknown`
    reported the bot's placeholder as the verdict. That re-opened the exact race
    this script exists to close, gated on API flakiness instead of timing.

    Waiting costs one more poll; a genuine COMMENT verdict still returns as soon
    as the state resolves.
    """
    _gh(
        bin_dir,
        [_review("COMMENTED", body="test permission check - ignore")],
        "unknown",
    )
    proc = _run(bin_dir, env_file)

    assert proc.returncode == 2
    assert "VERDICT" not in proc.stdout
    assert "unknown" in proc.stderr


def test_a_decisive_verdict_wins_over_an_earlier_commented(
    bin_dir: Path, env_file: Path
) -> None:
    """Ordering, not recency of any state: the stub is older, the verdict newer."""
    _gh(
        bin_dir,
        [
            _review("COMMENTED", at="2099-01-01T00:00:01Z"),
            _review("CHANGES_REQUESTED", at="2099-01-01T00:00:02Z"),
        ],
        "running",
    )
    proc = _run(bin_dir, env_file)

    assert proc.returncode == 0
    assert "VERDICT CHANGES_REQUESTED" in proc.stdout


def _foreign_run(title: str, conclusion: str = "skipped") -> dict:
    """A newer `PR Review` run belonging to something else.

    `pr-review.yml` triggers on `issue_comment`, which fires for comments on
    ISSUES as well as PRs. Those runs are gated out and complete as `skipped`
    within about ten seconds, so any comment posted anywhere in the repo while a
    review is running produces one of these.
    """
    return {
        "status": "completed",
        "conclusion": conclusion,
        "createdAt": "2099-01-01T00:00:30Z",
        "displayTitle": title,
    }


def test_a_newer_run_for_a_different_pr_is_not_this_review(
    bin_dir: Path, env_file: Path
) -> None:
    """The bug that cost a real review round. A routine PO comment on issue
    #441 spawned a gated-out `skipped` run, which was newer than #636's and so
    was read as "this review failed" — while #636 went on to APPROVE two
    minutes later. The caller abandoned a review that was still thinking.
    """
    _gh(
        bin_dir,
        [],
        "running",
        extra_runs=[_foreign_run("Question: Is it always counting with 15 minutes?")],
    )
    proc = _run(bin_dir, env_file, timeout=2)

    # Times out waiting, which is correct: the review is still running.
    assert proc.returncode == 2
    assert "FAILED without submitting a verdict" not in proc.stderr


def test_this_prs_own_failed_run_is_still_reported(
    bin_dir: Path, env_file: Path
) -> None:
    """The scoping must not swallow a genuine failure — that is the other half
    of the same rule, and the reason a fixed grace window was replaced by
    asking the run in the first place."""
    _gh(
        bin_dir,
        [],
        "failed",
        extra_runs=[_foreign_run("some unrelated issue")],
    )
    proc = _run(bin_dir, env_file, timeout=2)

    assert proc.returncode == 2
    assert "FAILED without submitting a verdict" in proc.stderr


def test_an_in_flight_review_is_not_re_triggered(bin_dir: Path, tmp_path: Path) -> None:
    """C2: three callers can now invoke this script for the same PR sharing
    no state. If a run is already in flight, this invocation must NOT post a
    second '@claude-bot review' -- it must wait on the run already going.

    Proven by using an EMPTY BESS_AGENT_TOKEN env file: posting the trigger
    comment goes through gh-agent.sh, which fails loudly ("... is not set")
    before ever reaching `gh` when the token is missing. If the script still
    reaches a VERDICT with no token configured, it never attempted to post --
    the only way that succeeds is the in-flight gate skipping the trigger.
    """
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")
    _gh(bin_dir, [_review("APPROVED")], "running")

    proc = _run(bin_dir, empty_env)

    assert proc.returncode == 0, proc.stderr
    assert "VERDICT APPROVED" in proc.stdout
    assert "BESS_AGENT_TOKEN is not set" not in proc.stderr
    assert "already in flight" in proc.stderr


def test_no_in_flight_run_still_triggers_normally(
    bin_dir: Path, env_file: Path
) -> None:
    """The other half of the same gate: with nothing running, the script
    must still post -- the fix must not turn into "never trigger a review"."""
    _gh(bin_dir, [], "none")

    proc = _run(bin_dir, env_file, timeout=2)

    assert proc.returncode == 2
    assert "already in flight" not in proc.stderr
    assert "No PR Review run started at all" in proc.stderr


def test_a_transient_api_failure_does_not_kill_the_poll(
    bin_dir: Path, env_file: Path
) -> None:
    """`set -e` used to turn one 503 on the verdict read into a fatal exit 1,
    AFTER the trigger comment had posted — so re-running spent a second paid
    review round on a review already in flight. GitHub returned 503s for about
    ninety minutes on 2026-08-17 and this fired twice.

    The shim fails `pr view --json reviews` once, then serves normally.
    """
    _gh(bin_dir, [_review("APPROVED")], "running")

    # Wrap the shim: first reviews read fails, subsequent ones succeed.
    gh = bin_dir / "gh"
    real = gh.read_text()
    (bin_dir / "gh-real").write_text(real)
    (bin_dir / "gh-real").chmod(0o755)
    _write(
        gh,
        f"""#!/bin/sh
case "$*" in
  *'pr view'*'--json reviews'*)
      if [ ! -f {bin_dir}/tripped ]; then
          touch {bin_dir}/tripped
          echo "HTTP 503: no server is currently available" >&2
          exit 1
      fi ;;
esac
exec {bin_dir}/gh-real "$@"
""",
    )

    proc = _run(bin_dir, env_file, timeout=6)

    assert proc.returncode == 0, proc.stderr
    assert "VERDICT APPROVED" in proc.stdout
