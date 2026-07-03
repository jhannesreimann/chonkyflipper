"""
BadUSB payload list and execution endpoints.
"""

from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error

bp = Blueprint('badusb', __name__, url_prefix='/api')


@bp.route('/badusb/payloads', methods=['GET'])
def badusb_list_payloads():
    badusb = get_module('badusb')
    return api_success(badusb.list_payloads())


@bp.route('/badusb/execute', methods=['POST'])
def badusb_execute():
    data = request.json or {}
    payload_name = data.get('payload')
    if not payload_name:
        return api_error('payload name required', 400)
    badusb = get_module('badusb')
    result = badusb.execute_payload(payload_name, layout=data.get('layout'))
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
