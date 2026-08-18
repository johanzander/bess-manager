#!/usr/bin/env bash
# Verifies that .claude/settings.json's sandbox config actually does what it
# claims, by exercising it rather than reasoning about it.
#
# RUN THIS IN A FRESH SESSION, VIA THE BASH TOOL, from the repo root or a
# worktree.
#
# FRESH, because the sandbox captures its policy once -- at activation -- and
# then ignores every later settings edit. The trap is that this looks like the
# opposite: editing settings.json mid-session DOES activate the sandbox, so the
# editing session finds itself sandboxed and concludes the config live-reloads.
# It does not. Subsequent edits are silently ignored while probes keep
# returning confident results measured against the first config. Four knobs
# were "verified" that way once; none of those results meant anything. If a
# result contradicts the config you are reading, the config is not what runs.
#
# VIA THE BASH TOOL, because the sandbox applies only to commands Claude Code
# itself runs. A `!`-prefixed or terminal-typed invocation is unsandboxed -- it
# would pass the permissive checks and fail the restrictive ones, which reads
# exactly like a real result. Check 0 exists to catch that.
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
# Decide from the EXIT STATUS, not from whether the directory exists.
# `git worktree add` creates the target directory BEFORE writing .git/worktrees,
# and .claude/worktrees/<name> is not itself denied (only specific .claude
# files are -- see check 4). So a correctly-blocked run still leaves the
# directory behind, and a `[ -d ]` test reports "created" on a correct config:
# a false FAIL, plus a stray directory when `git worktree remove` then fails.
probe_wt=".claude/worktrees/sandbox-probe-$$"
if wt_err=$(git worktree add -q -b "sandbox-probe-$$" "$probe_wt" HEAD 2>&1 >/dev/null); then
  wt=created
  git worktree remove --force "$probe_wt" >/dev/null 2>&1
  git branch -D "sandbox-probe-$$" >/dev/null 2>&1
else
  wt=blocked
  # Report WHY it was blocked here, on the PASS path. The remedy string below
  # cannot: it prints only when the check FAILS, i.e. when the add SUCCEEDED,
  # and then there is no error to show. Surfacing it here also catches a block
  # for some reason other than the sandbox.
  [ -n "$wt_err" ] && printf 'INFO  worktree add blocked with: %s\n' "$(printf '%s' "$wt_err" | head -1)"
  # Clean up the partial directory the failed add left behind.
  rm -rf "$probe_wt" 2>/dev/null
  git worktree prune >/dev/null 2>&1
  git branch -D "sandbox-probe-$$" >/dev/null 2>&1
fi
# Expected BLOCKED: .git/config and .git/worktrees are on the built-in
# denyWrite list, and writes are allowOnly minus denyWithinAllow with no
# allow-within-deny primitive, so allowWrite cannot re-open them. A "created"
# here would mean the sandbox is looser than this repo's docs assume.
check "git worktree add is blocked (use EnterWorktree)" blocked "$wt" \
  "the sandbox allowed a .git/config + .git/worktrees write. Either the write policy changed or the sandbox is not applied; re-read docs/agents/local-agent-environment.md Permissions before trusting anything here. (No error to quote -- this check fails precisely when the command SUCCEEDED.)"

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
  "the sandbox allowed a write to the settings file that governs it. Either the deny list changed or the sandbox is not applied -- re-derive before trusting docs/agents/local-agent-environment.md's Permissions section."

# 4b. The paths docs/agents/local-agent-environment.md is unsure about. These are reported, not asserted:
#     the earlier claim that they were denied came from misreading the binary's
#     GitHub Actions config as the local one, so measure rather than restate.
touch scripts/.sandbox-probe 2>/dev/null && sc=allowed || sc=blocked
rm -f scripts/.sandbox-probe 2>/dev/null
printf 'INFO  Bash writing scripts/** is %s\n' "$sc"

