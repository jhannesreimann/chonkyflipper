#!/usr/bin/env python3
"""
Bluetooth/BLE Module - Raspberry Pi internal Bluetooth (hci0)
BLE discovery and beacon decoding via Bleak (BlueZ backend); pairing and
device info via bluetoothctl.
"""

import asyncio
import re
import struct
import subprocess
from datetime import datetime

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    BleakScanner = None
    BleakClient = None

try:
    import bluetooth as _pybluez  # PyBluez / pybluez2 (Classic SDP browsing)
except ImportError:
    _pybluez = None

# Eddystone service UUID (16-bit 0xFEAA in full 128-bit form)
_EDDYSTONE_UUID = '0000feaa-0000-1000-8000-00805f9b34fb'
# Company identifier Apple uses for iBeacon manufacturer data
_APPLE_COMPANY_ID = 0x004C

# Eddystone-URL scheme prefixes and expansion codes (Eddystone spec)
_URL_SCHEMES = ['http://www.', 'https://www.', 'http://', 'https://']
_URL_EXPANSIONS = [
    '.com/', '.org/', '.edu/', '.net/', '.info/', '.biz/', '.gov/',
    '.com', '.org', '.edu', '.net', '.info', '.biz', '.gov',
]

# Bluetooth Class of Device -> major device class label (bits 8-12 of the CoD)
_COD_MAJOR = {
    0: 'Miscellaneous', 1: 'Computer', 2: 'Phone', 3: 'Network',
    4: 'Audio/Video', 5: 'Peripheral', 6: 'Imaging', 7: 'Wearable',
    8: 'Toy', 9: 'Health',
}
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
_MAC_RE = re.compile(r'([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})')


