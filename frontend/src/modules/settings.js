// Settings: network status, Wi-Fi client connect/disconnect, power management
// (auto-shutdown threshold + power off) and OTA system updates.
import { apiGet, apiPost } from '../api.js'
import { subscribe, getState, refreshAll } from '../state.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner } from '../ui.js'
import { esc, signalBars } from '../util.js'
import { startTask, notify } from '../toast.js'

let selectedSsid = null

export default function renderSettings(root) {
  root.innerHTML = `
    ${pageHead('fa-sliders', 'Settings', 'Network, power and updates')}
    <div class="grid lg:grid-cols-2 gap-4">
      ${card(`${sectionTitle('Network status')}<div id="s-net"></div>`)}
      <div id="s-wifi-card">${card(`${sectionTitle('Wi-Fi client')}<div id="s-wifi"></div>`)}</div>
      ${card(`${sectionTitle('Power')}<div id="s-power"></div>`)}
      ${card(`${sectionTitle('System update')}<div id="s-update"></div>`)}
    </div>
  `

  renderPower(root)
  renderUpdatePanel(root)
  renderWifiClient(root)

  const unsub = subscribe((s) => {
    if (!document.body.contains(root)) return unsub()
    renderNet(root, s.network)
    syncUpdateButton(root, s)
  })
}

// ---------------------------------------------------------------- Network status
function renderNet(root, net) {
  const wrap = root.querySelector('#s-net')
  if (!wrap) return
  if (!net) return (wrap.innerHTML = spinner('Loading...'))
  const eth = net.ethernet || {}
  const wc = net.wifi_client || {}
  const row = (icon, label, value, tone) => `
    <div class="flex items-center gap-3 py-2 border-b border-base-300/50 last:border-0">
      <i class="fa-solid ${icon} w-5 text-center text-base-content/45"></i>
      <span class="text-sm flex-1">${esc(label)}</span>
      <span class="text-xs font-semibold ${tone}">${value}</span>
    </div>`
  wrap.innerHTML =
    row('fa-network-wired', 'LAN (eth0)', eth.connected ? esc(eth.ip || 'connected') : 'Not connected', eth.connected ? 'text-success' : 'text-base-content/40') +
    row('fa-tower-cell', 'Access Point', net.ap_mode ? `${esc(net.ap_ssid)} · ${esc(net.ap_ip)}` : 'Down', net.ap_mode ? 'text-success' : 'text-base-content/40') +
    row('fa-wifi', 'Wi-Fi client', wc.adapter_present ? (wc.connected ? esc(wc.ssid) : 'Not connected') : 'No adapter', wc.connected ? 'text-success' : 'text-warning') +
    row('fa-globe', 'Internet', net.internet_available ? `Online (${esc(net.internet_source || '?')})` : 'Offline', net.internet_available ? 'text-success' : 'text-error')
}

// ---------------------------------------------------------------- Wi-Fi client
function renderWifiClient(root) {
  const wrap = root.querySelector('#s-wifi')
  const net = getState().network
  const wc = net?.wifi_client || {}

  if (wc.adapter_present === false) {
    wrap.innerHTML = empty('Alfa adapter not detected.', 'fa-wifi')
    return
  }

  if (wc.connected) {
    wrap.innerHTML = `
      ${infoBox(`Connected to <strong>${esc(wc.ssid)}</strong>${wc.ip ? ` · ${esc(wc.ip)}` : ''}`, 'fa-circle-check')}
      <button id="s-wifi-disc" class="btn btn-outline btn-error btn-sm gap-2 mt-3"><i class="fa-solid fa-link-slash"></i>Disconnect</button>`
    wrap.querySelector('#s-wifi-disc').addEventListener('click', () => disconnect(root))
    return
  }

  wrap.innerHTML = `
    <p class="text-xs text-base-content/55 mb-3">Connect the Alfa adapter to an upstream network for internet (enables seamless updates).</p>
    <button id="s-wifi-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass"></i>Scan networks</button>
    <div id="s-wifi-list" class="mt-3"></div>
    <div id="s-wifi-connect" class="mt-3 hidden"></div>`
  wrap.querySelector('#s-wifi-scan').addEventListener('click', () => scanWifi(root))
}

