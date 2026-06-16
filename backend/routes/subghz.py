"""
Sub-1GHz recording and transmit endpoints.
"""

from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('subghz', __name__)


def _subghz_module():
    import sys
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.cc1101 import CC1101Module
    return CC1101Module()


@bp.route('/api/subghz/record', methods=['POST'])
def subghz_record():
    data = request.json or {}
    frequency = data.get('frequency', 433.92)
    duration = data.get('duration', 3)
    cc1101 = _subghz_module()
    result = cc1101.record_signal(frequency, duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/subghz/transmit', methods=['POST'])
def subghz_transmit():
    data = request.json or {}
    signal_id = data.get('signal_id')
    cc1101 = _subghz_module()
    result = cc1101.transmit_signal(signal_id)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
