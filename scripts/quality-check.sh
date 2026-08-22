#!/bin/bash

# Quality Check Script for BESS Manager
# Run this script before committing to ensure all files meet quality standards

set -e

echo "🔍 Running BESS Manager Quality Checks..."
echo "========================================"

# Check if we're in the right directory
if [ ! -f "CLAUDE.md" ]; then
    echo "❌ Error: Run this script from the project root directory"
    exit 1
fi

# Initialize counters
ERRORS=0
WARNINGS=0

# Resolve a Python tool: the project venv first, then PATH. Prints nothing and
# returns 1 when the tool is available in neither.
#
# The venv lookup matters because the documented way to run anything here is
# `.venv/bin/<tool>` (see CLAUDE.md) — a fresh git worktree has a .venv but
# usually no activated shell, so a bare `command -v pytest` finds nothing.
#
# A missing tool is an ERROR, not a warning: this script is the pre-commit
# gate, and skipping its three most important checks while printing
# "Errors: 0" reports success for a run that verified nothing. That is exactly
# how Black violations reached CI from a fresh worktree.
py_tool() {
    if [ -x ".venv/bin/$1" ]; then
        echo ".venv/bin/$1"
    elif command -v "$1" >/dev/null 2>&1; then
        echo "$1"
    else
        return 1
    fi
}

echo ""
echo "📋 Running Python tests..."
echo "---------------------------"

if PYTEST=$(py_tool pytest); then
    echo "🔸 Running fast tests (use '$PYTEST' directly to include slow algorithm tests)..."
    if [ "${BESS_HEADLESS_MODE:-0}" = "1" ]; then
        # test_agent_permissions.py pins the HOST .claude/settings.json profile,
        # which a dispatched container replaces with container/agent-settings.json
        # (bypassPermissions by design -- the container is the boundary). The pins
        # do not apply there, so exclude the file.
        PYTEST_IGNORE_PERM="--ignore=backend/tests/test_agent_permissions.py"
    fi
    if ! "$PYTEST" -m "not slow" --tb=short -q ${PYTEST_IGNORE_PERM:-}; then
        echo "❌ Tests failed"
        ERRORS=$((ERRORS + 1))
    else
        echo "✅ Fast tests passed"
    fi
else
    echo "❌ pytest not found in .venv/bin or on PATH — cannot verify tests."
    echo "   Install with: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📋 Checking Python code quality..."
echo "-----------------------------------"

# Black and Ruff violations are ERRORs, not warnings: both are hard CI
# failures, so a gate that reports them as warnings and still exits 0 sends
# code to CI that is already known to fail.
#
# Check if Python files exist
if find . -name "*.py" -not -path "./build/*" -not -path "./.venv/*" -not -path "./frontend/node_modules/*" | grep -q .; then
    # Run Black formatting check
    if BLACK=$(py_tool black); then
        echo "🔸 Checking Black formatting..."
        if ! "$BLACK" --check . --exclude="/(build|\.venv|node_modules)/" >/dev/null 2>&1; then
            echo "❌ Black formatting issues found. Run: $BLACK ."
            ERRORS=$((ERRORS + 1))
        else
            echo "✅ Black formatting OK"
        fi
    else
        echo "❌ Black not found in .venv/bin or on PATH — cannot verify formatting."
        echo "   Install with: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
        ERRORS=$((ERRORS + 1))
    fi

    # Run Ruff linting check
    if RUFF=$(py_tool ruff); then
        echo "🔸 Checking Ruff linting..."
        if ! "$RUFF" check . --exclude="build,.venv,node_modules" >/dev/null 2>&1; then
            echo "❌ Ruff linting issues found. Run: $RUFF check --fix ."
            ERRORS=$((ERRORS + 1))
        else
            echo "✅ Ruff linting OK"
        fi
    else
        echo "❌ Ruff not found in .venv/bin or on PATH — cannot verify linting."
        echo "   Install with: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
        ERRORS=$((ERRORS + 1))
    fi
    # mypy, scoped to files this branch actually changed.
    #
    # `docs/agents/rules.md` requires mypy to pass, but nothing ran it: not
    # this gate, not CI, and it was not even in requirements-dev.txt. Turning
    # it on repo-wide is not an option — a measured 2914 errors across 191
    # files, 417 of them outside tests. So the rule is enforced going forward
    # instead of retroactively: code you touch must type-check, and the legacy
    # backlog burns down as files get edited.
    #
    # Three sources, because each misses something the others catch:
    # committed-on-this-branch, uncommitted-but-tracked, and untracked. The
    # last one matters most — a brand-new file is untracked until its first
    # commit, and this gate is meant to run BEFORE that commit. Leaving it out
    # let a probe file with a known error pass the gate silently.
    #
    # A file deleted on this branch still appears in the diff, hence the -e
    # test. No changed Python files is a pass, not a skip-with-warning.
    #
    if MYPY=$(py_tool mypy); then
        echo "🔸 Checking mypy on changed files..."
        # Delegated so CI and this script run byte-identical logic. The
        # script owns merge-base resolution, file collection and the
        # baseline comparison -- see scripts/mypy-changed.sh for why it is a
        # ratchet rather than a clean-files check. Exit 2 (setup failure,
        # e.g. an unresolvable main) is an ERROR here for the same reason an
        # unresolvable base always was: a run that type-checked nothing must
        # not report success.
        # Resolved against this script's own location, not the cwd: the
        # gate is run from the repo root in practice but not in its tests,
        # and a cwd-relative path silently turns "gate passed" into "gate
        # never ran".
        if ! "$(dirname "${BASH_SOURCE[0]}")/mypy-changed.sh" "$MYPY" --include-worktree; then
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo "❌ mypy not found in .venv/bin or on PATH — cannot verify types."
        echo "   Install with: .venv/bin/pip install -r requirements-dev.txt"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "ℹ️  No Python files found to check"
