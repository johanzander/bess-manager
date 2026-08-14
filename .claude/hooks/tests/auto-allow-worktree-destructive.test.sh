#!/usr/bin/env bash
# Regression tests for .claude/hooks/auto-allow-worktree-destructive.sh.
#
# The hook decides between "allow", "ask" and "deny" from a command STRING,
# and both directions of a wrong answer hurt: a missed containment case
# silently writes into the shared main checkout, while an over-broad match
# reintroduces the prompt-stall the hook exists to remove. Every case below
# is one or the other.
#
# Runs against a throwaway repo + linked worktree in a temp dir, so it needs
# no particular checkout layout and leaves nothing behind.
#
#   bash .claude/hooks/tests/auto-allow-worktree-destructive.test.sh
set -uo pipefail

HOOK=$(cd "$(dirname "$0")/.." && pwd)/auto-allow-worktree-destructive.sh
[ -f "$HOOK" ] || { echo "hook not found: $HOOK" >&2; exit 1; }

# Deliberately NOT under mktemp's default root: the hook counts /tmp and
# the macOS $TMPDIR as disposable, so a fixture there would be auto-allowed
# and the "reaches the main checkout" cases could not be expressed at all.
# `pwd -P` because `git rev-parse --show-toplevel` reports a resolved path
# and the hook compares the two as strings.
# ~/.cache is absent on a fresh macOS install and on most CI runners, where
# mktemp would fail with only its own stderr -- indistinguishable from a
# real test failure.
mkdir -p "${HOME}/.cache" || exit 1
TMP=$(mktemp -d "${HOME}/.cache/bess-hook-test-XXXXXX") || exit 1
TMP=$(cd "$TMP" && pwd -P)
trap 'rm -rf "$TMP"' EXIT

MAIN="$TMP/main"
WT="$TMP/wt"
git init -q "$MAIN"
# The hook identifies its own repository from its own location, and is silent
# in any other -- so the fixture has to OWN the copy under test, or every case
# below would fall through as "not this repo". This mirrors production, where
# the hook file is tracked and a copy sits in every worktree.
mkdir -p "$MAIN/.claude/hooks"
cp "$HOOK" "$MAIN/.claude/hooks/"
HOOK="$MAIN/.claude/hooks/$(basename "$HOOK")"
git -C "$MAIN" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$MAIN" worktree add -q -b testwt "$WT"
# A second linked worktree, to prove sibling worktrees count as contained
# while the main checkout does not.
git -C "$MAIN" worktree add -q -b siblingwt "$TMP/sibling-wt"

failures=0

# Asserts the hook's decision for a command run from inside the worktree.
run() {
  local expected="$1" cmd="$2" out got
  out=$(printf '%s' "$cmd" | jq -Rn '{tool_input: {command: input}}' | (cd "$WT" && bash "$HOOK") 2>&1)
  got=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // (if .continue then "fallthrough" else "unparseable" end)' 2>/dev/null) \
    || got="unparseable: $out"
  if [ "$got" = "$expected" ]; then
    printf 'ok    %-5s %s\n' "$got" "$cmd"
  else
    printf 'FAIL  got=%-12s want=%-6s %s\n' "$got" "$expected" "$cmd"
    failures=$((failures + 1))
  fi
}

echo "== pushes that can move a shared ref =="
# The bare `main` spelling is the one an accidental force-update is LEAST
# likely to use, so every refspec form has to be matched.
run ask "git push origin main"
run ask "git push origin HEAD:main"
run ask "git push origin mybr:refs/heads/main"
run ask "git push origin +main"
run ask "git push --force origin HEAD:refs/heads/main"
run ask "git push -f origin mybr"
run ask "git push origin v10.1.0"
run ask "git push --tags"
run ask "git push beta main"
run allow "git push origin feat/issue-561-thing"
run allow "git push -u origin feat/main-ish"
# --force-with-lease is the one force form that REFUSES to clobber an
# update it has not seen -- the accident a prompt here would guard. It is
# routine after the Step 4 merge, so asking would stall every run. Bare
# --force still asks (pinned above), including when both could match.
run allow "git push --force-with-lease origin HEAD"
run allow "git push --force-with-lease origin feat/issue-561-thing"
# ...but never onto a shared ref, lease or not.
run ask "git push --force-with-lease origin main"
run ask "git push --force-with-lease origin HEAD:refs/heads/beta"

