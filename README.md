# ChonkyFlipper

A portable penetration testing framework built on Raspberry Pi 4. This headless device creates its own WiFi access point for mobile control via smartphone browser.

## Overview

ChonkyFlipper integrates multiple wireless attack vectors into a compact form factor suitable for IoT security assessments and wireless research. The device operates autonomously without requiring an external display or keyboard.

Key capabilities include WiFi reconnaissance with monitor mode support, Bluetooth LE and Classic scanning with advertisement spoofing, infrared signal capture and replay, sub-1GHz RF analysis (433/868MHz), Zigbee network auditing, NFC/RFID card interaction, and USB HID emulation for physical security testing.

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
* CC2531 USB Dongle (TI packet sniffer firmware) for Zigbee security auditing
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
    app.py              Flask application entrypoint
    config.py           Centralized paths and constants
    utils.py            API response helpers (api_success / api_error)
    routes/             Flask blueprints (status, wifi, bluetooth, ir,
    |                     subghz, nfc, badusb, zigbee, zigbee_audit, network)
    modules/
        wifi.py         Alfa adapter + WiFi scanning
        bluetooth.py    BLE + Classic BT scanner, GATT, SDP, beacon decode, spoofing
        ir.py           IR record + transmit (LIRC kernel drivers)
        ir_protocols.py Protocol encoders (NEC, Samsung, Sony, RC5, etc.)
        ir_db.py        SQLite IR payload database (brands/devices/buttons)
        ir_sync.py      Flipper-IRDB incremental git sync
        cc1101.py       Sub-1GHz transceiver (SPI)
        pn532.py        NFC/RFID reader/writer (I2C)
        zigbee.py       Zigbee2MQTT bridge (MQTT)
        zigbee_audit.py Zigbee security auditing (CC2531 + KillerBee)
        badusb/             USB HID interpreter, keymaps, DB, sync engine
    requirements.txt

frontend/
    index.html          Mobile dashboard shell
    src/
        main.js         App shell: header, sidebar, hash router, theme toggle
        state.js        Central polling store (/status, /system, /network, /version)
        api.js          Fetch wrappers (apiGet / apiPost / apiDelete)
        toast.js        Toast notifications + persistent task handles
        ui.js           Shared presentational fragments (pageHead, card, tabBar, etc.)
        util.js         Escaping + small DOM/format helpers
        style.css       Tailwind entry, chonky / chonky-dark DaisyUI themes
        modules/
            dashboard.js   System overview (temperature, uptime, module status)
            wifi.js        Scan, monitor mode, packet capture, deauth
            bluetooth.js   BLE + Classic scanning, GATT, spoofing, HCI capture
            ir.js          IR library browser (brands/devices/buttons), record/send
            subghz.js      CC1101 record / replay (433/868 MHz)
            nfc.js         PN532 read / write / clone
            badusb.js      DuckyScript payload list + execute
            zigbee.js      Zigbee2MQTT devices, events, bridge info, network map
            zigbee-sniffer.js  CC2531 sniffer: PAN scan, packet capture, key extraction
            settings.js    WiFi connect, network status, power, system update

payloads/
    ir/                 Bootstrap IR JSON payloads (seed DB offline)
    badusb/             DuckyScript payloads for BadUSB

