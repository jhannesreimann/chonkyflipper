"""
Sub-1GHz recording, replay, spectrum scan and signal management endpoints.
"""

from flask import Blueprint, request
from hardware import get_module
from modules.subghz_decode import decode_pulses
from utils import api_success, api_error, api_from_result, parse_int, parse_float

bp = Blueprint('subghz', __name__, url_prefix='/api')


@bp.route('/subghz/record', methods=['POST'])
def subghz_record():
    data = request.json or {}
    frequency = parse_float(data.get('frequency', 433.92), 433.92, 300, 928)
    duration = parse_int(data.get('duration', 3), 3, 1, 60)
    cc1101 = get_module('cc1101')
    result = cc1101.record_signal(frequency, duration)
    return api_from_result(result)


@bp.route('/subghz/transmit', methods=['POST'])
def subghz_transmit():
    data = request.json or {}
    signal_id = data.get('signal_id')
    repeat = parse_int(data.get('repeat', 3), 3, 1, 100)
    cc1101 = get_module('cc1101')
    result = cc1101.transmit_signal(signal_id, repeat)
    return api_from_result(result)


@bp.route('/subghz/scan', methods=['POST'])
def subghz_scan():
    data = request.json or {}
    start = parse_float(data.get('start_mhz', 433.0), 433.0, 300, 928)
    end = parse_float(data.get('end_mhz', 434.0), 434.0, 300, 928)
    step = parse_int(data.get('step_khz', 25), 25, 1, 1000)
    cc1101 = get_module('cc1101')
    result = cc1101.scan_frequency(start, end, step)
    return api_from_result(result)


@bp.route('/subghz/signals', methods=['GET'])
def subghz_signals():
    cc1101 = get_module('cc1101')
    result = cc1101.list_signals()
    if 'error' in result:
        return api_error(result['error'], 500)
    return api_success(result)


@bp.route('/subghz/signals/<signal_id>', methods=['GET'])
def subghz_get_signal(signal_id):
    cc1101 = get_module('cc1101')
    result = cc1101.get_signal(signal_id)
    return api_from_result(result, error_code=404)


@bp.route('/subghz/decode', methods=['POST'])
def subghz_decode():
    data = request.json or {}
    signal_id = data.get('signal_id')
    cc1101 = get_module('cc1101')
    sig = cc1101.get_signal(signal_id)
    if not sig.get('success'):
        return api_error(sig.get('error', 'Not found'), 404)
    return api_success(decode_pulses(sig.get('pulses', [])))


@bp.route('/subghz/jam', methods=['POST'])
def subghz_jam():
    data = request.json or {}
    frequency = parse_float(data.get('frequency', 433.92), 433.92, 300, 928)
    duration = parse_int(data.get('duration', 5), 5, 1, 60)
    mode = data.get('mode', 'noise')
    cc1101 = get_module('cc1101')
    result = cc1101.jam(frequency, duration, mode)
    return api_from_result(result)


@bp.route('/subghz/signals/<signal_id>', methods=['DELETE'])
def subghz_delete(signal_id):
    cc1101 = get_module('cc1101')
    result = cc1101.delete_signal(signal_id)
    return api_from_result(result, error_code=404)