# 4c. THE SYMLINKED DEPENDENCY TREES. In a worktree, frontend/node_modules and
#     .venv are symlinks into the MAIN checkout (scripts/worktree-setup.sh), so
#     a write through them resolves outside the worktree's own root. That is
#     why allowWrite lists the main checkout as well as ".". Missing it does
#     not look like a permissions problem -- it surfaces as vitest failing to
#     load its config with EPERM on node_modules/.vite-temp, i.e. Step 6's
#     quality gate breaking in every worktree for no visible reason.
#     This check is only MEANINGFUL in a linked worktree. In the main checkout
#     frontend/node_modules is a real directory inside ".", so the probe passes
#     no matter what allowWrite says -- and the main checkout is the obvious
#     place to run this script from, so a PASS there means nothing. Say so
#     rather than bank a false green.
#     Three states, and they must not be conflated. `-L` alone is not enough:
#     a DANGLING link (main checkout's node_modules removed or reinstalled
#     while a worktree still points at it) is `-L` true but `-e` false, and
#     probing it fails on the missing target -- reporting a sandbox
#     misconfiguration and sending the reader to allowWrite, which is the wrong
#     knob entirely. Require both.
if [ -L frontend/node_modules ] && [ ! -e frontend/node_modules ]; then
  printf 'SKIP  frontend/node_modules is a DANGLING symlink -- its target is gone, not a sandbox problem (re-run scripts/worktree-setup.sh)\n'
elif [ ! -L frontend/node_modules ]; then
  if [ -e frontend/node_modules ]; then
    printf 'SKIP  node_modules symlink check -- not a symlink here (run this from a linked worktree; a PASS in the main checkout proves nothing)\n'
  else
    printf 'SKIP  frontend/node_modules not present (run scripts/worktree-setup.sh)\n'
  fi
else
  touch frontend/node_modules/.sandbox-probe 2>/dev/null && nm=allowed || nm=blocked
  rm -f frontend/node_modules/.sandbox-probe 2>/dev/null
  check "writing through the node_modules symlink is allowed" allowed "$nm" \
    "add the main checkout to sandbox.filesystem.allowWrite -- nested worktrees and every symlink target are then covered by one entry. Without it vitest and vite build fail EPERM in every worktree. NOTE: a SIBLING checkout (../bess-manager-feature) is NOT under that path and needs its own entry."
fi

# 4d. THE TWO USER-LEVEL CACHES scripts/worktree-setup.sh WRITES. Both sit well
#     outside the repo, so neither the "." nor the "~/GitHub/bess-manager"
#     entry reaches them, and the built-in allowOnly list covers only
#     ~/.npm/_logs -- not the package cache next to it. Setup does BOTH: it
#     runs `npm install` when a lockfile has diverged from the main checkout,
#     and then `npx playwright install chromium`.
#
#     What makes this worth a check rather than a comment is that NEITHER
#     failure names the sandbox. npm reports EPERM on ~/.npm/_cacache as
#     "Your cache folder contains root-owned files ... please run: sudo chown
#     -R", sending you to `sudo` -- which is on the ask list and is entirely
#     the wrong fix. And worktree-setup.sh's Playwright step is bounded by a
#     timeout whose message blames a slow download, so a blocked cache reads
#     as the unrelated extraction hang described in worktree-setup.sh (which
#     is a real, separate failure -- do not conflate the two). Both the npm and
#     the Playwright blocks were observed here in one session, and the
#     Playwright one cost a whole worktree's setup.
#
# 4d-i. The Playwright browser cache. Browsers are deliberately NOT
#       per-worktree -- one shared user-level cache serves every checkout, so
#       redirecting PLAYWRIGHT_BROWSERS_PATH into the repo is not the fix.
#       mkdir rather than touch, and create the cache dir first: it may not
#       exist yet on a fresh machine, and creating it is the first thing a
#       real install does.
#       `PLAYWRIGHT_BROWSERS_PATH=0` is Playwright's documented sentinel for
#       "no shared cache, keep browsers inside node_modules" -- NOT a path.
#       Treating it as one makes the probe `mkdir -p 0` in the repo, which
#       succeeds and reports a PASS that measured nothing.
pw_sentinel=no
if [ "${PLAYWRIGHT_BROWSERS_PATH:-}" = "0" ]; then
  pw_sentinel=yes
elif [ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ]; then
  pw_cache="$PLAYWRIGHT_BROWSERS_PATH"
elif [ "$(uname -s)" = "Darwin" ]; then
  pw_cache="$HOME/Library/Caches/ms-playwright"
