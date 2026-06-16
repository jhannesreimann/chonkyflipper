"""
WiFi scanning, monitor mode, and packet capture endpoints.
"""

import os
import re
import time
import subprocess
from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('wifi', __name__)


# ------------------------------------------------------------------ helpers

def _wpa_scan():
    """Scan WiFi networks using wpa_cli on wlan1. Returns list of dicts."""
    if not os.path.exists('/sys/class/net/wlan1'):
        return None

    subprocess.run(['sudo', '-n', 'ip', 'link', 'set', 'wlan1', 'up'],
                   capture_output=True)

    # Ensure wpa_supplicant is running
    wpa_active = subprocess.run(
        ['systemctl', 'is-active', '--quiet', 'wpa_supplicant@wlan1']
    ).returncode == 0
    if not wpa_active:
        subprocess.run(
            ['sudo', '-n', 'systemctl', 'start', 'wpa_supplicant@wlan1'],
            capture_output=True,
        )
        time.sleep(2)

    networks = []
    try:
        # Trigger scan, retry if busy
        for _ in range(3):
            result = subprocess.run(
                ['sudo', '-n', 'wpa_cli', '-i', 'wlan1', 'scan'],
                capture_output=True, text=True, timeout=5,
            )
            if 'OK' in result.stdout:
                time.sleep(3)
                break
            if 'FAIL-BUSY' in result.stdout:
                time.sleep(1)
                continue
            time.sleep(1)

        output = subprocess.check_output(
            ['sudo', '-n', 'wpa_cli', '-i', 'wlan1', 'scan_results'],
            text=True, stderr=subprocess.DEVNULL, timeout=10,
        )

        for line in output.split('\n'):
            parts = line.split('\t')
            if len(parts) < 5:
                continue
            bssid = parts[0].strip()
            if not re.match(r'^[0-9a-fA-F:]{17}$', bssid):
                continue

            try:
                freq = int(parts[1].strip())
                signal = int(parts[2].strip())
            except ValueError:
                continue

            flags = parts[3].strip()
            ssid = parts[4].strip() if len(parts) > 4 else '(hidden)'

            security = None
            if 'WPA2' in flags:
                security = 'WPA2'
            elif 'WPA-' in flags:
                security = 'WPA'

            channel = None
            if 2412 <= freq <= 2484:
                channel = (freq - 2412) // 5 + 1
            elif 5180 <= freq <= 5885:
                channel = (freq - 5180) // 5 + 36

            networks.append({
                'bssid': bssid.upper(),
                'ssid': ssid,
                'signal_dbm': signal,
                'channel': channel,
                'security': security,
            })
    except Exception:
        pass

    # Deduplicate by SSID, keep strongest
    seen = {}
    for net in networks:
        ssid = net.get('ssid', '')
        if not ssid:
            continue
        if ssid not in seen or net.get('signal_dbm', -100) > seen[ssid].get('signal_dbm', -100):
            if ssid in seen and not seen[ssid].get('security') and net.get('security'):
                seen[ssid]['security'] = net['security']
            else:
                seen[ssid] = net

    return sorted(seen.values(), key=lambda x: x.get('signal_dbm', -100), reverse=True)


def _wifi_module():
    """Lazy-init the WiFiModule (avoid circular import)."""
    import sys
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.wifi import WiFiModule
    return WiFiModule()


# ------------------------------------------------------------------ routes

@bp.route('/api/wifi/scan', methods=['GET'])
def wifi_scan():
    networks = _wpa_scan()
    if networks is None:
        return api_error('Alfa WiFi adapter not connected', 400)
    return api_success({'networks': networks})


@bp.route('/api/wifi/start_monitor', methods=['POST'])
def wifi_start_monitor():
    wifi = _wifi_module()
    result = wifi.start_monitor_mode()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/wifi/capture', methods=['POST'])
def wifi_capture():
    data = request.json or {}
    duration = data.get('duration', 60)
    wifi = _wifi_module()
    result = wifi.capture_packets(duration=duration)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)
