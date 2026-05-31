#!/usr/bin/env python3
"""
ChonkyFlipper Backend - Flask API Server
Mobile IoT Pentesting Rig Controller
"""

import os
import subprocess
import json
from flask import Flask, jsonify, request
from flask_cors import CORS
from modules.wifi import WiFiModule
from modules.bluetooth import BluetoothModule
from modules.ir import IRModule
from modules.cc1101 import CC1101Module
from modules.pn532 import PN532Module
from modules.badusb import BadUSBModule

app = Flask(__name__)
CORS(app)  # Enable CORS for mobile web app access

# Initialize modules (lazy loading on first use)
modules = {}

_pipower = None

def _get_power_data():
    global _pipower
    try:
        if _pipower is None:
            from pipower5 import PiPower5
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
            'badusb': BadUSBModule
        }
        modules[name] = module_map[name]()
    return modules[name]

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get overall system status"""
    return jsonify({
        'status': 'online',
        'hostname': 'chonkyflipper',
        'modules': {
            'wifi': {'available': True, 'interface': 'wlan1'},
            'bluetooth': {'available': True, 'interface': 'hci0'},
            'ir': {'available': True, 'gpio': '17/27'},
            'cc1101': {'available': True, 'spi': '0.0'},
            'pn532': {'available': True, 'i2c': '0x24'},
            'zigbee': {'available': True, 'usb': 'ttyUSB0'}
        },
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
        # Check hostapd status
        hostapd_active = subprocess.run(
            ['systemctl', 'is-active', 'hostapd'],
            capture_output=True
        ).returncode == 0
        
        # Check client mode status
        wpa_active = subprocess.run(
            ['systemctl', 'is-active', 'wpa_supplicant@wlan0'],
            capture_output=True
        ).returncode == 0
        
        # Check internet connectivity
        try:
            subprocess.run(['ping', '-c', '1', '-W', '2', '8.8.8.8'], 
                         capture_output=True, check=True)
            internet = True
        except:
            internet = False
        
        return jsonify({
            'ap_mode': hostapd_active,
            'client_mode': wpa_active,
            'internet_available': internet,
            'ap_ssid': 'Chonky_Control' if hostapd_active else None,
            'ap_ip': '192.168.4.1' if hostapd_active else None
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

@app.route('/api/system/update', methods=['POST'])
def system_update():
    """Run git pull to update ChonkyFlipper (requires internet)"""
    try:
        # Check internet first
        try:
            subprocess.run(['ping', '-c', '1', '-W', '2', 'github.com'],
                         capture_output=True, check=True)
        except:
            return jsonify({
                'success': False,
                'error': 'No internet connection. Enable maintenance mode first.'
            }), 400
        
        # Run update script
        result = subprocess.run(
            ['/opt/chonkyflipper/update.sh'],
            capture_output=True,
            text=True
        )
        
        return jsonify({
            'success': result.returncode == 0,
            'output': result.stdout,
            'error': result.stderr if result.returncode != 0 else None
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
