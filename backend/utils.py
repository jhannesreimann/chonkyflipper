#!/usr/bin/env python3
"""
Shared utilities: API response helpers, request validation, subprocess runner,
and SyncTask for background sync operations.
"""

import subprocess
import threading
from flask import jsonify


def api_success(data=None, code=200):
    """Return a standardised success response.
    Always includes 'success': True. Caller data is merged in (non-mutating)."""
    if data is None:
        data = {}
    payload = dict(data)
    payload['success'] = True
    return jsonify(payload), code


def api_error(message, code=400):
    """Return a standardised error response.
    Always includes 'success': False and 'error'. """
    return jsonify({'success': False, 'error': str(message)}), code


def api_from_result(result, error_code=500, success_code=200):
    """Convert a module result dict into an API response.
    If result['success'] is truthy, return api_success(result, success_code).
    Otherwise return api_error(result.get('error', 'Failed'), error_code)."""
    if result.get('success'):
        return api_success(result, success_code)
    return api_error(result.get('error', 'Failed'), error_code)


def parse_int(value, default, min_val=None, max_val=None):
    """Parse an integer from a request value with bounds checking."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if min_val is not None:
        result = max(result, min_val)
    if max_val is not None:
        result = min(result, max_val)
    return result


def parse_float(value, default, min_val=None, max_val=None):
    """Parse a float from a request value with bounds checking."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if min_val is not None:
        result = max(result, min_val)
    if max_val is not None:
        result = min(result, max_val)
    return result


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


class SyncTask:
    """Manages a background sync operation with progress tracking.

    Usage in a route module:
        _sync = SyncTask()

        @bp.route('/sync/start', methods=['POST'])
        def sync_start():
            return _sync.start(lambda syncer: syncer.sync(progress_callback=_sync.callback))

        @bp.route('/sync/status', methods=['GET'])
        def sync_status():
            return _sync.status()
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._task = {'running': False, 'progress': 0, 'total': 0, 'current': ''}

    def callback(self, progress, total, current=''):
        """Progress callback compatible with sync engines."""
        with self._lock:
            self._task['progress'] = progress
            self._task['total'] = total
            self._task['current'] = current

    def start(self, fn):
        """Start fn in a background thread. fn receives no arguments.
        Returns api_error if already running, api_success if started."""
        with self._lock:
            if self._task['running']:
                return api_error('Sync already in progress', 400)
            self._task = {'running': True, 'progress': 0, 'total': 0, 'current': ''}

        def _run():
            try:
                result = fn()
                with self._lock:
                    self._task['result'] = result
            except Exception as e:
                with self._lock:
                    self._task['error'] = str(e)
            finally:
                with self._lock:
                    self._task['running'] = False

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return api_success({'status': 'started'})

    def status(self):
        """Return current sync status as an API response."""
        with self._lock:
            return api_success(dict(self._task))
