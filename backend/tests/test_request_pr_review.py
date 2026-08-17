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
    # The trigger comment goes through gh-agent.sh; make it a no-op.
    (d / "scripts").mkdir(parents=True, exist_ok=True)
    return d


def _gh(bin_dir: Path, reviews: list, run_state: str) -> None:
    """A `gh` answering the two queries the script makes.

    `reviews` is returned for `pr view --json reviews`; `run_state` drives
    `run list`, which is how the script decides whether the reviewer is still
    working.
    """
    runs = {
        "running": [{"status": "in_progress", "conclusion": None}],
        "finished": [{"status": "completed", "conclusion": "success"}],
        "failed": [{"status": "completed", "conclusion": "failure"}],
        "none": [],
    }[run_state]
    # createdAt must sort after the script's `since`, which it computes at start.
    for r in runs:
        r["createdAt"] = "2099-01-01T00:00:00Z"

    # The shim must APPLY --jq, like real gh does. An earlier version echoed the
    # raw JSON and the script happily reported it as a verdict — the shim has to
    # be faithful about the part under test, which here is the jq filter.
    (bin_dir / "reviews.json").write_text(json.dumps({"reviews": reviews}))
    (bin_dir / "runs.json").write_text(json.dumps(runs))

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
  *'pr view'*)  src='{bin_dir}/reviews.json' ;;
  *'run list'*) src='{bin_dir}/runs.json' ;;
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


def _run(bin_dir: Path, timeout: int = 2) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        REVIEW_POLL_INTERVAL="1",
    )
    return subprocess.run(
        ["bash", str(SCRIPT), "622", str(timeout)],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


def test_approved_returns_immediately(bin_dir: Path) -> None:
    _gh(bin_dir, [_review("APPROVED")], "running")
    proc = _run(bin_dir)
    assert proc.returncode == 0
    assert "VERDICT APPROVED" in proc.stdout


def test_changes_requested_returns_immediately(bin_dir: Path) -> None:
    _gh(bin_dir, [_review("CHANGES_REQUESTED")], "running")
    proc = _run(bin_dir)
    assert proc.returncode == 0
    assert "VERDICT CHANGES_REQUESTED" in proc.stdout


def test_commented_while_running_is_not_a_verdict(bin_dir: Path) -> None:
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
    proc = _run(bin_dir)

    assert proc.returncode == 2
    assert "VERDICT" not in proc.stdout
    assert "still running" in proc.stderr


def test_commented_after_the_run_finished_is_the_verdict(bin_dir: Path) -> None:
    """The opposite failure. `pr-review.yml` lists COMMENT as one of three final
    verdicts, so once the run is over a COMMENTED last word IS the answer —
    swallowing it made the script report "no summary" while findings sat on the
    PR."""
    _gh(bin_dir, [_review("COMMENTED")], "finished")
    proc = _run(bin_dir)

    assert proc.returncode == 0
    assert "VERDICT COMMENTED" in proc.stdout


def test_a_failed_run_reports_at_once_instead_of_waiting(bin_dir: Path) -> None:
    """A dead run and a thinking one are both silence if you only poll reviews.
    #623's run died on `Reached maximum number of turns (60)` and the wait
    continued for 16 minutes."""
    _gh(bin_dir, [], "failed")
    proc = _run(bin_dir, timeout=60)

    assert proc.returncode == 2
    assert "FAILED" in proc.stderr
    assert "not a slow one" in proc.stderr


def test_no_run_at_all_is_reported_as_a_trigger_fault(bin_dir: Path) -> None:
    """#619 failed this way twice: the trigger never reached the workflow, which
    needs a different response from a stalled review."""
    _gh(bin_dir, [], "none")
    proc = _run(bin_dir)

    assert proc.returncode == 2
    assert "No PR Review run started at all" in proc.stderr
    assert "actor gate" in proc.stderr


def test_a_decisive_verdict_wins_over_an_earlier_commented(bin_dir: Path) -> None:
    """Ordering, not recency of any state: the stub is older, the verdict newer."""
    _gh(
        bin_dir,
        [
            _review("COMMENTED", at="2099-01-01T00:00:01Z"),
            _review("CHANGES_REQUESTED", at="2099-01-01T00:00:02Z"),
        ],
        "running",
    )
    proc = _run(bin_dir)

    assert proc.returncode == 0
    assert "VERDICT CHANGES_REQUESTED" in proc.stdout
