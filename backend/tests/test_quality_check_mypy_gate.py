"""Tests for the mypy gate in scripts/quality-check.sh and scripts/mypy-changed.sh.

The gate scopes mypy to files changed against `origin/main` and fails only on
errors the branch INTRODUCED, measured against the same files at the
merge-base. Four things have to hold for that to be worth anything:

- a newly introduced type error must fail the run;
- an error that already existed at the merge-base must NOT;
- a run that could not resolve the ref must not be able to report success;
- a run whose BASELINE could not be computed must not report success either —
  an empty baseline makes every pre-existing error look new, which is the
  concrete bug this gate hit in development (a relative mypy path stopped
  resolving once the baseline pass cd'd into the extracted tree).

`git`, `black`, `ruff` and `pytest` are shims on PATH (same approach as
test_backlog_digest.py), but **mypy is the real one**: shimming it would
leave the gate's actual invocation — its flags, its quoting, the file list it
builds — unexercised, which is how a test passes while proving less than it
claims. The git shim names a changed file for the same reason; with an empty
file list the gate takes its "no changed Python files" path and never calls
mypy at all.

The git shim also serves `archive`, which is how the baseline tree is
extracted. It tars up whatever BASELINE_DIR points at, so a test sets the
"before" state simply by writing a different module there.
"""

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "quality-check.sh"

# Reach mypy through the interpreter running the tests, not through a fixed
# `.venv/bin/mypy` path. CI installs dependencies without that venv layout, so
# the fixed path exec'd a binary that did not exist -- mypy then "failed" in
# every run alike, the delta assertions collapsed to zero, and the suite went
# red on CI while passing locally. If mypy is not importable at all, skip
# rather than assert against a gate that cannot run.
pytest.importorskip("mypy")

# `archive` tars BASELINE_DIR; `rev-parse --show-toplevel` must name the
# project, since mypy-changed.sh cds there before doing anything else.
# `ls-files --others` names the fixture because a brand-new file is untracked
# until its first commit — the case the gate exists to catch.
GIT_RESOLVES = """
case "$1 $2" in
  "rev-parse --show-toplevel") echo "$PROJECT_DIR" ;;
  "merge-base origin/main") echo deadbeef ;;
  "diff --name-only") ;;
  "ls-files --others") echo mod.py ;;
  "archive deadbeef") tar -cf - -C "$BASELINE_DIR" . ;;
  *) ;;
esac
exit 0
"""

# Same as GIT_RESOLVES but names a path with a space in it — the case a
# space-joined file list silently splits into two arguments.
GIT_RESOLVES_SPACED_PATH = """
case "$1 $2" in
  "rev-parse --show-toplevel") echo "$PROJECT_DIR" ;;
  "merge-base origin/main") echo deadbeef ;;
  "diff --name-only") ;;
  "ls-files --others") echo "mod with space.py" ;;
  "archive deadbeef") tar -cf - -C "$BASELINE_DIR" . ;;
  *) ;;
esac
exit 0
"""

GIT_CANNOT_RESOLVE = """
case "$1 $2" in
  "rev-parse --show-toplevel") echo "$PROJECT_DIR" ;;
  "merge-base origin/main") exit 128 ;;
  "merge-base FETCH_HEAD") exit 128 ;;
  "diff --name-only") ;;
  "ls-files --others") echo mod.py ;;
  *) ;;
esac
exit 0
"""

