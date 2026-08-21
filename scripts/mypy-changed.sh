#!/usr/bin/env bash
#
# Type-check the Python files this branch touches, failing only on errors the
# branch INTRODUCED.
#
# Why a ratchet rather than "the changed files must be clean" (#614's original
# shape): mypy reports errors in the modules a checked file imports, not only
# in the file named on the command line. Handing it one core/bess file pulls in
# ha_api_controller.py and 30 others, so the gate demanded a repo-wide cleanup
# that its own comment ruled out ("Repo-wide is not an option (2914 errors
# across 191 files)"). No PR touching core/bess could pass it -- #643's
# six-line fix hit 404 errors across 31 files while introducing none of them.
#
# Two changes make the gate mean what it always intended:
#
#   --follow-imports=silent   errors are attributed to the files under test,
#                             not to whatever they import.
#   baseline comparison       the same files are checked at the merge-base and
#                             only NEW error signatures fail.
#
# The baseline is computed, not committed: the merge-base tree is extracted and
# type-checked on the fly. That keeps the burn-down honest (fixing an old error
# is never required, but re-introducing one is caught) with no generated file to
# drift or regenerate.
#
# Signatures drop line numbers deliberately -- inserting a line above an
# existing error must not read as a new one.
#
# Usage:
#   scripts/mypy-changed.sh <mypy-binary> [--include-worktree]
#
# --include-worktree also considers uncommitted and untracked files, which is
# what a local pre-commit run wants and CI does not (CI has only the commit).
#
# Exit: 0 clean or only pre-existing errors; 1 new errors; 2 setup failure.

set -uo pipefail

MYPY="${1:?usage: mypy-changed.sh <mypy-binary> [--include-worktree]}"
INCLUDE_WORKTREE="${2:-}"

# Resolved to an absolute path up front: the baseline pass runs from inside the
# extracted tree, where a relative ".venv/bin/mypy" does not exist. Left
# relative, that pass silently produced NO baseline and every pre-existing
# error read as newly introduced.
if [ -x "$MYPY" ]; then
    MYPY=$(cd "$(dirname "$MYPY")" && pwd)/$(basename "$MYPY")
elif ! MYPY=$(command -v "$MYPY"); then
    echo "❌ mypy binary not found: ${1}"
    exit 2
fi

MYPY_ARGS=(--explicit-package-bases --ignore-missing-imports --follow-imports=silent)

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "❌ Not a git repository — mypy checked nothing."
    exit 2
}
cd "$repo_root" || exit 2

# origin/main may be absent in a fresh CI checkout; FETCH_HEAD covers the
# `git fetch --no-tags origin main` the workflow runs just before this.
base=""
for ref in origin/main FETCH_HEAD; do
    if base=$(git merge-base "$ref" HEAD 2>/dev/null) && [ -n "$base" ]; then
        break
    fi
    base=""
done
if [ -z "$base" ]; then
    echo "❌ Cannot resolve a merge-base against main — mypy checked nothing."
    echo "   Run: git fetch origin main"
    exit 2
fi

# sort -u is load-bearing: a file changed on the branch AND dirty in the
# working tree appears in both diffs, and mypy fails with "Duplicate module
# named ..." when handed the same path twice.
collect() {
    git diff --name-only --diff-filter=d "$base" HEAD
    if [ "$INCLUDE_WORKTREE" = "--include-worktree" ]; then
        git diff --name-only --diff-filter=d HEAD
        git ls-files --others --exclude-standard
    fi
}

changed=()
while IFS= read -r f; do
    case "$f" in *.py) [ -e "$f" ] && changed+=("$f") ;; esac
done <<EOF
$(collect | sort -u)
EOF

if [ ${#changed[@]} -eq 0 ]; then
    echo "✅ mypy OK (no changed Python files)"
    exit 0
fi

# file:code:message — no line number, so unrelated insertions above an existing
# error do not masquerade as new ones.
signatures() {
    sed -E 's/^([^:]+):[0-9]+:([0-9]+:)? /\1: /' \
        | grep -E ' error: ' \
        | sort
}

head_errors=$("$MYPY" "${MYPY_ARGS[@]}" "${changed[@]}" 2>/dev/null | signatures)

# Baseline: the same paths as they stand at the merge-base. A file added on
# this branch has no baseline entry, so all of its errors count as new — a new
# file is expected to be clean.
#
# Extracted with `git archive` rather than `git worktree add`: this repo is
# shared with other checkouts and agent sessions, and registering/removing a
# worktree as a side effect of a lint gate is not worth the blast radius. The
# whole tree is extracted, not just the changed files, because
# --follow-imports=silent still has to RESOLVE imports to silence them.
base_errors=""
tmp_tree=$(mktemp -d)
cleanup() { rm -rf "$tmp_tree"; }
trap cleanup EXIT

if git archive "$base" | tar -x -C "$tmp_tree" 2>/dev/null; then
    base_files=()
    for f in "${changed[@]}"; do
        [ -e "$tmp_tree/$f" ] && base_files+=("$f")
    done
    if [ ${#base_files[@]} -gt 0 ]; then
        # Exit status is checked, not discarded. mypy exits 0 (clean) or 1
        # (errors found); anything else is a crash or a usage error, and
        # treating that as "no baseline errors" would flag the entire
        # pre-existing backlog as newly introduced.
        base_raw=$(cd "$tmp_tree" && "$MYPY" "${MYPY_ARGS[@]}" "${base_files[@]}" 2>&1)
        base_status=$?
        if [ "$base_status" -gt 1 ]; then
            echo "❌ Baseline mypy run failed (exit ${base_status}) at ${base}:"
            printf '%s\n' "$base_raw" | tail -5
            echo "   Refusing to guess — every pre-existing error would read as new."
            exit 2
        fi
        base_errors=$(printf '%s\n' "$base_raw" | signatures)
    fi
else
    echo "❌ Could not extract the baseline tree at ${base}."
    echo "   Refusing to guess — every pre-existing error would read as new."
    exit 2
fi

new_errors=$(comm -13 <(printf '%s\n' "$base_errors") <(printf '%s\n' "$head_errors"))
new_count=$(printf '%s\n' "$new_errors" | grep -c ' error: ')

if [ "$new_count" -gt 0 ]; then
    echo "❌ mypy: ${new_count} new type error(s) introduced by this branch:"
    printf '%s\n' "$new_errors" | grep ' error: ' | sed 's/^/   /'
    echo
    echo "   Pre-existing errors in these files are not your problem — only"
    echo "   the ones above are. Reproduce with:"
    printf '   %s %s %s\n' "$MYPY" "${MYPY_ARGS[*]}" "${changed[*]}"
    exit 1
fi

pre_existing=$(printf '%s\n' "$head_errors" | grep -c ' error: ')
if [ "$pre_existing" -gt 0 ]; then
    echo "✅ mypy OK (no new errors; ${pre_existing} pre-existing in touched files)"
else
    echo "✅ mypy OK (changed files)"
fi
