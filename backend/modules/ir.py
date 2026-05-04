#!/usr/bin/env python3
"""
IR Module - Controls KY-005 (TX) and KY-022 (RX)
Infrared signal recording and replay
"""

import subprocess
import os
import json
import time
from datetime import datetime

class IRModule:
    """IR signal recording and transmission, GPIO 17 (TX) / GPIO 27 (RX)"""
    
    def __init__(self, tx_pin=17, rx_pin=27):
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.signals_dir = '/opt/chonkyflipper/signals/ir'
        os.makedirs(self.signals_dir, exist_ok=True)
        
        # Ensure pigpio daemon is running
        self._ensure_pigpio()
    
    def _ensure_pigpio(self):
        """Ensure pigpio daemon is running for precise GPIO timing"""
        try:
            subprocess.run(
                ['pgrep', '-x', 'pigpiod'],
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError:
            # Not running, try to start
            try:
                subprocess.run(['sudo', 'pigpiod'], check=True)
            except:
                pass
    
    def record_signal(self, duration=5, name=None):
        """
        Record IR signal from KY-022 receiver
        Returns raw timing data
        """
        if name is None:
            name = f'ir_signal_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        
        filepath = os.path.join(self.signals_dir, f'{name}.json')
        
        # Use irrecord (LIRC) or custom pigpio implementation
        # For now, provide placeholder that will be implemented with pigpio
        
        signal_data = {
            'name': name,
            'timestamp': datetime.now().isoformat(),
            'duration': duration,
            'tx_pin': self.tx_pin,
            'rx_pin': self.rx_pin,
            'protocol': 'raw',
            'pulses': [],  # Will be populated by pigpio ISR
            'note': 'Recording requires pigpio or LIRC setup'
        }
        
        # TODO: Implement actual recording with pigpio
        # This requires setting up a callback on the RX pin
        # and measuring pulse widths with microsecond precision
        
        # Save to file
        with open(filepath, 'w') as f:
            json.dump(signal_data, f, indent=2)
        
        return {
            'success': True,
            'name': name,
            'filepath': filepath,
            'duration': duration,
            'status': 'placeholder - implement pigpio recording'
        }
    
    def transmit_signal(self, signal_id):
        """
        Transmit recorded IR signal via KY-005
        signal_id: Name of the saved signal file
        """
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        
        if not os.path.exists(filepath):
            return {
                'success': False,
                'error': f'Signal {signal_id} not found'
            }
        
        # Load signal data
        with open(filepath, 'r') as f:
            signal_data = json.load(f)
        
        # TODO: Implement actual transmission with pigpio
        # This requires generating carrier frequency (typically 38kHz)
        # and modulating it with the pulse data
        
        return {
            'success': True,
            'signal': signal_id,
            'tx_pin': self.tx_pin,
            'protocol': signal_data.get('protocol', 'unknown'),
            'status': 'placeholder - implement pigpio transmission'
        }
    
    def transmit_raw(self, pulses):
        """
        Transmit raw pulse timing data
        pulses: List of pulse widths in microseconds (on/off alternating)
        """
        # Implementation with pigpio waves
        # This is the core function for replay attacks
        
        return {
            'success': False,
            'message': 'Raw transmission requires pigpio implementation'
        }
    
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
                            'protocol': data.get('protocol', 'unknown')
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
        Common: NEC, Sony, RC5, RC6, Panasonic, etc.
        """
        if not pulses or len(pulses) < 10:
            return 'unknown'
        
        # NEC protocol: 9000us header, 562.5us pulse, 562.5us/1687.5us data
        # Sony protocol: 2400us header
        # RC5/RC6: Manhester encoding, specific timings
        
        header = pulses[0] if pulses else 0
        
        if 8500 < header < 9500:
            return 'NEC'
        elif 2200 < header < 2600:
            return 'Sony'
        elif 3000 < header < 5000:
            return 'RC5'
        
        return 'raw'
    
    def _transmit_with_pigpio(self, pulses, frequency=38000):
        """
        Internal: Transmit using pigpio waves
        Generates carrier wave at specified frequency
        """
        # Implementation outline:
        # 1. Create wave chain with carrier modulation
        # 2. Send wave via pigpio
        # 3. Clean up
        
        # This requires the pigpio Python library
        pass
