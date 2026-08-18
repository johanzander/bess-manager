"""Tests for the mypy gate in scripts/quality-check.sh.

The gate scopes mypy to files changed against `origin/main`, so it depends on
that ref resolving. When it cannot, the run type-checks nothing — and a check
that verified nothing must not be able to report success. Warnings exit 0, so
the severity of that branch is the whole behaviour under test.

Everything expensive is a shim on PATH (`git`, `black`, `ruff`, `mypy`,
`pytest`), same approach as test_backlog_digest.py: the script runs against a
throwaway directory, not this repo.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "quality-check.sh"

# A git shim that resolves origin/main, and one that cannot. Only the
# merge-base arm differs — everything else the gate calls is identical, so a
# difference in the run is attributable to that arm alone.
GIT_RESOLVES = """
case "$1 $2" in
  "merge-base origin/main") echo deadbeef ;;
  "diff --name-only") ;;
  "ls-files --others") ;;
  *) ;;
esac
exit 0
"""

GIT_CANNOT_RESOLVE = """
case "$1 $2" in
  "merge-base origin/main") exit 128 ;;
  "diff --name-only") ;;
  "ls-files --others") ;;
  *) ;;
esac
exit 0
"""


def _write_shim(bin_dir: Path, name: str, body: str) -> None:
    p = bin_dir / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def _run(tmp_path: Path, git_body: str) -> subprocess.CompletedProcess:
    """Run the gate in a throwaway project with the given `git` behaviour."""
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    # The script refuses to run anywhere without CLAUDE.md, and its Python
    # block is skipped unless a .py file exists.
    (project / "CLAUDE.md").write_text("# stub\n")
    (project / "mod.py").write_text("x = 1\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_shim(bin_dir, "git", git_body)
    for tool in ("black", "ruff", "mypy", "pytest"):
        _write_shim(bin_dir, tool, "exit 0\n")

    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=project,
        capture_output=True,
        text=True,
        env=env,
    )


def _error_count(proc: subprocess.CompletedProcess) -> int:
    m = re.search(r"^Errors: (\d+)$", proc.stdout, re.MULTILINE)
    assert m, f"no summary in output:\n{proc.stdout}"
    return int(m.group(1))


def test_unresolvable_origin_main_fails_the_gate(tmp_path: Path) -> None:
    """A run that type-checked nothing must not be able to exit 0.

    Asserted as a delta against the resolvable run rather than an absolute
    count, so unrelated checks failing in a stub directory cannot mask or
    manufacture the signal.
    """
    resolvable = _run(tmp_path / "ok", GIT_RESOLVES)
    unresolvable = _run(tmp_path / "broken", GIT_CANNOT_RESOLVE)

    assert _error_count(unresolvable) == _error_count(resolvable) + 1
    assert unresolvable.returncode != 0


def test_resolvable_origin_main_runs_mypy(tmp_path: Path) -> None:
    """The control: with the ref resolvable the gate actually checks types."""
    proc = _run(tmp_path / "ok", GIT_RESOLVES)
    assert "Checking mypy on changed files" in proc.stdout
    assert "Cannot resolve origin/main" not in proc.stdout
