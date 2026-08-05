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

echo '{"continue": true}'
