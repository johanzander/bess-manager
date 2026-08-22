"""Tests for scripts/fleet-manifest.sh.

The manifest replaces `git worktree list` as the answer to "what is in
flight", so the properties that matter are the ones a caller depends on:
a registered dispatch reads back, a status update is visible to the next
reader, and a second live `product-owner` is refused rather than silently
accepted (only that role has `memory: project`, so two of them would race
on the same memory files).

Every test points BESS_FLEET_DB at a tmp_path database. Nothing here needs
a container, a token, or the network.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "fleet-manifest.sh"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "fleet" / "manifest.db"


def _run(db: Path, args: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ, BESS_FLEET_DB=str(db))
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env
    )


def _register(
    db: Path, container: str, role: str = "dev", issue: int = 1
) -> subprocess.CompletedProcess:
    return _run(
        db,
        [
            "register",
            f"/clones/issue-{issue}",
            str(issue),
            f"fix/issue-{issue}",
            container,
            role,
        ],
    )


def test_register_then_get_round_trips(db: Path) -> None:
    assert _register(db, "agent-1", issue=502).returncode == 0

    result = _run(db, ["get", "agent-1"])
    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)[0]

    assert row["container_id"] == "agent-1"
    assert row["clone_path"] == "/clones/issue-502"
    assert row["issue_or_pr"] == 502
    assert row["branch"] == "fix/issue-502"
    assert row["role"] == "dev"
    assert row["status"] == "working"
    assert row["started_at"].endswith("Z")


def test_register_creates_the_database_and_its_directory(db: Path) -> None:
    """run-agent.sh registers before any work happens, on a machine where
    .fleet/ may not exist yet -- so creating it is the script's job."""
    assert not db.parent.exists()
    assert _register(db, "agent-1").returncode == 0
    assert db.exists()


def test_update_status_is_visible_to_the_next_reader(db: Path) -> None:
    _register(db, "agent-1")

    assert _run(db, ["update-status", "agent-1", "needs_input"]).returncode == 0

    row = json.loads(_run(db, ["get", "agent-1"]).stdout)[0]
    assert row["status"] == "needs_input"


def test_list_returns_every_dispatch(db: Path) -> None:
    _register(db, "agent-1", issue=1)
    _register(db, "agent-2", issue=2)

    rows = json.loads(_run(db, ["list"]).stdout)
    assert {r["container_id"] for r in rows} == {"agent-1", "agent-2"}


def test_list_filters_by_status(db: Path) -> None:
    _register(db, "agent-1", issue=1)
    _register(db, "agent-2", issue=2)
    _run(db, ["update-status", "agent-2", "done"])

    rows = json.loads(_run(db, ["list", "--status", "working"]).stdout)
    assert [r["container_id"] for r in rows] == ["agent-1"]


def test_list_on_an_empty_manifest_is_valid_json(db: Path) -> None:
    """Callers parse this; sqlite3 -json prints nothing at all for zero rows,
    which json.loads rejects."""
    result = _run(db, ["list"])
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_get_on_an_unknown_container_fails(db: Path) -> None:
    result = _run(db, ["get", "never-registered"])
    assert result.returncode != 0


def test_second_live_product_owner_is_refused(db: Path) -> None:
    assert _register(db, "po-1", role="po").returncode == 0

    result = _register(db, "po-2", role="po")
    assert result.returncode != 0
    assert "product-owner" in result.stderr

    # ...and the refused dispatch left no row behind.
    rows = json.loads(_run(db, ["list"]).stdout)
    assert [r["container_id"] for r in rows] == ["po-1"]


def test_product_owner_can_be_replaced_once_the_previous_one_is_done(db: Path) -> None:
    _register(db, "po-1", role="po")
    _run(db, ["update-status", "po-1", "done"])

    assert _register(db, "po-2", role="po").returncode == 0


def test_the_singleton_rule_does_not_apply_to_implementers(db: Path) -> None:
    """Fleet-scale parallelism is the whole point for role=dev."""
    assert _register(db, "agent-1", issue=1).returncode == 0
    assert _register(db, "agent-2", issue=2).returncode == 0


def test_set_branch_fills_in_what_dispatch_could_not_know(db: Path) -> None:
    """implement-issue Step 1 derives the branch name from the issue itself, so
    run-agent.sh cannot register it -- the agent reports it once Step 4 runs."""
    _run(db, ["register", "/clones/issue-502", "502", "", "agent-1", "dev"])

    assert _run(db, ["set-branch", "agent-1", "fix/issue-502-slug"]).returncode == 0

    row = json.loads(_run(db, ["get", "agent-1"]).stdout)[0]
    assert row["branch"] == "fix/issue-502-slug"


def test_set_branch_on_an_unknown_container_fails(db: Path) -> None:
    assert _run(db, ["set-branch", "never-registered", "fix/x"]).returncode != 0


def test_the_product_owner_registers_without_an_issue(db: Path) -> None:
    """run-po.sh dispatches at the backlog, not at a number -- so an empty
    issue is the normal case for that role, not a malformed call."""
    result = _run(
        db, ["register", "/clones/product-owner", "", "main", "bess-po", "po"]
    )

    assert result.returncode == 0, result.stderr
    row = json.loads(_run(db, ["get", "bess-po"]).stdout)[0]
    assert row["role"] == "po"
    assert row["issue_or_pr"] in (None, "", 0)


def test_unknown_status_is_refused(db: Path) -> None:
    _register(db, "agent-1")
    result = _run(db, ["update-status", "agent-1", "hibernating"])
    assert result.returncode != 0

    row = json.loads(_run(db, ["get", "agent-1"]).stdout)[0]
    assert row["status"] == "working"


def test_unknown_role_is_refused(db: Path) -> None:
    result = _register(db, "agent-1", role="architect")
    assert result.returncode != 0


def test_update_status_on_an_unknown_container_fails(db: Path) -> None:
    """A silent no-op here would show as an agent stuck in 'working' forever."""
    result = _run(db, ["update-status", "never-registered", "done"])
    assert result.returncode != 0


def test_registering_over_a_live_container_fails(db: Path) -> None:
    """That id belongs to an agent still working -- overwriting its row would
    lose the only record of it."""
    assert _register(db, "agent-1", issue=1).returncode == 0
    assert _register(db, "agent-1", issue=2).returncode != 0


def test_redispatching_a_finished_issue_reclaims_its_row(db: Path) -> None:
    """The container id comes from the issue number, so re-dispatching #502
    reuses it -- and re-dispatch is the normal case, since implement-issue
    Step 0 treats it as a resume. A finished dispatch must not block its own."""
    _register(db, "agent-1", issue=502)
    first = json.loads(_run(db, ["get", "agent-1"]).stdout)[0]
    _run(db, ["update-status", "agent-1", "done"])

    assert _register(db, "agent-1", issue=502).returncode == 0

    row = json.loads(_run(db, ["get", "agent-1"]).stdout)[0]
    assert row["status"] == "working"
    assert row["started_at"] >= first["started_at"]
    # ...and still exactly one row, not a second one for the same container.
    assert len(json.loads(_run(db, ["list"]).stdout)) == 1
