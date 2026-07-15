#!/usr/bin/env python3
"""
IR Protocol Encoders and Decoders.
Encodes address/command pairs into pulse/space timing arrays for transmission.
"""


# Protocol Registry

PROTOCOL_REGISTRY = {}


def register(name, carrier=38000):
    """Decorator to register a protocol encoder."""
    def wrapper(fn):
        PROTOCOL_REGISTRY[name] = {'encode': fn, 'carrier': carrier}
        return fn
    return wrapper


def encode(protocol, **params):
    """Dispatch to the right encoder. Returns (pulses, spaces) or (None, error)."""
    if protocol not in PROTOCOL_REGISTRY:
        return None, f'Unknown protocol: {protocol}'
    try:
        return PROTOCOL_REGISTRY[protocol]['encode'](**params), None
    except Exception as e:
        return None, str(e)


def list_protocols():
    """Return list of supported protocol names."""
    return sorted(PROTOCOL_REGISTRY.keys())


# NEC Protocol

@register('NEC', carrier=38000)
def encode_nec(address, command, header_pulse=9000, header_space=4500,
               unit_pulse=560, unit_space_0=560, unit_space_1=1690,
               samsung32=False):
    """
    Build NEC protocol pulse and space arrays.
    Standard NEC: 9000us header, 32 bits (addr + ~addr + cmd + ~cmd).
    Samsung32 variant: 4500us header, 32 bits (addr + addr + cmd + ~cmd).
    Returns (pulses, spaces) lists in microseconds.
    """
    pulses = [header_pulse]
    spaces = [header_space]

    if samsung32:
        data = [
            address & 0xFF,
            address & 0xFF,
            command & 0xFF,
            (~command) & 0xFF
        ]
    else:
        data = [
            address & 0xFF,
            (~address) & 0xFF,
            command & 0xFF,
            (~command) & 0xFF
        ]

    for byte in data:
        for bit_pos in range(8):
            pulses.append(unit_pulse)
            if byte & (1 << bit_pos):
                spaces.append(unit_space_1)
            else:
                spaces.append(unit_space_0)

    pulses.append(unit_pulse)  # trailing pulse
    return pulses, spaces


# Panasonic Kaseikyo Protocol

# Standard Panasonic projector timings (from Flipper-IRDB captures):
#   Carrier: 38 kHz (though some docs say 37 kHz)
#   Leader:  ~3450 us mark, ~1750 us space
#   Bit 0:   ~430 us mark, ~430 us space
#   Bit 1:   ~430 us mark, ~1300 us space
#   Frame:   48 bits (16-bit address + 32-bit data)

PANASONIC_ADDRESS = 0x4004  # 16388, standard for Panasonic AV devices

@register('Panasonic', carrier=38000)
def encode_panasonic(address=PANASONIC_ADDRESS, command=0,
                     header_pulse=3450, header_space=1750,
                     unit_pulse=430, unit_space_0=430, unit_space_1=1300):
    """
    Encode Panasonic Kaseikyo 48-bit protocol.
    address: 16-bit device address (default 0x4004 for Panasonic projectors)
    command: 32-bit command code
    Returns (pulses, spaces) in microseconds.
    """
    pulses = [header_pulse]
    spaces = [header_space]

    # 16-bit address (LSB first), then 32-bit command (LSB first)
    for shift in range(0, 16, 8):
        byte = (address >> shift) & 0xFF
        for bit_pos in range(8):
            pulses.append(unit_pulse)
            if byte & (1 << bit_pos):
                spaces.append(unit_space_1)
            else:
                spaces.append(unit_space_0)

    for shift in range(0, 32, 8):
        byte = (command >> shift) & 0xFF
        for bit_pos in range(8):
            pulses.append(unit_pulse)
            if byte & (1 << bit_pos):
                spaces.append(unit_space_1)
            else:
                spaces.append(unit_space_0)

    pulses.append(unit_pulse)  # trailing pulse
    return pulses, spaces


# Sony SIRC Protocol

# Carrier: 40 kHz
# Header:  2400 us pulse, 600 us space
# Bit 0:   600 us pulse, 600 us space
# Bit 1:   600 us pulse, 1200 us space
# 12-bit:  5-bit address + 7-bit command
# 15-bit:  8-bit address + 7-bit command
# 20-bit:  5-bit address + 8-bit extended + 7-bit command

@register('Sony12', carrier=40000)
def encode_sony_12(command, address=0):
    return _encode_sony(command, address, 12)

@register('Sony15', carrier=40000)
def encode_sony_15(command, address=0):
    return _encode_sony(command, address, 15)

@register('Sony20', carrier=40000)
def encode_sony_20(command, address=0):
    return _encode_sony(command, address, 20)


