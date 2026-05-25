#!/usr/bin/env python3
"""
IR Module - Controls KY-005 (TX) and KY-022 (RX)
Infrared signal recording and replay using modern Linux kernel LIRC device interfaces
"""

import subprocess
import os
import json
import time
import struct
from datetime import datetime

class IRModule:
    """IR signal recording and transmission via kernel LIRC, GPIO 17 (TX) / GPIO 27 (RX)"""
    
    def __init__(self, tx_pin=17, rx_pin=27):
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.signals_dir = '/opt/chonkyflipper/signals/ir'
        os.makedirs(self.signals_dir, exist_ok=True)
        
        self.rx_dev = '/dev/lirc0'
        self.tx_dev = '/dev/lirc1'
        
    def _check_devices(self):
        """Check if kernel LIRC devices are active"""
        rx_ok = os.path.exists(self.rx_dev)
        tx_ok = os.path.exists(self.tx_dev)
        return rx_ok, tx_ok
    
    def record_signal(self, duration=5, name=None):
        """
        Record IR signal from /dev/lirc0 (KY-022 receiver)
        Returns raw timing data (microseconds of pulses and spaces)
        """
        if name is None:
            name = f'ir_signal_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        
        filepath = os.path.join(self.signals_dir, f'{name}.json')
        rx_ok, _ = self._check_devices()
        
        if not rx_ok:
            return {
                'success': False,
                'error': f'IR Receiver device {self.rx_dev} not found.',
                'hint': 'Please ensure dtoverlay=gpio-ir,gpiopin=27 is added to /boot/firmware/config.txt'
            }
            
        pulses = []
        try:
            print(f"Opening {self.rx_dev} for recording...")
            # Open LIRC device in non-blocking or timed read mode
            fd = os.open(self.rx_dev, os.O_RDONLY | os.O_NONBLOCK)
            
            start_time = time.time()
            print("Listening for IR pulses...")
            
            while (time.time() - start_time) < duration:
                try:
                    # LIRC packets are 4-byte packages representing pulse/space timing in microseconds
                    data = os.read(fd, 4)
                    if data and len(data) == 4:
                        val = struct.unpack('I', data)[0]
                        # In LIRC MODE2:
                        # Bits 0-23: Pulse/Space length in microseconds
                        # Bits 24-31: Type (0x01 for pulse, 0x00 for space, 0x02 for timeout)
                        length = val & 0x00FFFFFF
                        p_type = (val & 0xFF000000) >> 24
                        
                        if p_type == 0 or p_type == 1:
                            pulses.append({
                                'type': 'pulse' if p_type == 1 else 'space',
                                'duration_us': length
                            })
                except BlockingIOError:
                    # No data available right now, sleep briefly
                    time.sleep(0.01)
                    
            os.close(fd)
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Error recording IR: {str(e)}'
            }
            
        signal_data = {
            'name': name,
            'timestamp': datetime.now().isoformat(),
            'duration': duration,
            'tx_pin': self.tx_pin,
            'rx_pin': self.rx_pin,
            'protocol': self.detect_protocol([p['duration_us'] for p in pulses]) if pulses else 'unknown',
            'pulses': pulses
        }
        
        with open(filepath, 'w') as f:
            json.dump(signal_data, f, indent=2)
        
        return {
            'success': True,
            'name': name,
            'filepath': filepath,
            'duration': duration,
            'pulses_captured': len(pulses),
            'status': f'Captured {len(pulses)} raw IR pulses'
        }
    
    def transmit_signal(self, signal_id):
        """
        Transmit recorded IR signal via /dev/lirc1 (KY-005)
        signal_id: Name of the saved signal file
        """
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        
        if not os.path.exists(filepath):
            return {
                'success': False,
                'error': f'Signal {signal_id} not found'
            }
        
        _, tx_ok = self._check_devices()
        if not tx_ok:
            return {
                'success': False,
                'error': f'IR Transmitter device {self.tx_dev} not found.',
                'hint': 'Please ensure dtoverlay=gpio-ir-tx,gpiopin=17 is added to /boot/firmware/config.txt'
            }
            
        with open(filepath, 'r') as f:
            signal_data = json.load(f)
            
        pulses = signal_data.get('pulses', [])
        if not pulses:
            return {
                'success': False,
                'error': 'No pulse data found in signal file'
            }
            
        # Convert pulse dictionary back to array of microsecond timings for LIRC write
        # LIRC write requires writing an array of 32-bit integers representing microsecond durations,
        # alternating pulse/space, starting with a pulse.
        raw_timings = [p['duration_us'] for p in pulses]
        if len(raw_timings) % 2 == 0 and len(raw_timings) > 0:
            raw_timings = raw_timings[:-1]  # Remove trailing space to make length odd
        
        try:
            # Open LIRC TX device and write raw timings
            fd = os.open(self.tx_dev, os.O_WRONLY)
            # pack timings into 32-bit unsigned integers
            data_to_write = struct.pack(f'{len(raw_timings)}I', *raw_timings)
            os.write(fd, data_to_write)
            os.close(fd)
            
            return {
                'success': True,
                'signal': signal_id,
                'tx_pin': self.tx_pin,
                'pulses_sent': len(raw_timings),
                'status': 'IR replay transmitted successfully via LIRC'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Error transmitting IR: {str(e)}'
            }
            
    def transmit_raw(self, pulses):
        """
        Transmit raw pulse timing data
        pulses: List of pulse widths in microseconds (on/off alternating)
        """
        _, tx_ok = self._check_devices()
        if not tx_ok:
            return {
                'success': False,
                'error': f'IR Transmitter device {self.tx_dev} not found.'
            }
            
        raw_pulses = list(pulses)
        if len(raw_pulses) % 2 == 0 and len(raw_pulses) > 0:
            raw_pulses = raw_pulses[:-1]  # Remove trailing space to make length odd
            
        try:
            fd = os.open(self.tx_dev, os.O_WRONLY)
            data_to_write = struct.pack(f'{len(raw_pulses)}I', *raw_pulses)
            os.write(fd, data_to_write)
            os.close(fd)
            return {'success': True, 'pulses_sent': len(raw_pulses)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def list_signals(self):
        """List all recorded IR signals"""
        signals = []
        try:
            for filename in os.listdir(self.signals_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(self.signals_dir, filename)
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                        signals.append({
                            'name': data.get('name', filename),
                            'timestamp': data.get('timestamp'),
                            'protocol': data.get('protocol', 'unknown'),
                            'pulses': len(data.get('pulses', []))
                        })
        except Exception as e:
            return {'error': str(e)}
        
        return {'signals': signals}
    
    def delete_signal(self, signal_id):
        """Delete a recorded signal"""
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if os.path.exists(filepath):
            os.remove(filepath)
            return {'success': True, 'deleted': signal_id}
        return {'success': False, 'error': 'Signal not found'}
    
    def detect_protocol(self, pulses):
        """
        Attempt to detect IR protocol from pulse data
        """
        if not pulses or len(pulses) < 10:
            return 'unknown'
        
        header = pulses[0] if pulses else 0
        if 8500 < header < 9500:
            return 'NEC'
        elif 2200 < header < 2600:
            return 'Sony'
        elif 3000 < header < 5000:
            return 'RC5'
        
        return 'raw'
