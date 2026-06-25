"""
Bluetooth scanning endpoints.
"""

from flask import Blueprint
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