class BluetoothModule:
    """BLE scanning and beacon decoding via Bleak / BlueZ, interface hci0."""

    def __init__(self, interface='hci0'):
        self.interface = interface

    # ------------------------------------------------------------------ scanning

    def _discover(self, duration):
        """Run one BLE discovery pass. Returns {address: (BLEDevice, AdvertisementData)}."""
        if BleakScanner is None:
            raise RuntimeError('bleak is not installed (pip install bleak)')

        async def _run():
            return await BleakScanner.discover(
                timeout=duration, return_adv=True, adapter=self.interface,
            )

        return asyncio.run(_run())

    def scan_ble(self, duration=8):
        """Scan for BLE devices. Returns dict with a device list (MAC, name, RSSI)."""
        try:
            found = self._discover(duration)
        except Exception as e:
            return {'success': False, 'error': str(e), 'devices': []}

        devices = []
        for address, (device, adv) in found.items():
            devices.append({
                'mac': address.upper(),
                'name': adv.local_name or device.name or 'Unknown',
                'rssi': adv.rssi,
                'services': len(adv.service_uuids),
            })
        # Strongest signal first so the closest devices are easy to spot.
        devices.sort(key=lambda d: d['rssi'] if d['rssi'] is not None else -999, reverse=True)
        return {'success': True, 'devices': devices}

    def scan_beacons(self, duration=8):
        """Scan and decode iBeacon and Eddystone advertisements."""
        try:
            found = self._discover(duration)
        except Exception as e:
            return {'success': False, 'error': str(e), 'beacons': []}

        beacons = []
        for address, (device, adv) in found.items():
            beacon = self._parse_ibeacon(adv) or self._parse_eddystone(adv)
            if beacon:
                beacon['mac'] = address.upper()
                beacon['rssi'] = adv.rssi
                beacons.append(beacon)
        beacons.sort(key=lambda b: b['rssi'] if b['rssi'] is not None else -999, reverse=True)
        return {'success': True, 'beacons': beacons}

    # ------------------------------------------------------------------ advertisement logging

    def log_advertisements(self, duration=15):
        """Passively log BLE advertisements over a time window.

        Unlike scan_ble (one deduplicated snapshot), this counts every
        advertisement seen per device, tracking sighting count and RSSI range,
        so presence and signal drift over the window are visible.
        """
        if BleakScanner is None:
            return {'success': False, 'error': 'bleak is not installed', 'devices': []}
        try:
            devices = asyncio.run(self._capture(duration))
        except Exception as e:
            return {'success': False, 'error': str(e), 'devices': []}
        return {
            'success': True,
            'duration': duration,
            'count': sum(d['count'] for d in devices),
            'devices': devices,
        }

    async def _capture(self, duration):
        summary = {}

        def on_advert(device, adv):
            mac = device.address.upper()
            name = adv.local_name or device.name or 'Unknown'
            rssi = adv.rssi
            beacon = self._parse_ibeacon(adv) or self._parse_eddystone(adv)
            btype = beacon['type'] if beacon else None
            ts = datetime.now().isoformat()

            d = summary.get(mac)
            if d is None:
                d = summary[mac] = {
                    'mac': mac, 'name': name, 'beacon': btype, 'count': 0,
                    'rssi_last': None, 'rssi_min': None, 'rssi_max': None,
                    'first_seen': ts, 'last_seen': ts,
                }
            d['count'] += 1
            d['last_seen'] = ts
            if name != 'Unknown':
                d['name'] = name
            if btype and not d['beacon']:
                d['beacon'] = btype
            if rssi is not None:
                d['rssi_last'] = rssi
                d['rssi_min'] = rssi if d['rssi_min'] is None else min(d['rssi_min'], rssi)
                d['rssi_max'] = rssi if d['rssi_max'] is None else max(d['rssi_max'], rssi)

        scanner = BleakScanner(detection_callback=on_advert, adapter=self.interface)
        await scanner.start()
        try:
            await asyncio.sleep(duration)
        finally:
            await scanner.stop()
        return sorted(summary.values(), key=lambda d: d['count'], reverse=True)

    # ------------------------------------------------------------------ beacon decode

    @staticmethod
    def _parse_ibeacon(adv):
        data = adv.manufacturer_data.get(_APPLE_COMPANY_ID)
        # iBeacon prefix is 0x02 0x15 followed by 21 bytes (UUID + major + minor + tx).
        if not data or len(data) < 23 or data[0] != 0x02 or data[1] != 0x15:
            return None
        u = data[2:18].hex()
        uuid = f'{u[0:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:32]}'
        return {
            'type': 'iBeacon',
            'uuid': uuid,
            'major': int.from_bytes(data[18:20], 'big'),
            'minor': int.from_bytes(data[20:22], 'big'),
            'tx_power': struct.unpack('b', data[22:23])[0],
        }

    @classmethod
    def _parse_eddystone(cls, adv):
        data = adv.service_data.get(_EDDYSTONE_UUID)
        if not data:
            return None
        frame = data[0]
        if frame == 0x00 and len(data) >= 18:  # UID frame
            namespace = data[2:12].hex()
            instance = data[12:18].hex()
            return {'type': 'Eddystone-UID', 'namespace': namespace,
                    'instance': instance, 'id': namespace + instance}
        if frame == 0x10:  # URL frame
            return {'type': 'Eddystone-URL', 'id': cls._decode_eddystone_url(data)}
        if frame == 0x20:  # TLM (telemetry) frame
            return {'type': 'Eddystone-TLM'}
        return {'type': 'Eddystone'}

    @staticmethod
    def _decode_eddystone_url(data):
        if len(data) < 3:
            return None
        scheme = data[2]
        url = _URL_SCHEMES[scheme] if scheme < len(_URL_SCHEMES) else ''
        for b in data[3:]:
            url += _URL_EXPANSIONS[b] if b < len(_URL_EXPANSIONS) else chr(b)
        return url

    # ------------------------------------------------------------------ GATT profiling

    def profile_device(self, mac_address, read_values=True):
        """Connect to a BLE device and enumerate its GATT services,
        characteristics, descriptors, and (optionally) readable values."""
        if BleakClient is None:
            return {'success': False, 'error': 'bleak is not installed', 'mac': mac_address}
        try:
            return asyncio.run(self._profile(mac_address, read_values))
        except Exception as e:
            return {'success': False, 'error': str(e), 'mac': mac_address}

    async def _profile(self, mac_address, read_values):
        services = []
        async with BleakClient(mac_address, timeout=20.0, adapter=self.interface) as client:
            for service in client.services:
                characteristics = []
                for char in service.characteristics:
                    value_hex = value_text = None
                    # Reading is best-effort: many characteristics are write/notify
                    # only, or need pairing, so guard each read individually.
                    if read_values and 'read' in char.properties:
                        try:
                            raw = await client.read_gatt_char(char.uuid)
                            value_hex = raw.hex()
                            value_text = self._printable(raw)
                        except Exception:
                            pass
                    characteristics.append({
                        'uuid': str(char.uuid),
                        'name': char.description or '',
                        'handle': char.handle,
                        'properties': list(char.properties),
                        'value_hex': value_hex,
                        'value_text': value_text,
                        'descriptors': [
                            {'uuid': str(d.uuid), 'handle': d.handle}
                            for d in char.descriptors
                        ],
                    })
                services.append({
                    'uuid': str(service.uuid),
                    'name': service.description or '',
                    'characteristics': characteristics,
                })
        return {'success': True, 'mac': mac_address, 'services': services}

    @staticmethod
    def _printable(raw):
        """Return a UTF-8 string if the bytes are printable text, else None."""
        try:
            text = raw.decode('utf-8').strip('\x00')
        except Exception:
            return None
        if text and all(32 <= ord(c) <= 126 or c in '\r\n\t' for c in text):
            return text
        return None

    # ------------------------------------------------------------------ Classic BT (BR/EDR) + SDP

    def scan_classic(self, duration=10):
        """Discover Classic (BR/EDR) devices via a bluetoothd-managed inquiry.

        Runs bluetoothctl scan for `duration` seconds and parses the discovery
        events, keeping devices that report a Class of Device (the BR/EDR
        signal) so BLE-only devices are filtered out.
        """
        try:
            result = subprocess.run(
                ['bluetoothctl', '--timeout', str(duration), 'scan', 'on'],
                capture_output=True, text=True, timeout=duration + 15,
            )
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Classic scan timed out', 'devices': []}
        except FileNotFoundError:
            return {'success': False, 'error': 'bluetoothctl not found', 'devices': []}
        except Exception as e:
            return {'success': False, 'error': str(e), 'devices': []}

        devices = self._parse_classic_scan(result.stdout)
        devices.sort(key=lambda d: d['rssi'] if d['rssi'] is not None else -999, reverse=True)
        return {'success': True, 'duration': duration, 'devices': devices}

    def _parse_classic_scan(self, output):
        found = {}
        for raw in output.splitlines():
            line = _ANSI_RE.sub('', raw).strip()
            m = _MAC_RE.search(line)
            if not m:
                continue
            mac = m.group(1).upper()
            rest = line[m.end():].strip()
            d = found.setdefault(mac, {'mac': mac, 'name': None, 'rssi': None, 'cod': None})
            if ':' in rest:
                key, _, val = rest.partition(':')
                key, val = key.strip(), val.strip()
                if key == 'RSSI':
                    try:
                        d['rssi'] = int(val.split()[0])
                    except (ValueError, IndexError):
                        pass
                elif key == 'Class':
                    d['cod'] = val
                elif key == 'Name':
                    d['name'] = val
            elif rest and d['name'] is None:
                d['name'] = rest
        # Keep only BR/EDR devices (those that reported a Class of Device).
        classic = []
        for d in found.values():
            if not d['cod']:
                continue
            d['type'] = self._cod_major(d['cod'])
            d.pop('cod', None)
            classic.append(d)
        return classic

    @staticmethod
    def _cod_major(cod):
        try:
            val = int(cod, 16)
        except (TypeError, ValueError):
            return 'Unknown'
        return _COD_MAJOR.get((val >> 8) & 0x1F, 'Unknown')

    def enumerate_services(self, mac_address):
        """SDP browse a Classic device for its service records (RFCOMM channels,
        protocols, profiles) via PyBluez."""
        if _pybluez is None:
            return {'success': False, 'error': 'PyBluez is not installed (pip install pybluez2)',
                    'services': [], 'mac': mac_address}
        try:
            records = _pybluez.find_service(address=mac_address)
        except Exception as e:
            return {'success': False, 'error': str(e), 'services': [], 'mac': mac_address}

        services = []
        for r in records:
            services.append({
                'name': self._clean(r.get('name')),
                'protocol': r.get('protocol'),
                'channel': r.get('port'),
                'service_classes': r.get('service-classes') or [],
                'profiles': [p[0] for p in (r.get('profiles') or []) if p],
                'description': self._clean(r.get('description')),
            })
        return {'success': True, 'mac': mac_address, 'services': services}

    @staticmethod
    def _clean(v):
        return v.decode('utf-8', 'replace') if isinstance(v, bytes) else v

    # ------------------------------------------------------------------ pairing (bluetoothctl)

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
