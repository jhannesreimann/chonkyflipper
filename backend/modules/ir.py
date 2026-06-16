#!/usr/bin/env python3
"""
IR Module - Controls KY-005 transmitter (GPIO 17) and KY-022 receiver (GPIO 27)
Uses kernel gpio-ir-tx / gpio-ir LIRC drivers via /dev/lirc0 and /dev/lirc1
"""

import os
import json
import time
import struct
import tempfile
from datetime import datetime
from config import SIGNALS_IR


class IRModule:
    """IR signal recording and transmission via kernel LIRC devices"""

    def __init__(self, tx_pin=17, rx_pin=27):
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.signals_dir = SIGNALS_IR
        os.makedirs(self.signals_dir, exist_ok=True)
        self.tx_dev, self.rx_dev = self._detect_devices()

    def _detect_devices(self):
        """Find TX and RX lirc devices by checking sysfs names"""
        tx_dev = '/dev/lirc0'
        rx_dev = '/dev/lirc1'
        for i in range(4):
            dev = f'/dev/lirc{i}'
            if not os.path.exists(dev):
                continue
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
        import subprocess
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return '', 'Command timed out', 1

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_signal(self, duration=5, name=None):
        if name is None:
            name = f'ir_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

        filepath = os.path.join(self.signals_dir, f'{name}.json')

        if not os.path.exists(self.rx_dev):
            return {'success': False, 'error': f'IR receiver {self.rx_dev} not found.'}

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
                        if length >= 0x00FFFF00:
                            continue
                        if p_type == 0:
                            if length < 1000000:
                                spaces.append(length)
                        elif p_type == 1:
                            if length < 100000:
                                pulses.append(length)
                except BlockingIOError:
                    time.sleep(0.005)
                except OSError:
                    break
            os.close(fd)
        except Exception as e:
            return {'success': False, 'error': f'Recording error: {str(e)}'}

        if not pulses:
            return {'success': False, 'error': 'No IR signal detected. Point a remote at the receiver and press a button.'}

        pairs = []
        for i in range(min(len(pulses), len(spaces))):
            pairs.append({'type': 'pulse', 'duration_us': pulses[i]})
            pairs.append({'type': 'space', 'duration_us': spaces[i]})
        if len(pulses) > len(spaces):
            pairs.append({'type': 'pulse', 'duration_us': pulses[-1]})

        protocol = self.detect_protocol(pulses, spaces)

        signal_data = {
            'name': name, 'timestamp': datetime.now().isoformat(),
            'duration_recorded': duration,
            'protocol': protocol['name'], 'protocol_confidence': protocol['confidence'],
            'address': protocol.get('address'), 'command': protocol.get('command'),
            'pulse_count': len(pulses), 'pulses': pulses, 'spaces': spaces, 'pairs': pairs,
        }

        with open(filepath, 'w') as f:
            json.dump(signal_data, f, indent=2)

        return {
            'success': True, 'name': name, 'filepath': filepath,
            'protocol': protocol['name'], 'pulses_captured': len(pulses),
            'preview': f'{protocol["name"]} signal, {len(pulses)} pulses',
        }

    # ------------------------------------------------------------------
    # Transmission
    # ------------------------------------------------------------------

    def transmit_signal(self, signal_id):
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if not os.path.exists(filepath):
            return {'success': False, 'error': f'Signal {signal_id} not found'}

        if not os.path.exists(self.tx_dev):
            return {'success': False, 'error': f'IR transmitter {self.tx_dev} not found.'}

        with open(filepath, 'r') as f:
            signal_data = json.load(f)

        pairs = signal_data.get('pairs', [])
        if not pairs:
            return {'success': False, 'error': 'No pulse data in signal file'}

        return self._transmit_pairs(pairs, signal_id)

    def transmit_raw(self, pulses, spaces=None):
        if not os.path.exists(self.tx_dev):
            return {'success': False, 'error': f'IR transmitter {self.tx_dev} not found.'}

        pairs = []
        for i, pulse in enumerate(pulses):
            pairs.append({'type': 'pulse', 'duration_us': pulse})
            if spaces and i < len(spaces):
                pairs.append({'type': 'space', 'duration_us': spaces[i]})

        return self._transmit_pairs(pairs)

    def _transmit_pairs(self, pairs, label='raw'):
        """Write pulse-space file and transmit via ir-ctl. Uses tempfile to avoid PID races."""
        lines = []
        for p in pairs:
            dur = p['duration_us']
            if dur >= 1000000:
                continue
            if p['type'] == 'pulse' and dur > 100000:
                continue
            lines.append(f"{p['type']} {dur}")

        fd, tmpfile = tempfile.mkstemp(prefix='ir-tx-', suffix='.txt')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write('\n'.join(lines))

            stdout, stderr, rc = self._run(
                ['ir-ctl', '-d', self.tx_dev, f'--send={tmpfile}'], timeout=5,
            )

            if rc == 0:
                return {'success': True, 'signal': label, 'pairs_sent': len(pairs)}
            return {'success': False, 'error': f'ir-ctl failed: {stderr}'}
        finally:
            os.remove(tmpfile)

    # ------------------------------------------------------------------
    # Signal management
    # ------------------------------------------------------------------

    def list_signals(self):
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
                        'pulses': data.get('pulse_count', len(data.get('pulses', []))),
                    })
        except Exception as e:
            return {'signals': [], 'error': str(e)}

        return {'signals': sorted(signals, key=lambda s: s.get('timestamp', ''), reverse=True)}

    def delete_signal(self, signal_id):
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if os.path.exists(filepath):
            os.remove(filepath)
            return {'success': True, 'deleted': signal_id}
        return {'success': False, 'error': 'Signal not found'}

    # ------------------------------------------------------------------
    # Protocol detection
    # ------------------------------------------------------------------

    def detect_protocol(self, pulses, spaces=None):
        from modules.ir_protocols import detect_protocol as _detect
        return _detect(pulses, spaces)
