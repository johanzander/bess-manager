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
TMP=$(mktemp -d "${HOME}/.cache/bess-hook-test-XXXXXX") || exit 1
TMP=$(cd "$TMP" && pwd -P)
trap 'rm -rf "$TMP"' EXIT

MAIN="$TMP/main"
WT="$TMP/wt"
git init -q "$MAIN"
git -C "$MAIN" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$MAIN" worktree add -q -b testwt "$WT"

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

echo "== writes that reach the main checkout =="
run ask "sed -i '' s/a/b/ $MAIN/backend/app.py"
run ask "touch $MAIN/x"
run ask "mkdir -p $MAIN/x"
run ask "cp somefile $MAIN/somefile"
# Absolute path quoted inside an argument, not at token start.
run ask "python3 -c \"import shutil; shutil.rmtree('$MAIN')\""
# Relative traversal, redirect and rm alike.
run ask "echo x > ../../main/README.md"
run ask "rm -rf ../../main"
# Traversal out THROUGH an allowed temp prefix.
run ask "rm -rf /tmp/../$MAIN"
run ask "git -C $MAIN reset --hard"
run ask "tar -C $MAIN -xf x.tar"

echo "== state shared with the main checkout =="
# A linked worktree has its own working tree but ONE object database and
# ONE ref namespace, so these escape it even without -C.
run ask "git branch -D some-branch"
run ask "git branch --delete some-branch"
run ask "git tag -d v1.0.0"
run ask "git gc --prune=now"
run ask "git reflog expire --expire=now --all"
run ask "git worktree remove $TMP/other"
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
run allow "gh run watch 123"

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

echo
if [ "$failures" -eq 0 ]; then
  echo "all checks passed"
else
  echo "$failures check(s) failed"
fi
exit $((failures > 0))
