"""
Network status, WiFi client management, and maintenance mode endpoints.
"""

import os
import re
import time
import subprocess
from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('network', __name__)


@bp.route('/api/network/status', methods=['GET'])
def network_status():
    try:
        hostapd_active = subprocess.run(
            ['systemctl', 'is-active', 'hostapd'], capture_output=True
        ).returncode == 0

        wlan1_exists = os.path.exists('/sys/class/net/wlan1')

        wlan1_connected = False
        wlan1_ssid = None
        wlan1_ip = None
        if wlan1_exists:
            try:
                ssid_out = subprocess.check_output(
                    ['wpa_cli', '-i', 'wlan1', 'status'],
                    text=True, stderr=subprocess.DEVNULL,
                )
                wpa_state = None
                for line in ssid_out.split('\n'):
                    if line.startswith('wpa_state='):
                        wpa_state = line.split('=', 1)[1]
                    if line.startswith('ssid='):
                        val = line.split('=', 1)[1]
                        wlan1_ssid = val if val else None
                    if line.startswith('ip_address='):
                        val = line.split('=', 1)[1]
                        wlan1_ip = val if val else None
                wlan1_connected = (wpa_state == 'COMPLETED')
            except Exception:
                pass

        eth0_connected = False
        eth0_ip = None
        try:
            with open('/sys/class/net/eth0/operstate') as f:
                eth0_connected = f.read().strip() == 'up'
            if eth0_connected:
                ip_out = subprocess.check_output(
                    ['ip', '-4', '-br', 'addr', 'show', 'eth0'],
                    text=True, stderr=subprocess.DEVNULL,
                )
                match = re.search(r'(\d+\.\d+\.\d+\.\d+)', ip_out)
                if match:
                    eth0_ip = match.group(1)
        except Exception:
            pass

        internet = False
        internet_source = None
        try:
            subprocess.run(
                ['ping', '-c', '1', '-W', '2', '8.8.8.8'],
                capture_output=True, check=True,
            )
            internet = True
            route_out = subprocess.check_output(
                ['ip', 'route', 'get', '8.8.8.8'], text=True, stderr=subprocess.DEVNULL,
            )
            if 'eth0' in route_out:
                internet_source = 'ethernet'
            elif 'wlan1' in route_out:
                internet_source = 'wifi'
            elif 'wlan0' in route_out:
                internet_source = 'ap_client'
            else:
                internet_source = 'unknown'
        except Exception:
            pass

        return api_success({
            'ap_mode': hostapd_active,
            'ap_ssid': 'Chonky_Control' if hostapd_active else None,
            'ap_ip': '192.168.4.1' if hostapd_active else None,
            'ethernet': {'connected': eth0_connected, 'ip': eth0_ip},
            'wifi_client': {
                'adapter_present': wlan1_exists,
                'connected': wlan1_connected,
                'ssid': wlan1_ssid,
                'ip': wlan1_ip,
            },
            'internet_available': internet,
            'internet_source': internet_source,
        })
    except Exception as e:
        return api_error(str(e), 500)


