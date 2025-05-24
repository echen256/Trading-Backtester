from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv, find_dotenv
import os
from pathlib import Path

# Automatically find and load .env file
load_dotenv(find_dotenv())

# Initialize the Flask app
app = Flask(__name__)
CORS(app)

# Import routes
from app import routes
