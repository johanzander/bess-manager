# BESS Manager Development Guide

This guide will help you set up a development environment for the BESS Battery Manager add-on and connect it to a local Home Assistant instance.

## Prerequisites

- Docker and Docker Compose installed
- VS Code with Remote-Containers extension (recommended)
- Home Assistant instance running locally (or accessible via network)
- A long-lived access token from Home Assistant

## Development Environment Setup

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/bess-manager.git
cd bess-manager
```

### 2. Create Environment File

Create a `.env` file in the root directory with the following content:

```
# Home Assistant connection
HA_URL=http://host.docker.internal:8123
HA_TOKEN=your_long_lived_access_token_here

# Development mode
FLASK_DEBUG=true

```

Replace `your_long_lived_access_token_here` with a token from your Home Assistant instance.

### 3. Start Development Container

```bash
docker-compose up -d
```

This will start a development container with the Flask app running.

### 4. Access the Application

The application will be available at:
- Flask API: http://localhost:8080
- Web interface: http://localhost:8080

### 5. Developing with VS Code

If you're using VS Code with Remote-Containers:

1. Open the project folder in VS Code
2. Click the green button in the bottom-left corner
3. Select "Remote-Containers: Reopen in Container"
4. VS Code will open a new window connected to the development container
5. You can now edit the code and the changes will be reflected immediately

## Debugging

The Flask app runs with debug mode enabled, so you'll see detailed error messages in the console.

To view logs:

```bash
docker-compose logs -f
```

## Home Assistant Access Token

To create a long-lived access token:

1. In Home Assistant, click on your user profile (bottom left)
2. Scroll down to "Long-Lived Access Tokens"
3. Click "Create Token", give it a name, and copy the token value

## Testing the API

You can test the API endpoints using curl:

```bash
# Check service health
curl http://localhost:8080/

# Get battery settings
curl http://localhost:8080/api/settings/battery

# Get schedule for today
curl http://localhost:8080/api/schedule/today

```

## Creating a Production Build

To build the add-on for production:

```bash
# Make the script executable
chmod +x package-addon.sh

# Run the script
./package-addon.sh
```

This will create a build in the `build/repository` directory that you can add to Home Assistant as a custom repository.

## Directory Structure

- `addon/` - Add-on files for Home Assistant
- `core/` - Core BESS system code
- `dev/` - Development environment files
- `build/` - Build output directory (created by package-addon.sh)

## Modifying the Frontend

The frontend is a single HTML file with inline JavaScript. To modify it:

1. Edit `addon/index.html`
2. The changes will be reflected when you refresh the browser

## Adding New Features

When adding new features, remember to:

1. Add appropriate API endpoints in `app.py`
2. Update the frontend to use the new endpoints
3. Test thoroughly in the development environment
4. Update the documentation in README.md

## Production Deployment

To deploy to a production Home Assistant instance:

1. Run `./package-addon.sh` to build the add-on
2. Copy the `build/repository` directory to a web server or GitHub repository
3. Add the repository URL to Home Assistant
4. Install the BESS Manager add-on from the Add-on Store

## Troubleshooting

### Connection Issues

If you have trouble connecting to Home Assistant:

1. Make sure your access token is valid
2. Check the `HA_URL` in your `.env` file
3. If running HA in Docker, ensure `host.docker.internal` resolves correctly

### Module Import Errors

If you see module import errors:

1. Make sure all required packages are in `requirements.txt`
2. Rebuild the container: `docker-compose down && docker-compose up -d`

### API Errors

If API calls return errors:

1. Check the logs for detailed error messages
2. Verify your Home Assistant has the required entities (Nordpool, Growatt)
3. Check permissions for your access token