"""
BadUSB payload library, filesystem listing, execution, sync, and auto-fire.
"""

import os
import threading
import time
from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error

bp = Blueprint('badusb', __name__, url_prefix='/api')


# lazy DB helpers

_db = None
_sync = None
_sync_lock = threading.Lock()
_sync_task = {'running': False, 'progress': 0, 'total': 0, 'current': ''}


def _get_db():
    global _db
    if _db is None:
        from modules.badusb.db import BadUSBDB
        _db = BadUSBDB()
        _db.init_db()
        # Auto-seed from filesystem on first init if empty
        if _db.get_stats().get('total', 0) == 0:
            from config import PAYLOADS_DIR
            _db.seed_from_filesystem(PAYLOADS_DIR)
    return _db


def _get_sync():
    global _sync
    if _sync is None:
        from modules.badusb.sync import BadUSBSync
        _sync = BadUSBSync(_get_db())
    return _sync


# filesystem payloads

@bp.route('/badusb/payloads', methods=['GET'])
def badusb_list_payloads():
    badusb = get_module('badusb')
    return api_success(badusb.list_payloads())


@bp.route('/badusb/execute', methods=['POST'])
def badusb_execute():
    """Execute a payload by filesystem name or by DB id + inline content."""
    data = request.json or {}
    badusb = get_module('badusb')
    layout = data.get('layout')

    # DB payload: execute by id (fetches content from DB)
    payload_id = data.get('id')
    if payload_id is not None:
        try:
            payload_id = int(payload_id)
        except (TypeError, ValueError):
            return api_error('id must be an integer', 400)
        db = _get_db()
        p = db.get_payload(payload_id)
        if not p:
            return api_error('Payload not found', 404)
        result = badusb.execute_content(
            p['content'],
            layout=layout or p.get('layout', 'us'),
            label=p.get('name', f'payload #{payload_id}'))
        return api_success(result) if result.get('success') else api_error(
            result.get('error', 'Failed'), 500)

    # Inline content: execute raw DuckyScript
    content = data.get('content')
    if content:
        result = badusb.execute_content(
            content,
            layout=layout,
            label=data.get('label', 'inline'))
        return api_success(result) if result.get('success') else api_error(
            result.get('error', 'Failed'), 500)

    # Filesystem payload: execute by name
    payload_name = data.get('payload')
    if not payload_name:
        return api_error('payload name, id, or content required', 400)
    result = badusb.execute_payload(payload_name, layout=layout)
    return api_success(result) if result.get('success') else api_error(
        result.get('error', 'Failed'), 500)


# library (DB-backed)

@bp.route('/badusb/library/os', methods=['GET'])
def badusb_library_os():
    db = _get_db()
    os_types = db.get_os_types()
    return api_success({'os_types': os_types})


@bp.route('/badusb/library/categories', methods=['GET'])
def badusb_library_categories():
    os_slug = request.args.get('os')
    db = _get_db()
    categories = db.get_categories(os_slug=os_slug if os_slug else None)
    return api_success({'categories': categories})


@bp.route('/badusb/library/payloads', methods=['GET'])
def badusb_library_payloads():
    os_slug = request.args.get('os')
    category_slug = request.args.get('category')
    try:
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(request.args.get('limit', 100))
    except (TypeError, ValueError):
        limit = 100

    db = _get_db()
    payloads = db.get_payloads(os_slug=os_slug, category_slug=category_slug,
                               offset=offset, limit=limit)
    return api_success({'payloads': payloads})


@bp.route('/badusb/library/payload/<int:payload_id>', methods=['GET'])
def badusb_library_payload(payload_id):
    db = _get_db()
    p = db.get_payload(payload_id)
    if not p:
        return api_error('Payload not found', 404)
    return api_success(p)


@bp.route('/badusb/library/search', methods=['GET'])
def badusb_library_search():
    q = request.args.get('q', '')
    db = _get_db()
    results = db.search(q)
    return api_success(results)


@bp.route('/badusb/library/stats', methods=['GET'])
def badusb_library_stats():
    db = _get_db()
    return api_success(db.get_stats())


# sync

@bp.route('/badusb/library/sync/check', methods=['POST'])
def badusb_sync_check():
    sync = _get_sync()
    result = sync.check_for_updates()
    return api_success(result) if result.get('success') else api_error(
        result.get('error', 'Failed'), 500)


