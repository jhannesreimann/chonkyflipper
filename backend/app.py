#!/usr/bin/env python3
"""
ChonkyFlipper Backend - Flask API Server
Mobile IoT Pentesting Rig Controller
"""

from flask import Flask
from flask_cors import CORS
from routes import register_blueprints

app = Flask(__name__)
CORS(app)

# Register all API route blueprints
register_blueprints(app)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
