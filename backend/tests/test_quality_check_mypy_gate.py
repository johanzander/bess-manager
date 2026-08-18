"""Tests for the mypy gate in scripts/quality-check.sh.

The gate scopes mypy to files changed against `origin/main`. Two things have
to hold for that to be worth anything: a real type error in a changed file
must fail the run, and a run that could not resolve the ref must not be able
to report success — warnings exit 0, so the severity of that branch IS the
behaviour.

`git`, `black`, `ruff` and `pytest` are shims on PATH (same approach as
test_backlog_digest.py), but **mypy is the real one**: shimming it would
leave the gate's actual invocation — its flags, its quoting, the file list it
builds — unexercised, which is how a test passes while proving less than it
claims. The git shim names a changed file for the same reason; with an empty
file list the gate takes its "no changed Python files" path and never calls
mypy at all.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "quality-check.sh"
REAL_MYPY = REPO_ROOT / ".venv" / "bin" / "mypy"

# Only the merge-base arm differs between these two, so any difference in a
# run is attributable to that arm alone. `ls-files --others` names the fixture
# because a brand-new file is untracked until its first commit — the case the
# gate exists to catch.
GIT_RESOLVES = """
case "$1 $2" in
  "merge-base origin/main") echo deadbeef ;;
  "diff --name-only") ;;
  "ls-files --others") echo mod.py ;;
  *) ;;
esac
exit 0
"""

GIT_CANNOT_RESOLVE = """
case "$1 $2" in
  "merge-base origin/main") exit 128 ;;
  "diff --name-only") ;;
  "ls-files --others") echo mod.py ;;
  *) ;;
esac
exit 0
"""

WELL_TYPED = """
def f(x: int) -> int:
    return x


f(1)
"""

ILL_TYPED = """
def f(x: int) -> int:
    return x


f("not an int")
"""


def _write_shim(bin_dir: Path, name: str, body: str) -> None:
    p = bin_dir / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def _run(
    tmp_path: Path, git_body: str, module_source: str = WELL_TYPED
) -> subprocess.CompletedProcess:
    """Run the gate in a throwaway project with the given git/module setup."""
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    # The script refuses to run anywhere without CLAUDE.md, and its Python
    # block is skipped unless a .py file exists.
    (project / "CLAUDE.md").write_text("# stub\n")
    (project / "mod.py").write_text(module_source)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_shim(bin_dir, "git", git_body)
    for tool in ("black", "ruff", "pytest"):
        _write_shim(bin_dir, tool, "exit 0\n")
    # Real mypy, reached through a passthrough: the gate resolves tools from
    # PATH when the cwd has no .venv, and the temp project never will.
    _write_shim(bin_dir, "mypy", f'exec "{REAL_MYPY}" "$@"\n')

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


def test_type_error_in_a_changed_file_fails_the_gate(tmp_path: Path) -> None:
    """The gate's whole purpose: a real type error must cost an error.

    Asserted as a delta against an identical run over a well-typed file, so
    unrelated checks failing in a stub directory can neither mask nor
    manufacture the signal.
    """
    clean = _run(tmp_path / "clean", GIT_RESOLVES, WELL_TYPED)
    dirty = _run(tmp_path / "dirty", GIT_RESOLVES, ILL_TYPED)

    assert _error_count(dirty) == _error_count(clean) + 1
    assert dirty.returncode != 0
    assert "mypy errors in changed files" in dirty.stdout


def test_a_changed_file_actually_reaches_mypy(tmp_path: Path) -> None:
    """Guards the vacuity the delta test cannot see.

    Both runs above would agree if the file list were empty and mypy never
    ran — the gate would report "no changed Python files" twice and the delta
    would simply be zero. This pins that the well-typed run took the
    checked-files path.
    """
    proc = _run(tmp_path / "clean", GIT_RESOLVES, WELL_TYPED)
    assert "✅ mypy OK (changed files)" in proc.stdout
    assert "no changed Python files" not in proc.stdout


def test_unresolvable_origin_main_fails_the_gate(tmp_path: Path) -> None:
    """A run that type-checked nothing must not be able to exit 0."""
    resolvable = _run(tmp_path / "ok", GIT_RESOLVES, WELL_TYPED)
    unresolvable = _run(tmp_path / "broken", GIT_CANNOT_RESOLVE, WELL_TYPED)

    assert _error_count(unresolvable) == _error_count(resolvable) + 1
    assert unresolvable.returncode != 0
    assert "Cannot resolve origin/main" in unresolvable.stdout
