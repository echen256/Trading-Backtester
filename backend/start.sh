#!/bin/bash

# Activate the virtual environment
source venv/bin/activate

set -a  # Automatically export all variables
source ./.env
set +a

# Start the Flask server
python app.py