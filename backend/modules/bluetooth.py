#!/usr/bin/env python3
"""
Bluetooth/BLE Module - Uses Raspberry Pi internal Bluetooth
Scans for BLE devices, beacons, and GATT services
"""

import subprocess
import json
import asyncio
from typing import List, Dict

class BluetoothModule:
    """BLE scanning and device interaction via bluetoothctl/hcitool"""
    
    def __init__(self, interface='hci0'):
        self.interface = interface
        self.scan_duration = 10  # seconds
    
    def scan_ble(self, duration=10):
        """
        Scan for BLE devices
        Returns list of devices with MAC, name, RSSI
        """
        devices = []
        
        try:
            # Use hcitool for basic LE scan
            stdout = subprocess.check_output(
                ['timeout', str(duration), 'hcitool', 'lescan'],
                stderr=subprocess.DEVNULL,
                text=True
            )
            
            # Parse output
            seen_macs = set()
            for line in stdout.split('\n'):
                if len(line) > 17:
                    mac = line[:17].strip().upper()
                    name = line[18:].strip() if len(line) > 18 else 'Unknown'
                    
                    if mac and ':' in mac and mac not in seen_macs:
                        seen_macs.add(mac)
                        devices.append({
                            'mac': mac,
                            'name': name if name else 'Unknown',
                            'rssi': None,  # Would need additional query
                            'type': 'BLE'
                        })
        except subprocess.CalledProcessError:
            pass
        except Exception as e:
            return [{'error': str(e)}]
        
        # Also try bluetoothctl for more info
        try:
            devices = self._scan_with_bluetoothctl(duration)
        except:
            pass
        
        return devices
    
    def _scan_with_bluetoothctl(self, duration):
        """Alternative scan using bluetoothctl"""
        devices = []
        
        try:
            # Start scan
            subprocess.run(
                ['bluetoothctl', 'scan', 'on'],
                input='scan on\n',
                capture_output=True,
                timeout=duration
            )
            
            # Get devices
            result = subprocess.run(
                ['bluetoothctl', 'devices'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            for line in result.stdout.split('\n'):
                if 'Device' in line:
                    parts = line.split(' ', 2)
                    if len(parts) >= 3:
                        mac = parts[1].upper()
                        name = parts[2]
                        devices.append({
                            'mac': mac,
                            'name': name,
                            'rssi': None,
                            'type': 'BLE/Classic'
                        })
        except:
            pass
        
        return devices
    
    def scan_beacons(self, duration=10):
        """
        Scan for BLE beacons (iBeacon, Eddystone)
        Useful for detecting presence sensors, tracking devices
        """
        beacons = []
        
        # Use hcitool with --duplicate to see all advertisements
        try:
            stdout = subprocess.check_output(
                ['timeout', str(duration), 'hcitool', 'lescan', '--duplicates'],
                stderr=subprocess.DEVNULL,
                text=True
            )
            
            # Parse for beacon-specific data
            for line in stdout.split('\n'):
                # Look for iBeacon signatures or Eddystone
                if any(sig in line.lower() for sig in ['ibeacon', 'eddystone', 'feaa', 'fff0']):
                    beacons.append({
                        'raw_data': line,
                        'type': self._detect_beacon_type(line)
                    })
        except:
            pass
        
        return beacons
    
    def _detect_beacon_type(self, data):
        """Detect beacon type from advertisement data"""
        data_lower = data.lower()
        if 'feaa' in data_lower:
            return 'Eddystone'
        elif 'fff0' in data_lower or 'ibeacon' in data_lower:
            return 'iBeacon'
        elif 'fe9a' in data_lower:
            return 'Eddystone TLM'
        return 'Unknown'
    
    def get_device_info(self, mac_address):
        """
        Get detailed information about a BLE device
        Uses gatttool or bluetoothctl
        """
        info = {
            'mac': mac_address,
            'name': None,
            'services': [],
            'characteristics': []
        }
        
        try:
            # Try to connect and get info
            result = subprocess.run(
                ['bluetoothctl', 'info', mac_address],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            for line in result.stdout.split('\n'):
                if 'Name:' in line:
                    info['name'] = line.split(':', 1)[1].strip()
                elif 'Service' in line:
                    info['services'].append(line.strip())
                    
        except Exception as e:
            info['error'] = str(e)
        
        return info
    
    def read_gatt(self, mac_address, service_uuid, char_uuid):
        """
        Read a GATT characteristic value
        For extracting data from BLE IoT devices
        """
        try:
            # Requires gatttool or better: bleak library
            # This is a placeholder - implement with bleak for production
            return {
                'success': False,
                'message': 'GATT read requires bleak library. Install with: pip3 install bleak'
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def pair_device(self, mac_address):
        """Attempt to pair with a Bluetooth device"""
        try:
            result = subprocess.run(
                ['bluetoothctl', 'pair', mac_address],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            success = 'Pairing successful' in result.stdout or 'Connected' in result.stdout
            
            return {
                'success': success,
                'mac': mac_address,
                'output': result.stdout,
                'error': result.stderr if not success else None
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def disconnect(self, mac_address):
        """Disconnect from a Bluetooth device"""
        try:
            subprocess.run(
                ['bluetoothctl', 'disconnect', mac_address],
                capture_output=True,
                timeout=10
            )
            return {'success': True, 'mac': mac_address}
        except Exception as e:
            return {'success': False, 'error': str(e)}
