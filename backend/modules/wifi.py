#!/usr/bin/env python3
"""
WiFi Module - Controls Alfa AWUS036ACS (RTL8811AU)
Monitor mode, packet capture, and wifite-based vulnerability auditing.
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

    # Scanning (enriched with risk and encryption details)

    def scan_networks(self):
        """Scan for WiFi networks using wpa_cli on wlan1. Returns list with risk and encryption."""
        if not os.path.exists('/sys/class/net/wlan1'):
            return None

        # wpa_cli scanning needs managed mode. A prior monitor session or a
        # wifite attack leaves wlan1 in monitor mode, which would make every
        # scan come back empty - so transparently restore managed mode first.
        if self._is_monitor_mode():
            self.stop_monitor_mode()
            time.sleep(2)

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

    # Monitor mode & packet capture

    def start_monitor_mode(self):
        """
        Enter monitor mode on wlan1 using iw (no airmon-ng).
        airmon-ng check kill would kill gunicorn+hostapd - avoided.
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
        """Return wlan1 to managed mode and restart WiFi client if needed.

        Uses ip link + iw (not ifconfig) for the rtl8821au driver.  ifconfig
        corrupts the driver state and causes "Invalid HW-addr family 0x0323"
        when wpa_supplicant tries to init the interface.
        """
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
        # The rtl8821au driver sometimes leaves the PROMISC flag set after
        # switching out of monitor mode, which silently breaks wpa_cli
        # scanning.  Explicitly clear it.
        subprocess.run(
            ['sudo', '-n', 'ip', 'link', 'set', self.interface, 'promisc', 'off'],
            capture_output=True,
        )
        subprocess.run(
            ['sudo', '-n', 'systemctl', 'restart', 'wpa_supplicant@wlan1'],
            capture_output=True,
        )
        return {'success': True, 'interface': self.interface}

    def _is_monitor_mode(self):
        """Return True if wlan1 is in monitor mode or has the PROMISC flag set.

        The rtl8821au driver can get stuck with PROMISC on even after
        iwconfig reports Mode:Managed - scanning is broken in that state
        too, so treat it as monitor-like.
        """
        result = subprocess.run(
            ['iwconfig', self.interface],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and 'Mode:Monitor' in result.stdout:
            return True
        result = subprocess.run(
            ['ip', 'link', 'show', self.interface],
            capture_output=True, text=True, timeout=5,
        )
        return 'PROMISC' in result.stdout

    # Filter presets for capture

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

    # Probe request capture

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

    # Wifite-based auditing (Kali's wireless auditor - scan + attack)

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
            # Skip past the number prefix (e.g. "  1  ")
            rest = stripped.split(None, 1)[1] if ' ' in stripped else stripped[3:]
            # Wifite columns (from header: "NUM  ESSID  CH  ENCR  PWR  WPS  CLIENT")
            # ESSID takes ~25 chars, then space-separated fields follow
            # Use right-anchored parsing: find the last 5 space-separated fields
            fields = rest.rsplit(None, 5)  # CH ENCR PWR WPS CLIENT (5 fields from right)
            if len(fields) >= 6:
                essid = fields[0]
                ch = fields[1]
                encr = fields[2]
                pwr = fields[3]
                wps = fields[4]
                clients = fields[5]
            else:
                # Fallback: split by 2+ spaces
                parts = rest.split('  ')
                if len(parts) >= 5:
                    essid = parts[0].strip()
                    ch = parts[1].strip() if len(parts) > 1 else '?'
                    encr = parts[2].strip() if len(parts) > 2 else '?'
                    pwr = parts[3].strip() if len(parts) > 3 else '?'
                    rest2 = parts[4].strip() if len(parts) > 4 else ''
                    wps_clients = rest2.split()
                    wps = wps_clients[0] if wps_clients else 'no'
                    clients = wps_clients[1] if len(wps_clients) > 1 else '0'
                else:
                    continue
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

