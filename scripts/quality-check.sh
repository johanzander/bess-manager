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
    if ! "$PYTEST" -m "not slow" --tb=short -q; then
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
if ! python3 - <<'PY'
import json, re, sys

# Patterns match the command AS WRITTEN -- prefix globbing, no normalisation.
#
# `git push` USED to be guarded by a blanket `Bash(git push *)`, justified here
# by the claim that a marker at an arbitrary argument position (`git push
# origin main --force`, `git push origin +beta-release-9.9`, `git push origin
# --delete release-X.Y`) is unreachable by a prefix glob. That claim was FALSE,
# and matches() below is the proof: `*` becomes `.*` under re.fullmatch, which
# spans spaces. So `Bash(git push *--force*)` DOES match `git push origin main
# --force`. The note further down about greedy globs said as much all along --
# the two comments contradicted each other and the blanket rule was built on
# the wrong one.
#
# The earlier enumerations leaked twice because they were prefix-ANCHORED
# (`Bash(git push --force*)`), which genuinely cannot reach position 3. The
# `*marker*` spelling can. So the guard is now per-shape: force in any
# position, refspec `+`, ref deletion, `--mirror`/`--prune`/`--tags`, release
# tags, and anything targeting main/master/beta. A push naming a feature branch
# explicitly runs unattended, which is the shape implement-issue and sweep-prs
# actually use -- a blanket ask there stalls every autonomous run for no gain,
# since branch-protection already refuses the case that matters.
#
# `gh api` keeps its blanket rule: any `-f`/`-F`/`-X` turns a read into a
# mutation, and the safe subset is not separable by shape the way push is.
#
# MUST_BE_GUARDED and MUST_NOT_BE_GUARDED below are what actually holds this
# together. Do not re-narrow by trusting rule NAMES -- add the command string.
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
        # Bare `git push` names no target, so it is guarded by NAME here. The
        # per-shape push rules are NOT listed by name on purpose: there are 52
        # of them, and pinning names would just re-create the presence-check
        # failure mode. They are held by MUST_BE_GUARDED command strings
        # instead -- deleting any one of them breaks at least one pinned
        # command, which is the check that actually catches regressions.
        "Bash(git push)",
        "Bash(gh api)", "Bash(gh api *)",
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
    # replaced normalised for exactly this, and CLAUDE.md teaches `git -C` as
    # the cross-checkout idiom, so it is the spelling most likely to be used.
    "git -c push.default=current push beta main",
    "git --no-pager gc --prune=now",
    "git -C sub tag -d v9.9.0",
    "git -C sub update-ref -d refs/heads/x",
    # The marker sits at an arbitrary argument position. Reachable by a
    # `*marker*` glob, NOT by a prefix-anchored one -- that distinction is the
    # whole reason the blanket rule could be retired. Every line here failed
    # against at least one earlier enumeration.
    "git push origin main --force",
    "git push origin main --force-with-lease",
    "git push -f origin main",
    "git push origin +beta-release-9.9",
    "git push origin --delete release-9.9",
    "git push origin v9.9.0",
    "git push origin --tags",
    "git push --mirror origin",
    "git push",
    # Refs that branch protection does NOT cover, and so are still ours to
    # guard: the beta REMOTE, and beta-release branches on origin. Only
    # `main` is protected, on either remote.
    "git push beta main",
    "git push origin HEAD:beta",
    "git push origin beta-release-v10.1.0b10-tmp",
    "git -C x push origin main --force",
    "git push origin refs/heads/beta",
    # `--all` pushes EVERY local branch, main included, and was missing while
    # its neighbours --mirror/--prune/--tags were all covered. `--branches` is
    # a synonym for it (git 2.50 `git push --help`: "--all, --branches"), so
    # enumerating one without the other would have been the next leak.
    # A TAG push, source-side. `*:refs/tags/*` only ever saw the
    # destination-side spelling, so `git push origin refs/tags/v1.2.3` -- the
    # ordinary one-sided form -- published a release tag unattended. The guard
    # is now `*refs/tags/*` without the colon, covering both sides.
    #
    # This one is guarded regardless of how the protected-BRANCH argument is
    # settled: a tag is not a branch, so branch protection never covers it, and
    # `git push origin v9.9.0` (no refs/ prefix) is not covered by this pattern
    # either -- `* v*` is what catches that, and it stays.
    "git push origin refs/tags/v1.2.3",
    "git -C x push origin refs/tags/v1.2.3",
    "git push --all",
    "git push --all origin",
    "git push --branches origin",
    "git -C x push --all origin",
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
# * GREEDY GLOBS. `*` compiles to `.*`, which spans spaces. This is what makes
#   the per-shape push rules possible at all -- `*--force*` reaches a marker at
#   any argument position -- and it is also why `git -* push *--force*` still
#   matches e.g. a commit whose MESSAGE contains " push --force". That is a
#   false PROMPT, not a hole, and it is accepted. When the choice is between an
#   extra prompt and a gap, take the prompt. The reverse trade is NOT
#   acceptable: a shape that must ask belongs in MUST_BE_GUARDED, not in a
#   comment explaining why it is fine.

