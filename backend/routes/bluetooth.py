"""
Bluetooth scanning endpoints.
"""

from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error, api_from_result

bp = Blueprint('bluetooth', __name__, url_prefix='/api')


@bp.route('/bluetooth/scan', methods=['GET'])
def bluetooth_scan():
    try:
        duration = int(request.args.get('duration', 8))
    except (TypeError, ValueError):
        duration = 8
    duration = max(1, min(duration, 120))
    bt = get_module('bluetooth')
    result = bt.scan_ble(duration)
    return api_from_result(result, error_code=500)


@bp.route('/bluetooth/beacons', methods=['GET'])
def bluetooth_beacons():
    try:
        duration = int(request.args.get('duration', 8))
    except (TypeError, ValueError):
        duration = 8
    duration = max(1, min(duration, 120))
    bt = get_module('bluetooth')
    result = bt.scan_beacons(duration)
    return api_from_result(result, error_code=500)


@bp.route('/bluetooth/gatt', methods=['POST'])
def bluetooth_gatt():
    data = request.json or {}
    mac = data.get('mac')
    if not mac:
        return api_error('mac required', 400)
    bt = get_module('bluetooth')
    result = bt.profile_device(mac)
    return api_from_result(result, error_code=500)


@bp.route('/bluetooth/gatt/write', methods=['POST'])
def bluetooth_gatt_write():
    data = request.json or {}
    mac = data.get('mac')
    char_uuid = data.get('char_uuid')
    value = data.get('value')
    if not mac or not char_uuid or value is None:
        return api_error('mac, char_uuid, and value are required', 400)
    bt = get_module('bluetooth')
    result = bt.write_characteristic(mac, char_uuid, value, data.get('without_response'))
    return api_from_result(result, error_code=500)


@bp.route('/bluetooth/capture-hci', methods=['POST'])
def bluetooth_capture_hci():
    data = request.json or {}
    try:
        duration = int(data.get('duration', 20))
    except (TypeError, ValueError):
        return api_error('duration must be an integer (seconds)', 400)
    duration = max(1, min(duration, 300))
    bt = get_module('bluetooth')
    result = bt.capture_hci(duration)
    return api_from_result(result, error_code=500)


@bp.route('/bluetooth/spoof', methods=['POST'])
def bluetooth_spoof():
    params = request.json or {}
    bt = get_module('bluetooth')
    result = bt.spoof_advertisement(params)
    return api_from_result(result, error_code=500)


@bp.route('/bluetooth/spoof/stop', methods=['POST'])
def bluetooth_spoof_stop():
    bt = get_module('bluetooth')
    return api_success(bt.stop_spoof())


@bp.route('/bluetooth/spoof/status', methods=['GET'])
def bluetooth_spoof_status():
    bt = get_module('bluetooth')
    return api_success(bt.spoof_status())


@bp.route('/bluetooth/deep-scan', methods=['POST'])
def bluetooth_deep_scan():
    data = request.json or {}
    try:
        duration = int(data.get('duration', 15))
    except (TypeError, ValueError):
        return api_error('duration must be an integer (seconds)', 400)
    duration = max(1, min(duration, 120))
    bt = get_module('bluetooth')
    result = bt.deep_scan(duration)
    return api_from_result(result, error_code=500)


@bp.route('/bluetooth/classic-scan', methods=['GET'])
def bluetooth_classic_scan():
    try:
        duration = int(request.args.get('duration', 10))
    except (TypeError, ValueError):
        duration = 10
    duration = max(1, min(duration, 60))
    bt = get_module('bluetooth')
    result = bt.scan_classic(duration)
    return api_from_result(result, error_code=500)


@bp.route('/bluetooth/sdp', methods=['POST'])
def bluetooth_sdp():
    data = request.json or {}
    mac = data.get('mac')
    if not mac:
        return api_error('mac required', 400)
    bt = get_module('bluetooth')
    result = bt.enumerate_services(mac)
    return api_from_result(result, error_code=500)


# background ad log daemon

@bp.route('/bluetooth/log/start', methods=['POST'])
def bluetooth_log_start():
    bt = get_module('bluetooth')
    result = bt.start_advert_log()
    return api_from_result(result, error_code=500)


@bp.route('/bluetooth/log/stop', methods=['POST'])
def bluetooth_log_stop():
    bt = get_module('bluetooth')
    return api_success(bt.stop_advert_log())


@bp.route('/bluetooth/log/status', methods=['GET'])
def bluetooth_log_status():
    bt = get_module('bluetooth')
    return api_success(bt.advert_log_status())


@bp.route('/bluetooth/log/data', methods=['GET'])
def bluetooth_log_data():
    bt = get_module('bluetooth')
    return api_success(bt.advert_log_data())
