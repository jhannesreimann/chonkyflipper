/**
 * ChonkyFlipper Frontend - Mobile Web Dashboard
 * Connects to Flask backend API
 */

const API_BASE = window.location.origin.includes('localhost') 
    ? 'http://localhost:5000' 
    : '';

const API_URL = `${API_BASE}/api`;

// Global state
let systemStatus = {};
let activeModule = null;

// -----------------------------------------------------------
// INIT
// -----------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    init();
});

async function init() {
    log('🚀 ChonkyFlipper initializing...');
    
    // Setup module click handlers
    document.querySelectorAll('.module-item').forEach(item => {
        item.addEventListener('click', () => {
            const module = item.dataset.module;
            showModulePanel(module);
        });
    });
    
    // Initial status check
    await checkStatus();
    await updateSystemInfo();
    await fetchVersion();
    await updateNetworkStatus();

    // Start periodic updates
    setInterval(checkStatus, 5000);
    setInterval(updateSystemInfo, 10000);
    setInterval(fetchVersion, 60000);
    setInterval(updateNetworkStatus, 10000);
}

// -----------------------------------------------------------
// STATUS & SYSTEM
// -----------------------------------------------------------

async function checkStatus() {
    try {
        const response = await fetch(`${API_URL}/status`);
        if (!response.ok) throw new Error('API offline');
        
        const data = await response.json();
        systemStatus = data;
        
        // Update status indicator
        const indicator = document.getElementById('status-indicator');
        const dot = indicator.querySelector('.dot');
        const text = document.getElementById('status-text');
        
        dot.className = 'dot online';
        text.textContent = 'Online';
        
        // Update module statuses
        if (data.modules) {
            Object.entries(data.modules).forEach(([name, info]) => {
                const el = document.getElementById(`status-${name}`);
                if (el) {
                    const status = info.available ? '✓ Ready' : '✗ Offline';
                    el.textContent = status;
                }
            });
        }
        
        // Update hostname
        if (data.hostname) {
            document.getElementById('hostname').textContent = data.hostname;
        }

        // Update battery
        if (data.power) {
            const el = document.getElementById('battery');
            const pct = data.power.battery_percentage;
            if (pct !== null && pct !== undefined) {
                el.textContent = pct + '%' + (data.power.is_charging ? ' ⚡' : '');
                el.className = 'value ' + (pct >= 60 ? 'battery-good' : pct >= 20 ? 'battery-warn' : 'battery-low');
            } else {
                el.textContent = 'UPS Active';
                el.className = 'value';
            }
        }
        
    } catch (error) {
        const indicator = document.getElementById('status-indicator');
        const dot = indicator.querySelector('.dot');
        const text = document.getElementById('status-text');
        
        dot.className = 'dot offline';
        text.textContent = 'Offline';
        
        console.error('Status check failed:', error);
    }
}

async function updateSystemInfo() {
    try {
        const response = await fetch(`${API_URL}/system/info`);
        if (!response.ok) return;

        const data = await response.json();

        if (data.uptime) {
            document.getElementById('uptime').textContent = data.uptime;
        }
        if (data.temperature) {
            document.getElementById('temp').textContent = data.temperature;
        }
    } catch (error) {
        // Silent fail - status check handles connectivity
    }
}

async function fetchVersion() {
    try {
        const response = await fetch(`${API_URL}/system/version`);
        if (!response.ok) return;

        const data = await response.json();
        const el = document.getElementById('current-version');
        if (el && data.sha && data.sha !== 'unknown') {
            el.textContent = `${data.branch || 'main'} @ ${data.sha}`;
            el.className = 'value';
        }
    } catch (error) {
        // Silent fail
    }
}

function showModulePanel(module) {
    // Hide all panels
    document.querySelectorAll('.module-panel').forEach(p => {
        p.classList.remove('active');
    });
    
    // Remove active state from all module items
    document.querySelectorAll('.module-item').forEach(i => {
        i.classList.remove('active');
    });
    
    // Show selected panel
    const panel = document.getElementById(`panel-${module}`);
    if (panel) {
        panel.classList.add('active');
        activeModule = module;
        
        // Highlight module
        const item = document.querySelector(`.module-item[data-module="${module}"]`);
        if (item) item.classList.add('active');
        
        // Auto-load data for specific panels
        if (module === 'ir') {
            irLoadSignals();
            irLoadPayloads();
        }

        log(`Opened ${module.toUpperCase()} panel`);
    }
}

// -----------------------------------------------------------
// WI-FI FUNCTIONS
// -----------------------------------------------------------

