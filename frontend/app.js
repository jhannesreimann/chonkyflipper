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

// ═══════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════

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
    
    // Start periodic updates
    setInterval(checkStatus, 5000);
    setInterval(updateSystemInfo, 10000);
}

// ═══════════════════════════════════════════════════════════
// STATUS & SYSTEM
// ═══════════════════════════════════════════════════════════

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
        
        log(`📂 Opened ${module.toUpperCase()} panel`);
    }
}

// ═══════════════════════════════════════════════════════════
// WI-FI FUNCTIONS
// ═══════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════
// BLUETOOTH FUNCTIONS
// ═══════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════
// IR FUNCTIONS
// ═══════════════════════════════════════════════════════════

async function irRecord() {
    log('🔴 Recording IR signal (5s)...');
    
    try {
        const response = await fetch(`${API_URL}/ir/record`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration: 5 })
        });
        const data = await response.json();
        
        if (data.success) {
            log(`✅ IR signal saved: ${data.name}`);
        } else {
            log('❌ IR record failed: ' + (data.error || 'Unknown'));
        }
    } catch (error) {
        log('❌ IR record error: ' + error.message);
    }
}

async function irTransmit() {
    log('📤 Transmit IR - select signal from list...');
    // Would show signal selection modal
    log('ℹ️ Select a signal from the list to transmit');
}

// ═══════════════════════════════════════════════════════════
// SUB-1GHZ FUNCTIONS
// ═══════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════
// NFC FUNCTIONS
// ═══════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════
// BADUSB FUNCTIONS
// ═══════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════
// NETWORK / SETTINGS FUNCTIONS
// ═══════════════════════════════════════════════════════════

async function updateNetworkStatus() {
    try {
        const response = await fetch(`${API_URL}/network/status`);
        const data = await response.json();
        
        // Update display
        const modeEl = document.getElementById('current-mode');
        const internetEl = document.getElementById('internet-status');
        
        if (data.ap_mode) {
            modeEl.textContent = 'AP Mode (Chonky_Control)';
            modeEl.className = 'value status-ap';
        } else if (data.client_mode) {
            modeEl.textContent = 'Client Mode (Maintenance)';
            modeEl.className = 'value status-client';
        } else {
            modeEl.textContent = 'Unknown';
            modeEl.className = 'value';
        }
        
        if (data.internet_available) {
            internetEl.textContent = '✅ Connected';
            internetEl.className = 'value status-online';
        } else {
            internetEl.textContent = '❌ No Internet';
            internetEl.className = 'value status-offline';
        }
        
    } catch (error) {
        console.log('Network status check failed:', error);
    }
}

function showMaintenanceDialog() {
    document.getElementById('maintenance-dialog').style.display = 'flex';
}

function hideMaintenanceDialog() {
    document.getElementById('maintenance-dialog').style.display = 'none';
}

async function enableMaintenanceMode() {
    const ssid = document.getElementById('maintenance-ssid').value;
    const password = document.getElementById('maintenance-password').value;
    
    if (!ssid || !password) {
        log('❌ Please enter both SSID and password');
        return;
    }
    
    log(`🔧 Enabling maintenance mode: connecting to ${ssid}...`);
    hideMaintenanceDialog();
    
    try {
        const response = await fetch(`${API_URL}/network/maintenance`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ssid, password })
        });
        
        const data = await response.json();
        
        if (data.success) {
            log(`✅ Maintenance mode enabled! Connect to ${ssid}`);
            log(`⚠️  You will be disconnected from Chonky_Control`);
            log(`🔗 New IP will be shown in your router or reconnect to check`);
        } else {
            log('❌ Failed to enable maintenance: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        log('❌ Maintenance mode error: ' + error.message);
    }
}

async function restoreAPMode() {
    log('📡 Restoring AP mode (Chonky_Control)...');
    
    try {
        const response = await fetch(`${API_URL}/network/apmode`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            log(`✅ AP mode restored!`);
            log(`🔗 Reconnect to: ${data.ssid} (IP: ${data.ip})`);
            log(`⏳ This may take 30 seconds...`);
        } else {
            log('❌ Failed to restore AP: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        log('❌ AP mode error: ' + error.message);
    }
}

async function runSystemUpdate() {
    const outputBox = document.getElementById('update-output');
    outputBox.style.display = 'block';
    outputBox.innerHTML = '<p>🔄 Checking for updates...</p>';
    
    log('🔄 Starting system update from GitHub...');
    
    try {
        const response = await fetch(`${API_URL}/system/update`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            outputBox.innerHTML = `<pre class="success">${escapeHtml(data.output || 'Update successful')}</pre>`;
            log('✅ System update complete!');
            log('🔄 Restarting services...');
        } else {
            outputBox.innerHTML = `<pre class="error">${escapeHtml(data.error || 'Update failed')}</pre>`;
            log('❌ Update failed: ' + (data.error || 'Check internet connection'));
        }
    } catch (error) {
        outputBox.innerHTML = `<pre class="error">${escapeHtml(error.message)}</pre>`;
        log('❌ Update error: ' + error.message);
    }
}

// Add periodic network status update
setInterval(updateNetworkStatus, 10000);

// Global error handler
window.addEventListener('error', (e) => {
    log('❌ JavaScript error: ' + e.message);
});
