#!/bin/bash
# InspectorPro - Development Environment Setup & Start Script
# This script installs dependencies and starts the FastAPI server.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "  InspectorPro - Development Setup"
echo "========================================="
echo ""

# Check Python version
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "ERROR: Python 3.10+ is required but not found."
    echo "Please install Python from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "Found Python: $PYTHON_VERSION"

# Check for .env file
if [ ! -f ".env" ]; then
    echo ""
    echo "WARNING: .env file not found!"
    echo "Create a .env file with:"
    echo "  ANTHROPIC_API_KEY=your_key_here"
    echo "  OPENAI_API_KEY=your_key_here"
    echo ""
fi

# Check for inspection library
if [ ! -d "400S_Sorted_Library" ]; then
    echo ""
    echo "WARNING: 400S_Sorted_Library/ directory not found!"
    echo "The inspection engine requires this directory with inspection profiles."
    echo ""
fi

# Install dependencies
echo ""
echo "Installing Python dependencies..."
$PYTHON_CMD -m pip install --quiet --upgrade pip
$PYTHON_CMD -m pip install --quiet fastapi "uvicorn[standard]" python-multipart python-dotenv
$PYTHON_CMD -m pip install --quiet -r requirements.txt 2>/dev/null || true
echo "Dependencies installed."

# Start the server
echo ""
echo "========================================="
echo "  Starting InspectorPro Server"
echo "========================================="
echo ""
echo "  URL:  http://localhost:8000"
echo "  API:  http://localhost:8000/api/profiles"
echo "  Docs: http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop the server."
echo "========================================="
echo ""

$PYTHON_CMD -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
