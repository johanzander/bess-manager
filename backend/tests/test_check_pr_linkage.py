"""Tests for scripts/check-pr-linkage.sh -- the CI gate that fails a PR whose
body links no issue (#828).

The board, `advance-pr` and the release skill's issue-closing step all find a
PR's issue through its body. The check must accept exactly what the board
associates, so it shares the board's linkage rule (`scripts/lib/pr-linkage.jq`)
rather than restating it; the last test pins that there is one copy.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-pr-linkage.sh"


def _check(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)], input=body, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    "body",
    [
        "## Summary\n- thing\n\nRefs #828\n",
        "Closes #12",
        "fixes #12",
        "Resolves #12",
        "Part of #409",
        "tracking #409",
        "Tracks #409",
        "No issue: CI-only chore, no user-facing change",
        "## Summary\n\n  No issue: docs typo\n",
    ],
)
def test_a_linked_body_passes(body: str) -> None:
    proc = _check(body)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "body",
    [
        "",
        "## Summary\n- a change with no issue reference at all\n",
        # A bare number or a cross-reference is context, not linkage -- the
        # board would not associate it, so the check must not accept it.
        "Related to #828",
        "Blocked by #828",
        "see #828",
        "Not part of #828",
        # A verb-shaped substring is not the verb.
        "the counterpart of #828",
        # A backticked worked example is not a declaration.
        "Use the line `Refs #828` in your body",
        # The escape hatch needs a reason, and must start a line.
        "No issue:",
        "No issue:   \n",
        "this PR has No issue: really",
    ],
)
def test_an_unlinked_body_fails_and_says_how_to_fix_it(body: str) -> None:
    proc = _check(body)
    assert proc.returncode == 1
    assert "Refs #" in proc.stderr
    assert "No issue:" in proc.stderr


def test_the_untouched_pr_template_fails() -> None:
    # The template documents the accepted spellings inside an HTML comment,
    # `No issue: <reason>` among them. That hint is invisible on GitHub and
    # must not satisfy the check, or an unfilled template would pass.
    template = (REPO_ROOT / ".github" / "pull_request_template.md").read_text()
    assert _check(template).returncode == 1
    assert _check(template.replace("Refs #", "Refs #828")).returncode == 0


def test_the_linkage_regex_is_declared_once() -> None:
    # The check and the board must not be able to disagree. Before #828 the
    # work-verb regex was kept "byte-identical" by hand in two jq programs;
    # a third copy in the check would be one more place for them to drift.
    pattern = re.compile(r"\(\?:fixes\|closes\|resolves")
    holders = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "scripts").rglob("*")
        if p.is_file()
        and p.suffix in {".sh", ".jq"}
        and pattern.search(p.read_text(errors="ignore"))
    )
    assert holders == ["scripts/lib/pr-linkage.jq"]
