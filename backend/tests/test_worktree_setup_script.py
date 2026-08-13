"""Tests for scripts/worktree-setup.sh — the one-shot dependency bootstrap
for a freshly created git worktree (issue #556).

A new worktree starts with no .venv, no frontend/node_modules and no
e2e/node_modules, so a full `implement-issue` run spends ~35 of its ~40
minutes reinstalling dependencies that already exist, byte-identical, in the
main checkout. The script shares them instead.

Everything here runs the real script as a subprocess against a real, throwaway
git worktree built in tmp_path, so the CLI contract is exercised exactly as a
maintainer would invoke it. The two expensive commands the script may shell out
to — `npm` and `npx playwright install` — are replaced by recording shims on
PATH, which is what lets us assert *whether* an install was needed without
paying for one. Playwright's own PLAYWRIGHT_BROWSERS_PATH env var points the
browser-cache checks at a synthetic cache.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "worktree-setup.sh"

_SHIM = """#!/bin/sh
echo "$(basename "$0") $*" >> "$SHIM_LOG"
exit 0
"""


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)


def _make_main_checkout(root: Path) -> Path:
    """A minimal stand-in for the main bess-manager checkout: a git repo that
    carries the real script plus the three dependency trees a worktree wants."""
    main = root / "main-checkout"
    (main / "scripts").mkdir(parents=True)
    (main / "scripts" / "worktree-setup.sh").write_bytes(SCRIPT.read_bytes())
    (main / "scripts" / "worktree-setup.sh").chmod(0o755)

    # Dependency trees that already exist in the main checkout (gitignored
    # there, hence created directly rather than committed).
    (main / ".venv" / "bin").mkdir(parents=True)
    for pkg in ("frontend", "e2e"):
        (main / pkg).mkdir(exist_ok=True)
        (main / pkg / "package-lock.json").write_text(f'{{"name": "{pkg}"}}\n')
        (main / pkg / "node_modules" / "some-dep").mkdir(parents=True)

    _run(["git", "init", "-b", "main"], cwd=main)
    _run(["git", "config", "user.email", "t@example.com"], cwd=main)
    _run(["git", "config", "user.name", "Test"], cwd=main)
    # The real .gitignore, not a hand-written stand-in — whether the script's
    # symlinks are ignored depends on its exact patterns (a trailing slash
    # matches a directory but not a symlink to one).
    (main / ".gitignore").write_bytes((REPO_ROOT / ".gitignore").read_bytes())
    _run(["git", "add", "-A"], cwd=main)
    _run(["git", "commit", "-m", "init"], cwd=main)
    return main


def _make_worktree(main: Path) -> Path:
    wt = main.parent / "wt"
    _run(["git", "worktree", "add", str(wt), "-b", "feature"], cwd=main)
    return wt


def _make_shims(root: Path) -> tuple[Path, Path]:
    """Recording stand-ins for npm/npx, so the test can tell whether the script
    decided an install was necessary without actually running one."""
    bindir = root / "shims"
    bindir.mkdir()
    log = root / "shim.log"
    for name in ("npm", "npx"):
        shim = bindir / name
        shim.write_text(_SHIM)
        shim.chmod(0o755)
    return bindir, log


def _healthy_browser_cache(root: Path) -> Path:
    cache = root / "ms-playwright"
    binary = cache / "chromium-1217" / "chrome-mac-arm64" / "Chromium"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    (cache / "chromium-1217" / "INSTALLATION_COMPLETE").write_text("")
    return cache


def _setup(tmp_path):
    main = _make_main_checkout(tmp_path)
    wt = _make_worktree(main)
    bindir, log = _make_shims(tmp_path)
    cache = _healthy_browser_cache(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "SHIM_LOG": str(log),
        "PLAYWRIGHT_BROWSERS_PATH": str(cache),
    }
    return main, wt, env, log, cache


def _invoke(wt: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(wt / "scripts" / "worktree-setup.sh")],
        cwd=wt,
        env=env,
        capture_output=True,
        text=True,
    )


def _shim_calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def test_links_venv_and_node_modules_to_the_main_checkout(tmp_path):
    """The whole point: a fresh worktree ends up sharing all three dependency
    trees, so nothing is reinstalled."""
    main, wt, env, log, _ = _setup(tmp_path)

    result = _invoke(wt, env)

    assert result.returncode == 0, result.stderr
    assert (wt / ".venv").is_symlink()
    assert (wt / ".venv").resolve() == (main / ".venv").resolve()
    for pkg in ("frontend", "e2e"):
        link = wt / pkg / "node_modules"
        assert link.is_symlink(), f"{pkg}/node_modules should be shared, not installed"
        assert link.resolve() == (main / pkg / "node_modules").resolve()
    assert not any(
        c.startswith("npm install") for c in _shim_calls(log)
    ), "identical lockfiles must not trigger an install"


def test_installs_instead_of_linking_when_the_lockfile_diverges(tmp_path):
    """Sharing node_modules is only valid while the lockfiles agree — a branch
    that changes dependencies must get its own real install, not the main
    checkout's tree under a different lockfile."""
    _, wt, env, log, _ = _setup(tmp_path)
    (wt / "frontend" / "package-lock.json").write_text('{"name": "frontend-changed"}\n')

    result = _invoke(wt, env)

    assert result.returncode == 0, result.stderr
    assert not (wt / "frontend" / "node_modules").is_symlink()
    assert "npm install" in "\n".join(_shim_calls(log))
    # The unchanged package root is still shared.
    assert (wt / "e2e" / "node_modules").is_symlink()


