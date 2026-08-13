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
# Every check below therefore fails CLOSED: where a pattern list is
# unavoidable it enumerates what is SAFE, so a shape nobody thought of
# costs one prompt rather than a silent auto-allow.
#
# Three exceptions never get auto-allowed:
#
#   1. Globally-scoped actions (sudo, the shared podman VM, anything
#      touching GitHub, a push that can move a shared ref) -- matched at
#      command-word position, not as a bare substring, so that
#      `grep "sudo " docs/` is not mistaken for running sudo.
#   2. Mutations of state SHARED with the main checkout. A linked worktree
#      has its own working tree but ONE object database and ONE ref
#      namespace with every other checkout (see mutates_shared_state).
#   3. Commands that can reach OUTSIDE the worktree. Those are put through
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

# --- Hard denials -------------------------------------------------------
#
# `podman machine rm` / `podman system reset` are `deny` entries in
# settings.json -- a hard block on destroying the shared podman VM every
# worktree's E2E stack runs on. A hook decision SUPERSEDES a settings rule,
# so answering "ask" here would quietly downgrade that block to a single
# keystroke. Re-emit the deny instead of weakening it.
is_hard_denied() {
  printf '%s' "$1" | grep -qE "${CMD_START}podman[[:space:]]+(machine[[:space:]]+(rm|reset)|system[[:space:]]+reset)"
}

# --- Globally-scoped actions -------------------------------------------
#
# Effects that no worktree can contain: elevated privileges, anything that
# reaches GitHub, or a push that can move a shared ref.
#
# These get an explicit "ask" rather than a fall-through, because
# settings.json ALLOWS `Bash(git push *)` and `Bash(gh *)` -- falling
# through would let them run unprompted rather than prompt.
is_globally_scoped() {
  printf '%s' "$1" | grep -qE "${CMD_START}sudo[[:space:]]" && return 0

  # `gh` reaches GitHub, which no worktree contains. Enumerating destructive
  # subcommands fails the wrong way: `gh api -X DELETE repos/...` is the
  # general form of every entry such a list could hold, and `gh workflow
  # run` / `gh secret set` / `gh repo edit` are not obviously "destructive"
  # names. So invert -- every `gh` asks unless it is a read-only query.
  # Counting both forms catches a compound `gh pr view && gh pr merge`,
  # where matching only the first invocation would clear the whole command.
  local gh_all gh_readonly
  # `grep -c` counts LINES, and a command is normally one line, so both
  # counts would be 1 for that compound. Count occurrences with -o | wc -l.
  gh_all=$(printf '%s' "$1" | grep -oE "${CMD_START}gh[[:space:]]" | wc -l | tr -d ' ' || true)
  gh_readonly=$(printf '%s' "$1" | grep -oE "${CMD_START}gh[[:space:]]+(pr[[:space:]]+(view|list|diff|checks|status)|issue[[:space:]]+(view|list)|run[[:space:]]+(view|list|watch)|release[[:space:]]+(view|list)|repo[[:space:]]+view|workflow[[:space:]]+(view|list)|label[[:space:]]+list|search|auth[[:space:]]+status)([[:space:]]|$)" | wc -l | tr -d ' ' || true)
  [ "$gh_all" -ne "$gh_readonly" ] && return 0

  # Any push that can move a shared ref. The ref has to be matched in every
  # refspec form -- `main`, `HEAD:main`, `br:refs/heads/main`, `+main` --
  # not just as a bare word, since the bare word is the spelling least
  # likely to appear when something force-updates a ref. Force pushes ask
  # unconditionally: settings.json already asks for them, and this hook's
  # explicit allow would otherwise override that.
  if printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+push([[:space:]]|$)"; then
    printf '%s' "$1" | grep -qE "(--force|--force-with-lease|[[:space:]]-f([[:space:]]|$)|--all|--mirror|--tags)" && return 0
    printf '%s' "$1" | grep -qE "(^|[[:space:]:+])(refs/heads/)?(main|beta)([[:space:]]|:|$)" && return 0
    printf '%s' "$1" | grep -qE "(^|[[:space:]:+])(refs/tags/)?v[0-9]" && return 0
  fi
  return 1
}

