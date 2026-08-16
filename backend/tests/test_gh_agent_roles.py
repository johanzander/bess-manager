"""Tests for scripts/gh-agent.sh role routing.

The script's whole job is choosing which token `gh` runs with, so the test
replaces `gh` with a shim that prints the token it was handed. That makes the
routing assertable without a network call or a real credential.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "gh-agent.sh"


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    shim = d / "gh"
    shim.write_text('#!/bin/sh\necho "token=$GH_TOKEN args=$*"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return d


def _run(bin_dir: Path, env_file: Path, args: list[str]) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        BESS_ENV_FILE=str(env_file),
    )
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env
    )


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    f = tmp_path / ".env"
    f.write_text("BESS_PO_TOKEN=po-secret\nBESS_AGENT_TOKEN=dev-secret\n")
    return f


def test_po_role_uses_po_token(bin_dir: Path, env_file: Path) -> None:
    result = _run(bin_dir, env_file, ["--as", "po", "issue", "comment", "1"])
    assert "token=po-secret" in result.stdout
    assert "args=issue comment 1" in result.stdout


def test_dev_role_uses_developer_token(bin_dir: Path, env_file: Path) -> None:
    result = _run(bin_dir, env_file, ["--as", "dev", "pr", "comment", "2"])
    assert "token=dev-secret" in result.stdout


def test_default_role_is_dev(bin_dir: Path, env_file: Path) -> None:
    """Existing callers (request-pr-review.sh) pass no --as and must keep
    posting as the developer identity."""
    result = _run(bin_dir, env_file, ["pr", "comment", "3"])
    assert "token=dev-secret" in result.stdout


def test_unknown_role_fails_loudly(bin_dir: Path, env_file: Path) -> None:
    result = _run(bin_dir, env_file, ["--as", "reviewer", "pr", "list"])
    assert result.returncode != 0
    assert "reviewer" in result.stderr


def test_missing_token_fails_loudly(bin_dir: Path, tmp_path: Path) -> None:
    """No fallback: an absent token raises rather than silently posting as
    whoever `gh` happens to be authenticated as."""
    empty = tmp_path / "empty.env"
    empty.write_text("")
    result = _run(bin_dir, empty, ["--as", "po", "issue", "list"])
    assert result.returncode != 0
    assert "BESS_PO_TOKEN" in result.stderr
