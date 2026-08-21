#!/usr/bin/env bash
#
# Start the product-owner container: one clone, one container, looping forever.
#
#     scripts/run-po.sh
#
# WHY THIS ONE ROLE HAS A DIFFERENT LIFECYCLE. Implementers are dispatched per
# issue and torn down (scripts/run-agent.sh). `product-owner` is the only agent
# with `memory: project`, and that memory lives in git-tracked files under
# .claude/agent-memory/. A fresh clone per pass would trap every memory edit in
# a throwaway checkout unless it were pushed and merged before teardown --
# strictly slower than today's "edit the file, done", i.e. a real regression.
# One long-lived container on one clone keeps a memory edit visible to the very
# next pass, exactly as it is today, while durability for OTHER containers
# still flows through the normal push -> PR -> merge path.
#
# It also removes Rhythm's current requirement of an open terminal running
# `/loop /backlog`. It does NOT remove the underlying constraint that this only
# happens while the laptop is on -- that is a v1 laptop-only limitation, not a
# container one.
#
# Only one may run at a time. scripts/fleet-manifest.sh enforces that as a
# singleton rule rather than this script checking, because it is a property of
# the fleet, not of one launcher.
#
# Options:
#   --interval <seconds>  between backlog passes (default 1800 -- 30 min,
#                         matching Rhythm's existing informal cadence)
#   --image <tag>         default bess-agent:dev (or $BESS_AGENT_IMAGE)
#   --build               rebuild the image even if it exists
#   --open-network        disable the egress allowlist
#   --dry-run             print the podman command instead of running it
#
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/lib/agent-dispatch.sh
source "$SCRIPT_DIR/lib/agent-dispatch.sh"

IMAGE="${BESS_AGENT_IMAGE:-bess-agent:dev}"
INTERVAL=1800
EGRESS="restricted"
FORCE_BUILD=false
DRY_RUN=false

usage() {
  sed -n '/^# Start the product-owner/,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --interval)     INTERVAL="${2:?--interval requires seconds}"; shift 2 ;;
    --image)        IMAGE="${2:?--image requires a tag}"; shift 2 ;;
    --build)        FORCE_BUILD=true; shift ;;
    --open-network) EGRESS="open"; shift ;;
    --dry-run)      DRY_RUN=true; shift ;;
    -h|--help)      usage ;;
    *)              echo "run-po.sh: unknown argument '$1'" >&2; usage ;;
  esac
done

dispatch_resolve_paths || exit 1

CLONE_DIR="$CLONES_DIR/product-owner"
CONTAINER="bess-po"

if podman container exists "$CONTAINER" 2>/dev/null; then
  echo "❌ container '$CONTAINER' already exists -- the product-owner is a singleton." >&2
  echo "   Attach:  podman exec -it $CONTAINER bash" >&2
  echo "   Logs:    podman logs -f $CONTAINER" >&2
  echo "   Replace: podman rm -f $CONTAINER && scripts/fleet-manifest.sh update-status $CONTAINER done" >&2
  exit 1
fi

dispatch_ensure_clone "$CLONE_DIR"
dispatch_load_credentials po || exit 1
# No podman socket: the product-owner only runs `/backlog` passes, never Step 8
# (local run & observe), and the socket is authority over the host -- see
# agent-dispatch.sh. It stays unmounted unless a dispatch explicitly opts in.
dispatch_ensure_image "$IMAGE" "$FORCE_BUILD"
mkdir -p "$FLEET_DIR"

# Register FIRST here, unlike run-agent.sh, and that ordering is the point: the
# singleton check lives in `register`, so a second product-owner must be
# refused before its container starts, not cleaned up after.
if ! "$MANIFEST" register "$CLONE_DIR" "" "main" "$CONTAINER" po; then
  exit 1
fi

dispatch_run_args "$CONTAINER" "$CLONE_DIR" po "$EGRESS" false
# Restart on its own: this is meant to be started once (e.g. at login) and left
# alone, so a crash should not quietly end the fleet's backlog work.
DISPATCH_RUN_ARGS+=(--restart unless-stopped)

# git pull, one pass, sleep, repeat -- the containerized equivalent of the
# Rhythm surface's `/loop /backlog`. `|| true` on the pass, because one failed
# backlog pass (a network blip, a rate limit) must not end the loop; the next
# one is 30 minutes away and costs nothing.
po_loop='
while :; do
  echo "── backlog pass $(date -u +%Y-%m-%dT%H:%M:%SZ) ─────────────────────"
  git pull --ff-only || echo "git pull failed -- continuing on the current checkout"
  claude -p "/backlog" --dangerously-skip-permissions --output-format stream-json --verbose || true
  echo "── sleeping '"$INTERVAL"'s ─────────────────────────────────────────"
  sleep '"$INTERVAL"'
done
'

if [ "$DRY_RUN" = true ]; then
  dispatch_print_run_args "$IMAGE" bash -lc "$po_loop"
  "$MANIFEST" update-status "$CONTAINER" done >/dev/null 2>&1 || true
  exit 0
fi

container_id=$(podman run "${DISPATCH_RUN_ARGS[@]}" "$IMAGE" bash -lc "$po_loop")

cat <<EOF

🗂  product-owner running as $CONTAINER (one pass every ${INTERVAL}s)
   clone      $CLONE_DIR
   container  ${container_id:0:12}
   logs       podman logs -f $CONTAINER
   stop       podman rm -f $CONTAINER && scripts/fleet-manifest.sh update-status $CONTAINER done
EOF
