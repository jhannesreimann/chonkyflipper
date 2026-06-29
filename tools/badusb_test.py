#!/usr/bin/env python3
"""
BadUSB payload tester -- runs DuckyScript payloads on the dev machine using the
SAME interpreter the Pi uses (backend/modules/badusb), so what you preview here
is what the gadget executes. Only the output backend differs: this drives the
local keyboard via PyAutoGUI instead of writing HID reports to /dev/hidg0.

  python tools/badusb_test.py <payload.txt> --dry-run     # preview, no typing
  python tools/badusb_test.py <payload.txt> --delay 3     # focus window, then type

Note: PyAutoGUI types through the OS keyboard layout, so --layout only affects
the dry-run preview. The raw HID layout maps only matter on the Pi.
"""

import argparse
import os
import sys
import time

# Reuse the real interpreter from the backend package.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, 'backend'))
from modules.badusb.interpreter import Interpreter, parse  # noqa: E402

# DuckyScript token -> PyAutoGUI key name
_MODNAME = {
    'CTRL': 'ctrl', 'CONTROL': 'ctrl', 'SHIFT': 'shift', 'ALT': 'alt',
    'GUI': 'win', 'WINDOWS': 'win', 'COMMAND': 'win', 'META': 'win',
    'ALTGR': 'altright', 'RALT': 'altright',
}
_KEYNAME = {
    'ENTER': 'enter', 'RETURN': 'enter', 'ESC': 'esc', 'ESCAPE': 'esc',
    'SPACE': 'space', 'TAB': 'tab', 'BACKSPACE': 'backspace',
    'DELETE': 'delete', 'DEL': 'delete', 'INSERT': 'insert',
    'UP': 'up', 'DOWN': 'down', 'LEFT': 'left', 'RIGHT': 'right',
    'HOME': 'home', 'END': 'end', 'PAGEUP': 'pageup', 'PAGEDOWN': 'pagedown',
    'PRINTSCREEN': 'printscreen', 'CAPSLOCK': 'capslock', 'NUMLOCK': 'numlock',
    'PAUSE': 'pause', 'BREAK': 'pause',
    'F1': 'f1', 'F2': 'f2', 'F3': 'f3', 'F4': 'f4', 'F5': 'f5', 'F6': 'f6',
    'F7': 'f7', 'F8': 'f8', 'F9': 'f9', 'F10': 'f10', 'F11': 'f11', 'F12': 'f12',
}


class PyAutoGUIBackend:
    """Semantic backend that drives the local keyboard (or prints, in dry-run)."""

    def __init__(self, dry_run=False, interval=0.0):
        self.dry_run = dry_run
        self.interval = interval
        self._buf = []
        if not dry_run:
            global pyautogui
            import pyautogui
            pyautogui.FAILSAFE = True

    def _flush(self):
        if self._buf:
            print(f'  TYPE   {"".join(self._buf)!r}')
            self._buf = []

    def char(self, ch):
        if self.dry_run:
            self._buf.append(ch)
        else:
            pyautogui.write(ch, interval=self.interval)
        return True

    def key(self, name):
        if self.dry_run:
            self._flush()
            print(f'  KEY    {name}')
        else:
            pyautogui.press(_KEYNAME.get(name.upper(), name.lower()))
        return True

    def combo(self, mods, key):
        names = [_MODNAME.get(m.upper(), m.lower()) for m in mods]
        if key:
            names.append(_KEYNAME.get(key.upper(), key.lower()))
        if self.dry_run:
            self._flush()
            print(f'  COMBO  {" + ".join(names)}')
        else:
            pyautogui.hotkey(*names)
        return True

    def delay(self, ms):
        if self.dry_run:
            self._flush()
            print(f'  WAIT   {ms}ms')
        else:
            time.sleep(ms / 1000.0)

    def set_layout(self, name):
        if self.dry_run:
            self._flush()
            print(f'  LAYOUT {name}')


def main():
    ap = argparse.ArgumentParser(
        description='Run a DuckyScript payload using the shared interpreter.')
    ap.add_argument('payload', help='Path to payload .txt file')
    ap.add_argument('--dry-run', action='store_true',
                    help='Print what would be typed without touching the keyboard')
    ap.add_argument('--delay', type=int, default=3, metavar='SECS',
                    help='Startup delay -- time to focus the target window (default: 3)')
    ap.add_argument('--interval', type=float, default=0.02, metavar='SECS',
                    help='Per-keystroke delay for STRING (default: 0.02)')
    ap.add_argument('--layout', default='us',
                    help='Keyboard layout for the dry-run preview (default: us)')
    args = ap.parse_args()

    if not os.path.exists(args.payload):
        print(f'Error: file not found: {args.payload}')
        sys.exit(1)

    text = open(args.payload, 'r').read()

    # Validate syntax up front so errors surface before any typing.
    try:
        parse(text)
    except Exception as e:
        print(f'Syntax error: {e}')
        sys.exit(1)

    if args.dry_run:
        print(f"\n--- Dry run: {args.payload} (layout {args.layout}) ---")
        backend = PyAutoGUIBackend(dry_run=True)
        interp = Interpreter(backend)
        backend.set_layout(args.layout)
        interp.run(text)
        backend._flush()
        print('--- End ---')
    else:
        print(f'\nSwitch focus to the target window. Executing in {args.delay}s...')
        for i in range(args.delay, 0, -1):
            print(f'  {i}...')
            time.sleep(1)
        print('Running payload.')
        interp = Interpreter(PyAutoGUIBackend(dry_run=False, interval=args.interval))
        interp.run(text)
        print('Done.')

    if interp.warnings:
        print(f'\n{len(interp.warnings)} warning(s):')
        for w in interp.warnings[:20]:
            print(f'  ! {w}')
    if interp.skipped_chars:
        print(f'{interp.skipped_chars} character(s) had no mapping in layout {args.layout!r}.')


if __name__ == '__main__':
    main()