async function scanWifi(root) {
  const list = root.querySelector('#s-wifi-list')
  list.innerHTML = spinner('Scanning...')
  const task = startTask('Scanning Wi-Fi')
  try {
    const d = await apiGet('/wifi/scan', { timeout: 30000 })
    const nets = d.networks || []
    task.done('Scan complete', `${nets.length} networks`)
    if (!nets.length) return (list.innerHTML = empty('No networks found.'))
    list.innerHTML = nets
      .map(
        (n) => `
      <button class="w-full flex items-center justify-between gap-3 rounded-xl bg-base-200/50 px-3 py-2.5 mb-2 hover:bg-base-200 text-left"
        data-ssid="${esc(n.ssid || '')}">
        <span class="min-w-0"><span class="block font-medium text-sm truncate">${esc(n.ssid || '(hidden)')}</span>
          <span class="block text-[0.65rem] text-base-content/45">${esc(n.security || 'Open')}</span></span>
        <span class="flex items-center gap-2 shrink-0">${signalBars(n.signal_dbm)}</span>
      </button>`,
      )
      .join('')
    list.querySelectorAll('[data-ssid]').forEach((b) =>
      b.addEventListener('click', () => promptConnect(root, b.dataset.ssid)),
    )
  } catch (e) {
    task.fail('Scan failed', e.message)
    list.innerHTML = errorBox(e.message)
  }
}

function promptConnect(root, ssid) {
  selectedSsid = ssid
  const box = root.querySelector('#s-wifi-connect')
  box.classList.remove('hidden')
  box.innerHTML = `
    <label class="form-control">
      <span class="label-text text-xs mb-1">Password for <strong>${esc(ssid)}</strong></span>
      <input id="s-wifi-pw" type="password" class="input input-bordered input-sm" placeholder="Network password" />
    </label>
    <div class="flex gap-2 mt-2">
      <button id="s-wifi-go" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-link"></i>Connect</button>
      <button id="s-wifi-cancel" class="btn btn-ghost btn-sm">Cancel</button>
    </div>
    <div id="s-wifi-msg" class="mt-2"></div>`
  box.querySelector('#s-wifi-pw').focus()
  box.querySelector('#s-wifi-go').addEventListener('click', () => connect(root))
  box.querySelector('#s-wifi-cancel').addEventListener('click', () => box.classList.add('hidden'))
}

async function connect(root) {
  const pw = root.querySelector('#s-wifi-pw').value
  const msg = root.querySelector('#s-wifi-msg')
  if (!pw || !selectedSsid) return
  msg.innerHTML = spinner(`Connecting to ${selectedSsid}...`)
  const task = startTask('Wi-Fi connect', selectedSsid)
  try {
    const d = await apiPost('/network/wifi-connect', { ssid: selectedSsid, password: pw }, { timeout: 40000 })
    if (!d.success) throw new Error(d.error || 'Connection failed')
    task.done('Connected', `${selectedSsid}${d.ip ? ` · ${d.ip}` : ''}`)
    refreshAll()
    setTimeout(() => renderWifiClient(root), 800)
  } catch (e) {
    task.fail('Connect failed', e.message)
    msg.innerHTML = errorBox(e.message)
  }
}

async function disconnect(root) {
  const task = startTask('Disconnecting Wi-Fi')
  try {
    await apiPost('/network/wifi-disconnect')
    task.done('Disconnected')
    refreshAll()
    setTimeout(() => renderWifiClient(root), 800)
  } catch (e) {
    task.fail('Disconnect failed', e.message)
  }
}

// ---------------------------------------------------------------- Power
async function renderPower(root) {
  const wrap = root.querySelector('#s-power')
  wrap.innerHTML = `
    <div class="flex items-baseline justify-between gap-2 mb-2">
      <span class="text-sm font-medium">Auto shutdown</span>
      <span class="text-sm font-semibold text-primary"><span id="s-pct">...</span>% battery</span>
    </div>
    <input id="s-slider" type="range" min="0" max="50" value="10" class="range range-primary range-sm w-full" />
    <div class="flex justify-between text-[0.65rem] text-base-content/40 px-0.5 mt-1"><span>0%</span><span>50%</span></div>
    <button id="s-poweroff" class="btn btn-error btn-outline btn-sm gap-2 mt-5"><i class="fa-solid fa-power-off"></i>Power off</button>
  `
  const slider = wrap.querySelector('#s-slider')
  const label = wrap.querySelector('#s-pct')
  try {
    const d = await apiGet('/system/power/shutdown-percentage')
    slider.value = d.percentage
    label.textContent = d.percentage
  } catch (e) {
    label.textContent = '?'
  }
  slider.addEventListener('input', () => (label.textContent = slider.value))
  slider.addEventListener('change', async () => {
    try {
      await apiPost('/system/power/shutdown-percentage', { percentage: parseInt(slider.value) })
      notify('Shutdown threshold set', 'success', `${slider.value}% battery`)
    } catch (e) {
      notify('Failed to set threshold', 'error', e.message)
    }
  })
  wrap.querySelector('#s-poweroff').addEventListener('click', confirmPoweroff)
}