fi

echo ""
echo "📋 Checking TypeScript code quality..."
echo "--------------------------------------"

# Check if TypeScript files exist in frontend
if [ -d "frontend" ] && find frontend/src -name "*.ts" -o -name "*.tsx" 2>/dev/null | grep -q .; then
    cd frontend
    
    # Check if package.json exists
    if [ -f "package.json" ]; then
        # Run frontend tests
        if command -v npm >/dev/null 2>&1; then
            echo "🔸 Running frontend tests..."
            if npm test 2>/dev/null; then
                echo "✅ Frontend tests passed"
            else
                echo "❌ Frontend tests failed"
                ERRORS=$((ERRORS + 1))
            fi

            echo "🔸 Checking TypeScript compilation..."
            if npm run type-check >/dev/null 2>&1; then
                echo "✅ TypeScript compilation OK"
            else
                echo "⚠️  TypeScript compilation issues found. Run: npm run type-check"
                WARNINGS=$((WARNINGS + 1))
            fi
            
            # Check ESLint
            echo "🔸 Checking ESLint..."
            if npm run lint >/dev/null 2>&1; then
                echo "✅ ESLint OK"
            else
                echo "⚠️  ESLint issues found. Run: npm run lint:fix"
                WARNINGS=$((WARNINGS + 1))
            fi
        else
            echo "⚠️  npm not installed. Install Node.js and npm"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        echo "⚠️  No package.json found in frontend directory"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    cd ..
else
    echo "ℹ️  No TypeScript files found to check"
fi

echo ""
echo "📋 Checking permission surface..."
echo "-------------------------------------------"

# Replaces the hook-matrix gate deleted with the hooks (#588). verify-sandbox.sh
# cannot fill that role -- it exits 2 unless the Bash tool runs it in a
# sandboxed session, so it can never be a CI or pre-commit check. What IS
# statically checkable is that the rules which stand in for the deleted hooks
# are still present. Every entry below was a real regression at some point:
# option-first `git stash` forms fell through to `auto` because the deny list
# enumerated literal subcommands, and the GitHub-publishing guards were dropped
# entirely -- effects the sandbox cannot contain, since it bounds the
# filesystem, not the network.
# `if ! ...` is load-bearing: `set -e` (line 6) aborts the whole script on a
# bare failing statement, so a plain heredoc here would skip the ERRORS
# increment, the checks below it, AND the final summary -- a missing rule would
# stop the run mid-file with no verdict, which is the opposite of a gate.
#
# These assertions validate the repo's committed .claude/settings.json. A
# dispatched container shadows that file with container/agent-settings.json --
# bypassPermissions by design, since the container is the boundary -- so the
# assertions do not apply there. They still run on the host, where they matter.
if [ "${BESS_HEADLESS_MODE:-0}" = "1" ]; then
    echo "⏭️  Skipping permission-surface check (headless container mode)"
elif ! python3 - <<'PY'
import json, re, sys

