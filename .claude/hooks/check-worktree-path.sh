#!/usr/bin/env bash
# PreToolUse hook for Edit/Write/NotebookEdit.
#
# Blocks a file-write tool call whose target path resolves to a DIFFERENT
# git checkout (main repo vs. a .claude/worktrees/* worktree vs. a sibling
# worktree) than the one the session's shell is currently running in.
#
# Why this exists: multiple sessions work in different worktrees of this
# repo concurrently. An absolute path copied from before a worktree switch
# (or typed from habit) silently edits the WRONG checkout -- most often the
# shared main repo checkout, on whatever branch happens to be checked out
# there. This has caused real, repeated damage (edits landing on unrelated
# branches, getting reverted, work having to be redone) and is NOT reliably
# prevented by instructions/memory alone -- only a hook can inspect every
# tool call before it executes. See docs/agents/rules.md "Working Location"
# and the feedback_worktree_before_any_edit memory (multiple recurrences).
set -euo pipefail

input=$(cat)
target_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')

if [ -z "$target_path" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Resolve against the parent directory so a not-yet-created file still
# resolves to the right checkout.
if [ -e "$target_path" ] && [ -d "$target_path" ]; then
  check_dir="$target_path"
else
  check_dir=$(dirname -- "$target_path")
fi

target_root=$(git -C "$check_dir" rev-parse --show-toplevel 2>/dev/null || true)
session_root=$(git rev-parse --show-toplevel 2>/dev/null || true)

# Not applicable outside git (either side), or comparison indeterminate.
if [ -z "$target_root" ] || [ -z "$session_root" ]; then
  echo '{"continue": true}'
  exit 0
fi

if [ "$target_root" != "$session_root" ]; then
  reason="BLOCKED: target path '${target_path}' resolves to git checkout '${target_root}', but this session's shell is currently in a DIFFERENT checkout: '${session_root}'. This is the cross-worktree path-confusion bug -- re-derive the path from \`pwd\` (it must start with '${session_root}') before retrying. Do not force this through; verify the path prefix."
  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
fi

# ---------------------------------------------------------------------------
# Second check: is this session in a worktree at all?
#
# CLAUDE.md's rule is unconditional -- "Never edit any file on main, even a
# one-line doc fix" -- and it is prose, so it has to be REMEMBERED at the moment
# of the first edit. That is precisely when it isn't: a session that opens as a
# question ("why does X happen?") and drifts into implementing never re-evaluates
# a rule it had no reason to consider at the start. Six live sessions currently
# sit in the main checkout for exactly that legitimate read-only reason.
#
# The cost is not hypothetical. PR #619's branch carries a merge of itself --
# `Merge remote-tracking branch 'origin/fix/...' into fix/...` -- because two
# writers worked the same branch from different bases and diverged for fifteen
# hours. The reviewer reviewed one line three times while the other line, based
# on a commit from 08:09, never saw a single verdict.
#
# So the check is mechanical and fires at the transition itself: the first
# Edit/Write IS the moment a question becomes an implementation. A linked
# worktree has its own git dir under the main one, so `--git-dir` and
# `--git-common-dir` differ there and are identical in the main checkout. That
# is a path comparison, the only shape docs/agents/rules.md sanctions for this
# hook -- it never has to guess what a command string will touch.
#
# Sibling checkouts (`../bess-manager-feature/`) are linked worktrees too, so
# they pass: this enforces "work in a worktree", not "work under .claude/".
git_dir=$(git rev-parse --absolute-git-dir 2>/dev/null || true)
common_dir=$(cd "$(git rev-parse --git-common-dir 2>/dev/null || echo .)" 2>/dev/null && pwd || true)

if [ -n "$git_dir" ] && [ -n "$common_dir" ] && [ "$git_dir" = "$common_dir" ]; then
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
  reason="BLOCKED: this session is in the MAIN checkout ('${session_root}', branch '${branch}'), not a worktree, so editing '${target_path}' would write straight into the shared checkout. CLAUDE.md: work in a worktree before ANY edit -- unconditional, including a one-line doc fix. If this session started as a question and has become implementation work, that is the common path here and this is the moment to switch: call EnterWorktree (never \`git worktree add\`, which the sandbox denies), then redo the edit there. The main checkout stays read-only: questions, \`gh\`, the backlog, and dispatch all work fine from it."
  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
fi

echo '{"continue": true}'
