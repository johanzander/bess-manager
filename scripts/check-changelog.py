#!/usr/bin/env python3
"""Guard the beta-release CHANGELOG against silent corruption.

The beta release flow (`.claude/skills/release/SKILL.md`) merges `beta/main`
into a fresh release branch. `CHANGELOG.md` conflicts on every release, and
git's 3-way merge has repeatedly collapsed the newly-prepended section into
the previous one (b7/b8 and b9/b10 on the published beta history, #648).

This script has two subcommands:

``build``
    Resolve the CHANGELOG merge deterministically instead of by hand: take
    `beta/main`'s published history verbatim and insert the new section (the
    `## [` section identified by ``--section``, default the topmost one) of the
    release branch's own CHANGELOG after the preamble. The result is
    byte-deterministic — this removes the failure mode rather than detecting
    it.

``check``
    Assert three invariants on a CHANGELOG, each replacing a rule the release
    skill used to describe in prose:

    1. **Prepend-only** (needs ``--beta-ref``/``--beta-file``) — strip the new
       section and the remainder must be byte-identical to `beta/main`'s
       CHANGELOG. Catches absorbed sections, dropped lines, and silent reflows
       anywhere in published history.
    2. **Coverage** (needs the cut) — every `(#N)` merge commit on
       `origin/main` since the previous beta's cut must be represented in the
       new section — by its own PR number or by an issue it references — or be
       named on the explicit ``--internal`` list (which the script prints on
       the record). `release:` commits and merge commits are excluded
       automatically.
    3. **No re-announcing** (needs the cut) — every `#N` linked in the new
       section must belong to a PR that merged after the previous beta's cut
       (its number or one of its referenced issues). Nothing already shipped
       may be re-listed.

    The CHANGELOG links issue numbers for most entries, not the PR that fixed
    them, so the coverage and no-re-announcing checks map merged PRs to their
    issues via the merge-commit body (GitHub embeds the PR body there). The
    cut is the previous beta's branch point: ``--since-ref`` (a commit) or
    ``--since`` (a timestamp); with neither it defaults to the merge-base of
    `origin/main` and `beta/main`.

Usage:
    scripts/check-changelog.py build --new <release-changelog.md> \\
        --beta <beta-changelog.md> [--out <path>] [--section <prefix>]
    scripts/check-changelog.py check --changelog <path> \\
        [--section <prefix>] \\
        [--since <timestamp>] [--since-ref <git-ref>] \\
        [--internal <comma-separated PRs>] [--internal-file <path>] \\
        [--dismiss <comma-separated numbers>] [--dismiss-file <path>] \\
        [--beta-ref <git-ref>] [--beta-file <path>] [--remote <name>]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# PR number referenced as a markdown link `[#N](...)` — the entry format the
# CHANGELOG uses. A bare `#N` in prose (e.g. a "Delta from" note's context
# list) is deliberately not matched: a note is context, not an entry.
_PR_LINK_RE = re.compile(r"\[#(\d+)\]\(")
# PR number in a merge-commit subject `fix: ... (#667)`.
_PR_COMMIT_RE = re.compile(r"\(#(\d+)\)")
# Issue references in a merge-commit body (GitHub embeds the PR body there):
# `Closes #662`, `Fixes #N`, `Refs #N`, ...
_ISSUE_REF_RE = re.compile(
    r"\b(?:closes|fixes|refs|resolves|addresses)\s+#(\d+)", re.IGNORECASE
)
# Subjects that never need a changelog entry: the release's own stamp, an
# actual merge commit, or the one-time beta reset.
_AUTO_EXCLUDE_RE = re.compile(
    r"^(release:|Merge |chore: reset beta/main)", re.IGNORECASE
)


class ChangelogCheckError(Exception):
    """Raised when a CHANGELOG invariant is violated."""


class MergedPR(NamedTuple):
    """A PR merged on origin/main since the cut, with the issues it references."""

    number: int
    issues: frozenset[int] = frozenset()


def _heading_line_indexes(lines: list[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if line.startswith("## [")]


def _splitlines_keepends(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _section_bounds(lines: list[str], section_prefix: str | None) -> tuple[int, int]:
    """Start/end line indexes of the section treated as "new".

    With *section_prefix*, the section whose heading starts with
    ``## [<section_prefix>]``; otherwise the topmost ``## [` section.
    """
    headings = _heading_line_indexes(lines)
    if not headings:
        raise ChangelogCheckError("no `## [` section heading found in CHANGELOG")
    if section_prefix is None:
        idx = headings[0]
    else:
        matches = [i for i in headings if lines[i].startswith(f"## [{section_prefix}]")]
        if not matches:
            raise ChangelogCheckError(
                f"no `## [` section whose heading starts with "
                f"`## [{section_prefix}]` found in CHANGELOG"
            )
        idx = matches[0]
    pos = headings.index(idx)
    end = headings[pos + 1] if pos + 1 < len(headings) else len(lines)
    return idx, end


def extract_new_section(changelog: str, section_prefix: str | None = None) -> str:
    """The ``## [` section of *changelog* identified by *section_prefix*."""
    lines = _splitlines_keepends(changelog)
    start, end = _section_bounds(lines, section_prefix)
    return "".join(lines[start:end])


