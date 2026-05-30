#!/usr/bin/env python3
"""
BadUSB Module - USB HID Keyboard Emulation
Writes 8-byte HID reports to /dev/hidg0 (Linux configfs USB gadget)
"""

import os
import struct
import time
from datetime import datetime

# Maps printable ASCII characters to (modifier_byte, HID_keycode).
# modifier 0x00 = none, 0x02 = Left Shift
_CHAR_MAP = {
    'a':(0x00,0x04),'b':(0x00,0x05),'c':(0x00,0x06),'d':(0x00,0x07),
    'e':(0x00,0x08),'f':(0x00,0x09),'g':(0x00,0x0A),'h':(0x00,0x0B),
    'i':(0x00,0x0C),'j':(0x00,0x0D),'k':(0x00,0x0E),'l':(0x00,0x0F),
    'm':(0x00,0x10),'n':(0x00,0x11),'o':(0x00,0x12),'p':(0x00,0x13),
    'q':(0x00,0x14),'r':(0x00,0x15),'s':(0x00,0x16),'t':(0x00,0x17),
    'u':(0x00,0x18),'v':(0x00,0x19),'w':(0x00,0x1A),'x':(0x00,0x1B),
    'y':(0x00,0x1C),'z':(0x00,0x1D),
    'A':(0x02,0x04),'B':(0x02,0x05),'C':(0x02,0x06),'D':(0x02,0x07),
    'E':(0x02,0x08),'F':(0x02,0x09),'G':(0x02,0x0A),'H':(0x02,0x0B),
    'I':(0x02,0x0C),'J':(0x02,0x0D),'K':(0x02,0x0E),'L':(0x02,0x0F),
    'M':(0x02,0x10),'N':(0x02,0x11),'O':(0x02,0x12),'P':(0x02,0x13),
    'Q':(0x02,0x14),'R':(0x02,0x15),'S':(0x02,0x16),'T':(0x02,0x17),
    'U':(0x02,0x18),'V':(0x02,0x19),'W':(0x02,0x1A),'X':(0x02,0x1B),
    'Y':(0x02,0x1C),'Z':(0x02,0x1D),
    '1':(0x00,0x1E),'2':(0x00,0x1F),'3':(0x00,0x20),'4':(0x00,0x21),
    '5':(0x00,0x22),'6':(0x00,0x23),'7':(0x00,0x24),'8':(0x00,0x25),
    '9':(0x00,0x26),'0':(0x00,0x27),
    '!':(0x02,0x1E),'@':(0x02,0x1F),'#':(0x02,0x20),'$':(0x02,0x21),
    '%':(0x02,0x22),'^':(0x02,0x23),'&':(0x02,0x24),'*':(0x02,0x25),
    '(':(0x02,0x26),')':(0x02,0x27),
    ' ':(0x00,0x2C),'\t':(0x00,0x2B),'\n':(0x00,0x28),
    '-':(0x00,0x2D),'_':(0x02,0x2D),'=':(0x00,0x2E),'+':(0x02,0x2E),
    '[':(0x00,0x2F),'{':(0x02,0x2F),']':(0x00,0x30),'}':(0x02,0x30),
    '\\':(0x00,0x31),'|':(0x02,0x31),
    ';':(0x00,0x33),':':(0x02,0x33),"'":(0x00,0x34),'"':(0x02,0x34),
    '`':(0x00,0x35),'~':(0x02,0x35),',':(0x00,0x36),'<':(0x02,0x36),
    '.':(0x00,0x37),'>':(0x02,0x37),'/':(0x00,0x38),'?':(0x02,0x38),
}

# Named keys used in DuckyScript commands (e.g. ENTER, F5, UP)
# Maps token -> HID keycode (modifier always comes from the command prefix)
_KEY_MAP = {
    'ENTER':0x28,'RETURN':0x28,'ESCAPE':0x29,'ESC':0x29,
    'BACKSPACE':0x2A,'TAB':0x2B,'SPACE':0x2C,
    'DELETE':0x4C,'DEL':0x4C,'INSERT':0x49,
    'HOME':0x4A,'END':0x4D,'PAGEUP':0x4B,'PAGEDOWN':0x4E,
    'UP':0x52,'DOWN':0x51,'LEFT':0x50,'RIGHT':0x4F,
    'CAPSLOCK':0x39,'NUMLOCK':0x53,'SCROLLLOCK':0x47,
    'PRINTSCREEN':0x46,'PAUSE':0x48,'BREAK':0x48,
    'F1':0x3A,'F2':0x3B,'F3':0x3C,'F4':0x3D,
    'F5':0x3E,'F6':0x3F,'F7':0x40,'F8':0x41,
    'F9':0x42,'F10':0x43,'F11':0x44,'F12':0x45,
    # Single-letter args for modifier combos (e.g. "GUI r", "CTRL c")
    'A':0x04,'B':0x05,'C':0x06,'D':0x07,'E':0x08,'F':0x09,
    'G':0x0A,'H':0x0B,'I':0x0C,'J':0x0D,'K':0x0E,'L':0x0F,
    'M':0x10,'N':0x11,'O':0x12,'P':0x13,'Q':0x14,'R':0x15,
    'S':0x16,'T':0x17,'U':0x18,'V':0x19,'W':0x1A,'X':0x1B,
    'Y':0x1C,'Z':0x1D,
}