echo "== state shared with the main checkout =="
# A linked worktree has its own working tree but ONE object database and
# ONE ref namespace, so these escape it even without -C.
# `git branch -D` is allowed on purpose. implement-issue Step 4 prunes
# merged worktrees in a loop, and the danger is already handled upstream:
# git REFUSES to delete a branch checked out in another worktree (verified:
# "error: cannot delete branch 'x' used by worktree at ...", exit 1). An
# unchecked-out branch stays reachable by the SHA git prints, which is why
# reflog expire / gc / filter-branch below must keep asking.
run allow "git branch -D some-branch"
run allow "git branch --delete some-branch"
# A tag is how a release is addressed and nothing refuses to delete one.
run ask "git tag -d v1.0.0"
run ask "git gc --prune=now"
run ask "git reflog expire --expire=now --all"
# Plain `remove` refuses a worktree with uncommitted or untracked files
# (verified: exit 128), so only --force can actually discard work.
run allow "git worktree remove $TMP/other"
run ask "git worktree remove --force $TMP/other"
run ask "git worktree remove -f $TMP/other"
# THE ACCEPTED TRADE. Filesystem containment was removed, so a command that
# names a path outside this worktree -- including the main checkout -- is no
# longer inspected. These two are pinned as `allow` deliberately: they are
# what the reduced hook lets through, and if a future change makes them ask
# again, that is a decision to take knowingly rather than by accident.
# Tracked content in the main checkout is recoverable from git; uncommitted
# work is not. The Edit/Write equivalent is still guarded by
# check-worktree-path.sh, which compares two `git rev-parse` results and
# parses nothing.
run allow "git worktree remove $TMP/other && rm -rf $MAIN"
run allow "rm -rf $TMP/other"
run ask "git worktree prune"
run allow "git branch --show-current"
run allow "git status --short"

echo "== gh reaches GitHub, which no worktree contains =="
run ask "gh api -X DELETE repos/o/r"
run ask "gh api repos/o/r"
run ask "gh workflow run issue-fix.yml"
run ask "gh secret set FOO"
run ask "gh repo edit --visibility private"
run ask "gh pr close 561"
run ask "gh pr merge 561"
# A read-only first invocation must not clear the rest of a compound.
run ask "gh pr view 561 && gh pr merge 561"
run allow "gh pr view 561 --json title"
run allow "gh pr list"
# Authoring a PR/issue on this repo IS the work product -- `gh pr create` is
# the closing step of implement-issue, so a read-only-only safe list would
# move the stall from `rm -f` to the finish line. Publishing, merging and
# reconfiguring stay behind a prompt (pinned above).
run allow "gh pr create --draft --base main --title x --body-file /tmp/b.md"
run allow "gh pr edit 561 --body-file /tmp/b.md"
run allow "gh pr ready 561"
run allow "gh issue comment 558 --body 'working on it'"
run allow "gh issue edit 558 --add-label analyzed"
# Authoring first must still not clear a publishing invocation after it.
run ask "gh pr create --draft --title x && gh pr merge 561"
run allow "gh run watch 123"

