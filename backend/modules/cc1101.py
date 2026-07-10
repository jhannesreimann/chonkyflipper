#!/usr/bin/env python3
"""
CC1101 Module - Sub-1 GHz Transceiver (433/868 MHz)
SPI control plane + lgpio GDO0 timing for OOK record and replay.
"""

import os
import json
import time
from datetime import datetime
from config import SIGNALS_SUBGHZ

# GDO0 carries the raw demodulated OOK bitstream in async serial mode
# (RX: CC1101 -> Pi, TX: Pi -> CC1101). Wired to BCM 25 (header pin 22).
GDO0_BCM = 25

# OOK denoise / burst-extraction tuning (microseconds)
GAP_US = 6000        # silence longer than this separates transmissions
MIN_PULSES = 16      # a burst shorter than this is treated as noise
MIN_MEDIAN_US = 60   # real OOK pulses are wide; sub-us hash is slicer noise
MAX_PULSE_US = 30000 # clamp absurd gaps so replay never stalls the line high
CARRIER_DBM = -85    # RSSI floor a genuine transmission must clear


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
        self._chip = None  # lgpio chip handle, opened lazily

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

    def _write_burst(self, reg, values):
        return self.spi.xfer2([(reg & 0x3F) | 0x40] + list(values))

    def _read_register(self, reg):
        resp = self.spi.xfer2([reg, 0x00])
        return resp[1]

    def _calc_freq_regs(self, frequency_mhz):
        freq_val = int((frequency_mhz * 1000000 * 65536) / 26000000)
        return (freq_val >> 16) & 0xFF, (freq_val >> 8) & 0xFF, freq_val & 0xFF

    def _configure_default_ook(self):
        # Async serial OOK: GDO0 (0x02=0x0D) streams the raw sliced bitstream,
        # PKTCTRL0 (0x08=0x32) = async serial, MDMCFG2 (0x12=0x30) = OOK/ASK
        # with no preamble/sync so the modem does not gate on a packet framing.
        config = {
            0x00: 0x06, 0x02: 0x0D, 0x03: 0x47, 0x08: 0x32,
            0x0B: 0x06, 0x10: 0xF8, 0x11: 0x93, 0x12: 0x30,
            0x17: 0x30, 0x18: 0x18, 0x1B: 0x03, 0x1C: 0x40, 0x1D: 0x91,
        }
        for reg, val in config.items():
            self._write_register(reg, val)

    def _configure_tx_ook(self):
        # For async OOK TX the modem keys the PA from the GDO0 input level:
        # PATABLE[0]=off, PATABLE[1]=on, FREND0 (0x22) selects the 1-index PA
        # ramp so a logic high emits carrier and a logic low is silent.
        self._configure_default_ook()
        self._write_register(0x22, 0x11)          # FREND0: PA_POWER = 1
        self._write_burst(0x3E, [0x00, 0xC0])     # PATABLE: off / ~+10 dBm

    def _ensure_spi(self):
        if self._init_spi():
            return {'success': True}
        return {'success': False, 'error': 'CC1101 SPI communication failed. Check wiring.'}

    # GDO0 timing plane (lgpio) -- no daemon, opened on first use

    def _gpio(self):
        if self._chip is not None:
            return self._chip
        import lgpio
        self._chip = lgpio.gpiochip_open(0)
        return self._chip

    def _gpio_release(self, pin):
        try:
            import lgpio
            lgpio.gpio_free(self._chip, pin)
        except Exception:
            pass

    # Frequency control

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

    # Recording -- raw OOK pulse capture via GDO0 edge timestamps

    def _extract_burst(self, pulses):
        # pulses: list of [level, us]. Split on long idle gaps and keep the
        # densest segment so replay carries the transmission, not the noise
        # floor around it.
        segments = []
        current = []
        for level, dur in pulses:
            current.append([level, dur])
            if dur >= GAP_US:
                segments.append(current)
                current = []
        if current:
            segments.append(current)
        best = max(segments, key=len, default=[])
        # Trim a trailing idle gap so the burst ends on an edge.
        while best and best[-1][1] >= GAP_US:
            best.pop()
        return best

    def record_signal(self, frequency_mhz=433.92, duration=3, name=None):
        if name is None:
            name = f'subghz_{frequency_mhz}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

        filepath = os.path.join(self.signals_dir, f'{name}.json')

        spi_check = self._ensure_spi()
        if not spi_check['success']:
            return spi_check

        try:
            import lgpio
        except Exception as e:
            return {'success': False, 'error': f'lgpio unavailable for GDO0 capture: {e}'}

        self._configure_default_ook()
        self.set_frequency(frequency_mhz)
        self._write_strobe(0x3A)  # SFRX flush
        self._write_strobe(0x34)  # SRX
        time.sleep(0.02)

        edges = []  # (level, tick_ns)

        def _on_edge(chip, gpio, level, tick):
            edges.append((level, tick))

        chip = self._gpio()
        lgpio.gpio_claim_alert(chip, GDO0_BCM, lgpio.BOTH_EDGES)
        cb = lgpio.callback(chip, GDO0_BCM, lgpio.BOTH_EDGES, _on_edge)

        # Poll RSSI across the window: without carrier the async slicer floods
        # GDO0 with noise edges, so edge count alone cannot tell signal from
        # noise. A real transmission lifts RSSI well above the noise floor.
        peak_rssi = -120.0
        deadline = time.time() + duration
        while time.time() < deadline:
            rv = self._read_register(0xF4)  # RSSI status reg
            dbm = (rv - 256) / 2 - 74 if rv >= 128 else rv / 2 - 74
            if dbm > peak_rssi:
                peak_rssi = dbm
            time.sleep(0.02)

        cb.cancel()
        self._gpio_release(GDO0_BCM)
        self._write_strobe(0x36)  # SIDLE

        # Convert transitions to [level, duration_us]. Each edge reports the
        # level the line moved TO; that level holds until the next edge.
        pulses = []
        for i in range(len(edges) - 1):
            level = edges[i][0]
            dur = int((edges[i + 1][1] - edges[i][1]) / 1000)
            if dur > 0:
                pulses.append([level, min(dur, MAX_PULSE_US)])

        burst = self._extract_burst(pulses)
        # A genuine OOK frame needs carrier (RSSI above the floor), enough
        # structured pulses, and pulse widths in a real timing range -- not the
        # sub-microsecond hash the slicer emits on noise.
        widths = sorted(d for _, d in burst)
        median_us = widths[len(widths) // 2] if widths else 0
        carrier = peak_rssi >= CARRIER_DBM
        clean = carrier and len(burst) >= MIN_PULSES and median_us >= MIN_MEDIAN_US

        # Only persist the pulse train when it is a real burst; noise captures
        # would otherwise bloat the store with tens of thousands of junk edges.
        stored = burst if clean else []

        signal_data = {
            'name': name, 'timestamp': datetime.now().isoformat(),
            'frequency_mhz': frequency_mhz, 'duration': duration,
            'modulation': 'OOK', 'pulses': stored,
            'edges': len(edges), 'clean': clean,
            'peak_rssi_dbm': round(peak_rssi, 1),
            'spi_device': f'/dev/spidev{self.spi_bus}.{self.spi_device}',
        }
        with open(filepath, 'w') as f:
            json.dump(signal_data, f, indent=2)

        if clean:
            note = None
        elif not carrier:
            note = f'No carrier (peak {round(peak_rssi, 1)} dBm) -- no transmission detected during the window.'
        else:
            note = 'Carrier seen but no clean OOK burst decoded -- try again closer to the transmitter.'

        return {
            'success': True, 'name': name, 'filepath': filepath,
            'frequency': frequency_mhz, 'pulses': len(signal_data['pulses']),
            'edges': len(edges), 'clean': clean,
            'peak_rssi_dbm': round(peak_rssi, 1), 'note': note,
        }

    # Transmission -- raw OOK replay by driving GDO0 in async serial mode

    def transmit_signal(self, signal_id, repeat=3):
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if not os.path.exists(filepath):
            return {'success': False, 'error': f'Signal {signal_id} not found'}

        spi_check = self._ensure_spi()
        if not spi_check['success']:
            return spi_check

        with open(filepath, 'r') as f:
            signal_data = json.load(f)

        pulses = signal_data.get('pulses') or []
        if not pulses:
            return {'success': False, 'error': 'Signal has no raw pulse data to replay.'}

        try:
            import lgpio
        except Exception as e:
            return {'success': False, 'error': f'lgpio unavailable for GDO0 replay: {e}'}

        frequency = signal_data.get('frequency_mhz', 433.92)
        self._configure_tx_ook()
        self.set_frequency(frequency)

        # Build the lgpio wave: group of one GPIO (GDO0), bit 0 = high/low.
        wave = []
        for level, dur in pulses:
            bits = 1 if level else 0
            wave.append(lgpio.pulse(bits, 1, max(1, int(dur))))

        chip = self._gpio()
        lgpio.group_claim_output(chip, [GDO0_BCM], [0])
        self._write_strobe(0x35)  # STX -- PA on, keyed by GDO0 input
        time.sleep(0.005)

        sent = 0
        try:
            for _ in range(max(1, repeat)):
                lgpio.tx_wave(chip, GDO0_BCM, wave)
                while lgpio.tx_busy(chip, GDO0_BCM, lgpio.TX_WAVE):
                    time.sleep(0.002)
                sent += 1
                time.sleep(0.02)  # inter-frame gap
        finally:
            self._gpio_release(GDO0_BCM)
            self._write_strobe(0x36)  # SIDLE

        return {
            'success': True, 'signal_id': signal_id, 'frequency': frequency,
            'pulses': len(pulses), 'repeats': sent,
        }

    # Spectrum scan

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

    # Signal management

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
                            'pulses': len(data.get('pulses', [])),
                            'clean': data.get('clean', False),
                        })
        except Exception as e:
            return {'error': str(e)}
        signals.sort(key=lambda s: s.get('timestamp') or '', reverse=True)
        return {'signals': signals}

    def delete_signal(self, signal_id):
        filepath = os.path.join(self.signals_dir, f'{signal_id}.json')
        if os.path.exists(filepath):
            os.remove(filepath)
            return {'success': True, 'deleted': signal_id}
        return {'success': False, 'error': 'Signal not found'}
