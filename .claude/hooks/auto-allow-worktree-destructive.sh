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
# worktree.
#
# In the main checkout it stays silent -- every ask/deny rule in settings.json
# applies unchanged -- with ONE exception: `git stash` is denied there too,
# because refs/stash is shared repo-wide rather than worktree-scoped, so the
# main checkout is one of the checkouts racing for it. That check sits above
# the worktree gate for exactly that reason. In a repository that is not this
# one, the hook is silent throughout, stash included.
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
# Shell keywords are in the prefix list beside the wrappers because a
# separator followed by a keyword is still a command-word position:
# `for d in */; do git stash; done` and `if true; then git stash; fi` put
# `do`/`then` exactly where `nohup` would sit, and a loop over worktrees is
# the shape the stash guard exists for.
CMD_PREFIX='([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+|(nohup|time|command|exec|env|eval|do|then|else|elif|if|while|until)[[:space:]]+)*'
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

# `git stash` does not work when more than one agent shares a repository.
#
# There is exactly ONE `refs/stash` per repository, shared by the main
# checkout and every linked worktree. It is a stack with no owner: agent A's
# `git stash` pushes an entry that agent B's `git stash pop` will happily
# take, and B has no way to tell it was not theirs. With ~20 worktrees
# active here that is not a race worth running -- it silently destroys work,
# in a way git provides no recovery path for once popped and discarded.
#
# Denied rather than asked, and denied in the MAIN CHECKOUT TOO, because the
# stack is shared repo-wide rather than worktree-scoped. A prompt would only
# push the decision onto whoever is watching, which for a subagent is nobody.
#
# The alternative is a temporary WIP commit: it lives on the branch, so it is
# per-worktree, private to that agent, and recoverable by SHA even if the
# branch moves.
#
#     git add -A && git commit -m "wip: <what>"     # set work aside
#     git reset --soft HEAD~1                        # pick it back up
#
# `git stash list` and `git stash show` only read, so they stay allowed.
#
# KNOWN LIMIT: a stash inside a quoted string -- `bash -c "git stash pop"`,
# `sh -c '...'` -- is not matched, because the anchor would have to treat a
# quote as a command separator. It cannot: `grep -rn 'git stash' docs/` is a
# pinned allow, and quote-permissive anchoring turns that into a deny. This
# guard classifies by command shape (see the header); an explicit shell
# wrapper defeats shape matching by construction, and chasing it is the
# regex-parses-shell mistake the header records.
uses_shared_stash() {
  # Bare `git stash` (implicit push), and every mutating subcommand.
  # `import` is git >= 2.50 and rewrites refs/stash wholesale.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+stash([[:space:]]+(push|save|pop|apply|drop|clear|branch|create|store|import)${CMD_END}|[[:space:]]*[;&|)<>]|[[:space:]]*$)" && return 0
  # The bare-`git stash` branch spells its terminator out instead of reusing
  # CMD_END: CMD_END accepts a SPACE, which here would swallow the space
  # before a subcommand and deny the read-only `git stash list`. Only a
  # separator or end of string means "no subcommand followed".
  #
  # `git stash -u`, `git stash -k`, etc: a flag straight after `stash` is
  # still an implicit push.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+stash[[:space:]]+-" && return 0
  return 1
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
  #
  # `gh api` is on that safe list, but only in its read shape. gh sends GET
  # unless the invocation says otherwise, and there are exactly two ways it
  # can: `-X/--method` names a verb outright, and `-f/-F/--field/--raw-field/
  # --input` attach a body, which flips the default to POST. A `gh api`
  # segment carrying any of them is a mutation and still asks -- classified
  # by the flags in the command, not by guessing what the endpoint does.
  # Without this, one read-only `gh api` poisoned an otherwise safe chain:
  # `gh pr view ... && gh api .../comments` counted 3 safe out of 4.
  local rest api_args
  rest=$1
  while printf '%s' "$rest" | grep -qE "${CMD_START}gh[[:space:]]+api${CMD_END}"; do
    rest=${rest#*gh api}
    api_args=${rest%%&&*}
    api_args=${api_args%%||*}
    api_args=${api_args%%;*}
    api_args=${api_args%%|*}
    printf '%s' "$api_args" |
      grep -qE "[[:space:]](-X|--method|-f|-F|--field|--raw-field|--input)([[:space:]]|=)" && return 0
  done

  local gh_all gh_safe
  gh_all=$(printf '%s' "$1" | grep -oE "${CMD_START}gh${CMD_END}" | wc -l | tr -d ' ' || true)
  gh_safe=$(printf '%s' "$1" | grep -oE "${CMD_START}gh([[:space:]]+(pr[[:space:]]+(view|list|diff|checks|status|create|edit|comment|ready|checkout|review)|issue[[:space:]]+(view|list|create|edit|comment|close|reopen)|run[[:space:]]+(view|list|watch)|release[[:space:]]+(view|list)|repo[[:space:]]+(view|clone)|workflow[[:space:]]+(view|list)|label[[:space:]]+(list|create)|api|search|auth[[:space:]]+status|--version|--help|-h)|${CMD_END})${CMD_END}" | wc -l | tr -d ' ' || true)
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

  # The stash is handled earlier by uses_shared_stash, which applies in the
  # main checkout too -- the stack is shared repo-wide, not worktree-scoped.

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
# so git's global options walked past every other one. It has to happen above
# the stash check too, not just above the worktree gate -- `git -C sub stash
# pop` is the same bypass aimed at the one guard that is a hard deny.
normalised=$(normalise_git "$command")

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

# Which repository is the command aimed at? Everything this hook knows about
# -- ~20 worktrees sharing one refs/stash, a podman VM, shared refs -- is true
# of THIS repository. A command run from a clone somewhere else is governed by
# nothing here, so the hook must be silent there, stash included: a hard deny
# with no override in an unrelated repo is a wall, not a guard.
#
# Identified the way check-worktree-path.sh does it -- two `git` results
# compared as strings, parsing nothing. The hook file is tracked, so a copy of
# it exists in every worktree; resolving from its own directory yields this
# repository's main root either way.
hook_main_root=$(git -C "$(dirname -- "$0")" worktree list --porcelain 2>/dev/null |
  awk '/^worktree /{sub(/^worktree /, ""); print; exit}')

if [ -z "$main_root" ] || [ -z "$hook_main_root" ] || [ "$main_root" != "$hook_main_root" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Above the worktree gate on purpose, and below the repo check for the same
# reason: refs/stash is shared by this repository's main checkout and every
# worktree alike, so it must hold in all of them -- and only in them.
if uses_shared_stash "$normalised"; then
  decide deny "Denied: there is ONE refs/stash for this whole repository, shared by the main checkout and all ~20 worktrees, and the stack has no owner -- another agent's \`git stash pop\` will take your entry with no way to tell it was not theirs. To set work aside on this branch, use a WIP commit, recoverable by SHA: \`git add -A && git commit -m \"wip: ...\"\`, then \`git reset --soft HEAD~1\` to resume. To move one file's changes into a worktree, pipe a patch across: \`git diff -- <file> | git -C <worktree> apply\` (see docs/agents/rules.md). (\`git stash list\`/\`show\` are read-only and still allowed.)"
  exit 0
fi

# Everything below applies ONLY inside a linked worktree. In the main
# checkout this hook stays silent so settings.json governs it entirely.
if [ "$session_root" = "$main_root" ]; then
  echo '{"continue": true}'
  exit 0
fi

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
