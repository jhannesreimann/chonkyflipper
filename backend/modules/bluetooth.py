#!/usr/bin/env python3
"""
Bluetooth/BLE Module - Raspberry Pi internal Bluetooth (hci0)
BLE discovery and beacon decoding via Bleak (BlueZ backend); pairing and
device info via bluetoothctl.
"""

import asyncio
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
from datetime import datetime

from config import HCI_CAPTURES_DIR, INSTALL_DIR

_ADVERTISER_SCRIPT = f'{INSTALL_DIR}/ble-advertiser.py'
_ADVERTISER_PID = f'{INSTALL_DIR}/ble-advertiser.pid'

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    BleakScanner = None
    BleakClient = None


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

    # scanning

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

    # advertisement logging

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

    # beacon decode

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

    # GATT profiling

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

    def write_characteristic(self, mac_address, char_uuid, value_hex, without_response=None):
        """Write bytes (given as a hex string) to a writable GATT characteristic.

        without_response: None = auto (prefer write-with-response when the
        characteristic supports it), True = force write-without-response,
        False = force write-with-response.
        """
        if BleakClient is None:
            return {'success': False, 'error': 'bleak is not installed', 'mac': mac_address}
        try:
            data = bytes.fromhex(str(value_hex).replace('0x', '').replace(' ', '').replace(':', ''))
        except ValueError:
            return {'success': False, 'error': 'value must be a valid hex string'}
        try:
            return asyncio.run(self._write(mac_address, char_uuid, data, without_response))
        except Exception as e:
            return {'success': False, 'error': str(e), 'mac': mac_address}

    async def _write(self, mac_address, char_uuid, data, without_response):
        async with BleakClient(mac_address, timeout=20.0, adapter=self.interface) as client:
            char = client.services.get_characteristic(char_uuid)
            if char is None:
                return {'success': False, 'error': f'Characteristic {char_uuid} not found'}
            props = char.properties
            if without_response:
                if 'write-without-response' not in props:
                    return {'success': False, 'error': 'Characteristic does not support write-without-response'}
                response = False
            elif without_response is False:
                if 'write' not in props:
                    return {'success': False, 'error': 'Characteristic does not support write-with-response'}
                response = True
            elif 'write' in props:
                response = True
            elif 'write-without-response' in props:
                response = False
            else:
                return {'success': False, 'error': 'Characteristic is not writable'}
            await client.write_gatt_char(char, data, response=response)
            return {
                'success': True, 'mac': mac_address, 'char_uuid': char_uuid,
                'bytes_written': len(data), 'with_response': response,
            }

    # Classic BT (BR/EDR) + SDP

    def scan_classic(self, duration=10):
        """Discover Classic (BR/EDR) devices via hcitool inquiry.

        hcitool inq performs a real BR/EDR inquiry (unlike bluetoothctl scan
        which defaults to BLE).  Each response includes the Class of Device so
        we know the device is BR/EDR-capable without guessing.
        """
        try:
            # --length is in 1.28 s units; cap at a reasonable max.
            length = max(1, min(int(duration / 1.28), 60))
        except (TypeError, ValueError):
            length = 8
        try:
            result = subprocess.run(
                ['hcitool', 'inq', '--flush', '--length', str(length)],
                capture_output=True, text=True, timeout=duration + 15,
            )
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Classic scan timed out', 'devices': []}
        except FileNotFoundError:
            return {'success': False, 'error': 'hcitool not found (install bluez-hcidump)', 'devices': []}
        except Exception as e:
            return {'success': False, 'error': str(e), 'devices': []}

        devices = self._parse_hci_inq(result.stdout)
        # Resolve friendly names (best-effort, one at a time).
        for d in devices:
            try:
                name = subprocess.run(
                    ['hcitool', 'name', d['mac']],
                    capture_output=True, text=True, timeout=5,
                )
                n = name.stdout.strip()
                if n and ':' not in n and n != 'Unknown':
                    d['name'] = n
            except Exception:
                pass
        devices.sort(key=lambda d: d['rssi'] if d['rssi'] is not None else -999, reverse=True)
        return {'success': True, 'duration': duration, 'devices': devices}

    def _parse_hci_inq(self, output):
        devices = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith('Inquiring'):
                continue
            m = _MAC_RE.search(line)
            if not m:
                continue
            d = {'mac': m.group(1).upper(), 'name': None, 'rssi': None}
            # Class of Device - e.g. "class: 0x0c043c"
            cm = re.search(r'class:\s*(0x[0-9a-fA-F]+)', line)
            if cm:
                d['type'] = self._cod_major(cm.group(1))
            else:
                d['type'] = 'Unknown'
            devices.append(d)
        return devices

    @staticmethod
    def _cod_major(cod):
        try:
            val = int(cod, 16)
        except (TypeError, ValueError):
            return 'Unknown'
        return _COD_MAJOR.get((val >> 8) & 0x1F, 'Unknown')

    def enumerate_services(self, mac_address):
        """SDP browse a Classic device via sdptool (part of bluez)."""
        try:
            result = subprocess.run(
                ['sdptool', 'browse', mac_address],
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'SDP browse timed out',
                    'services': [], 'mac': mac_address}
        except FileNotFoundError:
            return {'success': False, 'error': 'sdptool not found (install bluez)',
                    'services': [], 'mac': mac_address}
        except Exception as e:
            return {'success': False, 'error': str(e), 'services': [], 'mac': mac_address}

        if result.returncode != 0:
            err = (result.stderr or '').strip()
            return {'success': False, 'error': err or 'SDP browse failed',
                    'services': [], 'mac': mac_address}

        services = self._parse_sdptool(result.stdout)
        return {'success': True, 'mac': mac_address, 'services': services}

    @staticmethod
    def _parse_sdptool(output):
        """Parse sdptool browse output into structured service records."""
        services = []
        cur = None
        in_list = None  # current list key: 'classes', 'protocols', 'profiles'

        for raw in output.splitlines():
            line = raw.rstrip()

            # Service Name: (may appear before or after RecHandle)
            if line.startswith('Service Name:') or line.startswith('Service Provider:'):
                if cur is None:
                    cur = {'name': None, 'protocol': None, 'channel': None,
                           'service_classes': [], 'profiles': []}
                val = line.split(':', 1)[1].strip()
                if val and line.startswith('Service Name:'):
                    cur['name'] = val
                continue

            # Service RecHandle starts a new record (some records have no name)
            if line.startswith('Service RecHandle:'):
                if cur is not None:
                    services.append(cur)
                cur = {'name': None, 'protocol': None, 'channel': None,
                       'service_classes': [], 'profiles': []}
                in_list = None
                continue

            if cur is None:
                continue

            # "Service Class ID List:" / "Protocol Descriptor List:" / "Profile Descriptor List:"
            if line.startswith('Service Class ID List:'):
                in_list = 'classes'
                continue
            if line.startswith('Protocol Descriptor List:'):
                in_list = 'protocols'
                continue
            if line.startswith('Profile Descriptor List:'):
                in_list = 'profiles'
                continue

            # Indented list items
            stripped = line.lstrip()
            if not stripped:
                in_list = None
                continue

            if in_list == 'classes':
                # "Headset Audio Gateway" (0x1112)
                m = re.match(r'"([^"]+)"\s*\(0x[0-9a-fA-F]+\)', stripped)
                if m:
                    cur['service_classes'].append(m.group(1))

            elif in_list == 'protocols':
                # "L2CAP" (0x0100)  or  "RFCOMM" (0x0003)
                m = re.match(r'"([^"]+)"\s*\(0x[0-9a-fA-F]+\)', stripped)
                if m:
                    cur['protocol'] = m.group(1)
                if stripped.startswith('Channel:'):
                    try:
                        cur['channel'] = int(stripped.split(':')[1].strip())
                    except (ValueError, IndexError):
                        pass

            elif in_list == 'profiles':
                m = re.match(r'"([^"]+)"\s*\(0x[0-9a-fA-F]+\)', stripped)
                if m:
                    cur['profiles'].append(m.group(1))

        if cur is not None:
            services.append(cur)
        return services

    # raw HCI capture

    def capture_hci(self, duration=20, filename=None):
        """Capture raw HCI traffic to a btsnoop (.pcap) file via btmon for
        offline Wireshark analysis. Blocks for `duration` seconds.

        btmon needs CAP_NET_RAW; install.sh grants it via setcap so this runs
        without sudo and the file stays owned by the service user.
        """
        os.makedirs(HCI_CAPTURES_DIR, exist_ok=True)
        if not filename:
            filename = f'hci_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pcap'
        filename = os.path.basename(filename)
        if not filename.endswith('.pcap'):
            filename += '.pcap'
        path = os.path.join(HCI_CAPTURES_DIR, filename)
        try:
            result = subprocess.run(
                ['timeout', str(duration), 'btmon', '-w', path],
                capture_output=True, text=True, timeout=duration + 15,
            )
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'HCI capture timed out'}
        except FileNotFoundError:
            return {'success': False, 'error': 'btmon not found (install bluez)'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            err = (result.stderr or '').strip()
            return {'success': False,
                    'error': err or 'capture produced no data (btmon needs CAP_NET_RAW; run the setcap step)'}
        return {'success': True, 'filename': filename,
                'size': os.path.getsize(path), 'duration': duration}


    # deep scan (bettercap)

    def deep_scan(self, duration=15):
        """Deep BLE scan via bettercap for richer metadata (notably the MAC
        manufacturer / vendor). Opt-in; falls back gracefully when bettercap
        is not installed."""
        if shutil.which('bettercap') is None:
            return {'success': False, 'devices': [],
                    'error': 'bettercap is not installed (sudo apt install bettercap)'}
        script = f'{INSTALL_DIR}/bt-deep-scan.sh'
        if not os.path.isfile(script):
            return {'success': False, 'devices': [],
                    'error': 'bt-deep-scan.sh not deployed; run update.sh'}
        try:
            result = subprocess.run(
                ['sudo', '-n', script, str(duration)],
                capture_output=True, text=True, timeout=duration + 30,
            )
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Deep scan timed out', 'devices': []}
        except Exception as e:
            return {'success': False, 'error': str(e), 'devices': []}

        devices = self._parse_bettercap_ble(result.stdout)
        if not devices and result.returncode not in (0, 124):
            err = (result.stderr or '').strip()
            return {'success': False, 'devices': [],
                    'error': err or 'bettercap returned no devices'}
        devices.sort(key=lambda d: d['rssi'] if d['rssi'] is not None else -999, reverse=True)
        return {'success': True, 'duration': duration, 'engine': 'bettercap', 'devices': devices}

    @staticmethod
    def _parse_bettercap_ble(output):
        # bettercap renders a table with a vertical-bar separator; normalise it
        # to ASCII and map columns by their header so column order changes
        # between versions don't break parsing.
        devices = []
        idx = None
        for raw in output.splitlines():
            line = _ANSI_RE.sub('', raw).replace(chr(0x2502), '|')
            if '|' not in line:
                continue
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if not cells:
                continue
            upper = [c.upper() for c in cells]
            if idx is None:
                if any('RSSI' in c for c in upper) and any('MAC' in c for c in upper):
                    idx = {
                        'rssi': next((i for i, c in enumerate(upper) if 'RSSI' in c), 0),
                        'mac': next((i for i, c in enumerate(upper) if c == 'MAC'), 0),
                        'vendor': next((i for i, c in enumerate(upper) if c == 'VENDOR'), None),
                        'name': next((i for i, c in enumerate(upper) if c == 'NAME'), None),
                        'connect': next((i for i, c in enumerate(upper) if c == 'CONNECT'), None),
                    }
                continue
            if idx['mac'] >= len(cells):
                continue
            mac = cells[idx['mac']]
            if not mac or ':' not in mac:
                continue
            rssi = None
            ri = idx['rssi']
            if ri < len(cells) and cells[ri]:
                try:
                    rssi = int(cells[ri].split()[0])
                except (ValueError, IndexError):
                    pass
            vendor = cells[idx['vendor']] if (idx['vendor'] is not None and idx['vendor'] < len(cells)) else None
            name = cells[idx['name']] if (idx['name'] is not None and idx['name'] < len(cells)) else None
            connect = cells[idx['connect']] if (idx['connect'] is not None and idx['connect'] < len(cells)) else ''
            devices.append({
                'mac': mac.upper(),
                'name': name or 'Unknown',
                'rssi': rssi,
                'vendor': vendor or None,
                'connectable': connect.strip().lower() in ('true', 'yes', '✓', '✔'),
            })
        return devices

    # advertisement spoofing

    def spoof_advertisement(self, params):
        """Broadcast a crafted BLE advertisement (device spoof / beacon) via a
        detached advertiser process. Replaces any advert already running."""
        cfg, err = self._build_advert(params)
        if err:
            return {'success': False, 'error': err}
        if not os.path.isfile(_ADVERTISER_SCRIPT):
            return {'success': False, 'error': 'ble-advertiser.py not deployed; run update.sh'}

        self._stop_advertiser()
        try:
            proc = subprocess.Popen(
                [sys.executable, _ADVERTISER_SCRIPT, json.dumps(cfg)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return {'success': False, 'error': str(e)}

        # If it dies right away it's usually a BlueZ permission / D-Bus issue.
        time.sleep(0.6)
        if proc.poll() is not None:
            return {'success': False,
                    'error': 'advertiser exited immediately (check BlueZ advertising permissions)'}

        try:
            with open(_ADVERTISER_PID, 'w') as f:
                f.write(str(proc.pid))
        except OSError:
            pass
        return {'success': True, 'pid': proc.pid, 'duration': cfg['duration'],
                'name': cfg.get('name') or None, 'frame': (params.get('frame') or 'custom')}

    def stop_spoof(self):
        return {'success': True, 'stopped': self._stop_advertiser()}

    def spoof_status(self):
        pid = self._read_pid()
        return {'success': True, 'running': pid is not None, 'pid': pid}

    def _stop_advertiser(self):
        pid = self._read_pid()
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        try:
            os.remove(_ADVERTISER_PID)
        except OSError:
            pass
        return pid is not None

    @staticmethod
    def _read_pid():
        try:
            with open(_ADVERTISER_PID) as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            return None
        try:
            os.kill(pid, 0)  # liveness check
            return pid
        except OSError:
            try:
                os.remove(_ADVERTISER_PID)
            except OSError:
                pass
            return None

    def _build_advert(self, params):
        """Translate the high-level spoof form into the low-level advert config
        the advertiser script consumes."""
        try:
            duration = max(1, min(int(params.get('duration', 60)), 600))
        except (TypeError, ValueError):
            duration = 60
        cfg = {
            'adapter': self.interface,
            'duration': duration,
            'type': params.get('type', 'peripheral'),
            'name': params.get('name') or '',
            'service_uuids': params.get('service_uuids') or [],
            'manufacturer_data': {},
            'service_data': {},
            'include_tx_power': bool(params.get('include_tx_power', False)),
        }
        frame = (params.get('frame') or 'custom').lower()

        if frame == 'ibeacon':
            uuid = (params.get('uuid') or '').replace('-', '')
            if len(uuid) != 32:
                return None, 'iBeacon requires a 16-byte (32 hex char) UUID'
            try:
                major = int(params.get('major', 0)) & 0xFFFF
                minor = int(params.get('minor', 0)) & 0xFFFF
                tx = int(params.get('tx_power', -59)) & 0xFF
            except (TypeError, ValueError):
                return None, 'invalid iBeacon major/minor/tx_power'
            cfg['manufacturer_data'] = {'76': f'0215{uuid}{major:04x}{minor:04x}{tx:02x}'}
            cfg['type'] = 'broadcast'

        elif frame == 'eddystone-url':
            encoded, err = self._encode_eddystone_url(params.get('url') or '')
            if err:
                return None, err
            tx = int(params.get('tx_power', -59)) & 0xFF
            cfg['service_uuids'] = sorted(set(cfg['service_uuids'] + ['feaa']))
            cfg['service_data'] = {'0000feaa-0000-1000-8000-00805f9b34fb': f'10{tx:02x}{encoded}'}
            cfg['type'] = 'broadcast'

        elif frame == 'eddystone-uid':
            ns = (params.get('namespace') or '').replace('-', '')
            inst = (params.get('instance') or '').replace('-', '')
            if len(ns) != 20 or len(inst) != 12:
                return None, 'Eddystone-UID needs a 10-byte namespace and 6-byte instance'
            tx = int(params.get('tx_power', -59)) & 0xFF
            cfg['service_uuids'] = sorted(set(cfg['service_uuids'] + ['feaa']))
            cfg['service_data'] = {'0000feaa-0000-1000-8000-00805f9b34fb': f'00{tx:02x}{ns}{inst}'}
            cfg['type'] = 'broadcast'

        else:  # custom / raw
            mfg_id = params.get('manufacturer_id')
            mfg_data = (params.get('manufacturer_data') or '').replace(' ', '')
            if mfg_id not in (None, '') and mfg_data:
                try:
                    cid = int(mfg_id)
                    bytes.fromhex(mfg_data)  # validate hex
                except (TypeError, ValueError):
                    return None, 'invalid manufacturer id or data'
                cfg['manufacturer_data'] = {str(cid): mfg_data}

        if not (cfg['name'] or cfg['service_uuids'] or cfg['manufacturer_data'] or cfg['service_data']):
            return None, 'advertisement is empty; set a name, service UUID, or data'
        return cfg, None

    @staticmethod
    def _encode_eddystone_url(url):
        if not url:
            return None, 'Eddystone-URL requires a url'
        scheme = None
        rest = url
        for i, prefix in enumerate(_URL_SCHEMES):
            if url.startswith(prefix):
                scheme, rest = i, url[len(prefix):]
                break
        if scheme is None:
            return None, 'url must start with http(s):// (optionally www.)'
        out = f'{scheme:02x}'
        i = 0
        while i < len(rest):
            for code, exp in enumerate(_URL_EXPANSIONS):
                if rest.startswith(exp, i):
                    out += f'{code:02x}'
                    i += len(exp)
                    break
            else:
                out += f'{ord(rest[i]):02x}'
                i += 1
        return out, None

    # pairing (bluetoothctl)

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

    # background ad log daemon

    _LOGGER_SCRIPT = f'{INSTALL_DIR}/ble-advert-logger.py'
    _LOGGER_PID = f'{INSTALL_DIR}/ble-advert-logger.pid'
    _LOGGER_STATE = f'{INSTALL_DIR}/ble-advert-log.json'

    def start_advert_log(self):
        """Start the background BLE advertisement logger daemon."""
        if not os.path.isfile(self._LOGGER_SCRIPT):
            return {'success': False, 'error': 'ble-advert-logger.py not deployed; run update.sh'}
        if self._logger_running():
            return {'success': False, 'error': 'Advert logger is already running'}

        self._stop_logger()
        try:
            proc = subprocess.Popen(
                [sys.executable, self._LOGGER_SCRIPT, self._LOGGER_STATE, self._LOGGER_PID],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return {'success': False, 'error': str(e)}

        time.sleep(0.8)
        if proc.poll() is not None:
            return {'success': False, 'error': 'Logger exited immediately (check bleak)'}

        try:
            with open(self._LOGGER_PID, 'w') as f:
                f.write(str(proc.pid))
        except OSError:
            pass
        return {'success': True, 'pid': proc.pid}

    def stop_advert_log(self):
        stopped = self._stop_logger()
        try:
            os.remove(self._LOGGER_STATE)
        except OSError:
            pass
        return {'success': True, 'stopped': stopped}

    def advert_log_status(self):
        pid = self._logger_running()
        return {'success': True, 'running': pid is not None, 'pid': pid}

    def advert_log_data(self):
        """Read the current state file from the running daemon."""
        try:
            with open(self._LOGGER_STATE) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {'success': True, 'running': False, 'devices': [], 'total_sightings': 0,
                    'device_count': 0, 'started_at': None}
        data['success'] = True
        return data

    def _stop_logger(self):
        pid = self._read_logger_pid()
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        try:
            os.remove(self._LOGGER_PID)
        except OSError:
            pass
        return pid is not None

    def _logger_running(self):
        pid = self._read_logger_pid()
        if pid is None:
            return None
        try:
            os.kill(pid, 0)
            return pid
        except OSError:
            try:
                os.remove(self._LOGGER_PID)
            except OSError:
                pass
            return None

    @classmethod
    def _read_logger_pid(cls):
        try:
            with open(cls._LOGGER_PID) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None
