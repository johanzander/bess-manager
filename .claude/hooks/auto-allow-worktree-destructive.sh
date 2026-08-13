#!/usr/bin/env bash
# PreToolUse hook for Bash.
#
# The worktree IS the safety boundary. A linked git worktree
# (.claude/worktrees/* or a sibling per CLAUDE.md's Worktree Conventions)
# is disposable by construction: it can be blown away and recreated, and
# nothing in it is shared with the main checkout or with another agent.
# Inside one, a permission prompt protects nothing -- it just stalls
# otherwise autonomous work (implement-issue rebuilding a venv, pruning a
# scenario fixture, merging origin/main before a PR).
#
# So this hook AUTO-ALLOWS Bash commands when the session's cwd resolves to
# a linked worktree, and falls through (no decision) everywhere else, so
# the normal ask/deny rules in settings.json still guard the shared main
# checkout.
#
# It deliberately does NOT enumerate destructive command shapes. The
# previous version did -- an allowlist of `rm -rf`, `git reset --hard`,
# `git rebase`, `git merge`, `git push --force` -- and the enumeration was
# the bug: a plain `rm -f <file>` fell through to `ask: Bash(rm *)` and
# prompted, and every new command shape needed another entry. Inverting it
# removes that whole class of stall.
#
# The escape list below is the exception: commands whose blast radius
# LEAVES the worktree are never auto-allowed, no matter where they run.
# Keep it narrow and justified -- everything added here reintroduces a
# prompt inside worktrees.
set -euo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

if [ -z "$command" ]; then
  echo '{"continue": true}'
  exit 0
fi

# --- Escape list: blast radius outside this worktree -----------------
#
# These must keep hitting the normal permission rules (including the deny
# entries in settings.json). A PreToolUse "allow" decision bypasses the
# permission system entirely, so anything matched here that we allowed
# would render those deny rules dead.
#
#   podman machine rm / system reset -> destroys the shared podman VM that
#     every worktree's E2E stack runs on (settings.json denies these).
#   gh pr merge / gh release / gh repo -> mutates GitHub, not the checkout.
#   git push to a non-feature ref     -> touches a shared remote branch.
#   sudo                              -> escapes the user account entirely.
#   rm/mv targeting an absolute path outside the worktree root.
is_escaped() {
  case "$1" in
    *"sudo "*) return 0 ;;
    *"podman machine rm"*|*"podman system reset"*|*"podman machine reset"*) return 0 ;;
    *"gh pr merge"*|*"gh release"*|*"gh repo delete"*|*"gh repo archive"*) return 0 ;;
    *"git push"*"main"*|*"git push"*"beta"*) return 0 ;;
  esac
  return 1
}

if is_escaped "$command"; then
  echo '{"continue": true}'
  exit 0
fi

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

if [ -z "$main_root" ] || [ "$session_root" = "$main_root" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Destructive verbs aimed at an absolute path outside this worktree are the
# one in-worktree shape that can still damage something shared -- a stale
# absolute path from before a worktree switch is exactly the cross-checkout
# confusion that check-worktree-path.sh guards for Edit/Write.
case "$command" in
  *"rm "*|*"mv "*|*"chmod "*|*"chown "*|*"truncate "*)
    for token in $command; do
      case "$token" in
        /*)
          case "$token" in
            "$session_root"/*|"$session_root") ;;
            /private/tmp/claude-*|/tmp/*|/private/var/folders/*) ;;
            *)
              echo '{"continue": true}'
              exit 0
              ;;
          esac
          ;;
      esac
    done
    ;;
esac

reason="Auto-allowed: cwd '${session_root}' is a linked git worktree (main checkout is '${main_root}'). A worktree is disposable, so commands scoped to it need no confirmation per CLAUDE.md's Worktree Conventions. Commands whose blast radius leaves the worktree are excluded and still prompt."
jq -n --arg reason "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "allow",
    permissionDecisionReason: $reason
  }
}'