# Patterns match the command AS WRITTEN -- prefix globbing, no normalisation.
#
# `gh api` USED to be pinned here by spelling: this list demanded the literal
# `Bash(gh api)` / `Bash(gh api *)` blanket rules, on the grounds that the
# dangerous shapes put their marker at an arbitrary argument position
# (`gh api <path> -X PUT`, `gh api <path> -f k=v`) which a prefix glob cannot
# reach. #657 replaced that blanket with an enumeration of the write flags, to
# stop `gh api` reads prompting on every call -- and this gate then failed on
# a clean `origin/main`, because the strings it demanded were gone while the
# PROPERTY it cared about still held.
#
# Pinning a spelling was the wrong assertion. What matters is that a `gh api`
# WRITE cannot reach `allow`, not which rule stops it -- and that is already
# asserted below, by command string, in MUST_BE_GUARDED. Those entries survive
# any future respelling; the literal ones did not.
#
# The enumeration's real risk is a write flag nobody listed. That is not
# hypothetical: `-F, --field` and `-f, --raw-field` (see `gh api --help`) had
# only their SHORT forms enumerated, so `gh api <path> --field k=v` resolved to
# `allow` -- a write that never prompted. Both long forms are pinned below now.
# When adding a `gh api` write flag, add its command string there too, or the
# next respelling re-opens the same hole silently.
#
# `git push` USED to be in that same sentence and no longer is. It was never
# the glob that made it safe -- the glob was a blunt instrument compensating
# for having no guard at the only layer that can actually see a ref update.
# The four leaks it was blanket-guarding against are now refused SERVER-SIDE
# by GitHub rulesets, which evaluate the resulting ref rather than the command
# string, so argument order cannot evade them:
#
#   git push origin main --force        -> non_fast_forward on ~DEFAULT_BRANCH
#   git push origin +beta-release-9.9   -> non_fast_forward on beta-release-*
#   git push origin +release-9.9        -> non_fast_forward on release-*
#   git push origin --delete <ref>      -> deletion on both of the above
#   git push origin v9.9.0 (force/move) -> non_fast_forward on ~ALL tags
#
# All rulesets are enforcement=active with an EMPTY bypass_actors list, so
# they bind the repo owner too -- which matters, because local pushes
# authenticate as the owner (osxkeychain), never as bess-agent.
#
# Do NOT re-add a `Bash(git push*)` ask on the grounds that "a guard is
# missing". Check the rulesets first:
#
#   gh api repos/johanzander/bess-manager/rulesets
#   gh api repos/johanzander/bess-manager-beta/rulesets
#
# What this deliberately does NOT cover: force-pushing or deleting a FEATURE
# branch (fix/**, feat/**) on origin. An accepted residual -- but NOT because
# "the damage is bounded to your own unmerged branch". ~20 worktrees push in
# parallel as the same identity, so a misaimed --force destroys another agent's
# commits and closes its PR, with the recovering reflog sitting in a different
# worktree.
#
# Every entry below is a rule whose deletion is the exact regression this gate
# was written for -- the GitHub-reaching and history-destroying guards. Keep
# this list in sync with the ask/deny lists; a rule absent from here is a rule
# that can be silently removed.
REQUIRED = {
    "deny": [
        "Bash(git stash -*)", "Bash(git stash --*)", "Bash(git stash)",
        "Bash(git -* stash)", "Bash(git -* stash pop*)",
        "Bash(git -* stash drop*)", "Bash(git -* stash clear*)",
        "Bash(podman machine rm)", "Bash(podman system reset)",
    ],
    "ask": [
        "Bash(gh pr merge*)", "Bash(gh repo edit*)",
        "Bash(gh release create*)", "Bash(gh release edit*)",
        "Bash(gh release delete*)", "Bash(gh release delete-asset*)",
        "Bash(gh release upload*)",
        "Bash(gh repo delete*)", "Bash(gh secret*)", "Bash(gh workflow run*)",
        "Bash(git gc*)", "Bash(git prune*)", "Bash(git repack*)",
        "Bash(git maintenance*)",
        "Bash(git reflog expire*)", "Bash(git reflog delete*)",
        "Bash(git update-ref*)",
        "Bash(git tag -d*)", "Bash(git tag --delete*)", "Bash(git tag -f*)",
        "Bash(sudo *)",
    ],
}

