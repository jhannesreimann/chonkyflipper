# ChonkyFlipper Backend

Flask + Gunicorn API server for the ChonkyFlipper pentesting rig. Runs on
Raspberry Pi 4 with Kali Linux ARM64. All hardware modules are lazy-loaded
on first use via `hardware.py`.

## Stack

- **Flask** 2.3.x with Blueprint-based routing
- **Gunicorn** (2 workers, bind `127.0.0.1:5000`)
- **nginx** reverse proxy on `:80` (serves frontend, proxies `/api` to gunicorn)
- **SQLite** with WAL mode for payload databases (IR library, BadUSB library)

## Layout

```
backend/
  app.py              Flask app: CORS, token auth, blueprint registration
  config.py           Centralized paths and constants
  hardware.py         Lazy module factory (importlib-based)
  utils.py            API helpers, request validation, SyncTask
  routes/             Flask blueprints (one per hardware module)
    status.py         System info, module detection, power, updates
    wifi.py           WiFi scan, monitor mode, capture, wifite
    bluetooth.py      BLE scan, GATT, spoofing, HCI capture, classic BT
    ir.py             IR record/transmit, library browser, IRDB sync
    subghz.py         CC1101 record/transmit/scan/jam/decode
    nfc.py            PN532 read/write/dump/clone/mfoc
    badusb.py         Payload library, filesystem, execution, auto-fire
    zigbee.py         Zigbee2MQTT bridge (MQTT)
    zigbee_audit.py   CC2531 + KillerBee security auditing
    network.py        AP/ethernet/wifi-client status, wpa_supplicant
    loot.py           Captured file browser
  modules/
    base_db.py        Shared SQLite base class (WAL, schema versioning, sync state)
    base_sync.py      Shared git sync base class (clone, fetch, merge, SHA tracking)
    wifi.py           Alfa adapter control (RTL8811AU driver)
    bluetooth/        BLE + Classic BT package
      beacons.py      iBeacon / Eddystone parsing and encoding
      parsers.py      hcitool / sdptool / bettercap output parsers
      module.py       BluetoothModule (scan, GATT, spoof, capture, pair)
    ir/               IR package
      module.py       IR record/transmit via LIRC kernel drivers
      db.py           SQLite IR payload database (BasePayloadDB)
      sync.py         Flipper-IRDB incremental git sync (BaseGitSync)
      protocols.py    Protocol encoders (NEC, Samsung32, Sony SIRC, Panasonic, RC5)
    cc1101.py         Sub-1GHz transceiver (SPI + lgpio)
    pn532.py          NFC/RFID reader/writer (libnfc CLI tools)
    zigbee.py         Zigbee2MQTT MQTT bridge
    zigbee_audit.py   KillerBee + CC2531 security auditing
    badusb/           USB HID package
      interpreter.py  DuckyScript 3.0 parser (variables, IF/WHILE, expressions)
      keymaps.py      Keyboard layout tables (us/de) + modifier bitmasks
      backends.py     HidBackend (/dev/hidg0) + DryRunBackend (preview)
      module.py       Filesystem payload discovery and execution
      db.py           SQLite payload library (BasePayloadDB)
      sync.py         GitHub repo sync (BaseGitSync)
  requirements.txt
```

## Architecture

### Module loading

`hardware.py` maps module names to dotted class paths. `get_module('wifi')`
imports `modules.wifi.WiFiModule` on first call and caches the instance.
Packages (`bluetooth/`, `ir/`, `badusb/`) re-export their main class from
`__init__.py` so the import path stays simple.

### Shared base classes

- **`BasePayloadDB`** (`base_db.py`): SQLite connection management with WAL,
  busy timeout, `check_same_thread=False`, schema versioning, and sync state
  key-value storage. Inherited by `ir/db.py` and `badusb/db.py`.
- **`BaseGitSync`** (`base_sync.py`): Git operations (clone, fetch, merge,
  SHA comparison, changed-file diff). Inherited by `ir/sync.py` and
  `badusb/sync.py`.

### Route helpers

- **`api_success(data)`**: Non-mutating success response (`success: True`).
- **`api_error(msg, code)`**: Standard error response.
- **`api_from_result(result)`**: Converts a module result dict to an API
  response based on `result['success']`.
- **`parse_int` / `parse_float`**: Request parameter validation with bounds.
- **`SyncTask`**: Background sync management with lock, progress callback, and
  status polling. Used by IR and BadUSB sync routes.

### API authentication

If `/opt/chonkyflipper/config/api_token` exists, all `/api/` requests must
include an `X-API-Token` header matching the file contents. If no token file
exists, auth is disabled (backward compatible).

## Development

### Running locally (no hardware)

```bash
cd backend
python3 app.py
```

The server starts on `:5000` with debug mode off. Set `FLASK_DEBUG=1` to
enable the Werkzeug debugger. Hardware modules will fail on import if the
required libraries (spidev, bleak, lgpio, etc.) are not installed.

### On the Pi

```bash
cd /opt/chonkyflipper
source venv/bin/activate
python3 app.py
```

Or via systemd: `sudo systemctl restart chonkyflipper`

### Importing modules for testing

```python
from modules.ir import IRModule
from modules.ir.db import IRPayloadDB
from modules.ir.sync import IRDBSync
from modules.bluetooth import BluetoothModule
from modules.badusb import BadUSBModule
```

## Deployment

`update.sh` (run as root via sudo) handles deployment:
1. `git pull` in `/home/kali/chonkyflipper/`
2. `pip install -r requirements.txt` in the venv (as chonky user)
3. Copy backend files to `/opt/chonkyflipper/`
4. Build frontend and copy to `/var/www/html/`
5. Restart `chonkyflipper.service`

The venv at `/opt/chonkyflipper/venv` must be owned by `chonky:chonky`.
