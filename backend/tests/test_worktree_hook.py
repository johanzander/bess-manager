"""Tests for .claude/hooks/check-worktree-path.sh.

The hook is the only mechanical enforcement of "work in a worktree before ANY
edit". CLAUDE.md has stated that rule unconditionally for a long time and it
still gets skipped, because prose has to be REMEMBERED at the moment of the
first edit — and that is exactly the moment a session which opened as a question
has no reason to reconsider it.

The damage is on the record. PR #619's branch carries a merge of itself
(`Merge remote-tracking branch 'origin/fix/...' into fix/...`) because two
writers worked the same branch from different bases and diverged for fifteen
hours; the reviewer reviewed one line three times while the other, based on a
commit from 08:09, never saw a verdict.

So these tests pin the decision the hook makes, against real git checkouts built
in tmp_path rather than the developer's own layout.
"""

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "hooks" / "check-worktree-path.sh"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(cwd),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real main checkout on `main` with one commit."""
    main = tmp_path / "main-checkout"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "seed.txt").write_text("seed\n")
    _git(main, "add", "seed.txt")
    _git(main, "commit", "-q", "-m", "seed")
    return main


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Path:
    """A linked worktree of that checkout — the sanctioned place to edit."""
    wt = tmp_path / "linked-worktree"
    _git(repo, "worktree", "add", "-q", "-b", "feat/x", str(wt))
    return wt


def _decide(cwd: Path, target: Path) -> dict:
    """Run the hook as Claude Code would, and return its decision."""
    proc = subprocess.run(
        ["bash", str(HOOK)],
        cwd=cwd,
        input=json.dumps({"tool_input": {"file_path": str(target)}}),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _denial(decision: dict) -> str | None:
    hook_out = decision.get("hookSpecificOutput")
    if not hook_out or hook_out.get("permissionDecision") != "deny":
        return None
    return hook_out["permissionDecisionReason"]


def test_editing_from_the_main_checkout_is_blocked(repo: Path) -> None:
    """The gap this closes. The pre-existing check only fired when the target
    was a DIFFERENT checkout, so an edit made from the main checkout to a file
    in the main checkout — the exact shape of a question-session that drifted
    into implementing — sailed through."""
    reason = _denial(_decide(repo, repo / "seed.txt"))

    assert reason is not None
    assert "MAIN checkout" in reason
    # The remedy has to be in the message: an agent that is blocked without
    # being told the next move retries or works around it.
    assert "EnterWorktree" in reason


def test_the_message_names_the_branch_and_the_read_only_escape(repo: Path) -> None:
    """Blocking is only half the job. The main checkout has legitimate
    read-only uses — six live sessions sit there asking questions, running
    `gh`, and dispatching — so the denial must say what still works, or it
    reads as "this session is useless here"."""
    reason = _denial(_decide(repo, repo / "seed.txt"))

    assert reason is not None
    assert "branch 'main'" in reason
    assert "read-only" in reason


def test_editing_inside_a_linked_worktree_is_allowed(worktree: Path) -> None:
    """The rule must not block the sanctioned path, or it just gets disabled."""
    decision = _decide(worktree, worktree / "seed.txt")

    assert _denial(decision) is None
    assert decision.get("continue") is True


def test_a_new_file_in_a_worktree_is_allowed(worktree: Path) -> None:
    """Resolution goes via the parent directory so a not-yet-created file still
    lands in the right checkout — pinned because most edits during
    implementation create files."""
    decision = _decide(worktree, worktree / "brand-new.py")

    assert _denial(decision) is None


def test_cross_checkout_edits_are_still_blocked(repo: Path, worktree: Path) -> None:
    """Regression guard on the original purpose: a stale absolute path from an
    earlier turn writing into a different checkout."""
    reason = _denial(_decide(worktree, repo / "seed.txt"))

    assert reason is not None
    assert "DIFFERENT checkout" in reason


def test_outside_a_git_repo_the_hook_stays_out_of_the_way(tmp_path: Path) -> None:
    """The hook governs this repo's worktree discipline, not the filesystem."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    decision = _decide(plain, plain / "file.txt")

    assert _denial(decision) is None