# Presence checks alone kept passing while real command spellings slipped
# through -- four review rounds of the same class of bug. So also assert, per
# COMMAND STRING, that something actually matches it. Patterns are prefix
# globs over the command as written, which is the semantics that keeps
# surprising people: `git stash pop` is covered while `git -C x stash pop` is
# not, because the rule anchors on the literal `git stash`.
#
# Add a line here whenever a new spelling is found in the wild. A rule that
# looks right and matches nothing is the failure mode this exists to catch.
# MUST_BE_DENIED is checked against `deny` ONLY. Checking these against
# deny+ask would certify a one-keystroke `ask` for commands policy says are
# unapprovable -- and that is not hypothetical: an earlier `Bash(git -*)` ask
# matched `git -C x stash pop` while no deny did, silently downgrading the
# stash prohibition to a prompt, and a deny+ask gate reported it green.
MUST_BE_DENIED = [
    # Every mutating stash form, in both plain and global-option spellings.
    # `clear` and `drop` destroy other agents' entries irreversibly.
    "git stash", "git stash push", "git stash push -u", "git stash save wip",
    "git stash pop", "git stash apply", "git stash apply stash@{0}",
    "git stash drop", "git stash drop stash@{1}", "git stash clear",
    "git stash branch tmp", "git stash store abc123", "git stash create",
    "git stash -u", "git stash --include-untracked",
    "git -C ../bess-manager-feature stash pop",
    "git -C .claude/worktrees/x stash drop",
    "git --git-dir=/tmp/r/.git stash drop",
    # The shared podman VM: destruction is unrecoverable and outside the sandbox.
    "podman machine rm", "podman system reset",
]

# Checked against deny + ask: a prompt is an acceptable outcome for these.
MUST_BE_GUARDED = [
    # git's global options may precede the subcommand -- the hook this
    # replaced normalised for exactly this, and local-agent-environment.md
    # teaches `git -C` as
    # the cross-checkout idiom, so it is the spelling most likely to be used.
    "git --no-pager gc --prune=now",
    "git -C sub tag -d v9.9.0",
    "git -C sub update-ref -d refs/heads/x",
    # history destruction, incl. the spellings that are NOT `gc`/`reflog expire`
    "git tag --delete v9.9.0", "git tag -d v9.9.0",
    "git tag -f v9.9.0 abc123",
    "git reflog expire --expire=now --all", "git reflog delete HEAD@{0}",
    "git gc --prune=now", "git prune", "git repack -d",
    "git maintenance run --task=gc",
    "git update-ref -d refs/tags/v9.9.0",
    # gh reaching GitHub, including the raw API path
    "gh api repos/o/r/pulls/1/merge -X PUT",
    "gh api repos/o/r/releases -f tag_name=v1",
    # Long forms of the two field flags. Enumerating only `-f`/`-F` left these
    # reaching `allow`; see the REQUIRED comment above.
    "gh api repos/o/r/releases --field tag_name=v1",
    "gh api repos/o/r/releases --raw-field tag_name=v1",
    "gh api --field tag_name=v1 repos/o/r/releases",
    "gh api --raw-field tag_name=v1 repos/o/r/releases",
    # Attached-value spellings. cobra/pflag takes `--flag=value`, `-fvalue`
    # and `-f=value` as readily as `--flag value`, and a glob ending in
    # ` --field ` (with a space) cannot reach them -- a write that resolves to
    # `allow` by the same argument the long-form pins above were added for.
    "gh api repos/o/r/releases --field=tag_name=v1",
    "gh api repos/o/r/releases --raw-field=tag_name=v1",
    "gh api --field=tag_name=v1 repos/o/r/releases",
    "gh api --raw-field=tag_name=v1 repos/o/r/releases",
    "gh api repos/o/r/pulls/1/merge --method=PUT",
    "gh api --method=PUT repos/o/r/pulls/1/merge",
    "gh api repos/o/r/pulls/1/merge -XPUT",
    "gh api -XPUT repos/o/r/pulls/1/merge",
    "gh api repos/o/r/releases -fbody=hi",
    "gh api -fbody=hi repos/o/r/releases",
    "gh api repos/o/r/releases -Fbody=hi",
    "gh api -Fbody=hi repos/o/r/releases",
    "gh pr merge 588 --squash",
    # Publishing a release escapes to GitHub irreversibly. The read-only verbs
    # are exempt (see MUST_NOT_BE_GUARDED) -- the gate pins both directions so
    # the split cannot silently collapse back to a blanket rule or a hole.
    "gh release create v9.9.0", "gh release create v9.9.0 -R owner/repo",
    "gh release edit v9.9.0 --draft=false",
    "gh release delete v9.9.0 --yes",
    "gh release delete-asset v9.9.0 addon.zip",
    "gh release upload v9.9.0 addon.zip",
    "gh secret set FOO", "gh workflow run ci.yml", "gh repo edit --visibility private",
    # Unrecoverable gh mutations. `gh repo delete` was unguarded while the far
    # milder `gh repo edit` asked -- it escapes to GitHub and git cannot undo
    # it, which is this file's stated standard for the ask list.
    "gh repo delete owner/repo --yes", "gh pr close 1",
    "gh issue delete 1", "gh cache delete --all",
    "sudo rm -rf /",
]

