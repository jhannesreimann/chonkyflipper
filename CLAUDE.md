# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commit Rules
- **Never** include `Co-Authored-By: Claude` or similar trailers in commit messages
- **Never** use em dashes (`---` / U+2014), box-drawing chars, or other Unicode flourishes in code, comments, or logs
- Keep comment styles consistent within each file -- don't switch between `# ---` and `// ===` patterns wildly
- Code should look human-written -- no AI-typical formatting tells
- When implementing a feature, search GitHub issues for a corresponding issue. If one exists, reference it in the commit with `(resolves #N)`. If no issue exists, commit without a reference.
- Before committing, verify comment style is consistent with the file being edited -- match existing patterns

## Project Overview
Mobile IoT auditing framework / pentesting rig running on Raspberry Pi 4 with Kali Linux ARM64.
The Pi hosts a WiFi access point (Chonky_Control) controlled via smartphone browser.

- **Dev machine**: Arch Linux (noaa@archlinux)
- **Pi**: chonkyflipper.fritz.box (SSH: `ssh kali@chonkyflipper.fritz.box`, no password, key at `~/.ssh/id_rsa`)
- **GitHub**: github.com/jhannesreimann/chonkyflipper (private repo, SSH key on Pi at `/home/kali/.ssh/id_ed25519`)

## Accessing the UI
- **From the LAN** (dev machine on fritz.box): http://192.168.178.78/
- **From phone on Chonky_Control AP**: http://192.168.4.1/
- 192.168.4.1 ONLY works when connected to the Chonky_Control WiFi -- not reachable from the LAN
- Both addresses serve the same nginx instance (listens on 0.0.0.0:80, all interfaces)

## Development Notes
- There is **no test suite, no linter, no build step**. The Flask app runs directly: `python3 backend/app.py` on the Pi.
- All module code runs only on the Pi -- it imports hardware-specific libraries (RPi.GPIO, spidev, board, adafruit_pn532). You can edit files locally, but testing requires deploying to the Pi.
- The `requirements.txt` lists Pi-only packages. No venv is needed locally unless you want syntax checking.
- The venv at `/opt/chonkyflipper/venv` MUST be owned by `chonky:chonky` so the service user can pip install during updates. If root-owned, `pip install` will fail with permission errors.
- To test modules directly, use the venv Python: `cd /opt/chonkyflipper && source venv/bin/activate`
- Always verify the deployed version: `curl -s http://127.0.0.1:5000/api/system/version` on the Pi

## Key Paths
| Path | Purpose |
|------|---------|
| `/opt/chonkyflipper/` | Backend deployment (Flask app, venv, modules, scripts) |
| `/opt/chonkyflipper/venv/` | Python virtual environment (must be chonky:chonky) |
| `/opt/chonkyflipper/data/` | SQLite databases (ir_payloads.db), cloned Flipper-IRDB repo |
| `/opt/chonkyflipper/payloads/` | IR JSON payloads (`ir/`) + BadUSB DuckyScripts (`badusb/`) |
| `/var/www/html/` | Frontend deployment (nginx serves on port 80) |
| `/home/kali/chonkyflipper/` | Git clone (source of truth for updates) |
| `/opt/pipower5/` | PiPower5 UPS HAT (installed from local source, NOT on PyPI) |
| `/opt/zigbee2mqtt/` | Zigbee2MQTT Node.js app + data/config |
| `/opt/chonkyflipper/VERSION` | Current deployed git SHA (written by update.sh) |

## Architecture
```
Phone browser ---WiFi---> wlan0 AP (Chonky_Control, 192.168.4.1)
                           |
                       nginx :80  --> static frontend (index.html, app.js, style.css)
                           |
                       /api/* proxy --> gunicorn :5000 (Flask app.py, user: chonky)

Internet <---LAN---> eth0 (192.168.178.78)
Internet <---WiFi--> wlan1 (192.168.178.89, Alfa AWUS036ACS, client mode via wpa_supplicant)
```

## Backend Architecture

### Module Pattern
Every hardware module follows the same lazy-init pattern in `app.py`:
```python
modules = {}
def get_module(name):
    if name not in modules:
        module_map = {
            'wifi': WiFiModule, 'bluetooth': BluetoothModule, 'ir': IRModule,
            'cc1101': CC1101Module, 'pn532': PN532Module, 'badusb': BadUSBModule,
            'zigbee': ZigbeeModule
        }
        modules[name] = module_map[name]()
    return modules[name]
```
Modules are instantiated on first use. Each module class lives in `backend/modules/<name>.py` and handles its own hardware detection, initialization, and cleanup.

**Important**: `backend/modules/__init__.py` imports all modules including `cc1101` which imports `spidev`. This means you cannot import any module with system Python (spidev is only in the venv). Always use the venv Python when testing modules directly.

