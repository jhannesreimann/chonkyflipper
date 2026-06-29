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
        """Verify the CC2531 dongle is present (fast USB check)."""
        try:
            import usb.core
            dev = usb.core.find(idVendor=0x0451, idProduct=0x16AE)
            return dev is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Passive capture (zbdump)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # PAN discovery (zbstumbler)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Replay attack (zbreplay)
    # ------------------------------------------------------------------

    def replay_packets(self, cap_file, count=1, channel=None):
        """Replay captured packets for command injection.
        Note: CC2531 sniffer firmware does not support packet injection.
        Requires Atmel RZUSBSTICK or similar transmit-capable hardware."""
        return {'success': False,
                'error': 'Packet injection not supported on CC2531 sniffer. '
                         'Replay requires a TX-capable dongle (e.g. RZUSBSTICK).'}

        # zbreplay requires a channel
        if not channel:
            channel = 11  # default Zigbee channel
        args = ['-r', cap_file, '-c', str(channel), '-n', str(count)]

        stdout, stderr, rc = self._run_kb('zbreplay', *args, timeout=30)
        if rc != 0:
            return {'success': False,
                    'error': f'Replay failed: {stderr[:200] or stdout[:200]}'}
        return {'success': True, 'file': cap_file, 'repeat': count,
                'channel': channel, 'output': stdout[:500]}

    # ------------------------------------------------------------------
    # Association flood (zbassocflood)
    # ------------------------------------------------------------------

    def assoc_flood(self, channel, pan_id, duration=5):
        """Flood a PAN with association requests (DoS).
        Note: CC2531 sniffer firmware does not support packet injection."""
        return {'success': False,
                'error': 'Packet injection not supported on CC2531 sniffer. '
                         'Association flood requires a TX-capable dongle.'}

        # zbassocflood runs until killed; use duration to limit
        stdout, stderr, rc = self._run_kb(
            'zbassocflood', '-c', str(channel), '-p', pan_id,
            '-s', '0.05', timeout=duration + 5,
        )
        if rc != 0:
            return {'success': False,
                    'error': f'Flood failed: {stderr[:200] or stdout[:200]}'}
        return {'success': True, 'channel': channel, 'pan_id': pan_id,
                'duration': duration, 'output': stdout[:500]}

    # ------------------------------------------------------------------
    # Key extraction (zbdsniff) - issue #62
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Device discovery (parse pcap for devices)
    # ------------------------------------------------------------------

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
            # tshark already formats them: EUI-64 as colon-sep hex, short as 0xHHHH
            dev_id = src64 if src64 else src16
            if not dev_id or dev_id == '0x':
                continue

            d = devices.setdefault(dev_id, {
                'mac_long': src64,
                'mac_short': src16,
                'pan': pan,
                'count': 0,
                'protocols': set(),
                'is_coordinator': False,
            })
            d['count'] += 1
            if protocols:
                for proto in protocols.split(':'):
                    if proto.strip():
                        d['protocols'].add(proto.strip())
            # Beacons indicate coordinator/router
            if frame_type == '0x0000':
                d['is_coordinator'] = True

        # Format for output
        device_list = []
        for dev_id, d in sorted(devices.items(), key=lambda x: -x[1]['count']):
            # tshark already formats MACs: EUI-64 as colon-sep, short as 0xHHHH
            mac_fmt = d['mac_long'] if d['mac_long'] else d['mac_short'] if d['mac_short'] else dev_id
            role = 'Coordinator/Router' if d['is_coordinator'] else 'End Device' if d['count'] < 5 else 'Active Device'
            device_list.append({
                'mac': mac_fmt,
                'pan': d['pan'],
                'packets': d['count'],
                'role': role,
                'has_zigbee': 'zbee_nwk' in str(d['protocols']),
                'has_ipv6': '6lowpan' in str(d['protocols']) or 'ipv6' in str(d['protocols']),
            })

        return {'success': True, 'devices': device_list,
                'packets_analyzed': packet_count,
                'file': os.path.basename(cap_file)}

    # ------------------------------------------------------------------
    # List captures
    # ------------------------------------------------------------------

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
