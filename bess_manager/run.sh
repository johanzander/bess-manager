#!/usr/bin/env bash
set -e

# Source bashio
if [ -f /usr/lib/bashio/bashio.sh ]; then
    echo "Sourcing bashio.sh..."
    # shellcheck disable=SC1091
    source /usr/lib/bashio/bashio.sh
    
    # Enable Home Assistant API
    export HA_TOKEN=$(bashio::config 'hassio_token')
    export HA_URL="http://supervisor/core"
    bashio::log.info "Starting BESS Manager..."
else
    echo "WARNING: bashio.sh not found. Using environment variables."
    # Environment variables should already be set by the Home Assistant add-on system
    echo "INFO: Starting BESS Manager with existing environment..."
fi

# Make sure Python path is set correctly
export PYTHONPATH="/app:${PYTHONPATH}"

# Start the application
cd /app
echo "Starting uvicorn..."
python -m uvicorn app:app --host 0.0.0.0 --port 8080
echo "uvicorn exited..."

