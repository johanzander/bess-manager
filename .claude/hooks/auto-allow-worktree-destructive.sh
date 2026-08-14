#!/usr/bin/env bash
# PreToolUse hook for Bash.
#
# Inside a linked git worktree, do anything to the repository -- except
# destroy the repository or its history.
#
# A linked worktree (.claude/worktrees/* or a sibling per CLAUDE.md's
# Worktree Conventions) is disposable by construction: blow it away, make
# another. Prompting there protects nothing and stalls otherwise autonomous
# work, so this hook auto-allows Bash commands whose cwd is a linked
# worktree. In the main checkout it stays silent and every ask/deny rule in
# settings.json applies unchanged.
#
# What it still refuses is a short, closed list of effects no worktree can
# contain, and which no amount of `git checkout` gets back:
#
#   1. The shared podman VM every worktree's E2E stack runs on (a `deny`
#      in settings.json, re-emitted here rather than downgraded).
#   2. Elevated privileges, anything reaching GitHub, and pushes that move
#      a shared ref (main, beta, beta-release-*, tags).
#   3. Writes to state shared across worktrees: ONE object database, ONE
#      ref namespace, ONE stash, ONE .git/config.
#
# WHAT THIS DELIBERATELY NO LONGER DOES
#
# An earlier version also tried to decide, from the command string, whether
# a command would write OUTSIDE the worktree -- absolute paths, `..`, `~`,
# variables, substitutions. That is shell parsing by regex, and it does not
# work: quoting, globs, heredocs and `cd` all defeat it. It produced six
# distinct false positives in one day, EVERY ONE introduced by the fix to
# the previous one -- including blocking a live beta release, and judging a
# worktree foreign to itself because `;` was not treated as a separator.
#
# It is gone. The accepted cost: a stale absolute path in a Bash command can
# now reach the main checkout without a prompt. Tracked content there is
# recoverable from git; uncommitted work is not. That trade was made
# deliberately, because a guard with a false-positive rate this high gets
# click-throughed and protects nothing anyway.
#
# The equivalent guard for Edit/Write still exists and is reliable, because
# it parses nothing: check-worktree-path.sh compares two `git rev-parse`
# results as strings. Prefer that shape for anything added here.
set -euo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

