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
# Most checks below fail CLOSED: where a pattern list is unavoidable it
# enumerates what is SAFE, so a shape nobody thought of costs one prompt
# rather than a silent auto-allow. That holds for the `gh` list, the
# read-only list and the containment check.
#
# `mutates_shared_state` is the exception and cannot be inverted: git's
# subcommand surface is open-ended, so a safe-list would prompt on most
# ordinary git use. It is a BLOCKLIST, which means a ref-mutating shape not
# named there is allowed -- that is how `git branch -f main HEAD`,
# `update-ref` and `symbolic-ref` were missed once already. Treat it as the
# weakest link here and add to it whenever a new shared-state write shows
# up, rather than assuming its absence implies safety.
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
#
# The anchor must also step over anything that sits BEFORE the command word
# without being it. Without this, one env assignment defeated every guard in
# this file at once -- `PODMAN=1 podman machine rm` was auto-allowed,
# silently upgrading a settings.json `deny` to an unprompted allow. Env
# prefixes are ordinary generated-command shape (`PYTHONPATH=. ...`,
# `TZ=UTC ...`), so that was an accident-class miss, not just an
# adversarial one.
CMD_PREFIX='([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+|(nohup|time|command|exec|env)[[:space:]]+)*'
CMD_START="(^|[;&|(]|&&|\\|\\||\\n)[[:space:]]*${CMD_PREFIX}"

