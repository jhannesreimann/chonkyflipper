#!/usr/bin/env python3
"""
CC1101 Module - Sub-1 GHz Transceiver (433/868 MHz)
SPI interface for signal recording and replay attacks
"""

import os
import json
import time
from datetime import datetime
from config import SIGNALS_SUBGHZ


class CC1101Module:
    """CC1101 Sub-1 GHz RF module via SPI, supports 315/433/868 MHz"""

    def __init__(self, bus=0, device=0):
        self.spi_bus = bus
        self.spi_device = device
        self.signals_dir = SIGNALS_SUBGHZ
        os.makedirs(self.signals_dir, exist_ok=True)
        self.spi = None
        self._initialized = False
        self._calibrated = False

    def _init_spi(self):
        if self._initialized:
            return True
        try:
            import spidev
            self.spi = spidev.SpiDev()
            self.spi.open(self.spi_bus, self.spi_device)
            self.spi.max_speed_hz = 5000000
            self._write_strobe(0x30)  # SRES
            time.sleep(0.01)
            version = self._read_register(0x31 | 0xC0)
            if version == 0x00 or version == 0xFF:
                self.spi.close()
                return False
            self._configure_default_ook()
            self._initialized = True
            return True
        except Exception:
            return False

    def _write_strobe(self, strobe):
        return self.spi.xfer2([strobe])[0]

    def _write_register(self, reg, val):
        return self.spi.xfer2([reg & 0x3F, val & 0xFF])

    def _read_register(self, reg):
        resp = self.spi.xfer2([reg, 0x00])
        return resp[1]

    def _calc_freq_regs(self, frequency_mhz):
        freq_val = int((frequency_mhz * 1000000 * 65536) / 26000000)
        return (freq_val >> 16) & 0xFF, (freq_val >> 8) & 0xFF, freq_val & 0xFF

    def _configure_default_ook(self):
        config = {
            0x00: 0x06, 0x02: 0x0D, 0x03: 0x47, 0x08: 0x32,
            0x0B: 0x06, 0x10: 0xF8, 0x11: 0x93, 0x12: 0x30,
            0x17: 0x30, 0x18: 0x18, 0x1B: 0x03, 0x1C: 0x40, 0x1D: 0x91,
        }
        for reg, val in config.items():
            self._write_register(reg, val)

    def _ensure_spi(self):
        if self._init_spi():
            return {'success': True}
        return {'success': False, 'error': 'CC1101 SPI communication failed. Check wiring.'}

    # ------------------------------------------------------------------
    # Frequency control
    # ------------------------------------------------------------------

    def set_frequency(self, frequency_mhz):
        if not self._initialized and not self._init_spi():
            return {'success': False, 'message': 'CC1101 SPI interface not initialized'}

        self._write_strobe(0x36)  # SIDLE
        f2, f1, f0 = self._calc_freq_regs(frequency_mhz)
        self._write_register(0x0D, f2)
        self._write_register(0x0E, f1)
        self._write_register(0x0F, f0)
        time.sleep(0.005)

        if not self._calibrated:
            self._write_strobe(0x33)  # SCAL - calibrate once
            time.sleep(0.01)
            self._calibrated = True

        return {'success': True, 'frequency_mhz': frequency_mhz}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_signal(self, frequency_mhz=433.92, duration=3, name=None):
        if name is None:
            name = f'subghz_{frequency_mhz}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

        filepath = os.path.join(self.signals_dir, f'{name}.json')

        spi_check = self._ensure_spi()
        if not spi_check['success']:
            return spi_check

        self.set_frequency(frequency_mhz)
        self._write_strobe(0x34)  # SRX
        time.sleep(0.01)

        samples = []
        start_time = time.time()
        while (time.time() - start_time) < duration:
            rssi_val = self._read_register(0xF4)
            if rssi_val >= 128:
                rssi_dbm = (rssi_val - 256) / 2 - 74
            else:
                rssi_dbm = rssi_val / 2 - 74
            samples.append({'time_offset': time.time() - start_time, 'rssi_dbm': rssi_dbm})
            time.sleep(0.05)

        self._write_strobe(0x36)  # SIDLE

        signal_data = {
            'name': name, 'timestamp': datetime.now().isoformat(),
            'frequency_mhz': frequency_mhz, 'duration': duration,
            'modulation': 'OOK', 'rssi_samples': samples,
            'spi_device': f'/dev/spidev{self.spi_bus}.{self.spi_device}',
        }
        with open(filepath, 'w') as f:
            json.dump(signal_data, f, indent=2)

        return {
            'success': True, 'name': name, 'filepath': filepath,
            'frequency': frequency_mhz, 'samples': len(samples),
        }

    # ------------------------------------------------------------------
    # Transmission (not yet implemented for raw replay)
    # ------------------------------------------------------------------

    def transmit_signal(self, signal_id, repeat=3):
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if not os.path.exists(filepath):
            return {'success': False, 'error': f'Signal {signal_id} not found'}

        spi_check = self._ensure_spi()
        if not spi_check['success']:
            return spi_check

        with open(filepath, 'r') as f:
            signal_data = json.load(f)

        frequency = signal_data.get('frequency_mhz', 433.92)
        self.set_frequency(frequency)
        self._write_strobe(0x35)  # STX

        # Full raw replay requires GPIO-level pulse timing on GDO0 (GPIO 25).
        # This is not yet implemented; return a clear status.
        time.sleep(0.3)
        self._write_strobe(0x36)  # SIDLE
        return {
            'success': False,
            'error': 'Raw sub-GHz replay not yet implemented. Recordings saved to disk for analysis.',
        }

    # ------------------------------------------------------------------
    # Spectrum scan
    # ------------------------------------------------------------------

    def scan_frequency(self, start_mhz=433.0, end_mhz=434.0, step_khz=25):
        if not self._initialized and not self._init_spi():
            return {'success': False, 'error': 'CC1101 SPI interface not initialized'}

        # Calibrate once before the scan loop
        self._write_strobe(0x36)  # SIDLE
        self._write_strobe(0x33)  # SCAL
        time.sleep(0.01)
        self._calibrated = True

        results = []
        current = start_mhz
        while current <= end_mhz:
            # Update only frequency registers (no recalibration per step)
            f2, f1, f0 = self._calc_freq_regs(current)
            self._write_strobe(0x36)  # SIDLE
            self._write_register(0x0D, f2)
            self._write_register(0x0E, f1)
            self._write_register(0x0F, f0)
            time.sleep(0.002)
            self._write_strobe(0x34)  # SRX
            time.sleep(0.005)

            rssi_val = self._read_register(0xF4)
            rssi_dbm = (rssi_val - 256) / 2 - 74 if rssi_val >= 128 else rssi_val / 2 - 74

            results.append({
                'frequency_mhz': round(current, 4),
                'rssi_dbm': rssi_dbm,
                'activity': rssi_dbm > -85,
            })
            current += step_khz / 1000.0

        self._write_strobe(0x36)  # SIDLE
        return {
            'success': True, 'range': f'{start_mhz}-{end_mhz} MHz',
            'step_khz': step_khz, 'samples': len(results), 'results': results,
        }

    # ------------------------------------------------------------------
    # Signal management
    # ------------------------------------------------------------------

    def list_signals(self):
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
                            'modulation': data.get('modulation', 'unknown'),
                        })
        except Exception as e:
            return {'error': str(e)}
        return {'signals': signals}

    def delete_signal(self, signal_id):
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if os.path.exists(filepath):
            os.remove(filepath)
            return {'success': True, 'deleted': signal_id}
        return {'success': False, 'error': 'Signal not found'}
