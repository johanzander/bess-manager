#!/usr/bin/env bash
#
# The fleet manifest: one row per dispatched agent, in SQLite.
#
# WHY THIS EXISTS. `implement-issue` Step 0, `sweep-prs` and
# `backlog-digest.sh` currently treat `git worktree list` as ground truth for
# "what is in flight". Containerized agents get a private CLONE, not a
# worktree (see docs/superpowers/specs/2026-08-20-agent-fleet-sandbox-router-design.md
# for why: worktrees share one mutable ref namespace, and a dashboard that
# shows "12 agents working" invites dispatching 12 at once), so git's own
# registry no longer knows about them. This is the replacement registry.
#
# WHY SQLITE AND NOT A JSON FILE. N containers write status updates
# concurrently. That is exactly the shared-mutable-state race this phase
# exists to remove from git -- reintroducing it in the bookkeeping would be
# absurd. SQLite's locking handles it; a JSON file would need a hand-rolled
# atomic-write protocol to get to the same place.
#
# Usage:
#   fleet-manifest.sh register <clone_path> <issue_or_pr> <branch> <container_id> <role>
#   fleet-manifest.sh update-status <container_id> <status>
#   fleet-manifest.sh set-branch <container_id> <branch>
#   fleet-manifest.sh get <container_id>
#   fleet-manifest.sh list [--status <status>]
#
# `get` and `list` print a JSON array (`[]` when empty -- sqlite3 -json emits
# nothing at all for zero rows, which every JSON parser rejects).
#
set -euo pipefail

ROLES="dev po"
STATUSES="working needs_input in_review escalated done"

