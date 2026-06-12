#!/usr/bin/env python3
"""
IR Module - Controls KY-005 transmitter (GPIO 17) and KY-022 receiver (GPIO 27)
Uses kernel gpio-ir-tx / gpio-ir LIRC drivers via /dev/lirc0 and /dev/lirc1
"""

import subprocess
import os
import json
import time
import struct
import re
from datetime import datetime


class IRModule:
    """IR signal recording and transmission via kernel LIRC devices"""

    def __init__(self, tx_pin=17, rx_pin=27):
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.signals_dir = '/opt/chonkyflipper/signals/ir'
        self.payloads_dir = '/opt/chonkyflipper/payloads'
        os.makedirs(self.signals_dir, exist_ok=True)
        os.makedirs(self.payloads_dir, exist_ok=True)

        # Detect which lirc device is TX and which is RX
        self.tx_dev, self.rx_dev = self._detect_devices()

    def _detect_devices(self):
        """Find TX and RX lirc devices by checking sysfs names"""
        tx_dev = '/dev/lirc0'
        rx_dev = '/dev/lirc1'
        for i in range(4):
            dev = f'/dev/lirc{i}'
            if not os.path.exists(dev):
                continue
            # Check the rc device name
            rc_path = f'/sys/class/rc/rc{i}'
            try:
                with open(f'{rc_path}/name') as f:
                    name = f.read().strip()
                if 'transmit' in name.lower():
                    tx_dev = dev
                elif 'recv' in name.lower() or 'receiver' in name.lower():
                    rx_dev = dev
            except Exception:
                continue
        return tx_dev, rx_dev

    def _run(self, cmd, timeout=10):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return '', 'Command timed out', 1

    def record_signal(self, duration=5, name=None):
        """
        Record IR signal from the receiver.
        Uses blocking LIRC reads to capture all pulses reliably.
        """
        if name is None:
            name = f'ir_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

        filepath = os.path.join(self.signals_dir, f'{name}.json')

        if not os.path.exists(self.rx_dev):
            return {
                'success': False,
                'error': f'IR receiver {self.rx_dev} not found.'
            }

        pulses = []
        spaces = []
        try:
            fd = os.open(self.rx_dev, os.O_RDONLY | os.O_NONBLOCK)
            start = time.time()
            while (time.time() - start) < duration:
                try:
                    data = os.read(fd, 4)
                    if data and len(data) == 4:
                        val = struct.unpack('I', data)[0]
                        length = val & 0x00FFFFFF
                        p_type = (val >> 24) & 0xFF

                        # Filter LIRC timeout markers (0x00FFFFFF = 16777215)
                        if length >= 0x00FFFF00:
                            # Timeout/overflow — skip, end of signal
                            continue

                        if p_type == 0:  # space
                            # Also filter unreasonably long spaces (>1 second)
                            if length < 1000000:
                                spaces.append(length)
                        elif p_type == 1:  # pulse
                            # Filter unreasonably long pulses
                            if length < 100000:
                                pulses.append(length)
                except BlockingIOError:
                    time.sleep(0.005)
                except OSError:
                    break
            os.close(fd)

        except Exception as e:
            return {
                'success': False,
                'error': f'Recording error: {str(e)}'
            }

        if not pulses:
            return {
                'success': False,
                'error': 'No IR signal detected. Point a remote at the receiver and press a button.'
            }

        # Build pulse-space pairs
        pairs = []
        for i in range(min(len(pulses), len(spaces))):
            pairs.append({
                'type': 'pulse',
                'duration_us': pulses[i]
            })
            pairs.append({
                'type': 'space',
                'duration_us': spaces[i]
            })
        if len(pulses) > len(spaces):
            pairs.append({
                'type': 'pulse',
                'duration_us': pulses[-1]
            })

        protocol = self.detect_protocol(pulses, spaces)

        signal_data = {
            'name': name,
            'timestamp': datetime.now().isoformat(),
            'duration_recorded': duration,
            'protocol': protocol['name'],
            'protocol_confidence': protocol['confidence'],
            'address': protocol.get('address'),
            'command': protocol.get('command'),
            'pulse_count': len(pulses),
            'pulses': pulses,
            'spaces': spaces,
            'pairs': pairs
        }

        with open(filepath, 'w') as f:
            json.dump(signal_data, f, indent=2)

        return {
            'success': True,
            'name': name,
            'filepath': filepath,
            'protocol': protocol['name'],
            'pulses_captured': len(pulses),
            'preview': f'{protocol["name"]} signal, {len(pulses)} pulses'
        }

    def transmit_signal(self, signal_id):
        """
        Transmit a recorded IR signal via ir-ctl.
        """
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if not os.path.exists(filepath):
            return {
                'success': False,
                'error': f'Signal {signal_id} not found'
            }

        if not os.path.exists(self.tx_dev):
            return {
                'success': False,
                'error': f'IR transmitter {self.tx_dev} not found.'
            }

        with open(filepath, 'r') as f:
            signal_data = json.load(f)

        pairs = signal_data.get('pairs', [])
        if not pairs:
            return {
                'success': False,
                'error': 'No pulse data in signal file'
            }

        return self._transmit_pairs(pairs, signal_id)

    def transmit_raw(self, pulses, spaces=None):
        """
        Transmit raw pulse/space timing data.
        pulses: list of pulse widths in microseconds
        spaces: list of space widths (defaults to alternating even pattern)
        """
        if not os.path.exists(self.tx_dev):
            return {
                'success': False,
                'error': f'IR transmitter {self.tx_dev} not found.'
            }

        pairs = []
        for i, pulse in enumerate(pulses):
            pairs.append({'type': 'pulse', 'duration_us': pulse})
            if spaces and i < len(spaces):
                pairs.append({'type': 'space', 'duration_us': spaces[i]})

        return self._transmit_pairs(pairs)

    def _transmit_pairs(self, pairs, label='raw'):
        """Write pulse-space file and transmit via ir-ctl"""
        # Build ir-ctl pulse file, filtering any unreasonable values
        lines = []
        for p in pairs:
            dur = p['duration_us']
            # Skip timeout markers and unreasonably long values
            if dur >= 1000000:  # >1 second is a LIRC timeout, not a real signal
                continue
            if p['type'] == 'pulse' and dur > 100000:
                continue
            t = p['type']
            lines.append(f'{t} {dur}')

        tmpfile = f'/tmp/ir-tx-{os.getpid()}.txt'
        with open(tmpfile, 'w') as f:
            f.write('\n'.join(lines))

        stdout, stderr, rc = self._run(
            ['ir-ctl', '-d', self.tx_dev, f'--send={tmpfile}'],
            timeout=5
        )
        os.remove(tmpfile)

        if rc == 0:
            return {
                'success': True,
                'signal': label,
                'pairs_sent': len(pairs)
            }
        else:
            return {
                'success': False,
                'error': f'ir-ctl failed: {stderr}'
            }

    def list_signals(self):
        """List all recorded IR signals"""
        signals = []
        try:
            for filename in sorted(os.listdir(self.signals_dir)):
                if not filename.endswith('.json'):
                    continue
                filepath = os.path.join(self.signals_dir, filename)
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    signals.append({
                        'name': data.get('name', filename.replace('.json', '')),
                        'timestamp': data.get('timestamp'),
                        'protocol': data.get('protocol', 'unknown'),
                        'pulses': data.get('pulse_count', len(data.get('pulses', [])))
                    })
        except Exception as e:
            return {'signals': [], 'error': str(e)}

        return {'signals': sorted(signals, key=lambda s: s.get('timestamp', ''), reverse=True)}

    def delete_signal(self, signal_id):
        """Delete a recorded signal"""
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if os.path.exists(filepath):
            os.remove(filepath)
            return {'success': True, 'deleted': signal_id}
        return {'success': False, 'error': 'Signal not found'}

    # -------------------------------------------------
    # Protocol detection (issue #24)
    # -------------------------------------------------

    def detect_protocol(self, pulses, spaces=None):
        """
        Detect IR protocol from pulse/space timing data.
        Returns dict with protocol name, confidence, address, command.
        """
        if not pulses or len(pulses) < 4:
            return {'name': 'unknown', 'confidence': 0}

        # NEC protocol: 9000us header pulse, 4500us header space
        # Logical 0: 560us pulse + 560us space
        # Logical 1: 560us pulse + 1690us space
        # 32 bits: 8-bit address + 8-bit inverse + 8-bit command + 8-bit inverse
        if 8500 < pulses[0] < 9500 and spaces and 4000 < spaces[0] < 5000:
            result = self._decode_nec(pulses, spaces)
            if result['confidence'] > 0.5:
                return result

        # Sony SIRC: 2400us header pulse, 600us header space
        # Logical 0: 600us pulse + 600us space, Logical 1: 600us pulse + 1200us space
        if 2000 < pulses[0] < 2800 and spaces and 500 < spaces[0] < 700:
            result = self._decode_sony(pulses, spaces)
            if result['confidence'] > 0.5:
                return result

        # RC5: ~889us per half-bit, Manchester encoding, 13-14 bits
        if 800 < pulses[0] < 1000:
            return {'name': 'RC5 (likely)', 'confidence': 0.5}

        # Generic: just classify based on header
        if pulses[0] > 8000:
            return {'name': 'NEC-like', 'confidence': 0.3}
        elif pulses[0] > 2000:
            return {'name': 'Sony-like', 'confidence': 0.3}

        return {'name': 'raw', 'confidence': 0.1}

    def _decode_nec(self, pulses, spaces):
        """Decode NEC protocol from pulse/space timings"""
        result = {'name': 'NEC', 'confidence': 0}

        if len(pulses) < 34 or len(spaces) < 33:
            return {'name': 'NEC (incomplete)', 'confidence': 0.3}

        # Skip header (index 0 of both)
        bits = []
        for i in range(1, min(34, min(len(pulses), len(spaces) + 1))):
            p = pulses[i] if i < len(pulses) else 0
            s = spaces[i] if i < len(spaces) else 0

            if 400 < p < 700 and 400 < s < 700:
                bits.append(0)
            elif 400 < p < 700 and 1400 < s < 2000:
                bits.append(1)
            else:
                bits.append(None)

        valid = sum(1 for b in bits if b is not None)
        if valid < 16:
            return {'name': 'NEC (noisy)', 'confidence': 0.3}

        confidence = valid / len(bits) if bits else 0

        # Extract address and command from first 32 bits
        if len(bits) >= 32:
            addr = 0
            cmd = 0
            for i in range(8):
                if bits[i] is not None:
                    addr |= bits[i] << i
            for i in range(16, 24):
                if bits[i] is not None:
                    cmd |= bits[i] << (i - 16)
            result['address'] = addr
            result['command'] = cmd
            result['address_hex'] = f'0x{addr:02X}'
            result['command_hex'] = f'0x{cmd:02X}'

        result['confidence'] = confidence
        return result

    def _decode_sony(self, pulses, spaces):
        """Decode Sony SIRC protocol"""
        result = {'name': 'Sony SIRC', 'confidence': 0}

        bits = []
        for i in range(1, min(len(pulses), len(spaces) + 1)):
            p = pulses[i] if i < len(pulses) else 0
            s = spaces[i] if i < len(spaces) else 0

            if 400 < p < 800 and 400 < s < 800:
                bits.append(0)
            elif 400 < p < 800 and 1000 < s < 1400:
                bits.append(1)
            else:
                bits.append(None)

        valid = sum(1 for b in bits if b is not None)
        if valid < 8:
            return {'name': 'Sony (noisy)', 'confidence': 0.3}

        confidence = valid / len(bits) if bits else 0
        result['confidence'] = confidence

        if len(bits) >= 12:
            cmd = 0
            addr = 0
            for i in range(7):
                if bits[i] is not None:
                    cmd |= bits[i] << i
            for i in range(7, min(12, len(bits))):
                if bits[i] is not None:
                    addr |= bits[i] << (i - 7)
            result['command'] = cmd
            result['address'] = addr

        return result

    # -----------------------------------------------------------
    # NEC encoder / Payload library
    # -----------------------------------------------------------

    @staticmethod
    def _encode_nec(address, command, header_pulse=9000, header_space=4500,
                    unit_pulse=560, unit_space_0=560, unit_space_1=1690,
                    samsung32=False):
        """
        Build NEC protocol pulse and space arrays from address and command.
        Returns (pulses, spaces) lists in microseconds.
        Standard NEC: 9000us header, 32 bits (addr + ~addr + cmd + ~cmd).
        Samsung variant: 4500us header, 32 bits (addr + addr + cmd + ~cmd).
        """
        pulses = [header_pulse]
        spaces = [header_space]

        # Build 32-bit payload
        if samsung32:
            # Samsung32: address repeated, command inverted
            data = [
                address & 0xFF,
                address & 0xFF,        # repeated, not inverted
                command & 0xFF,
                (~command) & 0xFF
            ]
        else:
            # Standard NEC: both inverted
            data = [
                address & 0xFF,
                (~address) & 0xFF,
                command & 0xFF,
                (~command) & 0xFF
            ]

        for byte in data:
            for bit_pos in range(8):
                pulses.append(unit_pulse)
                if byte & (1 << bit_pos):
                    spaces.append(unit_space_1)
                else:
                    spaces.append(unit_space_0)

        pulses.append(unit_pulse)  # trailing pulse
        return pulses, spaces

    def _load_payload_files(self):
        """Load IR payload definitions from JSON files."""
        payloads = {}
        payload_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'payloads', 'ir'
        )
        if not os.path.isdir(payload_dir):
            return payloads

        for filename in sorted(os.listdir(payload_dir)):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(payload_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)

                brand = data.get('brand', 'Unknown')
                device = data.get('device', '')
                for btn_id, btn in data.get('buttons', {}).items():
                    proto = data.get('protocol', 'NEC')
                    if proto == 'NEC':
                        hp = data.get('header_pulse', 9000)
                        hs = data.get('header_space', 4500)
                        s32 = data.get('samsung32', False)
                        p, s = self._encode_nec(
                            btn['address'], btn['command'],
                            header_pulse=hp, header_space=hs,
                            samsung32=s32
                        )
                        payloads[f'{brand.lower()}_{btn_id}'] = {
                            'name': f'{brand} {btn["label"]}',
                            'brand': brand,
                            'device': device,
                            'protocol': proto,
                            'pulses': p,
                            'spaces': s
                        }
            except Exception:
                continue

        return payloads

    def list_payloads(self):
        """List all loaded IR payloads grouped by brand."""
        payloads = self._load_payload_files()
        result = []
        for pid, p in payloads.items():
            result.append({
                'id': pid,
                'name': p['name'],
                'brand': p.get('brand', ''),
                'protocol': p['protocol']
            })
        return {'payloads': sorted(result, key=lambda x: x['name'])}

    def execute_payload(self, payload_id):
        """Load and transmit a payload by ID."""
        payloads = self._load_payload_files()
        if payload_id not in payloads:
            return {'success': False, 'error': f'Payload {payload_id} not found'}

        p = payloads[payload_id]
        pairs = []
        for i, pulse in enumerate(p['pulses']):
            pairs.append({'type': 'pulse', 'duration_us': pulse})
            if i < len(p['spaces']):
                pairs.append({'type': 'space', 'duration_us': p['spaces'][i]})

        return self._transmit_pairs(pairs, payload_id)

    def brute_force_power(self, brands=None):
        """
        Send power toggle codes for multiple brands to find which one works.
        """
        payloads = self._load_payload_files()
        power_ids = [pid for pid in payloads if pid.endswith('power_toggle')]

        if brands:
            power_ids = [pid for pid in power_ids
                         if any(pid.startswith(b.lower()) for b in brands)]

        results = []
        for pid in power_ids[:10]:  # limit to 10 codes
            p = payloads[pid]
            result = self.execute_payload(pid)
            result['label'] = p['name']
            results.append(result)
            time.sleep(0.5)

        return {
            'success': True,
            'sent': len(results),
            'results': results
        }