# `git` accepts global options between the program name and the subcommand,
# so a literal `git`+space+`push` match is trivially sidestepped by
# `git -C sub push origin main` or `git --git-dir=... push origin main`.
# Strip those options once, up front, and match against the normalised
# string. Spaces are squeezed too so `git   push` matches the same way.
# This is for MATCHING only -- the command that runs is untouched.
normalise_git() {
  printf '%s' "$1" | sed -E \
    -e 's/(^|[[:space:]])git([[:space:]]+(-c[[:space:]]+[^[:space:]]+|-C[[:space:]]+[^[:space:]]+|--git-dir=[^[:space:]]+|--work-tree=[^[:space:]]+|--exec-path=[^[:space:]]*|--no-pager|--paginate|--bare|--literal-pathspecs))+/\1git/g' \
    | tr -s ' '
}

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
# settings.json ALLOWS `Bash(git push *)` outright -- falling through would
# let a shared-ref push run unprompted rather than prompt. (There is no
# blanket `Bash(gh *)` entry, only eight narrow `gh issue`/`gh pr`
# patterns; the safe list below must stay a superset of those, or a hook
# decision silently revokes a permission the user granted.)
is_globally_scoped() {
  printf '%s' "$1" | grep -qE "${CMD_START}sudo[[:space:]]" && return 0

  # `gh` reaches GitHub, which no worktree contains. Enumerating destructive
  # subcommands fails the wrong way: `gh api -X DELETE repos/...` is the
  # general form of every entry such a list could hold, and `gh workflow
  # run` / `gh secret set` / `gh repo edit` are not obviously "destructive"
  # names. So invert -- every `gh` asks unless it is on the safe list.
  # Counting both forms catches a compound `gh pr view && gh pr merge`,
  # where matching only the first invocation would clear the whole command.
  #
  # The safe list covers reads AND authoring, not reads alone. A read-only
  # list looks tighter but defeats the point of the hook: `gh pr create` is
  # the closing step of implement-issue, so a run that no longer stalls on
  # `rm -f` would instead stall at the finish line, and `gh issue comment`
  # would stall it in the middle. Authoring a PR/issue on this repo IS the
  # work product. What stays behind a prompt is everything that publishes,
  # merges, or reconfigures: pr merge, release, repo edit/delete, secret,
  # workflow run, and any non-GET `gh api`.
  local gh_all gh_safe
  # `grep -c` counts LINES, and a command is normally one line, so both
  # counts would be 1 for that compound. Count occurrences with -o | wc -l.
  # `gh[[:space:]]` missed a bare `gh` at end of string -- it matched neither
  # counter, so both stayed 0 and the command was allowed. Anchor on
  # ([[:space:]]|$) so the totals cannot silently agree at zero.
  gh_all=$(printf '%s' "$1" | grep -oE "${CMD_START}gh([[:space:]]|$)" | wc -l | tr -d ' ' || true)
  gh_safe=$(printf '%s' "$1" | grep -oE "${CMD_START}gh([[:space:]]+(pr[[:space:]]+(view|list|diff|checks|status|create|edit|comment|ready|checkout|review)|issue[[:space:]]+(view|list|create|edit|comment|close|reopen)|run[[:space:]]+(view|list|watch)|release[[:space:]]+(view|list)|repo[[:space:]]+(view|clone)|workflow[[:space:]]+(view|list)|label[[:space:]]+(list|create)|search|auth[[:space:]]+status|--version|--help|-h)|([[:space:]]|$))([[:space:]]|$)" | wc -l | tr -d ' ' || true)
  [ "$gh_all" -ne "$gh_safe" ] && return 0

  # Any push that can move a shared ref. The ref has to be matched in every
  # refspec form -- `main`, `HEAD:main`, `br:refs/heads/main`, `+main` --
  # not just as a bare word, since the bare word is the spelling least
  # likely to appear when something force-updates a ref.
  #
  # `--force-with-lease` is exempt: it is the one force form that REFUSES to
  # clobber an update it has not seen, which is exactly the accident a
  # prompt here would be guarding against. It is also routine after the
  # Step 4 merge, so asking costs a stall on every run. Bare `--force`/`-f`
  # keeps asking -- that one overwrites unconditionally. Order matters
  # below: test the lease form first, or `--force` matches its prefix.
  # Both tests are scoped to the push's OWN arguments, not the whole command
  # string. Scanning the whole string made any `main` anywhere in a compound
  # turn a safe push into a prompt -- including `git push -u origin feat/x &&
  # gh pr create --base main ...`, which is implement-issue's closing step,
  # i.e. exactly the stall this hook exists to remove.
  # EVERY push is examined, not just the first. Stripping only up to the
  # first occurrence let a second push ride along unchecked --
  # `git push origin feat/x && git push origin main` was allowed, defeating
  # the guard this comment describes.
  local norm rest push_args
  norm=$(normalise_git "$1")
  rest=$norm
  while printf '%s' "$rest" | grep -qE "${CMD_START}git[[:space:]]+push([[:space:]]|$)"; do
    rest=${rest#*git push}
    push_args=${rest%%&&*}
    push_args=${push_args%%||*}
    push_args=${push_args%%;*}
    push_args=${push_args%%|*}
    push_touches_shared_ref "$push_args" && return 0
  done
  return 1
}

# Decides whether one push's argument list names a ref shared with other
# checkouts. Works on the refspec TOKENS rather than scanning the string:
# a substring test cannot tell `main` from `feat/main-ish`, and widening it
# to catch `beta-release-*` would have swallowed the latter.
push_touches_shared_ref() {
  local args="$1" tok dst

  if ! printf '%s' "$args" | grep -qE '\-\-force-with-lease'; then
    printf '%s' "$args" | grep -qE "(--force|[[:space:]]-f([[:space:]]|$))" && return 0
  fi
  printf '%s' "$args" | grep -qE "(--all|--mirror|--tags)" && return 0

  set -f
  for tok in $args; do
    case "$tok" in -*) continue ;; esac
    # `src:dst` pushes to dst; a bare token is its own destination. Strip the
    # force marker and any fully-qualified prefix so every spelling of the
    # same ref -- main, HEAD:main, br:refs/heads/main, +main -- reduces to
    # the same name.
    dst=${tok##*:}
    dst=${dst#+}
    dst=${dst#refs/heads/}
    dst=${dst#refs/tags/}
    case "$dst" in
      # beta-release-* are shared release refs per the Release Workflow
      # section, and were missed while `beta` itself was caught.
      main | beta | beta-release* | release-* | v[0-9]*)
        set +f
        return 0
        ;;
    esac
  done
  set +f

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
  # `git branch -D` is deliberately NOT here. implement-issue Step 4 prunes
  # merged worktrees in a loop, so asking turns one cleanup step into dozens
  # of prompts -- and the danger it would be guarding is already handled
  # upstream: git itself REFUSES to delete a branch checked out in another
  # worktree ("error: cannot delete branch 'x' used by worktree at ...",
  # exit 1), so it cannot cut another agent out from under itself. What is
  # left is an unchecked-out branch, whose SHA git prints on delete and
  # which stays reachable -- protected because `reflog expire`, `gc` and
  # `filter-branch` below keep asking. `git tag -d` DOES stay: a tag is how
  # a release is addressed, and nothing refuses to delete one.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+tag[[:space:]]+(.*[[:space:]])?(-d|--delete)([[:space:]]|$)" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+(gc|prune|reflog[[:space:]]+expire|update-ref[[:space:]]+-d|filter-branch)([[:space:]]|$)" && return 0

  # The stash is ONE `refs/stash` shared by every worktree, so these discard
  # work stashed from the main checkout or another agent's session. Same
  # class as the reflog/gc cases above, and this project leans on `git stash`
  # for branch isolation, which makes the shared stack a live hazard rather
  # than a theoretical one.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+stash[[:space:]]+(clear|drop|pop)([[:space:]]|$)" && return 0

  # A linked worktree shares `.git/config` with the main checkout, and
  # `--global` reaches `~/.gitconfig`, outside every worktree. Repointing or
  # removing `origin` changes where every checkout pushes.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+config[[:space:]]+(.*[[:space:]])?(--global|--system)([[:space:]]|$)" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+remote[[:space:]]+(set-url|remove|rm|rename|add)([[:space:]]|$)" && return 0

  # Direct writes to the shared ref namespace. `git branch -D` is allowed
  # because git refuses the dangerous case, but nothing refuses these: they
  # MOVE a ref rather than delete it, so `git branch -f main HEAD` rewrites
  # main for every checkout at once, and `update-ref`/`symbolic-ref` do the
  # same one layer down. `update-ref` has no read form. `symbolic-ref` does
  # (`--short HEAD`), so only the two-argument writing form matches.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+branch[[:space:]]+(.*[[:space:]])?(-f|--force|-M|-m|--move)([[:space:]]|$)" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+update-ref([[:space:]]|$)" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+symbolic-ref[[:space:]]+[^-][^[:space:]]*[[:space:]]+[^[:space:]]" && return 0
  # Same upstream-protection argument as `git branch -D`: plain `git worktree
  # remove` REFUSES a worktree holding uncommitted or untracked files
  # (verified: "contains modified or untracked files, use --force to delete
  # it", exit 128), so it cannot destroy unsaved work, and a clean worktree
  # has nothing to lose -- its branch survives. Step 4 removes merged
  # worktrees in a loop, so asking here meant ~24 prompts in one step. Only
  # `--force`, which is what actually discards the work, still asks.
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+worktree[[:space:]]+remove([[:space:]]|$)" &&
    printf '%s' "$1" | grep -qE "(--force|[[:space:]]-f([[:space:]]|$))" && return 0
  printf '%s' "$1" | grep -qE "${CMD_START}git[[:space:]]+worktree[[:space:]]+prune([[:space:]]|$)" && return 0
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

# Every LINKED worktree of this repo, i.e. all of them except the main
# checkout. These count as contained: a linked worktree is disposable by
# exactly the argument that justifies auto-allowing commands inside this
# one, and agents legitimately reach across them (cutting a release from a
# changelog worktree, comparing two branches' output). Treating them as
# foreign made ordinary cross-worktree work prompt, while protecting
# nothing -- the checkout this guard exists for is the MAIN one, which is
# shared, long-lived, and the only place a stale path does lasting damage.
linked_roots=$(printf '%s\n' "$worktree_list" | awk '/^worktree /{sub(/^worktree /, ""); print}' | tail -n +2)

is_contained_path() {
  local candidate="$1" root
  case "$candidate" in
    "$session_root" | "$session_root"/*) return 0 ;;
    /tmp/* | /private/tmp/* | /private/var/folders/* | /dev/null) return 0 ;;
  esac
  # Never the main checkout, even though it is in the same repo.
  case "$candidate" in
    "$main_root" | "$main_root"/*) return 1 ;;
  esac
  while IFS= read -r root; do
    [ -n "$root" ] || continue
    case "$candidate" in
      "$root" | "$root"/*) return 0 ;;
    esac
  done <<EOF
$linked_roots
EOF
  return 1
}

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
  # Trigger on the ability to WRITE, not on merely naming a path.
  #
  # The previous trigger was "any absolute path, any `..`, any `~`", which
  # made the containment check run over nearly every command -- and since
  # that check cannot parse shell quoting, each unparseable-but-harmless
  # shape became a prompt. Four distinct false positives reached the user:
  # `cmd 2>/dev/null` plus any `$var`; a `cd` into a SIBLING worktree; a
  # read-only `grep` whose literal pattern contained `$(` and `;;`; and
  # inspection of files under $HOME. All were read-only or worktree-local.
  #
  # A command that cannot write cannot commit the accident this guards, so
  # the write verbs ARE the right trigger. The cost is a known miss: an
  # arbitrary-write shape not on this list is auto-allowed. Interpreters are
  # therefore included wholesale (`python3 -c "shutil.rmtree(...)"` was the
  # motivating miss), and `is_contained_path` -- not this list -- is what
  # decides whether the path is actually foreign.
  printf '%s' "$1" | grep -qE "${CMD_START}(rm|mv|cp|ln|dd|tee|shred|install|truncate|chmod|chown|rsync|find|xargs|sed|touch|mkdir|tar|unzip|python|python3|perl|ruby|node|osascript)([[:space:]]|$)" && return 0
  printf '%s' "$1" | grep -qE "(^|[[:space:]])(-C|--git-dir|--work-tree)([[:space:]]|=)" && return 0
  # A redirect that creates or truncates a file. `2>/dev/null` and `2>&1`
  # are stripped first -- they write nothing and appear on ordinary reads.
  printf '%s' "$1" |
    sed -E 's/2>&1//g; s/[0-9]?>[[:space:]]*\/dev\/null//g' |
    grep -qE '>' && return 0
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
  # Shell separators must be separators HERE too, not just quotes and
  # parens. Without `;`, `cd /path/to/wt; cmd` yielded the token
  # "/path/to/wt;" -- trailing semicolon attached -- which matches neither
  # "$session_root" nor "$session_root"/*, so a worktree was judged foreign
  # to ITSELF and every `cd <own worktree>; ...` prompted.
  for token in $(printf '%s' "$cmd" | tr "\"'(),=;&|<>" "           "); do
    case "$token" in
      /*)
        case "$token" in
          *)
            if ! is_contained_path "$token"; then
              set +f
              return 0
            fi
            ;;
        esac
        ;;
    esac
  done
  set +f

  return 1
}

# Pruning a merged worktree necessarily names a path outside this one, so
# the containment check below would ask on every iteration of Step 4's
# cleanup loop -- ~24 prompts for the step whose whole purpose is unattended
# tidying. Exempt exactly that command and nothing else: a lone `git
# worktree remove` with no `--force` (matched above in mutates_shared_state)
# and no second invocation chained after it. git refuses to remove a
# worktree holding uncommitted or untracked files, so this cannot discard
# work; `rm -rf <other worktree>` gets no such exemption, because nothing
# protects it.
# --- Read-only inspection -----------------------------------------------
#
# needs_scrutiny fires on any absolute path or `~`, whether or not the
# command can write. That made ordinary inspection outside the worktree
# prompt -- `cat ~/Downloads/bess-debug.json` is the first step of
# visualize-debug-log, and `head $MAIN/CHANGELOG.md` is routine -- trading
# one stall class for another. The containment guard is about WRITES, so a
# command that cannot write is exempt from it.
#
# This is an allowlist, so it fails closed: an unrecognised program (or
# `python3 -c ...`, or `sed -i`) is not read-only and stays scrutinised.
READ_ONLY_CMDS='cat|head|tail|less|more|grep|egrep|fgrep|rg|ag|ls|stat|file|wc|diff|jq|yq|sort|uniq|cut|tr|column|basename|dirname|realpath|readlink|echo|printf|pwd|date|which|type|shasum|md5sum|true|test'
READ_ONLY_GIT='log|show|diff|status|rev-parse|ls-files|describe|blame|shortlog|cat-file|for-each-ref|check-ignore'

is_read_only() {
  local cleaned seg first sub
  # Discard the harmless redirects first; any OTHER redirect writes a file,
  # so the command is not read-only.
  cleaned=$(printf '%s' "$1" | sed -E 's/2>&1//g; s/[0-9]?>[[:space:]]*\/dev\/null//g')
  printf '%s' "$cleaned" | grep -q '>' && return 1

  while IFS= read -r seg; do
    seg=$(printf '%s' "$seg" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
    [ -z "$seg" ] && continue
    # Step over the same prefixes CMD_START skips.
    seg=$(printf '%s' "$seg" | sed -E "s/^${CMD_PREFIX}//")
    first=${seg%% *}
    case "$first" in
      git)
        sub=$(printf '%s' "$seg" | awk '{print $2}')
        printf '%s' "$sub" | grep -qE "^(${READ_ONLY_GIT})$" || return 1
        ;;
      *)
        printf '%s' "$first" | grep -qE "^(${READ_ONLY_CMDS})$" || return 1
        ;;
    esac
  done <<EOF
$(printf '%s' "$cleaned" | tr ';|&' '\n')
EOF
  return 0
}

is_lone_worktree_removal() {
  printf '%s' "$1" | grep -qE '^[[:space:]]*git[[:space:]]+worktree[[:space:]]+remove[[:space:]]+[^;&|]+$' &&
    ! printf '%s' "$1" | grep -qE '(--force|[[:space:]]-f([[:space:]]|$))'
}

if ! is_read_only "$command" &&
   ! is_lone_worktree_removal "$command" &&
   needs_scrutiny "$command" && escapes_worktree "$command"; then
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
