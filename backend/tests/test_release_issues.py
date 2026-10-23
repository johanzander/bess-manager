"""Tests for scripts/release-issues.sh — the open issues a stable release ships.

The release skill closes the issues a release shipped (#827). Which issue a PR
belongs to is decided in exactly one place, `scripts/backlog-digest.sh` (its
work-verb scan plus branch convention, #684), so this script reads the digest's
per-issue `merged_prs` instead of scanning PR text itself. It adds only the tag
range: an issue is a candidate when one of its merged PRs is in
`<prev>..<new>`, and it is *partial* when another PR is still open.

Fixtures: a throwaway git repo with two tags, and a hand-written digest handed
over through DIGEST_JSON so the test never touches GitHub.
"""

import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release-issues.sh"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.test",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.test",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, **_GIT_ENV},
    )


def _commit(repo: Path, subject: str) -> None:
    _git(repo, "commit", "--allow-empty", "-m", subject)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "fix: shipped in the previous release (#748)")
    _git(repo, "tag", "v1.0.0")
    # In the range: a subject carries only its PR number; the issue link lives
    # in the digest, not in the commit text.
    _commit(repo, "fix: fail explicitly when the SOC fallback is unavailable (#797)")
    _commit(repo, "feat: cap grid import in a peak-shaving window (#805)")
    _commit(repo, "fix: color the Diff tooltip by favorability (#765)")
    _git(repo, "tag", "v1.1.0")
    # After the range: merged to main but not in this release.
    _commit(repo, "feat: check CHANGELOG structure (#826)")
    return repo


def _digest(tmp_path: Path, items: list[dict]) -> Path:
    path = tmp_path / "digest.json"
    path.write_text(json.dumps({"items": items}))
    return path


def _run(repo: Path, digest: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT), "v1.0.0", "v1.1.0"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "DIGEST_JSON": str(digest)},
    )


def _item(
    number: int, title: str, merged_prs: list[int], open_prs: Sequence[int] = ()
) -> dict:
    return {
        "number": number,
        "title": title,
        "merged_prs": merged_prs,
        "prs": [
            {"number": n, "mergeable": "MERGEABLE", "isDraft": True} for n in open_prs
        ],
    }


def test_issue_with_a_merged_pr_in_range_is_resolved(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    digest = _digest(tmp_path, [_item(792, "SOC unavailable", [797])])

    proc = _run(repo, digest)

    assert proc.returncode == 0, proc.stderr
    assert "#792" in proc.stdout and "resolved" in proc.stdout
    assert "#797" in proc.stdout


def test_issue_with_another_open_pr_is_partial(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    digest = _digest(tmp_path, [_item(96, "peak shaving", [805], open_prs=[900])])

    proc = _run(repo, digest)

    assert proc.returncode == 0, proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if "#96" in ln)
    assert "partial" in line and "#900" in line


def test_issue_found_through_a_pr_that_names_it_nowhere(tmp_path: Path) -> None:
    # #765 never says "Refs #763" in its commit text. The digest still links
    # them (branch convention), and the script follows the digest.
    repo = _make_repo(tmp_path)
    digest = _digest(tmp_path, [_item(763, "Diff color", [765])])

    proc = _run(repo, digest)

    assert "#763" in proc.stdout and "resolved" in proc.stdout


def test_issue_shipped_in_an_earlier_release_is_not_listed(tmp_path: Path) -> None:
    # #748 is before v1.0.0: that release should have closed it, and this one
    # must not announce it again.
    repo = _make_repo(tmp_path)
    digest = _digest(tmp_path, [_item(717, "old fix", [748])])

    proc = _run(repo, digest)

    assert proc.returncode == 0, proc.stderr
    assert "#717" not in proc.stdout


def test_issue_merged_after_the_range_is_not_listed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    digest = _digest(tmp_path, [_item(822, "structure check", [826])])

    proc = _run(repo, digest)

    assert "#822" not in proc.stdout


def test_a_pr_number_is_not_mistaken_for_an_issue(tmp_path: Path) -> None:
    # Subject numbers are PR numbers; only digest items (open issues) can be
    # listed, so a PR number with no matching item produces nothing.
    repo = _make_repo(tmp_path)
    digest = _digest(tmp_path, [])

    proc = _run(repo, digest)

    assert proc.returncode == 0, proc.stderr
    assert "#797" not in proc.stdout
    assert "no open issues" in proc.stdout.lower()


def test_unknown_tag_is_a_clear_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    digest = _digest(tmp_path, [])

    proc = subprocess.run(
        [str(SCRIPT), "v1.0.0", "v9.9.9"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "DIGEST_JSON": str(digest)},
    )

    assert proc.returncode != 0
    assert "v9.9.9" in proc.stderr


def test_the_end_of_the_range_may_be_a_branch(tmp_path: Path) -> None:
    # The skill lists issues before the new tag exists, using origin/main.
    repo = _make_repo(tmp_path)
    digest = _digest(tmp_path, [_item(822, "structure check", [826])])

    proc = subprocess.run(
        [str(SCRIPT), "v1.0.0", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "DIGEST_JSON": str(digest)},
    )

    assert proc.returncode == 0, proc.stderr
    assert "#822" in proc.stdout and "resolved" in proc.stdout
