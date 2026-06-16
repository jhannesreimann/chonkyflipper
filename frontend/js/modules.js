/**
 * ChonkyFlipper Frontend - Module Panel Handlers
 * WiFi, Bluetooth, IR, Sub-1GHz, NFC, BadUSB
 */

// ------------------------------------------------------------------ WiFi

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
                `<table><thead><tr><th>Network</th><th>BSSID</th><th>Ch</th><th>Sec</th><th>Signal</th></tr></thead><tbody>` +
                data.networks.map(net =>
                    `<tr><td>${escapeHtml(net.ssid || 'Hidden')}</td><td>${net.bssid || '-'}</td><td>${net.channel || '-'}</td><td>${escapeHtml(net.security || 'Open')}</td><td>${net.signal_dbm !== undefined ? net.signal_dbm + ' dBm' : '-'}</td></tr>`
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

async function wifiCapture() {
    log('Starting packet capture (10s)...');
    try {
        const data = await apiPost('/wifi/capture', { duration: 10 });
        log(data.success ? `Capture saved: ${data.filename} (${data.size_bytes} bytes)` : 'Capture failed');
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