async function wifiScan() {
    log('🔍 Scanning Wi-Fi networks...');
    setLoading('wifi-results', true);
    
    try {
        const response = await fetch(`${API_URL}/wifi/scan`);
        const data = await response.json();
        
        const container = document.getElementById('wifi-results');
        
        if (data.networks && data.networks.length > 0) {
            const html = `
                <table>
                    <thead>
                        <tr>
                            <th>Network</th>
                            <th>BSSID</th>
                            <th>Ch</th>
                            <th>Signal</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.networks.map(net => `
                            <tr>
                                <td>${escapeHtml(net.essid || 'Hidden')}</td>
                                <td>${net.bssid || '-'}</td>
                                <td>${net.channel || '-'}</td>
                                <td>${net.signal_dbm || '-'} dBm</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
            container.innerHTML = html;
            log(`📡 Found ${data.networks.length} networks`);
        } else {
            container.innerHTML = '<p class="placeholder">No networks found</p>';
        }
    } catch (error) {
        log('❌ Wi-Fi scan failed: ' + error.message);
        document.getElementById('wifi-results').innerHTML = 
            '<p class="placeholder" style="color: #e94560;">Scan failed</p>';
    } finally {
        setLoading('wifi-results', false);
    }
}

async function wifiMonitorMode() {
    log('📡 Enabling monitor mode...');
    
    try {
        const response = await fetch(`${API_URL}/wifi/start_monitor`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            log('✅ Monitor mode enabled: ' + data.interface);
        } else {
            log('❌ Monitor mode failed: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        log('❌ Monitor mode error: ' + error.message);
    }
}

async function wifiCapture() {
    log('💾 Starting packet capture (10s)...');
    
    try {
        const response = await fetch(`${API_URL}/wifi/capture`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration: 10 })
        });
        const data = await response.json();
        
        if (data.success) {
            log(`✅ Capture saved: ${data.filename} (${data.size_bytes} bytes)`);
        } else {
            log('❌ Capture failed: ' + (data.error || 'Unknown'));
        }
    } catch (error) {
        log('❌ Capture error: ' + error.message);
    }
}

// -----------------------------------------------------------
// BLUETOOTH FUNCTIONS
// -----------------------------------------------------------

async function bleScan() {
    log('📶 Scanning BLE devices...');
    setLoading('ble-results', true);
    
    try {
        const response = await fetch(`${API_URL}/bluetooth/scan`);
        const data = await response.json();
        
        const container = document.getElementById('ble-results');
        
        if (data.devices && data.devices.length > 0) {
            const html = `
                <table>
                    <thead>
                        <tr>
                            <th>Device</th>
                            <th>MAC</th>
                            <th>RSSI</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.devices.map(dev => `
                            <tr>
                                <td>${escapeHtml(dev.name || 'Unknown')}</td>
                                <td>${dev.mac || '-'}</td>
                                <td>${dev.rssi || '-'} dBm</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
            container.innerHTML = html;
            log(`📶 Found ${data.devices.length} BLE devices`);
        } else {
            container.innerHTML = '<p class="placeholder">No devices found</p>';
        }
    } catch (error) {
        log('❌ BLE scan failed: ' + error.message);
    } finally {
        setLoading('ble-results', false);
    }
}

async function bleBeacons() {
    log('📡 Scanning for BLE beacons...');
    
    try {
        const response = await fetch(`${API_URL}/bluetooth/beacons`);
        const data = await response.json();
        
        if (data.beacons && data.beacons.length > 0) {
            log(`📡 Found ${data.beacons.length} beacons`);
        } else {
            log('ℹ️ No beacons detected');
        }
    } catch (error) {
        log('❌ Beacon scan failed: ' + error.message);
    }
}

// -----------------------------------------------------------
// IR FUNCTIONS
// -----------------------------------------------------------

async function irRecord() {
    const status = document.getElementById('ir-record-status');
    status.style.display = 'block';
    status.className = 'status-msg info';
    status.textContent = 'Recording 5 seconds... point remote at receiver and press buttons.';

    try {
        const response = await fetch(`${API_URL}/ir/record`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration: 5 })
        });
        const data = await response.json();

        if (data.success) {
            status.className = 'status-msg success';
            status.textContent = 'Captured: ' + (data.preview || data.name);
            log('IR signal recorded: ' + data.name + ' (' + data.protocol + ')');
            irLoadSignals();
        } else {
            status.className = 'status-msg error';
            status.textContent = data.error || 'Record failed';
            log('IR record failed: ' + (data.error || 'Unknown'));
        }
    } catch (error) {
        status.className = 'status-msg error';
        status.textContent = 'Record error: ' + error.message;
    }
}

