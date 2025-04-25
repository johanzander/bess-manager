#!/bin/bash
# Setup linting and code quality tools for BESS Manager

set -e  # Exit on error

echo "=== Setting up code quality tools for BESS Manager ==="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required but not found. Please install Python 3 first."
    exit 1
fi

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "pip3 is required but not found. Please install pip3 first."
    exit 1
fi

# Check if Node.js is installed (for frontend linting)
if ! command -v node &> /dev/null; then
    echo "Node.js is required for frontend linting but not found."
    echo "Please install Node.js first if you want to lint frontend code."
    echo "Continuing with backend setup only..."
    SKIP_FRONTEND=true
else
    SKIP_FRONTEND=false
fi

# Install pre-commit
echo "Installing pre-commit..."
pip3 install pre-commit

# Install Python linters
echo "Installing Python linters..."
pip3 install black ruff mypy types-requests types-PyYAML

# Install frontend linters if Node.js is available
if [ "$SKIP_FRONTEND" = false ]; then
    echo "Installing frontend linters..."
    cd frontend
    npm install --save-dev eslint prettier \
        eslint-plugin-react \
        eslint-config-prettier \
        @typescript-eslint/eslint-plugin \
        @typescript-eslint/parser
    cd ..
fi

# Install pre-commit hooks
echo "Installing pre-commit hooks..."
pre-commit install

echo "Setting up git hook paths..."
git config core.hooksPath .git/hooks

echo ""
echo "=== Setup complete! ==="
echo "Code quality tools are now installed and configured."
echo "Pre-commit hooks will run automatically on git commit."
echo ""
echo "You can also run the checks manually with:"
echo "  - pre-commit run --all-files  # Run all checks on all files"
echo "  - pre-commit run              # Run checks only on staged files"
echo ""
echo "For frontend linting, you can also run:"
echo "  - cd frontend && npm run lint # Run ESLint"
echo "  - cd frontend && npm run format # Run Prettier"
