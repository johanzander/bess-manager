#!/bin/bash
# Script to deploy the BESS Manager add-on to a local Home Assistant instance

# Default target path, can be overridden by environment variable
TARGET_PATH=${TARGET_PATH:-"/Volumes/addons/bess_manager"}

if [ ! -d "$TARGET_PATH" ]; then
    echo "Error: Target directory $TARGET_PATH does not exist"
    echo "Please create the directory or set TARGET_PATH environment variable"
    exit 1
fi

# Append a local build number (X.Y.Z.N) to trigger HA update detection
# without modifying the real semver in bess_manager/config.yaml.
# The build number is written only to the build output config.
BASE_VERSION=$(grep "^version:" "bess_manager/config.yaml" | cut -d'"' -f2)
if [ -f "$TARGET_PATH/config.yaml" ]; then
    DEPLOYED_VERSION=$(grep "^version:" "$TARGET_PATH/config.yaml" | cut -d'"' -f2)
    # Extract local build number if present (e.g. "9.5.2.3" → 3)
    if [[ "$DEPLOYED_VERSION" =~ ^${BASE_VERSION}\.([0-9]+)$ ]]; then
        LOCAL_BUILD=$(( ${BASH_REMATCH[1]} + 1 ))
    elif [ "$DEPLOYED_VERSION" = "$BASE_VERSION" ]; then
        LOCAL_BUILD=1
    else
        LOCAL_BUILD=0
    fi
else
    LOCAL_BUILD=0
fi

if [ "$LOCAL_BUILD" -gt 0 ]; then
    DEPLOY_VERSION="${BASE_VERSION}.${LOCAL_BUILD}"
    echo "Local deploy version: $BASE_VERSION → $DEPLOY_VERSION"
else
    DEPLOY_VERSION="$BASE_VERSION"
    echo "Deploy version: $DEPLOY_VERSION"
fi

# Build first to ensure latest version
echo "Building add-on..."
./package-addon.sh

# Stamp the local build version into the built config (not the source file)
if [ "$DEPLOY_VERSION" != "$BASE_VERSION" ]; then
    sed -i '' "s/version: \"$BASE_VERSION\"/version: \"$DEPLOY_VERSION\"/" build/bess_manager/config.yaml
fi

echo "Deploying to $TARGET_PATH..."

# Backup existing config if it exists
if [ -f "$TARGET_PATH/config.yaml" ]; then
    echo "Backing up existing config.yaml..."
    cp "$TARGET_PATH/config.yaml" "$TARGET_PATH/config.yaml.backup"
fi

# Use rsync to exclude unwanted files and handle permissions better
# --inplace: avoid temp files (needed for SMB/mounted volumes)
# --no-times/--no-perms: don't try to set attributes the filesystem doesn't support
rsync -rv --delete --inplace --no-times --no-perms --no-owner --no-group \
  --exclude='.DS_Store' \
  --exclude='*.pyc' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='.git*' \
  --exclude='*.tmp' \
  --exclude='*.log' \
  --exclude='tests/' \
  --exclude='*/tests/' \
  build/bess_manager/ "$TARGET_PATH/"

# Restore user configuration from backup if it exists
if [ -f "$TARGET_PATH/config.yaml.backup" ]; then
    echo "Preserving user configuration..."

    # Extract user settings from backup
    INFLUX_URL=$(grep "url:" "$TARGET_PATH/config.yaml.backup" | head -1 | sed 's/.*url: *"//' | sed 's/".*//')
    INFLUX_USER=$(grep "username:" "$TARGET_PATH/config.yaml.backup" | head -1 | sed 's/.*username: *"//' | sed 's/".*//')
    INFLUX_PASS=$(grep "password:" "$TARGET_PATH/config.yaml.backup" | head -1 | sed 's/.*password: *"//' | sed 's/".*//')
    CONFIG_ENTRY_ID=$(grep "config_entry_id:" "$TARGET_PATH/config.yaml.backup" | sed 's/.*config_entry_id: *"//' | sed 's/".*//')

    # Only update if values are not defaults
    if [ "$INFLUX_URL" != "http://homeassistant.local:8086/api/v2/query" ]; then
        sed -i '' "s|url: \"http://homeassistant.local:8086/api/v2/query\"|url: \"$INFLUX_URL\"|" "$TARGET_PATH/config.yaml"
        echo "  - Restored InfluxDB URL"
    fi

    if [ "$INFLUX_USER" != "your_db_username_here" ]; then
        sed -i '' "s/username: \"your_db_username_here\"/username: \"$INFLUX_USER\"/" "$TARGET_PATH/config.yaml"
        echo "  - Restored InfluxDB username"
    fi

    if [ "$INFLUX_PASS" != "your_db_password_here" ]; then
        sed -i '' "s/password: \"your_db_password_here\"/password: \"$INFLUX_PASS\"/" "$TARGET_PATH/config.yaml"
        echo "  - Restored InfluxDB password"
    fi

    if [ ! -z "$CONFIG_ENTRY_ID" ] && [ "$CONFIG_ENTRY_ID" != "01K3Y99FD3MDZYVFX2XSWR4888" ]; then
        sed -i '' "s/config_entry_id: \"01K3Y99FD3MDZYVFX2XSWR4888\"/config_entry_id: \"$CONFIG_ENTRY_ID\"/" "$TARGET_PATH/config.yaml"
        echo "  - Restored Nordpool config entry ID"
    fi

    # Clean up backup
    rm "$TARGET_PATH/config.yaml.backup"
fi

echo "Deployment complete!"

# Check if version was updated
if [ -f "$TARGET_PATH/config.yaml" ]; then
    VERSION=$(grep "^version:" "$TARGET_PATH/config.yaml" | cut -d' ' -f2 | tr -d '"')
    echo "Deployed version: $VERSION"
    echo ""
    echo "📋 Next steps:"
    echo "1. Go to Home Assistant → Settings → Add-ons"
    echo "2. Find 'BESS Manager' add-on"
    echo "3. Click 'Reload' or restart the add-on"
    echo "4. Verify version shows: $VERSION"
else
    echo "⚠️  Could not verify deployment version"
fi
