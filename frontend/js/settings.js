/**
 * ChonkyFlipper Frontend - Network Status, WiFi Connect, Power, Update
 */

let selectedWifiSsid = null;
let selectedWifiBssid = null;

// ------------------------------------------------------------------ Network Status

async function updateNetworkStatus() {
    try {
        const data = await apiGet('/network/status');

        const eth0El = document.getElementById('net-eth0');
        if (data.ethernet && data.ethernet.connected) {
            eth0El.textContent = 'Connected (' + (data.ethernet.ip || 'no IP') + ')';
            eth0El.className = 'net-value online';
        } else {
            eth0El.textContent = 'Not connected';
            eth0El.className = 'net-value offline';
        }

        const wlan1El = document.getElementById('net-wlan1');
        const wifiSection = document.getElementById('wifi-scanner-section');
        if (data.wifi_client && data.wifi_client.adapter_present) {
            wifiSection.style.display = '';
            if (data.wifi_client.connected) {
                wlan1El.textContent = 'Connected to ' + data.wifi_client.ssid;
                wlan1El.className = 'net-value online';
            } else {
                wlan1El.textContent = 'Not connected';
                wlan1El.className = 'net-value warning';
            }
        } else {
            wifiSection.style.display = 'none';
            wlan1El.textContent = 'Adapter not found';
            wlan1El.className = 'net-value offline';
        }

        const internetEl = document.getElementById('net-internet');
        if (data.internet_available) {
            const source = data.internet_source;
            internetEl.textContent = source === 'ethernet' ? 'Online (LAN)' :
                source === 'wifi' ? 'Online (WiFi)' :
                source === 'ap_client' ? 'Online (AP client)' : 'Online';
            internetEl.className = 'net-value online';
        } else {
            internetEl.textContent = 'Offline';
            internetEl.className = 'net-value offline';
        }

        const updateBtn = document.getElementById('update-btn');
        const updateHint = document.getElementById('update-hint');
        if (data.internet_available) {
            updateBtn.disabled = false;
            updateHint.textContent = 'Internet available via ' + (data.internet_source || 'unknown') + '. Updates will not disconnect you.';
        } else {
            updateBtn.disabled = true;
            updateHint.textContent = 'Connect LAN cable or WiFi client for internet access.';
        }

        const discBtn = document.getElementById('wifi-disconnect-btn');
        const scanBtn = document.getElementById('wifi-scan-btn');
        const netTable = document.getElementById('wifi-networks-table');
        const pwPrompt = document.getElementById('wifi-password-prompt');
        const scanStatus = document.getElementById('wifi-scan-status');

        if (data.wifi_client && data.wifi_client.connected) {
            discBtn.style.display = '';
            scanBtn.style.display = 'none';
            netTable.style.display = 'none';
            pwPrompt.style.display = 'none';
            scanStatus.style.display = 'none';
        } else {
            discBtn.style.display = 'none';
            scanBtn.style.display = '';
        }
    } catch (error) {
        console.log('Network status check failed:', error);
    }
}

// ------------------------------------------------------------------ WiFi Scanner (settings panel)

async function scanWifiNetworks() {
    const table = document.getElementById('wifi-networks-table');
    const body = document.getElementById('wifi-networks-body');
    const scanBtn = document.getElementById('wifi-scan-btn');

    scanBtn.disabled = true;
    scanBtn.textContent = 'Scanning...';
    table.style.display = 'none';
    setLoading('wifi-scan-status', true);

    try {
        const data = await apiGet('/wifi/scan');
        setLoading('wifi-scan-status', false);

        if (!data.success) {
            document.getElementById('wifi-scan-status').innerHTML =
                `<p class="placeholder" style="color:#e94560;">${escapeHtml(data.error || 'Scan failed')}</p>`;
            scanBtn.disabled = false;
            scanBtn.textContent = 'Scan';
            return;
        }
        if (!data.networks || data.networks.length === 0) {
            document.getElementById('wifi-scan-status').innerHTML =
                '<p class="placeholder">No networks found.</p>';
            scanBtn.disabled = false;
            scanBtn.textContent = 'Scan';
            return;
        }

        document.getElementById('wifi-scan-status').innerHTML = '';
        table.style.display = '';

        body.innerHTML = data.networks.map(net => {
            const ssid = net.ssid || '(hidden)';
            const signal = net.signal_dbm ? net.signal_dbm + ' dBm' : '?';
            const sec = net.security || 'Open';
            const bars = signalToBars(net.signal_dbm);
            return `<tr class="wifi-network-row" onclick="selectWifiNetwork('${escapeHtmlAttr(ssid)}','${net.bssid||''}')"><td>${escapeHtml(ssid)}</td><td>${bars} ${signal}</td><td>${escapeHtml(sec)}</td><td><button class="btn btn-secondary" style="padding:4px 10px;font-size:0.75rem;">→</button></td></tr>`;
        }).join('');

        log('Found ' + data.networks.length + ' WiFi networks');
    } catch (error) {
        setLoading('wifi-scan-status', false);
        document.getElementById('wifi-scan-status').innerHTML =
            '<p class="placeholder" style="color:#e94560;">Scan error: ' + escapeHtml(error.message) + '</p>';
    }

    scanBtn.disabled = false;
    scanBtn.textContent = 'Scan';
}

