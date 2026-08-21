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
#
# What sharing costs: .venv and (when the lockfiles agree) node_modules are
# symlinks into the main checkout, so they are READ-shared but not write-isolated.
# Anything that installs — `npm install`, `pip install` — resolves through the
# link and mutates the main checkout's tree, changing dependencies underneath
# every other worktree at once. Read-only use (pytest, npm run build, playwright)
# is safe; when a branch genuinely needs its own dependency set, give it a real
# install rather than writing through the link:
#
#     rm .venv && python -m venv .venv && .venv/bin/pip install -r requirements.txt
#     rm frontend/node_modules && (cd frontend && npm install)
#
# For node this is also automatic: change `package-lock.json`, re-run this
# script, and the diverged package root gets its own install. There is no such
# check for .venv — requirements.txt drift is on you to notice.

set -euo pipefail

# --target-dir/--main-checkout exist for scripts/run-agent.sh, which sets up an
# agent's private CLONE rather than a linked worktree. A clone is a fully
# independent repository, so the derivation below cannot find the main checkout
# from it -- there is no git-common-dir pointing back. Given explicitly, the
# rest of this script is identical: it only ever needed "which tree am I
# setting up" and "which tree do I share from".
TARGET_DIR=""
MAIN_CHECKOUT_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --target-dir)     TARGET_DIR="${2:?--target-dir requires a path}"; shift 2 ;;
        --main-checkout)  MAIN_CHECKOUT_ARG="${2:?--main-checkout requires a path}"; shift 2 ;;
        *) echo "❌ worktree-setup.sh: unknown argument '$1'" >&2; exit 2 ;;
    esac
done

if [ -n "$TARGET_DIR" ]; then
    if [ -z "$MAIN_CHECKOUT_ARG" ]; then
        echo "❌ --target-dir requires --main-checkout (an independent clone cannot derive it)." >&2
        exit 2
    fi
    WORKTREE_ROOT=$(cd "$TARGET_DIR" && pwd -P)
    MAIN_CHECKOUT=$(cd "$MAIN_CHECKOUT_ARG" && pwd -P)
else
    WORKTREE_ROOT=$(git rev-parse --show-toplevel)
    GIT_DIR=$(cd "$(git rev-parse --git-dir)" && pwd -P)
    GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)

    if [ "$GIT_DIR" = "$GIT_COMMON" ]; then
        echo "❌ Not in a linked worktree — run this from a worktree, not the main checkout." >&2
        echo "   (For an agent's private clone use --target-dir/--main-checkout.)" >&2
        exit 1
    fi

    MAIN_CHECKOUT=$(dirname "$GIT_COMMON")
fi

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

# True when a package root's installed tree was built from the lockfile beside
# it. npm records what it actually installed in node_modules/.package-lock.json,
# using the same {path: {version}} shape as package-lock.json, so comparing the
# two answers "is this install current?" without running npm (which costs a
# second per package and fails for unrelated reasons like extraneous packages).
# Unknown -> true: if either file is missing or unparseable this cannot show
# staleness, and answering false there would force a full install on every
# worktree for no evidence.
install_matches_lockfile() {
    python3 - "$1" <<'PY'
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
try:
    want = json.loads((root / "package-lock.json").read_text())["packages"]
    have = json.loads((root / "node_modules" / ".package-lock.json").read_text())["packages"]
except Exception:
    sys.exit(0)

for path, spec in want.items():
    if not path.startswith("node_modules/") or "version" not in spec:
        continue
    # Optional deps are absent from a perfectly current install by design --
    # npm skips the ones whose os/cpu do not apply, and records nothing for
    # them. Treating that as staleness made a freshly `npm install`ed e2e tree
    # report STALE over `fsevents` alone, which would send every worktree
    # through a full install: the exact cost this sharing exists to avoid.
    if spec.get("optional"):
        continue
    if have.get(path, {}).get("version") != spec["version"]:
        sys.exit(1)
sys.exit(0)
PY
}