async function irLoadSignals() {
    try {
        const response = await fetch(`${API_URL}/ir/signals`);
        const data = await response.json();
        const table = document.getElementById('ir-signals-table');
        const body = document.getElementById('ir-signals-body');
        const empty = document.getElementById('ir-signals-empty');

        if (data.signals && data.signals.length > 0) {
            table.style.display = '';
            empty.style.display = 'none';
            body.innerHTML = data.signals.map(s => `
                <tr>
                    <td>${escapeHtml(s.name)}</td>
                    <td>${escapeHtml(s.protocol || '?')}</td>
                    <td>${s.pulses || 0}</td>
                    <td><button class="btn btn-secondary" style="padding:4px 10px;font-size:0.75rem;"
                            onclick="irTransmitSignal('${escapeHtmlAttr(s.name)}')">Send</button></td>
                </tr>`).join('');
        } else {
            table.style.display = 'none';
            empty.style.display = '';
        }
    } catch (error) {
        log('IR signal list error: ' + error.message);
    }
}

async function irTransmitSignal(name) {
    log('Transmitting: ' + name);
    try {
        const response = await fetch(`${API_URL}/ir/transmit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_id: name })
        });
        const data = await response.json();
        if (data.success) {
            log('Signal sent: ' + name);
        } else {
            log('Transmit failed: ' + (data.error || 'Unknown'));
        }
    } catch (error) {
        log('Transmit error: ' + error.message);
    }
}

async function irLoadPayloads() {
    try {
        const response = await fetch(`${API_URL}/ir/payloads`);
        const data = await response.json();
        const list = document.getElementById('ir-payloads-list');

        if (data.payloads && data.payloads.length > 0) {
            list.innerHTML = data.payloads.map(p => `
                <div class="payload-item">
                    <div>
                        <strong>${escapeHtml(p.name)}</strong>
                        <span style="color:var(--text-secondary);font-size:0.75rem;">
                            ${escapeHtml(p.protocol)} - ${escapeHtml(p.description)}
                        </span>
                    </div>
                    <button class="btn btn-secondary" style="padding:4px 10px;font-size:0.75rem;"
                            onclick="irSendPayload('${escapeHtmlAttr(p.id)}')">Send</button>
                </div>`).join('');
        } else {
            list.innerHTML = '<p class="placeholder">No payloads available.</p>';
        }
    } catch (error) {
        log('IR payload list error: ' + error.message);
    }
}

async function irSendPayload(id) {
    log('Sending payload: ' + id);
    try {
        const response = await fetch(`${API_URL}/ir/payloads/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ payload_id: id })
        });
        const data = await response.json();
        if (data.success) {
            log('Payload sent: ' + id);
        } else {
            log('Payload failed: ' + (data.error || 'Unknown'));
        }
    } catch (error) {
        log('Payload error: ' + error.message);
    }
}

async function irBruteforce() {
    const status = document.getElementById('ir-bruteforce-status');
    status.style.display = 'block';
    status.className = 'status-msg info';
    status.textContent = 'Sending power codes... watch the target device.';

    log('Brute forcing IR power codes...');
    try {
        const response = await fetch(`${API_URL}/ir/bruteforce`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ brands: ['samsung', 'generic'] })
        });
        const data = await response.json();
        if (data.success) {
            status.className = 'status-msg success';
            status.textContent = 'Sent ' + data.sent + ' power codes.';
            log('Brute force done: ' + data.sent + ' codes sent');
        } else {
            status.className = 'status-msg error';
            status.textContent = data.error || 'Failed';
        }
    } catch (error) {
        status.className = 'status-msg error';
        status.textContent = 'Error: ' + error.message;
    }
}

// -----------------------------------------------------------
// SUB-1GHZ FUNCTIONS
// -----------------------------------------------------------

async function subghzRecord() {
    const freq = document.getElementById('subghz-freq').value;
    log(`🔴 Recording Sub-1GHz @ ${freq} MHz (3s)...`);
    
    try {
        const response = await fetch(`${API_URL}/subghz/record`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ frequency: parseFloat(freq), duration: 3 })
        });
        const data = await response.json();
        
        if (data.success) {
            log(`✅ Signal saved: ${data.name}`);
        } else {
            log('❌ Record failed: ' + (data.error || 'Unknown'));
        }
    } catch (error) {
        log('❌ Sub-1GHz error: ' + error.message);
    }
}

async function subghzTransmit() {
    log('📤 Transmit Sub-1GHz - select signal...');
}

