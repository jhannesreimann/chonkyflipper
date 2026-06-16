"""
NFC/RFID read and write endpoints.
"""

from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('nfc', __name__)


def _nfc_module():
    import sys
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.pn532 import PN532Module
    return PN532Module()


@bp.route('/api/nfc/read', methods=['GET'])
def nfc_read():
    pn532 = _nfc_module()
    result = pn532.read_card()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/nfc/write', methods=['POST'])
def nfc_write():
    data = request.json or {}
    uid = data.get('uid')
    payload = data.get('payload')
    pn532 = _nfc_module()
    result = pn532.write_card(uid, payload)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
