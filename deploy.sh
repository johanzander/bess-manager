#!/bin/bash
# Script to deploy the BESS Manager add-on to a local Home Assistant instance

# Default target path, can be overridden by environment variable
TARGET_PATH=${TARGET_PATH:-"/Volumes/addons/bess_manager"}

if [ ! -d "$TARGET_PATH" ]; then
    echo "Error: Target directory $TARGET_PATH does not exist"
    echo "Please create the directory or set TARGET_PATH environment variable"
    exit 1
fi

# Auto-increment patch version if deploying same version
if [ -f "$TARGET_PATH/config.yaml" ]; then
    CURRENT_VERSION=$(grep "^version:" "$TARGET_PATH/config.yaml" | cut -d'"' -f2)
    BUILD_VERSION=$(grep "^version:" "config.dev.yaml" | cut -d'"' -f2)

    if [ "$CURRENT_VERSION" = "$BUILD_VERSION" ]; then
        echo "Same version detected ($BUILD_VERSION), auto-incrementing patch version..."

        # Extract version parts
        MAJOR=$(echo $BUILD_VERSION | cut -d. -f1)
        MINOR=$(echo $BUILD_VERSION | cut -d. -f2)
        PATCH=$(echo $BUILD_VERSION | cut -d. -f3)

        # Increment patch version (use 10# base to avoid octal interpretation of e.g. "0b9")
        if [[ "$PATCH" =~ ^([0-9]+b)([0-9]+)$ ]]; then
            # Beta version like "0b9" → "0b10"
            BETA_PREFIX="${BASH_REMATCH[1]}"
            BETA_NUM=$((10#${BASH_REMATCH[2]} + 1))
            NEW_PATCH="${BETA_PREFIX}${BETA_NUM}"
        else
            NEW_PATCH=$((10#$PATCH + 1))
        fi
        NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"

        echo "Updating version: $BUILD_VERSION → $NEW_VERSION"
        sed -i '' "s/version: \"$BUILD_VERSION\"/version: \"$NEW_VERSION\"/" config.dev.yaml
        echo "Updated config.dev.yaml"
    fi
fi

# Build first to ensure latest version
echo "Building add-on..."
./package-addon.sh

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
