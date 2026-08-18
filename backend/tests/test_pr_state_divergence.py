"""Tests for pr-state.sh's local-writer section — the two-writers detector.

This is the one thing GitHub cannot tell you. A branch with two writers looks
completely normal through the API: the divergence exists only between a local
checkout and the remote, and it collapses into an ordinary merge commit the
moment somebody reconciles it.

PR #619 is why this exists. One writer took the branch at 08:09 and worked from
that base; another pushed 23031e78 at 09:34. The reviewer reviewed 23031e78
three times, twice with blocking findings, while the first line never held that
commit at all. Fifteen hours later it landed as `Merge remote-tracking branch
'origin/fix/...' into fix/...` — a branch merged into itself.

So the scenario below is built for real: a bare "origin", two clones that both
commit to one branch, and the assertion that the script names it.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "pr-state.sh"

GIT_ENV = {
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}

BRANCH = "fix/issue-592-vpp-idle-at-floor"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**GIT_ENV, "HOME": str(cwd)},
    )
    return proc.stdout.strip()


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)


@pytest.fixture
def two_writers(tmp_path: Path) -> Path:
    """A checkout whose branch has diverged from its own remote.

    Writer B pushes; writer A, which branched earlier, commits locally without
    pulling. That is #619's shape exactly.
    """
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "-q", "--bare", "-b", "main")

    writer_b = tmp_path / "writer-b"
    _git(tmp_path, "clone", "-q", str(origin), "writer-b")
    _commit(writer_b, "seed")
    _git(writer_b, "push", "-q", "origin", "main")
    _git(writer_b, "checkout", "-q", "-b", BRANCH)
    _commit(writer_b, "from-b")
    _git(writer_b, "push", "-q", "origin", BRANCH)

    writer_a = tmp_path / "writer-a"
    _git(tmp_path, "clone", "-q", str(origin), "writer-a")
    _git(writer_a, "checkout", "-q", "-b", BRANCH, "--no-track", "origin/main")
    _commit(writer_a, "from-a")
    # A never pulled B's push, so the two lines have no common tip.
    return writer_a


def _run(cwd: Path, tmp_path: Path, prs: list[dict]) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "prs.json").write_text(json.dumps(prs))
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\ncat '{bin_dir}/prs.json'\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}"),
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _pr(number: int, branch: str) -> dict:
    return {
        "number": number,
        "title": f"pr {number}",
        "isDraft": True,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "headRefName": branch,
        "updatedAt": "2026-08-17T00:00:00Z",
        "reviews": [],
        "commits": [{"committedDate": "2026-08-17T00:00:00Z"}],
        "comments": [
            {"body": "@claude-bot review", "createdAt": "2026-08-18T00:00:00Z"}
        ],
        "statusCheckRollup": [
            {"name": "Fast tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ],
    }


def test_two_writers_on_one_branch_are_named(two_writers: Path, tmp_path: Path) -> None:
    """The #619 shape. Local has a commit the remote lacks AND the remote has a
    commit local lacks — which cannot happen with a single writer."""
    out = _run(two_writers, tmp_path, [_pr(619, BRANCH)])

    assert "DIVERGED" in out
    assert "TWO WRITERS" in out
    assert "#619" in out


def test_a_branch_in_sync_is_not_flagged(two_writers: Path, tmp_path: Path) -> None:
    """Guards against a detector that shouts on every branch — which would get
    it ignored, the way a CONFLICTING PR with no checks got ignored."""
    _git(two_writers, "fetch", "-q", "origin")
    _git(two_writers, "reset", "-q", "--hard", f"origin/{BRANCH}")
    out = _run(two_writers, tmp_path, [_pr(619, BRANCH)])

    assert "DIVERGED" not in out
    assert "in sync" in out


def test_a_branch_with_no_open_pr_is_not_reported(
    two_writers: Path, tmp_path: Path
) -> None:
    """The fleet has ~47 worktrees and most have no open PR. Listing them all
    would bury the one line that matters."""
    out = _run(two_writers, tmp_path, [_pr(999, "some/other-branch")])

    assert BRANCH not in out.split("Local writers")[-1]