def strip_new_section(changelog: str, section_prefix: str | None = None) -> str:
    """*changelog* with its new section removed."""
    lines = _splitlines_keepends(changelog)
    start, end = _section_bounds(lines, section_prefix)
    return "".join(lines[:start] + lines[end:])


def insert_new_section(beta_changelog: str, new_section: str) -> str:
    """*beta_changelog* verbatim, with *new_section* inserted after the preamble."""
    lines = _splitlines_keepends(beta_changelog)
    headings = _heading_line_indexes(lines)
    if not headings:
        # First beta on a beta repo with no published sections yet: append
        # after the preamble.
        return beta_changelog.rstrip("\n") + "\n\n" + new_section
    insert_at = headings[0]
    return "".join(lines[:insert_at]) + new_section + "".join(lines[insert_at:])


def build_release_changelog(
    release_changelog: str, beta_changelog: str, section_prefix: str | None = None
) -> str:
    """Deterministically resolve the release-branch CHANGELOG.

    Takes the *section_prefix*-identified section of the release branch's own
    *release_changelog* (the renamed `Unreleased` block) and inserts it into
    *beta_changelog*, which is otherwise taken verbatim.
    """
    return insert_new_section(
        beta_changelog, extract_new_section(release_changelog, section_prefix)
    )


def parse_pr_refs(text: str) -> set[int]:
    """PR/issue numbers referenced as ``[#N](...)`` links in *text*."""
    return {int(n) for n in _PR_LINK_RE.findall(text)}


def parse_merged_prs(git_log: str) -> list[MergedPR]:
    """Parse ``git log --format=%B%x00`` output into merged PRs + issue refs.

    Each NUL-separated block is one commit's full body. The PR number is the
    trailing ``(#N)`` in the subject (GitHub appends it); earlier ``(#N)`` in
    the subject and ``Closes/Fixes/Refs/... #N`` in the body are issue refs.
    """
    merged: list[MergedPR] = []
    for blob in git_log.split("\x00"):
        if not blob.strip():
            continue
        # git pads each `--format` record with a trailing newline, so blobs
        # after the first start with a blank line; the subject is the first
        # non-empty line.
        nonempty = [line for line in blob.splitlines() if line.strip()]
        if not nonempty:
            continue
        subject = nonempty[0]
        if _AUTO_EXCLUDE_RE.match(subject):
            continue
        prs = [int(n) for n in _PR_COMMIT_RE.findall(subject)]
        if not prs:
            continue
        number = prs[-1]
        issues = {int(n) for n in prs[:-1]}
        issues.update(int(n) for n in _ISSUE_REF_RE.findall(blob))
        merged.append(MergedPR(number, frozenset(issues)))
    return merged


