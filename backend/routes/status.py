"""
System status, version, and update endpoints.
"""

import os
import time
import subprocess
from flask import Blueprint
from config import VERSION_FILE, REPO_DIR
from utils import api_success, api_error

bp = Blueprint('status', __name__)

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
            'ups_active': True,
        }


def _detect_modules():
    """Detect which hardware modules are present. Cached for 30 seconds."""
    now = time.time()
    if _status_cache['data'] is not None and (now - _status_cache['time']) < _STATUS_CACHE_TTL:
        return _status_cache['data']

    module_status = {
        'wifi': {
            'available': os.path.exists('/sys/class/net/wlan1'),
            'interface': 'wlan1',
        },
        'bluetooth': {
            'available': os.path.exists('/sys/class/bluetooth/hci0'),
            'interface': 'hci0',
        },
        'ir': {
            'available': os.path.exists('/dev/lirc0'),
            'gpio': '17/27',
        },
        'cc1101': {
            'available': os.path.exists('/sys/bus/spi/devices/spi0.0'),
            'spi': '0.0',
        },
        'pn532': {'available': False, 'i2c': '0x24'},
        'zigbee': {
            'available': bool(
                __import__('glob').glob('/dev/ttyUSB*')
                or __import__('glob').glob('/dev/ttyACM*')
            ),
            'usb': 'ttyUSB0',
        },
    }

    # PN532: check I2C bus
    try:
        i2c_out = subprocess.check_output(
            ['sudo', '-n', 'i2cdetect', '-y', '1'],
            text=True, stderr=subprocess.DEVNULL, timeout=3,
        )
        if '24' in i2c_out:
            for line in i2c_out.split('\n'):
                if line.startswith('20:') and '24' in line.split():
                    module_status['pn532']['available'] = True
                    break
    except Exception:
        pass

    _status_cache['data'] = module_status
    _status_cache['time'] = now
    return module_status


# ------------------------------------------------------------------ routes

@bp.route('/api/status', methods=['GET'])
def get_status():
    return api_success({
        'hostname': 'chonkyflipper',
        'modules': _detect_modules(),
        'power': _get_power_data(),
    })


@bp.route('/api/system/info', methods=['GET'])
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


@bp.route('/api/system/version', methods=['GET'])
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


@bp.route('/api/system/update', methods=['POST'])
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


@bp.route('/api/system/poweroff', methods=['POST'])
def system_poweroff():
    try:
        subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
        return api_success({'message': 'Shutting down...'})
    except Exception as e:
        return api_error(str(e), 500)
