"""
Parsers for external tool output: hcitool, sdptool, bettercap.
Pure text processing — no hardware or async dependencies.
"""

import re

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
_MAC_RE = re.compile(r'([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})')

# Bluetooth Class of Device -> major device class label (bits 8-12 of the CoD)
_COD_MAJOR = {
    0: 'Miscellaneous', 1: 'Computer', 2: 'Phone', 3: 'Network',
    4: 'Audio/Video', 5: 'Peripheral', 6: 'Imaging', 7: 'Wearable',
    8: 'Toy', 9: 'Health',
}


def cod_major(cod):
    """Map a Class of Device hex value to a major device class label."""
    try:
        val = int(cod, 16)
    except (TypeError, ValueError):
        return 'Unknown'
    return _COD_MAJOR.get((val >> 8) & 0x1F, 'Unknown')


def parse_hci_inq(output):
    """Parse hcitool inq output into a list of device dicts."""
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith('Inquiring'):
            continue
        m = _MAC_RE.search(line)
        if not m:
            continue
        d = {'mac': m.group(1).upper(), 'name': None, 'rssi': None}
        cm = re.search(r'class:\s*(0x[0-9a-fA-F]+)', line)
        if cm:
            d['type'] = cod_major(cm.group(1))
        else:
            d['type'] = 'Unknown'
        devices.append(d)
    return devices


def parse_sdptool(output):
    """Parse sdptool browse output into structured service records."""
    services = []
    cur = None
    in_list = None  # current list key: 'classes', 'protocols', 'profiles'

    for raw in output.splitlines():
        line = raw.rstrip()

        if line.startswith('Service Name:') or line.startswith('Service Provider:'):
            if cur is None:
                cur = {'name': None, 'protocol': None, 'channel': None,
                       'service_classes': [], 'profiles': []}
            val = line.split(':', 1)[1].strip()
            if val and line.startswith('Service Name:'):
                cur['name'] = val
            continue

        if line.startswith('Service RecHandle:'):
            if cur is not None:
                services.append(cur)
            cur = {'name': None, 'protocol': None, 'channel': None,
                   'service_classes': [], 'profiles': []}
            in_list = None
            continue

        if cur is None:
            continue

        if line.startswith('Service Class ID List:'):
            in_list = 'classes'
            continue
        if line.startswith('Protocol Descriptor List:'):
            in_list = 'protocols'
            continue
        if line.startswith('Profile Descriptor List:'):
            in_list = 'profiles'
            continue

        stripped = line.lstrip()
        if not stripped:
            in_list = None
            continue

        if in_list == 'classes':
            m = re.match(r'"([^"]+)"\s*\(0x[0-9a-fA-F]+\)', stripped)
            if m:
                cur['service_classes'].append(m.group(1))

        elif in_list == 'protocols':
            m = re.match(r'"([^"]+)"\s*\(0x[0-9a-fA-F]+\)', stripped)
            if m:
                cur['protocol'] = m.group(1)
            if stripped.startswith('Channel:'):
                try:
                    cur['channel'] = int(stripped.split(':')[1].strip())
                except (ValueError, IndexError):
                    pass

        elif in_list == 'profiles':
            m = re.match(r'"([^"]+)"\s*\(0x[0-9a-fA-F]+\)', stripped)
            if m:
                cur['profiles'].append(m.group(1))

    if cur is not None:
        services.append(cur)
    return services


def parse_bettercap_ble(output):
    """Parse bettercap BLE scan output into a list of device dicts."""
    devices = []
    idx = None
    for raw in output.splitlines():
        line = _ANSI_RE.sub('', raw).replace(chr(0x2502), '|')
        if '|' not in line:
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if not cells:
            continue
        upper = [c.upper() for c in cells]
        if idx is None:
            if any('RSSI' in c for c in upper) and any('MAC' in c for c in upper):
                idx = {
                    'rssi': next((i for i, c in enumerate(upper) if 'RSSI' in c), 0),
                    'mac': next((i for i, c in enumerate(upper) if c == 'MAC'), 0),
                    'vendor': next((i for i, c in enumerate(upper) if c == 'VENDOR'), None),
                    'name': next((i for i, c in enumerate(upper) if c == 'NAME'), None),
                    'connect': next((i for i, c in enumerate(upper) if c == 'CONNECT'), None),
                }
            continue
        if idx['mac'] >= len(cells):
            continue
        mac = cells[idx['mac']]
        if not mac or ':' not in mac:
            continue
        rssi = None
        ri = idx['rssi']
        if ri < len(cells) and cells[ri]:
            try:
                rssi = int(cells[ri].split()[0])
            except (ValueError, IndexError):
                pass
        vendor = cells[idx['vendor']] if (idx['vendor'] is not None and idx['vendor'] < len(cells)) else None
        name = cells[idx['name']] if (idx['name'] is not None and idx['name'] < len(cells)) else None
        connect = cells[idx['connect']] if (idx['connect'] is not None and idx['connect'] < len(cells)) else ''
        devices.append({
            'mac': mac.upper(),
            'name': name or 'Unknown',
            'rssi': rssi,
            'vendor': vendor or None,
            'connectable': connect.strip().lower() in ('true', 'yes', '✓', '✔'),
        })
    return devices
