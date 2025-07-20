#!/bin/bash

# Activate the virtual environment
cd ./backend
source venv/bin/activate

set -a  # Automatically export all variables
source ./.env
set +a

if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

cd ./app/data_download
# Start the Flask server
python data_download.py >> ./../../logs/data_download.log 2>&1