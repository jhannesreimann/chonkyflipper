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
- The Flask backend has **no test suite, no linter** and runs directly: `python3 backend/app.py` on the Pi.
- The frontend IS built: `cd frontend && npm run build` produces static files in `frontend/dist/`.  The dev server (`npm run dev`) proxies `/api` to the Pi so you can work on the UI locally against live hardware.
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
| `/opt/chonkyflipper/killerbee/` | KillerBee framework for Zigbee security auditing |
| `/opt/chonkyflipper/data/zigbee_captures/` | Zigbee sniffer pcap captures |
| `/opt/chonkyflipper/VERSION` | Current deployed git SHA (written by update.sh) |

## Architecture
```
Phone browser ---WiFi---> wlan0 AP (Chonky_Control, 192.168.4.1)
                           |
                       nginx :80  --> static frontend (dist/ built by Vite)
                           |
                       /api/* proxy --> gunicorn :5000 (Flask app.py, user: chonky)

Internet <---LAN---> eth0 (192.168.178.78)
Internet <---WiFi--> wlan1 (192.168.178.89, Alfa AWUS036ACS, client mode via wpa_supplicant)
```

## Backend Architecture

### Module Pattern
Every hardware module follows the same lazy-init pattern in `app.py`:
```python
_modules = {}
def get_module(name):
    if name not in _modules:
        module_map = {
            'wifi': 'modules.wifi.WiFiModule',
            'bluetooth': 'modules.bluetooth.BluetoothModule',
            'ir': 'modules.ir.IRModule',
            'cc1101': 'modules.cc1101.CC1101Module',
            'pn532': 'modules.pn532.PN532Module',
            'badusb': 'modules.badusb.BadUSBModule',
            'zigbee': 'modules.zigbee.ZigbeeModule',
        }
        mod_path, cls_name = module_map[name].rsplit('.', 1)
        mod = __import__(mod_path, fromlist=[cls_name])
        _modules[name] = getattr(mod, cls_name)()
    return _modules[name]
```
Modules are instantiated on first use via `__import__`. Each module class lives in `backend/modules/<name>.py` and handles its own hardware detection, initialization, and cleanup.

The `__init__.py` only lists `__all__` -- no eager imports. Use `from modules.ir import IRModule` inside the venv to import specific modules directly when testing.

