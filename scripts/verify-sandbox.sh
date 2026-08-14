#!/usr/bin/env bash
# Verifies that .claude/settings.json's sandbox config actually does what it
# claims, by exercising it rather than reasoning about it.
#
# RUN THIS IN A FRESH CLAUDE CODE SESSION, from the repo root or a worktree.
#
# It has to be a fresh session, and that is the whole reason this script
# exists. Sandbox policy is read ONCE at session start: edits to
# settings.json during a session have no effect, and a `claude -p` child
# inherits the parent's policy rather than loading the file, so a session
# that changed the config cannot test the change -- not directly, and not
# through a subagent. Every such attempt measures the stale policy and
# reports confident nonsense.
#
#   bash scripts/verify-sandbox.sh
#
# Each check prints PASS/FAIL and, on failure, what to do about it. Exit 0
# means the config is safe to rely on.
set -uo pipefail

failures=0
outside="${HOME}/.bess-sandbox-probe-$$"

check() {
  local label="$1" expected="$2" got="$3" remedy="$4"
  if [ "$expected" = "$got" ]; then
    printf 'PASS  %s\n' "$label"
  else
    printf 'FAIL  %s (expected %s, got %s)\n      -> %s\n' "$label" "$expected" "$got" "$remedy"
    failures=$((failures + 1))
  fi
}

# 0. AM I EVEN SANDBOXED? Everything below is meaningless otherwise, and an
#    unsandboxed run does not fail loudly -- it PASSES the permissive checks
#    and fails the restrictive ones, which reads exactly like a real result.
#    A plain terminal is not sandboxed: the sandbox is applied by Claude Code
#    to commands IT runs, so this must be run by the Bash tool from inside a
#    freshly started session.
touch "$outside" 2>/dev/null && out=allowed || out=blocked
rm -f "$outside" 2>/dev/null

if [ "$out" = allowed ]; then
  cat <<'MSG'
NOT RUNNING UNDER THE SANDBOX -- no checks were run.

A write outside the repository succeeded, so nothing here is being enforced.
That is what a plain terminal looks like; the sandbox only applies to commands
Claude Code itself runs.

To get a real result:
  1. Start a NEW Claude Code session in this directory (policy is read once,
     at session start, so a session that edited the config cannot test it).
  2. Ask it to run: bash scripts/verify-sandbox.sh
     Let the Bash TOOL run it. A `!`-prefixed or terminal-typed command may
     not take the same path.
MSG
  exit 2
fi
printf 'PASS  %s\n' "write outside the repo is blocked"

# 2. ...without breaking ordinary in-repo work.
touch ./.bess-sandbox-probe-inside 2>/dev/null && in=allowed || in=blocked
rm -f ./.bess-sandbox-probe-inside 2>/dev/null
check "write inside the repo is allowed" allowed "$in" \
  "the sandbox is too tight to work in; widen sandbox.filesystem.allowWrite"

# 3. WORKTREE CREATION. This project's entire workflow depends on it, and it
#    writes .git/worktrees + .git/config + the checked-out .claude/** -- all
#    of which Claude Code's DEFAULT denyWrite list covers. Whether an
#    allowWrite entry can re-open a default deny is the open question this
#    check settles.
# Errors are captured in a VARIABLE, never a temp file: the sandbox denies
# /tmp and $TMPDIR, so `2>/tmp/...` fails to open and swallows the very
# message this check exists to report.
probe_wt=".claude/worktrees/sandbox-probe-$$"
wt_err=$(git worktree add -q -b "sandbox-probe-$$" "$probe_wt" HEAD 2>&1 >/dev/null)
if [ -d "$probe_wt" ]; then
  wt=created
  git worktree remove --force "$probe_wt" >/dev/null 2>&1
  git branch -D "sandbox-probe-$$" >/dev/null 2>&1
else
  wt=blocked
fi
# Expected BLOCKED: .git/config and .git/worktrees are on the built-in
# denyWrite list, and writes are allowOnly minus denyWithinAllow with no
# allow-within-deny primitive, so allowWrite cannot re-open them. A "created"
# here would mean the sandbox is looser than this repo's docs assume.
check "git worktree add is blocked (use EnterWorktree)" blocked "$wt" \
  "$(printf 'the sandbox allowed a .git/config + .git/worktrees write. Either the write policy changed or the sandbox is not applied; re-read CLAUDE.md Permissions before trusting anything here. Error was: %s' "$(printf '%s' "$wt_err" | head -1)")"

# NOTE ON `rm -rf`, which is the reason settings.json leaves rm unattended.
# There is deliberately no probe for it, because a safe one cannot be written.
# Proving an unlink outside the repo is blocked needs a file outside the repo
# that already exists -- and creating one is itself blocked (check 0), so the
# only candidates are the user's real files. A probe that deletes ~/.zshrc when
# the sandbox is OFF is worse than no probe.
#
# Check 0 is the sound proxy. The macOS profile emits one rule covering both
# operations together:
#     n8t("deny", ["file-write-unlink", "file-write-create"], ...)
# so a blocked create outside the repo means a blocked unlink outside the repo.
# If check 0 passes, `rm -rf` cannot escape.

# 4. EDITING THE AGENT CONFIG ITSELF. `.claude` is on the default denyWrite
#    list specifically to stop a session rewriting its own hooks and agents.
#    That is a reasonable default, but this repo edits .claude/** as ordinary
#    work, and the Edit/Write tools are not affected -- only Bash is.
touch .claude/.sandbox-probe 2>/dev/null && cl=allowed || cl=blocked
rm -f .claude/.sandbox-probe 2>/dev/null
# Expected BLOCKED, same reason. This is not a problem to fix: .claude/** is
# edited with the Edit/Write tools, which the sandbox does not govern at all.
# It is checked so the constraint stays a measured fact rather than folklore.
check "Bash writing .claude/** is blocked (use Edit/Write)" blocked "$cl" \
  "the sandbox allowed a .claude write, so the built-in denyWrite list changed. Re-derive it before trusting CLAUDE.md's Permissions section."

# 5. gh. `gh pr create` is the closing step of implement-issue, and gh is a Go
#    binary: under the macOS sandbox it cannot reach trustd to verify TLS,
#    which surfaces as x509: OSStatus -26276.
if command -v gh >/dev/null 2>&1; then
  gh_err=$(gh auth status 2>&1 >/dev/null) && g=works || g=broken
  check "gh reaches GitHub" works "$g" \
    "$(printf 'sandbox.excludedCommands did not exempt gh. Try sandbox.enableWeakerNetworkIsolation (documented for exactly this, and explicitly weaker), or move the exclusion to ~/.claude/settings.json -- several sandbox keys are ignored in PROJECT settings. First error: %s' "$(printf '%s' "$gh_err" | head -1)")"
else
  printf 'SKIP  gh not installed\n'
fi

# 6. The podman VM backs every E2E run and lives outside the repo.
if command -v podman >/dev/null 2>&1; then
  podman info >/dev/null 2>&1 && p=works || p=broken
  check "podman reaches its VM" works "$p" \
    "the sandbox denies the podman socket; add it to sandbox.filesystem.allowRead or exclude podman"
else
  printf 'SKIP  podman not installed\n'
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "sandbox config verified"
else
  echo "$failures check(s) failed -- do not rely on this config until they are resolved"
fi
exit $((failures > 0))
