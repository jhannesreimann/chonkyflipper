"""
NFC/RFID read and write endpoints.
"""

from flask import Blueprint, request
from utils import api_success, api_error

bp = Blueprint('nfc', __name__)


def _nfc_module():
    import sys
    sys.path.insert(0, '/opt/chonkyflipper')
    from modules.pn532 import PN532Module
    return PN532Module()


@bp.route('/api/nfc/read', methods=['GET'])
def nfc_read():
    pn532 = _nfc_module()
    result = pn532.read_card()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/nfc/write', methods=['POST'])
def nfc_write():
    data = request.json or {}
    uid = data.get('uid')
    payload = data.get('payload')
    pn532 = _nfc_module()
    result = pn532.write_card(uid, payload)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/nfc/dump', methods=['POST'])
def nfc_dump():
    """Full Mifare Classic 1K dump using default key.  See /api/nfc/mfoc for
    key-recovery based dumping via the Kali mfoc tool."""
    data = request.json or {}
    key = data.get('key', 'FFFFFFFFFFFF')
    timeout = data.get('timeout', 30)
    pn532 = _nfc_module()
    result = pn532.dump_card(key=key, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/nfc/clone', methods=['POST'])
def nfc_clone():
    """Write a previously captured sector dump to a magic card."""
    data = request.json or {}
    dump_data = data.get('dump')
    if not dump_data:
        return api_error('dump data (sectors dict) required', 400)
    key = data.get('key', 'FFFFFFFFFFFF')
    timeout = data.get('timeout', 30)
    pn532 = _nfc_module()
    result = pn532.clone_dump(dump_data, key=key, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/api/nfc/mfoc', methods=['POST'])
def nfc_mfoc():
    """Run mfoc (Mifare Offline Cracker) for key recovery on a Mifare Classic.
    Requires a USB NFC reader supported by libnfc, or may work with the PN532
    if it is configured for libnfc access."""
    import subprocess, os, tempfile
    data = request.json or {}
    timeout = data.get('timeout', 60)

    tmpdir = tempfile.mkdtemp(prefix='nfc-mfoc-')
    outfile = os.path.join(tmpdir, 'dump.mfd')
    try:
        proc = subprocess.run(
            ['mfoc', '-O', outfile],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        result = {'success': True, 'stdout': proc.stdout[-2000:], 'stderr': proc.stderr[:500]}
        if os.path.exists(outfile) and os.path.getsize(outfile) > 0:
            result['dump_file'] = outfile
            result['dump_size'] = os.path.getsize(outfile)
        else:
            result['warning'] = 'mfoc completed but no dump file was produced'
        if proc.returncode != 0:
            result['success'] = False
            result['error'] = f'mfoc exited with code {proc.returncode}: {proc.stderr[:300] or proc.stdout[-300:]}'
    except subprocess.TimeoutExpired:
        return api_error(f'mfoc timed out after {timeout}s', 500)
    except FileNotFoundError:
        return api_error('mfoc not installed. Run: sudo apt install mfoc', 500)
    except Exception as e:
        return api_error(str(e), 500)

    return api_success(result) if result.get('success') else api_error(result.get('error', 'mfoc failed'), 500)
