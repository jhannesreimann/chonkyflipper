"""
WiFi scanning, monitor mode, packet capture, probe logging,
and wifite-based vulnerability auditing.
"""

from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error, api_from_result, parse_int

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
    return api_from_result(wifi.start_monitor_mode())


@bp.route('/wifi/stop_monitor', methods=['POST'])
def wifi_stop_monitor():
    """Return wlan1 to managed mode (e.g. after an attack) so scans work again."""
    wifi = get_module('wifi')
    return api_from_result(wifi.stop_monitor_mode())


# packet capture

@bp.route('/wifi/capture', methods=['POST'])
def wifi_capture():
    data = request.json or {}
    duration = parse_int(data.get('duration', 60), 60, 1, 600)
    channel = parse_int(data.get('channel'), None, 1, 165) if data.get('channel') is not None else None
    pkt_filter = data.get('filter')
    wifi = get_module('wifi')
    result = wifi.capture_packets(duration=duration, channel=channel, packet_filter=pkt_filter)
    return api_from_result(result)


# probes

@bp.route('/wifi/probes', methods=['POST'])
def wifi_probes():
    data = request.json or {}
    duration = parse_int(data.get('duration', 30), 30, 1, 300)
    wifi = get_module('wifi')
    return api_from_result(wifi.capture_probes(duration=duration))


# adapter reset (recover the wedged rtl8821au driver)

@bp.route('/wifi/reset_adapter', methods=['POST'])
def wifi_reset_adapter():
    wifi = get_module('wifi')
    return api_from_result(wifi.reset_adapter())


# wifite audit -- serialized with a cross-process file lock so two runs (e.g.
# from rapid tab switches) cannot fight over the adapter and crash the backend.

import fcntl

_WIFITE_LOCK_PATH = '/tmp/chonky_wifite.lock'


def _acquire_wifite_lock():
    f = open(_WIFITE_LOCK_PATH, 'w')
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except BlockingIOError:
        f.close()
        return None


@bp.route('/wifi/audit/wifite-scan', methods=['POST'])
def wifi_wifite_scan():
    """Wifite scan only (no attacks). Returns targets with clients."""
    lock = _acquire_wifite_lock()
    if lock is None:
        return api_error('A Wi-Fi audit is already running', 409)
    try:
        data = request.json or {}
        scan_time = parse_int(data.get('scan_time', 10), 10, 1, 120)
        wifi = get_module('wifi')
        targets = wifi.run_wifite_scan_only(scan_time=scan_time)
        return api_success({'targets': targets})
    finally:
        lock.close()


@bp.route('/wifi/audit/wifite-attack', methods=['POST'])
def wifi_wifite_attack():
    """Wifite attack: runs in background to avoid HTTP timeout."""
    lock = _acquire_wifite_lock()
    if lock is None:
        return api_error('A Wi-Fi audit is already running', 409)

    data = request.json or {}
    scan_time = parse_int(data.get('scan_time', 10), 10, 1, 120)
    attack_time = parse_int(data.get('attack_time', 120), 120, 10, 1800)

    wifi = get_module('wifi')
    import threading

    def _run():
        try:
            wifi.run_wifite_audit(scan_time=scan_time, attack_time=attack_time)
        finally:
            lock.close()  # release the lock only when the attack finishes

    threading.Thread(target=_run, daemon=True).start()
    return api_success({'status': 'started', 'scan_time': scan_time,
                        'attack_time': attack_time})


@bp.route('/wifi/audit/wifite-status', methods=['GET'])
def wifi_wifite_status():
    """Report whether a wifite audit is running (i.e. the lock is still held)."""
    probe = _acquire_wifite_lock()
    if probe is None:
        return api_success({'running': True})
    probe.close()
    return api_success({'running': False, 'message': 'No attack in progress'})