else
  pw_cache="$HOME/.cache/ms-playwright"
fi

if [ "$pw_sentinel" = yes ]; then
  printf 'SKIP  PLAYWRIGHT_BROWSERS_PATH=0 -- browsers live in node_modules, no shared cache to probe\n'
else
  # A cache directory that cannot even be CREATED is the blocked case, not an
  # inapplicable one. Reporting SKIP here (and counting no failure) is how a
  # fresh sandboxed machine exits 0 saying the config is safe while both npm
  # and Playwright are about to fail -- the exact condition this check exists
  # to catch. Fold it into the same `check`, so it FAILS.
  mkdir -p "$pw_cache" 2>/dev/null
  if [ -d "$pw_cache" ]; then
    mkdir "$pw_cache/.sandbox-probe" 2>/dev/null && pw=allowed || pw=blocked
    rmdir "$pw_cache/.sandbox-probe" 2>/dev/null
  else
    pw=blocked
  fi
  check "writing the Playwright browser cache is allowed" allowed "$pw" \
    "add the browser cache to sandbox.filesystem.allowWrite (~/Library/Caches/ms-playwright on macOS, ~/.cache/ms-playwright on Linux). Without it scripts/worktree-setup.sh cannot install browsers, and its timeout reports that as a stalled download -- indistinguishable from the separate extraction hang that timeout was written for. Do NOT point PLAYWRIGHT_BROWSERS_PATH into the repo to dodge this: one shared cache across every worktree is the design."
fi

# 4d-ii. The npm package cache. ~/.npm/_logs is writable by default and
#        ~/.npm/_cacache is not, so npm looks fine right up until it has to
#        fetch something -- `npm install` in worktree-setup.sh (diverged
#        lockfile), `npm ci` in e2e/run-e2e.sh (missing frontend/dist), or any
#        npx that misses the local node_modules.
#        Same rule as above: "could not be created" IS blocked. Never SKIP it.
mkdir -p "$HOME/.npm/_cacache" 2>/dev/null
if [ -d "$HOME/.npm/_cacache" ]; then
  mkdir "$HOME/.npm/_cacache/.sandbox-probe" 2>/dev/null && npmc=allowed || npmc=blocked
  rmdir "$HOME/.npm/_cacache/.sandbox-probe" 2>/dev/null
else
  npmc=blocked
fi
check "writing the npm package cache is allowed" allowed "$npmc" \
    "add ~/.npm to sandbox.filesystem.allowWrite. The built-in allow list covers ~/.npm/_logs only, so npm can write its log and not its cache. IGNORE the error npm prints -- it claims the cache 'contains root-owned files' and tells you to run 'sudo chown -R 502:20 ~/.npm'. That is npm guessing at EPERM; the files are not root-owned and sudo is not the fix."

# 5. gh. `gh pr create` is the closing step of implement-issue, and gh is a Go
#    binary: under the macOS sandbox it cannot reach trustd to verify TLS,
#    which surfaces as x509: OSStatus -26276.
if command -v gh >/dev/null 2>&1; then
  gh_err=$(gh auth status 2>&1 >/dev/null) && g=works || g=broken
  check "gh reaches GitHub" works "$g" \
    "$(printf 'gh needs BOTH sandbox.enableWeakerNetworkIsolation (trustd TLS: x509 OSStatus -26276) and network.allowMachLookup for SecurityServer/securityd (keychain: "token in keyring is invalid"). Check both are still set. Do NOT reach for excludedCommands -- it was tried in project and user settings and did nothing. First error: %s' "$(printf '%s' "$gh_err" | head -1)")"
else
  printf 'SKIP  gh not installed\n'
fi

# 6. The podman VM backs every E2E run and lives outside the repo.
if command -v podman >/dev/null 2>&1; then
  podman info >/dev/null 2>&1 && p=works || p=broken
  check "podman reaches its VM" works "$p" \
    "podman reaches its VM over a LOCAL TCP PORT (dial tcp 127.0.0.1:<port>), not a unix socket -- check sandbox.network.allowLocalBinding is still set. filesystem.allowRead, network.allowUnixSockets and excludedCommands are all the wrong knob; each was tried and disproved."
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
