#!/usr/bin/env python3
"""
WiFi Module - Controls Alfa AWUS036ACM (MT7612U)
Monitor Mode & Packet Injection Support
"""

import subprocess
import re
import json
import os
from datetime import datetime

class WiFiModule:
    """Wi-Fi scanning, monitor mode and packet capture via aircrack-ng"""
    
    def __init__(self, interface='wlan1', monitor_interface='wlan1mon'):
        self.interface = interface  # Alfa adapter
        self.monitor_interface = monitor_interface
        self.capture_dir = '/opt/chonkyflipper/captures'
        os.makedirs(self.capture_dir, exist_ok=True)
    
    def _run_command(self, cmd, shell=True):
        """Execute shell command and return output"""
        try:
            result = subprocess.run(
                cmd, shell=shell, capture_output=True, text=True, timeout=30
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return '', 'Command timed out', 1
        except Exception as e:
            return '', str(e), 1
    
    def scan(self):
        """
        Scan for nearby Wi-Fi networks
        Returns list of networks with BSSID, ESSID, Channel, Signal
        """
        networks = []
        
        # Use iwlist for basic scan
        stdout, stderr, rc = self._run_command(
            f'iwlist {self.interface} scan 2>/dev/null'
        )
        
        if rc != 0:
            # Fallback to iw
            stdout, stderr, rc = self._run_command(
                f'iw dev {self.interface} scan 2>/dev/null'
            )
        
        if stdout:
            networks = self._parse_scan_output(stdout)
        
        return networks
    
    def _parse_scan_output(self, output):
        """Parse iwlist/iw scan output"""
        networks = []
        current_net = {}
        
        for line in output.split('\n'):
            # Cell / BSS line indicates new network
            if 'Cell' in line or 'BSS' in line:
                if current_net and 'bssid' in current_net:
                    networks.append(current_net)
                current_net = {}
                # Extract BSSID
                bssid_match = re.search(r'([0-9A-Fa-f:]{17})', line)
                if bssid_match:
                    current_net['bssid'] = bssid_match.group(1).upper()
            
            # ESSID (Network Name)
            if 'ESSID' in line or 'SSID:' in line:
                essid_match = re.search(r'ESSID:"([^"]*)"', line)
                if not essid_match:
                    essid_match = re.search(r'SSID:\s*(\S+)', line)
                if essid_match:
                    current_net['essid'] = essid_match.group(1)
            
            # Channel
            if 'Channel:' in line or '(Channel' in line:
                channel_match = re.search(r'Channel[:\s]*(\d+)', line)
                if channel_match:
                    current_net['channel'] = int(channel_match.group(1))
            
            # Signal Strength
            if 'Signal level' in line or 'signal:' in line:
                signal_match = re.search(r'(-?\d+)', line)
                if signal_match:
                    current_net['signal_dbm'] = int(signal_match.group(1))
        
        # Add last network
        if current_net and 'bssid' in current_net:
            networks.append(current_net)
        
        # Remove duplicates and sort by signal strength
        seen = set()
        unique_nets = []
        for net in networks:
            key = net.get('bssid', '')
            if key and key not in seen:
                seen.add(key)
                unique_nets.append(net)
        
        return sorted(unique_nets, key=lambda x: x.get('signal_dbm', -100), reverse=True)
    
    def start_monitor_mode(self):
        """
        Enable monitor mode on the interface
        Required for packet injection and advanced scanning
        """
        commands = [
            f'airmon-ng check kill',  # Kill interfering processes
            f'ifconfig {self.interface} down',
            f'airmon-ng start {self.interface}',  # Start monitor mode
            f'ifconfig {self.monitor_interface} up'
        ]
        
        results = []
        for cmd in commands:
            stdout, stderr, rc = self._run_command(cmd)
            results.append({
                'command': cmd,
                'success': rc == 0,
                'output': stdout if stdout else stderr
            })
        
        # Check if monitor interface exists
        check_stdout, _, check_rc = self._run_command(
            f'ip link show {self.monitor_interface}'
        )
        
        success = check_rc == 0 and self.monitor_interface in check_stdout
        
        return {
            'success': success,
            'interface': self.monitor_interface if success else None,
            'commands': results
        }
    
    def stop_monitor_mode(self):
        """Stop monitor mode and return to managed mode"""
        stdout, stderr, rc = self._run_command(
            f'airmon-ng stop {self.monitor_interface}'
        )
        return {
            'success': rc == 0,
            'output': stdout
        }
    
    def capture_packets(self, duration=60, channel=None):
        """
        Capture packets to pcap file
        Useful for analyzing IoT device traffic
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'capture_{timestamp}.pcap'
        filepath = os.path.join(self.capture_dir, filename)
        
        interface = self.monitor_interface if self._is_monitor_mode() else self.interface
        
        cmd = f'timeout {duration} tcpdump -i {interface} -w {filepath}'
        if channel:
            cmd = f'iwconfig {interface} channel {channel} && ' + cmd
        
        stdout, stderr, rc = self._run_command(cmd)
        
        # Check if file was created
        file_exists = os.path.exists(filepath)
        file_size = os.path.getsize(filepath) if file_exists else 0
        
        return {
            'success': file_exists,
            'filename': filename,
            'filepath': filepath,
            'size_bytes': file_size,
            'duration': duration,
            'channel': channel
        }
    
    def _is_monitor_mode(self):
        """Check if interface is in monitor mode"""
        stdout, _, rc = self._run_command(f'iwconfig {self.monitor_interface}')
        return rc == 0 and 'Mode:Monitor' in stdout
    
    def deauth_attack(self, bssid, client=None, count=5):
        """
        Send deauthentication frames (for IoT testing only!)
        bssid: Target AP MAC
        client: Specific client MAC (None for broadcast)
        count: Number of frames to send
        """
        # Safety check - only works in monitor mode
        if not self._is_monitor_mode():
            return {'success': False, 'error': 'Monitor mode required'}
        
        # Construct aireplay-ng command
        if client:
            cmd = f'aireplay-ng -0 {count} -a {bssid} -c {client} {self.monitor_interface}'
        else:
            cmd = f'aireplay-ng -0 {count} -a {bssid} {self.monitor_interface}'
        
        stdout, stderr, rc = self._run_command(cmd)
        
        return {
            'success': rc == 0,
            'bssid': bssid,
            'client': client,
            'frames_sent': count,
            'output': stdout
        }
