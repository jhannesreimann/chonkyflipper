#!/usr/bin/env python3
"""
ChonkyFlipper Backend - Flask API Server
Mobile IoT Pentesting Rig Controller
"""

import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from routes import register_blueprints

app = Flask(__name__)

# Restrict CORS to same-origin in production (nginx serves the UI).
# In dev, Vite proxies /api so CORS is not needed.
CORS(app, resources={r'/api/*': {'origins': '*'}})

# --- Minimal API token authentication ---
# If /opt/chonkyflipper/config/api_token exists, all /api/ requests must
# include an X-API-Token header matching the file contents.
# If the file does not exist, auth is disabled (backward compatible).

_API_TOKEN = None
_TOKEN_FILE = '/opt/chonkyflipper/config/api_token'

def _load_api_token():
    global _API_TOKEN
    try:
        with open(_TOKEN_FILE) as f:
            _API_TOKEN = f.read().strip()
    except (OSError, IOError):
        _API_TOKEN = None

_load_api_token()


@app.before_request
def _check_api_token():
    if not _API_TOKEN:
        return None
    if not request.path.startswith('/api/'):
        return None
    token = request.headers.get('X-API-Token', '')
    if token == _API_TOKEN:
        return None
    return jsonify({'success': False, 'error': 'Unauthorized'}), 401


# Register all API route blueprints
register_blueprints(app)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG', '') == '1')