@bp.route('/badusb/library/sync/start', methods=['POST'])
def badusb_sync_start():
    global _sync_lock, _sync_task
    if not _sync_lock.acquire(blocking=False):
        return api_error('Sync already in progress', 400)

    _sync_task = {'running': True, 'progress': 0, 'total': 0, 'current': ''}

    def _progress(n, total, repo_name):
        _sync_task['progress'] = n
        _sync_task['total'] = total
        _sync_task['current'] = repo_name

    def _run():
        try:
            sync = _get_sync()
            result = sync.sync(progress_callback=_progress)
            _sync_task['result'] = result
        except Exception as e:
            _sync_task['error'] = str(e)
        finally:
            _sync_task['running'] = False
            _sync_lock.release()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return api_success({'status': 'started'})


@bp.route('/badusb/library/sync/status', methods=['GET'])
def badusb_sync_status():
    return api_success(_sync_task)


# auto-fire

_armed = {'enabled': False, 'payload_id': None, 'payload_name': None,
          'layout': 'us', 'content': None}
_was_connected = False


def _check_usb_host_connected():
    """Return True if the USB gadget is configured (host enumerated it)."""
    # Check if UDC is bound — means the gadget is active and a host is connected
    try:
        with open('/sys/kernel/config/usb_gadget/chonky/UDC', 'r') as f:
            udc = f.read().strip()
            return bool(udc)
    except Exception:
        pass
    # Fallback: check UDC symlink
    try:
        udc_dir = '/sys/class/udc'
        if os.path.isdir(udc_dir):
            for name in os.listdir(udc_dir):
                state_path = os.path.join(udc_dir, name, 'state')
                if os.path.isfile(state_path):
                    with open(state_path, 'r') as f:
                        if 'configured' in f.read():
                            return True
    except Exception:
        pass
    return False


def auto_fire_check():
    """Called from status poll. Fires armed payload on USB connect edge."""
    global _armed, _was_connected
    if not _armed['enabled']:
        _was_connected = False
        return None

    connected = _check_usb_host_connected()
    if connected and not _was_connected:
        _was_connected = True
        # Fire the armed payload
        badusb = get_module('badusb')
        if _armed.get('content'):
            result = badusb.execute_content(
                _armed['content'],
                layout=_armed.get('layout', 'us'),
                label=_armed.get('payload_name', 'armed'))
        elif _armed.get('payload_id'):
            db = _get_db()
            p = db.get_payload(_armed['payload_id'])
            if p:
                result = badusb.execute_content(
                    p['content'],
                    layout=_armed.get('layout', p.get('layout', 'us')),
                    label=p.get('name', f"payload #{_armed['payload_id']}"))
            else:
                result = {'success': False, 'error': 'Armed payload not found in DB'}
        elif _armed.get('payload_name'):
            result = badusb.execute_payload(
                _armed['payload_name'],
                layout=_armed.get('layout', 'us'))
        else:
            result = {'success': False, 'error': 'No payload armed'}

        _armed['enabled'] = False
        return result

    _was_connected = connected
    return None


@bp.route('/badusb/arm', methods=['POST'])
def badusb_arm():
    """Arm a payload to auto-execute when USB is connected to a host."""
    data = request.json or {}
    payload_id = data.get('id')
    payload_name = data.get('payload')
    content = data.get('content')
    if not payload_id and not payload_name and not content:
        return api_error('id, payload name, or content required', 400)

    _armed['enabled'] = True
    _armed['payload_id'] = payload_id
    _armed['payload_name'] = payload_name
    _armed['content'] = content
    _armed['layout'] = data.get('layout', 'us')
    return api_success({'armed': True, 'payload_id': payload_id,
                        'payload_name': payload_name})


@bp.route('/badusb/arm/status', methods=['GET'])
def badusb_arm_status():
    return api_success({'armed': _armed['enabled'],
                        'payload_id': _armed['payload_id'],
                        'payload_name': _armed['payload_name'],
                        'layout': _armed['layout']})


@bp.route('/badusb/arm/cancel', methods=['POST'])
def badusb_arm_cancel():
    _armed['enabled'] = False
    _armed['payload_id'] = None
    _armed['payload_name'] = None
    return api_success({'armed': False})
