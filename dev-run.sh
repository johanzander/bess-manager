#!/bin/bash
# Developer startup script with continuous logs
#
# Container runtime: auto-detected (podman preferred, falls back to docker).
# Override with DOCKER=docker ./dev-run.sh if needed.
# When using podman, podman-compose is auto-installed into the venv if missing.
if [ -z "$DOCKER" ]; then
  if command -v podman >/dev/null 2>&1; then
    DOCKER="podman"
  else
    DOCKER="docker"
  fi
fi
COMPOSE="${COMPOSE:-${DOCKER} compose}"
# podman-compose uses a different binary name; auto-install it into the venv if missing.
if [ "$DOCKER" = "podman" ]; then
  if ! command -v podman-compose >/dev/null 2>&1; then
    echo "Installing podman-compose into venv..."
    .venv/bin/pip install --quiet podman-compose
  fi
  COMPOSE="podman-compose"
fi

echo "==== BESS Manager Development Environment Setup ===="
echo "Container runtime: $DOCKER"

# Derive a unique project name from the directory so multiple worktrees
# can run side-by-side without container name conflicts.
export COMPOSE_PROJECT_NAME="bess-$(basename "$(pwd)")"
echo "Compose project: $COMPOSE_PROJECT_NAME"

# Derive stable ports from the directory name so each worktree gets a
# predictable, unique port.  The hash maps any directory name into the
# 8080-8179 range (backend) with frontend at +1000.
# Override via BESS_DEV_PORT / BESS_FRONTEND_PORT in .env if needed.
if [ -z "$BESS_DEV_PORT" ]; then
  _hash=$(printf '%s' "$(basename "$(pwd)")" | cksum | awk '{print $1}')
  export BESS_DEV_PORT=$(( 8080 + _hash % 100 ))
  export BESS_FRONTEND_PORT=$(( BESS_DEV_PORT + 1000 ))
fi
export BESS_FRONTEND_PORT="${BESS_FRONTEND_PORT:-$(( BESS_DEV_PORT + 1000 ))}"

# Verify container runtime is available
if ! $DOCKER info > /dev/null 2>&1; then
  echo "Error: $DOCKER is not running."
  echo "Please start $DOCKER and try again."
  exit 1
fi

# Check if .env exists, if not prompt the user
if [ ! -f .env ]; then
  echo "Error: .env file not found."
  echo "Please create a .env file with HA_URL and HA_TOKEN defined."
  exit 1
fi

# Export environment variables from .env file (excluding comments and empty lines)
echo "Loading environment variables from .env..."
set -a  # automatically export all variables
source <(grep -v '^#' .env | grep -v '^$' | sed 's/^\s*//')
set +a  # stop automatically exporting

# Display which HA instance we're connecting to
echo "Connecting to Home Assistant at: $HA_URL"

# Check if token is still the default
if [[ "$HA_TOKEN" == "your_long_lived_access_token_here" ]]; then
  echo "Please edit .env file to add your Home Assistant token."
  exit 1
fi

# Ensure requirements.txt exists with needed packages
echo "Checking requirements.txt..."
if [ ! -f backend/requirements.txt ]; then
  echo "Please create requirements.txt in backend directory..."
  exit 1
fi

# Extract options from config.yaml to backend/dev-options.json for development
# Note: InfluxDB credentials are passed as environment variables, not in options.json
echo "Extracting development options from config.yaml..."
if [ -f config.yaml ]; then
  ./.venv/bin/python << 'EOF'
import yaml
import json

with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

options = config.get('options', {})

# Remove InfluxDB from options - credentials come from environment variables
if 'influxdb' in options:
    del options['influxdb']
    print("  → InfluxDB credentials will be loaded from environment variables")

with open('backend/dev-options.json', 'w') as f:
    json.dump(options, f, indent=2)

print("✓ Created backend/dev-options.json (simulates /data/options.json in HA)")
EOF
else
  echo "Warning: config.yaml not found in root directory"
fi

# Create dev settings from example template if missing (file is gitignored)
if [ ! -f backend/dev-bess-settings.json ]; then
  cp backend/dev-bess-settings.json.example backend/dev-bess-settings.json
  echo "✓ Created backend/dev-bess-settings.json from example template"
fi

# Pass host timezone to containers so log timestamps use local time
export TZ=${TZ:-Europe/Stockholm}

echo "Stopping any existing containers for this project..."
$COMPOSE down --remove-orphans 2>/dev/null

# Also remove any stale container with the target name (e.g. left over
# from a previous run or an older compose config without project naming).
CONTAINER_NAME="${COMPOSE_PROJECT_NAME}-dev"
if $DOCKER ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  echo "Removing stale container: $CONTAINER_NAME"
  $DOCKER rm -f "$CONTAINER_NAME" >/dev/null
fi

# Only rebuild frontend if source files changed since last build
FRONTEND_BUILD="frontend/dist"
if [ ! -d "$FRONTEND_BUILD" ] || [ -n "$(find frontend/src frontend/index.html frontend/vite.config.ts frontend/package.json -newer "$FRONTEND_BUILD" 2>/dev/null)" ]; then
  echo "Building frontend (changes detected)..."
  (cd frontend && npm run build)
else
  echo "Frontend unchanged, skipping build."
fi

echo "Building and starting development container..."
$COMPOSE up --build -d

echo "Waiting for BESS to start (following logs)..."
echo ""

print_banner() {
  echo ""
  echo "========================================================"
  echo "  BESS Manager running at: http://localhost:${BESS_DEV_PORT}"
  echo "========================================================"
  echo ""
}
trap 'print_banner; exit 0' INT

# Stream logs; print the banner once BESS is fully started (Uvicorn ready).
$COMPOSE logs -f --no-log-prefix 2>&1 | while IFS= read -r line; do
    echo "$line"
    if [[ "$line" == *"Uvicorn running on"* ]]; then
      print_banner
    fi
  done
