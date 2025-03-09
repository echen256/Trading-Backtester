from flask import Flask
from flask_cors import CORS

# Initialize the Flask app
app = Flask(__name__)
CORS(app)
# Import routes
from app import routes