if [ -z "$command" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Anchored at command-word position: start of string, or after a shell
# separator, stepping over anything that precedes the command word without
# being it. A bare substring match would read `grep "sudo " docs/` as
# running sudo; without the prefix step, one env assignment
# (`PODMAN=1 podman machine rm`) shifted the command word out of every
# guard at once and turned a deny into a silent allow.
CMD_PREFIX='([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+|(nohup|time|command|exec|env)[[:space:]]+)*'
CMD_START="(^|[;&|(]|&&|\\|\\||\\n)[[:space:]]*${CMD_PREFIX}"

# The mirror of CMD_START at the far end of a match. Every guard needs one --
# without it `git gc --prune=now` matches while `git tag -d v1` matches only
# the prefix, so `git tagfoo` would slip in either direction -- but the naive
# spelling `([[:space:]]|$)` sees only a SPACE or end of string. A separator
# written flush against the last word is neither, so `git stash drop;`,
# `git gc&&echo x` and `sudo;` all read as unmatched and were auto-allowed
# while their spaced spellings asked. Shell separators terminate a command
# word exactly as whitespace does, so they belong in the same class.
CMD_END='([[:space:]]|[;&|)<>]|$)'

# git accepts global options between the program name and the subcommand,
# so a literal `git`+space+`push` match is sidestepped by `git -C sub push`.
# Strip them once, for MATCHING only; the command that runs is untouched.
# The leading class matches CMD_START's separators, not just whitespace:
# `git status;git -C sub gc` puts a `;` where the anchor wanted a space, and
# every guard downstream would then read the un-normalised form.
normalise_git() {
  printf '%s' "$1" | sed -E \
    -e 's/(^|[[:space:];&|(])git([[:space:]]+(-c[[:space:]]+[^[:space:]]+|-C[[:space:]]+[^[:space:]]+|--git-dir=[^[:space:]]+|--work-tree=[^[:space:]]+|--exec-path=[^[:space:]]*|--no-pager|--paginate|--bare|--literal-pathspecs))+/\1git/g' \
    | tr -s ' '
}

# settings.json DENIES these outright. A hook decision supersedes a settings
# rule, so answering "ask" here would quietly downgrade that hard block to a
# single keystroke. Re-emit the deny.
is_hard_denied() {
  printf '%s' "$1" | grep -qE "${CMD_START}podman[[:space:]]+(machine[[:space:]]+(rm|reset)|system[[:space:]]+reset)${CMD_END}"
}

# Does one push's argument list name a ref shared with other checkouts?
# Compared as TOKENS, not by substring: a substring test cannot tell `main`
# from `feat/main-ish`, and widening it to catch `beta-release-*` would
# swallow the latter.
push_touches_shared_ref() {
  local args="$1" tok dst

  # --force-with-lease is the one force form that refuses to clobber an
  # update it has not seen -- the accident a prompt here would guard -- and
  # it is routine after a merge. Bare --force/-f overwrites unconditionally.
  if ! printf '%s' "$args" | grep -qE '\-\-force-with-lease'; then
    printf '%s' "$args" | grep -qE "(--force|[[:space:]]-f${CMD_END})" && return 0
  fi
  printf '%s' "$args" | grep -qE "(--all|--mirror|--tags)" && return 0

  set -f
  for tok in $args; do
    case "$tok" in -*) continue ;; esac
    # `src:dst` pushes to dst; a bare token is its own destination. Strip the
    # force marker and any fully-qualified prefix so every spelling of one
    # ref -- main, HEAD:main, br:refs/heads/main, +main -- reduces alike.
    dst=${tok##*:}
    dst=${dst#+}
    dst=${dst#refs/heads/}
    dst=${dst#refs/tags/}
    case "$dst" in
      main | beta | beta-release* | release-* | v[0-9]*)
        set +f
        return 0
        ;;
    esac
  done
  set +f
  return 1
}

is_globally_scoped() {
  printf '%s' "$1" | grep -qE "${CMD_START}sudo${CMD_END}" && return 0

  # `gh` reaches GitHub, which no worktree contains. Enumerating destructive
  # subcommands fails the wrong way -- `gh api -X DELETE` is the general form
  # of every entry such a list could hold -- so invert: every `gh` asks
  # unless it is on the safe list. That list covers reads AND authoring,
  # because `gh pr create` is the closing step of implement-issue and
  # authoring on this repo IS the work product. It must also stay a superset
  # of settings.json's `gh` allow patterns, or a hook decision silently
  # revokes a permission the user granted. Counting per invocation catches
  # `gh pr view && gh pr merge`, where matching the first would clear both.
  local gh_all gh_safe
  gh_all=$(printf '%s' "$1" | grep -oE "${CMD_START}gh${CMD_END}" | wc -l | tr -d ' ' || true)
  gh_safe=$(printf '%s' "$1" | grep -oE "${CMD_START}gh([[:space:]]+(pr[[:space:]]+(view|list|diff|checks|status|create|edit|comment|ready|checkout|review)|issue[[:space:]]+(view|list|create|edit|comment|close|reopen)|run[[:space:]]+(view|list|watch)|release[[:space:]]+(view|list)|repo[[:space:]]+(view|clone)|workflow[[:space:]]+(view|list)|label[[:space:]]+(list|create)|search|auth[[:space:]]+status|--version|--help|-h)|${CMD_END})${CMD_END}" | wc -l | tr -d ' ' || true)
  [ "$gh_all" -ne "$gh_safe" ] && return 0

  # Every push is examined, not just the first: stripping only to the first
  # occurrence let `git push origin feat/x && git push origin main` through.
  local rest push_args
  rest=$1
  while printf '%s' "$rest" | grep -qE "${CMD_START}git[[:space:]]+push${CMD_END}"; do
    rest=${rest#*git push}
    push_args=${rest%%&&*}
    push_args=${push_args%%||*}
    push_args=${push_args%%;*}
    push_args=${push_args%%|*}
    push_touches_shared_ref "$push_args" && return 0
  done
  return 1
}

# A linked worktree has its own working tree but ONE object database, ONE
# ref namespace, ONE stash and ONE .git/config with every other checkout.
# These reach outside it without naming a path at all.
#
# This is a BLOCKLIST and cannot be inverted -- git's subcommand surface is
# open-ended, so a safe-list would prompt on most ordinary git use. A
# ref-mutating shape not named here is allowed; that is how `git branch -f`,
# `update-ref` and `symbolic-ref` were missed once already. Add to it when a
# new shared-state write appears rather than assuming absence means safety.
mutates_shared_state() {
  # `git branch -D` is deliberately absent: git REFUSES to delete a branch
  # checked out in another worktree, and an unchecked-out branch stays
  # reachable by the SHA git prints -- protected because reflog expire / gc
  # below keep asking. `git tag -d` stays: nothing refuses that, and a tag is
  # how a release is addressed.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+tag[[:space:]]+(.*[[:space:]])?(-d|--delete)${CMD_END}" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+(gc|prune|reflog[[:space:]]+expire|filter-branch)${CMD_END}" && return 0

  # ONE refs/stash for every worktree, and this project leans on stash for
  # branch isolation, so the shared stack is a live hazard.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+stash[[:space:]]+(clear|drop|pop)${CMD_END}" && return 0

  # Shared .git/config, and --global reaches ~/.gitconfig.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+config[[:space:]]+(.*[[:space:]])?(--global|--system)${CMD_END}" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+remote[[:space:]]+(set-url|remove|rm|rename|add)${CMD_END}" && return 0

  # Direct writes to the ref namespace. These MOVE a ref rather than delete
  # it, so nothing refuses them the way it refuses `branch -D`.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+branch[[:space:]]+(.*[[:space:]])?(-f|--force|-M|-m|--move)${CMD_END}" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+update-ref${CMD_END}" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+symbolic-ref[[:space:]]+[^-][^[:space:]]*[[:space:]]+[^[:space:]]" && return 0

  # Plain `worktree remove` refuses a worktree holding uncommitted or
  # untracked files, so only --force can actually discard work.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+worktree[[:space:]]+remove${CMD_END}" &&
    printf '%s' "$1" | grep -qE "(--force|[[:space:]]-f${CMD_END})" && return 0

  # `worktree prune` unregisters worktrees whose directory it cannot see --
  # which includes one that is merely unmounted or temporarily moved, not
  # only one that is really gone.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+worktree[[:space:]]+prune${CMD_END}" && return 0

  return 1
}

session_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$session_root" ]; then
  echo '{"continue": true}'
  exit 0
fi

# First entry of `git worktree list --porcelain` is always the main worktree;
# every other entry is a linked one. (Capture before awk -- piping straight
# into `awk 'exit'` can SIGPIPE git under `set -o pipefail`. And strip the
# prefix rather than taking $2, which truncates a path containing a space and
# would make the main checkout fail its own identity test.)
worktree_list=$(git worktree list --porcelain)
main_root=$(printf '%s\n' "$worktree_list" | awk '/^worktree /{sub(/^worktree /, ""); print; exit}')

# Everything below applies ONLY inside a linked worktree. In the main
# checkout this hook stays silent so settings.json governs it entirely.
if [ -z "$main_root" ] || [ "$session_root" = "$main_root" ]; then
  echo '{"continue": true}'
  exit 0
fi

decide() {
  jq -n --arg d "$1" --arg reason "$2" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: $d,
      permissionDecisionReason: $reason
    }
  }'
}

# Normalise ONCE, here, so every guard below matches the same string. Doing it
# inside a single guard is what let `git -C sub gc`, `git -C sub stash drop`
# and `git -c x=y config --global ...` through: only the push guard normalised,
# so git's global options walked past every other one.
normalised=$(normalise_git "$command")

if is_hard_denied "$normalised"; then
  decide deny "Denied in settings.json: this destroys the shared podman VM that every worktree's E2E stack depends on. Being inside a disposable worktree does not contain it."
  exit 0
fi

if is_globally_scoped "$normalised"; then
  decide ask "Not auto-allowed: this command's effect is global -- elevated privileges, a GitHub mutation, or a push that moves a shared ref (main, beta, beta-release-*, a tag). A worktree cannot contain it, so confirm explicitly."
  exit 0
fi

if mutates_shared_state "$normalised"; then
  decide ask "Not auto-allowed: a linked worktree shares ONE object database, ref namespace, stash and .git/config with every other checkout, so this reaches outside '${session_root}' without naming a path. Confirm explicitly."
  exit 0
fi

decide allow "Auto-allowed: cwd '${session_root}' is a linked git worktree (main checkout is '${main_root}'), which is disposable by construction. Effects that no worktree can contain -- the shared podman VM, GitHub, shared refs, shared git state -- are excluded and still prompt."
