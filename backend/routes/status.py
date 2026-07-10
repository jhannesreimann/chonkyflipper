"""
System status, version, and update endpoints.
"""

import os
import glob
import time
import subprocess
from flask import Blueprint, request
from config import (
    VERSION_FILE, REPO_DIR,
    WLAN1_PATH, HCI0_PATH, LIRC0_PATH, SPI0_PATH,
    CC2531_VID, CC2531_PID,
)
from utils import api_success, api_error

bp = Blueprint('status', __name__, url_prefix='/api')

# Module detection cache (avoids running i2cdetect on every 5s poll)
_status_cache = {'data': None, 'time': 0}
_STATUS_CACHE_TTL = 30

_pipower = None


def _get_power_data():
    global _pipower
    try:
        if _pipower is None:
            from pipower5.pipower5 import PiPower5
            _pipower = PiPower5()
        data = _pipower.read_all()
        return {
            'battery_percentage': data.get('battery_percentage'),
            'battery_voltage': data.get('battery_voltage'),
            'is_charging': data.get('is_charging', False),
            'ups_active': True,
        }
    except Exception:
        return {
            'battery_percentage': None,
            'battery_voltage': None,
            'is_charging': None,
            'ups_active': False,
        }


def _detect_modules():
    """Detect which hardware modules are present. Cached for 30 seconds."""
    now = time.time()
    if _status_cache['data'] is not None and (now - _status_cache['time']) < _STATUS_CACHE_TTL:
        return _status_cache['data']

    module_status = {
        'wifi': {
            'available': os.path.exists(WLAN1_PATH),
            'interface': 'wlan1',
        },
        'bluetooth': {
            'available': os.path.exists(HCI0_PATH),
            'interface': 'hci0',
        },
        'ir': {
            'available': os.path.exists(LIRC0_PATH),
            'gpio': '17/27',
        },
        'cc1101': {
            'available': os.path.exists(SPI0_PATH),
            'spi': '0.0',
        },
        'pn532': {'available': False, 'uart': 'ttyAMA0'},
        'zigbee': {
            'available': bool(
                glob.glob('/dev/ttyUSB*') or glob.glob('/dev/ttyACM*')
            ),
            'usb': 'ttyUSB0',
        },
        'zigbee-audit': {
            'available': False,
            'usb': 'CC2531',
        },
    }

    # PN532: probe libnfc via UART. Serialized + non-blocking so the two
    # workers and any in-flight NFC operation do not collide on the port.
    try:
        from modules.pn532 import probe_present
        module_status['pn532']['available'] = probe_present()
    except Exception:
        pass

    # CC2531 sniffer: check USB
    try:
        import usb.core
        dev = usb.core.find(idVendor=CC2531_VID, idProduct=CC2531_PID)
        module_status['zigbee-audit']['available'] = dev is not None
    except Exception:
        pass

    _status_cache['data'] = module_status
    _status_cache['time'] = now
    return module_status


# routes

@bp.route('/status', methods=['GET'])
def get_status():
    # Check auto-fire on each status poll (every 5s)
    auto_fire_result = None
    try:
        from routes.badusb import auto_fire_check
        auto_fire_result = auto_fire_check()
    except Exception:
        pass

    status = {
        'hostname': 'chonkyflipper',
        'modules': _detect_modules(),
        'power': _get_power_data(),
    }
    if auto_fire_result:
        status['auto_fire_fired'] = auto_fire_result
    try:
        from routes.badusb import get_arm_state
        status['badusb_armed'] = get_arm_state()
    except Exception:
        pass
    return api_success(status)


@bp.route('/system/info', methods=['GET'])
def get_system_info():
    try:
        uptime = subprocess.check_output(['uptime', '-p']).decode().strip()
        temp = subprocess.check_output(['vcgencmd', 'measure_temp']).decode().strip()
        return api_success({
            'uptime': uptime,
            'temperature': temp.replace('temp=', '').replace("'C", '°C'),
            'os': 'Kali Linux ARM64',
        })
    except Exception as e:
        return api_error(str(e), 500)


@bp.route('/system/version', methods=['GET'])
def system_version():
    try:
        if os.path.isfile(VERSION_FILE):
            with open(VERSION_FILE) as f:
                sha = f.read().strip()
            return api_success({
                'sha': sha,
                'repo': 'github.com/jhannesreimann/chonkyflipper',
            })
        # Fallback: try git
        if os.path.isdir(os.path.join(REPO_DIR, '.git')):
            sha = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                cwd=REPO_DIR, stderr=subprocess.DEVNULL,
            ).decode().strip()
            return api_success({
                'sha': sha,
                'repo': 'github.com/jhannesreimann/chonkyflipper',
            })
        return api_success({'sha': 'unknown'})
    except Exception:
        return api_success({'sha': 'unknown'})


@bp.route('/system/update', methods=['POST'])
def system_update():
    try:
        # Check internet
        try:
            subprocess.run(
                ['ping', '-c', '1', '-W', '3', 'github.com'],
                capture_output=True, check=True,
            )
        except Exception:
            return api_error(
                'No internet connection. Connect an Ethernet cable to the Pi '
                'for seamless updates (the Chonky_Control AP stays up).',
                400,
            )

        update_script = '/opt/chonkyflipper/update.sh'
        if not os.path.isfile(update_script):
            return api_error(f'Update script not found at {update_script}', 500)

        # Detach from gunicorn process group so restart doesn't kill us
        subprocess.Popen(
            ['sudo', update_script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        return api_success({
            'message': (
                'Update started in background. '
                'The backend will restart when the update completes. '
                'The dashboard will reconnect automatically in a few seconds.'
            ),
        })
    except Exception as e:
        return api_error(str(e), 500)


@bp.route('/system/poweroff', methods=['POST'])
def system_poweroff():
    try:
        subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
        return api_success({'message': 'Shutting down...'})
    except Exception as e:
        return api_error(str(e), 500)


@bp.route('/system/power/shutdown-percentage', methods=['GET'])
def get_shutdown_percentage():
    try:
        global _pipower
        if _pipower is None:
            from pipower5.pipower5 import PiPower5
            _pipower = PiPower5()
        pct = _pipower.read_shutdown_percentage()
        return api_success({'percentage': pct})
    except Exception as e:
        return api_error(str(e), 500)


@bp.route('/system/power/shutdown-percentage', methods=['POST'])
def set_shutdown_percentage():
    data = request.json or {}
    pct = data.get('percentage')
    if pct is None or not isinstance(pct, (int, float)) or pct < 0 or pct > 100:
        return api_error('percentage must be an integer between 0 and 100', 400)

    try:
        subprocess.run(
            ['sudo', '/opt/pipower5/venv/bin/pipower5', '-sp', str(int(pct))],
            capture_output=True, timeout=10, check=True,
        )
        subprocess.run(['sudo', 'systemctl', 'restart', 'pipower5.service'],
                       capture_output=True, timeout=10)
        return api_success({'percentage': int(pct)})
    except subprocess.CalledProcessError as e:
        return api_error(f'Failed to set shutdown percentage: {e.stderr}', 500)
    except Exception as e:
        return api_error(str(e), 500)
