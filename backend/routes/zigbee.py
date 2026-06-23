"""
Zigbee bridge, device management, and network map endpoints.
"""

from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('zigbee', __name__)


def _zigbee_module():
    import sys
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.zigbee import ZigbeeModule
    return ZigbeeModule()


@bp.route('/api/zigbee/bridge', methods=['GET'])
def zigbee_bridge():
    zigbee = _zigbee_module()
    result = zigbee.get_bridge_info()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/zigbee/devices', methods=['GET'])
def zigbee_devices():
    zigbee = _zigbee_module()
    result = zigbee.get_devices()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/zigbee/permit_join', methods=['POST'])
def zigbee_permit_join():
    data = request.json or {}
    enable = data.get('enable', True)
    duration = data.get('duration', 254)
    zigbee = _zigbee_module()
    result = zigbee.permit_join(enable, duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/zigbee/device/<device_name>', methods=['GET'])
def zigbee_device_state(device_name):
    zigbee = _zigbee_module()
    result = zigbee.get_device_state(device_name)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/zigbee/device/<device_name>/set', methods=['POST'])
def zigbee_device_set(device_name):
    payload = request.json or {}
    if not payload:
        return api_error('payload required', 400)
    zigbee = _zigbee_module()
    result = zigbee.set_device_state(device_name, payload)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/zigbee/dashboard', methods=['GET'])
def zigbee_dashboard():
    zigbee = _zigbee_module()
    result = zigbee.get_device_dashboard()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/zigbee/networkmap', methods=['GET'])
def zigbee_networkmap():
    zigbee = _zigbee_module()
    result = zigbee.get_network_map()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/zigbee/device/<device_name>', methods=['DELETE'])
def zigbee_device_remove(device_name):
    zigbee = _zigbee_module()
    result = zigbee.remove_device(device_name)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
