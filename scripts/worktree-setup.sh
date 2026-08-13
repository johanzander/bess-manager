#!/bin/bash
#
# One-shot dependency bootstrap for a freshly created git worktree (issue #556).
#
# A new worktree has no .venv and no node_modules, so a full local verification
# run spends most of its time reinstalling dependencies that already exist,
# byte-identical, in the main checkout. This shares them instead, and repairs
# the Playwright browser cache when a half-finished install left it unusable.
#
# Usage: run once, from the root of the worktree:
#
#     ./scripts/worktree-setup.sh

set -euo pipefail

WORKTREE_ROOT=$(git rev-parse --show-toplevel)
GIT_DIR=$(cd "$(git rev-parse --git-dir)" && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)

if [ "$GIT_DIR" = "$GIT_COMMON" ]; then
    echo "❌ Not in a linked worktree — run this from a worktree, not the main checkout." >&2
    exit 1
fi

MAIN_CHECKOUT=$(dirname "$GIT_COMMON")
cd "$WORKTREE_ROOT"

echo "🔗 Sharing dependencies from $MAIN_CHECKOUT"

# --- Python virtualenv -------------------------------------------------------

if [ -L .venv ] && [ ! -e .venv ]; then
    echo "   .venv is a broken symlink — removing"
    rm .venv
fi

if [ -e .venv ]; then
    echo "   .venv already present"
elif [ ! -d "$MAIN_CHECKOUT/.venv" ]; then
    echo "❌ $MAIN_CHECKOUT/.venv does not exist — create it in the main checkout first." >&2
    exit 1
else
    ln -s "$MAIN_CHECKOUT/.venv" .venv
    echo "   .venv → $MAIN_CHECKOUT/.venv"
fi

# --- Node dependencies -------------------------------------------------------
#
# Sharing node_modules is only valid while the lockfiles agree. A branch that
# changes dependencies gets its own real install — never the main checkout's
# tree under a different lockfile.

for pkg in frontend e2e; do
    [ -d "$pkg" ] || continue

    if [ -L "$pkg/node_modules" ] && [ ! -e "$pkg/node_modules" ]; then
        echo "   $pkg/node_modules is a broken symlink — removing"
        rm "$pkg/node_modules"
    fi

    if [ -e "$pkg/node_modules" ]; then
        echo "   $pkg/node_modules already present"
        continue
    fi

    if [ -d "$MAIN_CHECKOUT/$pkg/node_modules" ] &&
        cmp -s "$pkg/package-lock.json" "$MAIN_CHECKOUT/$pkg/package-lock.json"; then
        ln -s "$MAIN_CHECKOUT/$pkg/node_modules" "$pkg/node_modules"
        echo "   $pkg/node_modules → $MAIN_CHECKOUT/$pkg/node_modules"
    else
        echo "   $pkg: lockfile differs from the main checkout (or it has no"
        echo "   node_modules) — installing into this worktree instead of sharing"
        (cd "$pkg" && npm install)
    fi
done

# --- Playwright browsers -----------------------------------------------------
#
# Browsers live in a shared user-level cache, so they are never per-worktree.
# This does exactly one thing Playwright cannot do for itself: delete a
# directory that LIES. An interrupted `playwright install` leaves an empty
# browser directory next to an INSTALLATION_COMPLETE marker, and that marker
# makes every later install a silent no-op — so the missing binary is never
# repaired and surfaces as "browserType.launch: Executable doesn't exist".
# Trust the binary, not the marker.
#
# Deciding whether anything then needs installing is NOT this script's job:
# a browser that is entirely absent leaves no directory to inspect, so any
# such check silently passes a cache that cannot launch (observed during
# #556 — an intact chromium-1217 while chromium_headless_shell-1217 was
# simply missing). Playwright knows which browsers it needs; it always gets
# to check, and is a fast no-op when they are all present.

if [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ]; then
    BROWSER_CACHE="$PLAYWRIGHT_BROWSERS_PATH"
elif [ "$(uname -s)" = "Darwin" ]; then
    BROWSER_CACHE="$HOME/Library/Caches/ms-playwright"
else
    BROWSER_CACHE="$HOME/.cache/ms-playwright"
fi

if [ -d "$BROWSER_CACHE" ]; then
    # Only look at actual browser install directories (named e.g.
    # "chromium-1217" or "chromium_headless_shell-1217"). The cache also
    # holds Playwright-internal bookkeeping directories such as `__dirlock`
    # (its own install lock) and `.links` — those aren't browsers, have no
    # executable inside, and must never be treated as a stale install: doing
    # so removes Playwright's own lock file mid-use and crashes the very
    # `playwright install` this script goes on to run.
    for browser_dir in "$BROWSER_CACHE"/*-[0-9]*/; do
        [ -d "$browser_dir" ] || continue
        if [ -z "$(find "$browser_dir" -type f -perm -u+x -print -quit)" ]; then
            echo "🌐 Stale browser install (no executable): $browser_dir — removing"
            rm -rf "$browser_dir"
        fi
    done
fi

# The install is bounded because it can hang indefinitely: observed twice while
# working #556 (once for 9h24m), the downloader finishes fetching the ~173MB
# zip and then stops making progress, holding the file open and burning no CPU.
# That hang is what produces the corrupt directory this script has to repair, so
# waiting it out is never the right move — and an unbounded wait here would hang
# worktree setup itself. Fail loudly with the recovery instead.
INSTALL_TIMEOUT="${WORKTREE_SETUP_INSTALL_TIMEOUT:-300}"

echo "🌐 Verifying Playwright browsers (downloads only what is missing)"
# `set -m` puts the install in its own process group, so the timeout below can
# kill the whole tree. Killing just the direct child leaves npx's grandchildren
# (node, the downloader) alive, still holding this script's stdout open.
set -m
(cd e2e && npx playwright install chromium) &
install_pid=$!
set +m

waited=0
while kill -0 "$install_pid" 2>/dev/null; do
    if [ "$waited" -ge "$INSTALL_TIMEOUT" ]; then
        kill -9 -- "-$install_pid" 2>/dev/null || kill -9 "$install_pid" 2>/dev/null || true
        echo "" >&2
        echo "❌ playwright install made no progress within ${INSTALL_TIMEOUT}s — killed." >&2
        echo "   It usually finishes in 1-3 minutes. A hung install leaves a partial" >&2
        echo "   browser directory behind, so clear it and retry:" >&2
        echo "" >&2
        echo "     rm -rf \"$BROWSER_CACHE\"/chromium*" >&2
        echo "     cd e2e && npx playwright install chromium" >&2
        echo "" >&2
        echo "   Dependency sharing above completed — only the browsers are missing." >&2
        exit 1
    fi
    sleep 1
    waited=$((waited + 1))
done

wait "$install_pid"

echo "✅ Worktree ready"
