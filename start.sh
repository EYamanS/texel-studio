#!/bin/bash
# Texel Studio — one-command setup & start
set -e

cd "$(dirname "$0")"

# Python venv
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

# Python dependencies
echo "Installing Python dependencies..."
pip install -q -r requirements.txt

# .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from .env.example"
    echo "Edit .env with your API keys before generating."
    echo ""
fi

# Frontend build
if [ ! -d "static/_next" ] || [ "frontend/src" -nt "static/index.html" ] 2>/dev/null; then
    echo "Building frontend..."
    cd frontend
    npm install --silent
    npm run build 2>/dev/null
    cd ..
fi

echo ""
echo "Starting Texel Studio..."
echo "Open http://localhost:8500"
echo ""
python3 server.py
