# ChonkyFlipper

A portable penetration testing framework built on Raspberry Pi 4. This headless device creates its own WiFi access point for mobile control via smartphone browser.

## Overview

ChonkyFlipper integrates multiple wireless attack vectors into a compact form factor suitable for IoT security assessments and wireless research. The device operates autonomously without requiring an external display or keyboard.

Key capabilities include WiFi reconnaissance with monitor mode support, Bluetooth Low Energy scanning, infrared signal capture and replay, sub-1GHz RF analysis (433/868MHz), NFC/RFID card interaction, and USB HID emulation for physical security testing.

## Architecture

The system uses a three tier architecture: physical hardware layer (GPIO/SPI/I2C modules), REST API backend (Flask), and mobile web frontend. All components communicate over internal buses with the Raspberry Pi acting as the central controller.

## Hardware Stack

### Core Components

* Raspberry Pi 4 Model B (2GB RAM)
* GeeekPi 40mm PWM fan for active cooling
* GPIO stacking header for module expansion
* SunFounder PiPower 5 UPS HAT with 7.4V LiPo battery
* SanDisk 64GB Extreme PRO microSD

### Wireless Modules

* Alfa AWUS036ACS (RTL8811AU) for WiFi analysis
* Internal Pi 4 Bluetooth 5.0 for BLE operations
* SONOFF Zigbee 3.0 USB Dongle (EFR32MG21)
* CC1101 SPI module with SMA antenna (433/868MHz)
* PN532 I2C module for NFC/RFID

### Auxiliary

* KY-005 IR transmitter (GPIO 17)
* KY-022 IR receiver (GPIO 27)
* Mini breadboard with dual voltage rails (5V and 3.3V)

For complete schematics and a detailed GPIO allocation table, see [WIRING.md](WIRING.md).

## Power Design

The PiPower UPS HAT delivers power through the GPIO header pins, leaving the native USB-C port available exclusively for data connections. This enables BadUSB attacks where the device emulates keyboards or storage devices when connected to target computers.

Two separate voltage rails distribute power: 5V for the infrared modules, 3.3V for the CC1101 and PN532 modules. Ground connections are shared across all modules through the breadboard.

## Installation

### Prerequisites

* Kali Linux ARM64 for Raspberry Pi
* Physical hardware assembly completed

### Automated Install

Execute the installation script as root:

```bash
chmod +x install.sh
sudo ./install.sh
```

This creates the directory structure at /opt/chonkyflipper, installs Python dependencies in a virtual environment, configures systemd services, and enables automatic startup.

### Manual Setup

For custom installations or development:

```bash
sudo apt update
sudo apt install python3-pip python3-venv aircrack-ng tcpdump nmap hostapd dnsmasq nginx

pip3 install flask flask-cors gunicorn
```

I2C and SPI are enabled automatically by `install.sh` via `/boot/firmware/config.txt`. No `raspi-config` required.

## Project Structure

```
backend/
    app.py              Main Flask application
    modules/
        wifi.py         Alfa adapter controller
        bluetooth.py    BLE scanner
        ir.py           Infrared operations
        cc1101.py       Sub-1GHz transceiver
        pn532.py        NFC/RFID interface
    requirements.txt

frontend/
    index.html          Mobile dashboard
    style.css           Dark theme UI
    app.js              API client

install.sh              System setup script
```

## API Reference

### System Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/status | Module availability and health |
| GET | /api/system/info | Temperature and uptime |

### WiFi Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/wifi/scan | Discover access points |
| POST | /api/wifi/start_monitor | Enable monitor mode |
| POST | /api/wifi/capture | Record pcap files |

### Bluetooth

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/bluetooth/scan | Enumerate BLE devices |
| GET | /api/bluetooth/beacons | Detect iBeacon/Eddystone |

### Infrared

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/ir/record | Capture IR signals |
| POST | /api/ir/transmit | Replay stored signals |

### Sub-1GHz RF

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/subghz/record | Capture at 433/868MHz |
| POST | /api/subghz/transmit | Replay captured signals |

### NFC/RFID

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/nfc/read | Detect and read cards |
| POST | /api/nfc/write | Write data to cards |

### BadUSB

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/badusb/payloads | List available payloads |
| POST | /api/badusb/execute | Run HID emulation script |

## Usage Workflow

1. Power on the device. The Pi boots and automatically starts the backend API and WiFi access point (SSID: Chonky_Control).

2. Connect a smartphone to the Chonky_Control network.

3. Open a web browser and navigate to http://192.168.4.1 or http://chonkyflipper.local.

4. Select the desired testing module from the dashboard grid.

5. Execute scans, captures, or replay operations through the interface. Results display in real time within the browser.

All captured data (pcap files, IR signals, RF recordings, card data) stores locally on the device under /opt/chonkyflipper/ for later analysis.

## Development Status

**Completed:** Backend API and core driver implementations (PN532 via CircuitPython, CC1101 via SpiDev, IR TX/RX via Kernel LIRC), mobile frontend, installation automation, hardware assembly and testing.

**Pending:** Zigbee2MQTT setup, USB gadget mode for BadUSB, 3D printed enclosure.

## Disclaimer

This tool is intended solely for authorized security testing and educational purposes. Users must obtain explicit permission before testing any networks or devices they do not own. Compliance with local laws and regulations is the sole responsibility of the operator.

## License

MIT License. See LICENSE file for complete terms.
