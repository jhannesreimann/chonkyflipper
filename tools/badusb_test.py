#!/usr/bin/env python3
"""
BadUSB payload tester — runs DuckyScript payloads via local keyboard automation.
Use --dry-run to preview without typing anything.

On the Pi, swap PyAutoGUI calls for writes to /dev/hidg0.
"""

import argparse
import os
import sys
import time

try:
    import pyautogui
    pyautogui.FAILSAFE = True
except ImportError:
    print("Error: pyautogui not installed.  Run: pip install pyautogui")
    sys.exit(1)

# DuckyScript token -> pyautogui key name
KEY_MAP = {
    "ENTER": "enter", "RETURN": "enter",
    "SPACE": "space", "TAB": "tab",
    "BACKSPACE": "backspace", "DELETE": "delete", "DEL": "delete",
    "ESCAPE": "escape", "ESC": "escape",
    "UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right",
    "HOME": "home", "END": "end",
    "PAGEUP": "pageup", "PAGEDOWN": "pagedown",
    "INSERT": "insert", "PRINTSCREEN": "printscreen",
    "CAPSLOCK": "capslock", "NUMLOCK": "numlock",
    "PAUSE": "pause", "BREAK": "pause",
    "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4",
    "F5": "f5", "F6": "f6", "F7": "f7", "F8": "f8",
    "F9": "f9", "F10": "f10", "F11": "f11", "F12": "f12",
}

MODIFIER_MAP = {
    "CTRL": "ctrl", "CONTROL": "ctrl",
    "SHIFT": "shift",
    "ALT": "alt",
    "GUI": "win", "WINDOWS": "win", "COMMAND": "win", "META": "win",
}


def parse_payload(path):
    commands = []
    with open(path, "r") as f:
        for line_num, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.upper().startswith("REM"):
                continue
            parts = line.split(" ", 1)
            cmd = parts[0].upper()
            args = parts[1] if len(parts) > 1 else ""
            commands.append((cmd, args, line_num))
    return commands


def execute(commands, dry_run=False, interval=0.05):
    for cmd, args, line_num in commands:

        if cmd == "STRING":
            if dry_run:
                print(f"  [{line_num:>3}] TYPE   {repr(args)}")
            else:
                pyautogui.write(args, interval=interval)

        elif cmd == "DELAY":
            ms = int(args) if args.strip().isdigit() else 500
            if dry_run:
                print(f"  [{line_num:>3}] WAIT   {ms}ms")
            else:
                time.sleep(ms / 1000)

        elif cmd in MODIFIER_MAP and args:
            # e.g. "GUI r", "CTRL SHIFT ESC", "ALT F4"
            mod = MODIFIER_MAP[cmd]
            rest = [KEY_MAP.get(t.upper(), t.lower()) for t in args.split()]
            combo = [mod] + rest
            if dry_run:
                print(f"  [{line_num:>3}] COMBO  {' + '.join(combo)}")
            else:
                pyautogui.hotkey(*combo)

        elif cmd in KEY_MAP:
            if dry_run:
                print(f"  [{line_num:>3}] KEY    {KEY_MAP[cmd]}")
            else:
                pyautogui.press(KEY_MAP[cmd])

        elif cmd in MODIFIER_MAP and not args:
            # bare modifier key press (uncommon but valid)
            key = MODIFIER_MAP[cmd]
            if dry_run:
                print(f"  [{line_num:>3}] KEY    {key}")
            else:
                pyautogui.press(key)

        else:
            print(f"  [{line_num:>3}] WARN   unknown command: {cmd!r}")


def main():
    ap = argparse.ArgumentParser(
        description="Run a DuckyScript payload using local keyboard automation."
    )
    ap.add_argument("payload", help="Path to payload .txt file")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be typed without touching the keyboard"
    )
    ap.add_argument(
        "--delay", type=int, default=3, metavar="SECS",
        help="Startup delay in seconds — time to focus the target window (default: 3)"
    )
    ap.add_argument(
        "--interval", type=float, default=0.05, metavar="SECS",
        help="Delay between keystrokes for STRING commands (default: 0.05)"
    )
    args = ap.parse_args()

    if not os.path.exists(args.payload):
        print(f"Error: file not found: {args.payload}")
        sys.exit(1)

    commands = parse_payload(args.payload)
    print(f"Loaded {len(commands)} commands from '{args.payload}'")

    if args.dry_run:
        print("\n--- Dry run (no keyboard input) ---")
        execute(commands, dry_run=True)
        print("--- End ---")
        return

    print(f"\nSwitch focus to the target window. Executing in {args.delay}s...")
    for i in range(args.delay, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    print("Running payload.")
    execute(commands, dry_run=False, interval=args.interval)
    print("Done.")


if __name__ == "__main__":
    main()
