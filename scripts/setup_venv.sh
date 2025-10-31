#!/bin/bash

# Coralogix DR Tool - Virtual Environment Setup Script

set -e  # Exit on any error

echo "Setting up Python virtual environment for Coralogix DR Tool..."

# Check if Python 3.9+ is available
python_version=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
required_version="3.10"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "Error: Python 3.10+ is required. Found: $python_version"
    exit 1
fi

echo "Python version check passed: $python_version"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
else
    echo "Virtual environment already exists."
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# Create necessary directories
echo "Creating project directories..."
mkdir -p logs/parsing-rules
mkdir -p logs/recording-rules
mkdir -p logs/enrichments
mkdir -p logs/events2metrics
mkdir -p logs/custom-dashboards
mkdir -p logs/grafana-dashboards
mkdir -p logs/views
mkdir -p logs/custom-actions
mkdir -p logs/webhooks
mkdir -p logs/alerts
mkdir -p logs/slo
mkdir -p logs/main

mkdir -p state
mkdir -p snapshots
mkdir -p outputs
mkdir -p backups

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "Please edit .env file with your API keys and configuration."
else
    echo ".env file already exists."
fi

echo ""
echo "Setup complete! 🎉"
echo ""
echo "Next steps:"
echo "1. Activate the virtual environment: source .venv/bin/activate"
echo "2. Edit .env file with your API keys"
echo "3. Run the tool: python dr-tool.py parsing-rules --dry-run"
echo ""
