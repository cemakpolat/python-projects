#!/bin/bash

set -e

VENV_DIR="./venv"
REQUIREMENTS_FILE="requirements.txt"
SCRIPT="service_monitor.py"
DOCKER_COMPOSE_FILE="docker-compose.yml"

# --- Pre-checks ---

echo "🔍 Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3."
    exit 1
fi

if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 is not installed. Please install pip."
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please run: ./prepare.sh"
    exit 1
fi

if ! docker compose version &> /dev/null && ! docker-compose version &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please run: ./prepare.sh"
    exit 1
fi

# --- Start Docker Compose if needed ---
if [ -f "$DOCKER_COMPOSE_FILE" ]; then
    echo "🐳 Starting Docker Compose services..."
    docker compose up -d
else
    echo "⚠️ No $DOCKER_COMPOSE_FILE found. Skipping Docker Compose startup."
fi

# --- Set up virtual environment ---

if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r "$REQUIREMENTS_FILE"

# --- Load environment variables if .env exists ---
if [ -f .env ]; then
    echo "📄 Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

# --- Run monitor script ---
echo "🚀 Starting service monitor with sudo..."
sudo "$VENV_DIR/bin/python" "$SCRIPT"
