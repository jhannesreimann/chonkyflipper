#!/usr/bin/env python3
"""
ChonkyFlipper Backend - Flask API Server
Mobile IoT Pentesting Rig Controller
"""

import os
import re
import subprocess
import json
import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from modules.wifi import WiFiModule
from modules.bluetooth import BluetoothModule
from modules.ir import IRModule
from modules.cc1101 import CC1101Module
from modules.pn532 import PN532Module
from modules.badusb import BadUSBModule
from modules.zigbee import ZigbeeModule

app = Flask(__name__)
CORS(app)  # Enable CORS for mobile web app access

# Initialize modules (lazy loading on first use)
modules = {}

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
            'ups_active': True
        }
    except Exception:
        return {
            'battery_percentage': None,
            'battery_voltage': None,
            'is_charging': None,
            'ups_active': True
        }

def get_module(name):
    """Lazy module initialization"""
    if name not in modules:
        module_map = {
            'wifi': WiFiModule,
            'bluetooth': BluetoothModule,
            'ir': IRModule,
            'cc1101': CC1101Module,
            'pn532': PN532Module,
            'badusb': BadUSBModule,
            'zigbee': ZigbeeModule
        }
        modules[name] = module_map[name]()
    return modules[name]

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get overall system status with live hardware detection"""
    modules = {
        'wifi': {
            'available': os.path.exists('/sys/class/net/wlan1'),
            'interface': 'wlan1'
        },
        'bluetooth': {
            'available': os.path.exists('/sys/class/bluetooth/hci0'),
            'interface': 'hci0'
        },
        'ir': {
            'available': os.path.exists('/dev/lirc0'),
            'gpio': '17/27'
        },
        'cc1101': {
            'available': os.path.exists('/sys/bus/spi/devices/spi0.0'),
            'spi': '0.0'
        },
        'pn532': {
            'available': False,
            'i2c': '0x24'
        },
        'zigbee': {
            'available': bool(
                __import__('glob').glob('/dev/ttyUSB*') or
                __import__('glob').glob('/dev/ttyACM*')
            ),
            'usb': 'ttyUSB0'
        }
    }

    # PN532: check I2C bus for device at 0x24
    try:
        i2c_out = subprocess.check_output(
            ['sudo', '-n', 'i2cdetect', '-y', '1'],
            text=True, stderr=subprocess.DEVNULL, timeout=3
        )
        if '24' in i2c_out:
            # Verify it's at address 0x24, not just any "24" in the output
            for line in i2c_out.split('\n'):
                if line.startswith('20:') and '24' in line.split():
                    modules['pn532']['available'] = True
                    break
    except Exception:
        pass

    return jsonify({
        'status': 'online',
        'hostname': 'chonkyflipper',
        'modules': modules,
        'power': _get_power_data()
    })

@app.route('/api/system/info', methods=['GET'])
def get_system_info():
    """Get system information"""
    try:
        uptime = subprocess.check_output(['uptime', '-p']).decode().strip()
        temp = subprocess.check_output(['vcgencmd', 'measure_temp']).decode().strip()
        return jsonify({
            'uptime': uptime,
            'temperature': temp.replace('temp=', '').replace("'C", '°C'),
            'os': 'Kali Linux ARM64'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wifi/scan', methods=['GET'])
def wifi_scan():
    """Scan for Wi-Fi networks"""
    wifi = get_module('wifi')
    networks = wifi.scan()
    return jsonify({'networks': networks})

@app.route('/api/wifi/start_monitor', methods=['POST'])
def wifi_start_monitor():
    """Enable monitor mode on Alfa adapter"""
    wifi = get_module('wifi')
    result = wifi.start_monitor_mode()
    return jsonify(result)

@app.route('/api/wifi/capture', methods=['POST'])
def wifi_capture():
    """Start packet capture (pcap)"""
    data = request.json or {}
    duration = data.get('duration', 60)  # seconds
    wifi = get_module('wifi')
    result = wifi.capture_packets(duration=duration)
    return jsonify(result)

@app.route('/api/bluetooth/scan', methods=['GET'])
def bluetooth_scan():
    """Scan for BLE devices"""
    bt = get_module('bluetooth')
    devices = bt.scan_ble()
    return jsonify({'devices': devices})

@app.route('/api/bluetooth/beacons', methods=['GET'])
def bluetooth_beacons():
    """Listen for BLE beacons (iBeacon, Eddystone)"""
    bt = get_module('bluetooth')
    beacons = bt.scan_beacons()
    return jsonify({'beacons': beacons})

@app.route('/api/ir/record', methods=['POST'])
def ir_record():
    """Record IR signal"""
    data = request.json or {}
    duration = data.get('duration', 5)  # seconds
    ir = get_module('ir')
    result = ir.record_signal(duration=duration)
    return jsonify(result)

@app.route('/api/ir/transmit', methods=['POST'])
def ir_transmit():
    """Transmit recorded IR signal"""
    data = request.json or {}
    signal_id = data.get('signal_id')
    ir = get_module('ir')
    result = ir.transmit_signal(signal_id)
    return jsonify(result)


@app.route('/api/ir/signals', methods=['GET'])
def ir_list_signals():
    """List recorded IR signals"""
    ir = get_module('ir')
    return jsonify(ir.list_signals())


@app.route('/api/ir/signals/<signal_id>', methods=['DELETE'])
def ir_delete_signal(signal_id):
    """Delete a recorded IR signal"""
    ir = get_module('ir')
    return jsonify(ir.delete_signal(signal_id))


@app.route('/api/ir/payloads', methods=['GET'])
def ir_payloads():
    """List built-in IR payloads"""
    ir = get_module('ir')
    return jsonify(ir.list_payloads())


@app.route('/api/ir/payloads/execute', methods=['POST'])
def ir_execute_payload():
    """Execute a built-in IR payload"""
    data = request.json or {}
    payload_id = data.get('payload_id')
    if not payload_id:
        return jsonify({'success': False, 'error': 'payload_id required'}), 400
    ir = get_module('ir')
    return jsonify(ir.execute_payload(payload_id))


@app.route('/api/ir/bruteforce', methods=['POST'])
def ir_bruteforce():
    """Send common power toggle codes for device discovery"""
    ir = get_module('ir')
    data = request.json or {}
    brands = data.get('brands', None)
    return jsonify(ir.brute_force_power(brands))

@app.route('/api/subghz/record', methods=['POST'])
def subghz_record():
    """Record Sub-1 GHz signal (433/868 MHz)"""
    data = request.json or {}
    frequency = data.get('frequency', 433.92)  # MHz
    duration = data.get('duration', 3)  # seconds
    cc1101 = get_module('cc1101')
    result = cc1101.record_signal(frequency, duration)
    return jsonify(result)

@app.route('/api/subghz/transmit', methods=['POST'])
def subghz_transmit():
    """Replay recorded Sub-1 GHz signal"""
    data = request.json or {}
    signal_id = data.get('signal_id')
    cc1101 = get_module('cc1101')
    result = cc1101.transmit_signal(signal_id)
    return jsonify(result)

@app.route('/api/nfc/read', methods=['GET'])
def nfc_read():
    """Read NFC/RFID card"""
    pn532 = get_module('pn532')
    result = pn532.read_card()
    return jsonify(result)

@app.route('/api/nfc/write', methods=['POST'])
def nfc_write():
    """Write to NFC/RFID card"""
    data = request.json or {}
    uid = data.get('uid')
    payload = data.get('payload')
    pn532 = get_module('pn532')
    result = pn532.write_card(uid, payload)
    return jsonify(result)

@app.route('/api/badusb/payloads', methods=['GET'])
def badusb_list_payloads():
    """List available BadUSB payloads"""
    badusb = get_module('badusb')
    return jsonify(badusb.list_payloads())

@app.route('/api/badusb/execute', methods=['POST'])
def badusb_execute():
    """Execute BadUSB payload"""
    data = request.json or {}
    payload_name = data.get('payload')
    if not payload_name:
        return jsonify({'success': False, 'error': 'payload name required'}), 400
    badusb = get_module('badusb')
    return jsonify(badusb.execute_payload(payload_name))

@app.route('/api/network/status', methods=['GET'])
def network_status():
    """Get current network mode status"""
    try:
        # Check AP mode via hostapd
        hostapd_active = subprocess.run(
            ['systemctl', 'is-active', 'hostapd'],
            capture_output=True
        ).returncode == 0

        # Check if wlan1 exists (Alfa adapter)
        wlan1_exists = os.path.exists('/sys/class/net/wlan1')

        # Check wlan1 client mode status
        wlan1_connected = False
        wlan1_ssid = None
        wlan1_ip = None
        if wlan1_exists:
            # wpa_cli status tells us if we have a real connection
            try:
                ssid_out = subprocess.check_output(
                    ['wpa_cli', '-i', 'wlan1', 'status'],
                    text=True, stderr=subprocess.DEVNULL
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

        # Check eth0 link and IP
        eth0_connected = False
        eth0_ip = None
        try:
            with open('/sys/class/net/eth0/operstate') as f:
                eth0_connected = f.read().strip() == 'up'
            if eth0_connected:
                ip_out = subprocess.check_output(
                    ['ip', '-4', '-br', 'addr', 'show', 'eth0'],
                    text=True, stderr=subprocess.DEVNULL
                )
                match = re.search(r'(\d+\.\d+\.\d+\.\d+)', ip_out)
                if match:
                    eth0_ip = match.group(1)
        except Exception:
            pass

        # Check internet connectivity
        internet = False
        internet_source = None
        try:
            subprocess.run(['ping', '-c', '1', '-W', '2', '8.8.8.8'],
                         capture_output=True, check=True)
            internet = True
            # Determine which interface provides internet
            route_out = subprocess.check_output(
                ['ip', 'route', 'get', '8.8.8.8'], text=True, stderr=subprocess.DEVNULL
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

        return jsonify({
            'ap_mode': hostapd_active,
            'ap_ssid': 'Chonky_Control' if hostapd_active else None,
            'ap_ip': '192.168.4.1' if hostapd_active else None,
            'ethernet': {
                'connected': eth0_connected,
                'ip': eth0_ip
            },
            'wifi_client': {
                'adapter_present': wlan1_exists,
                'connected': wlan1_connected,
                'ssid': wlan1_ssid,
                'ip': wlan1_ip
            },
            'internet_available': internet,
            'internet_source': internet_source
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/network/maintenance', methods=['POST'])
def enable_maintenance_mode():
    """Enable client mode (maintenance) to connect to external WiFi"""
    data = request.json or {}
    ssid = data.get('ssid')
    password = data.get('password')
    
    if not ssid or not password:
        return jsonify({
            'success': False,
            'error': 'SSID and password required'
        }), 400
    
    try:
        # Save network credentials
        config_file = '/opt/chonkyflipper/config/maintenance-network.conf'
        with open(config_file, 'w') as f:
            f.write(f'SSID={ssid}\nPASSWORD={password}\n')
        os.chmod(config_file, 0o600)
        
        # Run maintenance mode script
        result = subprocess.run(
            ['/opt/chonkyflipper/maintenance-mode.sh', 'enable', ssid, password],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Maintenance mode enabled',
                'ssid': ssid,
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            }), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/network/apmode', methods=['POST'])
def enable_ap_mode():
    """Switch back to AP mode (Chonky_Control)"""
    try:
        result = subprocess.run(
            ['/opt/chonkyflipper/maintenance-mode.sh', 'disable'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'AP mode restored',
                'ssid': 'Chonky_Control',
                'ip': '192.168.4.1'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            }), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/network/wifi-scan', methods=['GET'])
def wifi_scan_networks():
    """Scan for WiFi networks using the Alfa adapter (wlan1)"""
    if not os.path.exists('/sys/class/net/wlan1'):
        return jsonify({
            'success': False,
            'error': 'Alfa WiFi adapter not connected'
        }), 400

    # Ensure wlan1 is up
    subprocess.run(['sudo', '-n', 'ip', 'link', 'set', 'wlan1', 'up'],
                   capture_output=True)

    # Keep wpa_supplicant running on wlan1 (start if not active)
    wpa_active = subprocess.run(
        ['systemctl', 'is-active', '--quiet', 'wpa_supplicant@wlan1']
    ).returncode == 0
    if not wpa_active:
        subprocess.run(
            ['sudo', '-n', 'systemctl', 'start', 'wpa_supplicant@wlan1'],
            capture_output=True
        )
        time.sleep(2)

    networks = []
    try:
        # Trigger a fresh scan, retry if busy
        for attempt in range(3):
            result = subprocess.run(
                ['sudo', '-n', 'wpa_cli', '-i', 'wlan1', 'scan'],
                capture_output=True, text=True, timeout=5
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
            text=True, stderr=subprocess.DEVNULL, timeout=10
        )

        # Parse tab-separated output (skip header line)
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

            # Determine security from flags
            security = None
            if 'WPA2' in flags:
                security = 'WPA2'
            elif 'WPA-' in flags:
                security = 'WPA'

            # Convert frequency to channel
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
                'security': security
            })

    except Exception:
        pass

    # Deduplicate by SSID, keep strongest signal
    seen = {}
    for net in networks:
        ssid = net.get('ssid', '')
        if not ssid:
            continue
        if ssid not in seen or net.get('signal_dbm', -100) > seen[ssid].get('signal_dbm', -100):
            # Keep security from any entry if the winner lacks it
            if ssid in seen and not seen[ssid].get('security') and net.get('security'):
                seen[ssid]['security'] = net['security']
            else:
                seen[ssid] = net

    result = sorted(seen.values(), key=lambda x: x.get('signal_dbm', -100), reverse=True)

    return jsonify({
        'success': True,
        'networks': result
    })


@app.route('/api/network/wifi-connect', methods=['POST'])
def wifi_connect():
    """Connect wlan1 to a WiFi network (leaves wlan0 AP untouched)"""
    if not os.path.exists('/sys/class/net/wlan1'):
        return jsonify({
            'success': False,
            'error': 'Alfa WiFi adapter not connected'
        }), 400

    data = request.json or {}
    ssid = data.get('ssid')
    password = data.get('password')

    if not ssid or not password:
        return jsonify({
            'success': False,
            'error': 'SSID and password required'
        }), 400

    # Clean up any stale state
    subprocess.run(['sudo', '-n', 'systemctl', 'stop', 'wpa_supplicant@wlan1'],
                   capture_output=True)
    subprocess.run(['sudo', '-n', 'ip', 'addr', 'flush', 'dev', 'wlan1'],
                   capture_output=True)
    subprocess.run(['sudo', '-n', 'rm', '-f', '/var/run/wpa_supplicant/wlan1'],
                   capture_output=True)

    # Bring interface up in managed mode
    subprocess.run(['sudo', '-n', 'ip', 'link', 'set', 'wlan1', 'up'],
                   capture_output=True)

    # Write wpa_supplicant config for wlan1 (via sudo tee)
    config = (
        f'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n'
        f'update_config=1\n'
        f'bgscan=""\n'
        f'country=DE\n\n'
        f'network={{\n'
        f'    ssid="{ssid}"\n'
        f'    psk="{password}"\n'
        f'    key_mgmt=WPA-PSK\n'
        f'}}\n'
    )
    conf_path = '/etc/wpa_supplicant/wpa_supplicant-wlan1.conf'
    tee = subprocess.Popen(
        ['sudo', '-n', 'tee', conf_path],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    tee.communicate(input=config.encode())
    subprocess.run(['sudo', '-n', 'chmod', '600', conf_path], capture_output=True)

    # Start wpa_supplicant on wlan1
    subprocess.run(['sudo', '-n', 'systemctl', 'enable', 'wpa_supplicant@wlan1'],
                   capture_output=True)
    subprocess.run(['sudo', '-n', 'systemctl', 'start', 'wpa_supplicant@wlan1'],
                   capture_output=True)

    # Wait for connection
    connected = False
    ip_addr = None
    for _ in range(15):
        time.sleep(1)
        try:
            status = subprocess.check_output(
                ['wpa_cli', '-i', 'wlan1', 'status'],
                text=True, stderr=subprocess.DEVNULL
            )
            if 'wpa_state=COMPLETED' in status:
                connected = True
                # Get IP
                ip_out = subprocess.check_output(
                    ['ip', '-4', '-br', 'addr', 'show', 'wlan1'],
                    text=True, stderr=subprocess.DEVNULL
                )
                match = re.search(r'(\d+\.\d+\.\d+\.\d+)', ip_out)
                if match:
                    ip_addr = match.group(1)
                break
        except Exception:
            pass

    if connected:
        # Save credentials for auto-reconnect
        config_file = '/opt/chonkyflipper/config/wifi-client.conf'
        with open(config_file, 'w') as f:
            f.write(f'SSID={ssid}\nPASSWORD={password}\n')
        os.chmod(config_file, 0o600)

        return jsonify({
            'success': True,
            'message': f'Connected to {ssid}',
            'ssid': ssid,
            'ip': ip_addr
        })
    else:
        return jsonify({
            'success': False,
            'error': f'Could not connect to {ssid}. Check password and try again.'
        }), 400


@app.route('/api/network/wifi-disconnect', methods=['POST'])
def wifi_disconnect():
    """Disconnect wlan1 from WiFi network"""
    subprocess.run(['sudo', '-n', 'systemctl', 'stop', 'wpa_supplicant@wlan1'],
                   capture_output=True)
    subprocess.run(['sudo', '-n', 'ip', 'addr', 'flush', 'dev', 'wlan1'],
                   capture_output=True)

    # Remove saved config
    config_file = '/opt/chonkyflipper/config/wifi-client.conf'
    if os.path.isfile(config_file):
        os.remove(config_file)

    return jsonify({
        'success': True,
        'message': 'Disconnected from WiFi'
    })


@app.route('/api/system/poweroff', methods=['POST'])
def system_poweroff():
    """Shut down the Raspberry Pi"""
    try:
        subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
        return jsonify({'success': True, 'message': 'Shutting down...'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/system/version', methods=['GET'])
def system_version():
    """Get the currently deployed version"""
    version_file = '/opt/chonkyflipper/VERSION'
    try:
        if os.path.isfile(version_file):
            with open(version_file) as f:
                sha = f.read().strip()
            return jsonify({
                'sha': sha,
                'repo': 'github.com/jhannesreimann/chonkyflipper'
            })
        else:
            # Fallback: try git (may fail if repo is inaccessible to chonky user)
            repo_dir = '/home/kali/chonkyflipper'
            if os.path.isdir(os.path.join(repo_dir, '.git')):
                try:
                    sha = subprocess.check_output(
                        ['git', 'rev-parse', '--short', 'HEAD'],
                        cwd=repo_dir, stderr=subprocess.DEVNULL
                    ).decode().strip()
                    return jsonify({
                        'sha': sha,
                        'repo': 'github.com/jhannesreimann/chonkyflipper'
                    })
                except Exception:
                    pass
            return jsonify({'sha': 'unknown'})
    except Exception as e:
        return jsonify({'sha': 'unknown', 'error': str(e)})


@app.route('/api/system/update', methods=['POST'])
def system_update():
    """Pull latest code from GitHub and deploy (requires internet)"""
    try:
        # Check internet first
        try:
            subprocess.run(['ping', '-c', '1', '-W', '3', 'github.com'],
                         capture_output=True, check=True)
        except:
            return jsonify({
                'success': False,
                'error': (
                    'No internet connection.\n\n'
                    'Connect an Ethernet cable to the Pi for seamless updates '
                    '(the Chonky_Control AP stays up).\n\n'
                    'Or enable Maintenance Mode in Settings to connect via WiFi.'
                )
            }), 400

        # Check update script exists
        if not os.path.isfile('/opt/chonkyflipper/update.sh'):
            return jsonify({
                'success': False,
                'error': 'Update script not found at /opt/chonkyflipper/update.sh'
            }), 500

        # Run update in background so the response returns before the
        # service restarts itself. The update script runs systemctl restart
        # at the end, which kills this process  --  we must be detached.
        subprocess.Popen(
            ['sudo', '/opt/chonkyflipper/update.sh'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True  # detach from gunicorn process group
        )

        return jsonify({
            'success': True,
            'message': (
                'Update started in background.\n'
                'The backend will restart when the update completes.\n'
                'The dashboard will reconnect automatically in a few seconds.'
            )
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/zigbee/bridge', methods=['GET'])
def zigbee_bridge():
    """Get Zigbee2MQTT bridge status and configuration"""
    zigbee = get_module('zigbee')
    return jsonify(zigbee.get_bridge_info())


@app.route('/api/zigbee/devices', methods=['GET'])
def zigbee_devices():
    """List all paired Zigbee devices"""
    zigbee = get_module('zigbee')
    return jsonify(zigbee.get_devices())


@app.route('/api/zigbee/permit_join', methods=['POST'])
def zigbee_permit_join():
    """Enable or disable Zigbee pairing mode"""
    data = request.json or {}
    enable = data.get('enable', True)
    duration = data.get('duration', 254)
    zigbee = get_module('zigbee')
    return jsonify(zigbee.permit_join(enable, duration))


@app.route('/api/zigbee/device/<device_name>', methods=['GET'])
def zigbee_device_state(device_name):
    """Get current state of a paired Zigbee device"""
    zigbee = get_module('zigbee')
    return jsonify(zigbee.get_device_state(device_name))


@app.route('/api/zigbee/device/<device_name>/set', methods=['POST'])
def zigbee_device_set(device_name):
    """Set state of a Zigbee device (e.g. {"state": "ON", "brightness": 128})"""
    payload = request.json or {}
    if not payload:
        return jsonify({'success': False, 'error': 'payload required'}), 400
    zigbee = get_module('zigbee')
    return jsonify(zigbee.set_device_state(device_name, payload))


@app.route('/api/zigbee/networkmap', methods=['GET'])
def zigbee_networkmap():
    """Get Zigbee mesh topology (nodes and links between paired devices)"""
    zigbee = get_module('zigbee')
    return jsonify(zigbee.get_network_map())


@app.route('/api/zigbee/device/<device_name>', methods=['DELETE'])
def zigbee_device_remove(device_name):
    """Remove (unpair) a Zigbee device"""
    zigbee = get_module('zigbee')
    return jsonify(zigbee.remove_device(device_name))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