function confirmPoweroff() {
  const dlg = document.createElement('dialog')
  dlg.className = 'modal modal-open'
  dlg.innerHTML = `
    <div class="modal-box">
      <h3 class="font-bold text-lg flex items-center gap-2"><i class="fa-solid fa-power-off text-error"></i>Power off</h3>
      <p class="py-3 text-sm text-base-content/70">Shut down ChonkyFlipper? You will need physical access to turn it back on.</p>
      <div class="modal-action">
        <button id="po-cancel" class="btn btn-ghost btn-sm">Cancel</button>
        <button id="po-go" class="btn btn-error btn-sm gap-2"><i class="fa-solid fa-power-off"></i>Power off</button>
      </div>
    </div>`
  document.body.appendChild(dlg)
  dlg.querySelector('#po-cancel').addEventListener('click', () => dlg.remove())
  dlg.querySelector('#po-go').addEventListener('click', async () => {
    dlg.remove()
    const task = startTask('Powering off')
    try {
      await apiPost('/system/poweroff')
    } catch (e) {
      /* server goes away - expected */
    }
    task.info('Shutting down', 'Reconnect after restart')
  })
}

// ---------------------------------------------------------------- Update
function renderUpdatePanel(root) {
  const wrap = root.querySelector('#s-update')
  wrap.innerHTML = `
    <p class="text-xs text-base-content/55">Current version: <span id="s-ver" class="font-mono font-semibold">...</span></p>
    <p id="s-update-hint" class="text-xs text-base-content/45 mt-1">Checking internet...</p>
    <button id="s-update-btn" class="btn btn-primary btn-sm gap-2 mt-3" disabled><i class="fa-brands fa-github"></i>Update from GitHub</button>
    <div id="s-update-out" class="console mt-3 hidden"></div>
  `
  wrap.querySelector('#s-update-btn').addEventListener('click', () => runUpdate(root))
}

function syncUpdateButton(root, s) {
  const ver = root.querySelector('#s-ver')
  const btn = root.querySelector('#s-update-btn')
  const hint = root.querySelector('#s-update-hint')
  if (!ver || !btn) return
  if (s.version?.sha && s.version.sha !== 'unknown') ver.textContent = `main @ ${s.version.sha}`
  const online = s.network?.internet_available
  btn.disabled = !online
  hint.textContent = online
    ? `Internet via ${s.network.internet_source || 'unknown'}. Updates keep the AP up.`
    : 'Connect a LAN cable or Wi-Fi client for internet access.'
}

async function runUpdate(root) {
  const out = root.querySelector('#s-update-out')
  out.classList.remove('hidden')
  out.textContent = 'Starting update...'
  const task = startTask('System update', 'Pulling from GitHub')
  try {
    const d = await apiPost('/system/update', {}, { timeout: 30000 })
    if (!d.success) throw new Error(d.error || 'Update failed')
    out.textContent = d.message || 'Update started'
    let n = 0
    const poll = setInterval(async () => {
      n++
      out.textContent = `Update in progress... (${n})`
      task.update(`waiting for restart (${n})`)
      try {
        await apiGet('/status', { timeout: 4000 })
        clearInterval(poll)
        out.textContent = 'Update complete. Backend back online.'
        task.done('Update complete')
        refreshAll()
      } catch (e) {
        /* still restarting */
      }
      if (n > 30) {
        clearInterval(poll)
        out.textContent = 'Update timed out. Check system status.'
        task.fail('Update timed out')
      }
    }, 2000)
  } catch (e) {
    task.fail('Update failed', e.message)
    out.textContent = e.message
  }
}