def check_prepend_only(
    release_changelog: str, beta_changelog: str, section_prefix: str | None = None
) -> None:
    """Raise unless stripping the new section leaves *beta_changelog* byte-identical."""
    remainder = strip_new_section(release_changelog, section_prefix)
    if remainder != beta_changelog:
        raise ChangelogCheckError(
            "prepend-only violated: the CHANGELOG below the new section is not "
            "byte-identical to beta/main's published history"
        )


def check_coverage(
    new_section: str, merged_prs: list[MergedPR], internal: set[int]
) -> list[int]:
    """PRs merged since the cut with no entry in the section (empty = pass).

    A merged PR is covered when its own number or any issue it references
    appears as a `[#N](...)` link in *new_section*. The CHANGELOG links issue
    numbers for most entries, so the PR-to-issue mapping from the merge-commit
    body is what makes this check meaningful.
    """
    section_links = parse_pr_refs(new_section)
    uncovered: list[int] = []
    for pr in merged_prs:
        if pr.number in internal:
            continue
        if ({pr.number} | pr.issues) & section_links:
            continue
        uncovered.append(pr.number)
    return sorted(uncovered)


def check_no_reannouncing(
    new_section: str, merged_prs: list[MergedPR], dismiss: set[int]
) -> list[int]:
    """Links in the new section not backed by a post-cut PR (empty = pass).

    A link is re-announcing old work when neither its number nor any post-cut
    merged PR references it — i.e. its work shipped before the cut. *dismiss*
    exempts links the maintainer has explicitly decided to keep.
    """
    section_links = parse_pr_refs(new_section)
    referenced: set[int] = set()
    for pr in merged_prs:
        referenced.add(pr.number)
        referenced.update(pr.issues)
    return sorted((section_links - referenced) - dismiss)


def _run_git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise ChangelogCheckError(
            f"`git {' '.join(args)}` failed:\n{proc.stderr.strip()}"
        )
    return proc.stdout


def _resolve_beta_changelog(beta_ref: str | None, beta_file: str | None) -> str | None:
    if beta_ref is not None:
        return _run_git(["show", f"{beta_ref}:CHANGELOG.md"])
    if beta_file is not None:
        return Path(beta_file).read_text()
    return None


def _merged_prs(
    since: str | None, since_ref: str | None, remote: str
) -> list[MergedPR]:
    """Merged PRs on *remote*/main since the cut, with their issue references.

    The cut is ``--since-ref`` (a commit), ``--since`` (a timestamp), or — with
    neither — the merge-base of *remote*/main and `beta/main`, i.e. the point
    the previous beta branched from main.
    """
    if since_ref is not None:
        log = _run_git(["log", f"{since_ref}..{remote}/main", "--format=%B%x00"])
    elif since is not None:
        log = _run_git(["log", f"{remote}/main", f"--since={since}", "--format=%B%x00"])
    else:
        base = _run_git(["merge-base", f"{remote}/main", "beta/main"]).strip()
        log = _run_git(["log", f"{base}..{remote}/main", "--format=%B%x00"])
    return parse_merged_prs(log)


def _parse_number_list(value: str | None, file_path: str | None) -> set[int]:
    numbers: set[int] = set()
    if value:
        numbers.update(int(part.strip()) for part in value.split(",") if part.strip())
    if file_path is not None:
        for line in Path(file_path).read_text().splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                numbers.add(int(line))
    return numbers


