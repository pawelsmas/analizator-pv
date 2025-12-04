#!/bin/bash
# Lint script for PV Optimizer
# Usage: ./scripts/lint.sh [--fix]

set -e

FIX_MODE=""
if [ "$1" == "--fix" ]; then
    FIX_MODE="--fix"
    echo "🔧 Running in FIX mode..."
else
    echo "🔍 Running in CHECK mode (use --fix to auto-fix)..."
fi

echo ""
echo "=========================================="
echo "📦 Python Linting (ruff)"
echo "=========================================="

if command -v ruff &> /dev/null; then
    if [ -n "$FIX_MODE" ]; then
        ruff check services/ --fix || true
        ruff format services/
    else
        ruff check services/ || true
        ruff format services/ --check || true
    fi
else
    echo "⚠️  ruff not installed. Install with: pip install ruff"
fi

echo ""
echo "=========================================="
echo "🌐 JavaScript Linting (ESLint)"
echo "=========================================="

if command -v npx &> /dev/null; then
    if [ -n "$FIX_MODE" ]; then
        npx eslint "services/frontend-*/**/*.js" --fix || true
    else
        npx eslint "services/frontend-*/**/*.js" || true
    fi
else
    echo "⚠️  npx not found. Install Node.js first."
fi

echo ""
echo "=========================================="
echo "✨ JavaScript Formatting (Prettier)"
echo "=========================================="

if command -v npx &> /dev/null; then
    if [ -n "$FIX_MODE" ]; then
        npx prettier --write "services/frontend-*/**/*.{js,css,html}" || true
    else
        npx prettier --check "services/frontend-*/**/*.{js,css,html}" || true
    fi
else
    echo "⚠️  npx not found. Install Node.js first."
fi

echo ""
echo "✅ Linting complete!"