# NOT modelled here, deliberately:
#
# * COMPOUND COMMANDS. `cd frontend && git push origin main` matches nothing in
#   this matcher, because matches() emulates a single command string. The
#   harness decomposes on &&/;/| before applying rules, so the real decision is
#   made on `git push origin main` -- do not "fix" this by adding compound
#   entries here; they would fail against a matcher that is correct for what it
#   models. Verifying the decomposition claim needs a live permission test, not
#   this gate.
# * GREEDY GLOBS. `*` compiles to `.*`, which spans spaces, so `git -* push*`
#   also matches e.g. a commit whose MESSAGE contains " push". That is a false
#   PROMPT, not a hole, and it is accepted: the alternative is dropping the
#   global-option guard on push, which is a real bypass. Precision here is
#   bounded by prefix globbing -- when the choice is between an extra prompt
#   and a gap, take the prompt.

# Read-only git must NOT be caught: an autonomous run executing rules.md's
# cross-checkout procedure (`git diff -- f | git -C <wt> apply`, then
# `git -C <wt> diff -- f` to verify) would otherwise stall on inspection
# commands. A blanket `Bash(git -*)` did exactly that, which is why the
# global-option rules name a verb.
MUST_NOT_BE_GUARDED = [
    "git -C sub status --short",
    "git --no-pager log --oneline -5",
    "git -C .claude/worktrees/x diff -- file.py",
    "git -C .claude/worktrees/x apply",
    "git status", "git diff", "git log --oneline",
    # Pushing. Enforcement moved to GitHub rulesets (see the REQUIRED comment
    # above), so these must run UNATTENDED -- implement-issue Step 9 and every
    # PR-refresh push. Pinned in this direction on purpose: the failure mode
    # being guarded against is someone re-adding a `Bash(git push*)` ask
    # because it "looks unguarded", which would silently restore the stall the
    # rulesets were created to remove. If you believe a guard is missing, read
    # the rulesets before touching this list.
    #
    # These entries assert only that the commands are LOCALLY unguarded. Which
    # of them GitHub also refuses is a separate question, and the answer is not
    # "all of them" -- do not read this list as a protection matrix:
    #
    #   main --force, +beta-release-*, v9.9.0 (tag)  -> refused by a ruleset
    #   +release-X.Y (rewrite)                       -> refused by a ruleset
    #   --delete release-X.Y                         -> ALLOWED, deliberately
    #
    # That last line is a deliberate asymmetry, not a residual and not an
    # oversight to "fix" by putting the prompt back. `release-X.Y` is the
    # short-lived hotfix branch created by the release skill (steps 2-6);
    # rewriting it is refused by the `release-*` ruleset, while deleting it
    # once the release is out is ordinary cleanup. The protected TAG pins the
    # released commit, so a spent branch costs nothing to lose.
    "git push", "git push -u origin main",
    "git push origin main --force",
    "git push origin +beta-release-9.9",
    "git push origin --delete release-9.9",
    "git push origin v9.9.0",
    "git -C .claude/worktrees/x push origin main",
    "git -c push.default=current push beta main",
    # Read-only stash inspection, which local-agent-environment.md and
    # rules.md both promise
    # keeps working. A blanket `git -* stash *` DENY caught these, and deny has
    # no override -- so the cross-checkout recipe was hard-blocked, not merely
    # prompted. That is why the stash twins name a verb.
    "git stash list", "git stash show",
    "git -C sub stash list",
    "git -C .claude/worktrees/x stash show",
    # implement-issue Step 4 prunes worktrees in a loop;
    # local-agent-environment.md argues that
    # must stay unattended. A `git -* prune*` twin caught `worktree prune` and
    # `remote prune` through the same greedy glob, so the twin was dropped.
    "git -C /main worktree prune", "git worktree prune",
    "git -C sub remote prune origin",
    # Reading releases changes nothing on GitHub, and the release/beta flows
    # check the published version constantly ("always check the current
    # published version before tagging"). A blanket `gh release*` ask made
    # every one of those a prompt, which is why these verbs are named.
    "gh release list -L 5 -R johanzander/bess-manager-beta",
    "gh release list", "gh release view v9.9.0",
    "gh release view --json tagName",
]


