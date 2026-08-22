"""Tests for scripts/check-changelog.py — the beta-release CHANGELOG guard.

The script has two jobs (wired into `.claude/skills/release/SKILL.md`):

- ``build`` deterministically resolves the CHANGELOG.md merge conflict in the
  beta release flow: take beta/main's published history verbatim and insert
  the new section after the preamble, instead of letting git's 3-way merge
  guess (which repeatedly absorbed the new section into the previous one,
  #648).
- ``check`` asserts three invariants on the built file:
  * prepend-only — stripping the new section leaves beta/main's published
    history byte-identical (catches absorbed sections, dropped lines, silent
    reflows);
  * coverage — every PR merged on origin/main since the last beta appears in
    the new section (by its PR number or an issue it references) or is
    dismissed on the explicit internal list;
  * no re-announcing — every PR linked in the new section merged after the
    last beta's cut (nothing already shipped is re-listed).

The CHANGELOG links issue numbers for most entries, so coverage and
no-re-announcing map merged PRs to their issues via the merge-commit body
(GitHub embeds the PR body there).

The pure functions under test are the heart of the script; the CLI is a thin
git wrapper around them. Fixtures model a b13 release over a b12/b11 beta
history.
"""

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-changelog.py"

# The script's filename carries the issue's exact name (`check-changelog.py`,
# hyphen), which Python cannot `import`; load it by path like test_app_startup
# does for app.py.
_spec = importlib.util.spec_from_file_location("check_changelog", SCRIPT)
assert _spec is not None and _spec.loader is not None
check_changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_changelog)

ChangelogCheckError = check_changelog.ChangelogCheckError
MergedPR = check_changelog.MergedPR
build_release_changelog = check_changelog.build_release_changelog
check_coverage = check_changelog.check_coverage
check_no_reannouncing = check_changelog.check_no_reannouncing
check_prepend_only = check_changelog.check_prepend_only
extract_new_section = check_changelog.extract_new_section
parse_merged_prs = check_changelog.parse_merged_prs
parse_pr_refs = check_changelog.parse_pr_refs
strip_new_section = check_changelog.strip_new_section

# --- fixtures ---------------------------------------------------------------

_ISSUE_URL = "https://github.com/johanzander/bess-manager/issues/{}"


def _entry(desc: str, n: int) -> str:
    return f"- {desc}. ([#{n}]({_ISSUE_URL.format(n)}))\n"


PREAMBLE = "# Changelog\n\nIntro line.\n\n"

# The new section a b13 release would carry (renamed Unreleased + curated).
NEW_SECTION = (
    "## [10.1.0b13] - 2026-08-22\n"
    "\n"
    "Delta from `v10.1.0b12`. Everything else accumulated in `Unreleased` on "
    "main already shipped in `v10.1.0b12` or earlier; this release covers only "
    "what is genuinely new since then.\n"
    "\n"
    "### Fixed\n"
    "\n" + _entry("Entry A", 680) + "\n"
)

# beta/main's published history: b12 (1 entry) then b11 (1 entry).
BETA_MAIN = (
    PREAMBLE
    + "## [10.1.0b12] - 2026-08-21\n"
    + "\n"
    + "### Fixed\n"
    + "\n"
    + _entry("Entry X", 650)
    + "\n"
    + "## [10.1.0b11] - 2026-08-18\n"
    + "\n"
    + "### Fixed\n"
    + "\n"
    + _entry("Entry Y", 630)
    + "\n"
)

# The release branch's own CHANGELOG at merge-conflict time: the new section on
# top, then origin/main's (stable) history below — which beta already covers in
# its own beta sections and must be discarded in favour of beta/main's verbatim.
RELEASE_BRANCH = (
    PREAMBLE
    + NEW_SECTION
    + "## [10.0.2] - 2026-08-10\n"
    + "\n"
    + "### Fixed\n"
    + "\n"
    + _entry("Old stable entry", 600)
    + "\n"
)

# The deterministic resolution: preamble + new section + beta/main verbatim.
BUILT = PREAMBLE + NEW_SECTION + BETA_MAIN[len(PREAMBLE) :]

# The exact corruption #648 describes: b13's entries absorbed into b12's
# section, no b13 heading at all.
ABSORBED = (
    PREAMBLE
    + "## [10.1.0b12] - 2026-08-21\n"
    + "\n"
    + "### Fixed\n"
    + "\n"
    + _entry("Entry X", 650)
    + _entry("Entry A", 680)
    + "\n"
    + "## [10.1.0b11] - 2026-08-18\n"
    + "\n"
    + "### Fixed\n"
    + "\n"
    + _entry("Entry Y", 630)
    + "\n"
)

