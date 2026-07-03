# Security Notes

This document records known security weaknesses in the ChonkyFlipper backend.
It is intentionally descriptive only. None of the items below are fixed in code
yet; they are tracked here so the risk is visible and can be prioritised later.

The device is a deliberately offensive pentesting rig, so some "weaknesses"
(deauth, BadUSB, packet injection) are the intended function. The items here are
about the control plane and how the tools are exposed, not the tools themselves.

## Threat model

The Flask API is reachable by anyone connected to the `Chonky_Control` access
point (`192.168.4.1`) and by anyone on the LAN the Pi is plugged into
(`192.168.178.78`). The AP itself is the only access control. Everything below
assumes an attacker who can reach port 80/5000.

## Findings

### 1. No authentication or authorization on the API
Every endpoint is unauthenticated. Anyone who can reach the web UI can trigger
WiFi deauth, run BadUSB payloads, capture traffic, store WiFi credentials, and
power off the Pi (`/api/system/poweroff`). There is no token, session, or origin
check.

- Impact: full control of the rig for anyone on the AP or LAN.
- Not fixed on purpose for now (no token added per current scope). A shared
  bearer token or a bound-to-localhost + reverse-proxy auth would be the
  smallest reasonable mitigation.

### 2. `shell=True` command execution in the WiFi module
`WiFiModule._run()` (`backend/modules/wifi.py`) builds a command string and runs
it with `subprocess.run(f'sudo -n {cmd}', shell=True, ...)`. Any caller that
passes attacker-influenced data into `cmd` creates a shell-injection path.

- Current callers appear to pass fixed/validated arguments, so this is a latent
  risk rather than a confirmed injection.
- Preferred fix: pass argument lists (`shell=False`) like the rest of the code
  base already does, or route everything through `utils.sudo_run()`.

### 3. Unescaped SSID / passphrase in wpa_supplicant config
`_write_wpa_config()` (`backend/routes/network.py`) interpolates the
user-supplied `ssid` and `password` directly into the wpa_supplicant config:

```
network={
    ssid="<ssid>"
    psk="<password>"
    ...
}
```

An SSID or passphrase containing a double quote or newline can break out of the
quoted value and inject additional config directives.

- Impact: config corruption at minimum; potentially unexpected supplicant
  behaviour.
- Preferred fix: validate/escape the values, or use `wpa_passphrase` to generate
  the network block.

### 4. CORS is fully open
`CORS(app)` in `backend/app.py` allows all origins. Combined with the lack of
auth (finding 1), any web page the operator's phone visits could script requests
against the API while on the AP.

- Preferred fix: restrict to the known frontend origin, or drop CORS entirely
  since the UI is served same-origin by nginx in production.

### 5. Flask debug server
`app.run(host='0.0.0.0', port=5000, debug=True)` in `backend/app.py` enables the
Werkzeug debugger. Production uses gunicorn so this only applies when the app is
run directly, but leaving `debug=True` risks exposing the interactive debugger
(remote code execution) if it is ever launched that way.

- Preferred fix: gate debug behind an env var, default off.

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
`_wifite_bg_task` in `routes/wifi.py` and `_sync_task` in `routes/ir.py`. A poll
can land on a different worker than the one that started a task, so status may be
reported inconsistently. Not a security issue, but it affects reliability and
would be fixed by sharing state (single worker, or an external store).

### Misleading UPS status
`_get_power_data()` in `routes/status.py` returns `ups_active: True` even inside
the exception branch, so if reading the PiPower5 HAT fails the API still claims
the UPS is active (with null battery fields). The exception branch should report
`ups_active: False` (or `None`) so the UI can distinguish "no UPS" from "UPS read
failed". Left unchanged for now since it is a behavioural change.

### maintenance-mode.sh invoked without sudo
`/api/network/maintenance` and `/api/network/apmode` call
`/opt/chonkyflipper/maintenance-mode.sh` directly (`routes/network.py`), while
every other privileged operation uses `sudo -n`. If the script needs root (it
reconfigures hostapd/wpa_supplicant), this is inconsistent and likely only works
because of some other privilege path. Worth confirming what the script actually
requires and making the invocation consistent with the rest of the code base.
