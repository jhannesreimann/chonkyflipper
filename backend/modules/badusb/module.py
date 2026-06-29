#!/usr/bin/env python3
"""
BadUSB module -- USB HID keyboard emulation via /dev/hidg0.

Thin wrapper around the shared DuckyScript interpreter: it locates payloads,
runs them through a HID backend, and reports what happened (statements run,
dropped characters, warnings). The interpreter and keymaps are reusable and
hardware-free; only this module touches the device and the payload directory.
"""

import os
from datetime import datetime

from config import PAYLOADS_DIR

from . import keymaps
from .backends import HidBackend, DryRunBackend
from .interpreter import Interpreter, parse


class BadUSBModule:
    """USB HID keyboard emulation via /dev/hidg0 (Linux configfs gadget)."""

    def __init__(self):
        self.hid_device = '/dev/hidg0'
        self.payloads_dir = os.path.join(PAYLOADS_DIR, 'badusb')
        self.default_layout = 'us'
        os.makedirs(self.payloads_dir, exist_ok=True)

    def _check_device(self):
        return os.path.exists(self.hid_device)

    def _resolve_path(self, payload_name):
        # Support nested category folders (e.g. "recon/win_network_map") while
        # refusing any path that escapes the payloads directory.
        name = payload_name.replace('\\', '/')
        if not name.endswith('.txt'):
            name += '.txt'
        base = os.path.normpath(self.payloads_dir)
        full = os.path.normpath(os.path.join(base, name))
        if not full.startswith(base + os.sep):
            return None
        return full

    def _read(self, payload_name):
        filepath = self._resolve_path(payload_name)
        if filepath is None:
            return None, f'Invalid payload path "{payload_name}"'
        if not os.path.exists(filepath):
            return None, f'Payload "{payload_name}" not found in {self.payloads_dir}'
        with open(filepath, 'r') as f:
            return f.read(), None

    def list_payloads(self):
        # Walk subfolders so category-organised payloads (recon/, credentials/)
        # are returned as "category/name" relative paths.
        try:
            names = []
            for rootdir, _dirs, files in os.walk(self.payloads_dir):
                for fname in files:
                    if not fname.endswith('.txt'):
                        continue
                    rel = os.path.relpath(os.path.join(rootdir, fname), self.payloads_dir)
                    names.append(rel.replace(os.sep, '/')[:-4])
            return {'payloads': sorted(names), 'layouts': keymaps.available_layouts()}
        except Exception as e:
            return {'payloads': [], 'error': str(e)}

    def validate_payload(self, payload_name):
        """Parse a payload without running it. Reports syntax errors early."""
        text, err = self._read(payload_name)
        if err:
            return {'valid': False, 'error': err}
        try:
            parse(text)
            return {'valid': True}
        except Exception as e:
            return {'valid': False, 'error': str(e)}

    def execute_payload(self, payload_name, layout=None):
        if not self._check_device():
            return {
                'success': False,
                'error': f'{self.hid_device} not found',
                'hint': 'Ensure dtoverlay=dwc2 is in /boot/firmware/config.txt, reboot, then run setup-gadget.sh',
            }

        text, err = self._read(payload_name)
        if err:
            return {'success': False, 'error': err}

        layout = (layout or self.default_layout).lower()
        interp = Interpreter(HidBackend(self.hid_device, layout))
        try:
            interp.run(text)
        except PermissionError:
            return {
                'success': False,
                'error': f'Permission denied on {self.hid_device}. Check udev rules or service user permissions.',
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'warnings': interp.warnings}

        return {
            'success': True,
            'payload': payload_name,
            'layout': layout,
            'commands_run': interp.stmt_count,
            'skipped_chars': interp.skipped_chars,
            'warnings': interp.warnings,
            'timestamp': datetime.now().isoformat(),
        }

    def dry_run_payload(self, payload_name, layout=None):
        """Execute against a recording backend -- returns the action log."""
        text, err = self._read(payload_name)
        if err:
            return {'success': False, 'error': err}
        interp = Interpreter(DryRunBackend(layout or self.default_layout))
        try:
            interp.run(text)
        except Exception as e:
            return {'success': False, 'error': str(e), 'warnings': interp.warnings}
        return {
            'success': True,
            'payload': payload_name,
            'log': interp.b.log,
            'commands_run': interp.stmt_count,
            'warnings': interp.warnings,
        }
