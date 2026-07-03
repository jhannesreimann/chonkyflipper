"""
WiFi scanning, monitor mode, packet capture, probe logging,
rogue AP detection, deauth, handshake capture, and attacks.
"""

from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error

bp = Blueprint('wifi', __name__, url_prefix='/api')


# scan

@bp.route('/wifi/scan', methods=['GET'])
def wifi_scan():
    wifi = get_module('wifi')
    networks = wifi.scan_networks()
    if networks is None:
        return api_error('Alfa WiFi adapter not connected', 400)
    return api_success({'networks': networks})


# monitor mode

@bp.route('/wifi/start_monitor', methods=['POST'])
def wifi_start_monitor():
    wifi = get_module('wifi')
    result = wifi.start_monitor_mode()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/wifi/stop_monitor', methods=['POST'])
def wifi_stop_monitor():
    """Return wlan1 to managed mode (e.g. after an attack) so scans work again."""
    wifi = get_module('wifi')
    result = wifi.stop_monitor_mode()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# packet capture

@bp.route('/wifi/capture', methods=['POST'])
def wifi_capture():
    data = request.json or {}
    duration = data.get('duration', 60)
    channel = data.get('channel')
    pkt_filter = data.get('filter')
    wifi = get_module('wifi')
    result = wifi.capture_packets(duration=duration, channel=channel, packet_filter=pkt_filter)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# probes

@bp.route('/wifi/probes', methods=['POST'])
def wifi_probes():
    data = request.json or {}
    duration = data.get('duration', 30)
    wifi = get_module('wifi')
    result = wifi.capture_probes(duration=duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# anomalies

@bp.route('/wifi/anomalies', methods=['POST'])
def wifi_anomalies():
    wifi = get_module('wifi')
    networks = wifi.scan_networks()
    if networks is None:
        return api_error('Alfa WiFi adapter not connected', 400)
    result = wifi.detect_anomalies(networks)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# deauth

@bp.route('/wifi/deauth', methods=['POST'])
def wifi_deauth():
    data = request.json or {}
    bssid = data.get('bssid')
    if not bssid:
        return api_error('bssid required', 400)
    client = data.get('client')
    count = data.get('count', 5)
    channel = data.get('channel')
    wifi = get_module('wifi')
    result = wifi.deauth_attack(bssid, client=client, count=count, channel=channel)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# handshake capture

@bp.route('/wifi/handshake', methods=['POST'])
def wifi_handshake():
    data = request.json or {}
    bssid = data.get('bssid')
    channel = data.get('channel')
    if not bssid or not channel:
        return api_error('bssid and channel required', 400)
    timeout = data.get('timeout', 60)
    wifi = get_module('wifi')
    result = wifi.capture_handshake(bssid, channel, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


# wifite audit

@bp.route('/wifi/audit/wifite-scan', methods=['POST'])
def wifi_wifite_scan():
    """Wifite scan only (no attacks). Returns targets with clients."""
    data = request.json or {}
    scan_time = data.get('scan_time', 10)
    wifi = get_module('wifi')
    targets = wifi.run_wifite_scan_only(scan_time=scan_time)
    return api_success({'targets': targets})


_wifite_bg_task = None

@bp.route('/wifi/audit/wifite-attack', methods=['POST'])
def wifi_wifite_attack():
    """Wifite attack: runs in background to avoid HTTP timeout."""
    global _wifite_bg_task
    if _wifite_bg_task and _wifite_bg_task.poll() is None:
        return api_error('Attack already in progress', 400)

    data = request.json or {}
    scan_time = data.get('scan_time', 10)
    attack_time = data.get('attack_time', 120)
    channel = data.get('channel')

    wifi = get_module('wifi')
    # Run in background thread so API returns immediately
    import threading
    result_holder = {}

    def _run():
        result_holder['data'] = wifi.run_wifite_audit(
            scan_time=scan_time, attack_time=attack_time)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _wifite_bg_task = t

    return api_success({'status': 'started', 'scan_time': scan_time,
                         'attack_time': attack_time})


@bp.route('/wifi/audit/wifite-status', methods=['GET'])
def wifi_wifite_status():
    """Check if background wifite attack is still running."""
    global _wifite_bg_task
    if _wifite_bg_task and _wifite_bg_task.is_alive():
        return api_success({'running': True})
    return api_success({'running': False, 'message': 'No attack in progress'})


# attack viability check

@bp.route('/wifi/attack/check', methods=['POST'])
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

    wifi = get_module('wifi')
    result = wifi.check_attack_viability(bssid, channel, security)
    return api_success(result)


# attacks

@bp.route('/wifi/attack/wep', methods=['POST'])
def wifi_attack_wep():
    data = request.json or {}
    bssid = data.get('bssid')
    channel = data.get('channel')
    if not bssid or not channel:
        return api_error('bssid and channel required', 400)
    timeout = data.get('timeout', 120)
    wifi = get_module('wifi')
    result = wifi.attack_wep(bssid, channel, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/wifi/attack/wpa', methods=['POST'])
def wifi_attack_wpa():
    data = request.json or {}
    bssid = data.get('bssid')
    channel = data.get('channel')
    if not bssid or not channel:
        return api_error('bssid and channel required', 400)
    timeout = data.get('timeout', 90)
    wifi = get_module('wifi')
    result = wifi.attack_wpa(bssid, channel, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/wifi/attack/wps', methods=['POST'])
def wifi_attack_wps():
    data = request.json or {}
    bssid = data.get('bssid')
    channel = data.get('channel')
    if not bssid or not channel:
        return api_error('bssid and channel required', 400)
    timeout = data.get('timeout', 300)
    wifi = get_module('wifi')
    result = wifi.attack_wps(bssid, channel, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