# Modifier key bits (OR'd together for combos like CTRL+SHIFT)
_MODIFIER_BITS = {
    'CTRL':0x01,'CONTROL':0x01,
    'SHIFT':0x02,
    'ALT':0x04,
    'GUI':0x08,'WINDOWS':0x08,'COMMAND':0x08,'META':0x08,
}

_KEY_RELEASE = bytes(8)  # 8 zero bytes = all keys up


class BadUSBModule:
    """USB HID keyboard emulation via /dev/hidg0 (Linux configfs gadget)"""

    def __init__(self):
        self.hid_device = '/dev/hidg0'
        self.payloads_dir = '/opt/chonkyflipper/payloads'
        os.makedirs(self.payloads_dir, exist_ok=True)

    def _check_device(self):
        return os.path.exists(self.hid_device)

    def _send_report(self, modifier, keycode):
        """Send one key-down + key-up HID report pair to the host."""
        report = struct.pack('8B', modifier, 0, keycode, 0, 0, 0, 0, 0)
        with open(self.hid_device, 'wb') as hid:
            hid.write(report)
            hid.write(_KEY_RELEASE)

    def _type_string(self, text):
        """Type a string character by character. Unknown characters are skipped."""
        for ch in text:
            entry = _CHAR_MAP.get(ch)
            if entry:
                self._send_report(entry[0], entry[1])

    def _run_commands(self, commands):
        """Execute a parsed command list against /dev/hidg0."""
        for cmd, args in commands:
            if cmd == 'STRING':
                self._type_string(args)

            elif cmd == 'DELAY':
                ms = int(args) if args.strip().isdigit() else 500
                time.sleep(ms / 1000)

            elif cmd in _MODIFIER_BITS and args:
                # e.g. "GUI r", "CTRL SHIFT ESC", "ALT F4"
                mod_byte = _MODIFIER_BITS[cmd]
                keycode = 0x00
                for token in args.upper().split():
                    if token in _MODIFIER_BITS:
                        mod_byte |= _MODIFIER_BITS[token]
                    elif token in _KEY_MAP:
                        keycode = _KEY_MAP[token]
                self._send_report(mod_byte, keycode)

            elif cmd in _KEY_MAP:
                self._send_report(0x00, _KEY_MAP[cmd])

    def _resolve_path(self, payload_name):
        if not payload_name.endswith('.txt'):
            payload_name += '.txt'
        return os.path.join(self.payloads_dir, payload_name)

    def parse_payload(self, payload_name):
        """
        Parse a DuckyScript payload file into (cmd, args) tuples.
        Returns (commands, error_string). On success error_string is None.
        """
        filepath = self._resolve_path(payload_name)
        if not os.path.exists(filepath):
            return None, f'Payload "{payload_name}" not found in {self.payloads_dir}'

        commands = []
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.upper().startswith('REM'):
                    continue
                parts = line.split(' ', 1)
                commands.append((parts[0].upper(), parts[1] if len(parts) > 1 else ''))
        return commands, None

    def list_payloads(self):
        """List available payload files (without .txt extension)."""
        try:
            names = [f[:-4] for f in os.listdir(self.payloads_dir) if f.endswith('.txt')]
            return {'payloads': sorted(names)}
        except Exception as e:
            return {'payloads': [], 'error': str(e)}

    def execute_payload(self, payload_name):
        """Execute a DuckyScript payload via /dev/hidg0."""
        if not self._check_device():
            return {
                'success': False,
                'error': f'{self.hid_device} not found',
                'hint': 'Ensure dtoverlay=dwc2 is in /boot/firmware/config.txt, reboot, then run setup-gadget.sh'
            }

        commands, err = self.parse_payload(payload_name)
        if err:
            return {'success': False, 'error': err}

        try:
            self._run_commands(commands)
            return {
                'success': True,
                'payload': payload_name,
                'commands_run': len(commands),
                'timestamp': datetime.now().isoformat()
            }
        except PermissionError:
            return {
                'success': False,
                'error': f'Permission denied on {self.hid_device}. Check udev rules or service user permissions.'
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
