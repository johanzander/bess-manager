# BESS Manager Development Guide

This guide helps you set up a development environment for the BESS Battery Manager add-on.

## Development Environment Setup

### Prerequisites

- Docker and Docker Compose installed

- VS Code with Remote-Containers extension (recommended)

- Home Assistant instance (local or network-accessible)

- Python 3.11 or higher

- Node.js 18 or higher

- A long-lived access token from Home Assistant

### HomeAssistant Environment Options

The BESS Manager can be developed using either a local or production HomeAssistant instance:

#### Local Development

When running HomeAssistant locally (e.g., on `localhost:8123`):

- Set `HA_URL=http://localhost:8123` in `.env`

- No token is required when running both services locally

- Useful for rapid development and testing

#### Production Environment

When using a remote/production HomeAssistant:

- Set `HA_URL` to your HomeAssistant URL

- Generate and set a long-lived access token in `HA_TOKEN`

- Enables testing with real production data

Example `.env` configuration:

```bash

# Local development

HA_URL=http://localhost:8123
HA_TOKEN=  # Not needed for local development

# OR Production environment

HA_URL=https://your-ha-instance.com
HA_TOKEN=your_long_lived_access_token_here
```text

### Initial Setup

1. Clone the Repository:

   ```bash
   git clone https://github.com/johanzander/bess-manager.git
   cd bess-manager
```text

2. Create Environment File:

   ```bash

   # Create .env in root directory

   HA_URL=http://host.docker.internal:8123
   HA_TOKEN=your_long_lived_access_token_here
   FLASK_DEBUG=true
   PORT=8080

   # Optional database settings

   HA_DB_URL=http://homeassistant.local:8086/api/v2/query
   HA_DB_USER_NAME=your_db_username
   HA_DB_PASSWORD=your_db_password
```text

3. Install Dependencies:

   ```bash
   pip install -r backend/requirements.txt
   cd frontend && npm install && cd ..
```text

### Running the Development Environment

#### Option 1: Docker Development

1. Start the containers:

   ```bash
   docker-compose up -d
```text

2. Access the services:

   - API: [http://localhost:8080](http://localhost:8080)
   - Frontend: [http://localhost:8080](http://localhost:8080)

#### Option 2: Local Development

1. Start the backend:

   ```bash
   ./dev-run.sh
```text

2. Start the frontend (in a separate terminal):

   ```bash
   cd frontend
   npm run dev
```text

3. Access the services:

   - API: [http://localhost:8080](http://localhost:8080)
   - Frontend: [http://localhost:5173](http://localhost:5173)

### VS Code Integration

If using VS Code with Remote-Containers:

1. Open the project in VS Code

2. Click the remote connection button (bottom-left corner)

3. Select "Remote-Containers: Reopen in Container"

## Project Structure

```text
├── backend/           # FastAPI application and add-on config
├── core/             # Core BESS system implementation
│   └── bess/         # BESS-specific modules
│       ├── tests/    # Test directory
│       └── ...       # Implementation modules
├── frontend/         # React-based web interface
└── build/           # Build output (created by package-addon.sh)
    ├── bess_manager/ # Add-on build
    └── repository/   # Repository build
```text

## Development Workflow

### API Development

1. Add new endpoints in `backend/app.py`

2. Update OpenAPI spec if needed

3. Generate frontend API client:

   ```bash
   cd frontend
   npm run generate-api
```text

### Frontend Development

1. Navigate to `frontend/`

2. Make changes to React components

3. Changes hot-reload automatically

4. Build for production:

   ```bash
   npm run build
```text

### Testing

```bash

# Run all tests

pytest

# Run specific categories

pytest core/bess/tests/unit/
pytest core/bess/tests/integration/

# Run with coverage

pytest --cov=core.bess
```text

### Code Quality

```bash

# Format code

black .
ruff check --fix .

# Type checking

mypy .

# Run all pre-commit hooks

pre-commit run --all-files
```text

## Debugging

### Backend Debugging

- Logs are available via:

  ```bash
  docker-compose logs -f
```text

- Set `FLASK_DEBUG=true` in `.env` for debug mode

### Frontend Debugging

- Use browser developer tools

- React Developer Tools extension recommended

- Source maps enabled in development

### Common Issues

1. Connection Issues:

   - Verify access token validity

   - Check `HA_URL` configuration

   - Ensure Docker network connectivity

2. Import Errors:

   - Verify `requirements.txt` is complete

   - Rebuild container: `docker-compose down && docker-compose up -d`

3. API Errors:

   - Check logs for detailed messages

   - Verify required Home Assistant entities exist

   - Check access token permissions

## Building for Production

1. Make the package script executable:

   ```bash
   chmod +x package-addon.sh
```text

2. Build the add-on:

   ```bash
   ./package-addon.sh
```text

The build output will be in:

- `build/bess_manager/` - For local installation

- `build/repository/` - For custom repository distribution

For deployment instructions, see [DEPLOYMENT.md](DEPLOYMENT.md).
