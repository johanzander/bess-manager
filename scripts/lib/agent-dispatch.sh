#!/usr/bin/env bash
#
# Shared plumbing for the two dispatchers, scripts/run-agent.sh (one container
# per issue, fire-and-forget) and scripts/run-po.sh (one long-lived
# product-owner container, looping forever).
#
# They differ in exactly three things -- clone name, lifetime, and the command
# the container runs. Everything else (where the main checkout is, the private
# clone, the role-scoped token, the podman socket, the run arguments) is
# identical, and lived in one script until the second one needed it.
#
# Sourced, never executed.

# Sibling scripts and the Containerfile are taken from THIS checkout, not from
# $MAIN_CHECKOUT. The two are usually the same directory, but not when
# dispatching from a worktree -- and resolving them against the main checkout
# means running whatever happens to be checked out on `main`, silently. That
# is not hypothetical: it ran main's argument-less worktree-setup.sh, which
# ignored --target-dir, cheerfully "set up" the dispatching worktree instead of
# the clone, and reported success. Data paths (.agent-clones, .fleet) stay
# under $MAIN_CHECKOUT, which is the whole point of resolving that separately.
DISPATCH_LIB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DISPATCH_SCRIPTS_DIR=$(dirname "$DISPATCH_LIB_DIR")
DISPATCH_REPO_ROOT=$(dirname "$DISPATCH_SCRIPTS_DIR")

