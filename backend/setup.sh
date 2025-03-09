#!/bin/bash

# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies from requirements.txt
pip install -r requirements.txt

echo "Virtual environment setup complete. Run 'source venv/bin/activate' to activate it."