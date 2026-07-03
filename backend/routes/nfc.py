"""
NFC/RFID read and write endpoints.
"""

from flask import Blueprint, request
from hardware import get_module
from utils import api_success, api_error

bp = Blueprint('nfc', __name__, url_prefix='/api')


@bp.route('/nfc/read', methods=['GET'])
def nfc_read():
    pn532 = get_module('pn532')
    result = pn532.read_card()
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/nfc/write', methods=['POST'])
def nfc_write():
    data = request.json or {}
    uid = data.get('uid')
    payload = data.get('payload')
    pn532 = get_module('pn532')
    result = pn532.write_card(uid, payload)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/nfc/dump', methods=['POST'])
def nfc_dump():
    """Full Mifare Classic 1K dump using default key.  See /api/nfc/mfoc for
    key-recovery based dumping via the Kali mfoc tool."""
    data = request.json or {}
    key = data.get('key', 'FFFFFFFFFFFF')
    timeout = data.get('timeout', 30)
    pn532 = get_module('pn532')
    result = pn532.dump_card(key=key, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/nfc/clone', methods=['POST'])
def nfc_clone():
    """Write a previously captured sector dump to a magic card."""
    data = request.json or {}
    dump_data = data.get('dump')
    if not dump_data:
        return api_error('dump data (sectors dict) required', 400)
    key = data.get('key', 'FFFFFFFFFFFF')
    timeout = data.get('timeout', 30)
    pn532 = get_module('pn532')
    result = pn532.clone_dump(dump_data, key=key, timeout=timeout)
    return api_success(result) if result.get('success') else api_error(result.get('error', 'Failed'), 500)


@bp.route('/nfc/mfoc', methods=['POST'])
def nfc_mfoc():
    """Run mfoc (Mifare Offline Cracker) for key recovery on a Mifare Classic."""
    import subprocess, os, tempfile
    data = request.json or {}
    timeout_sec = data.get('timeout', 120)

    tmpdir = tempfile.mkdtemp(prefix='nfc-mfoc-')
    outfile = os.path.join(tmpdir, 'dump.mfd')
    try:
        # Use timeout command wrapper so the entire process tree is killed,
        # preventing UART device lockup from orphaned libnfc processes.
        proc = subprocess.run(
            ['timeout', '--signal=KILL', str(timeout_sec),
             'mfoc', '-O', outfile],
            capture_output=True, text=True, timeout=timeout_sec + 15,
        )
        # Exit code 137 = killed by SIGKILL (timeout)
        killed = proc.returncode == 137
        dump_ok = os.path.exists(outfile) and os.path.getsize(outfile) > 0
        result = {
            'success': dump_ok or not killed,
            'stdout': proc.stdout[-3000:],
            'stderr': proc.stderr[:500],
            'timed_out': killed,
        }
        if dump_ok:
            result['dump_file'] = outfile
            result['dump_size'] = os.path.getsize(outfile)
        elif killed:
            result['error'] = f'mfoc timed out after {timeout_sec}s. Try again with card in sweet spot.'
        elif proc.returncode != 0:
            result['success'] = False
            result['error'] = f'mfoc exited with code {proc.returncode}: {proc.stderr[:300] or proc.stdout[-300:]}'
    except subprocess.TimeoutExpired:
        return api_error(f'mfoc timed out after {timeout_sec}s', 500)
    except FileNotFoundError:
        return api_error('mfoc not installed. Run: sudo apt install mfoc', 500)
    except Exception as e:
        return api_error(str(e), 500)

    return api_success(result) if result.get('success') else api_error(result.get('error', 'mfoc failed'), 500)
