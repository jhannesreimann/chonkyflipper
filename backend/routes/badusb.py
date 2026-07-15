"""
BadUSB payload library, filesystem listing, execution, sync, and auto-fire.
"""

import os
import json
import fcntl
import contextlib
import time
from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error, api_from_result, SyncTask

bp = Blueprint('badusb', __name__, url_prefix='/api')


# lazy DB helpers

_db = None
_sync = None
_sync_task = SyncTask()


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
        return api_from_result(result)
    content = data.get('content')
    if content:
        result = badusb.execute_content(
            content,
            layout=layout,
            label=data.get('label', 'inline'))
        return api_from_result(result)

    # Filesystem payload: execute by name
    payload_name = data.get('payload')
    if not payload_name:
        return api_error('payload name, id, or content required', 400)
    result = badusb.execute_payload(payload_name, layout=layout)
    return api_from_result(result)


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
    return api_from_result(result)


@bp.route('/badusb/library/sync/start', methods=['POST'])
def badusb_sync_start():
    def _run_sync():
        sync = _get_sync()
        return sync.sync(progress_callback=_sync_task.callback)
    return _sync_task.start(_run_sync)


@bp.route('/badusb/library/sync/status', methods=['GET'])
def badusb_sync_status():
    return _sync_task.status()


# auto-fire
#
# Armed state must be shared across gunicorn workers (the service runs with
# -w 2). An in-process dict only lives in the worker that handled the /arm
# POST, so status polls and the auto-fire edge check landing on the other
# worker would see nothing. We keep the state in a small file on tmpfs and
# guard read-modify-write with an flock so exactly one worker fires per edge.

_ARM_FILE = '/dev/shm/chonky_badusb_arm.json'
_ARM_LOCK = '/dev/shm/chonky_badusb_arm.lock'
_ARM_DEFAULT = {'enabled': False, 'payload_id': None, 'payload_name': None,
                'content': None, 'layout': 'us', 'was_connected': False}


def _read_arm():
    try:
        with open(_ARM_FILE, 'r') as f:
            merged = dict(_ARM_DEFAULT)
            merged.update(json.load(f))
            return merged
    except (OSError, ValueError):
        return dict(_ARM_DEFAULT)


def _write_arm(state):
    tmp = _ARM_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, _ARM_FILE)


@contextlib.contextmanager
def _arm_lock():
    f = open(_ARM_LOCK, 'w')
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _check_usb_host_connected():
    """Return True only when a host has actually enumerated the gadget.

    The gadget's UDC file stays populated for as long as the gadget is bound
    to the controller, so it is NOT a connection signal (it reads the same
    whether a host is plugged in or not). The controller's 'state' file is:
    it reports 'configured' once a host finishes enumeration and
    'not attached' when the data port is unplugged.
    """
    try:
        udc_dir = '/sys/class/udc'
        for name in os.listdir(udc_dir):
            state_path = os.path.join(udc_dir, name, 'state')
            try:
                with open(state_path, 'r') as f:
                    if f.read().strip() == 'configured':
                        return True
            except OSError:
                continue
    except OSError:
        pass
    return False


def auto_fire_check():
    """Called from status poll. Fires armed payload on USB connect edge.

    The claim-and-disarm happens under the lock so the second worker never
    fires the same edge; the payload itself runs outside the lock.
    """
    with _arm_lock():
        state = _read_arm()
        if not state['enabled']:
            return None
        connected = _check_usb_host_connected()
        if not (connected and not state['was_connected']):
            # No rising edge: just record the current connection state.
            state['was_connected'] = connected
            _write_arm(state)
            return None
        # Rising edge: claim this fire and disarm before releasing the lock.
        state['was_connected'] = True
        state['enabled'] = False
        _write_arm(state)
        armed = state

    badusb = get_module('badusb')
    if armed.get('content'):
        return badusb.execute_content(
            armed['content'],
            layout=armed.get('layout', 'us'),
            label=armed.get('payload_name', 'armed'))
    if armed.get('payload_id'):
        db = _get_db()
        p = db.get_payload(armed['payload_id'])
        if not p:
            return {'success': False, 'error': 'Armed payload not found in DB'}
        return badusb.execute_content(
            p['content'],
            layout=armed.get('layout', p.get('layout', 'us')),
            label=p.get('name', f"payload #{armed['payload_id']}"))
    if armed.get('payload_name'):
        return badusb.execute_payload(
            armed['payload_name'],
            layout=armed.get('layout', 'us'))
    return {'success': False, 'error': 'No payload armed'}


def get_arm_state():
    """Armed summary for the global /api/status poll (drives the UI banner)."""
    s = _read_arm()
    return {'armed': s['enabled'],
            'payload_name': s['payload_name'],
            'payload_id': s['payload_id'],
            'layout': s['layout']}


@bp.route('/badusb/arm', methods=['POST'])
def badusb_arm():
    """Arm a payload to auto-execute when USB is connected to a host."""
    data = request.json or {}
    payload_id = data.get('id')
    payload_name = data.get('payload')
    content = data.get('content')
    if not payload_id and not payload_name and not content:
        return api_error('id, payload name, or content required', 400)

    with _arm_lock():
        # Seed was_connected with the CURRENT state so we fire only on a fresh
        # plug-in edge after arming, never into whatever host is attached right
        # now. This keeps the arm live (and the banner shown) when the port is
        # already enumerated by some non-target host at arm time; the payload
        # fires when the cable is moved to the target (not attached -> configured).
        _write_arm({
            'enabled': True,
            'payload_id': payload_id,
            'payload_name': payload_name,
            'content': content,
            'layout': data.get('layout', 'us'),
            'was_connected': _check_usb_host_connected(),
        })
    return api_success({'armed': True, 'payload_id': payload_id,
                        'payload_name': payload_name})


@bp.route('/badusb/arm/status', methods=['GET'])
def badusb_arm_status():
    return api_success(get_arm_state())


@bp.route('/badusb/arm/cancel', methods=['POST'])
def badusb_arm_cancel():
    with _arm_lock():
        state = _read_arm()
        state['enabled'] = False
        _write_arm(state)
    return api_success({'armed': False})


# Background watcher: runs the auto-fire check server-side so a plug-in fires
# even when no browser is polling /api/status (e.g. the phone screen is off).
# Each worker starts one; auto_fire_check() claims the edge under the flock, so
# only one worker ever fires a given connect.
_watcher_thread = None
_watcher_guard = threading.Lock()


def _auto_fire_loop():
    while True:
        try:
            auto_fire_check()
        except Exception:
            pass
        time.sleep(2)


def start_auto_fire_watcher():
    global _watcher_thread
    with _watcher_guard:
        if _watcher_thread is not None and _watcher_thread.is_alive():
            return
        # A restart must not fire a leftover arm into a host that is already
        # attached: re-seed was_connected to the current state so only a fresh
        # plug-in edge fires (same seeding rule an explicit /arm uses).
        with _arm_lock():
            state = _read_arm()
            if state['enabled']:
                state['was_connected'] = _check_usb_host_connected()
                _write_arm(state)
        _watcher_thread = threading.Thread(
            target=_auto_fire_loop, name='badusb-autofire', daemon=True)
        _watcher_thread.start()


start_auto_fire_watcher()
