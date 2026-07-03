#!/usr/bin/env python3
"""
Keyboard layout tables for the BadUSB HID gadget.

A layout maps a printable character to (modifier_byte, hid_keycode). The
modifier byte is the USB HID modifier bitmask sent in byte 0 of the report:
    0x02 = Left Shift, 0x40 = Right Alt (AltGr).

Only the raw HID path (HidBackend) cares about layouts - it sends physical
scancodes, so the bytes that come out depend entirely on the layout the target
OS is set to. Pick the layout that matches the target machine, not the Pi.

NAMED_KEYS and MODIFIERS are layout-independent (HID usage IDs).
"""

# Modifier bitmask bits (HID report byte 0)
MODIFIERS = {
    'CTRL': 0x01, 'CONTROL': 0x01,
    'SHIFT': 0x02,
    'ALT': 0x04,
    'GUI': 0x08, 'WINDOWS': 0x08, 'COMMAND': 0x08, 'META': 0x08,
    'ALTGR': 0x40, 'RALT': 0x40,
}

# Named keys + letter/digit positions, used for standalone presses and as the
# non-modifier target of a combo (e.g. the "r" in GUI r). HID usage IDs.
NAMED_KEYS = {
    'ENTER': 0x28, 'RETURN': 0x28, 'ESCAPE': 0x29, 'ESC': 0x29,
    'BACKSPACE': 0x2A, 'TAB': 0x2B, 'SPACE': 0x2C,
    'DELETE': 0x4C, 'DEL': 0x4C, 'INSERT': 0x49,
    'HOME': 0x4A, 'END': 0x4D, 'PAGEUP': 0x4B, 'PAGEDOWN': 0x4E,
    'UP': 0x52, 'DOWN': 0x51, 'LEFT': 0x50, 'RIGHT': 0x4F,
    'CAPSLOCK': 0x39, 'NUMLOCK': 0x53, 'SCROLLLOCK': 0x47,
    'PRINTSCREEN': 0x46, 'PAUSE': 0x48, 'BREAK': 0x48, 'MENU': 0x65, 'APP': 0x65,
    'F1': 0x3A, 'F2': 0x3B, 'F3': 0x3C, 'F4': 0x3D,
    'F5': 0x3E, 'F6': 0x3F, 'F7': 0x40, 'F8': 0x41,
    'F9': 0x42, 'F10': 0x43, 'F11': 0x44, 'F12': 0x45,
}
# letters and digits as physical keys (US positions) for use in combos
for _i, _ch in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
    NAMED_KEYS[_ch] = 0x04 + _i
for _i, _ch in enumerate('1234567890'):
    NAMED_KEYS[_ch] = 0x1E + _i


def _build_us():
    """US QWERTY - the original Hak5/DuckyScript default layout."""
    m = {}
    for i, ch in enumerate('abcdefghijklmnopqrstuvwxyz'):
        m[ch] = (0x00, 0x04 + i)
        m[ch.upper()] = (0x02, 0x04 + i)
    digits = '1234567890'
    for i, ch in enumerate(digits):
        m[ch] = (0x00, 0x1E + i)
    for sym, base in zip('!@#$%^&*()', digits):
        m[sym] = (0x02, m[base][1])
    m.update({
        ' ': (0x00, 0x2C), '\t': (0x00, 0x2B), '\n': (0x00, 0x28),
        '-': (0x00, 0x2D), '_': (0x02, 0x2D), '=': (0x00, 0x2E), '+': (0x02, 0x2E),
        '[': (0x00, 0x2F), '{': (0x02, 0x2F), ']': (0x00, 0x30), '}': (0x02, 0x30),
        '\\': (0x00, 0x31), '|': (0x02, 0x31),
        ';': (0x00, 0x33), ':': (0x02, 0x33), "'": (0x00, 0x34), '"': (0x02, 0x34),
        '`': (0x00, 0x35), '~': (0x02, 0x35), ',': (0x00, 0x36), '<': (0x02, 0x36),
        '.': (0x00, 0x37), '>': (0x02, 0x37), '/': (0x00, 0x38), '?': (0x02, 0x38),
    })
    return m


def _build_de():
    """German QWERTZ. ASCII output only - chars that need umlaut/dead keys
    on this layout are intentionally omitted (backtick and ^ are dead keys)."""
    SHIFT, ALTGR = 0x02, 0x40
    m = {}
    # a..x sit in the same positions as US; y and z are swapped
    for i, ch in enumerate('abcdefghijklmnopqrstuvwx'):
        m[ch] = (0x00, 0x04 + i)
        m[ch.upper()] = (SHIFT, 0x04 + i)
    m['z'] = (0x00, 0x1C); m['Z'] = (SHIFT, 0x1C)
    m['y'] = (0x00, 0x1D); m['Y'] = (SHIFT, 0x1D)
    digits = '1234567890'
    for i, ch in enumerate(digits):
        m[ch] = (0x00, 0x1E + i)
    for sym, base in {'!': '1', '"': '2', '$': '4', '%': '5', '&': '6',
                      '/': '7', '(': '8', ')': '9', '=': '0'}.items():
        m[sym] = (SHIFT, m[base][1])
    for sym, base in {'{': '7', '[': '8', ']': '9', '}': '0'}.items():
        m[sym] = (ALTGR, m[base][1])
    m.update({
        ' ': (0x00, 0x2C), '\t': (0x00, 0x2B), '\n': (0x00, 0x28),
        '@': (ALTGR, 0x14),                       # AltGr + q
        '?': (SHIFT, 0x2D), '\\': (ALTGR, 0x2D),  # the ss / ? key
        '+': (0x00, 0x30), '*': (SHIFT, 0x30), '~': (ALTGR, 0x30),  # ~ is a dead key
        '#': (0x00, 0x32), "'": (SHIFT, 0x32),
        ',': (0x00, 0x36), ';': (SHIFT, 0x36),
        '.': (0x00, 0x37), ':': (SHIFT, 0x37),
        '-': (0x00, 0x38), '_': (SHIFT, 0x38),
        '<': (0x00, 0x64), '>': (SHIFT, 0x64), '|': (ALTGR, 0x64),
    })
    return m


LAYOUTS = {
    'us': _build_us(),
    'de': _build_de(),
}


def has_layout(name):
    return name.lower() in LAYOUTS


def get_layout(name):
    return LAYOUTS.get(name.lower(), LAYOUTS['us'])


def available_layouts():
    return sorted(LAYOUTS.keys())
