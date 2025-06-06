#!/bin/bash
# Script to deploy the BESS Manager add-on to a local Home Assistant instance

# Default target path, can be overridden by environment variable
TARGET_PATH=${TARGET_PATH:-"/Volumes/addons/bess_manager"}

if [ ! -d "$TARGET_PATH" ]; then
    echo "Error: Target directory $TARGET_PATH does not exist"
    echo "Please create the directory or set TARGET_PATH environment variable"
    exit 1
fi

echo "Deploying to $TARGET_PATH..."
cp -r build/bess_manager/* "$TARGET_PATH/"
echo "Deployment complete!"
