# Security Notes

This document records known security weaknesses in the ChonkyFlipper backend.
Some items have been fixed in code; their status is noted below.

The device is a deliberately offensive pentesting rig, so some "weaknesses"
(deauth, BadUSB, packet injection) are the intended function. The items here are
about the control plane and how the tools are exposed, not the tools themselves.

## Threat model

The Flask API is reachable by anyone connected to the `Chonky_Control` access
point (`192.168.4.1`) and by anyone on the LAN the Pi is plugged into
(`192.168.178.78`). When wlan1 is connected to an untrusted network for
internet access, the API is also reachable from that network. The AP itself is
the only access control. Everything below assumes an attacker who can reach
port 80/5000.

## Findings

### 1. No authentication or authorization on the API
Every endpoint is unauthenticated. Anyone who can reach the web UI can trigger
WiFi deauth, run BadUSB payloads, capture traffic, store WiFi credentials, and
power off the Pi (`/api/system/poweroff`).

- Impact: full control of the rig for anyone on the AP or LAN.
- **Fixed:** A minimal shared-secret token check has been added. If
  `/opt/chonkyflipper/config/api_token` exists, all `/api/` requests must
  include an `X-API-Token` header matching the file contents. The frontend
  prompts for the token on 401 and stores it in localStorage. If no token file
  exists, auth is disabled (backward compatible).

### 2. `shell=True` command execution in the WiFi module
`WiFiModule._run()` (`backend/modules/wifi.py`) builds a command string and runs
it with `subprocess.run(f'sudo -n {cmd}', shell=True, ...)`.

- **Fixed:** `_run()` now accepts argv lists (preferred, `shell=False`). All
  callers (capture_packets, capture_probes, wifite audit/scan) have been
  converted to pass argv lists. Route-level validation (`parse_int`/`parse_float`
  with bounds) prevents non-numeric values from reaching the command.
  The legacy string path is retained for any remaining callers but is no longer
  used by the main code paths.

### 3. Unescaped SSID / passphrase in wpa_supplicant config
`_write_wpa_config()` (`backend/routes/network.py`) interpolates the
user-supplied `ssid` and `password` directly into the wpa_supplicant config.

- **Fixed:** Values are now escaped via `_escape_wpa_value()` which strips
  newlines and escapes backslashes/quotes before interpolation.

### 4. CORS is fully open
`CORS(app)` in `backend/app.py` allows all origins.

- **Fixed:** CORS is now scoped to `/api/*` paths. In production, nginx serves
  the UI same-origin so CORS is not needed for the frontend. The wildcard is
  retained for `/api/*` to support the dev proxy, but combined with the token
  auth above, cross-origin abuse requires knowing the token.

### 5. Flask debug server
`app.run(host='0.0.0.0', port=5000, debug=True)` in `backend/app.py` enables the
Werkzeug debugger.

- **Fixed:** Debug mode is now gated behind `FLASK_DEBUG=1` env var, default off.

### 6. WiFi credentials stored in plaintext
`/opt/chonkyflipper/config/wifi-client.conf` and the maintenance config store the
SSID and password in plaintext (mode `0600`). Readable by root and the service
user. Acceptable for a single-user rig but worth noting.

### 7. Dependency hygiene
`backend/requirements.txt` pins `flask==2.3.3` and `flask-cors==4.0.0`, both
dated. `flask-cors 4.0.0` has published CVEs, and Werkzeug (Flask's dependency)
is not pinned at all, so a resolved version could drift. For a security-focused
module a quick dependency review / bump is a cheap win.

- Preferred fix: bump Flask/flask-cors to current patched releases and pin
  Werkzeug explicitly.

## Non-security correctness notes (related)

### Gunicorn per-worker state
The backend runs under gunicorn with 2 workers, but several pieces of state are
in-memory per worker: the module-detection cache in `routes/status.py`, the
cached hardware instances in `hardware.py`, and background-task handles like
`_sync_task` in `routes/ir.py` and `routes/badusb.py`. A poll can land on a
different worker than the one that started a task, so status may be reported
inconsistently. Not a security issue, but it affects reliability and would be
fixed by sharing state (single worker, or an external store).

