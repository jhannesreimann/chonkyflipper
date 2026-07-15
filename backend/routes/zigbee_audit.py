"""
Zigbee security auditing endpoints (CC2531 sniffer + KillerBee).
Passive capture and analysis only -- the CC2531 with stock TI firmware
is RX-only and cannot transmit.
"""

from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error, api_from_result, parse_int

bp = Blueprint('zigbee_audit', __name__, url_prefix='/api')


# capture

@bp.route('/zigbee/audit/capture', methods=['POST'])
def zigbee_audit_capture():
    data = request.json or {}
    channel = parse_int(data.get('channel', 11), 11, 11, 26)
    duration = parse_int(data.get('duration', 30), 30, 1, 300)
    zb = get_module('zigbee_audit')
    result = zb.capture_packets(channel=channel, duration=duration)
    return api_from_result(result, error_code=500)


# scan

@bp.route('/zigbee/audit/scan', methods=['POST'])
def zigbee_audit_scan():
    data = request.json or {}
    channels = data.get('channels', '11-26')
    duration = parse_int(data.get('duration', 30), 30, 1, 300)
    zb = get_module('zigbee_audit')
    result = zb.scan_channels(channels=channels, duration=duration)
    return api_from_result(result, error_code=500)


# list captures

@bp.route('/zigbee/audit/captures', methods=['GET'])
def zigbee_audit_captures():
    zb = get_module('zigbee_audit')
    return api_success(zb.list_captures())


# key extraction

@bp.route('/zigbee/audit/extract-keys', methods=['POST'])
def zigbee_audit_extract():
    data = request.json or {}
    cap_file = data.get('file')
    if not cap_file:
        return api_error('file (path to pcap) required', 400)
    zb = get_module('zigbee_audit')
    result = zb.extract_keys(cap_file)
    return api_from_result(result, error_code=500)


# device discovery

@bp.route('/zigbee/audit/discover', methods=['POST'])
def zigbee_audit_discover():
    data = request.json or {}
    cap_file = data.get('file')
    zb = get_module('zigbee_audit')
    result = zb.discover_devices(cap_file)
    return api_from_result(result, error_code=500)

