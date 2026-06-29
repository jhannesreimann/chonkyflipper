#!/usr/bin/env python3
"""
Background BLE advertisement logger.  Runs as a detached subprocess, continuously
collecting advertisement sightings and writing a JSON summary file every few seconds.
Killed with SIGTERM when the user stops logging.

Start:  python3 ble-advert-logger.py <state_file.json> <pid_file>
Stop:   kill $(cat <pid_file>)
"""

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone

try:
    from bleak import BleakScanner
except ImportError:
    print('bleak is not installed', file=sys.stderr)
    sys.exit(1)

STATE_FILE = sys.argv[1] if len(sys.argv) > 1 else '/tmp/ble-advert-log.json'
PID_FILE = sys.argv[2] if len(sys.argv) > 2 else '/tmp/ble-advert-log.pid'

# Eddystone service UUID (16-bit 0xFEAA in full 128-bit form)
_EDDYSTONE_UUID = '0000feaa-0000-1000-8000-00805f9b34fb'
_APPLE_COMPANY_ID = 0x004C

_URL_SCHEMES = ['http://www.', 'https://www.', 'http://', 'https://']
_URL_EXPANSIONS = [
    '.com/', '.org/', '.edu/', '.net/', '.info/', '.biz/', '.gov/',
    '.com', '.org', '.edu', '.net', '.info', '.biz', '.gov',
]


def parse_ibeacon(adv):
    data = adv.manufacturer_data.get(_APPLE_COMPANY_ID)
    if not data or len(data) < 23 or data[0] != 0x02 or data[1] != 0x15:
        return None
    u = data[2:18].hex()
    uuid = f'{u[0:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:32]}'
    return {
        'type': 'iBeacon',
        'uuid': uuid,
        'major': int.from_bytes(data[18:20], 'big'),
        'minor': int.from_bytes(data[20:22], 'big'),
    }


def parse_eddystone(adv):
    data = adv.service_data.get(_EDDYSTONE_UUID)
    if not data:
        return None
    frame = data[0]
    if frame == 0x00 and len(data) >= 18:
        ns = data[2:12].hex()
        inst = data[12:18].hex()
        return {'type': 'Eddystone-UID', 'namespace': ns, 'instance': inst}
    if frame == 0x10:
        return {'type': 'Eddystone-URL'}
    if frame == 0x20:
        return {'type': 'Eddystone-TLM'}
    return {'type': 'Eddystone'}


def write_state(summary, started_at):
    """Atomically write the current summary to the state file."""
    devices = sorted(summary.values(), key=lambda d: d['count'], reverse=True)
    total = sum(d['count'] for d in devices)
    payload = {
        'running': True,
        'started_at': started_at.isoformat(),
        'total_sightings': total,
        'device_count': len(devices),
        'devices': devices,
    }
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(payload, f)
    os.replace(tmp, STATE_FILE)


async def main():
    summary = {}
    started_at = datetime.now(timezone.utc)

    def on_advert(device, adv):
        mac = device.address.upper()
        name = adv.local_name or device.name or 'Unknown'
        rssi = adv.rssi
        beacon = parse_ibeacon(adv) or parse_eddystone(adv)
        btype = beacon['type'] if beacon else None
        ts = datetime.now(timezone.utc).isoformat()

        d = summary.get(mac)
        if d is None:
            d = summary[mac] = {
                'mac': mac, 'name': name, 'beacon': btype, 'count': 0,
                'rssi_last': None, 'rssi_min': None, 'rssi_max': None,
                'first_seen': ts, 'last_seen': ts,
            }
        d['count'] += 1
        d['last_seen'] = ts
        if name != 'Unknown':
            d['name'] = name
        if btype and not d['beacon']:
            d['beacon'] = btype
        if rssi is not None:
            d['rssi_last'] = rssi
            d['rssi_min'] = rssi if d['rssi_min'] is None else min(d['rssi_min'], rssi)
            d['rssi_max'] = rssi if d['rssi_max'] is None else max(d['rssi_max'], rssi)

    scanner = BleakScanner(detection_callback=on_advert, adapter='hci0')

    # Write PID file so the backend can manage us.
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    await scanner.start()

    # Periodically flush state to disk.
    async def flush_loop():
        while True:
            await asyncio.sleep(3)
            write_state(summary, started_at)

    flush_task = asyncio.create_task(flush_loop())

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)
    loop.add_signal_handler(signal.SIGINT, stop_event.set)

    await stop_event.wait()

    flush_task.cancel()
    try:
        await flush_task
    except asyncio.CancelledError:
        pass

    await scanner.stop()
    write_state(summary, started_at)

    try:
        os.remove(PID_FILE)
    except OSError:
        pass


if __name__ == '__main__':
    asyncio.run(main())
