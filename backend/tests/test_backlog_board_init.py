"""Tests for scripts/backlog-board-init.sh — the one-shot board bootstrap.

The script's every effect is a `gh project` call, so `gh` is a shim on PATH
that records its arguments and replays canned output — the same technique
test_backlog_digest.py uses. That is enough to pin the three things worth
pinning: the Priority tiers it creates, that an existing board is left alone,
and that a failed lookup does not become a second board.

Priority is the reason this file exists. It was created as `P0,P1,P2` — a
tier the live board does not have, missing two the digest ranks on — and a
plain string literal can drift back with nothing to catch it.
"""

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "backlog-board-init.sh"


def _make_gh(bin_dir: Path, log: Path, *, list_output: str, list_rc: int = 0) -> None:
    """A `gh` that logs every invocation and answers the calls the script makes.

    `auth status` must mention the project scope or the script stops early;
    `project list` is the idempotency lookup; `project create` returns a
    number; `project field-create` is what we assert on.
    """
    body = f"""
echo "$@" >> "{log}"
case "$1 $2" in
  "auth status") echo "✓ Logged in, scopes: repo, project" ;;
  "project list") printf '%s' '{list_output}'; exit {list_rc} ;;
  "project create") echo 7 ;;
  "project field-create") ;;
  *) ;;
esac
exit 0
"""
    p = bin_dir / "gh"
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def _run(
    tmp_path: Path, **gh_kwargs: object
) -> tuple[subprocess.CompletedProcess, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "gh.log"
    log.write_text("")
    _make_gh(bin_dir, log, **gh_kwargs)  # type: ignore[arg-type]

    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc, log.read_text()


def test_priority_field_is_created_with_the_tiers_the_board_has(
    tmp_path: Path,
) -> None:
    """P1-P4, and no P0 — matching the live board, the skill and the digest."""
    proc, calls = _run(tmp_path, list_output="")

    assert proc.returncode == 0, proc.stderr
    priority = [
        line
        for line in calls.splitlines()
        if "field-create" in line and "Priority" in line
    ]
    assert len(priority) == 1, calls
    assert "P1,P2,P3,P4" in priority[0]
    assert "P0" not in priority[0]


def test_an_existing_board_is_reported_and_left_alone(tmp_path: Path) -> None:
    """Idempotence: report the number, create nothing."""
    proc, calls = _run(tmp_path, list_output="3")

    assert proc.returncode == 0, proc.stderr
    assert "PROJECT_NUMBER 3" in proc.stdout
    assert "project create" not in calls
    assert "field-create" not in calls


def test_a_failed_lookup_does_not_create_a_second_board(tmp_path: Path) -> None:
    """A lookup that errors must not read as "no board exists".

    This is the whole reason the lookup is not `|| true`: an empty result and
    a failed call are indistinguishable afterwards, and the script creates a
    board when it sees the former.
    """
    proc, calls = _run(tmp_path, list_output="", list_rc=1)

    assert proc.returncode != 0
    assert "project create" not in calls
    assert "could not list projects" in proc.stderr
