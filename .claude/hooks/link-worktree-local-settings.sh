#!/usr/bin/env bash
# SessionStart hook.
#
# `.claude/settings.local.json` is gitignored (globally, via
# `**/.claude/settings.local.json`), so it exists ONLY in the main checkout.
# `.claude/settings.json` and everything under `.claude/hooks/` are tracked
# and travel into a worktree for free -- local settings do not.
#
# The asymmetry is silent and it bites hard: the moment a session enters a
# worktree it loses every permission rule and mode set in local settings,
# while the tracked `ask:` list keeps applying. A run that was fully
# autonomous in the main checkout starts prompting inside the worktree, for
# rules the user thought they had already relaxed.
#
# This symlinks the main checkout's local settings into every linked
# worktree that lacks them. A symlink (not a copy) so later edits in the
# main checkout apply everywhere without re-running anything.
#
# It sweeps all linked worktrees rather than trusting a payload field for
# "the worktree that was just created": the sweep is idempotent, needs no
# assumption about the hook's stdin shape, and self-heals worktrees that
# predate this hook.
#
# Registered on SessionStart ONLY, and deliberately not on WorktreeCreate.
# WorktreeCreate looked like the better event -- it fires before the session
# enters, so the link would be in place when settings load -- but that event
# expects the hook to RETURN the worktree path on stdout, and a hook that
# prints nothing breaks worktree creation outright: EnterWorktree fails with
# "hook succeeded but returned no worktree path". A sweeping hook has no such
# path to return.
#
# SessionStart also covers the case WorktreeCreate never did: `git worktree
# add`, the fallback path in superpowers:using-git-worktrees, fires no
# WorktreeCreate at all. Settings are already loaded by the time SessionStart
# runs, so a new worktree picks its link up on its NEXT session; the
# fleet-wide sweep is what makes that self-correcting rather than permanent.
#
# Scope note: .venv and frontend/node_modules have the same
# doesn't-travel problem, but they are scripts/worktree-setup.sh's job
# (issue #556). This hook stays limited to the permissions concern.
set -euo pipefail

# Drain stdin so the caller never sees EPIPE; the payload is not needed.
cat >/dev/null 2>&1 || true

worktree_list=$(git worktree list --porcelain 2>/dev/null || true)
if [ -z "$worktree_list" ]; then
  exit 0
fi

# Strip the prefix rather than taking $2 -- awk's $2 truncates at the first
# space, so a checkout path containing one would yield a short root and be
# silently skipped.
roots=$(printf '%s\n' "$worktree_list" | awk '/^worktree /{sub(/^worktree /, ""); print}')
main_root=$(printf '%s\n' "$roots" | head -n 1)
source_file="${main_root}/.claude/settings.local.json"

if [ ! -f "$source_file" ]; then
  exit 0
fi

printf '%s\n' "$roots" | tail -n +2 | while IFS= read -r root; do
  [ -n "$root" ] || continue
  [ -d "$root/.claude" ] || continue
  target="$root/.claude/settings.local.json"

  # Leave a real file alone -- a worktree may intentionally carry its own.
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    continue
  fi
  # Already pointing where we want.
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source_file" ]; then
    continue
  fi

  # Never let one unwritable or racing worktree abort the sweep: under
  # `set -e` a single ln failure would kill the script before `exit 0`, and
  # as a SessionStart hook that surfaces an error on every new session.
  ln -sfn "$source_file" "$target" 2>/dev/null || true
done

exit 0
