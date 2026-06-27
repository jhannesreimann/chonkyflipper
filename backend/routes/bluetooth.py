"""
Bluetooth scanning endpoints.
"""

from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('bluetooth', __name__)


def _bt_module():
    import sys
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.bluetooth import BluetoothModule
    return BluetoothModule()


@bp.route('/api/bluetooth/scan', methods=['GET'])
def bluetooth_scan():
    bt = _bt_module()
    result = bt.scan_ble()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Scan failed'), 500)


@bp.route('/api/bluetooth/beacons', methods=['GET'])
def bluetooth_beacons():
    bt = _bt_module()
    result = bt.scan_beacons()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Scan failed'), 500)


@bp.route('/api/bluetooth/capture', methods=['POST'])
def bluetooth_capture():
    data = request.json or {}
    try:
        duration = int(data.get('duration', 15))
    except (TypeError, ValueError):
        return api_error('duration must be an integer (seconds)', 400)
    duration = max(1, min(duration, 120))
    bt = _bt_module()
    result = bt.log_advertisements(duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Capture failed'), 500)


@bp.route('/api/bluetooth/gatt', methods=['POST'])
def bluetooth_gatt():
    data = request.json or {}
    mac = data.get('mac')
    if not mac:
        return api_error('mac required', 400)
    bt = _bt_module()
    result = bt.profile_device(mac)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'GATT profiling failed'), 500)


@bp.route('/api/bluetooth/gatt/write', methods=['POST'])
def bluetooth_gatt_write():
    data = request.json or {}
    mac = data.get('mac')
    char_uuid = data.get('char_uuid')
    value = data.get('value')
    if not mac or not char_uuid or value is None:
        return api_error('mac, char_uuid, and value are required', 400)
    bt = _bt_module()
    result = bt.write_characteristic(mac, char_uuid, value, data.get('without_response'))
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Write failed'), 500)


@bp.route('/api/bluetooth/capture-hci', methods=['POST'])
def bluetooth_capture_hci():
    data = request.json or {}
    try:
        duration = int(data.get('duration', 20))
    except (TypeError, ValueError):
        return api_error('duration must be an integer (seconds)', 400)
    duration = max(1, min(duration, 300))
    bt = _bt_module()
    result = bt.capture_hci(duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'HCI capture failed'), 500)


@bp.route('/api/bluetooth/captures', methods=['GET'])
def bluetooth_captures():
    bt = _bt_module()
    return api_success(bt.list_hci_captures())


@bp.route('/api/bluetooth/classic-scan', methods=['GET'])
def bluetooth_classic_scan():
    try:
        duration = int(request.args.get('duration', 10))
    except (TypeError, ValueError):
        duration = 10
    duration = max(1, min(duration, 60))
    bt = _bt_module()
    result = bt.scan_classic(duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Classic scan failed'), 500)


@bp.route('/api/bluetooth/sdp', methods=['POST'])
def bluetooth_sdp():
    data = request.json or {}
    mac = data.get('mac')
    if not mac:
        return api_error('mac required', 400)
    bt = _bt_module()
    result = bt.enumerate_services(mac)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'SDP enumeration failed'), 500)