install.sh              Full system setup (run once on fresh Pi)
update.sh               Git pull + deploy (run via dashboard or CLI)
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
| GET | /api/bluetooth/scan | Enumerate BLE devices (accepts `?duration=N`) |
| GET | /api/bluetooth/beacons | Detect iBeacon / Eddystone beacons |
| POST | /api/bluetooth/gatt | Profile GATT services on a BLE device |
| POST | /api/bluetooth/gatt/write | Write to a GATT characteristic |
| POST | /api/bluetooth/capture | One-shot BLE advertisement log (accepts `duration`) |
| POST | /api/bluetooth/log/start | Start background ad log daemon |
| POST | /api/bluetooth/log/stop | Stop background ad log daemon |
| GET | /api/bluetooth/log/status | Check if ad log daemon is running |
| GET | /api/bluetooth/log/data | Read current ad log daemon data |
| GET | /api/bluetooth/classic-scan | Discover Classic BR/EDR devices (hcitool inquiry) |
| POST | /api/bluetooth/sdp | Enumerate SDP services on a Classic device |
| POST | /api/bluetooth/deep-scan | Deep BLE scan via bettercap (vendor metadata) |
| POST | /api/bluetooth/spoof | Start BLE advertisement spoofing |
| POST | /api/bluetooth/spoof/stop | Stop advertisement spoofing |
| GET | /api/bluetooth/spoof/status | Check if spoofing is running |
| POST | /api/bluetooth/capture-hci | Capture raw HCI traffic (btmon, Wireshark pcap) |
| GET | /api/bluetooth/captures | List saved HCI capture files |

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
| GET | /api/badusb/payloads | List filesystem payloads |
| POST | /api/badusb/execute | Execute payload by name, DB id, or inline content |
| GET | /api/badusb/library/os | List OS types with payload counts |
| GET | /api/badusb/library/categories?os={slug} | Categories filtered by OS |
| GET | /api/badusb/library/payloads?os={slug}&category={slug} | Payload list with filters |
| GET | /api/badusb/library/payload/{id} | Single payload with full content |
| GET | /api/badusb/library/search?q=... | Full-text search |
| GET | /api/badusb/library/stats | Payload counts by OS and category |
| POST | /api/badusb/library/sync/check | Check for upstream repo updates |
| POST | /api/badusb/library/sync/start | Clone/update repos and import payloads |
| GET | /api/badusb/library/sync/status | Sync progress |
| POST | /api/badusb/arm | Arm a payload for auto-fire on USB connect |
| GET | /api/badusb/arm/status | Check armed state |
| POST | /api/badusb/arm/cancel | Cancel auto-fire |

### Zigbee Bridge (Zigbee2MQTT)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/zigbee/bridge | Bridge info and state |
| GET | /api/zigbee/dashboard | Combined device view (registry + live state) |
| GET | /api/zigbee/events?limit=N | Recent lifecycle and state events |
| GET | /api/zigbee/networkmap | Network topology (nodes + links) |
| POST | /api/zigbee/permit_join | Enable pairing mode |
| POST | /api/zigbee/device/\<name\>/set | Control device (e.g. on/off) |
| POST | /api/zigbee/device/\<name\>/rename | Rename a device |
| DELETE | /api/zigbee/device/\<name\> | Force-remove a device |

### Zigbee Auditing (CC2531 + KillerBee)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/zigbee/audit/capture | Capture packets on a channel to pcap |
| POST | /api/zigbee/audit/scan | Passive PAN discovery (zbstumbler) |
| POST | /api/zigbee/audit/discover | Parse pcap for devices (MACs, roles, encryption) |
| POST | /api/zigbee/audit/extract-keys | Extract network keys from capture (zbdsniff) |
| GET | /api/zigbee/audit/captures | List saved pcap capture files |

## Usage Workflow

1. Power on the device. The Pi boots and automatically starts the backend API and WiFi access point (SSID: Chonky_Control).

2. Connect a smartphone to the Chonky_Control network.

3. Open a web browser and navigate to http://192.168.4.1 or http://chonkyflipper.pi.

4. Select the desired testing module from the dashboard grid.

5. Execute scans, captures, or replay operations through the interface. Results display in real time within the browser.

All captured data (pcap files, IR signals, RF recordings, card data) stores locally on the device under /opt/chonkyflipper/ for later analysis.

## Development Status

**Completed:** Backend API and core driver implementations (PN532 via CircuitPython, CC1101 via SpiDev, IR TX/RX via Kernel LIRC), mobile frontend, installation automation, hardware assembly and testing.

**Pending:** 3D printed enclosure.

## Disclaimer

This tool is intended solely for authorized security testing and educational purposes. Users must obtain explicit permission before testing any networks or devices they do not own. Compliance with local laws and regulations is the sole responsibility of the operator.

## License

MIT License. See LICENSE file for complete terms.