def matches(pattern: str, command: str) -> bool:
    """Prefix-glob match over the raw command, mirroring the documented rules."""
    inner = pattern[len("Bash(") : -1] if pattern.startswith("Bash(") else pattern
    return re.fullmatch(re.escape(inner).replace(r"\*", ".*"), command) is not None


perms = json.load(open(".claude/settings.json"))["permissions"]
bad = [(k, p) for k, ps in REQUIRED.items() for p in ps if p not in perms.get(k, [])]
for k, p in bad:
    print(f"❌ permissions.{k} is missing {p}")

denies = perms.get("deny", [])
guards = denies + perms.get("ask", [])

for cmd in MUST_BE_DENIED:
    if not any(matches(p, cmd) for p in denies):
        why = " (only an ask matches -- deny > ask, so this is a prompt, not a block)" \
            if any(matches(p, cmd) for p in guards) else ""
        print(f"❌ no DENY rule matches: {cmd}{why}")
        bad.append(("deny", cmd))

for cmd in MUST_BE_GUARDED:
    if not any(matches(p, cmd) for p in guards):
        print(f"❌ no deny/ask rule matches: {cmd}")
        bad.append(("ask", cmd))

for cmd in MUST_NOT_BE_GUARDED:
    hit = [p for p in guards if matches(p, cmd)]
    if hit:
        print(f"❌ read-only command is gated by {hit[0]}: {cmd}")
        bad.append(("ask", cmd))

if bad:
    sys.exit(1)
total = len(MUST_BE_DENIED) + len(MUST_BE_GUARDED) + len(MUST_NOT_BE_GUARDED)
print(f"✅ Permission surface intact ({total} command shapes checked, "
      f"{len(MUST_BE_DENIED)} require deny, {len(MUST_NOT_BE_GUARDED)} must stay unattended)")
PY
then
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📋 Checking bot workflow publish contract..."
echo "-------------------------------------------"

# Stage 2 (issue-analyze.yml) spent three days exiting `success` while posting
# nothing -- five of nine non-skipped runs produced no comment and no label,
# burning $0.33-1.58 each (#646). Every layer reported healthy: the run was
# green, is_error false, permission_denials_count 0.
#
# Two independent things have to hold, and this gate checks BOTH because either
# one alone leaves the failure silent:
#
#   1. The prompt must tell the agent to RUN a command to publish. Stage 2 said
#      "Post ONE comment on the issue with this structure:" followed by a
#      markdown template -- a description of a document, not an instruction to
#      execute anything. These workflows run in AGENT mode (use_sticky_comment
#      false, track_progress false), so the action posts nothing on the agent's
#      behalf: an agent that renders the template as its final assistant message
#      has, by its own lights, finished. It then never reaches the labelling
#      step, which is why the label was untouched too.
#
#      The contrast is what makes this more than a story. On the SAME action
#      version (459ad358 / CLI 2.1.234), Stage 4's review -- whose prompt names
#      `gh pr review` explicitly -- landed an APPROVED verdict, while Stage 2
#      went silent three times in three seconds. Stage 2 was the only bot
#      workflow whose publish step was prose, and the only one that failed to
#      publish.
#
#   2. The workflow must VERIFY it afterwards. The prompt fix is a behavioural
#      argument about what a model will infer, so it cannot be trusted on its
#      own -- the next upstream version may infer differently, exactly as this
#      one did. Only a post-condition on the job makes that loud instead of
#      green.
#
# Deliberately NOT checked for, and deliberately not built: a step that posts
# the comment on the agent's behalf when it didn't. That is a second publishing
# path whose only job is to route around the first one failing, and it would
# mask the regression rather than surface it (docs/agents/rules.md, Debugging
# Protocol step 8). The guard asserts; it does not repair.
if ! python3 - <<'PY'
import pathlib, re, sys

WORKFLOWS = pathlib.Path(".github/workflows")

# Workflows whose whole product is a comment on the issue. Stage 3 is excluded
# on purpose: its product is a PR, which is observable without this check.
PUBLISHERS = {
    "issue-triage.yml": "gh issue comment",
    "issue-analyze.yml": "gh issue comment",
}

bad = []

for name, command in PUBLISHERS.items():
    path = WORKFLOWS / name
    if not path.is_file():
        print(f"❌ {name} is missing -- the publish contract cannot be checked")
        bad.append(name)
        continue
    if command not in path.read_text():
        print(
            f"❌ {name} never names `{command}`. Its publish step is prose, so "
            "the agent can render it as a final message and exit success "
            "having written nothing to GitHub (#646)."
        )
        bad.append(name)