def cmd_build(args: argparse.Namespace) -> int:
    release = Path(args.new).read_text()
    beta = Path(args.beta).read_text()
    built = build_release_changelog(release, beta, args.section)
    if args.out:
        Path(args.out).write_text(built)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(built)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    changelog = Path(args.changelog).read_text()
    beta = _resolve_beta_changelog(args.beta_ref, args.beta_file)
    internal = _parse_number_list(args.internal, args.internal_file)
    dismiss = _parse_number_list(args.dismiss, args.dismiss_file)

    violations: list[str] = []

    if beta is not None:
        try:
            check_prepend_only(changelog, beta, args.section)
        except ChangelogCheckError as exc:
            violations.append(str(exc))

    merged: list[MergedPR] | None = None
    try:
        merged = _merged_prs(args.since, args.since_ref, args.remote)
    except ChangelogCheckError as exc:
        print(f"note: coverage/no-re-announcing skipped ({exc})", file=sys.stderr)

    if merged is not None:
        try:
            new_section = extract_new_section(changelog, args.section)
        except ChangelogCheckError as exc:
            violations.append(str(exc))
        else:
            uncovered = check_coverage(new_section, merged, internal)
            if uncovered:
                violations.append(
                    "coverage violated: merged since the last beta with no entry "
                    "and not dismissed: " + ", ".join(f"#{n}" for n in uncovered)
                )
            reannounced = check_no_reannouncing(new_section, merged, dismiss)
            if reannounced:
                violations.append(
                    "no-re-announcing violated: linked in the new section but "
                    "merged before the cut (already shipped): "
                    + ", ".join(f"#{n}" for n in reannounced)
                )

    if internal:
        print("Internal no-entry list: " + ", ".join(f"#{n}" for n in sorted(internal)))
    if dismiss:
        print("Dismissed links: " + ", ".join(f"#{n}" for n in sorted(dismiss)))

    if violations:
        for violation in violations:
            print(f"ERROR: {violation}", file=sys.stderr)
        return 1
    print("check-changelog: OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Guard the beta-release CHANGELOG against silent corruption."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser(
        "build", help="deterministically resolve the CHANGELOG merge"
    )
    build_p.add_argument(
        "--new", required=True, help="release branch's CHANGELOG (ours)"
    )
    build_p.add_argument("--beta", required=True, help="beta/main's CHANGELOG (theirs)")
    build_p.add_argument(
        "--out", help="write the result to this path instead of stdout"
    )
    build_p.add_argument(
        "--section", help="new section heading prefix (default: topmost)"
    )
    build_p.set_defaults(command="build")

    check_p = sub.add_parser("check", help="assert the CHANGELOG invariants")
    check_p.add_argument("--changelog", required=True)
    check_p.add_argument(
        "--section", help="new section heading prefix (default: topmost)"
    )
    check_p.add_argument("--since", help="git log --since value (previous beta's cut)")
    check_p.add_argument(
        "--since-ref", help="git ref/commit to cut the merged-PR range"
    )
    check_p.add_argument(
        "--internal", help="comma-separated PR numbers dismissed as internal"
    )
    check_p.add_argument(
        "--internal-file", help="file of dismissed PR numbers, one per line"
    )
    check_p.add_argument(
        "--dismiss", help="comma-separated link numbers exempt from no-re-announcing"
    )
    check_p.add_argument(
        "--dismiss-file", help="file of exempted link numbers, one per line"
    )
    check_p.add_argument(
        "--beta-ref", help="git ref whose CHANGELOG.md is beta/main's history"
    )
    check_p.add_argument("--beta-file", help="path to beta/main's CHANGELOG.md")
    check_p.add_argument(
        "--remote", default="origin", help="remote for the git log (default origin)"
    )
    check_p.set_defaults(command="check")

    args = parser.parse_args()

    if args.command == "check":
        if (
            args.beta_ref is None
            and args.beta_file is None
            and args.since is None
            and args.since_ref is None
        ):
            parser.error(
                "check needs --beta-ref/--beta-file and/or --since/--since-ref "
                "to verify anything"
            )
        return cmd_check(args)
    if args.command == "build":
        return cmd_build(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