@bp.route('/api/network/maintenance', methods=['POST'])
def enable_maintenance_mode():
    data = request.json or {}
    ssid = data.get('ssid')
    password = data.get('password')

    if not ssid or not password:
        return api_error('SSID and password required', 400)

    try:
        config_file = '/opt/chonkyflipper/config/maintenance-network.conf'
        with open(config_file, 'w') as f:
            f.write(f'SSID={ssid}\nPASSWORD={password}\n')
        os.chmod(config_file, 0o600)

        result = subprocess.run(
            ['/opt/chonkyflipper/maintenance-mode.sh', 'enable', ssid, password],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return api_success({
                'message': 'Maintenance mode enabled', 'ssid': ssid, 'output': result.stdout,
            })
        return api_error(result.stderr, 500)
    except Exception as e:
        return api_error(str(e), 500)


@bp.route('/api/network/apmode', methods=['POST'])
def enable_ap_mode():
    try:
        result = subprocess.run(
            ['/opt/chonkyflipper/maintenance-mode.sh', 'disable'],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return api_success({
                'message': 'AP mode restored',
                'ssid': 'Chonky_Control', 'ip': '192.168.4.1',
            })
        return api_error(result.stderr, 500)
    except Exception as e:
        return api_error(str(e), 500)


# ------------------------------------------------------------------ WiFi client helpers

def _wifi_cleanup():
    """Clean up wlan1 state before (re)connecting."""
    for cmd in (
        ['sudo', '-n', 'systemctl', 'stop', 'wpa_supplicant@wlan1'],
        ['sudo', '-n', 'ip', 'addr', 'flush', 'dev', 'wlan1'],
        ['sudo', '-n', 'rm', '-f', '/var/run/wpa_supplicant/wlan1'],
    ):
        subprocess.run(cmd, capture_output=True)
    subprocess.run(['sudo', '-n', 'ip', 'link', 'set', 'wlan1', 'up'],
                   capture_output=True)


def _write_wpa_config(ssid, password):
    """Write wpa_supplicant config for wlan1."""
    config = (
        f'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n'
        f'update_config=1\nbgscan=""\ncountry=DE\n\n'
        f'network={{\n    ssid="{ssid}"\n    psk="{password}"\n    key_mgmt=WPA-PSK\n}}\n'
    )
    conf_path = '/etc/wpa_supplicant/wpa_supplicant-wlan1.conf'
    tee = subprocess.Popen(
        ['sudo', '-n', 'tee', conf_path],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    tee.communicate(input=config.encode())
    subprocess.run(['sudo', '-n', 'chmod', '600', conf_path], capture_output=True)


def _start_wpa_and_wait():
    """Start wpa_supplicant on wlan1 and wait for connection. Returns (connected, ip)."""
    subprocess.run(['sudo', '-n', 'systemctl', 'enable', 'wpa_supplicant@wlan1'],
                   capture_output=True)
    subprocess.run(['sudo', '-n', 'systemctl', 'start', 'wpa_supplicant@wlan1'],
                   capture_output=True)

    for _ in range(15):
        time.sleep(1)
        try:
            status = subprocess.check_output(
                ['wpa_cli', '-i', 'wlan1', 'status'],
                text=True, stderr=subprocess.DEVNULL,
            )
            if 'wpa_state=COMPLETED' in status:
                ip_out = subprocess.check_output(
                    ['ip', '-4', '-br', 'addr', 'show', 'wlan1'],
                    text=True, stderr=subprocess.DEVNULL,
                )
                match = re.search(r'(\d+\.\d+\.\d+\.\d+)', ip_out)
                return True, match.group(1) if match else None
        except Exception:
            pass
    return False, None


@bp.route('/api/network/wifi-connect', methods=['POST'])
def wifi_connect():
    if not os.path.exists('/sys/class/net/wlan1'):
        return api_error('Alfa WiFi adapter not connected', 400)

    data = request.json or {}
    ssid = data.get('ssid')
    password = data.get('password')
    if not ssid or not password:
        return api_error('SSID and password required', 400)

    _wifi_cleanup()
    _write_wpa_config(ssid, password)
    connected, ip_addr = _start_wpa_and_wait()

    if connected:
        config_file = '/opt/chonkyflipper/config/wifi-client.conf'
        with open(config_file, 'w') as f:
            f.write(f'SSID={ssid}\nPASSWORD={password}\n')
        os.chmod(config_file, 0o600)
        return api_success({
            'message': f'Connected to {ssid}', 'ssid': ssid, 'ip': ip_addr,
        })

    return api_error(f'Could not connect to {ssid}. Check password and try again.', 400)


@bp.route('/api/network/wifi-disconnect', methods=['POST'])
def wifi_disconnect():
    subprocess.run(['sudo', '-n', 'systemctl', 'stop', 'wpa_supplicant@wlan1'],
                   capture_output=True)
    subprocess.run(['sudo', '-n', 'ip', 'addr', 'flush', 'dev', 'wlan1'],
                   capture_output=True)

    config_file = '/opt/chonkyflipper/config/wifi-client.conf'
    if os.path.isfile(config_file):
        os.remove(config_file)

    return api_success({'message': 'Disconnected from WiFi'})
