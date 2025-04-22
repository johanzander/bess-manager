#!/bin/bash
# Script to build and package the BESS add-on for Home Assistant

set -e

echo "Building BESS Manager add-on for Home Assistant..."

# Create build directory
BUILD_DIR="./build/bess_manager"
mkdir -p "$BUILD_DIR"

# Build frontend
echo "Building frontend..."
cd frontend
npm ci
npm run build
cd ..

# Copy base files - make sure these match what Dockerfile expects
cp backend/Dockerfile "$BUILD_DIR/Dockerfile"
cp backend/app.py "$BUILD_DIR/app.py"
cp backend/log_config.py "$BUILD_DIR/log_config.py"
cp backend/requirements.txt "$BUILD_DIR/requirements.txt"
cp backend/run.sh "$BUILD_DIR/run.sh"
cp backend/config.yaml "$BUILD_DIR/config.yaml"
cp README.md "$BUILD_DIR/README.md"

# Copy core files
mkdir -p "$BUILD_DIR/core"
cp -r core/* "$BUILD_DIR/core/"

# Copy frontend files
mkdir -p "$BUILD_DIR/frontend"
cp -r frontend/dist/* "$BUILD_DIR/frontend/"

# Create repository structure
REPO_DIR="./build/repository"
mkdir -p "$REPO_DIR/bess_manager"
cp -r "$BUILD_DIR"/* "$REPO_DIR/bess_manager/"

# Create repository.json
cat > "$REPO_DIR/repository.json" << EOF
{
  "name": "BESS Battery Manager Repository",
  "url": "https://github.com/johanzander/bess-manager",
  "maintainer": "Johan Zander <johanzander@gmail.com>"
}
EOF

echo "Add-on built successfully!"