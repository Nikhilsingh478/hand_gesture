#!/bin/bash

# Move to the folder where this script lives
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Check Python 3 is available
if ! command -v python3 &> /dev/null; then
    osascript -e 'display alert "Python 3 not found" message "Please install Python 3 from https://python.org and try again."'
    exit 1
fi

# First run: create virtual environment and install dependencies
if [ ! -d "venv" ]; then
    echo "--------------------------------------------"
    echo "  First-time setup — installing dependencies"
    echo "  This takes ~1-2 minutes. Only happens once."
    echo "--------------------------------------------"
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip --quiet
    pip install -r requirements.txt
    echo ""
    echo "Setup complete! Starting app..."
    echo ""
else
    source venv/bin/activate
fi

# Launch the app
python3 main.py
