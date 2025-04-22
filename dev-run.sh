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

# Check if token is still the default
TOKEN=$(grep "HA_TOKEN" .env | cut -d'=' -f2)
if [[ "$TOKEN" == "your_long_lived_access_token_here" ]]; then
  echo "Please edit .env file to add your Home Assistant token."
  exit 1
fi

# Ensure requirements.txt exists with needed packages
echo "Checking requirements.txt..."
if [ ! -f backend/requirements.txt ]; then
  echo "Please create requirements.txt in backend directory..."
  exit 1
fi

echo "Stopping any existing containers..."
docker-compose down --remove-orphans

echo "Removing any existing containers to force rebuild..."
docker-compose rm -f

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