# --- Paths -------------------------------------------------------------------
#
# The main checkout, resolved the way scripts/gh-agent.sh resolves .env, plus
# the correction scripts/fleet-manifest.sh documents: an agent's clone is an
# INDEPENDENT repository, so git-common-dir there points at the clone itself
# rather than back here. A linked worktree needs no correction -- its
# git-common-dir is already the main checkout's .git, which is why dispatching
# from a worktree (the normal case, since the maintainer is usually mid-task
# somewhere else) just works.
dispatch_resolve_paths() {
  local common_dir
  common_dir=$(git rev-parse --git-common-dir 2>/dev/null || echo "")
  if [ -z "$common_dir" ]; then
    echo "not in a git repository" >&2
    return 1
  fi

  MAIN_CHECKOUT=$(dirname "$(cd "$common_dir" && pwd)")
  case "$MAIN_CHECKOUT" in
    */.agent-clones/*) MAIN_CHECKOUT="${MAIN_CHECKOUT%%/.agent-clones/*}" ;;
  esac

  CLONES_DIR="$MAIN_CHECKOUT/.agent-clones"
  FLEET_DIR="$MAIN_CHECKOUT/.fleet"
  MANIFEST="$DISPATCH_SCRIPTS_DIR/fleet-manifest.sh"
}

# --- Image -------------------------------------------------------------------
dispatch_ensure_image() {
  local image="$1" force="${2:-false}"
  if [ "$force" = true ] || ! podman image exists "$image"; then
    echo "🔨 building $image -- dependencies are baked in, so this is minutes ONCE,"
    echo "   not ~35 per dispatch (see Containerfile.agent for why they cannot be"
    echo "   mounted from a macOS host into a Linux container)."
    podman build \
      -f "$DISPATCH_REPO_ROOT/Containerfile.agent" \
      -t "$image" \
      --build-arg "MAIN_CHECKOUT=$MAIN_CHECKOUT" \
      "$DISPATCH_REPO_ROOT"
  fi
}

# --- The private clone -------------------------------------------------------
#
# --reference sources objects from the main checkout, so this is fast and
# disk-cheap; --dissociate then cuts the tie, so a later `git gc` here can
# never reach into a running agent. The result is a fully independent .git --
# own refs, own index, own lockfiles -- which is the entire reason dispatched
# agents get clones instead of worktrees.
#
# An existing clone is REUSED, never re-cloned: implement-issue Step 0 treats
# prior work as something to resume, and a re-clone would discard commits that
# exist nowhere else. (One abandoned branch in this repo held 32 such commits.)
dispatch_ensure_clone() {
  local clone_dir="$1" origin_url

  if [ -d "$clone_dir/.git" ]; then
    echo "📁 reusing existing clone $clone_dir (resume, not restart)"
  else
    origin_url=$(git -C "$MAIN_CHECKOUT" remote get-url origin)
    echo "📁 cloning into $clone_dir"
    mkdir -p "$(dirname "$clone_dir")"
    git clone --reference "$MAIN_CHECKOUT" --dissociate \
      --branch main "$origin_url" "$clone_dir"
  fi

  # On the host these symlinks point at the macOS dependency trees, which is
  # what keeps the clone directly usable here (`cd .agent-clones/... &&
  # .venv/bin/pytest`). In the container the SAME symlinks resolve to the Linux
  # trees baked into the image at that identical path.
  "$DISPATCH_SCRIPTS_DIR/worktree-setup.sh" \
    --target-dir "$clone_dir" --main-checkout "$MAIN_CHECKOUT"
}

# --- Credentials -------------------------------------------------------------
#
# Role-scoped, from the main checkout's .env -- the same file and the same two
# variables scripts/gh-agent.sh already uses. The maintainer's own `gh auth`
# never enters a container.
dispatch_load_credentials() {
  local role="$1" env_file token_var

  env_file="${BESS_ENV_FILE:-$MAIN_CHECKOUT/.env}"
  if [ -f "$env_file" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi

  case "$role" in
    po)  DISPATCH_TOKEN="${BESS_PO_TOKEN:-}";    token_var=BESS_PO_TOKEN ;;
    dev) DISPATCH_TOKEN="${BESS_AGENT_TOKEN:-}"; token_var=BESS_AGENT_TOKEN ;;
    *)   echo "unknown role '$role' (expected dev or po)" >&2; return 2 ;;
  esac

  if [ -z "$DISPATCH_TOKEN" ]; then
    echo "$token_var is not set in $env_file" >&2
    return 1
  fi

  # The agent's own credential, as opposed to its GitHub one. Checked here
  # rather than discovered inside the container, where it surfaces minutes
  # later as an opaque `claude -p` failure.
  DISPATCH_AGENT_AUTH=()
  if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    DISPATCH_AGENT_AUTH+=(-e "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN")
  elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    DISPATCH_AGENT_AUTH+=(-e "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
  else
    echo "neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY is set in $env_file" >&2
    echo "  -- the container has no way to authenticate the agent itself." >&2
    return 1
  fi
}

# --- The podman socket -------------------------------------------------------
#
# NOT MOUNTED BY DEFAULT. The socket is authority over the whole podman host:
# whoever holds it can start sibling containers with arbitrary bind mounts,
# which reaches whatever host paths are mounted in them -- including the main
# checkout and the tokens in its .env (BESS_PO_TOKEN, BESS_AGENT_TOKEN, the
# agent's Claude auth). Siblings started through it also get no nftables egress
# allowlist, since that lives per network namespace. So the boundary is only as
# strong as the socket stays out: only a `--with-compose` dispatch gets it
# (`run-agent.sh --with-compose`), and only because Step 8 (local run &
# observe) -- standing the real stack up from inside the container -- cannot
# work any other way.
#
# Step 8 does that by talking to the podman that started it, so the compose
# stack comes up as SIBLING containers rather than nested ones.
#
# The path is reported by, and belongs to, the podman VM -- on macOS it does
# not exist on this filesystem at all, so `[ -S "$sock" ]` here is not a
# stricter check, it is a guaranteed false negative. Ask podman whether its own
# socket exists instead; it is the only party that can see it.
dispatch_podman_socket() {
  local info
  info=$(podman info --format '{{.Host.RemoteSocket.Path}} {{.Host.RemoteSocket.Exists}}' 2>/dev/null) || {
    echo "podman is not reachable -- is 'podman machine' running?" >&2
    return 1
  }

  DISPATCH_PODMAN_SOCK=${info% *}
  DISPATCH_PODMAN_SOCK=${DISPATCH_PODMAN_SOCK#unix://}

  if [ -z "$DISPATCH_PODMAN_SOCK" ] || [ "${info##* }" != "true" ]; then
    echo "podman reports no API socket at '${DISPATCH_PODMAN_SOCK:-<none>}'" >&2
    echo "  -- is 'podman machine' running?" >&2
    return 1
  fi
}

# --- Run arguments -----------------------------------------------------------
#
# THE CLONE IS MOUNTED AT ITS OWN HOST ABSOLUTE PATH, not at /workspace, and
# that is not cosmetic. Two things depend on it:
#   - the clone's `.venv -> <main-checkout>/.venv` symlinks resolve to the
#     Linux trees baked into the image at exactly that path;
#   - the compose file's RELATIVE volume paths, evaluated by the outer podman,
#     name the same real directory inside the container and out. Mounted at
#     /workspace they would name paths only this container can see, and every
#     service in the stack would come up with empty volumes.
#
# ~/.claude/jobs is deliberately NOT mounted. It is global host bookkeeping in
# an undocumented format, and N containers writing it concurrently is exactly
# the shared-mutable-state hazard this phase removes everywhere else. The fleet
# manifest is the source of truth for what is running.
dispatch_run_args() {
  local container="$1" clone_dir="$2" role="$3" egress="$4" with_compose="${5:-false}"

  DISPATCH_RUN_ARGS=(
    --name "$container"
    --detach
    --cap-add=NET_ADMIN
    -v "$clone_dir:$clone_dir"
    -v "$FLEET_DIR:/fleet"
    -w "$clone_dir"
    -e "GH_TOKEN=$DISPATCH_TOKEN"
    -e "BESS_FLEET_DB=/fleet/manifest.db"
    -e "BESS_FLEET_CONTAINER=$container"
    -e "BESS_FLEET_ROLE=$role"
    -e "BESS_EGRESS=$egress"
    -e "BESS_HEADLESS_MODE=1"
    "${DISPATCH_AGENT_AUTH[@]}"
  )

  # The clone carries the repo's tracked .claude/settings.json -- host-interactive
  # policy (ask rules for `gh api`, git-stash denials, the macOS sandbox block) that
  # has no meaning for a headless agent and stalls it: a headless ask is a hard
  # denial, and --dangerously-skip-permissions does NOT override project ask rules
  # (verified live on the first dispatch: implement-issue died on `gh api`). Shadow
  # the clone's file with a container-scoped, read-only bypass so the container sees
  # permissive policy while the host clone and interactive sessions keep the real one.
  if [ -f "$DISPATCH_REPO_ROOT/container/agent-settings.json" ]; then
    DISPATCH_RUN_ARGS+=(
      -v "$DISPATCH_REPO_ROOT/container/agent-settings.json:$clone_dir/.claude/settings.json:ro"
    )
  fi

  if [ "$with_compose" = true ]; then
    DISPATCH_RUN_ARGS+=(
      -v "$DISPATCH_PODMAN_SOCK:/run/podman/podman.sock"
      -e "CONTAINER_HOST=unix:///run/podman/podman.sock"
      -e "DOCKER_HOST=unix:///run/podman/podman.sock"
    )
  fi
}

# --dry-run output is pasted into an issue on a public repo to show what a
# dispatch would do. DISPATCH_RUN_ARGS carries the real credentials as
# `-e "KEY=value"` pairs (GH_TOKEN, the agent's Claude auth), so print redacted.
dispatch_print_run_args() {
  local a
  printf 'podman run'
  for a in "${DISPATCH_RUN_ARGS[@]}" "$@"; do
    case "$a" in
      GH_TOKEN=*|ANTHROPIC_API_KEY=*|CLAUDE_CODE_OAUTH_TOKEN=*)
        printf ' %q' "${a%%=*}=***" ;;
      *) printf ' %q' "$a" ;;
    esac
  done
  printf '\n'
}