### IR Library System (multi-file subsystem)
The IR functionality spans four files:
- **`ir.py`** -- Low-level IR: records from `/dev/lirc1` (RX), transmits via `ir-ctl` to `/dev/lirc0` (TX). Also provides legacy JSON-payload execution and a `brute_force_power()` method that sends power toggles across brands.
- **`ir_protocols.py`** -- Protocol encoder registry. `@register('NEC')` decorator pattern adds encoders to `PROTOCOL_REGISTRY`. Protocols: NEC, Samsung32, Sony SIRC, Panasonic, RC5. `encode(protocol, **params)` returns `(pulses, spaces)` for transmission.
- **`ir_db.py`** -- SQLite-backed IR payload database. Tables: `brands`, `devices`, `buttons`, `schema_version`, `sync_state`. Provides hierarchical browsing (brands -> devices -> buttons), full-text search, and JSON seed import. Stores raw pulse/space arrays for each button. Auto-seeds from `payloads/ir/*.json` on first run.
- **`ir_sync.py`** -- Incremental sync from [Flipper-IRDB](https://github.com/logickworkshop/Flipper-IRDB). Clones the repo shallow into `/opt/chonkyflipper/data/irdb/`, parses `.ir` files (raw and parsed signal types), and imports into the SQLite DB. Tracks sync state via `sync_state` table for incremental updates.
- **`app.py` routes** -- `/api/ir/library/*` endpoints for browsing, `/api/ir/sync/*` for sync management.

### Zigbee2MQTT Bridge
- **`zigbee.py`** communicates with a local MQTT broker (mosquitto on `localhost:1883`) using `paho-mqtt`.
- Subscribes to `zigbee2mqtt/#` topics; caches retained messages.
- Uses request/response pattern for bridge commands (permit_join, networkmap, device remove) via `_publish_and_wait()`.
- The Zigbee2MQTT service runs as a separate Node.js process under the `zigbee2mqtt` user.
- **Hardware**: SONOFF Zigbee 3.0 USB Dongle Lite MG21 (Silicon Labs CP210x UART Bridge, `/dev/ttyUSB0`).
- **Adapter**: `ember` (configured in `/opt/zigbee2mqtt/data/configuration.yaml`)
- **Dependencies**: Node.js >= 18 (v20.20.2 installed), pnpm (v10.x), mosquitto MQTT broker.
- **User setup**: zigbee2mqtt user must have home dir at `/opt/zigbee2mqtt` (pnpm cache), dialout group for `/dev/ttyUSB0`.
- chonky user must be in `dialout` group to access the Zigbee USB dongle.

### BadUSB DuckyScript Parser
- **`badusb.py`** parses DuckyScript payloads (`.txt` files from `payloads/badusb/`).
- Commands: `STRING`, `DELAY`, modifier combos (`GUI r`, `CTRL SHIFT ESC`), and named keys (`ENTER`, `F5`, etc.).
- Writes 8-byte HID reports to `/dev/hidg0` (Linux configfs USB gadget).
- Character map covers printable ASCII plus shifted variants.

### WiFi Scanning
WiFi scanning is centralized in `_do_wifi_scan()` in `app.py` (not the `WiFiModule` class). Uses `wpa_cli -i wlan1 scan` + `scan_results`. The `WiFiModule` class (`wifi.py`) provides monitor mode, packet capture, and deauth -- lower-level aircrack-ng operations.

## Frontend Architecture
- Single-page app: `index.html` + `app.js` + `style.css`.
- **Polling pattern**: `checkStatus()` every 5s, `updateSystemInfo()` every 10s, `fetchVersion()` every 60s, `updateNetworkStatus()` every 10s.
- **Module panels**: Each hardware module has a hidden `<div class="module-panel">` in `index.html`. Clicking a `.module-item` in the grid shows the corresponding panel via `showModulePanel()`.
- `API_BASE` auto-detects: uses `http://localhost:5000` when page is served from localhost, empty string otherwise (nginx proxies `/api/` to backend).

## Network Interfaces (current state)
| Interface | Type | IP | Purpose |
|-----------|------|-----|---------|
| eth0 | LAN | 192.168.178.78 | Primary internet (fritz.box) |
| wlan0 | AP | 192.168.4.1 | Chonky_Control AP (hostapd) |
| wlan1 | Client | 192.168.178.89 | Alfa adapter, connected to "lama" WiFi |
- Interface naming is pinned via `/etc/udev/rules.d/70-persistent-wifi.rules` to prevent USB vs SDIO probe order races

## WiFi Client & Updates
- wlan1 connects to external WiFi via `wpa_supplicant@wlan1` (separate from wlan0 AP)
- Config at `/etc/wpa_supplicant/wpa_supplicant-wlan1.conf`, written via sudo tee
- `bgscan=""` disables periodic background scanning -- scans only on demand
- Update script at `/opt/chonkyflipper/update.sh` runs git pull + pip install + systemctl restart
- Internet check: ping 8.8.8.8, determine source from `ip route get`

## Hardware Modules (dynamic detection)
| Module | Detection | Interface | Device |
|--------|-----------|-----------|--------|
| WiFi (Alfa) | `/sys/class/net/wlan1` | USB | Alfa AWUS036ACS (RTL8811AU) |
| Bluetooth | `/sys/class/bluetooth/hci0` | Built-in UART | Pi 4 internal Bluetooth 5.0 |
| IR | `/dev/lirc0` | GPIO 17 (TX), GPIO 27 (RX) | KY-005 TX + KY-022 RX |
| CC1101 | `/sys/bus/spi/devices/spi0.0` | SPI0 (CE0, MOSI, MISO, SCLK) | CC1101 module with SMA antenna |
| PN532 | `i2cdetect -y 1` shows 0x24 | I2C1 (SDA=GPIO2, SCL=GPIO3) | PN532 NFC/RFID module |
| Zigbee | `/dev/ttyUSB0` | USB | SONOFF Zigbee 3.0 USB Dongle Lite MG21 |
| BadUSB | `/dev/hidg0` | USB-C data port | Linux configfs USB HID gadget |

See `WIRING.md` for the complete GPIO pinout and physical wiring schematic.

## Services
| Service | User | Status | Notes |
|---------|------|--------|-------|
| `chonkyflipper.service` | chonky | active | Gunicorn :5000, 2 workers |
| `chonky-gadget.service` | root (oneshot) | active | USB HID gadget setup, runs before backend |
| `hostapd.service` | root | active | WiFi AP on wlan0 |
| `dnsmasq.service` | root | active | DHCP + DNS for AP clients |
| `nginx.service` | root | active | :80 frontend, proxies /api/ -> :5000 |
| `mosquitto.service` | mosquitto | active | MQTT broker :1883 for Zigbee2MQTT |
| `zigbee2mqtt.service` | zigbee2mqtt | active | Node.js, ember adapter, /dev/ttyUSB0 |
| `wpa_supplicant@wlan1.service` | root | active | WiFi client on Alfa adapter |

## User & Permissions
- Service user: `chonky` (groups: chonky, video, netdev, i2c, bluetooth, gpio, spi, dialout, kali)
- Zigbee user: `zigbee2mqtt` (groups: zigbee2mqtt, dialout, home at `/opt/zigbee2mqtt`)
- Sudoers at `/etc/sudoers.d/chonky-ops` -- passwordless for: shutdown, update.sh, iw scan, wpa_cli, systemctl on wlan1, ip, i2cdetect, tee, rm socket, zigbee2mqtt management
- PiPower5 import: `from pipower5.pipower5 import PiPower5` (NOT `from pipower5 import PiPower5`)
- `/dev/hidg0` must be world-writable (udev rule: `KERNEL=="hidg*", MODE="0666"`)
- `/dev/ttyUSB0` owned by `root:dialout` -- chonky and zigbee2mqtt need dialout group

## Git & Deployment Gotchas
- **update.sh runs as root (via sudo)**: git commands in update.sh must use `sudo -u kali git ...` to avoid creating root-owned objects in `/home/kali/chonkyflipper/.git/`. If git objects become root-owned, `git fetch` as kali user will fail with "insufficient permission".
- **Fixing mixed ownership**: `sudo chown -R kali:kali /home/kali/chonkyflipper/.git`
- **VERSION file**: Written by update.sh (root), must be chowned to `chonky:chonky` so the API can read it.
- **Venv ownership**: The venv at `/opt/chonkyflipper/venv` must be `chonky:chonky`. If root-owned, pip install during updates will fail with permission errors.
- **Deploying manually**: If update.sh skips because git HEAD matches, run the copy steps manually (backend files -> /opt/chonkyflipper/, frontend -> /var/www/html/, payloads, systemctl restart).

## DNS
- dnsmasq serves BOTH `chonkyflipper.pi` AND `chonkyflipper.local` pointing to 192.168.4.1
- `.local` is unreliable on Linux (mDNS hijacks it via nss-mdns/systemd-resolved)
- Default recommendation: use `192.168.4.1` directly

## Important Notes
- `pipower5` is NOT on PyPI -- installed from `/opt/pipower5/` local source by install.sh
- `sudo -n` required for all privileged commands from the API (chonky user)
- `GIT_TERMINAL_PROMPT=0` for non-interactive git operations
- wpa_supplicant socket at `/var/run/wpa_supplicant/wlan1` needs cleanup (`rm -f`) before restart
- IR timeout filter: values >= 1,000,000us are LIRC timeout markers, not real signals. Filter both at record time (0x00FFFF00 mask) and transmit time.
- The `__init__.py` module file imports all hardware modules -- testing any module requires the venv Python (system Python lacks spidev, RPi.GPIO, etc.)
- Mosquitto listens on 127.0.0.1:1883 only (localhost), not exposed to external networks
- Zigbee2MQTT's pnpm requires a writable home directory for the zigbee2mqtt user -- set to `/opt/zigbee2mqtt` in `/etc/passwd`
- Zigbee network map generation via API may time out on large networks; the API has a 15s timeout
