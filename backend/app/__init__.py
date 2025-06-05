from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from dotenv import load_dotenv, find_dotenv
import os
from pathlib import Path

# Automatically find and load .env file
load_dotenv(find_dotenv())

# Initialize the Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
CORS(app, cors_allowed_origins="*")

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Import routes
from app import routes