def test_repairs_a_browser_cache_whose_marker_lies(tmp_path):
    """The trap from #556: an empty browser directory next to an
    INSTALLATION_COMPLETE marker makes every later `playwright install` a
    silent no-op, producing 14 identical 'Executable doesn't exist' failures.
    Checking the marker is what misses it; checking for the binary catches it."""
    _, wt, env, log, cache = _setup(tmp_path)
    corrupt = cache / "chromium_headless_shell-1217"
    corrupt.mkdir()
    (corrupt / "INSTALLATION_COMPLETE").write_text("")

    result = _invoke(wt, env)

    assert result.returncode == 0, result.stderr
    assert not corrupt.exists(), "stale browser directory must be removed, not trusted"
    assert any(
        "playwright install" in c for c in _shim_calls(log)
    ), "a repaired cache must be reinstalled"


def test_leaves_an_intact_browser_cache_alone(tmp_path):
    """The complement of the repair test: a cache with a real executable must
    not be deleted and reinstalled on every worktree setup."""
    _, wt, env, log, cache = _setup(tmp_path)

    result = _invoke(wt, env)

    assert result.returncode == 0, result.stderr
    assert (cache / "chromium-1217" / "chrome-mac-arm64" / "Chromium").exists()
    assert not any("playwright install" in c for c in _shim_calls(log))


def test_ignores_playwright_bookkeeping_directories_in_the_cache(tmp_path):
    """Regression test: the real ms-playwright cache holds non-browser
    directories alongside browser installs — notably `__dirlock`, Playwright's
    own install lock, which is an empty directory with no executable inside.
    Treating it as a stale browser install deletes Playwright's own lock file
    and crashes the reinstall the script goes on to trigger (observed live:
    'Error: Unable to update lock within the stale threshold'). It — and any
    other non `name-<digits>` entry — must be left alone."""
    _, wt, env, log, cache = _setup(tmp_path)
    (cache / "__dirlock").mkdir()
    (cache / ".links").mkdir()

    result = _invoke(wt, env)

    assert result.returncode == 0, result.stderr
    assert (
        cache / "__dirlock"
    ).exists(), "must not delete Playwright's own lock directory"
    assert not any("playwright install" in c for c in _shim_calls(log)), (
        "a bookkeeping directory with no executable must not be mistaken for "
        "a stale browser install"
    )


def test_repairs_a_broken_venv_symlink(tmp_path):
    """Regression test: a dangling `.venv` symlink (e.g. left over after the
    main checkout's .venv was recreated) satisfies `-L` but not `-e`. The
    original `[ -e .venv ] || [ -L .venv ]` check treated that as "already
    present" and skipped re-linking, so the worktree reported success while
    every later `.venv/bin/pytest` invocation would fail with "No such file
    or directory". The script must detect and repair a broken link, not just
    an absent one."""
    main, wt, env, _, _ = _setup(tmp_path)
    (wt / ".venv").symlink_to(main / "nonexistent-venv")

    result = _invoke(wt, env)

    assert result.returncode == 0, result.stderr
    assert (wt / ".venv").is_symlink()
    assert (wt / ".venv").resolve() == (main / ".venv").resolve()


def test_repairs_a_broken_node_modules_symlink(tmp_path):
    """Same broken-symlink trap as .venv, for the node_modules links."""
    main, wt, env, _, _ = _setup(tmp_path)
    (wt / "frontend" / "node_modules").symlink_to(main / "nonexistent-node-modules")

    result = _invoke(wt, env)

    assert result.returncode == 0, result.stderr
    link = wt / "frontend" / "node_modules"
    assert link.is_symlink()
    assert link.resolve() == (main / "frontend" / "node_modules").resolve()


def test_is_idempotent(tmp_path):
    """Run twice — a second run must not fail or nest a symlink inside the
    directory the first run linked."""
    main, wt, env, _, _ = _setup(tmp_path)

    assert _invoke(wt, env).returncode == 0
    result = _invoke(wt, env)

    assert result.returncode == 0, result.stderr
    assert (wt / ".venv").resolve() == (main / ".venv").resolve()
    assert not (main / ".venv" / ".venv").exists(), "must not link into the target"


def test_refuses_to_run_outside_a_worktree(tmp_path):
    """Run from the main checkout it would be linking .venv to itself; fail
    loudly rather than doing something surprising."""
    main = _make_main_checkout(tmp_path)
    bindir, log = _make_shims(tmp_path)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "SHIM_LOG": str(log)}

    result = _invoke(main, env)

    assert result.returncode != 0
    assert "worktree" in (result.stderr + result.stdout).lower()


def test_leaves_the_worktree_git_status_clean(tmp_path):
    """The links the script creates must be invisible to git. `.gitignore`'s
    `node_modules/` pattern matches a directory but NOT a symlink pointing at
    one, so sharing node_modules leaves untracked entries in every worktree —
    permanent `git status` noise, and a symlink holding an absolute
    machine-specific path that a `git add -A` would happily commit."""
    _, wt, env, _, _ = _setup(tmp_path)

    assert _invoke(wt, env).returncode == 0

    status = _run(["git", "status", "--porcelain"], cwd=wt).stdout
    assert status == "", f"script left the worktree dirty:\n{status}"


def test_script_exists_and_is_executable():
    assert SCRIPT.exists(), "scripts/worktree-setup.sh is missing"
    assert os.access(SCRIPT, os.X_OK), "scripts/worktree-setup.sh must be executable"


if __name__ == "__main__":
    pytest.main([__file__])
