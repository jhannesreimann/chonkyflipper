#!/usr/bin/env python3
"""
WiFi Module - Controls Alfa AWUS036ACM (MT7612U)
Monitor Mode & Packet Injection Support
"""

import os
import re
import time
import subprocess
from datetime import datetime
from config import CAPTURES_DIR


class WiFiModule:
    """Wi-Fi scanning, monitor mode and packet capture via aircrack-ng"""

    def __init__(self, interface='wlan1', monitor_interface='wlan1mon'):
        self.interface = interface
        self.monitor_interface = monitor_interface
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
    # Scanning (used by /api/wifi/scan via routes/wifi.py)
    # ------------------------------------------------------------------

    def scan_networks(self):
        """Scan for WiFi networks using wpa_cli on wlan1."""
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

                security = None
                if 'WPA2' in flags:
                    security = 'WPA2'
                elif 'WPA-' in flags:
                    security = 'WPA'

                channel = None
                if 2412 <= freq <= 2484:
                    channel = (freq - 2412) // 5 + 1
                elif 5180 <= freq <= 5885:
                    channel = (freq - 5180) // 5 + 36

                networks.append({
                    'bssid': bssid.upper(), 'ssid': ssid,
                    'signal_dbm': signal, 'channel': channel, 'security': security,
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
                else:
                    seen[ssid] = net

        return sorted(seen.values(), key=lambda x: x.get('signal_dbm', -100), reverse=True)

    # ------------------------------------------------------------------
    # Monitor mode & packet capture
    # ------------------------------------------------------------------

    def start_monitor_mode(self):
        commands = [
            'airmon-ng check kill',
            f'ifconfig {self.interface} down',
            f'airmon-ng start {self.interface}',
            f'ifconfig {self.monitor_interface} up',
        ]
        results = []
        for cmd in commands:
            stdout, stderr, rc = self._run(cmd)
            results.append({'command': cmd, 'success': rc == 0, 'output': stdout if stdout else stderr})

        check_stdout, _, check_rc = self._run(f'ip link show {self.monitor_interface}')
        success = check_rc == 0 and self.monitor_interface in check_stdout

        return {'success': success, 'interface': self.monitor_interface if success else None, 'commands': results}

    def stop_monitor_mode(self):
        stdout, stderr, rc = self._run(f'airmon-ng stop {self.monitor_interface}')
        return {'success': rc == 0, 'output': stdout}

    def capture_packets(self, duration=60, channel=None):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'capture_{timestamp}.pcap'
        filepath = os.path.join(CAPTURES_DIR, filename)

        interface = self.monitor_interface if self._is_monitor_mode() else self.interface

        cmd = f'timeout {duration} tcpdump -i {interface} -w {filepath}'
        if channel:
            cmd = f'iwconfig {interface} channel {channel} && ' + cmd

        self._run(cmd)

        file_exists = os.path.exists(filepath)
        file_size = os.path.getsize(filepath) if file_exists else 0

        return {'success': file_exists, 'filename': filename, 'filepath': filepath,
                'size_bytes': file_size, 'duration': duration, 'channel': channel}

    def _is_monitor_mode(self):
        stdout, _, rc = self._run(f'iwconfig {self.monitor_interface}')
        return rc == 0 and 'Mode:Monitor' in stdout

    def deauth_attack(self, bssid, client=None, count=5):
        if not self._is_monitor_mode():
            return {'success': False, 'error': 'Monitor mode required'}
        if client:
            cmd = f'aireplay-ng -0 {count} -a {bssid} -c {client} {self.monitor_interface}'
        else:
            cmd = f'aireplay-ng -0 {count} -a {bssid} {self.monitor_interface}'
        stdout, stderr, rc = self._run(cmd)
        return {'success': rc == 0, 'bssid': bssid, 'client': client,
                'frames_sent': count, 'output': stdout}
