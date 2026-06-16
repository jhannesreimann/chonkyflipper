#!/usr/bin/env python3
"""
Shared utilities: API response helpers and sudo subprocess runner.
"""

import subprocess
from flask import jsonify


def api_success(data=None, code=200):
    """Return a standardised success response.
    Always includes 'success': True. Caller data is merged in."""
    if data is None:
        data = {}
    data['success'] = True
    return jsonify(data), code


def api_error(message, code=400):
    """Return a standardised error response.
    Always includes 'success': False and 'error'. """
    return jsonify({'success': False, 'error': str(message)}), code


def sudo_run(cmd, timeout=10, input_text=None, capture=True):
    """Run a shell command, optionally with sudo.
    Returns (stdout, stderr, returncode) tuple."""
    try:
        result = subprocess.run(
            cmd, capture_output=capture, text=True, timeout=timeout,
            input=input_text
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return '', 'Command timed out', 1
    except Exception as e:
        return '', str(e), 1
