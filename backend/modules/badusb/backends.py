#!/usr/bin/env python3
"""
Output backends for the DuckyScript interpreter.

The interpreter is layout- and hardware-agnostic: it emits semantic actions
(type a char, press a named key, a modifier combo, wait) and a backend turns
them into real output. This is what lets the Pi (raw HID) and the dev tester
(local keyboard) share one interpreter.

Every backend implements:
    char(ch)        -> bool   type one printable character; False if unmapped
    key(name)       -> bool   press a named key (ENTER, F5, LEFT, ...)
    combo(mods, key)-> bool   modifier combo, mods is a list of modifier names
    delay(ms)                 wait (or note the wait, for dry runs)
    set_layout(name)          switch the active keyboard layout
"""

import time

from . import keymaps

_KEY_RELEASE = bytes(8)


class HidBackend:
    """Writes 8-byte HID reports to /dev/hidg0 (Linux configfs USB gadget)."""

    def __init__(self, device='/dev/hidg0', layout='us'):
        self.device = device
        self.charmap = keymaps.get_layout(layout)

    def set_layout(self, name):
        self.charmap = keymaps.get_layout(name)

    def _send(self, modifier, keycode):
        report = bytes((modifier & 0xFF, 0, keycode & 0xFF, 0, 0, 0, 0, 0))
        with open(self.device, 'wb') as hid:
            hid.write(report)
            hid.write(_KEY_RELEASE)

    def char(self, ch):
        entry = self.charmap.get(ch)
        if entry is None:
            return False
        self._send(entry[0], entry[1])
        return True

    def key(self, name):
        keycode = keymaps.NAMED_KEYS.get(name.upper())
        if keycode is None:
            return False
        self._send(0x00, keycode)
        return True

    def combo(self, mods, key):
        bits = 0
        for m in mods:
            bits |= keymaps.MODIFIERS.get(m.upper(), 0)
        keycode = keymaps.NAMED_KEYS.get(key.upper(), 0) if key else 0
        self._send(bits, keycode)
        return True

    def delay(self, ms):
        if ms > 0:
            time.sleep(ms / 1000.0)


class DryRunBackend:
    """Records actions instead of typing - used for previews and tests."""

    def __init__(self, layout='us'):
        self.layout = layout
        self.log = []

    def set_layout(self, name):
        self.layout = name
        self.log.append(('layout', name))

    def char(self, ch):
        self.log.append(('char', ch))
        return True

    def key(self, name):
        self.log.append(('key', name.upper()))
        return True

    def combo(self, mods, key):
        self.log.append(('combo', [m.upper() for m in mods], key))
        return True

    def delay(self, ms):
        self.log.append(('delay', ms))
