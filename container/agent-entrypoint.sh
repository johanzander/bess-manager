#!/usr/bin/env bash
#
# PID 1 for a dispatched-agent container (Containerfile.agent).
#
# Two jobs, then it gets out of the way:
#   1. Apply the egress allowlist, so a permissive in-container permission mode
#      still cannot reach arbitrary hosts.
#   2. Make the bind-mounted clone usable as a git repo (it is owned by the
#      host user, whose uid means nothing in here).
#
# EGRESS. The design says "network egress limited to GitHub, the Claude API,
# and the router endpoint". nftables filters by address, not by name, so the
# allowlist is resolved to addresses at start and RE-resolved on an interval --
# every host here is behind a CDN whose addresses rotate, and a set populated
# once would start failing requests hours into a long-lived container for
# reasons that look nothing like a firewall. DNS itself stays open (a resolver
# reachable only through the allowlist could never populate it); that leaves a
# DNS-shaped side channel, which is a deliberate, documented trade rather than
# an oversight.
#
# BESS_EGRESS=open disables the whole thing. It exists because a container that
# cannot reach something it needs fails in ways that read as anything but a
# firewall -- when a dispatch dies confusingly, re-running it open is the
# fastest way to rule this out.
#
set -euo pipefail

EGRESS_MODE="${BESS_EGRESS:-restricted}"
REFRESH_INTERVAL="${BESS_EGRESS_REFRESH_SECONDS:-60}"

# Everything a dispatched agent legitimately talks to.
#   github.com/api./codeload./*.githubusercontent.com -- clone, push, gh, PRs
#   api.anthropic.com                                 -- the agent itself
#   pypi/files.pythonhosted/registry.npmjs            -- a task that genuinely
#       changes requirements.txt or package.json installs into its own layer
#       (see Containerfile.agent); with these blocked that task cannot run at
#       all, and the failure would look like a broken lockfile
#   host.containers.internal                          -- the shared
#       claude-code-router instance, when Phase 2 lands. Allowed now because
#       the container's network policy is a Phase 1 decision.
DEFAULT_ALLOW_HOSTS="
github.com
api.github.com
codeload.github.com
objects.githubusercontent.com
raw.githubusercontent.com
uploads.github.com
api.anthropic.com
statsig.anthropic.com
pypi.org
files.pythonhosted.org
registry.npmjs.org
cdn.playwright.dev
playwright.azureedge.net
host.containers.internal
"
ALLOW_HOSTS="${BESS_EGRESS_HOSTS:-$DEFAULT_ALLOW_HOSTS}"

resolve_into_sets() {
  local host v4 v6
  v4=""
  v6=""
  for host in $ALLOW_HOSTS; do
    while read -r addr _; do
      case "$addr" in
        *:*) v6="$v6 $addr," ;;
        *)   v4="$v4 $addr," ;;
      esac
    done < <(getent ahosts "$host" 2>/dev/null | awk '{print $1}' | sort -u)
  done

  # A flush+re-add per refresh, not incremental adds: an address that stopped
  # being an answer should stop being allowed.
  nft flush set inet egress allowed4 2>/dev/null || true
  nft flush set inet egress allowed6 2>/dev/null || true
  [ -n "$v4" ] && nft add element inet egress allowed4 "{ ${v4%,} }" 2>/dev/null || true
  [ -n "$v6" ] && nft add element inet egress allowed6 "{ ${v6%,} }" 2>/dev/null || true
}

apply_egress_allowlist() {
  # policy drop on output, with the usual three exemptions: loopback,
  # already-established flows, and DNS.
  #
  # `|| return 1` is load-bearing, not decoration. `set -e` is suspended inside
  # a function used as an `if` condition, so without it a failed ruleset load
  # (no NET_ADMIN: "netlink: cache initialization failed") falls through to the
  # resolver, whose own failures are all tolerated, and the function returns 0
  # -- announcing a restricted container that has full egress. Observed exactly
  # once, here, before this line existed.
  nft -f - <<'RULES' || return 1
table inet egress {
  set allowed4 { type ipv4_addr; }
  set allowed6 { type ipv6_addr; }

  chain output {
    type filter hook output priority 0; policy drop;

    oif "lo" accept
    ct state established,related accept
    udp dport 53 accept
    tcp dport 53 accept

    ip  daddr @allowed4 accept
    ip6 daddr @allowed6 accept
  }
}
RULES

  resolve_into_sets

  # Re-resolve forever. Backgrounded and detached: this must not hold up the
  # agent, and its death must not take the container with it.
  (
    while sleep "$REFRESH_INTERVAL"; do
      resolve_into_sets
    done
  ) &
}

case "$EGRESS_MODE" in
  restricted)
    if apply_egress_allowlist; then
      echo "🔒 egress restricted to the allowlist (BESS_EGRESS=open to disable)" >&2
    else
      # Loud and fatal. Silently continuing would leave a container the
      # maintainer believes is network-isolated with full egress -- the one
      # failure mode worth refusing to start over.
      echo "❌ could not apply the egress allowlist (nftables needs --cap-add=NET_ADMIN)." >&2
      echo "   Refusing to start unrestricted. Re-run with BESS_EGRESS=open to accept that." >&2
      exit 1
    fi
    ;;
  open)
    echo "🌐 egress unrestricted (BESS_EGRESS=open)" >&2
    ;;
  *)
    echo "❌ unknown BESS_EGRESS='$EGRESS_MODE' (expected restricted or open)" >&2
    exit 2
    ;;
esac

# --- Hand over to the agent user ---------------------------------------------
#
# Everything above needed root (NET_ADMIN for the ruleset). Everything below
# must NOT have it: Claude Code refuses to run --dangerously-skip-permissions
# as root, and that flag is the point of this container.
AGENT_USER="${BESS_AGENT_USER:-agent}"
AGENT_HOME="/home/$AGENT_USER"
AGENT_UID=$(id -u "$AGENT_USER")
AGENT_GID=$(id -g "$AGENT_USER")

# The config below belongs to the agent user, so write it into ITS home rather
# than root's -- files under /root would simply not be read after the drop.
#
# safe.directory: the bind-mounted clone's files carry a uid that is not git's
# idea of "mine", and without this every git command fails at once as "dubious
# ownership".
{
  printf '[safe]\n\tdirectory = %s\n\tdirectory = *\n' "$PWD"
  # gh reads GH_TOKEN directly; git needs telling. The role-scoped token is
  # injected by scripts/run-agent.sh and is never the maintainer's own.
  if [ -n "${GH_TOKEN:-}" ]; then
    printf '[credential "https://github.com"]\n\thelper = !f() { echo "username=x-access-token"; echo "password=$GH_TOKEN"; }; f\n'
  fi
} > "$AGENT_HOME/.gitconfig"

# Workspace trust. Without it Claude Code ignores the project's own
# .claude/settings.json entirely -- "Ignoring 42 permissions.allow entries from
# .claude/settings.json: this workspace has not been trusted" -- and there is
# nobody here to accept a dialog. The clone's path is per-dispatch, so this
# cannot be baked into the image.
printf '{"projects": {"%s": {"hasTrustDialogAccepted": true}}}\n' "$PWD" \
  > "$AGENT_HOME/.claude.json"

chown -R "$AGENT_UID:$AGENT_GID" "$AGENT_HOME"

exec setpriv --reuid="$AGENT_UID" --regid="$AGENT_GID" --init-groups \
  env "HOME=$AGENT_HOME" "USER=$AGENT_USER" "$@"
