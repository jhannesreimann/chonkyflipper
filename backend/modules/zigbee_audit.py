#!/usr/bin/env python3
"""
Zigbee Security Auditing Module - CC2531 sniffer via KillerBee
Passive capture, PAN discovery, key extraction, replay, DoS attacks.
Requires: CC2531 USB dongle with TI packet sniffer firmware.
"""

import os
import subprocess
from datetime import datetime
from config import DATA_DIR

KILLERBEE_DIR = '/opt/chonkyflipper/killerbee'
ZB_CAPTURES_DIR = os.path.join(DATA_DIR, 'zigbee_captures')
os.makedirs(ZB_CAPTURES_DIR, exist_ok=True)

# KillerBee needs its source tree on PYTHONPATH
_KB_ENV = os.environ.copy()
_KB_ENV['PYTHONPATH'] = KILLERBEE_DIR


class ZigbeeAuditModule:
    """Zigbee security auditing via KillerBee + CC2531 sniffer dongle."""

    def __init__(self):
        self.captures_dir = ZB_CAPTURES_DIR

    def _run_kb(self, tool, *args, timeout=30):
        """Run a KillerBee tool. Returns (stdout, stderr, returncode)."""
        script = os.path.join(KILLERBEE_DIR, 'tools', tool)
        if not os.path.isfile(script):
            return '', f'KillerBee tool not found: {script}', 1

        cmd = ['python3', script] + list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, env=_KB_ENV,
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return '', 'Command timed out', 1
        except Exception as e:
            return '', str(e), 1

    def _check_device(self):
        """Return True if the CC2531 sniffer dongle (VID:0451 PID:16AE) is on
        the USB bus. This is the stock TI packet sniffer dongle KillerBee drives."""
        try:
            out = subprocess.run(
                ['lsusb'], capture_output=True, text=True, timeout=5,
            ).stdout.lower()
        except Exception:
            return False
        return '0451:16ae' in out


    # Passive capture (zbdump)

    def capture_packets(self, channel=11, duration=30):
        """Capture raw 802.15.4 frames to pcap file."""
        if not self._check_device():
            return {'success': False,
                    'error': 'CC2531 sniffer dongle not found. Check USB connection.'}

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'zigbee_capture_{timestamp}.pcap'
        filepath = os.path.join(self.captures_dir, filename)

        stdout, stderr, rc = self._run_kb(
            'zbdump', '-c', str(channel), '-w', filepath, timeout=duration + 15,
        )

        file_exists = os.path.exists(filepath)
        file_size = os.path.getsize(filepath) if file_exists else 0

        if not file_exists or file_size == 0:
            return {'success': False,
                    'error': f'No packets captured on channel {channel}. '
                             f'Try a different channel or longer duration. '
                             f'(stderr: {stderr[:200]})',
                    'filename': filename}

        return {'success': True,
                'filename': filename, 'filepath': filepath,
                'size_bytes': file_size, 'channel': channel, 'duration': duration}

    # PAN discovery (zbstumbler)

    def scan_channels(self, channels='11-26', duration=30):
        """Passively scan for Zigbee PANs across channels."""
        if not self._check_device():
            return {'success': False,
                    'error': 'CC2531 sniffer dongle not found.'}

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(self.captures_dir, f'pan_scan_{timestamp}.csv')

        # zbstumbler -c for channels, -w for output CSV, runs until timeout
        stdout, stderr, rc = self._run_kb(
            'zbstumbler', '-c', channels, '-w', filepath, timeout=duration + 15,
        )

        # Parse output for PAN info
        pans = []
        for line in stdout.split('\n'):
            line = line.strip()
            if line and not line.startswith('zb'):
                pans.append(line)

        if not os.path.exists(filepath) and len(pans) == 0:
            return {'success': False,
                    'error': f'No PANs found on channels {channels}. '
                             f'Try different channels or longer duration.'}

        return {'success': True,
                'pans': pans, 'channels': channels, 'file': filepath,
                'output': stdout[-1000:]}



    # Key extraction (zbdsniff)

    def extract_keys(self, cap_file):
        """Attempt to extract Zigbee network keys from a capture file."""
        if not os.path.exists(cap_file):
            return {'success': False, 'error': f'Capture file not found: {cap_file}'}

        if not self._check_device():
            return {'success': False, 'error': 'CC2531 sniffer dongle not found.'}

        stdout, stderr, rc = self._run_kb('zbdsniff', '-f', cap_file, timeout=30)
        if rc != 0:
            return {'success': False,
                    'error': f'Key extraction failed: {stderr[:200] or stdout[:200]}',
                    'output': stdout[-500:]}
        return {'success': True, 'output': stdout, 'file': cap_file}

    # Device discovery (parse pcap for devices, with ZCL cluster identification)

    # ZCL cluster ID -> human-readable device type
    _ZCL_CLUSTER_TYPES = {
        '0x0000': {'name': 'Basic', 'desc': 'Basic device info (all devices)'},
        '0x0001': {'name': 'Power Config', 'desc': 'Battery-powered device'},
        '0x0002': {'name': 'Temperature', 'desc': 'Temperature sensor'},
        '0x0003': {'name': 'Identify', 'desc': 'Device identification'},
        '0x0004': {'name': 'Groups', 'desc': 'Group membership'},
        '0x0005': {'name': 'Scenes', 'desc': 'Scene memory'},
        '0x0006': {'name': 'On/Off', 'desc': 'Switch or light'},
        '0x0007': {'name': 'On/Off Config', 'desc': 'Switch/light config'},
        '0x0008': {'name': 'Level Control', 'desc': 'Dimmable light'},
        '0x0009': {'name': 'Alarms', 'desc': 'Alarm device'},
        '0x000A': {'name': 'Time', 'desc': 'Time server'},
        '0x000B': {'name': 'RSSI Location', 'desc': 'Location tracking'},
        '0x000C': {'name': 'Analog Input', 'desc': 'Analog sensor (e.g. pressure)'},
        '0x000D': {'name': 'Analog Output', 'desc': 'Analog output'},
        '0x000E': {'name': 'Analog Value', 'desc': 'Analog value sensor'},
        '0x000F': {'name': 'Binary Input', 'desc': 'Contact sensor / button'},
        '0x0010': {'name': 'Binary Output', 'desc': 'Relay output'},
        '0x0012': {'name': 'Multistate Input', 'desc': 'Multi-position sensor'},
        '0x0013': {'name': 'Multistate Output', 'desc': 'Multi-position output'},
        '0x0015': {'name': 'Commissioning', 'desc': 'Commissioning data'},
        '0x0019': {'name': 'OTA Upgrade', 'desc': 'Over-the-air firmware'},
        '0x0020': {'name': 'Poll Control', 'desc': 'Poll-controlled device'},
        '0x0101': {'name': 'Door Lock', 'desc': 'Smart door lock'},
        '0x0102': {'name': 'Window Covering', 'desc': 'Blinds/shades'},
        '0x0201': {'name': 'Thermostat', 'desc': 'HVAC thermostat'},
        '0x0202': {'name': 'Fan Control', 'desc': 'Fan controller'},
        '0x0300': {'name': 'Color Control', 'desc': 'Color light (RGB/CT)'},
        '0x0400': {'name': 'Illuminance', 'desc': 'Light level sensor'},
        '0x0402': {'name': 'Temperature', 'desc': 'Temperature sensor'},
        '0x0403': {'name': 'Pressure', 'desc': 'Pressure sensor'},
        '0x0404': {'name': 'Flow', 'desc': 'Flow rate sensor'},
        '0x0405': {'name': 'Humidity', 'desc': 'Humidity sensor'},
        '0x0406': {'name': 'Occupancy', 'desc': 'Presence/motion sensor'},
        '0x0500': {'name': 'IAS Zone', 'desc': 'Alarm/safety sensor'},
        '0x0502': {'name': 'IAS WD', 'desc': 'Alarm warning device'},
        '0x0702': {'name': 'Smart Energy', 'desc': 'Power metering device'},
    }

    @staticmethod
    def _get_network_key():
        """Read the Zigbee network key from Zigbee2MQTT config."""
        try:
            import yaml
            config_path = '/opt/zigbee2mqtt/data/configuration.yaml'
            if not os.path.exists(config_path):
                return None
            with open(config_path) as f:
                config = yaml.safe_load(f)
            key = config.get('advanced', {}).get('network_key', [])
            if key and isinstance(key, list) and len(key) == 16:
                return ''.join(format(b, '02x') for b in key)
        except Exception:
            pass
        return None

    def discover_devices(self, cap_file=None):
        """Parse a pcap file to discover Zigbee devices (MACs, PANs, roles)."""
        if cap_file is None:
            # Use the latest capture
            captures = []
            try:
                for f in sorted(os.listdir(self.captures_dir), reverse=True):
                    if f.endswith('.pcap'):
                        cap_file = os.path.join(self.captures_dir, f)
                        break
            except Exception:
                pass
            if cap_file is None:
                return {'success': False, 'error': 'No captures available'}

        if not os.path.exists(cap_file):
            return {'success': False, 'error': f'File not found: {cap_file}'}

        result = subprocess.run(
            ['sudo', '-n', 'tshark', '-r', cap_file,
             '-T', 'fields', '-e', 'wpan.src64', '-e', 'wpan.src16',
             '-e', 'wpan.dst_pan', '-e', 'frame.protocols',
             '-e', 'wpan.frame_type', '-E', 'header=n', '-E', 'separator=,'],
            capture_output=True, text=True, timeout=30,
        )
        stdout, stderr, rc = result.stdout, result.stderr, result.returncode
        if rc != 0:
            return {'success': False, 'error': f'tshark failed: {stderr[:200]}'}

        devices = {}
        packet_count = 0
        encrypted_count = 0
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            packet_count += 1
            parts = line.split(',')
            src64 = parts[0].strip() if len(parts) > 0 else ''
            src16 = parts[1].strip() if len(parts) > 1 else ''
            pan = parts[2].strip() if len(parts) > 2 else ''
            protocols = parts[3].strip() if len(parts) > 3 else ''
            frame_type = parts[4].strip() if len(parts) > 4 else ''

            # Use src64 as device identifier, fallback to src16
            dev_id = src64 if src64 else src16
            if not dev_id or dev_id == '0x':
                continue

            d = devices.setdefault(dev_id, {
                'mac_long': src64,
                'mac_short': src16,
                'pan': pan,
                'count': 0,
                'protocols': set(),
                'is_coordinator': src16 == '0x0000',
                'is_router': False,
                'is_encrypted': False,
            })
            d['count'] += 1
            if protocols:
                for proto in protocols.split(':'):
                    p = proto.strip()
                    if p:
                        d['protocols'].add(p)
                        # Mark as encrypted if we see Zigbee APS or NWK security
                        if 'zbee_aps' in p.lower():
                            d['is_encrypted'] = True
                            encrypted_count += 1
            # Also check: if zbee_nwk or zbee_aps is present at all, traffic is likely encrypted
            if 'zbee_nwk' in str(d['protocols']) or 'zbee_aps' in str(d['protocols']):
                d['is_encrypted'] = True
            # Beacons indicate coordinator/router
            if frame_type == '0x0000':
                d['is_router'] = True

        # Decrypt and identify device types via ZCL clusters (if key is available)
        zcl_clusters = {}  # mac -> set of cluster type names
        network_key = self._get_network_key()
        if network_key and cap_file and os.path.exists(cap_file):
            zcl_clusters = self._parse_zcl_clusters(cap_file, network_key)

        # Format for output
        device_list = []
        for dev_id, d in sorted(devices.items(), key=lambda x: -x[1]['count']):
            # tshark already formats MACs: EUI-64 as colon-sep, short as 0xHHHH
            mac_fmt = d['mac_long'] if d['mac_long'] else d['mac_short'] if d['mac_short'] else dev_id
            # Determine role
            if d['is_coordinator']:
                role = 'Coordinator'
                role_desc = 'Network coordinator (trust center). Manages key distribution and device joins.'
            elif d['is_router']:
                role = 'Router'
                role_desc = 'Mains-powered routing device. Relays messages for other devices.'
            elif d['count'] >= 5:
                role = 'Active End Device'
                role_desc = 'Battery-powered device that communicates frequently.'
            else:
                role = 'End Device'
                role_desc = 'Battery-powered device. Sleeps between transmissions to save power.'
            # Merge ZCL cluster info for this device
            dev_clusters = {}
            for mac_pattern in [mac_fmt.replace(':', '').lower(), mac_fmt.replace(':', '').upper()]:
                if mac_pattern in zcl_clusters:
                    dev_clusters = zcl_clusters[mac_pattern]
                    break

            # Skip the coordinator (0x0000) - it's the user's own SONOFF dongle
            is_own_coordinator = d['is_coordinator'] and d.get('mac_short') == '0x0000'

            device_list.append({
                'mac': mac_fmt,
                'pan': d['pan'],
                'packets': d['count'],
                'role': role,
                'role_desc': role_desc,
                'has_zigbee': 'zbee_nwk' in str(d['protocols']),
                'has_ipv6': '6lowpan' in str(d['protocols']) or 'ipv6' in str(d['protocols']),
                'is_encrypted': d['is_encrypted'],
                'is_own_coordinator': is_own_coordinator,
                'device_types': [self._ZCL_CLUSTER_TYPES.get(c, {'name': 'Cluster '+c, 'desc': 'Unknown cluster'}) for c in dev_clusters],
            })

        # Cross-reference with coordinator's paired devices for identification
        coordinator_devices = self._get_coordinator_devices()

        for dev in device_list:
            mac_clean = dev['mac'].replace(':', '').lower()
            # Match against IEEE addresses from coordinator
            for cd in coordinator_devices:
                cd_addr = cd.get('ieee_address', '').replace('0x', '').lower()
                if cd_addr and (cd_addr in mac_clean or mac_clean in cd_addr):
                    dev['friendly_name'] = cd.get('friendly_name', '')
                    dev['model'] = cd.get('model', '')
                    dev['vendor'] = cd.get('vendor', '')
                    dev['description'] = cd.get('description', '')
                    break

        return {'success': True, 'devices': device_list,
                'packets_analyzed': packet_count,
                'encrypted_packets': encrypted_count,
                'file': os.path.basename(cap_file)}

    def _parse_zcl_clusters(self, cap_file, network_key):
        """Decrypt pcap with network key and extract ZCL cluster IDs per device."""
        clusters = {}
        try:
            result = subprocess.run(
                ['sudo', '-n', 'tshark', '-r', cap_file,
                 '-o', f'zigbee_network_key:{network_key}',
                 '-Y', 'zbee_zcl',
                 '-T', 'fields', '-e', 'wpan.src64', '-e', 'zbee_zcl.cluster'],
                capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.strip().split('\n'):
                parts = line.split('\t')
                if len(parts) < 2 or not parts[1].strip():
                    continue
                mac = parts[0].strip().replace(':', '').lower()
                cluster_id = parts[1].strip()
                if mac and cluster_id:
                    clusters.setdefault(mac, set()).add(cluster_id)
        except Exception:
            pass
        return clusters

    @staticmethod
    def _get_coordinator_devices():
        """Get paired device list from Zigbee2MQTT for cross-referencing."""
        try:
            import urllib.request, json as _json
            req = urllib.request.Request('http://127.0.0.1:5000/api/zigbee/dashboard')
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read())
            return data.get('devices', [])
        except Exception:
            return []

    # List captures

    def list_captures(self):
        """List all saved Zigbee capture files."""
        captures = []
        try:
            for filename in sorted(os.listdir(self.captures_dir), reverse=True):
                if filename.endswith('.pcap'):
                    filepath = os.path.join(self.captures_dir, filename)
                    captures.append({
                        'name': filename,
                        'size_bytes': os.path.getsize(filepath),
                        'timestamp': datetime.fromtimestamp(
                            os.path.getmtime(filepath)).isoformat(),
                    })
        except Exception as e:
            return {'success': False, 'error': str(e)}
        return {'success': True, 'captures': captures}
