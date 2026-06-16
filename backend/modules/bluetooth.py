#!/usr/bin/env python3
"""
Bluetooth/BLE Module - Uses Raspberry Pi internal Bluetooth
Scans for BLE devices and beacons via hcitool.
"""

import subprocess


class BluetoothModule:
    """BLE scanning and device interaction via hcitool / bluetoothctl"""

    def __init__(self, interface='hci0'):
        self.interface = interface

    def scan_ble(self, duration=10):
        """Scan for BLE devices. Returns list of devices with MAC, name."""
        devices = []
        seen_macs = set()

        try:
            stdout = subprocess.check_output(
                ['timeout', str(duration), 'hcitool', 'lescan'],
                stderr=subprocess.DEVNULL, text=True,
            )
            for line in stdout.split('\n'):
                if len(line) > 17:
                    mac = line[:17].strip().upper()
                    name = line[18:].strip() if len(line) > 18 else 'Unknown'
                    if mac and ':' in mac and mac not in seen_macs:
                        seen_macs.add(mac)
                        devices.append({
                            'mac': mac, 'name': name if name else 'Unknown',
                            'rssi': None, 'type': 'BLE',
                        })
        except subprocess.CalledProcessError:
            pass
        except Exception:
            pass

        return devices

    def scan_beacons(self, duration=10):
        """Scan for BLE beacons (iBeacon, Eddystone)."""
        beacons = []
        try:
            stdout = subprocess.check_output(
                ['timeout', str(duration), 'hcitool', 'lescan', '--duplicates'],
                stderr=subprocess.DEVNULL, text=True,
            )
            for line in stdout.split('\n'):
                data_lower = line.lower()
                if any(sig in data_lower for sig in ('ibeacon', 'eddystone', 'feaa', 'fff0')):
                    beacons.append({
                        'raw_data': line,
                        'type': self._detect_beacon_type(line),
                    })
        except subprocess.CalledProcessError:
            pass
        except Exception:
            pass

        return beacons

    @staticmethod
    def _detect_beacon_type(data):
        data_lower = data.lower()
        if 'feaa' in data_lower:
            return 'Eddystone'
        if 'fff0' in data_lower or 'ibeacon' in data_lower:
            return 'iBeacon'
        if 'fe9a' in data_lower:
            return 'Eddystone TLM'
        return 'Unknown'

    def get_device_info(self, mac_address):
        info = {'mac': mac_address, 'name': None, 'services': [], 'characteristics': []}
        try:
            result = subprocess.run(
                ['bluetoothctl', 'info', mac_address],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.split('\n'):
                if 'Name:' in line:
                    info['name'] = line.split(':', 1)[1].strip()
                elif 'Service' in line:
                    info['services'].append(line.strip())
        except Exception as e:
            info['error'] = str(e)
        return info

    def pair_device(self, mac_address):
        try:
            result = subprocess.run(
                ['bluetoothctl', 'pair', mac_address],
                capture_output=True, text=True, timeout=30,
            )
            success = 'Pairing successful' in result.stdout or 'Connected' in result.stdout
            return {'success': success, 'mac': mac_address, 'output': result.stdout,
                    'error': result.stderr if not success else None}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def disconnect(self, mac_address):
        try:
            subprocess.run(['bluetoothctl', 'disconnect', mac_address],
                           capture_output=True, timeout=10)
            return {'success': True, 'mac': mac_address}
        except Exception as e:
            return {'success': False, 'error': str(e)}