# --- Shared repository state --------------------------------------------
#
# A linked worktree has its own working tree, but shares ONE object
# database and ONE ref namespace with the main checkout and every other
# worktree. So these reach far outside the worktree even without `-C`:
# deleting a branch another agent is on, expiring the reflog that would
# have recovered it, or removing another agent's checkout outright.
mutates_shared_state() {
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+(branch|tag)[[:space:]]+(.*[[:space:]])?(-D|-d|--delete)([[:space:]]|$)" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+(gc|prune|reflog[[:space:]]+expire|update-ref[[:space:]]+-d|filter-branch)([[:space:]]|$)" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+worktree[[:space:]]+(remove|prune)([[:space:]]|$)" && return 0
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

if is_hard_denied "$command"; then
  reason="Denied: this destroys the shared podman VM every worktree's E2E stack runs on. settings.json denies it outright; a worktree does not make it recoverable, and this hook must not downgrade that block to a prompt."
  jq -n --arg reason "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
fi

if is_globally_scoped "$command" || mutates_shared_state "$command"; then
  reason="Not auto-allowed: this command's effect reaches outside the worktree -- elevated privileges, GitHub, a shared git ref, or the object database and ref namespace this worktree shares with the main checkout. Being inside a disposable worktree does not contain it. Confirm it explicitly."
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
# Purely relative, purely in-tree commands (pytest, npm ci, ruff, git status)
# skip this entirely, which is what keeps the autonomy this hook exists to
# provide.
#
# The trigger is deliberately NOT a list of writing verbs. That list is the
# same enumeration bug as before, only inverted: on this side a miss is a
# silent auto-allow, not an extra prompt, and the misses were the commonest
# in-place writers there are -- `sed -i` into the main checkout, `touch`,
# `mkdir -p`, `python3 -c "shutil.rmtree(...)"`. Trigger instead on the
# thing that actually makes a command dangerous here: naming a path that
# could sit outside the worktree. escapes_worktree then decides.
#
# The verb list survives only for the indirection case -- `rm -rf $HOME/x`
# names no literal path but still resolves to one.
needs_scrutiny() {
  # Any absolute path, any `..` traversal, any `~`.
  printf '%s' "$1" | grep -qE '(^|[[:space:]"'\''=:(])(/|~|\.\.(/|[[:space:]]|$))' && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}(rm|mv|cp|ln|dd|tee|shred|install|truncate|chmod|chown|rsync|find|xargs|sed|touch|mkdir)([[:space:]]|$)" && return 0
  printf '%s' "$1" | grep -qE "(^|[[:space:]])(-C|--git-dir|--work-tree)([[:space:]]|=)" && return 0
  # Any redirect, not just one to an absolute path: `> ../../repo/README.md`
  # leaves the worktree just as surely, and is the likelier accident.
  printf '%s' "$1" | grep -qE '>' && return 0
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

  # A variable or substitution is "unresolvable" only when it could actually
  # BE a path. Rejecting every `$` and backtick was far too blunt once
  # needs_scrutiny started firing on any redirect: `git show X 2>/dev/null |
  # grep "case \"$command\""` is read-only, names no path, and still
  # prompted. So reject command substitution (which can expand to anything),
  # and a variable spliced into a path (`$HOME/GitHub/...`, `"$root"/x`) --
  # but not a bare `$word` with no `/` around it, which is `$?`, `$1`, or a
  # literal `$name` inside a search pattern.
  printf '%s' "$cmd" | grep -qE '(\$\(|\$\{|`)' && return 0
  printf '%s' "$cmd" | grep -qE '(\$[A-Za-z_][A-Za-z0-9_]*/|/[^[:space:]"'\'']*\$[A-Za-z_{])' && return 0

  # Absolute paths must resolve under the worktree (or a disposable temp
  # area). Quotes, parens, commas and `=` are turned into SEPARATORS first,
  # not deleted: deleting them left `shutil.rmtree('/Users/x')` as the single
  # token `shutil.rmtree(/Users/x)`, which does not start with `/`, so the
  # check below never saw the path at all. Separating yields `/Users/x` as
  # its own token. An ordinary `sed s/a/b/` is unaffected -- it still forms
  # one token that does not begin with `/`.
  # Word-split deliberately, but with globbing off: an unquoted `*` in the
  # command would otherwise be pathname-expanded against the hook's own cwd
  # before we ever inspect it.
  local token
  set -f
  for token in $(printf '%s' "$cmd" | tr "\"'(),=" "      "); do
    case "$token" in
      /*)
        case "$token" in
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