function selectWifiNetwork(ssid, bssid) {
    selectedWifiSsid = ssid;
    selectedWifiBssid = bssid;
    document.getElementById('wifi-selected-ssid').textContent = ssid;
    document.getElementById('wifi-password-input').value = '';
    document.getElementById('wifi-password-prompt').style.display = '';
    document.querySelectorAll('.wifi-network-row').forEach(r => r.classList.remove('active'));
    document.querySelectorAll('.wifi-network-row').forEach(r => {
        if (r.cells[0].textContent === ssid) r.classList.add('active');
    });
}

function cancelWifiConnect() {
    document.getElementById('wifi-password-prompt').style.display = 'none';
    selectedWifiSsid = null;
    selectedWifiBssid = null;
}

async function connectToNetwork() {
    const password = document.getElementById('wifi-password-input').value;
    if (!password || !selectedWifiSsid) return;

    const status = document.getElementById('wifi-scan-status');
    status.style.display = 'block';
    status.className = 'status-msg info';
    status.textContent = 'Connecting to ' + selectedWifiSsid + '...';
    document.getElementById('wifi-password-prompt').style.display = 'none';

    try {
        const data = await apiPost('/network/wifi-connect', { ssid: selectedWifiSsid, password });
        if (data.success) {
            status.className = 'status-msg success';
            status.textContent = 'Connected to ' + selectedWifiSsid + (data.ip ? ' (' + data.ip + ')' : '');
            log('Connected to WiFi: ' + selectedWifiSsid);
            updateNetworkStatus();
        } else {
            status.className = 'status-msg error';
            status.textContent = data.error || 'Connection failed';
        }
    } catch (error) {
        status.className = 'status-msg error';
        status.textContent = 'Connection error: ' + error.message;
    }
    selectedWifiSsid = null;
    selectedWifiBssid = null;
}

async function disconnectWifi() {
    const status = document.getElementById('wifi-scan-status');
    status.style.display = 'block';
    status.className = 'status-msg info';
    status.textContent = 'Disconnecting...';
    try {
        const data = await apiPost('/network/wifi-disconnect');
        if (data.success) {
            status.className = 'status-msg success';
            status.textContent = 'Disconnected.';
            document.getElementById('wifi-networks-table').style.display = 'none';
            updateNetworkStatus();
            log('WiFi client disconnected');
        } else {
            status.className = 'status-msg error';
            status.textContent = data.error || 'Disconnect failed';
        }
    } catch (error) {
        status.className = 'status-msg error';
        status.textContent = 'Disconnect error: ' + error.message;
    }
}

// ------------------------------------------------------------------ Power & Update

function showPoweroffDialog() {
    document.getElementById('poweroff-dialog').style.display = 'flex';
}

function hidePoweroffDialog() {
    document.getElementById('poweroff-dialog').style.display = 'none';
}

async function confirmPoweroff() {
    hidePoweroffDialog();
    log('Shutting down...');
    try {
        await apiPost('/system/poweroff');
    } catch (error) { /* expected - server shuts down */ }
    log('Device is powering off. Reconnect after restart.');
}

async function runSystemUpdate() {
    const outputBox = document.getElementById('update-output');
    outputBox.style.display = 'block';
    outputBox.innerHTML = '<p>Starting update...</p>';
    log('Starting system update from GitHub...');

    try {
        const data = await apiPost('/system/update');
        if (data.success) {
            outputBox.innerHTML = `<pre class="success">${escapeHtml(data.message || 'Update started')}</pre>`;
            log(data.message);

            let attempts = 0;
            const checkBack = setInterval(async () => {
                attempts++;
                outputBox.innerHTML = `<pre class="success">Update in progress... (${attempts})</pre>`;
                try {
                    const resp = await fetch(`${API_URL}/status`);
                    if (resp.ok) {
                        clearInterval(checkBack);
                        outputBox.innerHTML = '<pre class="success">Update complete.</pre>';
                        log('Update complete - backend is back online.');
                        fetchVersion();
                        checkStatus();
                    }
                } catch { /* still restarting */ }
                if (attempts > 30) {
                    clearInterval(checkBack);
                    outputBox.innerHTML = '<pre class="error">Update timed out. Check system status.</pre>';
                    log('Update timeout - backend did not return after 30s.');
                }
            }, 2000);
        } else {
            outputBox.innerHTML = `<pre class="error">${escapeHtml(data.error || 'Update failed')}</pre>`;
            log('Update failed: ' + (data.error || 'Check internet connection'));
        }
    } catch (error) {
        outputBox.innerHTML = `<pre class="error">${escapeHtml(error.message)}</pre>`;
        log('Update error: ' + error.message);
    }
}
