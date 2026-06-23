"""
WiFi scanning, monitor mode, packet capture, probe logging,
rogue AP detection, deauth, handshake capture, and attacks.
"""

import os
import sys
from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('wifi', __name__)


def _wifi_module():
    """Lazy-init the WiFiModule."""
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.wifi import WiFiModule
    return WiFiModule()


# ------------------------------------------------------------------ scan

@bp.route('/api/wifi/scan', methods=['GET'])
def wifi_scan():
    wifi = _wifi_module()
    networks = wifi.scan_networks()
    if networks is None:
        return api_error('Alfa WiFi adapter not connected', 400)
    return api_success({'networks': networks})


# ------------------------------------------------------------------ monitor mode

@bp.route('/api/wifi/start_monitor', methods=['POST'])
def wifi_start_monitor():
    wifi = _wifi_module()
    result = wifi.start_monitor_mode()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# ------------------------------------------------------------------ packet capture

@bp.route('/api/wifi/capture', methods=['POST'])
def wifi_capture():
    data = request.json or {}
    duration = data.get('duration', 60)
    channel = data.get('channel')
    pkt_filter = data.get('filter')
    wifi = _wifi_module()
    result = wifi.capture_packets(duration=duration, channel=channel, packet_filter=pkt_filter)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# ------------------------------------------------------------------ probes (issue #13)

@bp.route('/api/wifi/probes', methods=['POST'])
def wifi_probes():
    data = request.json or {}
    duration = data.get('duration', 30)
    wifi = _wifi_module()
    result = wifi.capture_probes(duration=duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# ------------------------------------------------------------------ anomalies (issue #14)

@bp.route('/api/wifi/anomalies', methods=['POST'])
def wifi_anomalies():
    wifi = _wifi_module()
    networks = wifi.scan_networks()
    if networks is None:
        return api_error('Alfa WiFi adapter not connected', 400)
    result = wifi.detect_anomalies(networks)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# ------------------------------------------------------------------ deauth

@bp.route('/api/wifi/deauth', methods=['POST'])
def wifi_deauth():
    data = request.json or {}
    bssid = data.get('bssid')
    if not bssid:
        return api_error('bssid required', 400)
    client = data.get('client')
    count = data.get('count', 5)
    channel = data.get('channel')
    wifi = _wifi_module()
    result = wifi.deauth_attack(bssid, client=client, count=count, channel=channel)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# ------------------------------------------------------------------ handshake capture

@bp.route('/api/wifi/handshake', methods=['POST'])
def wifi_handshake():
    data = request.json or {}
    bssid = data.get('bssid')
    channel = data.get('channel')
    if not bssid or not channel:
        return api_error('bssid and channel required', 400)
    timeout = data.get('timeout', 60)
    wifi = _wifi_module()
    result = wifi.capture_handshake(bssid, channel, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# ------------------------------------------------------------------ attack viability check

@bp.route('/api/wifi/attack/check', methods=['POST'])
def wifi_attack_check():
    data = request.json or {}
    bssid = data.get('bssid')
    channel = data.get('channel')
    security = data.get('security')
    flags = data.get('flags', '')
    if not bssid or not channel:
        return api_error('bssid and channel required', 400)

    # Merge security from flags if not provided
    if not security and flags:
        from modules.wifi import WiFiModule
        security, _ = WiFiModule._classify_security(flags)

    wifi = _wifi_module()
    result = wifi.check_attack_viability(bssid, channel, security)
    return api_success(result)


# ------------------------------------------------------------------ attacks

@bp.route('/api/wifi/attack/wep', methods=['POST'])
def wifi_attack_wep():
    data = request.json or {}
    bssid = data.get('bssid')
    channel = data.get('channel')
    if not bssid or not channel:
        return api_error('bssid and channel required', 400)
    timeout = data.get('timeout', 120)
    wifi = _wifi_module()
    result = wifi.attack_wep(bssid, channel, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/wifi/attack/wpa', methods=['POST'])
def wifi_attack_wpa():
    data = request.json or {}
    bssid = data.get('bssid')
    channel = data.get('channel')
    if not bssid or not channel:
        return api_error('bssid and channel required', 400)
    timeout = data.get('timeout', 90)
    wifi = _wifi_module()
    result = wifi.attack_wpa(bssid, channel, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/wifi/attack/wps', methods=['POST'])
def wifi_attack_wps():
    data = request.json or {}
    bssid = data.get('bssid')
    channel = data.get('channel')
    if not bssid or not channel:
        return api_error('bssid and channel required', 400)
    timeout = data.get('timeout', 300)
    wifi = _wifi_module()
    result = wifi.attack_wps(bssid, channel, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
