#!/bin/bash

# Quality Check Script for BESS Manager
# Run this script before committing to ensure all files meet quality standards

set -e

echo "🔍 Running BESS Manager Quality Checks..."
echo "========================================"

# Check if we're in the right directory
if [ ! -f "CLAUDE.md" ]; then
    echo "❌ Error: Run this script from the project root directory"
    exit 1
fi

# Initialize counters
ERRORS=0
WARNINGS=0

# Resolve a Python tool: the project venv first, then PATH. Prints nothing and
# returns 1 when the tool is available in neither.
#
# The venv lookup matters because the documented way to run anything here is
# `.venv/bin/<tool>` (see CLAUDE.md) — a fresh git worktree has a .venv but
# usually no activated shell, so a bare `command -v pytest` finds nothing.
#
# A missing tool is an ERROR, not a warning: this script is the pre-commit
# gate, and skipping its three most important checks while printing
# "Errors: 0" reports success for a run that verified nothing. That is exactly
# how Black violations reached CI from a fresh worktree.
py_tool() {
    if [ -x ".venv/bin/$1" ]; then
        echo ".venv/bin/$1"
    elif command -v "$1" >/dev/null 2>&1; then
        echo "$1"
    else
        return 1
    fi
}

echo ""
echo "📋 Running Python tests..."
echo "---------------------------"

if PYTEST=$(py_tool pytest); then
    echo "🔸 Running fast tests (use '$PYTEST' directly to include slow algorithm tests)..."
    if ! "$PYTEST" -m "not slow" --tb=short -q; then
        echo "❌ Tests failed"
        ERRORS=$((ERRORS + 1))
    else
        echo "✅ Fast tests passed"
    fi
else
    echo "❌ pytest not found in .venv/bin or on PATH — cannot verify tests."
    echo "   Install with: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📋 Checking Python code quality..."
echo "-----------------------------------"

# Black and Ruff violations are ERRORs, not warnings: both are hard CI
# failures, so a gate that reports them as warnings and still exits 0 sends
# code to CI that is already known to fail.
#
# Check if Python files exist
if find . -name "*.py" -not -path "./build/*" -not -path "./.venv/*" -not -path "./frontend/node_modules/*" | grep -q .; then
    # Run Black formatting check
    if BLACK=$(py_tool black); then
        echo "🔸 Checking Black formatting..."
        if ! "$BLACK" --check . --exclude="/(build|\.venv|node_modules)/" >/dev/null 2>&1; then
            echo "❌ Black formatting issues found. Run: $BLACK ."
            ERRORS=$((ERRORS + 1))
        else
            echo "✅ Black formatting OK"
        fi
    else
        echo "❌ Black not found in .venv/bin or on PATH — cannot verify formatting."
        echo "   Install with: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
        ERRORS=$((ERRORS + 1))
    fi

    # Run Ruff linting check
    if RUFF=$(py_tool ruff); then
        echo "🔸 Checking Ruff linting..."
        if ! "$RUFF" check . --exclude="build,.venv,node_modules" >/dev/null 2>&1; then
            echo "❌ Ruff linting issues found. Run: $RUFF check --fix ."
            ERRORS=$((ERRORS + 1))
        else
            echo "✅ Ruff linting OK"
        fi
    else
        echo "❌ Ruff not found in .venv/bin or on PATH — cannot verify linting."
        echo "   Install with: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "ℹ️  No Python files found to check"
fi

echo ""
echo "📋 Checking TypeScript code quality..."
echo "--------------------------------------"

# Check if TypeScript files exist in frontend
if [ -d "frontend" ] && find frontend/src -name "*.ts" -o -name "*.tsx" 2>/dev/null | grep -q .; then
    cd frontend
    
    # Check if package.json exists
    if [ -f "package.json" ]; then
        # Run frontend tests
        if command -v npm >/dev/null 2>&1; then
            echo "🔸 Running frontend tests..."
            if npm test 2>/dev/null; then
                echo "✅ Frontend tests passed"
            else
                echo "❌ Frontend tests failed"
                ERRORS=$((ERRORS + 1))
            fi

            echo "🔸 Checking TypeScript compilation..."
            if npm run type-check >/dev/null 2>&1; then
                echo "✅ TypeScript compilation OK"
            else
                echo "⚠️  TypeScript compilation issues found. Run: npm run type-check"
                WARNINGS=$((WARNINGS + 1))
            fi
            
            # Check ESLint
            echo "🔸 Checking ESLint..."
            if npm run lint >/dev/null 2>&1; then
                echo "✅ ESLint OK"
            else
                echo "⚠️  ESLint issues found. Run: npm run lint:fix"
                WARNINGS=$((WARNINGS + 1))
            fi
        else
            echo "⚠️  npm not installed. Install Node.js and npm"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        echo "⚠️  No package.json found in frontend directory"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    cd ..
