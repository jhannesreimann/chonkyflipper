#!/usr/bin/env python3
"""
NFC Module - PN532 via libnfc (UART/HSU mode on GPIO 14/15).
Provides card read, block write, full sector dump/clone, and mfoc key recovery.
Depends on: libnfc-bin, mfoc (installed via apt).
"""

import os
import json
import fcntl
import contextlib
import subprocess
import tempfile
from datetime import datetime
from config import CARDS_DIR

os.makedirs(CARDS_DIR, exist_ok=True)

# The PN532 hangs off a single UART (/dev/ttyAMA0). libnfc takes an flock on the
# port, so two callers at once (the two gunicorn workers, or module detection
# racing a real operation) make one of them fail with "Serial port already
# claimed" and the module flickers to unavailable. Serialize every libnfc
# invocation on our own flock so that never happens.
_UART_LOCK_PATH = '/dev/shm/chonky-nfc-uart.lock'
_UART_DEVICE = '/dev/ttyAMA0'


@contextlib.contextmanager
def _uart_lock():
    """Block until the shared PN532 UART lock is held, then release on exit."""
    f = open(_UART_LOCK_PATH, 'w')
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()


def _kill_uart_holders():
    """Best-effort: kill a crashed libnfc tool still holding the UART."""
    subprocess.run(['fuser', '-k', _UART_DEVICE], capture_output=True, timeout=2)