echo "== the shared stash is denied outright =="
# ONE refs/stash per repository, shared by the main checkout and every
# worktree, and the stack has no owner: another agent's `pop` takes your
# entry with no way to tell it was not theirs. Denied rather than asked,
# because for a subagent there is nobody watching the prompt.
run deny "git stash"
run deny "git stash -q"
run deny "git stash -u"
run deny "git stash push -u -m wip"
run deny "git stash save wip"
run deny "git stash pop"
run deny "git stash apply"
run deny "git stash apply stash@{0}"
run deny "git stash drop"
run deny "git stash clear"
run deny "git stash branch tmp"
# This guard is a hard `deny` that also applies in the main checkout, so the
# two bypass classes fixed in #581 matter here more than anywhere: a
# separator flush against the subcommand, and git's global options.
run deny "git stash drop;"
run deny "git stash;"
run deny "git stash&&echo x"
run deny "git stash pop;echo x"
run deny "git -C sub stash pop"
run deny "git -C sub stash"
run deny "git -c core.x=1 stash drop"
run deny "git --no-pager stash apply"
# `import` (git >= 2.50) rewrites refs/stash wholesale.
run deny "git stash import https://example.com/bundle"
# A shell keyword sits exactly where `nohup` sits, and a loop over worktrees
# is the shape this guard exists for. Without keywords in the prefix these
# produced no decision at all -- which inside a worktree means allow.
run deny "for d in */; do git stash; done"
run deny "if true; then git stash; fi"
run deny "while read -r d; do git stash pop; done"
run deny "eval git stash"
# Reads are fine, and so is the WIP-commit alternative it points people to.
run allow "git stash list"
run allow "git stash show -p"
# The bare-`git stash` branch must not swallow the space before a read-only
# subcommand: its terminator is a separator or end of string, never a space.
run allow "git stash list;"
run allow "git stash list && git status"
run allow "git -C sub stash show"
run allow "git add -A && git commit -m 'wip: set aside'"
run allow "git reset --soft HEAD~1"
run allow "grep -rn 'git stash' docs/"

echo "== settings.json denials stay denials =="
# A hook decision supersedes a settings rule, so "ask" here would downgrade
# a hard block on destroying the shared podman VM to one keystroke.
run deny "podman machine rm"
run deny "podman system reset"
run allow "podman ps"

echo "== elevated privileges =="
run ask "sudo rm -rf /"
run allow "grep -rn 'sudo ' docs/"

echo "== autonomy inside the worktree is preserved =="
run allow ".venv/bin/pytest -m 'not slow'"
run allow "rm -rf .venv && python3 -m venv .venv"
run allow "npm ci"
run allow "git merge origin/main"
run allow "git reset --hard HEAD~1"
run allow "git rebase origin/main"
run allow "pytest 2>&1 | tee test.log"
run allow "npm run build > /dev/null"
run allow "cd $WT/frontend && npm run lint"
run allow "sed -i '' s/a/b/ backend/app.py"
run allow "mkdir -p docs/newdir"
run allow "echo hi > out.txt"
run allow "rm -rf /tmp/scratch"

echo "== a command prefix must not shift the command word out of the guards =="
# One env assignment used to defeat EVERY anchored guard at once, turning a
# settings.json deny into a silent allow.
run deny "PODMAN=1 podman machine rm"
run deny "env podman system reset"
run ask  "GIT_SSH_COMMAND=ssh git push origin main"
run ask  "nohup gh pr merge 561"
run ask  "time sudo rm -rf /"
run ask  "PYTHONPATH=. sudo rm -rf /"
# ...while an env prefix on ordinary work stays allowed.
run allow "PYTHONPATH=. .venv/bin/pytest -q"
run allow "TZ=UTC .venv/bin/pytest -q"

echo "== git global options must not slip past the push guard =="
run ask "git -C sub push origin main"
run ask "git --git-dir=sub/.git push origin main"
run ask "git -c push.default=matching push origin main"
run allow "git -C sub push origin feat/x"

echo "== the refspec scan is scoped to the push's own arguments =="
# A `main` elsewhere in a compound must not turn a safe push into a prompt.
run allow "git push -u origin feat/x && gh pr create --draft --base main --title x"
run allow "git commit -m 'fix main crash' && git push origin feat/x"
run ask   "git commit -m 'x' && git push origin main"

echo "== state shared across worktrees: config, remotes =="
# The stash moved to its own section above -- it is denied outright now,
# and denied in the main checkout too, so it is no longer an "ask" here.
run ask "git config --global user.email x@y.z"
run ask "git remote set-url origin git@github.com:other/repo.git"
run ask "git remote remove origin"
run allow "git config --get user.email"

echo "== a separator flush against the command word still terminates it =="
# Every guard used to end in `([[:space:]]|$)`, which sees a SPACE or end of
# string and nothing else. A `;` or `&&` written without a space before it is
# neither, so each of these was AUTO-ALLOWED while its spaced spelling asked
# -- the same bypass in every guard at once, reachable by deleting one space.
run deny "git stash drop;"
run deny "git stash drop; echo x"
run deny "git stash clear;"
run ask "git gc;"
run ask "git gc&&echo x"
run ask "git worktree prune;"
run ask "git worktree prune&&echo x"
run ask "git tag -d v1&&echo x"
run ask "git update-ref refs/heads/main HEAD;"
run ask "sudo;"
run deny "podman machine rm;"
# The spaced spelling of a compound must keep asking too: the guard fires on
# the stash, not on the `checkout main` that follows it.
run deny "git stash pop && git checkout main"
# ...and a terminator must not manufacture a match out of a longer word.
run allow "git stashfoo drop"
run allow "git gcfoo"