for pkg in frontend e2e; do
    [ -d "$pkg" ] || continue

    if [ -L "$pkg/node_modules" ] && [ ! -e "$pkg/node_modules" ]; then
        echo "   $pkg/node_modules is a broken symlink — removing"
        rm "$pkg/node_modules"
    fi

    # Two conditions, and the second is easy to miss. Comparing the two
    # LOCKFILES only answers "do these checkouts want the same dependencies" —
    # it says nothing about whether the tree we are about to share was ever
    # installed from the lockfile sitting next to it. A dependency bump merged
    # into main leaves exactly that state: main's package-lock.json is updated
    # by the merge, its node_modules is NOT (nothing re-installs on checkout).
    # Every new worktree then finds the lockfiles identical, shares a tree
    # built from the OLD lockfile, and runs against the previous versions while
    # this script reports success. That is not hypothetical — it is how the
    # Playwright bump would have silently reintroduced the install hang it was
    # merged to fix. So also require main's install to match main's lockfile.
    if [ -d "$MAIN_CHECKOUT/$pkg/node_modules" ] &&
        cmp -s "$pkg/package-lock.json" "$MAIN_CHECKOUT/$pkg/package-lock.json" &&
        install_matches_lockfile "$MAIN_CHECKOUT/$pkg"; then
        lockfiles_agree=true
    else
        lockfiles_agree=false
    fi

    if [ -L "$pkg/node_modules" ]; then
        # An existing share has to be re-checked, not trusted: the lockfiles
        # agreed when it was made, but this branch has since had every chance
        # to change dependencies or merge main. Skipping the check here is how
        # a worktree keeps testing against a tree that no longer matches it,
        # while re-running this script reports success.
        if [ "$lockfiles_agree" = true ]; then
            echo "   $pkg/node_modules already shared"
            continue
        fi
        echo "   $pkg/node_modules is shared but the lockfile has since diverged"
        echo "   from the main checkout — replacing the link with a real install"
        rm "$pkg/node_modules"
    elif [ -e "$pkg/node_modules" ]; then
        # A real directory is this worktree's own install — leave it alone.
        echo "   $pkg/node_modules already present"
        continue
    fi

    if [ "$lockfiles_agree" = true ]; then
        ln -s "$MAIN_CHECKOUT/$pkg/node_modules" "$pkg/node_modules"
        echo "   $pkg/node_modules → $MAIN_CHECKOUT/$pkg/node_modules"
    else
        echo "   $pkg: lockfile differs from the main checkout (or it has no"
        echo "   node_modules) — installing into this worktree instead of sharing"
        # npm's own EPERM message is a guess, not a diagnosis: a sandbox-blocked
        # ~/.npm/_cacache is reported as "Your cache folder contains root-owned
        # files ... please run: sudo chown -R", which sends you to `sudo` (on the
        # ask list) to fix files that are not root-owned. Say what it actually is.
        if ! (cd "$pkg" && npm install); then
            echo "" >&2
            echo "❌ npm install failed in $pkg." >&2
            echo "   If it blamed root-owned files and told you to run sudo chown," >&2
            echo "   IGNORE that — it is npm mis-reporting EPERM. Check the sandbox:" >&2
            echo "" >&2
            echo "     mkdir ~/.npm/_cacache/.probe   # 'Operation not permitted' = sandbox" >&2
            echo "" >&2
            echo "   ~/.npm belongs in sandbox.filesystem.allowWrite; only" >&2
            echo "   ~/.npm/_logs is granted by default. See scripts/verify-sandbox.sh." >&2
            exit 1
        fi
    fi
done

# --- Playwright browsers -----------------------------------------------------
#
# Everything below needs e2e/, both to run the install from and to be worth
# doing at all. Without that guard the subshell below fails under `set -e` with
# no diagnostic, immediately after reporting that all the sharing succeeded.
if [ ! -d e2e ]; then
    echo "✅ Worktree ready (no e2e/ — skipped Playwright browsers)"
    exit 0
fi

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
        echo "   If that retry ALSO makes no progress, check the sandbox before" >&2
        echo "   blaming the network. The browser cache lives outside every repo" >&2
        echo "   path sandbox.filesystem.allowWrite grants, and a blocked cache" >&2
        echo "   is indistinguishable from a slow download at this layer:" >&2
        echo "" >&2
        echo "     mkdir \"$BROWSER_CACHE/.probe\"   # 'Operation not permitted' = sandbox" >&2
        echo "" >&2
        echo "   See docs/agents/local-agent-environment.md 'Why each non-default" >&2
        echo "   knob is there', and confirm" >&2
        echo "   with scripts/verify-sandbox.sh in a FRESH session." >&2
        echo "" >&2
        echo "   Dependency sharing above completed — only the browsers are missing." >&2
        exit 1
    fi
    sleep 1
    waited=$((waited + 1))
done

wait "$install_pid"

echo "✅ Worktree ready"