# The post-agent guard: a run that published nothing must fail the job. Checked
# by the shape that actually does the work -- a step keyed on `if: always()`
# that re-reads the issue -- rather than by step name, which renames freely.
analyze = WORKFLOWS / "issue-analyze.yml"
if analyze.is_file():
    text = analyze.read_text()
    has_always = re.search(r"^\s*if:\s*always\(\)\s*$", text, re.MULTILINE)
    has_readback = "--json comments" in text and "--json labels" in text
    if not (has_always and has_readback):
        print(
            "❌ issue-analyze.yml has no post-agent verification step. A run "
            "that posts no comment and applies no label must FAIL the job, "
            "not exit success (#646 acceptance criterion)."
        )
        bad.append("issue-analyze.yml:guard")

if bad:
    sys.exit(1)
print(f"✅ Bot workflow publish contract intact ({len(PUBLISHERS)} publishers "
      "name their command, Stage 2 verifies it posted)")
PY
then
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📋 Checking bot workflow context contract..."
echo "-------------------------------------------"

# A workflow prompt must not tell its MAIN agent to read a `.claude/agents/*.md`
# file. Those files are sub-agent system prompts: the sub-agent already has one
# in full, so naming it as the main agent's REQUIRED READING loads a second copy
# into a different context window, on every turn, for an agent that never runs
# the procedure it describes.
#
# Stage 2 did exactly that with bess-analyst.md (25,681 B) and nothing consumed
# it (#654). Its six steps are: get context, identify the current problem,
# delegate, verify the cited file:line, publish, label -- no step applies a
# "domain expertise checklist". Worse, the section of that file which could
# plausibly serve as a judging standard (Separate Evidence from Claims) was
# already restated inline in the sub-agent task the same prompt passes, so the
# content was loaded three times over.
#
# The paired assertion matters as much as the removal: Stage 2 must still
# DELEGATE. Dropping the read is the saving; dropping the delegation would gut
# the stage, and the same "trim the prompt" instinct reaches for both.
if ! python3 - <<'PY_CTX'
import re, sys, pathlib

WF = pathlib.Path(".github/workflows")
bad = []

for f in sorted(set(WF.glob("*.yml")) | set(WF.glob("*.yaml"))):
    text = f.read_text()
    for i, line in enumerate(text.splitlines(), 1):
        # Match the shape the regression actually takes: a NUMBERED entry in a
        # reading list, e.g. "3. .claude/agents/bess-analyst.md — checklist".
        # Deliberately narrow. A prose line that merely names the path is not
        # flagged, because the prompt now carries an explicit "Do NOT read
        # .claude/agents/bess-analyst.md" note and a gate that fought its own
        # documentation would be worse than one with a known edge. An
        # unnumbered "read <path>" instruction would slip through; that is an
        # accepted narrowness, not a claim of completeness.
        if re.match(r"^\s*\d+\.\s+\.claude/agents/", line):
            bad.append(f"{f}:{i}: main agent told to read a sub-agent definition: {line.strip()}")

analyze = (WF / "issue-analyze.yml").read_text()
_, _, prompt_block = analyze.partition("prompt: |")
if not re.search(r"subagent_type[\s:`'\"]*bess-analyst", prompt_block):
    bad.append("issue-analyze.yml: Stage 2 no longer delegates to the bess-analyst "
               "sub-agent -- that delegation IS the stage")

if bad:
    for b in bad:
        print(f"   {b}")
    sys.exit(1)

print("✅ Bot workflow context contract intact (no sub-agent definition read by a "
      "main agent, Stage 2 still delegates)")
PY_CTX
then
    echo "❌ Bot workflow context contract violated"
    echo "   A sub-agent's definition is its own system prompt. Do not also list"
    echo "   it as the main agent's REQUIRED READING (#654)."
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📋 Checking agent context budget..."
echo "-------------------------------------------"

# Every bot stage loads CLAUDE.md before it does anything, on the main agent
# and again on its sub-agent, and re-sends it on every turn. It is the largest
# single item in the fixed context floor, so its size is a per-run cost on
# Stages 1-5 and on every local session.
#
# It reached 45,488 B once, of which 33,743 B (74%) was one section describing
# this machine -- the macOS sandbox, podman, worktrees, Playwright, the
# permission rules. None of it can apply on a fresh ubuntu runner under
# `--permission-mode bypassPermissions`, and it was billed on every turn of
# every stage anyway (#650).
#
# The fix was to RELOCATE that content, not delete it: it lives in
# docs/agents/local-agent-environment.md and is reached through the Agent
# Documentation Index like every other doc. This gate keeps it from creeping
# back inline. If you need to raise the cap, move content into docs/agents/
# and link it instead -- that is the mechanism CLAUDE.md already uses.
CLAUDE_MD_MAX_BYTES=16000
CLAUDE_MD_BYTES=$(wc -c < CLAUDE.md | tr -d ' ')