def _encode_sony(command, address, bits,
                 header_pulse=2400, header_space=600,
                 unit_pulse=600, unit_space_0=600, unit_space_1=1200):
    """Encode Sony SIRC protocol (generic bit length)."""
    pulses = [header_pulse]
    spaces = [header_space]

    data = command & 0x7F  # 7-bit command
    if bits >= 12:
        data |= (address & 0x1F) << 7   # 5-bit address for 12/20-bit
    if bits >= 15:
        data |= (address & 0xFF) << 7   # 8-bit address for 15-bit
    if bits >= 20:
        data |= ((address >> 5) & 0xFF) << 12  # 5-bit extended

    for bit_pos in range(bits):
        pulses.append(unit_pulse)
        if data & (1 << bit_pos):
            spaces.append(unit_space_1)
        else:
            spaces.append(unit_space_0)

    pulses.append(unit_pulse)  # trailing pulse
    return pulses, spaces


# RC5 Protocol

# Carrier: 36 kHz
# Manchester encoding at 889 us per half-bit (1778 us per bit)
# 14 bits: 2 start bits + 1 toggle + 5 address + 6 command

@register('RC5', carrier=36000)
def encode_rc5(address, command, toggle=0,
               half_bit=889):
    """
    Encode RC5 protocol (14-bit, Manchester).
    Start bits: S1=1, S2=1
    Toggle bit: T
    Address: 5 bits (0-31)
    Command: 6 bits (0-63)
    Returns (pulses, spaces) in microseconds.
    """
    pulses = []
    spaces = []

    # Build 14-bit frame: S1=1, S2=1, T, A4..A0, C5..C0
    frame = (1 << 13) | (1 << 12)  # start bits
    frame |= (toggle & 1) << 11
    frame |= (address & 0x1F) << 6
    frame |= command & 0x3F

    def add_bit(bit):
        """Manchester: 1 = space then pulse, 0 = pulse then space."""
        if bit:
            spaces.append(half_bit)
            pulses.append(half_bit)
        else:
            pulses.append(half_bit)
            spaces.append(half_bit)

    for i in range(13, -1, -1):
        add_bit((frame >> i) & 1)

    return pulses, spaces


# Protocol Aliases (Flipper-IRDB naming conventions)

@register('Samsung32', carrier=38000)
def encode_samsung32(address, command):
    """Samsung32 is NEC with 4500us header and non-inverted address byte."""
    return encode_nec(address, command, header_pulse=4500, samsung32=True)

@register('SIRC20', carrier=40000)
def encode_sirc20(command, address=0):
    """SIRC20 is Sony SIRC 20-bit variant (Flipper-IRDB naming)."""
    return encode_sony_20(command, address)

@register('NECext', carrier=38000)
def encode_necext(address, command):
    """NECext is standard NEC with extended addressing (timing idential to NEC)."""
    return encode_nec(address, command)

# Raw Passthrough

@register('Kaseikyo', carrier=38000)
def encode_kaseikyo(address=0, command=0):
    """Kaseikyo is Panasonic's 48-bit protocol family.
    Flipper-IRDB stores 4-byte address + 4-byte command, but the frame is
    16-bit vendor code (upper 16 bits of address) + 32-bit data (command,
    byte-reversed because _parse_hex_bytes is little-endian)."""
    vendor = (address >> 16) & 0xFFFF
    # Byte-reverse the 32-bit command: 0xD1030000 -> 0x000003D1
    cmd = ((command & 0xFF) << 24) | ((command & 0xFF00) << 8) | \
          ((command >> 8) & 0xFF00) | ((command >> 24) & 0xFF)
    return encode_panasonic(address=vendor, command=cmd)

@register('SIRC', carrier=40000)
def encode_sirc(command, address=0):
    """SIRC is Sony SIRC 12-bit (Flipper-IRDB naming)."""
    return encode_sony_12(command, address)

@register('SIRC15', carrier=40000)
def encode_sirc15(command, address=0):
    """SIRC15 is Sony SIRC 15-bit (Flipper-IRDB naming)."""
    return encode_sony_15(command, address)

@register('raw', carrier=38000)
def encode_raw(pulses, spaces=None, frequency=38000):
    """Pass through raw pulse/space arrays unchanged. Returns (pulses, spaces)."""
    return list(pulses), list(spaces) if spaces else []


# Protocol Detection (for recorded signals)

