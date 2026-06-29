"""
BadUSB payload list and execution endpoints.
"""

from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('badusb', __name__)


def _badusb_module():
    import sys
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.badusb import BadUSBModule
    return BadUSBModule()


@bp.route('/api/badusb/payloads', methods=['GET'])
def badusb_list_payloads():
    badusb = _badusb_module()
    return api_success(badusb.list_payloads())


@bp.route('/api/badusb/execute', methods=['POST'])
def badusb_execute():
    data = request.json or {}
    payload_name = data.get('payload')
    if not payload_name:
        return api_error('payload name required', 400)
    badusb = _badusb_module()
    result = badusb.execute_payload(payload_name, layout=data.get('layout'))
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