# ---------------------------------------------------------------------------
# Where the database lives.
#
# BESS_FLEET_DB wins when set -- that is how a container finds it, since the
# host's .fleet/ is bind-mounted at a path that has nothing to do with the
# repo layout inside the container.
#
# Otherwise: the MAIN checkout's .fleet/manifest.db, resolved the way
# gh-agent.sh resolves .env. One subtlety gh-agent.sh does not have: that
# trick works for a linked worktree (whose git-common-dir points back at the
# main checkout) but NOT for an agent's private clone, which is a fully
# independent repository -- there, git-common-dir is the clone's own .git and
# the naive answer would be a second, per-clone manifest that nothing else
# ever reads. Clones live at <main-checkout>/.agent-clones/<name>, so strip
# that suffix back off when it is present.
# ---------------------------------------------------------------------------
resolve_db() {
  if [ -n "${BESS_FLEET_DB:-}" ]; then
    printf '%s\n' "$BESS_FLEET_DB"
    return
  fi

  local common_dir repo_root
  common_dir=$(git rev-parse --git-common-dir 2>/dev/null || echo "")
  if [ -n "$common_dir" ]; then
    repo_root=$(dirname "$(cd "$common_dir" && pwd)")
  else
    repo_root=$(pwd)
  fi

  case "$repo_root" in
    */.agent-clones/*) repo_root="${repo_root%%/.agent-clones/*}" ;;
  esac

  printf '%s/.fleet/manifest.db\n' "$repo_root"
}

DB=$(resolve_db)
mkdir -p "$(dirname "$DB")"

# .timeout, not the default fail-fast: concurrent writers are the normal case
# here, and "database is locked" surfacing to a caller would be this script
# failing at the one job it was chosen for.
sql() { sqlite3 -cmd ".timeout 5000" "$DB" "$@"; }
sql_json() { sqlite3 -json -cmd ".timeout 5000" "$DB" "$@"; }

sql "CREATE TABLE IF NOT EXISTS dispatches (
       container_id TEXT PRIMARY KEY,
       clone_path   TEXT NOT NULL,
       issue_or_pr  INTEGER,
       branch       TEXT,
       role         TEXT NOT NULL,
       status       TEXT NOT NULL,
       started_at   TEXT NOT NULL
     );"

# SQL string literal quoting: double every single quote. Values here are
# branch names and paths, not attacker input, but a branch containing an
# apostrophe would otherwise produce a syntax error rather than a row.
q() { printf "'%s'" "${1//\'/\'\'}"; }

# Print a JSON array even when there are no rows.
emit_json() {
  local out
  out=$(sql_json "$1")
  printf '%s\n' "${out:-[]}"
}

member() {
  local needle="$1" haystack="$2" item
  for item in $haystack; do [ "$item" = "$needle" ] && return 0; done
  return 1
}

cmd="${1:-}"
shift || true

case "$cmd" in
  register)
    clone_path="${1:?register requires <clone_path>}"
    # Empty is allowed, same as branch below: the product-owner container is
    # not dispatched at an issue at all, so `${2:?}` (which rejects empty as
    # well as unset) would make run-po.sh unable to register itself.
    issue="${2?register requires <issue_or_pr> (empty is allowed)}"
    # `${3?...}` and not `${3:?...}`: an EMPTY branch is the normal case at
    # dispatch (see set-branch below), and `:?` rejects empty as well as unset.
    branch="${3?register requires <branch> (empty is allowed)}"
    container_id="${4:?register requires <container_id>}"
    role="${5:?register requires <role>}"

    if ! member "$role" "$ROLES"; then
      echo "fleet-manifest.sh: unknown role '$role' (expected one of: $ROLES)" >&2
      exit 2
    fi

    # The product-owner singleton. Enforced HERE rather than in run-po.sh
    # because it is a property of the fleet, not of one launcher: that role is
    # the only one with `memory: project`, so two live containers would race
    # on the same .claude/agent-memory/ files.
    if [ "$role" = "po" ]; then
      live=$(sql "SELECT count(*) FROM dispatches WHERE role='po' AND status != 'done';")
      if [ "$live" -ne 0 ]; then
        existing=$(sql "SELECT container_id FROM dispatches WHERE role='po' AND status != 'done' LIMIT 1;")
        echo "fleet-manifest.sh: a product-owner container is already live ($existing)." >&2
        echo "  Only one may run at a time -- it is the only role with project memory." >&2
        echo "  Stop it, or: fleet-manifest.sh update-status $existing done" >&2
        exit 1
      fi
    fi

    started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    # A container id is derived from the issue number, so re-dispatching the
    # same issue reuses the same id -- and re-dispatch is the NORMAL case, since
    # implement-issue Step 0 treats it as a resume. A finished dispatch must
    # therefore not block its own resume: reclaim a row whose work is 'done'
    # (new clone path, new start time, back to working). A row that is NOT done
    # still refuses, because that is a live agent being trampled.
    existing_status=$(sql "SELECT status FROM dispatches WHERE container_id = $(q "$container_id");")
    if [ "$existing_status" = "done" ]; then
      sql "UPDATE dispatches
             SET clone_path  = $(q "$clone_path"),
                 issue_or_pr = $(q "$issue"),
                 branch      = $(q "$branch"),
                 role        = $(q "$role"),
                 status      = 'working',
                 started_at  = $(q "$started_at")
           WHERE container_id = $(q "$container_id");"
      exit 0
    fi

    if ! sql "INSERT INTO dispatches
                (container_id, clone_path, issue_or_pr, branch, role, status, started_at)
              VALUES ($(q "$container_id"), $(q "$clone_path"), $(q "$issue"),
                      $(q "$branch"), $(q "$role"), 'working', $(q "$started_at"));" 2>/dev/null
    then
      echo "fleet-manifest.sh: container '$container_id' is already registered" >&2
      exit 1
    fi
    ;;

  update-status)
    container_id="${1:?update-status requires <container_id>}"
    status="${2:?update-status requires <status>}"

    if ! member "$status" "$STATUSES"; then
      echo "fleet-manifest.sh: unknown status '$status' (expected one of: $STATUSES)" >&2
      exit 2
    fi

    # An update that matches no row must fail loudly. Silently succeeding
    # would show up as an agent stuck in 'working' forever, with the caller
    # believing it had reported otherwise.
    changed=$(sql "UPDATE dispatches SET status = $(q "$status")
                   WHERE container_id = $(q "$container_id");
                   SELECT changes();")
    if [ "$changed" -eq 0 ]; then
      echo "fleet-manifest.sh: no dispatch registered for container '$container_id'" >&2
      exit 1
    fi
    ;;

  set-branch)
    # The branch does not exist at dispatch time: implement-issue Step 1
    # derives its name from the issue's labels and title
    # (<prefix>/issue-<n>-<slug>), which needs the issue read first. So
    # run-agent.sh registers an empty branch and the agent fills it in once
    # Step 4 has created it -- otherwise the dashboard shows every dispatch
    # sitting on `main` forever.
    container_id="${1:?set-branch requires <container_id>}"
    branch="${2:?set-branch requires <branch>}"

    changed=$(sql "UPDATE dispatches SET branch = $(q "$branch")
                   WHERE container_id = $(q "$container_id");
                   SELECT changes();")
    if [ "$changed" -eq 0 ]; then
      echo "fleet-manifest.sh: no dispatch registered for container '$container_id'" >&2
      exit 1
    fi
    ;;

  get)
    container_id="${1:?get requires <container_id>}"
    found=$(sql "SELECT count(*) FROM dispatches WHERE container_id = $(q "$container_id");")
    if [ "$found" -eq 0 ]; then
      echo "fleet-manifest.sh: no dispatch registered for container '$container_id'" >&2
      exit 1
    fi
    emit_json "SELECT * FROM dispatches WHERE container_id = $(q "$container_id");"
    ;;

  list)
    if [ "${1:-}" = "--status" ]; then
      status="${2:?--status requires a value}"
      if ! member "$status" "$STATUSES"; then
        echo "fleet-manifest.sh: unknown status '$status' (expected one of: $STATUSES)" >&2
        exit 2
      fi
      emit_json "SELECT * FROM dispatches WHERE status = $(q "$status") ORDER BY started_at;"
    else
      emit_json "SELECT * FROM dispatches ORDER BY started_at;"
    fi
    ;;

  *)
    sed -n '/^# Usage:/,/^#$/p' "$0" >&2
    exit 2
    ;;
esac