def detect_protocol(pulses, spaces=None):
    """
    Detect IR protocol from raw pulse/space timing data.
    Returns dict with name, confidence, address, command.
    """
    if not pulses or len(pulses) < 4:
        return {'name': 'unknown', 'confidence': 0}

    # NEC: 9000us header pulse, 4500us header space
    if spaces and 8500 < pulses[0] < 9500 and 4000 < spaces[0] < 5000:
        result = _decode_nec(pulses, spaces)
        if result['confidence'] > 0.5:
            return result

    # Panasonic Kaseikyo: ~3450us header pulse, ~1750us header space, 48 bits
    if spaces and 3000 < pulses[0] < 4000 and 1500 < spaces[0] < 2000:
        result = _decode_panasonic(pulses, spaces)
        if result['confidence'] > 0.5:
            return result

    # Sony SIRC: 2400us header pulse, 600us header space
    if spaces and 2000 < pulses[0] < 2800 and 500 < spaces[0] < 700:
        result = _decode_sony(pulses, spaces)
        if result['confidence'] > 0.5:
            return result

    # RC5: ~889us first pulse (Manchester, no distinct header)
    if 800 < pulses[0] < 1000:
        return {'name': 'RC5 (likely)', 'confidence': 0.5}

    # Generic fallback
    if pulses[0] > 8000:
        return {'name': 'NEC-like', 'confidence': 0.3}
    elif pulses[0] > 2000:
        return {'name': 'Sony-like', 'confidence': 0.3}

    return {'name': 'raw', 'confidence': 0.1}


def _decode_nec(pulses, spaces):
    """Decode NEC protocol from pulse/space timings."""
    result = {'name': 'NEC', 'confidence': 0}
    if len(pulses) < 34 or len(spaces) < 33:
        return {'name': 'NEC (incomplete)', 'confidence': 0.3}

    bits = []
    for i in range(1, min(34, min(len(pulses), len(spaces) + 1))):
        p = pulses[i] if i < len(pulses) else 0
        s = spaces[i] if i < len(spaces) else 0
        if 400 < p < 700 and 400 < s < 700:
            bits.append(0)
        elif 400 < p < 700 and 1400 < s < 2000:
            bits.append(1)
        else:
            bits.append(None)

    valid = sum(1 for b in bits if b is not None)
    if valid < 16:
        return {'name': 'NEC (noisy)', 'confidence': 0.3}

    confidence = valid / len(bits) if bits else 0

    if len(bits) >= 32:
        addr = sum((bits[i] or 0) << i for i in range(8))
        cmd = sum((bits[i] or 0) << (i - 16) for i in range(16, 24))
        result['address'] = addr
        result['command'] = cmd
        result['address_hex'] = f'0x{addr:02X}'
        result['command_hex'] = f'0x{cmd:02X}'

    result['confidence'] = confidence
    return result


def _decode_sony(pulses, spaces):
    """Decode Sony SIRC protocol."""
    result = {'name': 'Sony SIRC', 'confidence': 0}
    bits = []
    for i in range(1, min(len(pulses), len(spaces) + 1)):
        p = pulses[i] if i < len(pulses) else 0
        s = spaces[i] if i < len(spaces) else 0
        if 400 < p < 800 and 400 < s < 800:
            bits.append(0)
        elif 400 < p < 800 and 1000 < s < 1400:
            bits.append(1)
        else:
            bits.append(None)

    valid = sum(1 for b in bits if b is not None)
    if valid < 8:
        return {'name': 'Sony (noisy)', 'confidence': 0.3}

    result['confidence'] = valid / len(bits) if bits else 0

    if len(bits) >= 12:
        cmd = sum((bits[i] or 0) << i for i in range(7))
        addr = sum((bits[i] or 0) << (i - 7) for i in range(7, min(12, len(bits))))
        result['command'] = cmd
        result['address'] = addr

    return result


def _decode_panasonic(pulses, spaces):
    """Decode Panasonic Kaseikyo protocol (48-bit)."""
    result = {'name': 'Panasonic', 'confidence': 0}
    if len(pulses) < 48 or len(spaces) < 47:
        return {'name': 'Panasonic (short)', 'confidence': 0.3}

    bits = []
    for i in range(1, min(49, min(len(pulses), len(spaces) + 1))):
        p = pulses[i] if i < len(pulses) else 0
        s = spaces[i] if i < len(spaces) else 0
        if 350 < p < 550 and 350 < s < 550:
            bits.append(0)
        elif 350 < p < 550 and 1100 < s < 1500:
            bits.append(1)
        else:
            bits.append(None)

    valid = sum(1 for b in bits if b is not None)
    if valid < 24:
        return {'name': 'Panasonic (noisy)', 'confidence': 0.3}

    confidence = valid / max(len(bits), 1)

    if len(bits) >= 48:
        addr = 0
        for i in range(16):
            if bits[i] is not None:
                addr |= bits[i] << i
        cmd = 0
        for i in range(16, min(48, len(bits))):
            if bits[i] is not None:
                cmd |= bits[i] << (i - 16)
        result['address'] = addr
        result['command'] = cmd
        result['address_hex'] = f'0x{addr:04X}'
        result['command_hex'] = f'0x{cmd:08X}'

    result['confidence'] = confidence
    return result
