#!/bin/bash

# Activate the virtual environment
source venv/bin/activate

set -a  # Automatically export all variables
source ./.env
set +a

if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Start the Flask server
python data_download.py >> data_download.log 2>&1