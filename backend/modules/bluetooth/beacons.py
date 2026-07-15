"""
Beacon parsing and encoding for iBeacon and Eddystone protocols.
Pure data transformations — no hardware or async dependencies.
"""

import struct

# Eddystone service UUID (16-bit 0xFEAA in full 128-bit form)
EDDYSTONE_UUID = '0000feaa-0000-1000-8000-00805f9b34fb'
# Company identifier Apple uses for iBeacon manufacturer data
APPLE_COMPANY_ID = 0x004C

# Eddystone-URL scheme prefixes and expansion codes (Eddystone spec)
URL_SCHEMES = ['http://www.', 'https://www.', 'http://', 'https://']
URL_EXPANSIONS = [
    '.com/', '.org/', '.edu/', '.net/', '.info/', '.biz/', '.gov/',
    '.com', '.org', '.edu', '.net', '.info', '.biz', '.gov',
]


def parse_ibeacon(adv):
    """Extract iBeacon fields from a Bleak advertisement's manufacturer_data."""
    data = adv.manufacturer_data.get(APPLE_COMPANY_ID)
    if not data or len(data) < 23 or data[0] != 0x02 or data[1] != 0x15:
        return None
    u = data[2:18].hex()
    uuid = f'{u[0:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:32]}'
    return {
        'type': 'iBeacon',
        'uuid': uuid,
        'major': int.from_bytes(data[18:20], 'big'),
        'minor': int.from_bytes(data[20:22], 'big'),
        'tx_power': struct.unpack('b', data[22:23])[0],
    }


def parse_eddystone(adv):
    """Extract Eddystone frame fields from a Bleak advertisement's service_data."""
    data = adv.service_data.get(EDDYSTONE_UUID)
    if not data:
        return None
    frame = data[0]
    if frame == 0x00 and len(data) >= 18:  # UID frame
        namespace = data[2:12].hex()
        instance = data[12:18].hex()
        return {'type': 'Eddystone-UID', 'namespace': namespace,
                'instance': instance, 'id': namespace + instance}
    if frame == 0x10:  # URL frame
        return {'type': 'Eddystone-URL', 'id': decode_eddystone_url(data)}
    if frame == 0x20:  # TLM (telemetry) frame
        return {'type': 'Eddystone-TLM'}
    return {'type': 'Eddystone'}


def decode_eddystone_url(data):
    """Decode an Eddystone-URL frame's URL from the raw service_data bytes."""
    if len(data) < 3:
        return None
    scheme = data[2]
    url = URL_SCHEMES[scheme] if scheme < len(URL_SCHEMES) else ''
    for b in data[3:]:
        url += URL_EXPANSIONS[b] if b < len(URL_EXPANSIONS) else chr(b)
    return url


def encode_eddystone_url(url):
    """Encode a URL string into Eddystone-URL hex bytes (without the TX power byte).
    Returns (hex_string, error_message)."""
    if not url:
        return None, 'Eddystone-URL requires a url'
    scheme = None
    rest = url
    for i, prefix in enumerate(URL_SCHEMES):
        if url.startswith(prefix):
            scheme, rest = i, url[len(prefix):]
            break
    if scheme is None:
        return None, 'url must start with http(s):// (optionally www.)'
    out = f'{scheme:02x}'
    i = 0
    while i < len(rest):
        for code, exp in enumerate(URL_EXPANSIONS):
            if rest.startswith(exp, i):
                out += f'{code:02x}'
                i += len(exp)
                break
        else:
            out += f'{ord(rest[i]):02x}'
            i += 1
    return out, None
