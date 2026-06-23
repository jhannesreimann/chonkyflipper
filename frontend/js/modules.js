/**
 * ChonkyFlipper Frontend - Module Panel Handlers
 * WiFi, Bluetooth, IR, Sub-1GHz, NFC, BadUSB, Zigbee
 */

// ------------------------------------------------------------------ WiFi

function wifiTab(tab) {
    document.querySelectorAll('#panel-wifi .ir-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('#panel-wifi .ir-tab-content').forEach(c => { c.classList.remove('active'); c.style.display = 'none'; });
    const content = document.getElementById('wifi-tab-' + tab);
    if (content) { content.classList.add('active'); content.style.display = ''; }
    document.querySelector('#panel-wifi .ir-tab[onclick*="' + tab + '"]').classList.add('active');
    if (tab === 'attack') wifiShowAttackable();
}

// Risk badge colors
const RISK_COLORS = {critical: '#dc2626', high: '#f59e0b', medium: '#0ea5e9', low: '#10b981', none: '#94a3b8'};

function riskBadge(risk) {
    const color = RISK_COLORS[risk] || '#94a3b8';
    return `<span style="display:inline-block;padding:1px 6px;border-radius:8px;font-size:0.65rem;font-weight:700;background:${color}20;color:${color};border:1px solid ${color}40;">${risk.toUpperCase()}</span>`;
}

async function wifiScan() {
    log('Scanning Wi-Fi networks...');
    setLoading('wifi-results', true);
    try {
        const data = await apiGet('/wifi/scan');
        const container = document.getElementById('wifi-results');
        if (!data.success) {
            container.innerHTML = `<p class="placeholder" style="color:#e94560;">${escapeHtml(data.error || 'Scan failed')}</p>`;
            return;
        }
        if (data.networks && data.networks.length > 0) {
            container.innerHTML =
                `<table><thead><tr><th>Network</th><th>Security</th><th>Risk</th><th>Ch</th><th>Signal</th></tr></thead><tbody>` +
                data.networks.map(net =>
                    `<tr><td>${escapeHtml(net.ssid || 'Hidden')}<br><span style="font-size:0.6rem;color:var(--text-secondary);">${net.bssid||'-'}</span></td><td style="font-size:0.7rem;">${escapeHtml(net.security||'?')}</td><td>${riskBadge(net.risk||'low')}</td><td>${net.channel||'-'}</td><td>${net.signal_dbm!==undefined?net.signal_dbm+' dBm':'-'}</td></tr>`
                ).join('') + '</tbody></table>';
            log('Found ' + data.networks.length + ' networks');
        } else {
            container.innerHTML = '<p class="placeholder">No networks found</p>';
        }
    } catch (error) {
        log('Wi-Fi scan failed: ' + error.message);
        document.getElementById('wifi-results').innerHTML = '<p class="placeholder" style="color:#e94560;">Scan failed</p>';
    } finally {
        setLoading('wifi-results', false);
    }
}

async function wifiMonitorMode() {
    log('Enabling monitor mode...');
    try {
        const data = await apiPost('/wifi/start_monitor');
        log(data.success ? 'Monitor mode enabled: ' + data.interface : 'Monitor mode failed');
    } catch (error) { log('Monitor mode error: ' + error.message); }
}

// --- Audit tab (wifite-based vulnerability scan) ---

async function wifiAudit() {
    log('Running wifite security audit...');
    const results = document.getElementById('wifi-audit-results');
    results.innerHTML = '<p class="placeholder">Wifite scanning for vulnerable networks (15s)...</p>';
    try {
        const data = await apiPost('/wifi/audit/wifite-scan', { scan_time: 15 });
        const targets = data.targets || [];
        if (targets.length === 0) {
            results.innerHTML = '<p class="placeholder">No networks with connected clients detected. Try again later.</p>';
            log('Audit: no targets with clients found');
            return;
        }
        let html = '<div style="display:flex;flex-direction:column;gap:8px;margin-top:8px;">';
        html += '<p style="font-size:0.7rem;color:var(--text-secondary);">Wifite found ' + targets.length + ' network(s) with active clients:</p>';
        targets.forEach(t => {
            const enc = (t.encryption || '').toLowerCase();
            const hasWPS = t.wps === 'yes';
            const clients = parseInt(t.clients) || 0;
            const vulns = [];
            if (enc.includes('wep')) vulns.push('WEP (minutes to crack)');
            if (enc.includes('wpa') && !enc.includes('wpa3')) vulns.push('WPA handshake capture possible');
            if (hasWPS) vulns.push('WPS enabled (Pixie-Dust attackable)');
            if (clients > 0) vulns.push(clients + ' connected client(s)');
            html += '<div style="background:var(--bg-dark);border-radius:8px;padding:10px;border-left:3px solid var(--accent-warning);">' +
                '<div style="font-weight:600;font-size:0.8rem;">' + escapeHtml(t.essid) +
                ' <span style="font-size:0.65rem;color:var(--text-secondary);">Ch ' + t.channel + ' ' + t.power + '</span></div>' +
                '<div style="font-size:0.65rem;color:var(--text-secondary);margin:4px 0;">' + enc.toUpperCase() + '</div>' +
                '<div style="font-size:0.65rem;">' + vulns.map(v => '• ' + v).join('<br>') + '</div></div>';
        });
        html += '</div>';
        results.innerHTML = html;
        log('Audit: ' + targets.length + ' target(s) found by wifite');
    } catch (error) {
        results.innerHTML = '<p class="placeholder" style="color:#e94560;">wifite audit failed. Ensure wlan1 is available.</p>';
        log('Audit error: ' + error.message);
    }
}

// --- Probes tab ---

async function wifiProbes(duration) {
    log('Capturing probes (' + duration + 's)...');
    const results = document.getElementById('wifi-probes-results');
    results.innerHTML = '<p class="placeholder">Listening for ' + duration + ' seconds...</p>';
    try {
        const data = await apiPost('/wifi/probes', { duration: duration });
        if (!data.success) { results.innerHTML = `<p class="placeholder" style="color:#e94560;">${escapeHtml(data.error||'Failed')}</p>`; return; }
        if (!data.probes || data.probes.length === 0) {
            results.innerHTML = '<p class="placeholder">No probe requests captured.</p>';
            return;
        }
        let html = `<p style="font-size:0.7rem;color:var(--text-secondary);margin:8px 0;">${data.count} probes captured</p>`;
        html += '<table><thead><tr><th>Client MAC</th><th>SSID</th></tr></thead><tbody>';
        data.probes.forEach(p => {
            html += `<tr><td style="font-family:monospace;font-size:0.7rem;">${p.client_mac}</td><td>${escapeHtml(p.ssid||'(broadcast)')}</td></tr>`;
        });
        html += '</tbody></table>';
        results.innerHTML = html;
        log('Probes: ' + data.probes.length + ' captured');
    } catch (error) {
        results.innerHTML = '<p class="placeholder" style="color:#e94560;">Probe capture failed</p>';
        log('Probe error: ' + error.message);
    }
}

// --- Attack tab ---

let _attackableNetworks = [];

async function wifiShowAttackable() {
    const list = document.getElementById('wifi-attack-list');
    // Use wifite (Kali's wireless auditor) to find attackable targets with clients
    list.innerHTML = '<p class="placeholder">Running wifite scan (10s) - finding targets with clients...</p>';
    try {
        const data = await apiPost('/wifi/audit/wifite-scan', { scan_time: 10 });
        const targets = data.targets || [];
        if (targets.length === 0) {
            list.innerHTML = '<p class="placeholder">No targets with connected clients found.</p>';
            return;
        }
        let rows = targets.map(t => {
            const enc = (t.encryption || '').toLowerCase();
            const hasWPS = t.wps === 'yes';
            const ch = parseInt(t.channel) || 0;
            // ESSIDs that look like MAC addresses are hidden networks
            const isHidden = /^\([0-9A-F:]+\)$/.test(t.essid);
            const displayName = isHidden ? '(hidden: ' + t.essid + ')' : t.essid;
            return '<div style="background:var(--bg-dark);border-radius:8px;padding:8px;">' +
                '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                '<div><span style="font-weight:600;font-size:0.8rem;">' + escapeHtml(displayName) + '</span>' +
                '<span style="font-size:0.65rem;color:var(--text-secondary);margin-left:6px;">Ch ' + t.channel + ' ' + t.power + 'dB ' + t.clients + ' clients ' + enc.toUpperCase() + (hasWPS?' +WPS':'') + '</span></div>' +
                '<div style="display:flex;gap:4px;">' +
                '<button class="btn btn-secondary btn-sm" style="padding:3px 8px;font-size:0.65rem;" onclick="wifiteAttackTarget(\'' + t.essid + '\',' + ch + ')" title="Run wifite against this target (WPA handshake + WPS)">Attack</button>' +
                '</div></div></div>';
        }).join('');
        rows += '<div style="margin-top:12px;display:flex;gap:8px;">' +
            '<button class="btn btn-secondary btn-sm" onclick="wifiShowAttackable()">Rescan</button>' +
            '</div>';
        rows += '<p style="margin-top:4px;font-size:0.65rem;color:var(--text-secondary);">' +
            'Targets with clients found by wifite. Click Attack to run wifite against that network (handshake + WPS).</p>';
        list.innerHTML = rows;
    } catch (e) {
        list.innerHTML = '<p class="placeholder" style="color:#e94560;">wifite scan failed.</p>';
    }
}

async function wifiteAttackTarget(bssid, channel) {
    const result = document.getElementById('wifi-attack-result');
    result.style.display = 'block';
    result.innerHTML = '<pre>Starting wifite attack on ' + escapeHtml(bssid) + ' ch ' + channel + '...\n(Runs in background, polling for results)</pre>';
    log('Wifite attack: ' + bssid);

    try {
        // Start attack (returns immediately)
        const start = await apiPost('/wifi/audit/wifite-attack', {
            scan_time: 1, attack_time: 120, channel: channel
        });
        if (!start.success) {
            result.innerHTML = '<pre class="error">' + escapeHtml(start.error||'Failed to start') + '</pre>';
            return;
        }
        // Poll for completion every 5 seconds
        let attempts = 0;
        const poll = setInterval(async () => {
            attempts++;
            result.innerHTML = '<pre>Wifite attacking ' + escapeHtml(bssid) + '... (' + (attempts * 5) + 's)</pre>';
            try {
                const check = await apiGet('/wifi/audit/wifite-status');
                if (!check.running) {
                    clearInterval(poll);
                    // Re-run scan to get updated results
                    const scan = await apiPost('/wifi/audit/wifite-scan', { scan_time: 5 });
                    if (scan.cracked && scan.cracked.length > 0) {
                        let keys = scan.cracked.map(c => (c.essid||c.bssid) + ': ' + (c.key||c.psk||c.pin||'found')).join('\n');
                        result.innerHTML = '<pre class="success">CRACKED:\n' + keys + '</pre>';
                    } else {
                        result.innerHTML = '<pre>Attack finished. No keys cracked.\nCheck captured handshakes in /root/hs/</pre>';
                    }
                    log('Wifite attack complete');
                }
            } catch (e) { /* polling - ignore errors */ }
            if (attempts > 36) { // 3 minutes max
                clearInterval(poll);
                result.innerHTML = '<pre>Attack timed out after 3 min. Wifite may still be running.</pre>';
            }
        }, 5000);
    } catch (e) {
        result.innerHTML = '<pre class="error">' + escapeHtml(e.message) + '</pre>';
    }
}

async function wifiAttackWEP(bssid, channel) {
    const result = document.getElementById('wifi-attack-result');
    result.style.display = 'block';
    result.innerHTML = `<pre>Starting WEP attack on ${bssid} ch ${channel} (2 min)...</pre>`;
    log('WEP attack: ' + bssid);
    try {
        const data = await apiPost('/wifi/attack/wep', { bssid, channel, timeout: 120 });
        if (data.success) {
            result.innerHTML = `<pre class="success">KEY FOUND: ${data.key}</pre>`;
            log('WEP KEY: ' + data.key);
        } else {
            result.innerHTML = `<pre class="error">${escapeHtml(data.error||'Failed')}</pre>`;
        }
    } catch (e) { result.innerHTML = `<pre class="error">${escapeHtml(e.message)}</pre>`; }
}

async function wifiAttackWPA(bssid, channel) {
    const result = document.getElementById('wifi-attack-result');
    result.style.display = 'block';
    result.innerHTML = `<pre>Capturing handshake then cracking with rockyou.txt (90s)...</pre>`;
    log('WPA attack: ' + bssid);
    try {
        const data = await apiPost('/wifi/attack/wpa', { bssid, channel, timeout: 90 });
        if (data.success) {
            result.innerHTML = `<pre class="success">KEY FOUND: ${data.key}</pre>`;
            log('WPA KEY: ' + data.key);
        } else {
            result.innerHTML = `<pre class="error">${escapeHtml(data.error||'Failed')}</pre>`;
        }
    } catch (e) { result.innerHTML = `<pre class="error">${escapeHtml(e.message)}</pre>`; }
}

async function wifiAttackWPS(bssid, channel) {
    const result = document.getElementById('wifi-attack-result');
    result.style.display = 'block';
    result.innerHTML = `<pre>Starting WPS PIN attack on ${bssid} (5 min)...</pre>`;
    log('WPS attack: ' + bssid);
    try {
        const data = await apiPost('/wifi/attack/wps', { bssid, channel, timeout: 300 });
        if (data.success) {
            let msg = `PIN: ${data.pin}`;
            if (data.psk) msg += `\nPSK: ${data.psk}`;
            result.innerHTML = `<pre class="success">${msg}</pre>`;
            log('WPS crack: ' + msg.replace('\n', ', '));
        } else {
            result.innerHTML = `<pre class="error">${escapeHtml(data.error||'Failed')}</pre>`;
        }
    } catch (e) { result.innerHTML = `<pre class="error">${escapeHtml(e.message)}</pre>`; }
}

async function wifiDeauth(bssid, channel) {
    log('Deauth attack: ' + bssid + ' ch ' + channel);
    const result = document.getElementById('wifi-attack-result');
    result.style.display = 'block';
    result.innerHTML = '<pre>Sending deauth frames on channel ' + channel + '...</pre>';
    try {
        const data = await apiPost('/wifi/deauth', { bssid, count: 10, channel: channel });
        if (data.success) {
            result.innerHTML = '<pre class="success">Deauth sent: ' + data.frames_sent + ' frames\n' + (data.output||'') + '</pre>';
            log('Deauth sent to ' + bssid);
        } else {
            result.innerHTML = '<pre class="error">' + escapeHtml(data.error||'Deauth failed') + '</pre>';
        }
    } catch (e) { result.innerHTML = '<pre class="error">' + escapeHtml(e.message) + '</pre>'; }
}

// --- Capture tab ---

async function wifiCapture() {
    const filter = document.getElementById('wifi-capture-filter').value || null;
    const label = filter || 'all';
    log('Starting packet capture (60s, filter: ' + label + ')...');
    try {
        const data = await apiPost('/wifi/capture', { duration: 60, filter: filter });
        log(data.success ? `Capture saved: ${data.filename} (${data.size_bytes} bytes, filter: ${label})` : 'Capture failed');
    } catch (error) { log('Capture error: ' + error.message); }
}

// ------------------------------------------------------------------ Bluetooth

async function bleScan() {
    log('Scanning BLE devices...');
    setLoading('ble-results', true);
    try {
        const data = await apiGet('/bluetooth/scan');
        const container = document.getElementById('ble-results');
        if (data.devices && data.devices.length > 0) {
            container.innerHTML =
                `<table><thead><tr><th>Device</th><th>MAC</th><th>RSSI</th></tr></thead><tbody>` +
                data.devices.map(dev =>
                    `<tr><td>${escapeHtml(dev.name || 'Unknown')}</td><td>${dev.mac || '-'}</td><td>${dev.rssi || '-'} dBm</td></tr>`
                ).join('') + '</tbody></table>';
            log('Found ' + data.devices.length + ' BLE devices');
        } else {
            container.innerHTML = '<p class="placeholder">No devices found</p>';
        }
    } catch (error) {
        log('BLE scan failed: ' + error.message);
    } finally {
        setLoading('ble-results', false);
    }
}

async function bleBeacons() {
    log('Scanning for BLE beacons...');
    try {
        const data = await apiGet('/bluetooth/beacons');
        log(data.beacons && data.beacons.length > 0 ? `Found ${data.beacons.length} beacons` : 'No beacons detected');
    } catch (error) { log('Beacon scan failed: ' + error.message); }
}

// ------------------------------------------------------------------ IR

function irShowTab(tab) {
    document.querySelectorAll('.ir-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.ir-tab-content').forEach(c => { c.classList.remove('active'); c.style.display = 'none'; });
    const content = document.getElementById(`ir-tab-content-${tab}`);
    content.classList.add('active');
    content.style.display = '';
    document.getElementById(`ir-tab-${tab}`).classList.add('active');
    if (tab === 'library') irShowBrands();
    else if (tab === 'mysignals') irLoadSignals();
}

async function irShowBrands() {
    document.getElementById('ir-breadcrumb').style.display = 'none';
    document.getElementById('ir-devices-list').style.display = 'none';
    document.getElementById('ir-buttons-grid').style.display = 'none';
    document.getElementById('ir-search-results').style.display = 'none';
    document.getElementById('ir-brands-grid').style.display = '';

    const grid = document.getElementById('ir-brands-grid');
    const loading = document.getElementById('ir-brands-loading');
    grid.innerHTML = '';
    loading.style.display = 'block';

    try {
        const data = await apiGet('/ir/library/brands');
        loading.style.display = 'none';
        if (data.brands && data.brands.length > 0) {
            grid.innerHTML = data.brands.map(b =>
                `<div class="brand-card" onclick="irShowDevices('${escapeHtmlAttr(b.slug)}')"><div class="brand-name">${escapeHtml(b.name)}</div><div class="brand-count">${b.device_count} devices</div></div>`
            ).join('');
            document.getElementById('ir-lib-stats').textContent =
                `${data.total} brands · ${data.brands.reduce((s,b)=>s+b.device_count,0)} devices`;
        } else {
            grid.innerHTML = '<p class="placeholder">No brands found. Run sync to populate the library.</p>';
            document.getElementById('ir-lib-stats').textContent = 'Empty library';
        }
    } catch (e) {
        loading.style.display = 'none';
        grid.innerHTML = '<p class="placeholder">Error loading library. Check internet for first sync.</p>';
    }
}

async function irShowDevices(brandSlug) {
    document.getElementById('ir-brands-grid').style.display = 'none';
    document.getElementById('ir-buttons-grid').style.display = 'none';
    document.getElementById('ir-search-results').style.display = 'none';
    const list = document.getElementById('ir-devices-list');
    list.style.display = '';
    list.innerHTML = '<p class="placeholder">Loading...</p>';
    try {
        const data = await apiGet(`/ir/library/brands/${encodeURIComponent(brandSlug)}/devices`);
        if (!data.devices || data.devices.length === 0) {
            list.innerHTML = '<p class="placeholder">No devices found.</p>';
            return;
        }
        list.innerHTML = data.devices.map(d =>
            `<div class="device-item" onclick="irShowButtons(${d.id},'${escapeHtmlAttr(d.name)}')"><div class="device-info"><span class="device-name">${escapeHtml(d.name)}</span><span class="device-meta">${d.button_count} buttons</span></div><span style="color:var(--text-secondary);">➔</span></div>`
        ).join('');
        document.getElementById('ir-breadcrumb').style.display = '';
        document.getElementById('ir-breadcrumb').innerHTML =
            `<span class="breadcrumb-link" onclick="irShowBrands()">All Brands</span> → <strong>${escapeHtml(data.brand.name)}</strong>`;
    } catch (e) {
        list.innerHTML = '<p class="placeholder">Error loading devices.</p>';
    }
}

async function irShowButtons(deviceId, deviceName) {
    document.getElementById('ir-devices-list').style.display = 'none';
    document.getElementById('ir-search-results').style.display = 'none';
    const grid = document.getElementById('ir-buttons-grid');
    grid.style.display = '';
    grid.innerHTML = '<p class="placeholder">Loading...</p>';
    try {
        const data = await apiGet(`/ir/library/devices/${deviceId}/buttons`);
        if (!data.buttons || data.buttons.length === 0) {
            grid.innerHTML = '<p class="placeholder">No buttons found.</p>';
            return;
        }
        grid.innerHTML = '<div class="button-grid">' + data.buttons.map(b =>
            `<button class="btn-ir ${b.button_id.includes('power')?'power-btn':''}" onclick="irSendLibraryButton(${deviceId},'${escapeHtmlAttr(b.button_id)}')" title="${escapeHtmlAttr(b.protocol||b.protocol_hint||'')}">${escapeHtml(b.label)}</button>`
        ).join('') + '</div>';
        const bc = document.getElementById('ir-breadcrumb');
        bc.innerHTML =
            `<span class="breadcrumb-link" onclick="irShowBrands()">All Brands</span> → ` +
            `<span class="breadcrumb-link" onclick="irShowDevices('${escapeHtmlAttr(data.device.brand_slug||'')}')">${escapeHtml(data.device.brand_name||'')}</span> → ` +
            `<strong>${escapeHtml(deviceName)}</strong>`;
    } catch (e) {
        grid.innerHTML = '<p class="placeholder">Error loading buttons.</p>';
    }
}

async function irSendLibraryButton(deviceId, buttonId) {
    log('Sending: ' + buttonId);
    try {
        const data = await apiPost(`/ir/library/devices/${deviceId}/send`, { button_id: buttonId });
        log(data.success ? 'IR sent: ' + buttonId : 'IR send failed: ' + (data.error || 'Unknown'));
    } catch (e) { log('IR send error: ' + e.message); }
}

async function irSearch() {
    const q = document.getElementById('ir-search-input').value.trim();
    if (!q) return irShowBrands();
    ['ir-brands-grid','ir-devices-list','ir-buttons-grid'].forEach(id => document.getElementById(id).style.display='none');
    const results = document.getElementById('ir-search-results');
    results.style.display = '';
    results.innerHTML = '<p class="placeholder">Searching...</p>';
    try {
        const data = await apiGet(`/ir/library/search?q=${encodeURIComponent(q)}`);
        let html = '';
        if (data.results) {
            if (data.results.brands && data.results.brands.length) {
                html += '<h4 style="margin:8px 0 4px;color:var(--text-secondary);font-size:0.7rem;">BRANDS</h4>';
                html += data.results.brands.map(b =>
                    `<div class="device-item" onclick="irShowDevices('${escapeHtmlAttr(b.slug)}')"><span>${escapeHtml(b.name)} <span style="color:var(--text-secondary);font-size:0.65rem;">${b.count} devices</span></span><span style="color:var(--text-secondary);">➔</span></div>`
                ).join('');
            }
            if (data.results.devices && data.results.devices.length) {
                html += '<h4 style="margin:8px 0 4px;color:var(--text-secondary);font-size:0.7rem;">DEVICES</h4>';
                html += data.results.devices.map(d =>
                    `<div class="device-item" onclick="irShowButtons(${d.id},'${escapeHtmlAttr(d.name)}')"><span>${escapeHtml(d.name)} <span style="color:var(--text-secondary);font-size:0.65rem;">${escapeHtml(d.brand_name)}</span></span><span style="color:var(--text-secondary);">➔</span></div>`
                ).join('');
            }
            if (data.results.buttons && data.results.buttons.length) {
                html += '<h4 style="margin:8px 0 4px;color:var(--text-secondary);font-size:0.7rem;">BUTTONS</h4><div class="button-grid">';
                html += data.results.buttons.slice(0, 20).map(b =>
                    `<button class="btn-ir ${b.slug&&b.slug.includes('power')?'power-btn':''}" onclick="alert('Select through the device browser')">${escapeHtml(b.name)}</button>`
                ).join('') + '</div>';
            }
        }
        results.innerHTML = html || '<p class="placeholder">No results for "' + escapeHtml(q) + '"</p>';
    } catch (e) { results.innerHTML = '<p class="placeholder">Search error.</p>'; }
}

async function irSyncCheck() {
    const status = document.getElementById('ir-sync-status');
    const btn = document.getElementById('ir-sync-btn');
    status.style.display = 'block';
    status.className = 'status-msg info';
    status.textContent = 'Checking for updates...';
    btn.disabled = true;
    try {
        const cdata = await apiPost('/ir/sync/check');
        if (cdata.error) { status.className='status-msg error'; status.textContent=cdata.error; btn.disabled=false; return; }
        if (!cdata.has_updates) { status.className='status-msg success'; status.textContent='Library is up to date.'; btn.disabled=false; return; }
        const count = cdata.new_commits;
        status.textContent = count === -1 ? 'First-time setup: cloning full IR library...'
            : `Syncing ${count} new commits...`;
        const sdata = await apiPost('/ir/sync/start');
        if (!sdata.success) { status.className='status-msg error'; status.textContent=sdata.error||'Sync failed'; btn.disabled=false; return; }
        irPollSync();
    } catch (e) { status.className='status-msg error'; status.textContent='Sync check failed.'; btn.disabled=false; }
}

async function irPollSync() {
    const status = document.getElementById('ir-sync-status');
    const btn = document.getElementById('ir-sync-btn');
    try {
        const data = await apiGet('/ir/sync/status');
        if (data.running) { status.textContent = `Syncing... ${data.progress}/${data.total} ${data.current||''}`; setTimeout(irPollSync, 1000); return; }
        if (data.result && data.result.success) {
            status.className='status-msg success';
            status.textContent = `Synced! ${data.result.files_added} new, ${data.result.files_updated} updated.`;
            irShowBrands();
        } else if (data.error) { status.className='status-msg error'; status.textContent='Sync error: '+data.error; }
        else { status.className='status-msg success'; status.textContent='Sync complete.'; irShowBrands(); }
    } catch (e) { status.className='status-msg error'; status.textContent='Lost sync status.'; }
    btn.disabled = false;
}

function irRecord() {
    irShowTab('mysignals');
    _doIrRecord();
}

async function _doIrRecord() {
    const status = document.getElementById('ir-record-status');
    status.style.display = 'block';
    status.className = 'status-msg info';
    status.textContent = 'Recording 5s... point remote at receiver and press buttons.';
    try {
        const data = await apiPost('/ir/record', { duration: 5 });
        if (data.success) {
            status.className='status-msg success';
            status.textContent = 'Captured: ' + (data.preview || data.name);
            log('IR signal recorded: ' + data.name + ' (' + data.protocol + ')');
            irLoadSignals();
        } else { status.className='status-msg error'; status.textContent = data.error || 'Record failed'; }
    } catch (error) { status.className='status-msg error'; status.textContent = 'Record error: ' + error.message; }
}

async function irLoadSignals() {
    try {
        const data = await apiGet('/ir/signals');
        const table = document.getElementById('ir-signals-table');
        const body = document.getElementById('ir-signals-body');
        const empty = document.getElementById('ir-signals-empty');
        if (data.signals && data.signals.length > 0) {
            table.style.display = '';
            empty.style.display = 'none';
            body.innerHTML = data.signals.map(s =>
                `<tr><td>${escapeHtml(s.name)}</td><td>${escapeHtml(s.protocol||'?')}</td><td>${s.pulses||0}</td><td><button class="btn btn-secondary" style="padding:4px 10px;font-size:0.75rem;" onclick="irTransmitSignal('${escapeHtmlAttr(s.name)}')">Send</button></td></tr>`
            ).join('');
        } else { table.style.display='none'; empty.style.display=''; }
    } catch (error) { log('IR signal list error: '+error.message); }
}

async function irTransmitSignal(name) {
    log('Transmitting: ' + name);
    try {
        const data = await apiPost('/ir/transmit', { signal_id: name });
        log(data.success ? 'Signal sent: ' + name : 'Transmit failed: ' + (data.error || 'Unknown'));
    } catch (error) { log('Transmit error: ' + error.message); }
}

// ------------------------------------------------------------------ Sub-1GHz

async function subghzRecord() {
    const freq = document.getElementById('subghz-freq').value;
    log(`Recording Sub-1GHz @ ${freq} MHz (3s)...`);
    try {
        const data = await apiPost('/subghz/record', { frequency: parseFloat(freq), duration: 3 });
        log(data.success ? `Signal saved: ${data.name}` : 'Record failed: ' + (data.error || 'Unknown'));
    } catch (error) { log('Sub-1GHz error: ' + error.message); }
}

async function subghzTransmit() {
    log('Transmit Sub-1GHz - select signal...');
}

// ------------------------------------------------------------------ NFC

async function nfcRead() {
    log('Reading NFC card...');
    try {
        const data = await apiGet('/nfc/read');
        const container = document.getElementById('nfc-card');
        if (data.uid) {
            container.innerHTML = `<div class="card-info"><p><strong>UID:</strong> ${data.uid}</p><p><strong>Type:</strong> ${data.card_type||'Unknown'}</p><p><strong>Timestamp:</strong> ${new Date().toLocaleTimeString()}</p></div>`;
            log(`Card read: ${data.uid}`);
        } else {
            container.innerHTML = '<p class="placeholder">No card detected</p>';
        }
    } catch (error) { log('NFC read error: ' + error.message); }
}

function nfcClone() {
    log('NFC clone - read card first, then write to magic card');
}

// ------------------------------------------------------------------ BadUSB

let _badusbPayloads = [];

async function loadBadusbPayloads() {
    try {
        const data = await apiGet('/badusb/payloads');
        _badusbPayloads = data.payloads || [];
        renderBadusbButtons();
    } catch (error) { log('BadUSB payload list error: '+error.message); }
}

function renderBadusbButtons() {
    const container = document.getElementById('badusb-buttons');
    if (!container) return;
    if (_badusbPayloads.length === 0) {
        container.innerHTML = '<p class="placeholder">No payloads available.</p>';
        return;
    }
    container.innerHTML = _badusbPayloads.map(name =>
        `<button class="btn btn-danger" onclick="badusbExecute('${escapeHtmlAttr(name)}')">${escapeHtml(name)}</button>`
    ).join('');
}

async function badusbExecute(payload) {
    log(`Executing BadUSB payload: ${payload}`);
    try {
        const data = await apiPost('/badusb/execute', { payload });
        log(data.success ? 'Payload executed' : (data.error || 'Payload failed'));
    } catch (error) { log('BadUSB error: ' + error.message); }
}

// ------------------------------------------------------------------ Zigbee

function zigbeeShowTab(tab) {
    document.querySelectorAll('#panel-zigbee .ir-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('#panel-zigbee .ir-tab-content').forEach(c => { c.classList.remove('active'); c.style.display = 'none'; });
    const content = document.getElementById('zigbee-tab-content-' + tab);
    if (content) { content.classList.add('active'); content.style.display = ''; }
    document.getElementById('zigbee-tab-' + tab).classList.add('active');
    if (tab === 'devices') zigbeeLoadDevices();
    else if (tab === 'events') zigbeeLoadEvents();
}

// --- Devices tab ---

async function zigbeeLoadDevices() {
    const container = document.getElementById('zigbee-devices-list');
    setLoading('zigbee-devices-list', true);
    try {
        const data = await apiGet('/zigbee/dashboard');
        if (!data.success) {
            container.innerHTML = `<p class="placeholder" style="color:#e94560;">${escapeHtml(data.error || 'Failed to load devices')}</p>`;
            return;
        }
        const devices = (data.devices || []).filter(d => d.type !== 'Coordinator');
        if (devices.length === 0) {
            container.innerHTML = '<p class="placeholder">No devices paired. Use Permit Join to add one.</p>';
            return;
        }
        container.innerHTML = devices.map(zigbeeDeviceRow).join('');
        log('Zigbee: ' + devices.length + ' devices');
    } catch (e) {
        container.innerHTML = `<p class="placeholder" style="color:#e94560;">${escapeHtml(e.message)}</p>`;
    }
}

function zigbeeDeviceRow(d) {
    const name = escapeHtml(d.friendly_name || '?');
    const nameAttr = escapeHtmlAttr(d.friendly_name || '');
    const meta = [d.vendor, d.model].filter(Boolean).map(escapeHtml).join(' ') || escapeHtml(d.type || 'device');

    const av = d.available;
    const dotColor = av === true ? '#22c55e' : av === false ? '#dc2626' : '#94a3b8';
    const dotTitle = av === true ? 'online' : av === false ? 'offline' : 'unknown';

    const badges = [];
    if (d.battery !== null && d.battery !== undefined) {
        const bcol = d.battery >= 60 ? '#22c55e' : d.battery >= 20 ? 'var(--accent-warning)' : '#dc2626';
        badges.push(`<span style="font-size:0.65rem;color:${bcol};">Bat ${d.battery}%</span>`);
    }
    if (d.linkquality !== null && d.linkquality !== undefined) {
        const lcol = d.linkquality >= 100 ? '#22c55e' : d.linkquality >= 50 ? 'var(--accent-warning)' : '#dc2626';
        badges.push(`<span style="font-size:0.65rem;color:${lcol};" title="Link quality (LQI)">LQI ${d.linkquality}</span>`);
    }

    const actions = [];
    if (d.state === 'ON' || d.state === 'OFF') {
        const next = d.state === 'ON' ? 'OFF' : 'ON';
        actions.push(`<button class="btn btn-secondary btn-sm" onclick="zigbeeToggle('${nameAttr}','${next}')">Turn ${next === 'ON' ? 'On' : 'Off'}</button>`);
    }
    actions.push(`<button class="btn btn-secondary btn-sm" onclick="zigbeeRename('${nameAttr}')">Rename</button>`);
    actions.push(`<button class="btn btn-danger btn-sm" onclick="zigbeeRemove('${nameAttr}')">Remove</button>`);

    return `<div style="background:var(--bg-dark);border-radius:10px;padding:10px;margin-bottom:6px;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
            <div style="min-width:0;">
                <div style="font-weight:600;font-size:0.85rem;display:flex;align-items:center;gap:6px;">
                    <span style="width:8px;height:8px;border-radius:50%;background:${dotColor};flex:none;" title="${dotTitle}"></span>
                    <span style="overflow:hidden;text-overflow:ellipsis;">${name}</span>
                </div>
                <div style="font-size:0.65rem;color:var(--text-secondary);margin-top:2px;">${meta}</div>
            </div>
            <div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex:none;">${badges.join('')}</div>
        </div>
        <div style="display:flex;gap:4px;margin-top:8px;flex-wrap:wrap;">${actions.join('')}</div>
    </div>`;
}

async function zigbeePermitJoin() {
    const status = document.getElementById('zigbee-status');
    status.style.display = 'block';
    status.className = 'status-msg info';
    status.textContent = 'Enabling join mode for 4 minutes...';
    log('Zigbee: permit join enabled');
    try {
        const data = await apiPost('/zigbee/permit_join', { enable: true, duration: 254 });
        if (data.success) {
            status.className = 'status-msg success';
            status.textContent = 'Join mode active. Put your device into pairing mode now.';
        } else {
            status.className = 'status-msg error';
            status.textContent = data.error || 'Failed to enable join mode';
        }
    } catch (e) { status.className = 'status-msg error'; status.textContent = e.message; }
}

async function zigbeeToggle(name, next) {
    log('Zigbee: ' + name + ' -> ' + next);
    try {
        const data = await apiPost(`/zigbee/device/${encodeURIComponent(name)}/set`, { state: next });
        if (data.success) zigbeeLoadDevices();
        else log('Zigbee toggle failed: ' + (data.error || 'Unknown'));
    } catch (e) { log('Zigbee toggle error: ' + e.message); }
}

async function zigbeeRename(name) {
    const to = prompt('Rename "' + name + '" to:', name);
    if (!to || to === name) return;
    log('Zigbee: rename ' + name + ' -> ' + to);
    try {
        const data = await apiPost(`/zigbee/device/${encodeURIComponent(name)}/rename`, { to: to });
        if (data.success) { log('Renamed to ' + to); zigbeeLoadDevices(); }
        else log('Rename failed: ' + (data.error || 'Unknown'));
    } catch (e) { log('Rename error: ' + e.message); }
}

async function zigbeeRemove(name) {
    if (!confirm('Remove "' + name + '" from the Zigbee network?')) return;
    log('Zigbee: removing ' + name);
    try {
        const data = await apiDelete(`/zigbee/device/${encodeURIComponent(name)}`);
        if (data.success) { log('Removed ' + name); zigbeeLoadDevices(); }
        else log('Remove failed: ' + (data.error || 'Unknown'));
    } catch (e) { log('Remove error: ' + e.message); }
}

// --- Events tab ---

async function zigbeeLoadEvents() {
    const container = document.getElementById('zigbee-events-list');
    setLoading('zigbee-events-list', true);
    try {
        const data = await apiGet('/zigbee/events?limit=50');
        if (!data.success) {
            container.innerHTML = `<p class="placeholder" style="color:#e94560;">${escapeHtml(data.error || 'Failed to load events')}</p>`;
            return;
        }
        if (!data.events || data.events.length === 0) {
            container.innerHTML = '<p class="placeholder">No events recorded yet.</p>';
            return;
        }
        container.innerHTML = data.events.map(zigbeeEventRow).join('');
    } catch (e) {
        container.innerHTML = `<p class="placeholder" style="color:#e94560;">${escapeHtml(e.message)}</p>`;
    }
}

function zigbeeEventRow(ev) {
    const isLifecycle = ev.category === 'lifecycle';
    const color = isLifecycle ? 'var(--accent-secondary)' : 'var(--text-secondary)';
    const type = escapeHtml((ev.type || 'event').replace(/_/g, ' ').toUpperCase());
    const device = escapeHtml(ev.device || '');
    let time = '';
    try { time = new Date(ev.timestamp).toLocaleTimeString(); } catch (e) { time = ''; }
    const detail = zigbeeEventDetail(ev);
    return `<div style="background:var(--bg-dark);border-radius:8px;padding:8px 10px;margin-bottom:6px;border-left:3px solid ${color};">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
            <span style="font-weight:600;font-size:0.75rem;">${type}</span>
            <span style="font-size:0.6rem;color:var(--text-secondary);flex:none;">${time}</span>
        </div>
        <div style="font-size:0.68rem;color:var(--text-secondary);margin-top:2px;">${device}${detail}</div>
    </div>`;
}

function zigbeeEventDetail(ev) {
    const d = ev.detail || {};
    const parts = [];
    if (ev.category === 'state') {
        ['state', 'action', 'contact', 'occupancy', 'battery', 'linkquality', 'temperature', 'humidity'].forEach(k => {
            if (d[k] !== undefined && d[k] !== null) parts.push(`${k}: ${escapeHtml(String(d[k]))}`);
        });
    } else {
        if (d.ieee_address) parts.push(escapeHtml(d.ieee_address));
        if (d.status) parts.push(escapeHtml(String(d.status)));
    }
    return parts.length ? ' · ' + parts.join(' · ') : '';
}
