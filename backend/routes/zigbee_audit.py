"""
Zigbee security auditing endpoints (CC2531 sniffer + KillerBee).
"""

from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error

bp = Blueprint('zigbee_audit', __name__, url_prefix='/api')


# capture

@bp.route('/zigbee/audit/capture', methods=['POST'])
def zigbee_audit_capture():
    data = request.json or {}
    channel = data.get('channel', 11)
    duration = data.get('duration', 30)
    zb = get_module('zigbee_audit')
    result = zb.capture_packets(channel=channel, duration=duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Capture failed'), 500)


# scan

@bp.route('/zigbee/audit/scan', methods=['POST'])
def zigbee_audit_scan():
    data = request.json or {}
    channels = data.get('channels', '11-26')
    duration = data.get('duration', 30)
    zb = get_module('zigbee_audit')
    result = zb.scan_channels(channels=channels, duration=duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Scan failed'), 500)


# replay

@bp.route('/zigbee/audit/replay', methods=['POST'])
def zigbee_audit_replay():
    data = request.json or {}
    cap_file = data.get('file')
    if not cap_file:
        return api_error('file (path to pcap) required', 400)
    count = data.get('count', 1)
    channel = data.get('channel')
    zb = get_module('zigbee_audit')
    result = zb.replay_packets(cap_file, count=count, channel=channel)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Replay failed'), 500)


# assoc flood

@bp.route('/zigbee/audit/flood', methods=['POST'])
def zigbee_audit_flood():
    data = request.json or {}
    channel = data.get('channel')
    pan_id = data.get('pan_id')
    if not channel or not pan_id:
        return api_error('channel and pan_id required', 400)
    duration = data.get('duration', 5)
    zb = get_module('zigbee_audit')
    result = zb.assoc_flood(channel, pan_id, duration=duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Flood failed'), 500)


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
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Key extraction failed'), 500)


# device discovery

@bp.route('/zigbee/audit/discover', methods=['POST'])
def zigbee_audit_discover():
    data = request.json or {}
    cap_file = data.get('file')
    zb = get_module('zigbee_audit')
    result = zb.discover_devices(cap_file)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Discovery failed'), 500)


# device check

@bp.route('/zigbee/audit/device', methods=['GET'])
def zigbee_audit_device():
    zb = get_module('zigbee_audit')
    present = zb._check_device()
    return api_success({'cc2531_present': present})
