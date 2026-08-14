#!/usr/bin/env bash
# Verifies that .claude/settings.json's sandbox config actually does what it
# claims, by exercising it rather than reasoning about it.
#
# RUN THIS VIA THE BASH TOOL, from the repo root or a worktree.
#
# A FRESH SESSION IS NOT REQUIRED. Earlier versions of this header insisted it
# was, on the theory that sandbox policy is read once at session start. That is
# false: `sandbox.*` live-reloads when a settings file is edited, and the
# session that enabled the sandbox went on to verify its own config with this
# script. Iterate in one session; just re-run after every edit, because a
# settings change can silently fail to apply.
#
# What DOES matter is that the Bash TOOL runs it. The sandbox applies only to
# commands Claude Code itself runs, so a `!`-prefixed or terminal-typed
# invocation is unsandboxed -- it would pass the permissive checks and fail the
# restrictive ones, which reads exactly like a real result. Check 0 catches it.
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

# 4. EDITING THE AGENT CONFIG ITSELF. The deny is per-FILE, not on the .claude
#    directory: settings.json, hooks, skills, workflows, routines,
#    output-styles, launch.json and .mcp.json are denied so a session cannot
#    rewrite the rules that govern it. An arbitrary new file under .claude/ is
#    NOT denied -- an earlier version of this script probed with
#    `touch .claude/.sandbox-probe`, which succeeds, and read that as the whole
#    directory being writable. Probe a real entry on the list instead.
if [ -f .claude/settings.json ]; then
  printf '' >> .claude/settings.json 2>/dev/null && cl=allowed || cl=blocked
else
  cl=skipped
fi
check "Bash writing .claude/settings.json is blocked (use Edit/Write)" blocked "$cl" \
  "the sandbox allowed a write to the settings file that governs it. Either the deny list changed or the sandbox is not applied -- re-derive before trusting CLAUDE.md's Permissions section."

# 4b. The paths CLAUDE.md is unsure about. These are reported, not asserted:
#     the earlier claim that they were denied came from misreading the binary's
#     GitHub Actions config as the local one, so measure rather than restate.
touch scripts/.sandbox-probe 2>/dev/null && sc=allowed || sc=blocked
rm -f scripts/.sandbox-probe 2>/dev/null
printf 'INFO  Bash writing scripts/** is %s\n' "$sc"

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
