"""
Sub-1GHz recording and transmit endpoints.
"""

from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error

bp = Blueprint('subghz', __name__, url_prefix='/api')


@bp.route('/subghz/record', methods=['POST'])
def subghz_record():
    data = request.json or {}
    frequency = data.get('frequency', 433.92)
    duration = data.get('duration', 3)
    cc1101 = get_module('cc1101')
    result = cc1101.record_signal(frequency, duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/subghz/transmit', methods=['POST'])
def subghz_transmit():
    data = request.json or {}
    signal_id = data.get('signal_id')
    cc1101 = get_module('cc1101')
    result = cc1101.transmit_signal(signal_id)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
