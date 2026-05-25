#!/usr/bin/env python3
"""
CC1101 Module - Sub-1 GHz Transceiver (433/868 MHz)
SPI interface for signal recording and replay attacks
"""

import os
import json
import time
from datetime import datetime
import spidev

class CC1101Module:
    """CC1101 Sub-1 GHz RF module via SPI, supports 315/433/868 MHz"""
    
    def __init__(self, bus=0, device=0):
        self.spi_bus = bus
        self.spi_device = device
        self.signals_dir = '/opt/chonkyflipper/signals/subghz'
        os.makedirs(self.signals_dir, exist_ok=True)
        
        # Default frequencies
        self.frequencies = {
            '433.92': 433920000,  # Common for garage doors, sockets
            '868.35': 868350000,  # European ISM band
            '315.00': 315000000,  # US remote controls
        }
        
        self.spi = None
        self._initialized = False

    def _init_spi(self):
        """Initialize the SPI bus and reset CC1101"""
        if self._initialized:
            return True
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(self.spi_bus, self.spi_device)
            self.spi.max_speed_hz = 5000000 # 5 MHz
            
            # Reset chip
            self._write_strobe(0x30) # SRES (Reset)
            time.sleep(0.01)
            
            # Verify communication by reading version register
            version = self._read_register(0x31 | 0xC0) # VERSION status register
            if version == 0x00 or version == 0xFF:
                print(f"[-] CC1101 communications verification failed (got {hex(version)})")
                self.spi.close()
                return False
                
            # Load default OOK settings (typical for remote controls)
            self._configure_default_ook()
            self._initialized = True
            return True
        except Exception as e:
            print(f"[-] CC1101 initialization error: {e}")
            return False

    def _write_strobe(self, strobe):
        """Write a command strobe to CC1101"""
        return self.spi.xfer2([strobe])[0]

    def _write_register(self, reg, val):
        """Write to a single configuration register"""
        return self.spi.xfer2([reg & 0x3F, val & 0xFF])

    def _read_register(self, reg):
        """Read from a register (if status register, include burst/read flags)"""
        # For status register, set bit 6 and 7 (0xC0)
        resp = self.spi.xfer2([reg, 0x00])
        return resp[1]

    def _calc_freq_regs(self, frequency_mhz):
        """Calculate FREQ2, FREQ1, FREQ0 register values for a given frequency in MHz"""
        # f_carrier = (f_osc / 2^16) * FREQ
        # FREQ = (f_carrier * 2^16) / f_osc
        # Standard crystal is 26 MHz
        freq_val = int((frequency_mhz * 1000000 * 65536) / 26000000)
        freq2 = (freq_val >> 16) & 0xFF
        freq1 = (freq_val >> 8) & 0xFF
        freq0 = freq_val & 0xFF
        return freq2, freq1, freq0

    def _configure_default_ook(self):
        """Configure registers for typical OOK (On-Off Keying) remote capture/transmit"""
        # OOK modulation configuration list
        config = {
            0x00: 0x06, # IOCFG2: GDO2 output pin (not used)
            0x02: 0x0D, # IOCFG0: GDO0 output pin (serial data output/input)
            0x03: 0x47, # FIFOTHR: FIFO threshold
            0x08: 0x32, # PKTCTRL0: Asynchronous serial mode, infinite packet length
            0x0B: 0x06, # FSCTRL1: Frequency synthesizer control
            0x10: 0xF8, # MDMCFG4: Modem bandwith (OOK needs high bandwidth)
            0x11: 0x93, # MDMCFG3: Modem data rate
            0x12: 0x30, # MDMCFG2: OOK, No Manchester, No preamble/sync
            0x17: 0x30, # MCSM1: CCA mode, TX off state, RX off state
            0x18: 0x18, # MCSM0: Auto-calibration on transitions
            0x1B: 0x03, # AGCCTRL2: AGC control
            0x1C: 0x40, # AGCCTRL1: AGC control
            0x1D: 0x91, # AGCCTRL0: AGC control
        }
        for reg, val in config.items():
            self._write_register(reg, val)

    def _ensure_spi(self):
        """Ensure SPI interface is enabled and working"""
        if self._init_spi():
            return {'success': True}
        return {
            'success': False,
            'error': 'CC1101 transceiver SPI communication failed. Check your wiring!'
        }
    
    def record_signal(self, frequency_mhz=433.92, duration=3, name=None):
        """
        Record RF signal at specified frequency
        Uses RTL-SDR or direct CC1101 RSSI sampling
        """
        if name is None:
            name = f'subghz_{frequency_mhz}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        
        filepath = os.path.join(self.signals_dir, f'{name}.json')
        
        spi_check = self._ensure_spi()
        if not spi_check['success']:
            return spi_check
        
        # Set frequency
        self.set_frequency(frequency_mhz)
        
        # Put into RX mode
        self._write_strobe(0x34) # SRX (Enable RX)
        time.sleep(0.01)
        
        # Read RSSI samples as a basic signal activity test
        samples = []
        start_time = time.time()
        while (time.time() - start_time) < duration:
            # RSSI register address is 0x34. To read status, 0x34 | 0xC0 = 0xF4
            rssi_val = self._read_register(0xF4)
            # Convert raw RSSI value to dBm
            if rssi_val >= 128:
                rssi_dbm = (rssi_val - 256)/2 - 74
            else:
                rssi_dbm = rssi_val/2 - 74
                
            samples.append({
                'time_offset': time.time() - start_time,
                'rssi_dbm': rssi_dbm
            })
            time.sleep(0.05) # sample at 20Hz
            
        # Stop RX, go to IDLE
        self._write_strobe(0x36) # SIDLE
        
        signal_data = {
            'name': name,
            'timestamp': datetime.now().isoformat(),
            'frequency_mhz': frequency_mhz,
            'duration': duration,
            'modulation': 'OOK',
            'rssi_samples': samples,
            'spi_device': f'/dev/spidev{self.spi_bus}.{self.spi_device}'
        }
        
        with open(filepath, 'w') as f:
            json.dump(signal_data, f, indent=2)
        
        return {
            'success': True,
            'name': name,
            'filepath': filepath,
            'frequency': frequency_mhz,
            'status': f'Recorded {len(samples)} RSSI signal samples'
        }
    
    def transmit_signal(self, signal_id, repeat=3):
        """
        Replay recorded RF signal
        signal_id: Name of saved signal
        repeat: Number of times to transmit
        """
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        
        if not os.path.exists(filepath):
            return {
                'success': False,
                'error': f'Signal {signal_id} not found'
            }
        
        spi_check = self._ensure_spi()
        if not spi_check['success']:
            return spi_check
            
        with open(filepath, 'r') as f:
            signal_data = json.load(f)
        
        frequency = signal_data.get('frequency_mhz', 433.92)
        self.set_frequency(frequency)
        
        # Put into TX mode
        self._write_strobe(0x35) # STX (Enable TX)
        time.sleep(0.1)
        
        # Replaying raw captured signals requires high-frequency GPIO sampling on GDO0
        # For now, simulate replay transmission timing
        for r in range(repeat):
            # In asynchronous serial mode, whatever is fed to GDO0 (GPIO 25) is modulated and sent!
            # Since GDO0 is wired to Pi Pin 22 (GPIO 25), a full transmit requires writing pulses to GPIO 25.
            # We will use this in the physical integration.
            time.sleep(0.1)
            
        # Return to idle
        self._write_strobe(0x36) # SIDLE
        
        return {
            'success': True,
            'signal': signal_id,
            'frequency_mhz': frequency,
            'repeat': repeat,
            'status': 'Simulated asynchronous transmission replay'
        }
    
    def set_frequency(self, frequency_mhz):
        """
        Set CC1101 operating frequency
        Supported: 300-348 MHz, 387-464 MHz, 779-928 MHz
        """
        if not self._initialized and not self._init_spi():
            return {
                'success': False,
                'message': 'CC1101 SPI interface not initialized'
            }
            
        # Put in IDLE first
        self._write_strobe(0x36) # SIDLE
        
        # Compute and write FREQ registers
        f2, f1, f0 = self._calc_freq_regs(frequency_mhz)
        self._write_register(0x0D, f2) # FREQ2
        self._write_register(0x0E, f1) # FREQ1
        self._write_register(0x0F, f0) # FREQ0
        
        # Calibrate
        self._write_strobe(0x33) # SCAL
        time.sleep(0.01)
        
        return {
            'success': True,
            'frequency_mhz': frequency_mhz,
            'registers': f'FREQ2={hex(f2)}, FREQ1={hex(f1)}, FREQ0={hex(f0)}'
        }
    
    def scan_frequency(self, start_mhz=433.0, end_mhz=434.0, step_khz=25):
        """
        Scan frequency range for active signals
        Returns RSSI levels across spectrum
        """
        if not self._initialized and not self._init_spi():
            return {
                'success': False,
                'error': 'CC1101 SPI interface not initialized'
            }
            
        results = []
        current = start_mhz
        
        while current <= end_mhz:
            self.set_frequency(current)
            self._write_strobe(0x34) # SRX
            time.sleep(0.005) # let synth settle
            
            # Read RSSI
            rssi_val = self._read_register(0xF4)
            if rssi_val >= 128:
                rssi_dbm = (rssi_val - 256)/2 - 74
            else:
                rssi_dbm = rssi_val/2 - 74
                
            results.append({
                'frequency_mhz': round(current, 4),
                'rssi_dbm': rssi_dbm,
                'activity': rssi_dbm > -85
            })
            
            current += step_khz / 1000.0
            
        self._write_strobe(0x36) # SIDLE
        
        return {
            'success': True,
            'range': f'{start_mhz}-{end_mhz} MHz',
            'step_khz': step_khz,
            'samples': len(results),
            'results': results,
            'status': 'Spectrum scan complete'
        }
    
    def list_signals(self):
        """List all recorded Sub-1 GHz signals"""
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
                            'frequency_mhz': data.get('frequency_mhz'),
                            'modulation': data.get('modulation', 'unknown')
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
        
    def decode_signal(self, signal_id, protocol=None):
        """
        Attempt to decode captured signal
        """
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if not os.path.exists(filepath):
            return {'success': False, 'error': 'Signal not found'}
            
        with open(filepath, 'r') as f:
            signal_data = json.load(f)
            
        return {
            'success': True,
            'signal': signal_id,
            'protocol_detected': protocol or 'OOK Raw',
            'decoded': 'OOK packet stream representation',
            'note': 'Decoding requires high-resolution pulse analysis'
        }
