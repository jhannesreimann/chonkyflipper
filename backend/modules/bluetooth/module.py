#!/usr/bin/env python3
"""
Bluetooth/BLE Module - Raspberry Pi internal Bluetooth (hci0)
BLE discovery and beacon decoding via Bleak (BlueZ backend); pairing and
device info via bluetoothctl.
"""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

from config import HCI_CAPTURES_DIR, INSTALL_DIR

from .beacons import (
    parse_ibeacon, parse_eddystone, encode_eddystone_url,
    EDDYSTONE_UUID,
)
from .parsers import (
    parse_hci_inq, parse_sdptool, parse_bettercap_ble, cod_major,
)

_ADVERTISER_SCRIPT = f'{INSTALL_DIR}/ble-advertiser.py'
_ADVERTISER_PID = f'{INSTALL_DIR}/ble-advertiser.pid'

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    BleakScanner = None
    BleakClient = None


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
            beacon = parse_ibeacon(adv) or parse_eddystone(adv)
            if beacon:
                beacon['mac'] = address.upper()
                beacon['rssi'] = adv.rssi
                beacons.append(beacon)
        beacons.sort(key=lambda b: b['rssi'] if b['rssi'] is not None else -999, reverse=True)
        return {'success': True, 'beacons': beacons}

    # advertisement logging

    def log_advertisements(self, duration=15):
        """Passively log BLE advertisements over a time window."""
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
            beacon = parse_ibeacon(adv) or parse_eddystone(adv)
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

    # GATT profiling

    def profile_device(self, mac_address, read_values=True):
        """Connect to a BLE device and enumerate its GATT services."""
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
        """Write bytes (given as a hex string) to a writable GATT characteristic."""
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
        """Discover Classic (BR/EDR) devices via hcitool inquiry."""
        try:
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

        devices = parse_hci_inq(result.stdout)
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

        services = parse_sdptool(result.stdout)
        return {'success': True, 'mac': mac_address, 'services': services}

    # raw HCI capture

    def capture_hci(self, duration=20, filename=None):
        """Capture raw HCI traffic to a btsnoop (.pcap) file via btmon."""
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
        """Deep BLE scan via bettercap for richer metadata."""
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

        devices = parse_bettercap_ble(result.stdout)
        if not devices and result.returncode not in (0, 124):
            err = (result.stderr or '').strip()
            return {'success': False, 'devices': [],
                    'error': err or 'bettercap returned no devices'}
        devices.sort(key=lambda d: d['rssi'] if d['rssi'] is not None else -999, reverse=True)
        return {'success': True, 'duration': duration, 'engine': 'bettercap', 'devices': devices}

    # advertisement spoofing

    def spoof_advertisement(self, params):
        """Broadcast a crafted BLE advertisement via a detached advertiser process."""
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
        """Translate the high-level spoof form into the low-level advert config."""
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
            encoded, err = encode_eddystone_url(params.get('url') or '')
            if err:
                return None, err
            tx = int(params.get('tx_power', -59)) & 0xFF
            cfg['service_uuids'] = sorted(set(cfg['service_uuids'] + ['feaa']))
            cfg['service_data'] = {EDDYSTONE_UUID: f'10{tx:02x}{encoded}'}
            cfg['type'] = 'broadcast'

        elif frame == 'eddystone-uid':
            ns = (params.get('namespace') or '').replace('-', '')
            inst = (params.get('instance') or '').replace('-', '')
            if len(ns) != 20 or len(inst) != 12:
                return None, 'Eddystone-UID needs a 10-byte namespace and 6-byte instance'
            tx = int(params.get('tx_power', -59)) & 0xFF
            cfg['service_uuids'] = sorted(set(cfg['service_uuids'] + ['feaa']))
            cfg['service_data'] = {EDDYSTONE_UUID: f'00{tx:02x}{ns}{inst}'}
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
