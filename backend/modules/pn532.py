#!/usr/bin/env python3
"""
PN532 Module - RFID/NFC Reader/Writer
I2C interface, using adafruit-circuitpython-pn532
Supports: Mifare Classic, Ultralight, DESFire, FeliCa
"""

import os
import json
import time
from datetime import datetime
from config import CARDS_DIR


class PN532Module:
    """PN532 NFC/RFID module via I2C, GPIO 2 (SDA) / GPIO 3 (SCL)"""

    def __init__(self, i2c_bus=1, address=0x24):
        self.i2c_bus = i2c_bus
        self.address = address
        self.cards_dir = CARDS_DIR
        os.makedirs(self.cards_dir, exist_ok=True)
        self.pn532 = None
        self._initialized = False

    def _init_sensor(self):
        if self._initialized and self.pn532 is not None:
            return True
        import time as _time
        last_err = ''
        for attempt in range(3):
            try:
                import board
                import busio
                from adafruit_pn532.i2c import PN532_I2C
                i2c = busio.I2C(board.SCL, board.SDA)
                self.pn532 = PN532_I2C(i2c, address=self.address)
                self.pn532.SAM_configuration()
                _time.sleep(0.1)  # Let PN532 settle after SAM
                self._initialized = True
                return True
            except Exception as e:
                last_err = str(e)
                if attempt < 2:
                    _time.sleep(0.3)
        import sys
        print(f'[pn532] _init_sensor failed after 3 attempts: {last_err}', file=sys.stderr, flush=True)
        return False

    def read_card(self, timeout=10):
        if not self._init_sensor():
            return {'success': False, 'error': 'PN532 could not be initialized. Check I2C bus wiring and permissions.'}

        try:
            uid = self.pn532.read_passive_target(timeout=0.5)
            start_time = time.time()
            while uid is None and (time.time() - start_time) < timeout:
                uid = self.pn532.read_passive_target(timeout=0.5)
                time.sleep(0.1)

            if uid is not None:
                uid_hex = ''.join([f'{x:02x}' for x in uid])
                card_type = 'Mifare Classic' if len(uid) == 4 else 'NFC Tag'

                block_data = None
                try:
                    key = b'\xFF\xFF\xFF\xFF\xFF\xFF'
                    if len(uid) == 4:
                        if self.pn532.mifare_classic_authenticate_block(
                            uid, block_number=4, key_number=0x60, key=key,
                        ):
                            data = self.pn532.mifare_classic_read_block(4)
                            if data:
                                block_data = data.hex()
                except Exception:
                    pass

                result = {
                    'success': True, 'uid': uid_hex, 'card_type': card_type,
                    'block_data': block_data, 'timestamp': datetime.now().isoformat(),
                }
                self.save_card(uid_hex, {'block_4': block_data} if block_data else {},
                               name=f'scanned_{uid_hex}', card_type=card_type)
                return result

            return {'success': False, 'error': 'No card detected within timeout'}
        except Exception as e:
            return {'success': False, 'error': f'Error reading card: {str(e)}'}

    def write_card(self, uid=None, payload=None, sector=1, block=4):
        if not self._init_sensor():
            return {'success': False, 'error': 'PN532 could not be initialized. Check I2C bus wiring.'}

        if not payload:
            return {'success': False, 'error': 'Payload data is required'}

        try:
            if isinstance(payload, str):
                try:
                    payload_bytes = bytes.fromhex(payload)
                except ValueError:
                    payload_bytes = payload.encode('utf-8')
            else:
                payload_bytes = bytes(payload)

            if len(payload_bytes) < 16:
                payload_bytes += b'\x00' * (16 - len(payload_bytes))
            elif len(payload_bytes) > 16:
                payload_bytes = payload_bytes[:16]

            detected_uid = self.pn532.read_passive_target(timeout=5.0)
            if detected_uid is None:
                return {'success': False, 'error': 'No card detected to write to'}

            detected_uid_hex = ''.join([f'{x:02x}' for x in detected_uid])
            if uid and detected_uid_hex != uid:
                return {'success': False, 'error': f'UID mismatch! Expected {uid}, got {detected_uid_hex}'}

            key = b'\xFF\xFF\xFF\xFF\xFF\xFF'
            authenticated = self.pn532.mifare_classic_authenticate_block(
                detected_uid, block_number=block, key_number=0x60, key=key,
            )
            if not authenticated:
                return {'success': False, 'error': f'Failed to authenticate block {block} with default Key A'}

            self.pn532.mifare_classic_write_block(block, payload_bytes)
            verified_data = self.pn532.mifare_classic_read_block(block)

            return {
                'success': True, 'status': 'Write successful',
                'target_uid': detected_uid_hex, 'block_written': block,
                'payload_size': len(payload_bytes),
                'verified': verified_data == payload_bytes,
            }
        except Exception as e:
            return {'success': False, 'error': f'Error writing card: {str(e)}'}

    def save_card(self, uid, data, name=None, card_type=None):
        if name is None:
            name = f'card_{uid}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

        filepath = os.path.join(self.cards_dir, f'{name}.json')
        card_data = {
            'name': name, 'uid': uid,
            'timestamp': datetime.now().isoformat(), 'data': data,
            'type': card_type or 'Unknown',
        }
        with open(filepath, 'w') as f:
            json.dump(card_data, f, indent=2)

        return {'success': True, 'name': name, 'filepath': filepath, 'uid': uid}

    def list_saved_cards(self):
        cards = []
        try:
            for filename in os.listdir(self.cards_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(self.cards_dir, filename)
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                        cards.append({
                            'name': data.get('name', filename),
                            'uid': data.get('uid'),
                            'timestamp': data.get('timestamp'),
                            'type': data.get('type', 'unknown'),
                        })
        except Exception as e:
            return {'error': str(e)}
        return {'cards': cards}

    # ------------------------------------------------------------------
    # Full Mifare Classic dump (all accessible sectors via default key)
    # ------------------------------------------------------------------

    def dump_card(self, key='FFFFFFFFFFFF', timeout=30):
        """Read all 16 sectors of a Mifare Classic 1K card using a known key.
        Returns sector data keyed by sector number (0-15), each with 3 data
        blocks (0-2) per sector.  Block 3 of each sector is the trailer (keys
        + access bits) and is skipped for safety.

        Only sectors that authenticate successfully are included.  Use mfoc
        or mfcuk for key recovery on sectors that fail."""
        if not self._init_sensor():
            return {'success': False, 'error': 'PN532 not detected'}
        try:
            import adafruit_pn532
        except ImportError:
            return {'success': False, 'error': 'adafruit_pn532 not installed'}

        uid = None
        deadline = __import__('time').time() + timeout
        while __import__('time').time() < deadline:
            uid = self.pn532.read_passive_target(timeout=0.8)
            if uid:
                break
            __import__('time').sleep(0.3)

        if not uid:
            return {'success': False, 'error': 'No card found'}

        uid_hex = ''.join(format(b, '02x') for b in uid)
        key_bytes = b'\xff\xff\xff\xff\xff\xff' if key == 'FFFFFFFFFFFF' else (
            bytes.fromhex(key) if len(key) == 12 else bytes(12))

        sectors = {}
        failed = []
        for sector in range(16):
            block = sector * 4  # First block of sector (trailer = block + 3)
            try:
                if not self.pn532.mifare_classic_authenticate_block(
                    uid, block_number=block, key_number=0x60, key=key_bytes,
                ):
                    failed.append(sector)
                    continue
                # Read data blocks 0-2 (skip trailer at block+3)
                sector_data = {}
                for b in range(3):
                    blk = block + b
                    try:
                        data = self.pn532.mifare_classic_read_block(blk)
                        sector_data[str(blk)] = ''.join(format(x, '02x') for x in data)
                    except Exception:
                        sector_data[str(blk)] = None
                sectors[str(sector)] = sector_data
            except Exception:
                failed.append(sector)

        # Save the dump so it appears in saved cards history
        self.save_card(uid_hex, {'dump': sectors}, name=f'dump_{uid_hex}',
                       card_type='Mifare Classic (full dump)')

        return {
            'success': True,
            'uid': uid_hex,
            'sectors_read': len(sectors),
            'sectors_failed': failed,
            'sectors': sectors,
        }

    def clone_dump(self, dump_data, key='FFFFFFFFFFFF', timeout=30):
        """Write a previously captured sector dump back to a magic Mifare
        Classic card.  dump_data should be a dict like {'0': {'4': 'hex...', '5': ..., '6': ...}, ...}.

        Only sectors present in dump_data are written.  A magic (UID-changeable)
        card is required for writing sector 0 blocks."""
        if not self._init_sensor():
            return {'success': False, 'error': 'PN532 not detected'}
        try:
            import adafruit_pn532
        except ImportError:
            return {'success': False, 'error': 'adafruit_pn532 not installed'}

        uid = None
        deadline = __import__('time').time() + timeout
        while __import__('time').time() < deadline:
            uid = self.pn532.read_passive_target(timeout=0.8)
            if uid:
                break
            __import__('time').sleep(0.3)

        if not uid:
            return {'success': False, 'error': 'No card found'}

        uid_hex = ''.join(format(b, '02x') for b in uid)
        key_bytes = b'\xff\xff\xff\xff\xff\xff' if key == 'FFFFFFFFFFFF' else (
            bytes.fromhex(key) if len(key) == 12 else bytes(12))
        written = {}
        failed = {}

        for sector_str, blocks in dump_data.items():
            sector = int(sector_str)
            trailer_block = sector * 4 + 3
            auth_block = sector * 4
            try:
                if not self.pn532.mifare_classic_authenticate_block(
                    uid, block_number=auth_block, key_number=0x60, key=key_bytes,
                ):
                    failed[sector_str] = 'auth failed'
                    continue
                sector_written = {}
                for blk_str, hex_data in blocks.items():
                    blk = int(blk_str)
                    if blk == trailer_block:
                        continue  # Never write sector trailers via this path
                    if not hex_data or len(hex_data) != 32:
                        continue
                    try:
                        payload = bytes.fromhex(hex_data)
                        self.pn532.mifare_classic_write_block(blk, payload)
                        # Verify
                        verify = self.pn532.mifare_classic_read_block(blk)
                        v_hex = ''.join(format(x, '02x') for x in verify)
                        sector_written[blk_str] = v_hex == hex_data.lower()
                    except Exception as e:
                        sector_written[blk_str] = False
                written[sector_str] = sector_written
            except Exception as e:
                failed[sector_str] = str(e)

        return {
            'success': True,
            'target_uid': uid_hex,
            'sectors_written': len(written),
            'sectors_failed': failed,
            'blocks': written,
        }
