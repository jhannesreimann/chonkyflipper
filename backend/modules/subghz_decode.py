#!/usr/bin/env python3
"""
Sub-1GHz OOK protocol decoder.

Turns a captured pulse train ([[level, microseconds], ...]) into bits and
identifies common fixed-code protocols (EV1527, PT2262, HT12E) and KeeLoq
rolling-code transmissions.

Most 433 MHz remotes use PWM: each bit is a high/low pulse pair whose long/short
arrangement is the bit value (long-high + short-low = 1, short-high + long-low
= 0). Frames repeat several times per press, separated by a long sync gap. The
decoder segments on that gap, decodes each frame, then majority-votes the
repeated frames so a one-off noise frame cannot masquerade as the code.
"""

from collections import Counter

# Longest plausible fixed/rolling-code frame; anything longer is noise/FSK
# force-decoded as PWM, not a real code.
MAX_CODE_BITS = 80


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _frame_to_bits(frame, te):
    # Decode consecutive high/low pairs into bits. te is unused for the ratio
    # test (we compare the two halves directly) but kept for future tolerance
    # tuning.
    bits = []
    k, n = 0, len(frame)
    while k < n and frame[k][0] != 1:  # align to the first carrier-on pulse
        k += 1
    while k + 1 < n:
        hi, lo = frame[k], frame[k + 1]
        if hi[0] == 1 and lo[0] == 0:
            bits.append('1' if hi[1] > lo[1] else '0')
            k += 2
        else:
            k += 1  # skip a misaligned pulse and resync
    return ''.join(bits)


def _classify(nbits):
    if 62 <= nbits <= 70:
        return 'KeeLoq (rolling code)', 'rolling'
    if nbits == 24:
        return 'EV1527 / PT2262 (24-bit)', 'fixed'
    if nbits == 12:
        return 'HT12E / PT2262 (12-bit)', 'fixed'
    if 20 <= nbits <= 28:
        return 'Fixed-code PWM ({}-bit)'.format(nbits), 'fixed'
    return 'Unknown ({}-bit)'.format(nbits), 'unknown'


def decode_pulses(pulses, min_bits=8):
    if not pulses or len(pulses) < 4:
        return {'decoded': False, 'reason': 'Not enough pulse data to decode.'}

    durs = [d for _, d in pulses if d > 0]
    if not durs:
        return {'decoded': False, 'reason': 'No pulse timing to work with.'}

    # Estimate the base bit period Te from the short-pulse cluster.
    med = _median(durs)
    shorts = [d for d in durs if d <= med] or durs
    te = _median(shorts) or med

    # A low pulse far longer than a bit period is the inter-frame sync gap.
    sync_thresh = max(te * 6, 1500)
    frames, cur = [], []
    for lv, d in pulses:
        if lv == 0 and d >= sync_thresh:
            if cur:
                frames.append(cur)
                cur = []
        else:
            cur.append([lv, d])
    if cur:
        frames.append(cur)

    decoded = [b for b in (_frame_to_bits(f, te) for f in frames) if len(b) >= min_bits]
    if not decoded:
        return {
            'decoded': False,
            'reason': 'No PWM frames found -- signal may be FSK, Manchester, or noise.',
            'frames': len(frames), 'te_us': round(te),
        }

    # Prefer the longest SANE frame length that repeats, so a KeeLoq data frame
    # wins over its short preamble while absurd lengths (noise force-decoded as
    # PWM) are ignored. Real fixed/rolling codes are at most ~66 bits.
    by_len = {}
    for b in decoded:
        by_len.setdefault(len(b), []).append(b)
    repeated = [L for L, v in by_len.items() if len(v) >= 2]
    candidates = repeated or list(by_len.keys())
    sane = [L for L in candidates if L <= MAX_CODE_BITS]
    if not sane:
        longest = max(candidates)
        return {
            'decoded': False,
            'reason': 'Decoded {} bits -- too long for a fixed/rolling code frame; '
                      'likely FSK, Manchester, or noise.'.format(longest),
            'frames': len(decoded), 'te_us': round(te),
        }
    target_len = max(sane)
    group = by_len[target_len]
    best, agree = Counter(group).most_common(1)[0]

    proto, kind = _classify(len(best))
    value = int(best, 2) if best else 0
    confidence = 'high' if agree >= 3 else ('medium' if agree >= 2 else 'low')

    return {
        'decoded': True,
        'protocol': proto,
        'code_type': kind,
        'bits': len(best),
        'binary': best,
        'hex': '0x{:X}'.format(value),
        'te_us': round(te),
        'frames': len(decoded),
        'repeats_agree': agree,
        'confidence': confidence,
    }


if __name__ == '__main__':
    # Standalone tester: python3 subghz_decode.py <signal.json>
    import json, sys
    with open(sys.argv[1]) as f:
        data = json.load(f)
    print(json.dumps(decode_pulses(data.get('pulses', [])), indent=2))
