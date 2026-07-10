"""
Sub-1GHz recording, replay, spectrum scan and signal management endpoints.
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
    repeat = data.get('repeat', 3)
    cc1101 = get_module('cc1101')
    result = cc1101.transmit_signal(signal_id, repeat)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/subghz/scan', methods=['POST'])
def subghz_scan():
    data = request.json or {}
    start = data.get('start_mhz', 433.0)
    end = data.get('end_mhz', 434.0)
    step = data.get('step_khz', 25)
    cc1101 = get_module('cc1101')
    result = cc1101.scan_frequency(start, end, step)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/subghz/signals', methods=['GET'])
def subghz_signals():
    cc1101 = get_module('cc1101')
    result = cc1101.list_signals()
    if 'error' in result:
        return api_error(result['error'], 500)
    return api_success(result)


@bp.route('/subghz/signals/<signal_id>', methods=['DELETE'])
def subghz_delete(signal_id):
    cc1101 = get_module('cc1101')
    result = cc1101.delete_signal(signal_id)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 404)

