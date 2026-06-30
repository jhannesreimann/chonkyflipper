#!/usr/bin/env python3
"""
IR Database Sync Engine -- keeps the local IR payload DB in sync with Flipper-IRDB.
Uses git for efficient incremental updates (avoids GitHub API rate limits).
"""

import os
import subprocess
import json
import time
import re
from datetime import datetime


class IRDBSync:
    """Sync engine for Flipper-IRDB -> local SQLite database."""

    IRDB_REPO = 'https://github.com/logickworkshop/Flipper-IRDB.git'
    DEVICE_TYPE_MAP = {
        'TVs': 'TV',
        'Projectors': 'Projector',
        'ACs': 'AC',
        'Audio_and_Video_Receivers': 'Audio/Video Receiver',
        'SoundBars': 'Soundbar',
        'Streaming_Devices': 'Streaming Device',
        'DVD_Players': 'DVD Player',
        'Blu-Ray': 'Blu-Ray Player',
        'Cable_Boxes': 'Cable Box',
        'CD_Players': 'CD Player',
        'Consoles': 'Console',
        'Fans': 'Fan',
        'Cameras': 'Camera',
        'Monitors': 'Monitor',
        'LED_Lighting': 'LED Lighting',
        'Speakers': 'Speaker',
        'Toys': 'Toy',
        'Car_Multimedia': 'Car Multimedia',
        'Computers': 'Computer',
        'Digital_Signs': 'Digital Sign',
        'Heaters': 'Heater',
        'Humidifiers': 'Humidifier',
        'Air_Purifiers': 'Air Purifier',
        'Vacuum_Cleaners': 'Vacuum Cleaner',
        'VCR': 'VCR',
        'CCTV': 'CCTV',
        'Converters': 'Converter',
        'DVB-T': 'DVB-T',
        'Fireplaces': 'Fireplace',
        'Head_Units': 'Head Unit',
        'KVM': 'KVM',
        'Laserdisc': 'Laserdisc',
        'MiniDisc': 'MiniDisc',
        'Multimedia': 'Multimedia',
        'Picture_Frames': 'Picture Frame',
        'Touchscreen_Displays': 'Touchscreen Display',
        'TV_Tuner': 'TV Tuner',
        'Universal_TV_Remotes': 'Universal Remote',
        'Videoconferencing': 'Videoconferencing',
        'Whiteboards': 'Whiteboard',
        'Window_cleaners': 'Window Cleaner',
        'Bidet': 'Bidet',
        'Clocks': 'Clock',
        'Dust_Collectors': 'Dust Collector',
        'Handicap_Ceiling_Lifts': 'Ceiling Lift',
        'Miscellaneous': 'Misc',
    }

    def __init__(self, db, repo_dir=None):
        self.db = db
        if repo_dir is None:
            candidates = [
                '/opt/chonkyflipper/data/irdb',
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             '..', 'data', 'irdb'),
            ]
            repo_dir = candidates[0]
            for p in candidates:
                if os.path.isdir(os.path.dirname(p)):
                    repo_dir = p
                    break
        self.repo_dir = repo_dir

    # --- Repo Management ---------------------------------

    def _run(self, cmd, cwd=None, timeout=120):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                cwd=cwd or self.repo_dir
            )
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        except subprocess.TimeoutExpired:
            return '', 'Command timed out', 1
        except Exception as e:
            return '', str(e), 1

    def clone_or_update(self):
        """Ensure repo exists and is up to date. Returns {action, sha}."""
        if not os.path.isdir(os.path.join(self.repo_dir, '.git')):
            os.makedirs(os.path.dirname(self.repo_dir), exist_ok=True)
            # Shallow clone to save space
            stdout, stderr, rc = self._run(
                ['git', 'clone', '--depth', '1', self.IRDB_REPO, self.repo_dir],
                cwd='/tmp'
            )
            if rc != 0:
                return {'success': False, 'error': f'Clone failed: {stderr}'}
            sha = self._get_head_sha()
            self.db.set_sync_state('last_commit_sha', sha)
            self.db.set_sync_state('last_sync_at', datetime.now().isoformat())
            return {'success': True, 'action': 'cloned', 'sha': sha}

        # Already cloned -- pull updates
        stdout, stderr, rc = self._run(['git', 'fetch', 'origin', 'main'])
        if rc != 0:
            return {'success': False, 'error': f'Fetch failed: {stderr}'}

        old_sha = self._get_head_sha()
        stdout, stderr, rc = self._run(
            ['git', 'merge', 'origin/main', '--ff-only']
        )
        new_sha = self._get_head_sha()

        if old_sha == new_sha:
            return {'success': True, 'action': 'up_to_date', 'sha': new_sha}

        self.db.set_sync_state('last_commit_sha', new_sha)
        self.db.set_sync_state('last_sync_at', datetime.now().isoformat())
        return {'success': True, 'action': 'updated', 'sha': new_sha,
                'old_sha': old_sha}

    def _get_head_sha(self):
        stdout, _, rc = self._run(['git', 'rev-parse', 'HEAD'])
        return stdout if rc == 0 else None

    def _get_changed_files(self, old_sha, new_sha):
        """Get list of changed .ir files between two commits."""
        stdout, _, rc = self._run(
            ['git', 'diff', '--name-only', old_sha, new_sha, '--', '*.ir']
        )
        if rc != 0 or not stdout:
            return []
        return [f for f in stdout.split('\n') if f.endswith('.ir')]

    # --- Check for Updates ------------------------------

    def check_for_updates(self):
        """Check if upstream has new commits. Returns {has_updates, ...}."""
        # If repo doesn't exist at all, signal that a full clone is needed
        if not os.path.isdir(os.path.join(self.repo_dir, '.git')):
            return {'has_updates': True, 'new_commits': -1, 'needs_clone': True,
                    'local_sha': None, 'remote_sha': None}

        stdout, stderr, rc = self._run(['git', 'fetch', 'origin', 'main'])
        if rc != 0:
            return {'has_updates': False, 'error': f'Fetch failed: {stderr}'}

        local_sha = self._get_head_sha()
        stdout, _, rc = self._run(['git', 'rev-parse', 'origin/main'])
        remote_sha = stdout if rc == 0 else None

        if not local_sha or not remote_sha:
            return {'has_updates': False, 'error': 'Could not determine SHAs'}

        has_updates = local_sha != remote_sha

        new_count = 0
        if has_updates:
            stdout, _, rc = self._run(
                ['git', 'rev-list', '--count', f'{local_sha}..{remote_sha}']
            )
            try:
                new_count = int(stdout) if rc == 0 else 0
            except ValueError:
                new_count = 0

        return {
            'has_updates': has_updates,
            'new_commits': new_count,
            'local_sha': local_sha,
            'remote_sha': remote_sha
        }

    # --- Sync -------------------------------------------

    def sync(self, progress_callback=None):
        """
        Incremental sync: pull latest, import only new/changed .ir files.
        Returns {action, files_added, files_updated, errors}.
        """
        # Ensure we have the repo
        status = self.clone_or_update()
        if not status['success']:
            return status

        action = status.get('action', 'up_to_date')

        # If the DB was reset (no sync state) but repo exists, force a full import
        stored_sha = self.db.get_sync_state('last_commit_sha')
        if action == 'up_to_date' and stored_sha:
            return {
                'success': True,
                'action': 'up_to_date',
                'files_added': 0,
                'files_updated': 0,
                'errors': 0,
                'sha': status.get('sha', '')
            }
        if action == 'up_to_date' and not stored_sha:
            action = 'reimport'  # DB was reset, re-import everything

        # Get changed files
        old_sha = status.get('old_sha', '')
        new_sha = status.get('sha', '')

        if old_sha and new_sha:
            changed = self._get_changed_files(old_sha, new_sha)
        else:
            # Full clone -- import everything
            changed = self._find_all_ir_files()

        if not changed:
            return {
                'success': True,
                'action': action,
                'files_added': 0,
                'files_updated': 0,
                'errors': 0,
                'sha': new_sha
            }

        added = 0
        updated = 0
        errors = 0
        total = len(changed)

        for idx, rel_path in enumerate(changed):
            try:
                result = self._import_ir_file(rel_path)
                if result.get('added'):
                    added += 1
                elif result.get('updated'):
                    updated += 1
                else:
                    errors += 1
            except Exception:
                errors += 1

            if progress_callback:
                progress_callback(idx + 1, total, rel_path)

        return {
            'success': True,
            'action': action,
            'files_added': added,
            'files_updated': updated,
            'errors': errors,
            'total': total,
            'sha': new_sha
        }

    def _find_all_ir_files(self):
        """Walk the repo and return all .ir file paths (relative)."""
        files = []
        for root, dirs, filenames in os.walk(self.repo_dir):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in filenames:
                if f.endswith('.ir'):
                    full = os.path.join(root, f)
                    files.append(os.path.relpath(full, self.repo_dir))
        return sorted(files)

    def _import_ir_file(self, rel_path):
        """Parse a single .ir file and import into DB."""
        full_path = os.path.join(self.repo_dir, rel_path)
        parts = rel_path.replace('\\', '/').split('/')

        if len(parts) < 3:
            return {'skipped': True, 'reason': 'Invalid path depth'}

        device_type_folder = parts[0]
        brand_name = parts[1]
        filename = parts[-1]
        device_name = filename.replace('.ir', '')

        # Map device type folder to readable name
        device_type = self.DEVICE_TYPE_MAP.get(device_type_folder, device_type_folder)

        # Parse the file
        signals = self.parse_ir_file(full_path)
        if not signals:
            return {'skipped': True, 'reason': 'No signals parsed'}

        # Upsert brand + device
        brand_slug = brand_name.lower().replace(' ', '_').replace('-', '_')
        brand_id = self.db.insert_brand(brand_name, slug=brand_slug,
                                        device_type=device_type)
        device_slug = device_name.lower().replace(' ', '_').replace('-', '_')
        device_id = self.db.insert_device(
            brand_id, device_name, slug=device_slug,
            device_type=device_type, source_file=rel_path
        )

        added = 0
        updated = 0
        for sig in signals:
            btn_id = self._make_button_id(sig['name'])
            existing = self.db.get_button_by_device_and_id(device_id, btn_id)
            btn_kwargs = {
                'device_id': device_id,
                'button_id': btn_id,
                'label': sig['name'],
                'protocol': sig.get('protocol', ''),
                'address': sig.get('address'),
                'command': sig.get('command'),
                'frequency': sig.get('frequency', 38000),
                'duty_cycle': sig.get('duty_cycle', 0.33),
                'raw_pulses': sig.get('pulses'),
                'raw_spaces': sig.get('spaces'),
                'protocol_hint': sig.get('protocol', ''),
                'header_pulse': sig.get('header_pulse'),
                'header_space': sig.get('header_space'),
                'source_file': rel_path,
            }
            self.db.insert_button(**btn_kwargs)
            if existing:
                updated += 1
            else:
                added += 1

        return {'added': added, 'updated': updated}

    @staticmethod
    def _make_button_id(name):
        """Convert a signal name to a safe button_id string."""
        return re.sub(r'[^a-z0-9_]', '_', name.lower().replace(' ', '_'))

    # --- .ir File Parser --------------------------------

    def parse_ir_file(self, filepath):
        """
        Parse a Flipper Zero .ir file.
        Returns list of signal dicts with parsed or raw data.
        """
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        signals = []
        current = None
        in_data = False
        data_values = []

        for line in content.split('\n'):
            line = line.strip()

            if not line or line.startswith('Filetype:') or line.startswith('Version:'):
                continue

            # Comment line -- save as description
            if line.startswith('#') and not current:
                continue

            # New signal block
            if line.startswith('name:'):
                if current:
                    if data_values:
                        self._finalize_signal(current, data_values)
                    signals.append(current)
                current = {'name': line.split(':', 1)[1].strip()}
                in_data = False
                data_values = []
                continue

            if not current:
                continue

            if line.startswith('type:'):
                current['type'] = line.split(':', 1)[1].strip()
            elif line.startswith('protocol:'):
                current['protocol'] = line.split(':', 1)[1].strip()
            elif line.startswith('address:'):
                addr_str = line.split(':', 1)[1].strip()
                current['address_raw'] = addr_str
                current['address'] = self._parse_hex_bytes(addr_str)
            elif line.startswith('command:'):
                cmd_str = line.split(':', 1)[1].strip()
                current['command_raw'] = cmd_str
                current['command'] = self._parse_hex_bytes(cmd_str)
            elif line.startswith('frequency:'):
                try:
                    current['frequency'] = int(line.split(':', 1)[1].strip())
                except ValueError:
                    current['frequency'] = 38000
            elif line.startswith('duty_cycle:'):
                try:
                    current['duty_cycle'] = float(line.split(':', 1)[1].strip())
                except ValueError:
                    current['duty_cycle'] = 0.33
            elif line.startswith('data:'):
                data_str = line.split(':', 1)[1].strip()
                data_values = [int(v) for v in data_str.split() if v]
                in_data = True

        # Finalize last signal
        if current:
            self._finalize_signal(current, data_values)
            signals.append(current)

        return signals

    def _finalize_signal(self, signal, data_values):
        """Convert raw data array into pulses and spaces."""
        if signal.get('type') == 'raw' and data_values:
            pulses = []
            spaces = []
            for i, val in enumerate(data_values):
                if i % 2 == 0:
                    pulses.append(val)
                else:
                    spaces.append(val)
            signal['pulses'] = pulses
            signal['spaces'] = spaces

            # Detect header pulse for protocol hint
            if pulses:
                signal['header_pulse'] = pulses[0]
                if spaces:
                    signal['header_space'] = spaces[0]

            # Guess protocol from timing
            if not signal.get('protocol'):
                signal['protocol'] = self._guess_protocol(pulses, spaces)

        elif signal.get('type') == 'parsed':
            # For parsed signals, encode using the protocol
            proto = signal.get('protocol', 'NEC')
            addr = signal.get('address', 0)
            cmd = signal.get('command', 0)
            try:
                from modules.ir_protocols import encode
                (pulses, spaces), err = encode(proto, address=addr, command=cmd)
                if err is None:
                    signal['pulses'] = pulses
                    signal['spaces'] = spaces
            except Exception:
                pass

    @staticmethod
    def _parse_hex_bytes(hex_str):
        """Parse '00 00 00 00' or '00 00' hex byte string into an integer."""
        if not hex_str:
            return None
        parts = hex_str.strip().split()
        val = 0
        for i, b in enumerate(reversed(parts)):
            try:
                val |= int(b, 16) << (i * 8)
            except ValueError:
                continue
        return val

    @staticmethod
    def _guess_protocol(pulses, spaces):
        """Guess protocol from raw timing for display purposes."""
        if not pulses:
            return 'raw'
        hp = pulses[0] if pulses else 0
        hs = spaces[0] if spaces else 0

        if 8500 < hp < 9500 and 4000 < hs < 5000:
            return 'NEC'
        if 3000 < hp < 4000 and 1500 < hs < 2000:
            return 'Panasonic'
        if 2000 < hp < 2800 and 500 < hs < 700:
            return 'Sony SIRC'
        if 4000 < hp < 5000 and 4000 < hs < 5000:
            return 'Samsung32'
        if 800 < hp < 1000:
            return 'RC5'
        return 'raw'