# A dropped line from published history (b7's #512 line was lost this way).
DROPPED = BUILT.replace(_entry("Entry X", 650), "")

# PRs merged on origin/main since b12's cut: #680 fixed #680, #690 fixed
# nothing tracked, #701 referenced #680 in its title.
MERGED_PRS = [
    MergedPR(680, frozenset({680})),
    MergedPR(690, frozenset()),
    MergedPR(701, frozenset({680})),
]


# --- section extraction / build --------------------------------------------


def test_extract_new_section_takes_topmost_section() -> None:
    assert extract_new_section(RELEASE_BRANCH) == NEW_SECTION


def test_extract_new_section_by_prefix() -> None:
    assert extract_new_section(BUILT, section_prefix="10.1.0b13") == NEW_SECTION


def test_extract_new_section_prefix_missing_raises() -> None:
    with pytest.raises(ChangelogCheckError):
        extract_new_section(BUILT, section_prefix="10.1.0b99")


def test_build_is_deterministic() -> None:
    assert build_release_changelog(RELEASE_BRANCH, BETA_MAIN) == BUILT


def test_build_roundtrips_strip_to_beta_main() -> None:
    assert strip_new_section(BUILT) == BETA_MAIN


# --- prepend-only -----------------------------------------------------------


def test_prepend_only_accepts_correctly_built_changelog() -> None:
    check_prepend_only(BUILT, BETA_MAIN)  # must not raise


def test_prepend_only_rejects_absorbed_section() -> None:
    with pytest.raises(ChangelogCheckError):
        check_prepend_only(ABSORBED, BETA_MAIN)


def test_prepend_only_rejects_dropped_line() -> None:
    with pytest.raises(ChangelogCheckError):
        check_prepend_only(DROPPED, BETA_MAIN)


# --- coverage ---------------------------------------------------------------


def test_coverage_flags_merged_pr_with_no_entry() -> None:
    uncovered = check_coverage(NEW_SECTION, MERGED_PRS, internal={700})
    assert uncovered == [690]


def test_coverage_passes_when_every_pr_referenced_or_dismissed() -> None:
    covered = [MergedPR(680, frozenset({680})), MergedPR(700, frozenset())]
    assert check_coverage(NEW_SECTION, covered, internal={700}) == []


def test_coverage_accepts_pr_that_references_a_linked_issue() -> None:
    # #701 isn't linked directly, but it references #680 in its title, and
    # #680 is the issue the entry links — the CHANGELOG convention.
    assert check_coverage(NEW_SECTION, MERGED_PRS, internal=set()) == [690]


# --- no re-announcing -------------------------------------------------------


def test_no_reannouncing_accepts_only_fresh_links() -> None:
    assert check_no_reannouncing(NEW_SECTION, MERGED_PRS, dismiss=set()) == []


def test_no_reannouncing_flags_already_shipped_link() -> None:
    section = NEW_SECTION + _entry("Already shipped", 650)
    assert check_no_reannouncing(section, MERGED_PRS, dismiss=set()) == [650]


def test_no_reannouncing_dismiss_exempts_a_kept_link() -> None:
    section = NEW_SECTION + _entry("Kept deliberately", 650)
    assert check_no_reannouncing(section, MERGED_PRS, dismiss={650}) == []


def test_no_reannouncing_accepts_issue_backed_by_post_cut_pr() -> None:
    # #555 is an old issue re-opened by a PR merged after the cut; the fresh
    # entry legitimately links it.
    section = NEW_SECTION + _entry("Reopened old issue", 555)
    merged = [*MERGED_PRS, MergedPR(710, frozenset({555}))]
    assert check_no_reannouncing(section, merged, dismiss=set()) == []


# --- parsing ----------------------------------------------------------------


def test_parse_pr_refs_ignores_bare_hash_refs_in_prose() -> None:
    # The "Delta from" note references #450 in prose; only the [link](form)
    # counts as an entry reference.
    text = "the #450 PWL re-solve, plus " + _entry("linked", 512)
    assert parse_pr_refs(text) == {512}


