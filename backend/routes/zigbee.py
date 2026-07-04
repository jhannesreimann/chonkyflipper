"""
Zigbee bridge, device management, and network map endpoints.
"""

from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error

bp = Blueprint('zigbee', __name__, url_prefix='/api')


@bp.route('/zigbee/bridge', methods=['GET'])
def zigbee_bridge():
    zigbee = get_module('zigbee')
    result = zigbee.get_bridge_info()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/zigbee/permit_join', methods=['POST'])
def zigbee_permit_join():
    data = request.json or {}
    enable = data.get('enable', True)
    duration = data.get('duration', 254)
    zigbee = get_module('zigbee')
    result = zigbee.permit_join(enable, duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/zigbee/device/<device_name>/set', methods=['POST'])
def zigbee_device_set(device_name):
    payload = request.json or {}
    if not payload:
        return api_error('payload required', 400)
    zigbee = get_module('zigbee')
    result = zigbee.set_device_state(device_name, payload)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/zigbee/dashboard', methods=['GET'])
def zigbee_dashboard():
    zigbee = get_module('zigbee')
    result = zigbee.get_device_dashboard()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/zigbee/events', methods=['GET'])
def zigbee_events():
    limit = request.args.get('limit', default=50, type=int)
    zigbee = get_module('zigbee')
    result = zigbee.get_event_log(limit)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/zigbee/networkmap', methods=['GET'])
def zigbee_networkmap():
    zigbee = get_module('zigbee')
    result = zigbee.get_network_map()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/zigbee/device/<device_name>', methods=['DELETE'])
def zigbee_device_remove(device_name):
    zigbee = get_module('zigbee')
    result = zigbee.remove_device(device_name)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/zigbee/device/<device_name>/rename', methods=['POST'])
def zigbee_device_rename(device_name):
    data = request.json or {}
    to_name = data.get('to')
    if not to_name:
        return api_error('new name ("to") required', 400)
    zigbee = get_module('zigbee')
    result = zigbee.rename_device(device_name, to_name)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