# Resolves the ref but cannot produce the baseline tree.
GIT_ARCHIVE_FAILS = """
case "$1 $2" in
  "rev-parse --show-toplevel") echo "$PROJECT_DIR" ;;
  "merge-base origin/main") echo deadbeef ;;
  "diff --name-only") ;;
  "ls-files --others") echo mod.py ;;
  "archive deadbeef") exit 128 ;;
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
    tmp_path: Path,
    git_body: str,
    module_source: str = WELL_TYPED,
    baseline_source: str = WELL_TYPED,
) -> subprocess.CompletedProcess:
    """Run the gate in a throwaway project.

    `module_source` is the file as this branch has it; `baseline_source` is
    the same file as of the merge-base. Equal sources mean "touched but
    unchanged in type terms", which is the common real case.
    """
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    # The script refuses to run anywhere without CLAUDE.md, and its Python
    # block is skipped unless a .py file exists.
    (project / "CLAUDE.md").write_text("# stub\n")
    (project / "mod.py").write_text(module_source)
    (project / "mod with space.py").write_text(module_source)

    baseline = tmp_path / "baseline"
    baseline.mkdir(parents=True, exist_ok=True)
    (baseline / "mod.py").write_text(baseline_source)
    (baseline / "mod with space.py").write_text(baseline_source)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_shim(bin_dir, "git", git_body)
    for tool in ("black", "ruff", "pytest"):
        _write_shim(bin_dir, tool, "exit 0\n")
    # Real mypy, reached through a passthrough: the gate resolves tools from
    # PATH when the cwd has no .venv, and the temp project never will.
    _write_shim(bin_dir, "mypy", f'exec "{sys.executable}" -m mypy "$@"\n')

    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        PROJECT_DIR=str(project),
        BASELINE_DIR=str(baseline),
    )
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


def test_newly_introduced_type_error_fails_the_gate(tmp_path: Path) -> None:
    """The gate's whole purpose: an error this branch added must cost an error.

    Asserted as a delta against an identical run over a well-typed file, so
    unrelated checks failing in a stub directory can neither mask nor
    manufacture the signal.
    """
    clean = _run(tmp_path / "clean", GIT_RESOLVES, WELL_TYPED, WELL_TYPED)
    dirty = _run(tmp_path / "dirty", GIT_RESOLVES, ILL_TYPED, WELL_TYPED)

    assert _error_count(dirty) == _error_count(clean) + 1
    assert dirty.returncode != 0
    assert "new type error(s) introduced by this branch" in dirty.stdout


def test_a_preexisting_error_does_not_fail_the_gate(tmp_path: Path) -> None:
    """The ratchet half, and the reason this gate was rewritten.

    The same error present at the merge-base must not be charged to whoever
    next edits the file. Without this, touching any legacy module meant
    adopting its whole backlog -- #643's six-line fix faced 404 errors across
    31 files while introducing none of them.

    Paired with the test above, which uses the identical HEAD source and only
    a different baseline: the two differ in the baseline arm alone, so a pass
    here cannot come from mypy simply never running.
    """
    proc = _run(tmp_path / "legacy", GIT_RESOLVES, ILL_TYPED, ILL_TYPED)

    assert "no new errors" in proc.stdout
    assert "1 pre-existing in touched files" in proc.stdout
    assert "new type error(s) introduced" not in proc.stdout


def test_a_changed_file_actually_reaches_mypy(tmp_path: Path) -> None:
    """Guards the vacuity the delta tests cannot see.

    Runs would agree if the file list were empty and mypy never ran — the
    gate would report "no changed Python files" and every delta would be
    zero. This pins that the well-typed run took the checked-files path.
    """
    proc = _run(tmp_path / "clean", GIT_RESOLVES, WELL_TYPED, WELL_TYPED)
    assert "✅ mypy OK (changed files)" in proc.stdout
    assert "no changed Python files" not in proc.stdout


def test_unresolvable_origin_main_fails_the_gate(tmp_path: Path) -> None:
    """A run that type-checked nothing must not be able to exit 0."""
    resolvable = _run(tmp_path / "ok", GIT_RESOLVES, WELL_TYPED, WELL_TYPED)
    unresolvable = _run(tmp_path / "broken", GIT_CANNOT_RESOLVE, WELL_TYPED)

    assert _error_count(unresolvable) == _error_count(resolvable) + 1
    assert unresolvable.returncode != 0
    assert "Cannot resolve a merge-base" in unresolvable.stdout


def test_an_uncomputable_baseline_fails_the_gate(tmp_path: Path) -> None:
    """A missing baseline must fail closed, not silently pass everything.

    This is the failure mode that actually occurred while building the gate:
    the baseline pass ran from inside the extracted tree, where the relative
    `.venv/bin/mypy` no longer existed, so it produced no output. Read as
    "the baseline had no errors", that turns every pre-existing error into a
    newly introduced one -- and the symmetric version of the same mistake
    (treating a failed baseline as "nothing to compare") would wave real
    errors through instead.
    """
    ok = _run(tmp_path / "ok", GIT_RESOLVES, WELL_TYPED, WELL_TYPED)
    broken = _run(tmp_path / "broken", GIT_ARCHIVE_FAILS, WELL_TYPED)

    assert _error_count(broken) == _error_count(ok) + 1
    assert broken.returncode != 0


def test_a_changed_path_with_a_space_is_still_checked(tmp_path: Path) -> None:
    """The file list is an array, so a spaced path stays one argument.

    Space-joined, this path splits into `mod`, `with` and `space.py` — mypy
    is handed three names that do not exist, which is a mypy failure and so
    looks like a caught type error whatever the file contains. Asserting the
    error lands only for the ill-typed run is what separates the two.
    """
    clean = _run(tmp_path / "clean", GIT_RESOLVES_SPACED_PATH, WELL_TYPED, WELL_TYPED)
    dirty = _run(tmp_path / "dirty", GIT_RESOLVES_SPACED_PATH, ILL_TYPED, WELL_TYPED)

    assert "✅ mypy OK (changed files)" in clean.stdout
    assert _error_count(dirty) == _error_count(clean) + 1