def test_parse_merged_prs_from_git_log_bodies() -> None:
    # NUL-separated full bodies (git log --format=%B%x00). GitHub embeds the
    # PR body, so "Closes #N" / "Refs #N" are the issue links. `release:` and
    # `Merge ` commits are excluded automatically.
    #
    # Real git output pads each `--format` record with a trailing newline, so
    # every block after the first begins with a blank line — this fixture
    # reproduces that exactly (a regression: the parser used to take the first
    # line of each block as the subject and silently dropped every commit
    # after the first).
    log = (
        "fix: survive a transient HA failure in the charging-power tick "
        "(#643) (#675)\n\nCloses #643\n\x00\n"
        "fix: report price health from the cache (#667)\n\n"
        "With a cold probe still ERROR.\n\nCloses #662\n\x00\n"
        "release: v10.1.0 (#674)\n\nRelease stamp.\n\x00\n"
        "Merge pull request #104 from johanzander/foo\n\nMerged.\n\x00\n"
        "feat: ship a widget (#701)\n\nAdds the widget.\n\x00\n"
    )
    assert parse_merged_prs(log) == [
        MergedPR(675, frozenset({643})),
        MergedPR(667, frozenset({662})),
        MergedPR(701, frozenset()),
    ]


# --- CLI --------------------------------------------------------------------


def _run_cli(args: list[str], **extra_env: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, **extra_env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env
    )


def _write_git_shim(bin_dir: Path, beta_path: Path, log_path: Path) -> None:
    shim = bin_dir / "git"
    shim.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "show" ]; then cat "$GIT_SHIM_BETA";\n'
        'elif [ "$1" = "log" ]; then cat "$GIT_SHIM_LOG";\n'
        'else echo "unhandled git $*" >&2; exit 1; fi\n'
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)


def test_build_cli_writes_deterministic_output(tmp_path: Path) -> None:
    new = tmp_path / "new.md"
    beta = tmp_path / "beta.md"
    out = tmp_path / "out.md"
    new.write_text(RELEASE_BRANCH)
    beta.write_text(BETA_MAIN)

    proc = _run_cli(
        ["build", "--new", str(new), "--beta", str(beta), "--out", str(out)]
    )
    assert proc.returncode == 0, proc.stderr
    assert out.read_text() == BUILT


def test_check_cli_accepts_clean_changelog(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    beta_path = tmp_path / "beta.md"
    log_path = tmp_path / "log.txt"
    beta_path.write_text(BETA_MAIN)
    # --format=%B%x00 body: subject then body with "Closes #680".
    log_path.write_text("fix: a merged PR (#680)\n\nCloses #680\n\x00")
    _write_git_shim(bin_dir, beta_path, log_path)

    changelog = tmp_path / "changelog.md"
    changelog.write_text(BUILT)

    proc = _run_cli(
        [
            "check",
            "--changelog",
            str(changelog),
            "--beta-ref",
            "beta/main",
            "--since",
            "2026-08-21T00:00:00Z",
            "--internal",
            "700",
        ],
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        GIT_SHIM_BETA=str(beta_path),
        GIT_SHIM_LOG=str(log_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
    assert "Internal no-entry list: #700" in proc.stdout


def test_check_cli_rejects_absorbed_section(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    beta_path = tmp_path / "beta.md"
    log_path = tmp_path / "log.txt"
    beta_path.write_text(BETA_MAIN)
    log_path.write_text("fix: a merged PR (#680)\n\nCloses #680\n\x00")
    _write_git_shim(bin_dir, beta_path, log_path)

    changelog = tmp_path / "changelog.md"
    changelog.write_text(ABSORBED)

    proc = _run_cli(
        [
            "check",
            "--changelog",
            str(changelog),
            "--beta-ref",
            "beta/main",
            "--since",
            "2026-08-21T00:00:00Z",
        ],
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        GIT_SHIM_BETA=str(beta_path),
        GIT_SHIM_LOG=str(log_path),
    )
    assert proc.returncode == 1
    assert "prepend-only" in proc.stderr


def test_check_cli_section_missing_is_clean_error(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    beta_path = tmp_path / "beta.md"
    log_path = tmp_path / "log.txt"
    beta_path.write_text(BETA_MAIN)
    log_path.write_text("fix: a merged PR (#680)\n\nCloses #680\n\x00")
    _write_git_shim(bin_dir, beta_path, log_path)

    changelog = tmp_path / "changelog.md"
    changelog.write_text(ABSORBED)

    proc = _run_cli(
        [
            "check",
            "--changelog",
            str(changelog),
            "--beta-ref",
            "beta/main",
            "--since-ref",
            "b2a0107c",
            "--section",
            "10.1.0b13",
        ],
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        GIT_SHIM_BETA=str(beta_path),
        GIT_SHIM_LOG=str(log_path),
    )
    assert proc.returncode == 1
    assert "no `## [` section whose heading starts with" in proc.stderr