### IR Library System (multi-file subsystem)
The IR functionality spans four files:
- **`ir.py`** -- Low-level IR: records from `/dev/lirc1` (RX), transmits via `ir-ctl` to `/dev/lirc0` (TX). Also provides `transmit_raw()`, `detect_protocol()`, and signal management (list/delete). Tempfiles use `tempfile.mkstemp` to avoid PID races.
- **`ir_protocols.py`** -- Protocol encoder registry. `@register('NEC')` decorator pattern adds encoders to `PROTOCOL_REGISTRY`. Protocols: NEC, Samsung32, Sony SIRC, Panasonic, RC5. `encode(protocol, **params)` returns `(pulses, spaces)` for transmission.
- **`ir_db.py`** -- SQLite-backed IR payload database. Tables: `brands`, `devices`, `buttons`, `schema_version`, `sync_state`. Provides hierarchical browsing (brands -> devices -> buttons), full-text search, and JSON seed import. Stores raw pulse/space arrays for each button. Auto-seeds from `payloads/ir/*.json` on first run.
- **`ir_sync.py`** -- Incremental sync from [Flipper-IRDB](https://github.com/logickworkshop/Flipper-IRDB). Clones the repo shallow into `/opt/chonkyflipper/data/irdb/`, parses `.ir` files, and imports into the SQLite DB. Tracks sync state for incremental updates. Key bugfix: `parse_ir_file` now appends all signals (was only saving the last one per file).
- **`routes/ir.py`** -- `/api/ir/library/*` endpoints for browsing, `/api/ir/sync/*` for sync management, `/api/ir/signals` for recorded signals.

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

### Zigbee Security Auditing (CC2531 + KillerBee)
- **`zigbee_audit.py`** provides passive 802.15.4 packet capture, PAN discovery, device identification, and network key extraction using KillerBee framework with a CC2531 USB dongle.
- **Hardware**: CC2531 USB Dongle with stock Texas Instruments packet sniffer firmware (VID:0451 PID:16AE, bcdDevice 25.17). Pre-flashed from the factory -- no custom firmware or CC Debugger needed. This is the standard TI CC2531EMK evaluation kit firmware; KillerBee supports it natively for sniffing without any reflashing.
- **KillerBee** is cloned to `/opt/chonkyflipper/killerbee/`. Tools: `zbdump` (packet capture), `zbstumbler` (PAN discovery), `zbdsniff` (key extraction).
- The CC2531 is RX-only (sniffer firmware). Packet injection (replay, association flood) requires a TX-capable dongle like Atmel RZUSBSTICK/ApiMote.
- **Dependencies**: scapy, pyusb, pyserial, rangeparser (installed in venv). tshark for pcap analysis.
- **Udev rule**: `/etc/udev/rules.d/99-cc2531.rules` with MODE=0666 so chonky user can access USB directly (no sudo needed).
- **Device discovery**: `discover_devices()` uses tshark to parse pcap files, extracting MACs, PAN IDs, roles, and encryption status. Cross-references with Zigbee2MQTT coordinator for device names/models.
- **ZCL identification**: Attempts decryption with Z2M network key from config, maps cluster IDs to device types (On/Off=switch, Temperature=sensor, etc.).
- **Frontend**: `zigbee-sniffer.js` with 3 tabs (Scan, Capture, Extract). Sidebar shows expandable Zigbee entry with Coordinator (SONOFF) and Sniffer (CC2531) sub-items.
- **Routes**: `/api/zigbee/audit/` prefix -- `capture`, `scan`, `discover`, `extract-keys`, `captures`.

### NFC / RFID (PN532 + libnfc)
- **`pn532.py`** wraps libnfc CLI tools (`nfc-list`, `nfc-mfclassic`, `mfoc`) for card read, block write, full sector dump/clone, and key recovery.
- **Hardware**: PN532 NFC module in HSU (UART) mode. Switches: both OFF. Connected to Pi UART on GPIO 14 (TXD) and GPIO 15 (RXD) via `/dev/ttyAMA0`.
- **UART config**: `enable_uart=1` and `dtoverlay=miniuart-bt` in `/boot/firmware/config.txt`. libnfc configured at `/etc/nfc/libnfc.conf` with `pn532_uart:/dev/ttyAMA0`.
- **libnfc tools**: `nfc-list` (card detection), `nfc-mfclassic r a u` (full dump), `nfc-mfclassic w a u` (full clone), `mfoc -O` (key recovery). All installed via `apt install mfoc mfcuk libnfc-bin`.
- **Card types**: Mifare Classic 1K/4K detected via ATQA/SAK. Read/write block 4 with default key. Dump auto-falls back from nfc-mfclassic (default keys) to mfoc (key recovery) when sectors fail auth.
- **Clone workflow**: Dump saves full sector data to cards directory as JSON. Saved cards with full dumps get a clone button in the frontend that writes all sectors to a magic card via `nfc-mfclassic w a u`.
- **Limitations**: mfoc needs a genuine Mifare Classic card (not magic/gen2). Mifare Ultralight/NTAG/DESFire not supported by current tools. Card emulation not implemented (PN532 target mode not exposed in libnfc-bin).
- **Frontend**: `nfc.js` with Read & Dump, Write/Clone form, Advanced (mfoc), and Saved cards history section.
- **Routes**: `/api/nfc/read`, `/api/nfc/write`, `/api/nfc/dump`, `/api/nfc/clone`, `/api/nfc/mfoc`.

### BadUSB DuckyScript Parser & Payload Library

The BadUSB system has three layers: a filesystem scanner for local `.txt` payloads, a SQLite-backed library synced from GitHub payload repos (modelled after the IR library), and a USB HID gadget execution engine.

- **`modules/badusb/`** — Package: `interpreter.py` (DuckyScript 3.0 parser with variables, IF/WHILE, expressions), `keymaps.py` (us/de layout tables + named keys + modifier bitmasks), `backends.py` (HidBackend writing 8-byte reports to `/dev/hidg0`, DryRunBackend for preview), `module.py` (filesystem payload discovery and execution).
- **`modules/badusb/db.py`** — SQLite database: `os_types`, `categories`, `payloads` tables with FTS5 search. Stores payloads synced from GitHub with metadata parsed from REM headers (Title, Author, Description, Target OS, Category). Hierarchical browsing: OS → Category → Payloads.
- **`modules/badusb/sync.py`** — Sync engine cloning payload repos (`hak5/usbrubberducky-payloads`, `Starvinci/BadUsb-Library`, `aleff-github/my-flipper-shits`) via shallow git clone. Incremental updates via `git diff`. Parses REM comment headers to extract OS, category, author, and description.
- **`routes/badusb.py`** — Filesystem routes (`/badusb/payloads`, `/badusb/execute`), library routes (`/badusb/library/os`, `/categories`, `/payloads`, `/search`, `/stats`, `/sync/*`), and auto-fire routes (`/badusb/arm`, `/arm/status`, `/arm/cancel`).
- **Auto-fire**: Arm a payload, and when the Pi's USB-C port detects a host connection (UDC state change), the payload fires automatically. State is polled via `/api/status` every 5 seconds.
- **Frontend**: `badusb.js` — two-tab layout: Library (OS pills → category grid → payload list → detail with preview/edit/run/arm) and Files (existing filesystem browser).

### Sub-1GHz RF (CC1101)
- **`cc1101.py`** drives the CC1101 over SPI (`/dev/spidev0.0`) for the control plane (reset, strobes, register R/W, frequency synthesis, RSSI) and uses **lgpio** on GDO0 (BCM 25) for the timing plane.
- **Async serial OOK**: `_configure_default_ook()` puts the modem in async serial mode (IOCFG0=0x0D, PKTCTRL0=0x32, MDMCFG2=0x30) so GDO0 carries the raw sliced bitstream. Capture claims GDO0 as an lgpio alert and timestamps both edges; replay drives GDO0 with an lgpio `tx_wave` while the PA is keyed by the input level (`_configure_tx_ook()` sets FREND0 + PATABLE).
- **Capture denoise**: `_extract_burst()` splits the edge stream on long idle gaps (`GAP_US`) and keeps the densest segment; a capture with fewer than `MIN_PULSES` edges is flagged `clean=False` (noise only).
- **Decoding**: `subghz_decode.py` turns a captured pulse train into bits, majority-voting repeated frames to classify EV1527/PT2262/HT12E fixed codes and identify KeeLoq rolling code; absurd bit counts are rejected as noise/FSK.
- **Jamming**: `jam()` emits a continuous carrier (async TX + GDO0 held high) or PN9 noise (PKTCTRL0 random TX mode), hard-capped at 30 s. Real RF, gated behind a UI warning + confirm.
- **`scan_frequency()`** sweeps a band reading RSSI per step for the spectrum graph. Signals are stored as raw `pulses` (`[level, us]`) JSON in `signals/subghz/`.
- **Routes** (`routes/subghz.py`): `/subghz/record`, `/subghz/transmit`, `/subghz/scan`, `/subghz/jam`, `/subghz/decode`, `GET /subghz/signals`, `GET/DELETE /subghz/signals/<id>`.
- **Frontend**: `subghz.js` -- four tabs (Spectrum / Capture / Signals / Jam). The spectrum graph and per-signal OOK burst map are inline SVG (no chart library); bars use `fill-current` + DaisyUI text colours. The signal detail view has a Decode panel.
- **lgpio provisioning** (not on Kali apt, and the pip wheel needs the C lib): build `github.com/joan2937/lg` (`make && sudo make install && sudo ldconfig`), then install the binding into the venv as the chonky user: `sudo -u chonky bash -c 'LIBRARY_PATH=/usr/local/lib C_INCLUDE_PATH=/usr/local/include /opt/chonkyflipper/venv/bin/pip install lgpio'`. It runs daemonless; the import creates a `.lgd-nfy*` notify pipe in the service CWD (`/opt/chonkyflipper`, chonky-writable). Kept out of `requirements.txt` so `update.sh`'s `pip install` never tries (and fails) to rebuild the wheel without those env vars.

### WiFi Scanning
WiFi scanning is in `routes/wifi.py` (uses `wpa_cli -i wlan1 scan` + `scan_results`). The `WiFiModule` class (`wifi.py`) provides `scan_networks()`, monitor mode, packet capture, and wifite-based vulnerability auditing.

- **rtl8821au driver gotcha**: Never use `ifconfig` to bring wlan1 down/up; it corrupts the driver state and causes `Invalid HW-addr family 0x0323` when wpa_supplicant tries to init. Use `ip link set down/up` instead. `stop_monitor_mode()` uses `ip link` + `iw set type managed` + `ip link set promisc off` to reliably exit monitor mode. If the interface gets into a broken state (promisc stuck, scans return empty), reload the module: `modprobe -r 8821au && modprobe 8821au`.
- **Empty-scan auto-recovery**: `scan_networks()` reloads the `8821au` module (via `reset_adapter()`) and retries once when a scan returns zero networks, since an empty result almost always means the driver wedged. Manual trigger: `POST /wifi/reset_adapter` (Scan tab reset button). Requires the sudoers drop-in `/etc/sudoers.d/chonky-wifi-reset` granting chonky `modprobe -r 8821au` and `modprobe 8821au`. Do NOT run `iw dev wlan1 scan` directly against a wedged driver -- it can hard-crash the kernel and reboot the Pi.
- **wifite serialization**: `/wifi/audit/wifite-scan` and `wifite-attack` take a cross-process `flock` (`/tmp/chonky_wifite.lock`) so two runs cannot fight over the adapter and crash the backend. The Attack tab does not auto-scan on open (that caused concurrent runs on tab switches).

## Frontend Architecture
- **Stack**: Vite, Tailwind CSS v4, DaisyUI v5, Font Awesome; plain ES modules, no framework.
- **Source**: `frontend/src/`; one JS file per concern (see `frontend/README.md` for the full layout).
- **`src/main.js`**: app shell -- sidebar nav, hash-based router, header (status dot + task counter), theme toggle.
- **`src/state.js`**: central polling store -- `/api/status` (5s), `/api/system/info` (10s), `/api/network/status` (10s), `/api/system/version` (60s). Modules subscribe instead of polling independently.
- **`src/api.js`**: `apiGet()`/`apiPost()`/`apiDelete()` wrappers with AbortController timeouts. Always hits `/api` (relative path; works in dev via Vite proxy and in prod via nginx).
- **`src/ui.js`**: reusable fragments -- `pageHead()`, `card()`, `sectionTitle()`, `tabBar()`, `empty()`, `errorBox()`, `infoBox()`, `spinner()`, `riskBadge()`.
- **`src/toast.js`**: transient toasts (`notify()`) + persistent task handles (`startTask()` with `.done()`/`.fail()`/`.update()`). Tracks active task count shown in the header.
- **`src/style.css`**: Tailwind entry point, `chonky` / `chonky-dark` DaisyUI themes, `.nav-link` / `.surface` / `.console` component classes.
- **`src/modules/*.js`**: one file per hardware module, each exporting a `renderXxx(root)` function called by the router.
- **Local dev**: `cd frontend && npm install && CHONKY_API=http://192.168.178.78 npm run dev` -> `http://localhost:5173`, `/api` proxied to the Pi.
- **Production**: `npm run build` -> `frontend/dist/`, copied to `/var/www/html/` by `update.sh`. nginx serves the static files and proxies `/api` to gunicorn.

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
| PN532 | `nfc-list` shows pn532_uart | UART (TXD=GPIO15 Pin10, RXD=GPIO14 Pin8) | PN532 NFC/RFID module in HSU mode |
| Zigbee | `/dev/ttyUSB0` | USB | SONOFF Zigbee 3.0 USB Dongle Lite MG21 |
| Zigbee Sniffer | USB (VID:0451 PID:16AE) | USB | CC2531 USB Dongle, stock TI sniffer fw (bcd 25.17), pre-flashed, RX-only |
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
| `pipower5.service` | root | active | PiPower5 UPS HAT monitoring + shutdown |

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
- **Deploying manually**: If update.sh skips because git HEAD matches, run the copy steps manually -- backend files -> `/opt/chonkyflipper/`, `cd frontend && npm run build && cp -r dist/* /var/www/html/`, payloads, systemctl restart.

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
- `modules/__init__.py` no longer eagerly imports hardware modules (spidev, board, etc.). Individual modules can be imported directly inside the venv: `from modules.ir import IRModule`
- Mosquitto listens on 127.0.0.1:1883 only (localhost), not exposed to external networks
- Zigbee2MQTT's pnpm requires a writable home directory for the zigbee2mqtt user -- set to `/opt/zigbee2mqtt` in `/etc/passwd`
- Zigbee network map generation via API may time out on large networks; the API has a 15s timeout
- **PiPower5 shutdown**: Kali lacks `raspi-config` and `rpi-eeprom-update`, so `POWER_OFF_ON_HALT=1` cannot be set in the EEPROM. The SDSIG jumper stays on **PI3V3**. A systemd-shutdown hook at `/lib/systemd/system-shutdown/pipower-shutdown` sends an I2C command `[0xAC, 0x03, 0x00, 0xAE]` to the PiPower5 MCU (address 0x5C) to disable output. This hook runs AFTER all filesystems are unmounted and synced by systemd-shutdown -- confirmed clean (zero journal corruption). Do NOT use `dtoverlay=gpio-poweroff,gpio_pin=26` -- GPIO 26 defaults to LOW during early boot (internal pull-down), causing immediate power-cut (boot-loop). Both the UI "Power Off" button and 2s button press work: Pi shuts down cleanly, systemd-shutdown syncs filesystems, then the I2C hook tells the HAT to cut battery power.
