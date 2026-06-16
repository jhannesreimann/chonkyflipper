"""
IR signal recording, library browser, Flipper-IRDB sync, and device discovery.
"""

import os
import threading
from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('ir', __name__)


def _ir_module():
    import sys
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.ir import IRModule
    return IRModule()


def _ir_db():
    """Lazy-init the IR payload database, auto-seeding if empty."""
    from modules.ir_db import IRPayloadDB
    db = IRPayloadDB()
    db.init_db()
    if db.get_stats().get('brands', 0) == 0:
        db.seed_from_json('/opt/chonkyflipper/payloads')
    return db


# Sync state (protected by lock for thread safety)
_sync_lock = threading.Lock()
_sync_task = {'running': False, 'progress': 0, 'total': 0, 'current': ''}


# ------------------------------------------------------------------ recording

@bp.route('/api/ir/record', methods=['POST'])
def ir_record():
    data = request.json or {}
    duration = data.get('duration', 5)
    ir = _ir_module()
    return api_success(ir.record_signal(duration=duration))


@bp.route('/api/ir/transmit', methods=['POST'])
def ir_transmit():
    data = request.json or {}
    signal_id = data.get('signal_id')
    ir = _ir_module()
    result = ir.transmit_signal(signal_id)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 400)


@bp.route('/api/ir/signals', methods=['GET'])
def ir_list_signals():
    ir = _ir_module()
    return api_success(ir.list_signals())


@bp.route('/api/ir/signals/<signal_id>', methods=['DELETE'])
def ir_delete_signal(signal_id):
    ir = _ir_module()
    result = ir.delete_signal(signal_id)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Not found'), 404)


# ------------------------------------------------------------------ library browser

@bp.route('/api/ir/library/brands', methods=['GET'])
def ir_library_brands():
    db = _ir_db()
    brands = db.get_brands()
    return api_success({'brands': brands, 'total': len(brands)})


@bp.route('/api/ir/library/brands/<slug>/devices', methods=['GET'])
def ir_library_devices(slug):
    db = _ir_db()
    brand = db.get_brand_by_slug(slug)
    if not brand:
        return api_error('Brand not found', 404)
    devices = db.get_devices(slug)
    return api_success({'brand': brand, 'devices': devices})


@bp.route('/api/ir/library/devices/<int:device_id>/buttons', methods=['GET'])
def ir_library_buttons(device_id):
    db = _ir_db()
    device = db.get_device(device_id)
    if not device:
        return api_error('Device not found', 404)
    buttons = db.get_buttons(device_id)
    return api_success({'device': device, 'buttons': buttons})


@bp.route('/api/ir/library/devices/<int:device_id>/send', methods=['POST'])
def ir_library_send(device_id):
    data = request.json or {}
    button_id = data.get('button_id')
    if not button_id:
        return api_error('button_id required', 400)

    db = _ir_db()
    btn = db.get_button_by_device_and_id(device_id, button_id)
    if not btn:
        return api_error('Button not found', 404)

    ir = _ir_module()
    pulses = btn.get('raw_pulses', [])
    spaces = btn.get('raw_spaces', [])

    pairs = []
    for i, pulse in enumerate(pulses):
        pairs.append({'type': 'pulse', 'duration_us': pulse})
        if i < len(spaces):
            pairs.append({'type': 'space', 'duration_us': spaces[i]})

    result = ir._transmit_pairs(pairs, f'{btn.get("brand_name","")}_{button_id}')
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/ir/library/search', methods=['GET'])
def ir_library_search():
    query = request.args.get('q', '').strip()
    if not query:
        return api_success({'results': {}, 'total': 0, 'query': ''})
    db = _ir_db()
    results = db.search(query)
    total = len(results['brands']) + len(results['devices']) + len(results['buttons'])
    return api_success({'results': results, 'total': total, 'query': query})


@bp.route('/api/ir/library/stats', methods=['GET'])
def ir_library_stats():
    db = _ir_db()
    return api_success(db.get_stats())


# ------------------------------------------------------------------ Flipper-IRDB sync

@bp.route('/api/ir/sync/check', methods=['POST'])
def ir_sync_check():
    from modules.ir_sync import IRDBSync
    db = _ir_db()
    syncer = IRDBSync(db)
    return api_success(syncer.check_for_updates())


@bp.route('/api/ir/sync/start', methods=['POST'])
def ir_sync_start():
    global _sync_task
    with _sync_lock:
        if _sync_task['running']:
            return api_error('Sync already in progress', 400)
        _sync_task = {'running': True, 'progress': 0, 'total': 0, 'current': ''}

    def _do_sync():
        global _sync_task
        try:
            from modules.ir_sync import IRDBSync
            from modules.ir_db import IRPayloadDB
            db = IRPayloadDB()
            db.init_db()
            syncer = IRDBSync(db)
            result = syncer.sync(
                progress_callback=lambda p, t, f: _sync_task.update(
                    {'progress': p, 'total': t, 'current': f}
                )
            )
            with _sync_lock:
                _sync_task.update({'running': False, 'result': result})
        except Exception as e:
            with _sync_lock:
                _sync_task.update({'running': False, 'error': str(e)})

    t = threading.Thread(target=_do_sync, daemon=True)
    t.start()
    return api_success({'status': 'started'})


@bp.route('/api/ir/sync/status', methods=['GET'])
def ir_sync_status():
    with _sync_lock:
        return api_success(dict(_sync_task))