else
    echo "ℹ️  No TypeScript files found to check"
fi

echo ""
echo "📋 Checking scenario discovery coverage..."
echo "-------------------------------------------"

SCENARIO_DIR="scripts/mock_ha/scenarios"
MISSING_DISCOVERY=0
if [ -d "$SCENARIO_DIR" ]; then
    for f in "$SCENARIO_DIR"/ci-wizard-*.json; do
        name=$(basename "$f")
        if ! python3 -c "import json,sys; sys.exit(0 if 'expected_discovery' in json.load(open('$f')) else 1)" 2>/dev/null; then
            echo "❌ $name is missing expected_discovery section"
            MISSING_DISCOVERY=$((MISSING_DISCOVERY + 1))
        fi
    done
    if [ $MISSING_DISCOVERY -eq 0 ]; then
        echo "✅ All ci-wizard-* scenarios have expected_discovery"
    else
        echo "❌ $MISSING_DISCOVERY scenario(s) missing expected_discovery — add assertions before releasing"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "ℹ️  No scenario directory found"
fi

echo ""
echo "📋 Checking Markdown files..."
echo "------------------------------"

# Find project markdown files (exclude node_modules, build, .venv)
MD_FILES=$(find . -name "*.md" -not -path "./node_modules/*" -not -path "./build/*" -not -path "./.venv/*" -not -path "./frontend/node_modules/*" -not -path "./.git/*" -not -path "./.pytest_cache/*" 2>/dev/null | head -20)

if [ -n "$MD_FILES" ]; then
    echo "🔸 Found markdown files:"
    echo "$MD_FILES" | sed 's/^/  /'
    
    # Check for common markdown issues
    echo "🔸 Checking for common markdown issues..."
    
    # Check for trailing spaces
    if echo "$MD_FILES" | xargs grep -l " $" 2>/dev/null | grep -q .; then
        echo "⚠️  Files with trailing spaces found:"
        echo "$MD_FILES" | xargs grep -l " $" 2>/dev/null | sed 's/^/  /'
        WARNINGS=$((WARNINGS + 1))
    fi
    
    # Check for multiple consecutive blank lines
    if echo "$MD_FILES" | xargs grep -l "^$" 2>/dev/null | xargs grep -Pzo "\n\n\n" 2>/dev/null | grep -q .; then
        echo "⚠️  Files with multiple consecutive blank lines found"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    # Check for missing blank lines before headers
    HEADER_ISSUES=0
    for file in $MD_FILES; do
        if grep -Pzl ".*[^\n]\n#" "$file" 2>/dev/null; then
            HEADER_ISSUES=$((HEADER_ISSUES + 1))
        fi
    done
    
    if [ $HEADER_ISSUES -gt 0 ]; then
        echo "⚠️  $HEADER_ISSUES files with headers missing blank lines"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    if [ $WARNINGS -eq 0 ] || [ $HEADER_ISSUES -eq 0 ]; then
        echo "✅ Basic markdown formatting OK"
    fi
else
    echo "ℹ️  No markdown files found to check"
fi

echo ""
echo "📋 Summary"
echo "----------"
echo "Errors: $ERRORS"
echo "Warnings: $WARNINGS"

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo "🎉 All quality checks passed!"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo "⚠️  Quality checks completed with $WARNINGS warnings"
    echo "💡 Consider fixing warnings before committing"
    exit 0
else
    echo "❌ Quality checks failed with $ERRORS errors and $WARNINGS warnings"
    echo "🔧 Please fix all errors before committing"
    exit 1
fi