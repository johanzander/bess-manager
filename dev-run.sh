#!/bin/bash
# Developer startup script with continuous logs

echo "==== BESS Manager Development Environment Setup ===="

# Verify Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "Error: Docker is not running."
  echo "Please start Docker and try again."
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

# Extract options to backend/dev-options.json for development
# Prefers myconfig.yaml (personal, gitignored) over config.yaml (add-on manifest)
# Note: InfluxDB credentials are passed as environment variables, not in options.json
echo "Extracting development options..."
if [ -f myconfig.yaml ]; then
  echo "  Using myconfig.yaml (personal config)"
  CONFIG_FILE=myconfig.yaml
elif [ -f config.yaml ]; then
  echo "  Using config.yaml (add-on defaults)"
  CONFIG_FILE=config.yaml
else
  echo "Warning: No config file found in root directory"
  CONFIG_FILE=""
fi

if [ -n "$CONFIG_FILE" ]; then
  ./.venv/bin/python << EOF
import yaml
import json

with open('$CONFIG_FILE', 'r') as f:
    config = yaml.safe_load(f)

# myconfig.yaml has settings at root level; config.yaml nests them under 'options'
options = config.get('options', config)

# Remove InfluxDB from options - credentials come from environment variables
if 'influxdb' in options:
    del options['influxdb']
    print("  → InfluxDB credentials will be loaded from environment variables")

# Remove non-option keys that may be present in config.yaml (add-on metadata)
for key in ['name', 'description', 'version', 'slug', 'init', 'arch', 'startup',
            'boot', 'ports', 'ingress', 'ingress_port', 'panel_icon', 'panel_title',
            'panel_admin', 'hassio_api', 'homeassistant_api', 'auth_api', 'schema']:
    options.pop(key, None)

with open('backend/dev-options.json', 'w') as f:
    json.dump(options, f, indent=2)

print("✓ Created backend/dev-options.json (simulates /data/options.json in HA)")
EOF
fi

echo "Stopping any existing containers..."
docker-compose down --remove-orphans

echo "Removing any existing containers to force rebuild..."
docker-compose rm -f

echo "Building frontend..."
(cd frontend && npm run build)

echo "Building and starting development container with Python 3.10..."
docker-compose up --build -d

# Wait a moment for container to be ready
echo "Waiting for container to start..."
sleep 5

echo -e "\n==== CHECKING PYTHON VERSION IN CONTAINER ===="
docker-compose exec bess-dev python --version

echo -e "\n==== INITIAL CONTAINER LOGS ===="
docker-compose logs --no-log-prefix

echo -e "\nAccess the web interface at http://localhost:8080 once the app is running correctly."
echo -e "Following container logs now... (Press Ctrl+C to stop)\n"

# Follow the logs continuously
docker-compose logs -f --no-log-prefix
