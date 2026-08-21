#!/usr/bin/env bash
#
# Dispatch one containerized implementer at one issue or PR.
#
#     scripts/run-agent.sh 502
#
# Phase 1 of docs/superpowers/specs/2026-08-20-agent-fleet-sandbox-router-design.md.
# What it does, in order:
#
#   1. Gives the agent a private CLONE at .agent-clones/issue-<n>/ -- not a
#      worktree. Worktrees share one mutable ref namespace, which is survivable
#      only because a human paces dispatch by hand; containerizing removes that
#      pacing, so N agents branching, committing and pushing at once would land
#      exactly on the lock contention .claude/settings.json's git denylist was
#      written to avoid.
#   2. Symlinks the dependency trees into it, so the clone is a normal,
#      immediately-usable checkout ON THE HOST: `cd .agent-clones/issue-<n> &&
#      .venv/bin/pytest` is how you inspect what an agent built, exactly as
#      with a worktree today, with nothing container-specific to know.
#   3. Starts the container -- clone bind-mounted at its own host path, a
#      role-scoped gh token (never the maintainer's own `gh auth`), a
#      restricted egress allowlist, and a permissive in-container permission
#      mode. That last one is the point of the whole phase: the blast radius of
#      "just allow it" is a disposable container and a scoped token, so safety
#      comes from the boundary instead of from another allowlist entry.
#   4. Registers the dispatch in the fleet manifest IMMEDIATELY, before any work
#      happens, so a container that dies in its first second is still visible
#      to implement-issue Step 0's resume check.
#
# The clone directory is host-persistent and deliberately outlives the
# container: a killed container leaves its commits and uncommitted work on
# disk. Nothing here deletes one.
#
# Options:
#   --image <tag>       default bess-agent:dev (or $BESS_AGENT_IMAGE)
#   --build             rebuild the image even if it exists
#   --open-network      disable the egress allowlist (debugging a dispatch that
#                       failed in a way that might be the firewall)
#   --dry-run           print the podman command instead of running it
#   --verify-isolation  prove containers cannot corrupt each other's deps
#
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/lib/agent-dispatch.sh
source "$SCRIPT_DIR/lib/agent-dispatch.sh"

IMAGE="${BESS_AGENT_IMAGE:-bess-agent:dev}"
EGRESS="restricted"
FORCE_BUILD=false
DRY_RUN=false
MODE="dispatch"
NUMBER=""

usage() {
  sed -n '/^# Dispatch one/,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --image)            IMAGE="${2:?--image requires a tag}"; shift 2 ;;
    --build)            FORCE_BUILD=true; shift ;;
    --open-network)     EGRESS="open"; shift ;;
    --dry-run)          DRY_RUN=true; shift ;;
    --verify-isolation) MODE="verify-isolation"; shift ;;
    -h|--help)          usage ;;
    -*)                 echo "run-agent.sh: unknown flag '$1'" >&2; usage ;;
    *)                  NUMBER="$1"; shift ;;
  esac
done

dispatch_resolve_paths || exit 1

