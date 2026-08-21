#!/usr/bin/env bash
#
# Block until the maintainer replies on an issue or PR, then print the reply.
#
#     scripts/wait-for-reply.sh <issue-or-pr-number> <since-iso8601> [options]
#
# WHY THIS EXISTS. A dispatched agent (scripts/run-agent.sh) reaches genuine
# judgment gates -- implement-issue Step 3, Step 7, advance-pr's review-round
# cap. The container must NOT exit at one. Exiting would throw away Step 10's
# recovery of a PR gone CONFLICTING because another PR merged underneath it,
# and advance-pr's repeated run through the review loop: hardened, working
# machinery that a fresh dispatch would have to redo by hand. So the agent
# posts its question (scripts/gh-agent.sh --as dev) and blocks HERE, keeping
# every bit of its in-memory context, and resumes in the same process the
# moment an answer lands.
#
# This is a poll, not a webhook: no listener, no port, nothing to keep running
# on the host. It is the same shape as `gh pr checks --watch`, which this repo
# already blocks on for far longer.
#
# Options:
#   --kind issue|pr     which thread to read (default: issue)
#   --timeout <seconds> give up eventually (default: 24h). A gate nobody
#                       answers must not hold a container open forever.
#   --from <login>      repeatable; only comments from these authors satisfy
#                       the gate (default: the repo owner). Any account can
#                       comment on a public repo, so an unrecognised author is
#                       skipped -- never accepted as the maintainer.
#   --ignore <login>    repeatable; defaults cover the automation identities,
#                       layered on top of --from.
#
# Exit 0 and print the new comment on success; non-zero on timeout.
#
set -euo pipefail

NUMBER="${1:-}"
SINCE="${2:-}"
if [ -z "$NUMBER" ] || [ -z "$SINCE" ]; then
  echo "usage: wait-for-reply.sh <issue-or-pr-number> <since-iso8601> [--kind issue|pr]" >&2
  echo "                         [--timeout <seconds>] [--from <login>] [--ignore <login>]" >&2
  exit 2
fi
shift 2

KIND="issue"
TIMEOUT="${BESS_REPLY_TIMEOUT_SECONDS:-86400}"
INTERVAL="${BESS_POLL_INTERVAL_SECONDS:-90}"

# The agent's own voice. Its status comments land in the very thread it is
# waiting on, and treating one as the answer would make every gate resolve
# itself instantly -- against its own question. Layered on top of --from: a
# login in the ignore set is skipped even if --from also names it.
IGNORE="bess-agent bess-developer bess-product-owner bess-po bess-manager-claude-bot github-actions"

# The gate is the maintainer's. --from is an allowlist (default: the repo
# owner); --ignore only subtracts from it. Every other trigger surface in this
# repo gates on the owner explicitly, and CLAUDE.md says so as a rule -- this
# script is how a dispatched agent reaches a judgment gate, so it must not be
# the one place a drive-by comment reads as the maintainer.
FROM_LOGINS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --kind)    KIND="${2:?--kind requires issue|pr}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?--timeout requires seconds}"; shift 2 ;;
    --from)    FROM_LOGINS="$FROM_LOGINS ${2:?--from requires a login}"; shift 2 ;;
    --ignore)  IGNORE="$IGNORE ${2:?--ignore requires a login}"; shift 2 ;;
    *) echo "wait-for-reply.sh: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

case "$KIND" in
  issue|pr) ;;
  *) echo "wait-for-reply.sh: unknown --kind '$KIND' (expected issue or pr)" >&2; exit 2 ;;
esac

if [ -z "$FROM_LOGINS" ]; then
  # Resolve the owner once, before polling. Same repo context `gh issue view`
  # relies on below (the dispatch clone's origin), so if that resolves, this
  # does. Explicit failure, not a fallback: a gate that cannot name its author
  # must not accept any author.
  owner=$(gh repo view --json owner --jq .owner.login 2>/dev/null || true)
  if [ -z "$owner" ]; then
    echo "wait-for-reply.sh: could not determine the repo owner -- pass --from <login>" >&2
    exit 2
  fi
  FROM_LOGINS="$owner"
fi

# SECONDS is bash's own monotonic counter -- no date arithmetic, and immune to
# a shim'd or slow `gh` skewing the accounting.
SECONDS=0

while :; do
  # --json comments is the whole payload; the filtering below is done in
  # python rather than jq because comparing ISO timestamps is the entire job
  # and getting that subtly wrong is how a gate silently never fires.
  payload=$(gh "$KIND" view "$NUMBER" --json comments 2>/dev/null || echo '')

  if [ -n "$payload" ]; then
    reply=$(printf '%s' "$payload" | python3 -c '
import json, sys

since = sys.argv[1]
ignore = {name.lower() for name in sys.argv[2].split()}
allowed = {name.lower() for name in sys.argv[3].split()}

try:
    comments = json.load(sys.stdin).get("comments") or []
except Exception:
    sys.exit(1)

for c in comments:
    author = ((c.get("author") or {}).get("login") or "").lower()
    created = c.get("createdAt") or c.get("created_at") or ""
    if author in ignore:
        continue
    if author not in allowed:
        continue
    # Lexicographic comparison is correct for RFC-3339 UTC timestamps, which
    # is what the GitHub API returns and what run-agent.sh stamps.
    if created > since:
        print(c.get("body") or "")
        sys.exit(0)
sys.exit(1)
' "$SINCE" "$IGNORE" "$FROM_LOGINS") && {
      printf '%s\n' "$reply"
      exit 0
    }
  fi

  if [ "$SECONDS" -ge "$TIMEOUT" ]; then
    echo "wait-for-reply.sh: timed out after ${TIMEOUT}s waiting for a reply on $KIND #$NUMBER" >&2
    exit 1
  fi

  # `sleep 0` is a real case: the tests drive the loop with no delay.
  sleep "$INTERVAL"
done
