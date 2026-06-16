/**
 * ChonkyFlipper Frontend - Initialization, Status & System
 */

let systemStatus = {};
let activeModule = null;

document.addEventListener('DOMContentLoaded', () => {
    init();
});

async function init() {
    log('ChonkyFlipper initializing...');

    document.querySelectorAll('.module-item').forEach(item => {
        item.addEventListener('click', () => {
            showModulePanel(item.dataset.module);
        });
    });

    await checkStatus();
    await updateSystemInfo();
    await fetchVersion();
    await updateNetworkStatus();

    setInterval(checkStatus, 5000);
    setInterval(updateSystemInfo, 10000);
    setInterval(fetchVersion, 60000);
    setInterval(updateNetworkStatus, 10000);
}

// ------------------------------------------------------------------ status

async function checkStatus() {
    try {
        const data = await apiGet('/status');
        systemStatus = data;

        const indicator = document.getElementById('status-indicator');
        indicator.querySelector('.dot').className = 'dot online';
        document.getElementById('status-text').textContent = 'Online';

        if (data.modules) {
            Object.entries(data.modules).forEach(([name, info]) => {
                const el = document.getElementById(`status-${name}`);
                if (el) {
                    el.textContent = info.available ? '✓ Ready' : '✗ Offline';
                }
            });
        }

        if (data.hostname) {
            document.getElementById('hostname').textContent = data.hostname;
        }

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
        document.getElementById('status-indicator').querySelector('.dot').className = 'dot offline';
        document.getElementById('status-text').textContent = 'Offline';
    }
}

async function updateSystemInfo() {
    try {
        const data = await apiGet('/system/info');
        if (data.uptime) document.getElementById('uptime').textContent = data.uptime;
        if (data.temperature) document.getElementById('temp').textContent = data.temperature;
    } catch (error) {
        // silent - status check handles connectivity
    }
}

async function fetchVersion() {
    try {
        const data = await apiGet('/system/version');
        const el = document.getElementById('current-version');
        if (el && data.sha && data.sha !== 'unknown') {
            el.textContent = `main @ ${data.sha}`;
            el.className = 'value';
        }
    } catch (error) {
        // silent
    }
}

// ------------------------------------------------------------------ module panels

function showModulePanel(module) {
    document.querySelectorAll('.module-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.module-item').forEach(i => i.classList.remove('active'));

    const panel = document.getElementById(`panel-${module}`);
    if (panel) {
        panel.classList.add('active');
        activeModule = module;

        const item = document.querySelector(`.module-item[data-module="${module}"]`);
        if (item) item.classList.add('active');

        if (module === 'ir') irShowTab('library');
        if (module === 'badusb') loadBadusbPayloads();

        log(`Opened ${module.toUpperCase()} panel`);
    }
}

window.addEventListener('error', (e) => {
    log('JS error: ' + e.message);
});
