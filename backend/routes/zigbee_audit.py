"""
Zigbee security auditing endpoints (CC2531 sniffer + KillerBee).
"""

from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('zigbee_audit', __name__)


def _audit_module():
    import sys
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.zigbee_audit import ZigbeeAuditModule
    return ZigbeeAuditModule()


# ------------------------------------------------------------------ capture

@bp.route('/api/zigbee/audit/capture', methods=['POST'])
def zigbee_audit_capture():
    data = request.json or {}
    channel = data.get('channel', 11)
    duration = data.get('duration', 30)
    zb = _audit_module()
    result = zb.capture_packets(channel=channel, duration=duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Capture failed'), 500)


# ------------------------------------------------------------------ scan

@bp.route('/api/zigbee/audit/scan', methods=['POST'])
def zigbee_audit_scan():
    data = request.json or {}
    channels = data.get('channels', '11-26')
    duration = data.get('duration', 30)
    zb = _audit_module()
    result = zb.scan_channels(channels=channels, duration=duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Scan failed'), 500)


# ------------------------------------------------------------------ replay

@bp.route('/api/zigbee/audit/replay', methods=['POST'])
def zigbee_audit_replay():
    data = request.json or {}
    cap_file = data.get('file')
    if not cap_file:
        return api_error('file (path to pcap) required', 400)
    count = data.get('count', 1)
    channel = data.get('channel')
    zb = _audit_module()
    result = zb.replay_packets(cap_file, count=count, channel=channel)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Replay failed'), 500)


# ------------------------------------------------------------------ assoc flood

@bp.route('/api/zigbee/audit/flood', methods=['POST'])
def zigbee_audit_flood():
    data = request.json or {}
    channel = data.get('channel')
    pan_id = data.get('pan_id')
    if not channel or not pan_id:
        return api_error('channel and pan_id required', 400)
    duration = data.get('duration', 5)
    zb = _audit_module()
    result = zb.assoc_flood(channel, pan_id, duration=duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Flood failed'), 500)


# ------------------------------------------------------------------ list captures

@bp.route('/api/zigbee/audit/captures', methods=['GET'])
def zigbee_audit_captures():
    zb = _audit_module()
    return api_success(zb.list_captures())


# ------------------------------------------------------------------ key extraction

@bp.route('/api/zigbee/audit/extract-keys', methods=['POST'])
def zigbee_audit_extract():
    data = request.json or {}
    cap_file = data.get('file')
    if not cap_file:
        return api_error('file (path to pcap) required', 400)
    zb = _audit_module()
    result = zb.extract_keys(cap_file)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Key extraction failed'), 500)


# ------------------------------------------------------------------ device check

@bp.route('/api/zigbee/audit/device', methods=['GET'])
def zigbee_audit_device():
    zb = _audit_module()
    present = zb._check_device()
    return api_success({'cc2531_present': present})