def probe_present(timeout=5):
    """Presence check for module detection, safe to call every status poll.

    Non-blocking on the shared lock: if an NFC operation is already running the
    device is present and in use, so report available without touching the port
    (avoids the false-unavailable flicker). Only when the UART is free do we
    actually probe with nfc-list, recovering a stale lock once before giving up.
    """
    f = open(_UART_LOCK_PATH, 'w')
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True  # busy elsewhere -> present and in use
        try:
            r = subprocess.run(['nfc-list'], capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and 'pn532' in r.stdout.lower():
                return True
            _kill_uart_holders()
            r = subprocess.run(['nfc-list'], capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0 and 'pn532' in r.stdout.lower()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()


# Known default keys that mfoc tests
COMMON_KEYS = [
    'FFFFFFFFFFFF', 'A0A1A2A3A4A5', 'D3F7D3F7D3F7', '000000000000',
    'B0B1B2B3B4B5', '4D3A99C351DD', '1A982C7E459A', 'AABBCCDDEEFF',
    '714C5C886E97', '587EE5F9350F', 'A0478CC39091', '533CB6C723F6',
    '8FD0A4F256E9',
]


class PN532Module:
    """NFC reader/writer via PN532 in HSU (UART) mode using libnfc tools."""

    def __init__(self):
        self.cards_dir = CARDS_DIR

    # Helpers

    @staticmethod
    def _run(cmd, timeout=30):
        """Run a libnfc command under the shared UART lock, return (out, err, rc)."""
        try:
            with _uart_lock():
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.stdout, r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            return '', 'timed out', 1
        except FileNotFoundError:
            return '', f'{cmd[0]} not found', 1

    @classmethod
    def check_device(cls):
        """Return True if the PN532 is reachable via libnfc (UART)."""
        stdout, _, rc = cls._run(['nfc-list'], timeout=5)
        return rc == 0 and 'pn532' in stdout.lower()

    @staticmethod
    def _parse_nfc_list(stdout):
        """Extract UID, ATQA, SAK, ATS, and capabilities from nfc-list -v output."""
        uid = ''
        atqa = ''
        sak = ''
        ats = ''
        speeds = []
        fingerprint = []
        max_frame = ''
        fwt = ''
        uid_size = ''
        iso14443_4 = False
        for line in stdout.split('\n'):
            line = line.strip()
            if line.startswith('UID (NFCID1):'):
                uid = ''.join(line.split(':')[1].strip().split())
            elif line.startswith('ATQA'):
                atqa = ''.join(line.split(':')[1].strip().split())
            elif line.startswith('SAK'):
                sak = ''.join(line.split(':')[1].strip().split())
            elif line.startswith('ATS:'):
                ats = line.split(':', 1)[1].strip().replace(' ', '')
            elif 'bitrate' in line.lower() and 'kbits/s' in line:
                match = __import__('re').search(r'(\d+)\s*kbits/s', line)
                if match:
                    speeds.append(int(match.group(1)))
            elif 'Max Frame Size' in line:
                match = __import__('re').search(r'(\d+)\s*bytes', line)
                if match:
                    max_frame = match.group(1)
            elif 'Frame Waiting Time' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    fwt = parts[1].strip()
            elif 'UID size' in line:
                uid_size = line.replace('*', '').replace('UID size:', '').strip()
            elif 'Compliant with ISO/IEC 14443-4' in line:
                iso14443_4 = True
            elif line.startswith('* MIFARE') or line.startswith('* Mifare'):
                fingerprint.append(line.replace('*', '').strip())
        caps = {
            'ats': ats, 'speeds': sorted(set(speeds)),
            'max_frame': max_frame, 'fwt': fwt, 'uid_size': uid_size,
            'iso14443_4': iso14443_4, 'fingerprint': fingerprint,
        }
        return uid, atqa, sak, caps

    @staticmethod
    def _parse_mfclassic_output(stdout):
        """Parse nfc-mfclassic output into blocks dict {block_num: hex_data}."""
        blocks = {}
        for line in stdout.split('\n'):
            parts = line.strip().split(':')
            if len(parts) >= 2 and parts[0].strip().isdigit():
                blk = int(parts[0].strip())
                data = parts[1].strip().replace(' ', '')
                if len(data) == 32:
                    blocks[blk] = data
        return blocks

    @staticmethod
    def _blocks_to_sectors(blocks):
        """Group 64 blocks into 16 sectors of 4 blocks each."""
        sectors = {}
        for blk, data in blocks.items():
            sector = blk // 4
            if str(sector) not in sectors:
                sectors[str(sector)] = {}
            sectors[str(sector)][str(blk)] = data
        # Remove trailer blocks (block % 4 == 3) for safety
        for s in sectors:
            sectors[s] = {k: v for k, v in sectors[s].items()
                          if int(k) % 4 != 3}
        return sectors

    def _detect_card_type(self, uid, atqa, sak):
        """Guess card type from ATQA/SAK."""
        if atqa == '0004' and sak == '08':
            return 'Mifare Classic 1K'
        if atqa == '0002' and sak == '18':
            return 'Mifare Classic 4K'
        if sak == '20':
            if atqa == '0344':
                return 'MIFARE DESFire EV1'
            return 'MIFARE DESFire'
        if sak == '00':
            return 'Mifare Ultralight / NTAG'
        if uid and len(uid) == 8:
            return 'Mifare Classic (4-byte UID)'
        if uid and len(uid) == 14:
            return 'Mifare Classic (7-byte UID)'
        return 'NFC Tag'

    # Read card (nfc-list)

    @staticmethod
    def _recover_uart():
        """Kill any process holding /dev/ttyAMA0.  Needed after mfoc or other
        libnfc tools crash without closing the UART device."""
        _kill_uart_holders()

    def _nfc_list_with_retry(self, timeout=10):
        """Run nfc-list -v, recovering the UART and retrying once on failure."""
        stdout, stderr, rc = self._run(['nfc-list', '-v'], timeout=timeout)
        if rc == 0 and 'pn532' in stdout.lower():
            return stdout, stderr, rc
        # UART might be locked, try recovery and retry
        self._recover_uart()
        import time as _time
        _time.sleep(0.5)
        return self._run(['nfc-list', '-v'], timeout=timeout)

    def read_card(self, timeout=10):
        """Detect a card and return UID, type, ATQA, SAK."""
        stdout, stderr, rc = self._nfc_list_with_retry(timeout=timeout)
        if rc != 0:
            return {'success': False,
                    'error': f'nfc-list failed: {stderr.strip() or "PN532 not found"}'}
        if 'pn532' not in stdout.lower():
            return {'success': False, 'error': 'PN532 not detected via libnfc'}
        if 'passive target(s) found' not in stdout:
            return {'success': False, 'error': 'No card detected within timeout'}

        uid, atqa, sak, caps = self._parse_nfc_list(stdout)
        if not uid:
            return {'success': False, 'error': 'Card detected but no UID read'}

        card_type = self._detect_card_type(uid, atqa, sak)

        # Try a quick read of block 4 via nfc-mfclassic (Classic only)
        block_data = None
        if not caps.get('iso14443_4'):
            out, _, _ = self._run(
                ['nfc-mfclassic', 'r', 'a', 'u', '/dev/null'], timeout=10)
            if out:
                blocks = self._parse_mfclassic_output(out)
                block_data = blocks.get(4)

        result = {
            'success': True, 'uid': uid,
            'card_type': card_type, 'atqa': atqa, 'sak': sak,
            'block_data': block_data, 'timestamp': datetime.now().isoformat(),
            'capabilities': caps,
        }
        self.save_card(uid, {'block_4': block_data, 'atqa': atqa, 'sak': sak, 'caps': caps},
                       name=f'scanned_{uid}', card_type=card_type)
        return result

    # Write block (nfc-mfclassic single block)

    def write_card(self, uid=None, payload=None, sector=1, block=4):
        """Write 16 bytes to a specific block using the default key."""
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
        except Exception as e:
            return {'success': False, 'error': f'Payload encoding error: {e}'}

        # Write binary .mfd file, then use nfc-mfclassic
        hex_data = payload_bytes.hex()
        tmp = tempfile.NamedTemporaryFile(suffix='.mfd', delete=False)
        tmp.close()
        try:
            # Build a proper 1K .mfd (64 blocks of 16 bytes, binary)
            mfd_data = bytearray(1024)
            mfd_data[block * 16:(block + 1) * 16] = payload_bytes
            with open(tmp.name, 'wb') as f:
                f.write(mfd_data)

            stdout, stderr, rc = self._run(
                ['nfc-mfclassic', 'w', 'a', 'u', tmp.name], timeout=20)

            if rc != 0:
                return {'success': False,
                        'error': f'Write failed: {stderr.strip()[:200] or stdout[:200]}'}

            # Verify by reading back
            verify_out, _, _ = self._run(
                ['nfc-mfclassic', 'r', 'a', 'u', '/dev/null'], timeout=10)
            v_blocks = self._parse_mfclassic_output(verify_out)
            verified = v_blocks.get(block) == hex_data

            return {
                'success': True, 'status': 'Write successful',
                'target_uid': uid or 'detected',
                'block_written': block, 'payload_size': 16,
                'verified': verified,
            }
        finally:
            os.unlink(tmp.name)

    # Full dump (nfc-mfclassic)

    def dump_card(self, key='FFFFFFFFFFFF', timeout=30):
        """Read all 64 blocks of a Mifare Classic 1K using nfc-mfclassic.
        Falls back to mfoc for key recovery if the default key fails."""
        tmp = tempfile.NamedTemporaryFile(suffix='.mfd', delete=False)
        tmp.close()
        try:
            stdout, stderr, rc = self._run(
                ['nfc-mfclassic', 'r', 'a', 'u', tmp.name], timeout=timeout)

            if rc == 0 and os.path.exists(tmp.name):
                with open(tmp.name, 'rb') as f:
                    mfd_data = f.read()
                blocks = {}
                for i in range(0, len(mfd_data), 16):
                    chunk = mfd_data[i:i+16]
                    if len(chunk) == 16:
                        blocks[i // 16] = chunk.hex()
                if blocks:
                    uid_hex = self._uid_from_blocks(blocks)
                    sectors = self._blocks_to_sectors(blocks)
                    self.save_card(uid_hex, {'dump': sectors},
                                   name=f'dump_{uid_hex}',
                                   card_type='Mifare Classic 1K (full dump)')
                    return {
                        'success': True, 'uid': uid_hex,
                        'sectors_read': len(sectors), 'sectors_failed': [],
                        'sectors': sectors,
                    }
        except Exception:
            pass  # Fall through to mfoc
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

        # Default key failed, try mfoc
        return self.mfoc_dump(timeout=timeout)

    # mfoc key recovery + dump

    def mfoc_dump(self, timeout=60):
        """Run mfoc to recover keys and dump all sectors."""
        tmp = tempfile.NamedTemporaryFile(suffix='.mfd', delete=False)
        tmp.close()
        try:
            stdout, stderr, rc = self._run(
                ['mfoc', '-O', tmp.name], timeout=timeout + 15)

            if rc != 0 and not os.path.exists(tmp.name):
                return {'success': False,
                        'error': f'mfoc failed: {stderr[:300] or stdout[:300]}'}

            if os.path.exists(tmp.name) and os.path.getsize(tmp.name) > 0:
                # .mfd files are binary (16 bytes per block)
                with open(tmp.name, 'rb') as f:
                    mfd_data = f.read()
                blocks = {}
                for i in range(0, len(mfd_data), 16):
                    chunk = mfd_data[i:i+16]
                    if len(chunk) == 16:
                        blocks[i // 16] = chunk.hex()
                if not blocks:
                    return {'success': False, 'error': 'mfoc produced empty dump'}
                uid_hex = self._uid_from_blocks(blocks)
                sectors = self._blocks_to_sectors(blocks)

                # Parse which sectors were recovered
                failed = []
                for s in range(16):
                    if str(s) not in sectors or not sectors[str(s)]:
                        failed.append(s)

                self.save_card(uid_hex, {'dump': sectors},
                               name=f'mfoc_{uid_hex}',
                               card_type='Mifare Classic 1K (mfoc dump)')
                return {
                    'success': True, 'uid': uid_hex,
                    'sectors_read': len(sectors) - len(failed),
                    'sectors_failed': failed, 'sectors': sectors,
                    'stdout': stdout[-2000:],
                }
            return {'success': False, 'error': 'mfoc did not produce output file'}
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    # Clone full dump

    def clone_dump(self, dump_data, key='FFFFFFFFFFFF', timeout=30):
        """Write a full sector dump to a magic Mifare Classic card.
        dump_data: {'0': {'0': 'hex...', '1': ..., '2': ...}, ...}"""
        tmp = tempfile.NamedTemporaryFile(suffix='.mfd', delete=False)
        tmp.close()
        try:
            # Build a complete 64-block binary .mfd from dump_data
            all_blocks = {}
            for sector_str, blocks in dump_data.items():
                for blk_str, hex_data in blocks.items():
                    if hex_data and len(hex_data) == 32:
                        all_blocks[int(blk_str)] = hex_data
            mfd_data = bytearray(1024)
            for b in range(64):
                hex_str = all_blocks.get(b, '00000000000000000000000000000000')
                try:
                    mfd_data[b * 16:(b + 1) * 16] = bytes.fromhex(hex_str)
                except ValueError:
                    pass  # leave zeros if invalid hex
            with open(tmp.name, 'wb') as f:
                f.write(mfd_data)

            stdout, stderr, rc = self._run(
                ['nfc-mfclassic', 'w', 'a', 'u', tmp.name], timeout=timeout)

            if rc != 0:
                return {'success': False,
                        'error': f'Clone failed: {stderr.strip()[:200] or stdout[:200]}'}

            # Verify
            verify_out, _, _ = self._run(
                ['nfc-mfclassic', 'r', 'a', 'u', '/dev/null'], timeout=10)
            v_blocks = self._parse_mfclassic_output(verify_out)

            written = {}
            failed = {}
            for blk, expected in all_blocks.items():
                actual = v_blocks.get(blk, '')
                sector = str(blk // 4)
                if actual == expected:
                    written.setdefault(sector, {})[str(blk)] = True
                else:
                    failed.setdefault(sector, {})[str(blk)] = False

            return {
                'success': True,
                'target_uid': self._uid_from_blocks(v_blocks) or 'detected',
                'sectors_written': len(written),
                'sectors_failed': failed,
                'blocks': written,
            }
        finally:
            os.unlink(tmp.name)

    @staticmethod
    def _uid_from_blocks(blocks):
        """Extract UID from block 0 data."""
        b0 = blocks.get(0, '')
        if len(b0) >= 8:
            return b0[:8]
        return ''

    # Card storage (same as before)

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