if [ "$CLAUDE_MD_BYTES" -gt "$CLAUDE_MD_MAX_BYTES" ]; then
    echo "❌ CLAUDE.md is ${CLAUDE_MD_BYTES} B, over the ${CLAUDE_MD_MAX_BYTES} B budget"
    echo "   Every bot stage loads this file on every turn, on two agents."
    echo "   Move the new material into docs/agents/ and link it from the"
    echo "   Agent Documentation Index rather than raising the cap (#650)."
    ERRORS=$((ERRORS + 1))
else
    echo "✅ CLAUDE.md within context budget (${CLAUDE_MD_BYTES} B / ${CLAUDE_MD_MAX_BYTES} B)"
fi

echo ""
echo "📋 Checking scenario discovery coverage..."
echo "-------------------------------------------"

SCENARIO_DIR="scripts/mock_ha/scenarios"
MISSING_DISCOVERY=0
if [ -d "$SCENARIO_DIR" ]; then
    for f in "$SCENARIO_DIR"/ci-wizard-*.json; do
        name=$(basename "$f")
        if ! python3 -c "import json,sys; sys.exit(0 if 'expected_discovery' in json.load(open('$f')) else 1)" 2>/dev/null; then
            echo "❌ $name is missing expected_discovery section"
            MISSING_DISCOVERY=$((MISSING_DISCOVERY + 1))
        fi
    done
    if [ $MISSING_DISCOVERY -eq 0 ]; then
        echo "✅ All ci-wizard-* scenarios have expected_discovery"
    else
        echo "❌ $MISSING_DISCOVERY scenario(s) missing expected_discovery — add assertions before releasing"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "ℹ️  No scenario directory found"
fi

echo ""
echo "📋 Checking Markdown files..."
echo "------------------------------"

# Find project markdown files (exclude node_modules, build, .venv)
MD_FILES=$(find . -name "*.md" -not -path "./node_modules/*" -not -path "./build/*" -not -path "./.venv/*" -not -path "./frontend/node_modules/*" -not -path "./.git/*" -not -path "./.pytest_cache/*" 2>/dev/null | head -20)

if [ -n "$MD_FILES" ]; then
    echo "🔸 Found markdown files:"
    echo "$MD_FILES" | sed 's/^/  /'
    
    # Check for common markdown issues
    echo "🔸 Checking for common markdown issues..."
    
    # Check for trailing spaces
    if echo "$MD_FILES" | xargs grep -l " $" 2>/dev/null | grep -q .; then
        echo "⚠️  Files with trailing spaces found:"
        echo "$MD_FILES" | xargs grep -l " $" 2>/dev/null | sed 's/^/  /'
        WARNINGS=$((WARNINGS + 1))
    fi
    
    # Check for multiple consecutive blank lines
    if echo "$MD_FILES" | xargs grep -l "^$" 2>/dev/null | xargs grep -Pzo "\n\n\n" 2>/dev/null | grep -q .; then
        echo "⚠️  Files with multiple consecutive blank lines found"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    # Check for missing blank lines before headers
    HEADER_ISSUES=0
    for file in $MD_FILES; do
        if grep -Pzl ".*[^\n]\n#" "$file" 2>/dev/null; then
            HEADER_ISSUES=$((HEADER_ISSUES + 1))
        fi
    done
    
    if [ $HEADER_ISSUES -gt 0 ]; then
        echo "⚠️  $HEADER_ISSUES files with headers missing blank lines"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    if [ $WARNINGS -eq 0 ] || [ $HEADER_ISSUES -eq 0 ]; then
        echo "✅ Basic markdown formatting OK"
    fi
else
    echo "ℹ️  No markdown files found to check"
fi

echo ""
echo "📋 Summary"
echo "----------"
echo "Errors: $ERRORS"
echo "Warnings: $WARNINGS"

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo "🎉 All quality checks passed!"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo "⚠️  Quality checks completed with $WARNINGS warnings"
    echo "💡 Consider fixing warnings before committing"
    exit 0
else
    echo "❌ Quality checks failed with $ERRORS errors and $WARNINGS warnings"
    echo "🔧 Please fix all errors before committing"
    exit 1
fi