# Read-only git must NOT be caught: an autonomous run executing rules.md's
# cross-checkout procedure (`git diff -- f | git -C <wt> apply`, then
# `git -C <wt> diff -- f` to verify) would otherwise stall on inspection
# commands. A blanket `Bash(git -*)` did exactly that, which is why the
# global-option rules name a verb.
MUST_NOT_BE_GUARDED = [
    # THE HEADLINE BEHAVIOUR OF THE PROTECTED-REF SHRINK, pinned. These used to
    # sit in MUST_BE_GUARDED; deleting them from there proved nothing, because
    # a list that no longer mentions a command cannot tell you whether it is
    # guarded. So the exact commands the redesign turns on are asserted to run
    # UNATTENDED -- by the same command-string method the rest of this gate
    # uses, and for the same reason: a rule that looks right and matches
    # nothing is the failure this file exists to catch.
    #
    # This is where the decision reverses. If `enforce_admins` or the blocking
    # rule ever goes away -- the branch-protection check above fires when it
    # does -- restore the `* main` / `*:main` / `*refs/heads/main*` patterns in
    # .claude/settings.json AND move these back to MUST_BE_GUARDED. They are a
    # pair; moving one without the other leaves the gate contradicting itself.
    "git push origin main",
    "git push -u origin main",
    "git push origin HEAD:main",
    "git push origin refs/heads/main",
    "git push origin master",
    "git -C x push origin main",
    "git -C sub status --short",
    "git --no-pager log --oneline -5",
    "git -C .claude/worktrees/x diff -- file.py",
    "git -C .claude/worktrees/x apply",
    "git status", "git diff", "git log --oneline",
    # Read-only stash inspection, which CLAUDE.md and rules.md both promise
    # keeps working. A blanket `git -* stash *` DENY caught these, and deny has
    # no override -- so the cross-checkout recipe was hard-blocked, not merely
    # prompted. That is why the stash twins name a verb.
    "git stash list", "git stash show",
    "git -C sub stash list",
    "git -C .claude/worktrees/x stash show",
    # implement-issue Step 4 prunes worktrees in a loop; CLAUDE.md argues that
    # must stay unattended. A `git -* prune*` twin caught `worktree prune` and
    # `remote prune` through the same greedy glob, so the twin was dropped.
    "git -C /main worktree prune", "git worktree prune",
    "git -C sub remote prune origin",
    # Pushing a feature branch BY NAME. This is the shape implement-issue Step 9
    # and sweep-prs run, and the blanket `Bash(git push *)` stalled every one of
    # them. Branch protection already refuses the case a blanket rule was
    # protecting against, so the prompt bought nothing and cost an autonomous
    # run. These entries are what stops the blanket rule being reintroduced.
    "git push origin HEAD:fix/issue-592-vpp-idle-at-floor",
    "git push origin feat/phase4c-charge-commands",
    "git push -u origin fix/issue-604-signed-pair-aliases",
    "git push origin worktree-po-followups",
    "git -C .claude/worktrees/x push origin HEAD:fix/issue-592-vpp-idle-at-floor",
    # The `main` SUBSTRING trap: a branch may legitimately contain "main".
    # `Bash(git push * main*)` would prompt on this, which is why the protected
    # -ref rules anchor on the end of the token instead.
    "git push origin maintenance-cleanup",
    # Reading releases changes nothing on GitHub, and the release/beta flows
    # check the published version constantly ("always check the current
    # published version before tagging"). A blanket `gh release*` ask made
    # every one of those a prompt, which is why these verbs are named.
    "gh release list -L 5 -R johanzander/bess-manager-beta",
    "gh release list", "gh release view v9.9.0",
    "gh release view --json tagName",
    # `download` was claimed unattended in #617's body and in CLAUDE.md but had
    # no string pinning it -- flagged by that PR's review. Behaviour was already
    # correct; the verification was missing, which is the exact "rule that looks
    # right and matches nothing" failure this list guards against.
    "gh release download v9.9.0",
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
echo "📋 Checking branch protection..."
echo "-------------------------------------------"

# THE PREMISE THE PUSH RULES NOW REST ON.
#
# The protected-ref half of the push enumeration was deleted deliberately: with
# `enforce_admins` true, GitHub refuses a push to `main` server-side, including
# from the owner token every agent uses. That is a provable guarantee where an
# enumeration of command spellings is only ever a list of the ones somebody
# thought of -- and that list leaked three times, the last two spellings found
# by the review of the PR meant to fix it.
#
# But `enforce_admins` is a GitHub setting, not repo state: untracked, and
# flippable in two clicks by anyone with admin. The moment it goes false, this
# repo has NO guard on pushing to main at all, and nothing would say so. That
# is what this check exists to prevent -- it turns a load-bearing assumption
# into a checked invariant, so the protection cannot evaporate silently.
#
# If it fires: either turn enforce_admins back on, or restore the protected-ref
# patterns in .claude/settings.json (see CLAUDE.md, Permissions).
#
# Reading branch protection needs admin rights, which a CI token does not have,
# so an unreadable answer is a WARNING and a false one is an ERROR. Those are
# genuinely different outcomes -- "I could not check" is not "it is off" -- and
# collapsing them either way would make the gate lie in one direction or the
# other.
# TWO conditions, because `enforce_admins` ALONE PROTECTS NOTHING. It only
# extends whatever rules already exist to admins and the owner token; with no
# such rule it extends nothing, and `git push origin main` would succeed while
# this check reported green. Measured on this repo today: `required_reviews`
# and `restrictions` are both absent, and `required_status_checks` is the rule
# actually doing the blocking -- so asserting the flag without the rule would
# have been checking the wrong half.
#
# Any ONE blocking rule is enough, so the check accepts whichever is in force
# rather than pinning today's choice: required status checks, required reviews,
# a push restriction list, or a hard branch lock.
for remote_repo in "johanzander/bess-manager" "johanzander/bess-manager-beta"; do
    prot=$(gh api "repos/${remote_repo}/branches/main/protection" \
        --jq '{admins: (.enforce_admins.enabled // false),
               blocking: ((.required_status_checks != null)
                          or (.required_pull_request_reviews != null)
                          or (.restrictions != null)
                          or (.lock_branch.enabled // false))}
              | "\(.admins) \(.blocking)"' 2>/dev/null) || prot=""
    admins="${prot%% *}"
    blocking="${prot##* }"
    if [ -z "$prot" ]; then
        echo "⚠️  Could not read branch protection for ${remote_repo} (needs admin rights)"
        WARNINGS=$((WARNINGS + 1))
    elif [ "$blocking" != "true" ]; then
        echo "❌ ${remote_repo}: main has NO rule that blocks a push."
        echo "   enforce_admins only extends existing rules; on its own it protects nothing."
        echo "   Enable required status checks (or required reviews / push restrictions),"
        echo "   or restore the protected-ref patterns in .claude/settings.json."
        ERRORS=$((ERRORS + 1))
    elif [ "$admins" != "true" ]; then
        echo "❌ ${remote_repo}: enforce_admins is FALSE on main."
        echo "   The rules exist but do not apply to the owner token every agent uses."
        echo "   Re-enable it, or restore the protected-ref patterns in .claude/settings.json."
        ERRORS=$((ERRORS + 1))
    else
        echo "✅ ${remote_repo}: main is protected and enforced for admins"
    fi
done

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