// -----------------------------------------------------------
// NFC FUNCTIONS
// -----------------------------------------------------------

async function nfcRead() {
    log('📖 Reading NFC card...');
    
    try {
        const response = await fetch(`${API_URL}/nfc/read`);
        const data = await response.json();
        
        const container = document.getElementById('nfc-card');
        
        if (data.uid) {
            container.innerHTML = `
                <div class="card-info">
                    <p><strong>UID:</strong> ${data.uid}</p>
                    <p><strong>Type:</strong> ${data.card_type || 'Unknown'}</p>
                    <p><strong>Timestamp:</strong> ${new Date().toLocaleTimeString()}</p>
                </div>
            `;
            log(`✅ Card read: ${data.uid}`);
        } else {
            container.innerHTML = '<p class="placeholder">No card detected</p>';
            log('ℹ️ No card detected');
        }
    } catch (error) {
        log('❌ NFC read error: ' + error.message);
    }
}

async function nfcClone() {
    log('📋 NFC clone - read card first, then write to magic card');
}

// -----------------------------------------------------------
// BADUSB FUNCTIONS
// -----------------------------------------------------------

async function badusbExecute(payload) {
    log(`💉 Executing BadUSB payload: ${payload}`);
    
    const warnings = {
        'rickroll': '🎵 Opening Rick Astley on target...',
        'reverse_shell': '🐚 Attempting reverse shell...',
        'wifi_grab': '📶 Extracting WiFi credentials...'
    };
    
    log('⚠️ ' + (warnings[payload] || 'Executing payload'));
    
    try {
        const response = await fetch(`${API_URL}/badusb/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ payload })
        });
        const data = await response.json();
        
        if (data.success) {
            log('✅ Payload executed');
        } else {
            log('❌ ' + (data.message || 'Payload failed'));
        }
    } catch (error) {
        log('❌ BadUSB error: ' + error.message);
    }
}

// -----------------------------------------------------------
// UTILITIES
// -----------------------------------------------------------

function log(message) {
    const container = document.getElementById('activity-log');
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
    
    // Keep only last 50 entries
    while (container.children.length > 50) {
        container.removeChild(container.firstChild);
    }
}

function setLoading(elementId, loading) {
    const el = document.getElementById(elementId);
    if (loading) {
        el.dataset.originalContent = el.innerHTML;
        el.innerHTML = '<div style="display: flex; justify-content: center; padding: 20px;"><div class="spinner"></div></div>';
    } else if (el.dataset.originalContent) {
        // Content will be replaced by actual data
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// -----------------------------------------------------------
// NETWORK / SETTINGS FUNCTIONS
// -----------------------------------------------------------

let selectedWifiSsid = null;
let selectedWifiBssid = null;

async function updateNetworkStatus() {
    try {
        const response = await fetch(`${API_URL}/network/status`);
        const data = await response.json();

        // LAN status
        const eth0El = document.getElementById('net-eth0');
        if (data.ethernet && data.ethernet.connected) {
            eth0El.textContent = 'Connected (' + (data.ethernet.ip || 'no IP') + ')';
            eth0El.className = 'net-value online';
        } else {
            eth0El.textContent = 'Not connected';
            eth0El.className = 'net-value offline';
        }

        // WiFi client status
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

        // Internet
        const internetEl = document.getElementById('net-internet');
        if (data.internet_available) {
            const source = data.internet_source;
            const label = source === 'ethernet' ? 'Online (LAN)' :
                          source === 'wifi' ? 'Online (WiFi)' :
                          source === 'ap_client' ? 'Online (AP client)' : 'Online';
            internetEl.textContent = label;
            internetEl.className = 'net-value online';
        } else {
            internetEl.textContent = 'Offline';
            internetEl.className = 'net-value offline';
        }

        // Enable/disable update button
        const updateBtn = document.getElementById('update-btn');
        const updateHint = document.getElementById('update-hint');
        if (data.internet_available) {
            updateBtn.disabled = false;
            updateHint.textContent = 'Internet available via ' +
                (data.internet_source || 'unknown') + '. Updates will not disconnect you.';
        } else {
            updateBtn.disabled = true;
            updateHint.textContent = 'Connect LAN cable or WiFi client for internet access.';
        }

        // Show/hide UI based on connection state
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

async function scanWifiNetworks() {
    const table = document.getElementById('wifi-networks-table');
    const body = document.getElementById('wifi-networks-body');
    const status = document.getElementById('wifi-scan-status');
    const scanBtn = document.getElementById('wifi-scan-btn');

    scanBtn.disabled = true;
    scanBtn.textContent = 'Scanning...';
    table.style.display = 'none';
    status.style.display = 'block';
    status.className = 'status-msg info';
    status.textContent = 'Scanning for networks...';

    try {
        const response = await fetch(`${API_URL}/network/wifi-scan`);
        const data = await response.json();

        if (!data.success) {
            status.className = 'status-msg error';
            status.textContent = data.error || 'Scan failed';
            scanBtn.disabled = false;
            scanBtn.textContent = '🔍 Scan';
            return;
        }

        if (!data.networks || data.networks.length === 0) {
            status.className = 'status-msg info';
            status.textContent = 'No networks found.';
            scanBtn.disabled = false;
            scanBtn.textContent = '🔍 Scan';
            return;
        }

        status.style.display = 'none';
        table.style.display = '';

        body.innerHTML = data.networks.map(net => {
            const ssid = net.ssid || '(hidden)';
            const signal = net.signal_dbm ? net.signal_dbm + ' dBm' : '?';
            const sec = net.security || '?';
            const bars = signalToBars(net.signal_dbm);
            return `
                <tr class="wifi-network-row" onclick="selectWifiNetwork('${escapeHtmlAttr(ssid)}', '${net.bssid || ''}')">
                    <td>${escapeHtml(ssid)}</td>
                    <td>${bars} ${signal}</td>
                    <td>${escapeHtml(sec)}</td>
                    <td><button class="btn btn-secondary" style="padding:4px 10px;font-size:0.75rem;">→</button></td>
                </tr>`;
        }).join('');

        log('Found ' + data.networks.length + ' WiFi networks');

    } catch (error) {
        status.className = 'status-msg error';
        status.textContent = 'Scan error: ' + error.message;
    }

    scanBtn.disabled = false;
    scanBtn.textContent = '🔍 Scan';
}

function selectWifiNetwork(ssid, bssid) {
    selectedWifiSsid = ssid;
    selectedWifiBssid = bssid;

    document.getElementById('wifi-selected-ssid').textContent = ssid;
    document.getElementById('wifi-password-input').value = '';
    document.getElementById('wifi-password-prompt').style.display = '';

    // Highlight selected row
    document.querySelectorAll('.wifi-network-row').forEach(r => r.classList.remove('active'));
    const rows = document.querySelectorAll('.wifi-network-row');
    rows.forEach(r => {
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
        const response = await fetch(`${API_URL}/network/wifi-connect`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ssid: selectedWifiSsid, password: password })
        });

        const data = await response.json();

        if (data.success) {
            status.className = 'status-msg success';
            status.textContent = 'Connected to ' + selectedWifiSsid +
                (data.ip ? ' (' + data.ip + ')' : '');
            log('Connected to WiFi: ' + selectedWifiSsid);
            updateNetworkStatus();
        } else {
            status.className = 'status-msg error';
            status.textContent = data.error || 'Connection failed';
            log('WiFi connection failed: ' + (data.error || 'Unknown error'));
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
        const response = await fetch(`${API_URL}/network/wifi-disconnect`, {
            method: 'POST'
        });
        const data = await response.json();

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

function signalToBars(dbm) {
    if (dbm === null || dbm === undefined) return '';
    if (dbm >= -50) return '▁▃▅▇';
    if (dbm >= -65) return '▁▃▅';
    if (dbm >= -75) return '▁▃';
    return '▁';
}

function escapeHtmlAttr(str) {
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

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
        await fetch(`${API_URL}/system/poweroff`, { method: 'POST' });
        log('Device is powering off. Reconnect after restart.');
    } catch (error) {
        log('Device is powering off. Reconnect after restart.');
    }
}

async function runSystemUpdate() {
    const outputBox = document.getElementById('update-output');
    outputBox.style.display = 'block';
    outputBox.innerHTML = '<p>Starting update...</p>';

    log('Starting system update from GitHub...');

    try {
        const response = await fetch(`${API_URL}/system/update`, {
            method: 'POST'
        });

        const data = await response.json();

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
                        log('Update complete  --  backend is back online.');
                        fetchVersion();
                        checkStatus();
                    }
                } catch {
                    // Still restarting
                }

                if (attempts > 30) {
                    clearInterval(checkBack);
                    outputBox.innerHTML = '<pre class="error">Update timed out. Check system status.</pre>';
                    log('Update timeout  --  backend did not return after 30s.');
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

// Periodic network status update
setInterval(updateNetworkStatus, 10000);

// Global error handler
window.addEventListener('error', (e) => {
    log('JavaScript error: ' + e.message);
});