echo "== git global options must not slip past ANY guard =="
# normalise_git strips git's global options for matching, but only the push
# guard called it -- so every shared-state guard read the raw string and
# `git -C sub <anything>` walked straight through. It is applied once, up
# front, and every guard now matches the normalised form.
run deny "git -C sub stash drop"
run ask "git -C sub gc --prune=now"
run ask "git -C sub tag -d v1.0.0"
run ask "git -C sub config --global user.email x@y.z"
run ask "git -C sub remote remove origin"
run ask "git -C sub worktree prune"
run deny "git -c core.x=1 stash clear"
run ask "git --git-dir=sub/.git branch -f main HEAD"
run ask "git --no-pager -C sub reflog expire --expire=now --all"
# Normalisation is anchored like CMD_START, so a separator with no space
# after it does not hide the `git` that follows.
run ask "git status;git -C sub gc"
# Ordinary work through a global option stays allowed.
run allow "git -C sub status --short"
run allow "git -C sub stash list"

echo "== another repository is governed by none of this =="
# Everything the hook knows -- one shared refs/stash, ~20 worktrees, a shared
# podman VM -- is true of THIS repository. In an unrelated clone it must be
# silent, stash included: a hard deny with no override there is a wall, not a
# guard. (Verified in review by cloning a third-party repo and running
# `git stash` in it.)
FOREIGN="$TMP/foreign"
git init -q "$FOREIGN"
for foreign_cmd in "git stash" "git stash pop" "rm -rf .venv" "podman machine rm"; do
  foreign_decision=$(printf '%s' "$foreign_cmd" | jq -Rn '{tool_input: {command: input}}' \
    | (cd "$FOREIGN" && bash "$HOOK") | jq -r 'if .continue then "fallthrough" else "DECIDED" end')
  if [ "$foreign_decision" = "fallthrough" ]; then
    printf 'ok    %-5s %s\n' "none" "$foreign_cmd (from an unrelated repo)"
  else
    printf 'FAIL  got=%-12s want=%-6s %s\n' "$foreign_decision" "none" "$foreign_cmd (from an unrelated repo)"
    failures=$((failures + 1))
  fi
done

echo "== the main checkout keeps its own rules =="
# In the main checkout the hook must stay silent so settings.json applies
# unchanged -- an allow there would be the worst possible failure.
main_decision=$(printf '%s' "rm -rf .venv" | jq -Rn '{tool_input: {command: input}}' \
  | (cd "$MAIN" && bash "$HOOK") | jq -r 'if .continue then "fallthrough" else "DECIDED" end')
if [ "$main_decision" = "fallthrough" ]; then
  printf 'ok    %-5s %s\n' "none" "rm -rf .venv (from the main checkout)"
else
  printf 'FAIL  got=%-12s want=%-6s %s\n' "$main_decision" "none" "rm -rf .venv (from the main checkout)"
  failures=$((failures + 1))
fi

# ...with exactly one exception, and it is the reason the stash check sits
# above the worktree gate: refs/stash is shared repo-wide, so the main
# checkout is one of the checkouts racing for it.
main_stash=$(printf '%s' "git stash pop" | jq -Rn '{tool_input: {command: input}}' \
  | (cd "$MAIN" && bash "$HOOK") | jq -r '.hookSpecificOutput.permissionDecision // "fallthrough"')
if [ "$main_stash" = "deny" ]; then
  printf 'ok    %-5s %s\n' "deny" "git stash pop (from the main checkout)"
else
  printf 'FAIL  got=%-12s want=%-6s %s\n' "$main_stash" "deny" "git stash pop (from the main checkout)"
  failures=$((failures + 1))
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "all checks passed"
else
  echo "$failures check(s) failed"
fi
exit $((failures > 0))
