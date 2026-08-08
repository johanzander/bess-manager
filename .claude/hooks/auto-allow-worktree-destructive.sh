#!/usr/bin/env bash
# PreToolUse hook for Bash.
#
# Several destructive-looking commands (rm -rf, git reset --hard, git
# rebase, git merge, git push --force) are in settings.json's "ask" list
# because they're dangerous in the SHARED main checkout. But agents doing
# feature work almost always run them inside a disposable git worktree
# (.claude/worktrees/* or a sibling worktree per CLAUDE.md's Worktree
# Conventions), where blast radius is contained to that one checkout and
# there is nothing to protect -- the whole point of a worktree is that it
# can be blown away and recreated. Prompting there just stalls otherwise
# autonomous work (e.g. implement-issue rebuilding a venv).
#
# This hook auto-allows those specific command shapes when the session's
# cwd resolves to a LINKED worktree, and falls through (no decision) so
# the normal ask/deny rules in settings.json apply everywhere else,
# including the main checkout.
set -euo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

if [ -z "$command" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Only consider commands that would otherwise hit an "ask" rule.
case "$command" in
  *"rm -r "*|*"rm -R "*|*"rm -rf "*|*"rm -Rf "*|*"rm -fr "*|*"rm -fR "*|*"rm --recursive"*) ;;
  *"git reset --hard"*) ;;
  *"git rebase"*) ;;
  *"git merge"*) ;;
  *"git push --force"*|*"git push -f "*|*"git push -f")  ;;
  *) echo '{"continue": true}'; exit 0 ;;
esac

session_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$session_root" ]; then
  echo '{"continue": true}'
  exit 0
fi

# First entry of `git worktree list --porcelain` is always the main
# worktree (the original clone); every other entry is a linked worktree.
# (Capture to a variable before awk -- piping directly into `awk 'exit'`
# can SIGPIPE the git process under `set -o pipefail`.)
worktree_list=$(git worktree list --porcelain)
main_root=$(printf '%s\n' "$worktree_list" | awk '/^worktree /{print $2; exit}')

if [ -n "$main_root" ] && [ "$session_root" != "$main_root" ]; then
  reason="Auto-allowed: cwd '${session_root}' is a linked git worktree (main checkout is '${main_root}'), so this destructive command is scoped to a disposable checkout per CLAUDE.md's Worktree Conventions."
  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
fi

echo '{"continue": true}'