# --- --verify-isolation ------------------------------------------------------
#
# The design mounted the dependency trees read-only because two containers
# installing into one shared venv corrupts it. Baking them into an image layer
# removes the shared tree entirely: each container writes into its own
# copy-on-write view. That is a stronger guarantee than the permission bits --
# but only if it is true, and "that's how overlayfs works" is the kind of claim
# this repo does not accept unmeasured. So measure it.
if [ "$MODE" = "verify-isolation" ]; then
  dispatch_ensure_image "$IMAGE" "$FORCE_BUILD"

  # Pure-python, tiny, and in nothing this repo depends on -- the check needs a
  # package the host venv genuinely lacks, or its host half proves nothing.
  # Overridable because "what the host lacks" changes as requirements do.
  pkg="${BESS_ISOLATION_PROBE_PKG:-pyfiglet}"
  if "$MAIN_CHECKOUT/.venv/bin/python" -c "import $pkg" 2>/dev/null; then
    echo "❌ '$pkg' is already in the HOST venv, so the host half of this check would" >&2
    echo "   prove nothing. Pick a package the host does not have." >&2
    exit 1
  fi

  echo "→ installing '$pkg' inside container A"
  podman run --rm -e BESS_EGRESS=open "$IMAGE" bash -lc \
    "\"\$MAIN_CHECKOUT/.venv/bin/pip\" install -q $pkg && \"\$MAIN_CHECKOUT/.venv/bin/python\" -c 'import $pkg'"
  echo "   A: installed ✅"

  echo "→ checking container B"
  if podman run --rm -e BESS_EGRESS=open "$IMAGE" bash -lc \
      "\"\$MAIN_CHECKOUT/.venv/bin/python\" -c 'import $pkg' 2>/dev/null"; then
    echo "❌ FAIL: container A's install is visible in container B. The dependency" >&2
    echo "   tree is shared after all, and concurrent installs can corrupt it." >&2
    exit 1
  fi
  echo "   B: absent ✅"

  echo "→ checking the host's own venv"
  if "$MAIN_CHECKOUT/.venv/bin/python" -c "import $pkg" 2>/dev/null; then
    echo "❌ FAIL: the container's install reached the HOST venv." >&2
    exit 1
  fi
  echo "   host: untouched ✅"
  echo
  echo "dependency isolation verified: per-container copy-on-write, no shared tree"
  exit 0
fi

# --- Dispatch ----------------------------------------------------------------
[ -n "$NUMBER" ] || usage
case "$NUMBER" in
  ''|*[!0-9]*) echo "run-agent.sh: '$NUMBER' is not an issue or PR number" >&2; exit 2 ;;
esac

CLONE_DIR="$CLONES_DIR/issue-$NUMBER"
CONTAINER="bess-agent-$NUMBER"

if podman container exists "$CONTAINER" 2>/dev/null; then
  echo "❌ container '$CONTAINER' already exists." >&2
  echo "   A live one is this issue's agent -- attach rather than starting a second:" >&2
  echo "     podman exec -it $CONTAINER claude --resume" >&2
  echo "   A dead one can be cleared with: podman rm $CONTAINER" >&2
  exit 1
fi

dispatch_ensure_clone "$CLONE_DIR"
dispatch_load_credentials dev || exit 1
dispatch_podman_socket || { echo "  Step 8 (local run & observe) needs it." >&2; exit 1; }
dispatch_ensure_image "$IMAGE" "$FORCE_BUILD"
mkdir -p "$FLEET_DIR"

dispatch_run_args "$CONTAINER" "$CLONE_DIR" dev "$EGRESS"

# `--dangerously-skip-permissions` is the phase's whole point -- see the header.
agent_cmd=(
  claude -p "/implement-issue $NUMBER"
  --dangerously-skip-permissions
  --output-format stream-json --verbose
)

if [ "$DRY_RUN" = true ]; then
  printf 'podman run'; printf ' %q' "${DISPATCH_RUN_ARGS[@]}" "$IMAGE" "${agent_cmd[@]}"; printf '\n'
  exit 0
fi

container_id=$(podman run "${DISPATCH_RUN_ARGS[@]}" "$IMAGE" "${agent_cmd[@]}")

# Register BEFORE anything else can fail. The branch is left empty on purpose:
# implement-issue Step 1 derives its name from the issue itself, so it is not
# knowable yet -- the agent reports it with `fleet-manifest.sh set-branch` once
# Step 4 has created it.
if ! "$MANIFEST" register "$CLONE_DIR" "$NUMBER" "" "$CONTAINER" dev; then
  echo "⚠️  container started but could not be registered -- stopping it rather than" >&2
  echo "   leaving an agent that nothing is tracking." >&2
  podman rm -f "$CONTAINER" >/dev/null 2>&1 || true
  exit 1
fi

cat <<EOF

🚀 dispatched $CONTAINER on #$NUMBER
   clone      $CLONE_DIR
              (a normal checkout -- cd there and test it yourself)
   container  ${container_id:0:12}
   logs       podman logs -f $CONTAINER
   attach     podman exec -it $CONTAINER claude --resume
   fleet      scripts/fleet-manifest.sh list
EOF
