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
# Two exceptions never get auto-allowed:
#
#   1. Globally-scoped actions (sudo, podman machine rm, gh release, ...) --
#      matched at command-word position, not as a bare substring, so that
#      `grep "sudo " docs/` is not mistaken for running sudo.
#   2. Commands that can reach OUTSIDE the worktree. Those are put through
#      a stricter check (see needs_scrutiny / escapes_worktree below).
#
# THREAT MODEL: accidents, not an adversary. The damage this prevents is a
# stale absolute path left over from before a worktree switch, or a `../..`
# counted from the wrong cwd -- the Bash-side counterpart of what
# check-worktree-path.sh blocks for Edit/Write. A command that deliberately
# hides its target behind an unexpanded variable, an alias, or a here-doc
# can still get through: a hook sees the command STRING, not the syscalls
# it will make. Do not treat this as a sandbox. The real containment is
# that a worktree is disposable; this guard only keeps ordinary mistakes
# from reaching the shared checkout.
set -euo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

if [ -z "$command" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Anchored at command-word position: start of string, or after a shell
# separator (; & | && || newline). A bare substring match would treat
# `grep "sudo " docs/` as running sudo and reintroduce the prompt.
CMD_START='(^|[;&|(]|&&|\|\||\n)[[:space:]]*'

# --- Globally-scoped actions -------------------------------------------
#
# Effects that no worktree can contain: elevated privileges, the shared
# podman VM every worktree's E2E stack runs on, a GitHub mutation, or a
# push that moves a shared ref.
#
# These get an explicit "ask" rather than a fall-through. Falling through
# would be wrong in both directions: settings.json ALLOWS `Bash(git push *)`,
# so a shared-ref push would sail through unprompted, while `podman machine
# rm` would hit a deny it can no longer reach once any allow is in play.
is_globally_scoped() {
  printf '%s' "$1" | grep -qE "${CMD_START}sudo[[:space:]]" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}podman[[:space:]]+(machine[[:space:]]+(rm|reset)|system[[:space:]]+reset)" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}gh[[:space:]]+(pr[[:space:]]+merge|release|repo[[:space:]]+(delete|archive))" && return 0
  # Any push that can move a shared ref: main/beta branches, tags, --all,
  # --mirror. NOTE these must be an explicit deny, not a fall-through --
  # settings.json allow-lists `Bash(git push *)`, so falling through would
  # allow them outright rather than prompt.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+push([[:space:]]|$).*([[:space:]](main|beta)([[:space:]]|$)|--all|--mirror|--tags|[[:space:]]v[0-9])" && return 0
  return 1
}

session_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$session_root" ]; then
  echo '{"continue": true}'
  exit 0
fi

# First entry of `git worktree list --porcelain` is always the main
# worktree (the original clone); every other entry is a linked worktree.
# (Capture to a variable before awk -- piping directly into `awk 'exit'`
# can SIGPIPE the git process under `set -o pipefail`.)
# Strip the "worktree " prefix rather than taking $2 -- awk's $2 truncates
# at the first space, so a checkout path containing a space would yield a
# short main_root, the "am I the main checkout?" test below would wrongly
# say no, and the hook would auto-allow everything IN THE MAIN CHECKOUT.
worktree_list=$(git worktree list --porcelain)
main_root=$(printf '%s\n' "$worktree_list" | awk '/^worktree /{sub(/^worktree /, ""); print; exit}')

# Everything below applies ONLY inside a linked worktree. In the main
# checkout the hook stays completely silent, so that shared checkout keeps
# every ask/deny rule in settings.json exactly as configured.
if [ -z "$main_root" ] || [ "$session_root" = "$main_root" ]; then
  echo '{"continue": true}'
  exit 0
fi

if is_globally_scoped "$command"; then
  reason="Not auto-allowed: this command's effect is global (elevated privileges, the shared podman VM, a GitHub mutation, or a shared git ref), so being inside a disposable worktree does not contain it. Confirm it explicitly."
  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
fi

# --- Containment check --------------------------------------------------
#
# Only commands that can actually write outside the worktree are scrutinized.
# Read-only and build commands (pytest, npm ci, ruff, git status) skip this
# entirely, which is what keeps the autonomy this hook exists to provide.
#
# `git` is scrutinized only when given an explicit repo redirect (-C,
# --git-dir, --work-tree) -- without one it operates on the cwd's repo,
# which is this worktree by definition.
needs_scrutiny() {
  printf '%s' "$1" | grep -qE "${CMD_START}(rm|mv|cp|ln|dd|tee|shred|install|truncate|chmod|chown|rsync|find|xargs)([[:space:]]|$)" && return 0
  printf '%s' "$1" | grep -qE "(^|[[:space:]])(-C|--git-dir|--work-tree)([[:space:]]|=)" && return 0
  printf '%s' "$1" | grep -qE '>[[:space:]]*/' && return 0
  return 1
}

# A scrutinized command must be transparently contained. Anything that hides
# its target -- `..`, `~`, a variable, a command substitution -- cannot be
# resolved from the command string, so it is not auto-allowed. These are
# rare in generated commands and common in the accidents we care about
# (`rm -rf ../../..`, `$HOME/GitHub/bess-manager`).
escapes_worktree() {
  local cmd="$1"

  # Unresolvable indirection.
  # `/` must be in the leading class too: without it, `/tmp/../Users/...`
  # traverses out THROUGH an allowed temp prefix and passes the check below.
  printf '%s' "$cmd" | grep -qE '(^|[[:space:]"'\''=:/])\.\.(/|[[:space:]]|$)' && return 0
  printf '%s' "$cmd" | grep -qE '(^|[[:space:]"'\''=:])~' && return 0
  printf '%s' "$cmd" | grep -qE '[$`]' && return 0

  # Absolute paths must resolve under the worktree (or a disposable temp
  # area). Quotes are stripped first -- a leading `"` used to make the token
  # not start with `/`, which silently skipped the whole check.
  # Word-split deliberately, but with globbing off: an unquoted `*` in the
  # command would otherwise be pathname-expanded against the hook's own cwd
  # before we ever inspect it.
  local token stripped
  set -f
  for token in $cmd; do
    stripped=$(printf '%s' "$token" | tr -d "\"'")
    case "$stripped" in
      /*)
        case "$stripped" in
          "$session_root" | "$session_root"/*) ;;
          /tmp/* | /private/tmp/* | /private/var/folders/* | /dev/null) ;;
          *) set +f; return 0 ;;
        esac
        ;;
    esac
  done
  set +f

  return 1
}

if needs_scrutiny "$command" && escapes_worktree "$command"; then
  reason="Not auto-allowed: this command can write outside '${session_root}' -- it names an absolute path beyond the worktree, or hides its target behind '..', '~', a variable, or a command substitution. This is the Bash-side counterpart of the cross-checkout path confusion check-worktree-path.sh blocks for Edit/Write. Re-derive the path from \`pwd\` if that was unintended."
  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
fi

reason="Auto-allowed: cwd '${session_root}' is a linked git worktree (main checkout is '${main_root}'). A worktree is disposable, so commands scoped to it need no confirmation per CLAUDE.md's Worktree Conventions. Commands whose blast radius leaves the worktree are excluded and still prompt."
jq -n --arg reason "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "allow",
    permissionDecisionReason: $reason
  }
}'
