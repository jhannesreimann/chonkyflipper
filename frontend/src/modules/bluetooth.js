// Bluetooth: BLE scan / beacons / advert log / GATT, Classic (BR/EDR) discovery
// + SDP, bettercap deep scan, and advertisement spoofing.  Tab-based layout
// matching the Wi‑Fi module pattern.
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner, tabBar } from '../ui.js'
import { esc, fmtBytes } from '../util.js'
import { startTask, notify } from '../toast.js'

const TABS = [
  { id: 'scan', label: 'Scan', icon: 'fa-magnifying-glass' },
  { id: 'classic', label: 'Classic', icon: 'fa-bluetooth-b' },
  { id: 'deep', label: 'Deep', icon: 'fa-magnifying-glass-chart' },
  { id: 'spoof', label: 'Spoof', icon: 'fa-tower-broadcast' },
  { id: 'capture', label: 'Capture', icon: 'fa-wave-square' },
]

let active = 'scan'

export default function renderBluetooth(root) {
  root.innerHTML = `
    ${pageHead('fa-bluetooth-b', 'Bluetooth', 'Built-in dual-mode · hci0')}
    ${tabBar(TABS, active)}
    <div id="b-body"></div>
  `
  root.querySelectorAll('[data-tab]').forEach((el) => {
    el.addEventListener('click', () => {
      active = el.dataset.tab
      root.querySelectorAll('[data-tab]').forEach((t) => t.classList.toggle('tab-active', t.dataset.tab === active))
      paint(root)
    })
  })
  paint(root)
}

function paint(root) {
  const body = root.querySelector('#b-body')
  if (active === 'scan') return scanTab(body)
  if (active === 'classic') return classicTab(body)
  if (active === 'deep') return deepTab(body)
  if (active === 'spoof') return spoofTab(body)
  if (active === 'capture') return captureTab(body)
}

// ------------------------------------------------------------------ Scan tab (BLE)
function scanTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('BLE discovery', `
      <select id="b-cap-dur" class="select select-sm select-bordered w-auto">
        <option value="5">5s</option>
        <option value="8" selected>8s</option>
        <option value="15">15s</option>
        <option value="30">30s</option>
      </select>
      <button id="b-log" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-clock-rotate-left"></i><span id="b-log-label">Log</span></button>
      <button id="b-beacons" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-satellite-dish"></i>Beacons</button>
      <button id="b-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass"></i>Scan</button>
    `)}
    <div id="b-out">${empty('Scan to discover nearby BLE devices.', 'fa-bluetooth')}</div>
  `)
  body.querySelector('#b-scan').addEventListener('click', () => bleScan(body))
  body.querySelector('#b-beacons').addEventListener('click', () => beacons(body))
  body.querySelector('#b-log').addEventListener('click', () => toggleLogDaemon(body))
  refreshLogStatus(body)
  // Resume polling if daemon was already running
  apiGet('/bluetooth/log/status').then((s) => { if (s.running) startLogPolling(body) }).catch(() => {})
}

// ------------------------------------------------------------------ Classic tab
function classicTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('BR/EDR discovery', `
      <select id="b-classic-dur" class="select select-sm select-bordered w-auto">
        <option value="5">5s</option>
        <option value="10" selected>10s</option>
        <option value="20">20s</option>
        <option value="30">30s</option>
      </select>
      <button id="b-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass"></i>Scan</button>
    `)}
    <div id="b-out">${empty('Scan for discoverable BR/EDR devices.', 'fa-bluetooth')}</div>
  `)
  body.querySelector('#b-scan').addEventListener('click', () => scanClassic(body))
}

// ------------------------------------------------------------------ Deep tab
function deepTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Deep BLE scan (bettercap)', `
      <button id="b-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass-chart"></i>Scan 15s</button>
    `)}
    ${infoBox('Uses <strong>bettercap</strong> for vendor identification and richer metadata.')}
    <div id="b-out" class="mt-3">${empty('Run a deep scan to identify nearby BLE devices.', 'fa-bluetooth')}</div>
  `)
  body.querySelector('#b-scan').addEventListener('click', () => deepScan(body))
}

// ------------------------------------------------------------------ Capture tab (HCI)
function captureTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('HCI packet capture', `
      <select id="b-hci-dur" class="select select-sm select-bordered w-auto">
        <option value="10">10s</option>
        <option value="30" selected>30s</option>
        <option value="60">60s</option>
      </select>
      <button id="b-hci" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-wave-square"></i>Capture</button>
    `)}
    ${infoBox('Captures raw HCI traffic via <strong>btmon</strong> for offline Wireshark analysis. Saved files also appear in the Loot file manager.')}
    <div id="b-out" class="mt-3">${empty('Choose a duration and start capturing.', 'fa-wave-square')}</div>
  `)
  body.querySelector('#b-hci').addEventListener('click', () => {
    const dur = parseInt(body.querySelector('#b-hci-dur').value, 10) || 30
    hciCapture(body, dur)
  })
}

// ------------------------------------------------------------------ Spoof tab
function spoofTab(body) {
  body.innerHTML = card(`
    <div class="rounded-xl bg-base-200/40 p-4 space-y-3">
      <p class="text-[0.7rem] text-base-content/55">Broadcast a crafted BLE advertisement. Authorized testing only.</p>
      <div id="sp-status"></div>

      <div class="grid grid-cols-2 gap-2">
        <label class="form-control">
          <span class="label-text text-xs">Frame</span>
          <select id="sp-frame" class="select select-sm select-bordered">
            <option value="custom">Custom</option>
            <option value="ibeacon">iBeacon</option>
            <option value="eddystone-url">Eddystone URL</option>
            <option value="eddystone-uid">Eddystone UID</option>
          </select>
        </label>
        <label class="form-control">
          <span class="label-text text-xs">Duration (s)</span>
          <input id="sp-duration" type="number" value="60" min="1" max="600" class="input input-sm input-bordered" />
        </label>
      </div>

      <label class="form-control">
        <span class="label-text text-xs">Device name</span>
        <input id="sp-name" type="text" placeholder="Fake Device" class="input input-sm input-bordered w-full" />
      </label>

      <div data-grp="custom" class="space-y-2">
        <label class="form-control">
          <span class="label-text text-xs">Service UUIDs (comma-separated)</span>
          <input id="sp-uuids" type="text" placeholder="180d, feaa" class="input input-sm input-bordered w-full font-mono" />
        </label>
        <div class="grid grid-cols-2 gap-2">
          <label class="form-control"><span class="label-text text-xs">Manufacturer ID</span><input id="sp-mfg-id" type="number" placeholder="76" class="input input-sm input-bordered" /></label>
          <label class="form-control"><span class="label-text text-xs">Mfg data (hex)</span><input id="sp-mfg-data" type="text" placeholder="01ff" class="input input-sm input-bordered font-mono" /></label>
        </div>
      </div>

      <div data-grp="ibeacon" class="space-y-2" style="display:none;">
        <label class="form-control">
          <span class="label-text text-xs">Proximity UUID (16 bytes)</span>
          <input id="sp-uuid" type="text" placeholder="e2c56db5dffb48d2b060d0f5a71096e0" class="input input-sm input-bordered w-full font-mono" />
        </label>
        <div class="grid grid-cols-3 gap-2">
          <label class="form-control"><span class="label-text text-xs">Major</span><input id="sp-major" type="number" value="0" class="input input-sm input-bordered" /></label>
          <label class="form-control"><span class="label-text text-xs">Minor</span><input id="sp-minor" type="number" value="0" class="input input-sm input-bordered" /></label>
          <label class="form-control"><span class="label-text text-xs">TX @1m</span><input id="sp-tx" type="number" value="-59" class="input input-sm input-bordered" /></label>
        </div>
      </div>

      <div data-grp="eddystone-url" class="space-y-2" style="display:none;">
        <label class="form-control">
          <span class="label-text text-xs">URL</span>
          <input id="sp-url" type="text" placeholder="https://example.com" class="input input-sm input-bordered w-full font-mono" />
        </label>
      </div>

      <div data-grp="eddystone-uid" class="grid grid-cols-2 gap-2" style="display:none;">
        <label class="form-control"><span class="label-text text-xs">Namespace (10 bytes)</span><input id="sp-ns" type="text" class="input input-sm input-bordered font-mono" /></label>
        <label class="form-control"><span class="label-text text-xs">Instance (6 bytes)</span><input id="sp-inst" type="text" class="input input-sm input-bordered font-mono" /></label>
      </div>

      <label class="label cursor-pointer justify-start gap-2">
        <input id="sp-txp" type="checkbox" class="checkbox checkbox-sm" />
        <span class="label-text text-xs">Include TX power</span>
      </label>

      <div class="flex gap-2">
        <button id="sp-start" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-tower-broadcast"></i>Start</button>
        <button id="sp-stop" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-stop"></i>Stop</button>
      </div>
    </div>`)

  const frame = body.querySelector('#sp-frame')
  const showGroups = () => {
    body.querySelectorAll('[data-grp]').forEach((g) => {
      g.style.display = g.dataset.grp === frame.value ? '' : 'none'
    })
  }
  frame.addEventListener('change', showGroups)
  showGroups()
  body.querySelector('#sp-start').addEventListener('click', () => startSpoof(body))
  body.querySelector('#sp-stop').addEventListener('click', () => stopSpoof(body))
  refreshSpoofStatus(body)
}

// ---------------------------------------------------------------- BLE scan
async function bleScan(body) {
  const dur = parseInt(body.querySelector('#b-cap-dur')?.value, 10) || 8
  const out = body.querySelector('#b-out')
  out.innerHTML = spinner(`Scanning BLE devices for ${dur}s...`)
  const task = startTask('Scanning BLE')
  try {
    const d = await apiGet(`/bluetooth/scan?duration=${dur}`, { timeout: (dur + 15) * 1000 })
    const devs = d.devices || []
    task.done('BLE scan complete', `${devs.length} device(s)`)
    if (!devs.length) return (out.innerHTML = empty('No BLE devices found.'))
    out.innerHTML = `
      <div class="overflow-x-auto"><table class="table table-sm">
        <thead><tr><th>Device</th><th>MAC</th><th>RSSI</th><th></th></tr></thead>
        <tbody>${devs.map((d) => `<tr>
          <td class="font-medium">${esc(d.name || 'Unknown')}</td>
          <td class="font-mono text-xs">${esc(d.mac || '-')}</td>
          <td class="text-xs">${esc(d.rssi ?? '-')} dBm</td>
          <td class="text-right"><button class="btn btn-ghost btn-xs gap-1" data-profile="${esc(d.mac)}"><i class="fa-solid fa-sitemap"></i>Profile</button></td>
        </tr>`).join('')}</tbody>
      </table></div>
      <div id="b-gatt" class="mt-4"></div>`
    out.querySelectorAll('[data-profile]').forEach((b) =>
      b.addEventListener('click', () => profile(body, b.dataset.profile)))
  } catch (e) {
    task.fail('BLE scan failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- GATT profiling
async function profile(body, mac) {
  const gatt = body.querySelector('#b-gatt')
  gatt.innerHTML = spinner('Connecting and reading GATT...')
  const task = startTask('GATT profile', mac)
  try {
    const d = await apiPost('/bluetooth/gatt', { mac })
    const services = d.services || []
    task.done('GATT profile complete', `${services.length} service(s)`)
    if (!services.length) return (gatt.innerHTML = empty('No services found (device may require pairing).', 'fa-sitemap'))
    gatt.innerHTML = gattView(mac, services)
    gatt.querySelectorAll('[data-write]').forEach((btn) =>
      btn.addEventListener('click', () => gattWrite(mac, btn)))
  } catch (e) {
    task.fail('GATT profile failed', e.message)
    gatt.innerHTML = errorBox(e.message)
  }
}

function gattView(mac, services) {
  const body = services.map((svc) => {
    const chars = (svc.characteristics || []).map(charRow).join('')
    return `<div class="rounded-xl bg-base-200/50 p-3 mb-2">
      <div class="flex items-center justify-between gap-2 mb-2">
        <span class="font-semibold text-sm">${esc(svc.name || 'Unknown service')}</span>
        <span class="font-mono text-[0.6rem] text-base-content/45">${esc(shortUuid(svc.uuid))}</span>
      </div>
      ${chars || '<p class="text-xs text-base-content/45">No characteristics.</p>'}
    </div>`
  }).join('')
  return `${sectionTitle('GATT profile', `<span class="font-mono text-[0.65rem] text-base-content/50">${esc(mac)}</span>`)}${body}`
}

function charRow(c) {
  const propList = c.properties || []
  const props = propList.map((p) => `<span class="badge badge-xs badge-ghost">${esc(p)}</span>`).join(' ')
  const val = c.value_text
    ? `<div class="text-xs mt-1"><span class="text-base-content/45">value:</span> ${esc(c.value_text)}</div>`
    : c.value_hex ? `<div class="text-[0.65rem] font-mono mt-1 break-all text-base-content/55">${esc(c.value_hex)}</div>` : ''
  const desc = c.descriptors && c.descriptors.length
    ? `<div class="text-[0.6rem] text-base-content/40 mt-1">${c.descriptors.length} descriptor(s)</div>` : ''
  const canWrite = propList.includes('write') || propList.includes('write-without-response')
  const noResp = propList.includes('write-without-response') && !propList.includes('write')
  const writeRow = canWrite ? `<div class="flex items-center gap-1 mt-1.5" data-write-row>
    <select class="select select-xs select-bordered w-auto" data-fmt>
      <option value="hex" selected>hex</option>
      <option value="ascii">ascii</option>
    </select>
    <input class="input input-xs input-bordered flex-1 font-mono" placeholder="value to write" data-wval />
    <button class="btn btn-xs btn-ghost gap-1" data-write="${esc(c.uuid)}" data-wr="${noResp ? '1' : ''}"><i class="fa-solid fa-pen-to-square"></i>Write</button>
  </div>` : ''
  return `<div class="rounded-lg bg-base-100/60 px-3 py-2 mb-1">
    <div class="flex items-center justify-between gap-2">
      <span class="text-xs font-medium">${esc(c.name || 'Unknown characteristic')}</span>
      <span class="flex gap-1 flex-wrap justify-end">${props}</span>
    </div>
    <div class="font-mono text-[0.6rem] text-base-content/45">${esc(shortUuid(c.uuid))}</div>
    ${val}${desc}${writeRow}
  </div>`
}

function shortUuid(uuid) {
  if (!uuid) return ''
  const m = /^0000([0-9a-f]{4})-0000-1000-8000-00805f9b34fb$/i.exec(uuid)
  return m ? '0x' + m[1].toUpperCase() : uuid
}

async function gattWrite(mac, btn) {
  const row = btn.closest('[data-write-row]')
  const fmt = row.querySelector('[data-fmt]').value
  const rawValue = row.querySelector('[data-wval]').value
  const charUuid = btn.dataset.write
  const withoutResponse = btn.dataset.wr === '1'
  let hex
  try { hex = fmt === 'ascii' ? asciiToHex(rawValue) : normalizeHex(rawValue) }
  catch (e) { return notify('Invalid value', 'error', e.message) }
  if (!hex) return notify('Enter a value to write', 'warning')
  const task = startTask('GATT write', shortUuid(charUuid))
  try {
    const d = await apiPost('/bluetooth/gatt/write', { mac, char_uuid: charUuid, value: hex, without_response: withoutResponse })
    task.done('Write succeeded', `${d.bytes_written} byte(s)${d.with_response ? '' : ', no response'}`)
  } catch (e) { task.fail('Write failed', e.message) }
}

function asciiToHex(s) {
  let out = ''
  for (let i = 0; i < s.length; i++) {
    const code = s.charCodeAt(i)
    if (code > 0xff) throw new Error('non-ASCII character in input')
    out += code.toString(16).padStart(2, '0')
  }
  return out
}

function normalizeHex(s) {
  const h = s.replace(/0x/gi, '').replace(/[\s:]/g, '')
  if (h && !/^[0-9a-f]+$/i.test(h)) throw new Error('not valid hex')
  if (h.length % 2 !== 0) throw new Error('hex needs an even number of digits')
  return h.toLowerCase()
}

// ---------------------------------------------------------------- BLE beacons
async function beacons(body) {
  const dur = parseInt(body.querySelector('#b-cap-dur')?.value, 10) || 8
  const out = body.querySelector('#b-out')
  out.innerHTML = spinner(`Scanning for beacons for ${dur}s...`)
  const task = startTask('Scanning beacons')
  try {
    const d = await apiGet(`/bluetooth/beacons?duration=${dur}`, { timeout: (dur + 15) * 1000 })
    const bs = d.beacons || []
    task.done('Beacon scan complete', `${bs.length} beacon(s)`)
    if (!bs.length) return (out.innerHTML = empty('No iBeacon / Eddystone beacons detected.'))
    out.innerHTML = `<div class="overflow-x-auto"><table class="table table-sm">
      <thead><tr><th>Type</th><th>UUID / ID</th><th>RSSI</th></tr></thead>
      <tbody>${bs.map((b) => `<tr>
        <td>${esc(b.type || 'beacon')}</td>
        <td class="font-mono text-[0.65rem]">${esc(b.uuid || b.namespace || b.id || '-')}</td>
        <td class="text-xs">${esc(b.rssi ?? '-')} dBm</td>
      </tr>`).join('')}</tbody>
    </table></div>`
  } catch (e) {
    task.fail('Beacon scan failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- background ad log daemon
let _logPoll = null

async function toggleLogDaemon(body) {
  const status = await apiGet('/bluetooth/log/status')
  if (status.running) { await stopLogDaemon(body) }
  else { await startLogDaemon(body) }
}

async function startLogDaemon(body) {
  const task = startTask('Starting ad log daemon')
  try {
    const d = await apiPost('/bluetooth/log/start')
    task.done('Log daemon running', `pid ${d.pid}`)
    refreshLogStatus(body)
    startLogPolling(body)
  } catch (e) { task.fail('Log daemon failed to start', e.message) }
}

async function stopLogDaemon(body) {
  try { await apiPost('/bluetooth/log/stop'); notify('Log daemon stopped', 'success') }
  catch (e) { notify('Stop failed', 'error', e.message) }
  refreshLogStatus(body)
  stopLogPolling(body)
}

async function refreshLogStatus(body) {
  const label = body.querySelector('#b-log-label')
  const btn = body.querySelector('#b-log')
  if (!label || !btn) return
  try {
    const d = await apiGet('/bluetooth/log/status')
    if (d.running) {
      label.textContent = 'Stop'
      btn.classList.add('btn-error', 'btn-outline')
      btn.classList.remove('btn-ghost')
    } else {
      label.textContent = 'Log'
      btn.classList.remove('btn-error', 'btn-outline')
      btn.classList.add('btn-ghost')
    }
  } catch (e) { /* button stays in default state */ }
}

function startLogPolling(body) {
  stopLogPolling(body)
  _logPoll = setInterval(() => { if (active === 'scan') refreshLogData(body) }, 5000)
  refreshLogData(body)
}

function stopLogPolling(body) {
  if (_logPoll) { clearInterval(_logPoll); _logPoll = null }
  const headEl = body.querySelector('#b-log-head')
  if (headEl) headEl.innerHTML = '<span class="text-[0.65rem] text-base-content/50">Advert log stopped</span>'
  refreshLogStatus(body)
}

async function refreshLogData(body) {
  try {
    const d = await apiGet('/bluetooth/log/data')
    if (!d.running) { stopLogPolling(body); return }
    const out = body.querySelector('#b-out')
    const devices = d.devices || []
    if (!devices.length) { out.innerHTML = empty('Listening for advertisements...', 'fa-clock-rotate-left'); return }
    const elapsed = d.started_at ? elapsedTime(d.started_at) : ''
    out.innerHTML = advertLogViewDaemon(d, elapsed)
  } catch (e) { /* keep stale data */ }
}

function advertLogViewDaemon(d, elapsed) {
  const rows = (d.devices || []).map((dev) => `<tr>
    <td class="font-medium">${esc(dev.name || 'Unknown')}${dev.beacon ? ` <span class="badge badge-xs badge-ghost">${esc(dev.beacon)}</span>` : ''}</td>
    <td class="font-mono text-xs">${esc(dev.mac)}</td>
    <td class="text-xs text-center">${dev.count}</td>
    <td class="text-xs">${rssiRange(dev)}</td>
    <td class="text-xs">${esc(timeOnly(dev.last_seen))}</td>
  </tr>`).join('')
  return `<div id="b-log-head" class="flex items-center justify-between mb-2">
    ${sectionTitle('Advertisement log', `<span class="text-[0.65rem] text-base-content/50">${d.total_sightings} sightings · ${d.device_count} devices · ${elapsed}</span>`)}
  </div>
  <div class="overflow-x-auto"><table class="table table-sm">
    <thead><tr><th>Device</th><th>MAC</th><th>Seen</th><th>RSSI</th><th>Last</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`
}

function elapsedTime(startedAt) {
  try {
    const diff = Date.now() - new Date(startedAt).getTime()
    const m = Math.floor(diff / 60000)
    const s = Math.floor((diff % 60000) / 1000)
    return m > 0 ? `${m}m ${s}s` : `${s}s`
  } catch (e) { return '' }
}

function rssiRange(dev) {
  if (dev.rssi_last === null || dev.rssi_last === undefined) return '-'
  if (dev.rssi_min === dev.rssi_max) return `${dev.rssi_last} dBm`
  return `${dev.rssi_last} <span class="text-base-content/40">(${dev.rssi_min}..${dev.rssi_max})</span>`
}

function timeOnly(iso) {
  if (!iso) return ''
  try { return new Date(iso).toLocaleTimeString() } catch (e) { return '' }
}

// ---------------------------------------------------------------- HCI capture
async function hciCapture(body, dur) {
  const out = body.querySelector('#b-out')
  out.innerHTML = spinner(`Capturing HCI for ${dur}s...`)
  const task = startTask('HCI capture', `${dur}s`)
  try {
    const d = await apiPost('/bluetooth/capture-hci', { duration: dur }, { timeout: (dur + 30) * 1000 })
    task.done('HCI capture complete', d.filename)
    const href = `/api/loot/download?category=hci&name=${encodeURIComponent(d.filename)}`
    out.innerHTML = `<div class="rounded-xl bg-base-200/50 p-4 text-sm">
      <div class="font-semibold mb-1"><i class="fa-solid fa-circle-check text-success mr-1"></i>Capture saved</div>
      <div class="text-base-content/60 text-xs mb-3 font-mono break-all">${esc(d.filename)} · ${fmtBytes(d.size)}</div>
      <a href="${href}" class="btn btn-primary btn-sm gap-2" download><i class="fa-solid fa-download"></i>Download .pcap</a>
      <p class="text-[0.65rem] text-base-content/45 mt-3">Open in Wireshark for protocol analysis. Also listed in the Loot file manager.</p>
    </div>`
  } catch (e) {
    task.fail('HCI capture failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- Deep scan (bettercap)
async function deepScan(body) {
  const out = body.querySelector('#b-out')
  out.innerHTML = spinner('Deep scanning with bettercap (~15s)...')
  const task = startTask('Deep BLE scan')
  try {
    const d = await apiPost('/bluetooth/deep-scan', { duration: 15 }, { timeout: 60000 })
    const devs = d.devices || []
    task.done('Deep scan complete', `${devs.length} device(s)`)
    if (!devs.length) return (out.innerHTML = empty('No devices found.', 'fa-bluetooth'))
    out.innerHTML = `<div class="overflow-x-auto"><table class="table table-sm">
      <thead><tr><th>Device</th><th>MAC</th><th>Vendor</th><th>RSSI</th></tr></thead>
      <tbody>${devs.map((d) => `<tr>
        <td class="font-medium">${esc(d.name || 'Unknown')}</td>
        <td class="font-mono text-xs">${esc(d.mac)}</td>
        <td class="text-xs">${esc(d.vendor || '-')}</td>
        <td class="text-xs whitespace-nowrap">${esc(d.rssi ?? '-')} dBm</td>
      </tr>`).join('')}</tbody>
    </table></div>`
  } catch (e) {
    task.fail('Deep scan failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- advertisement spoofing
async function startSpoof(body) {
  const v = (id) => body.querySelector('#' + id).value.trim()
  const frame = v('sp-frame')
  const params = {
    frame,
    name: v('sp-name'),
    duration: parseInt(v('sp-duration'), 10) || 60,
    include_tx_power: body.querySelector('#sp-txp').checked,
  }
  if (frame === 'custom') {
    const uuids = v('sp-uuids')
    if (uuids) params.service_uuids = uuids.split(',').map((s) => s.trim()).filter(Boolean)
    if (v('sp-mfg-id')) params.manufacturer_id = parseInt(v('sp-mfg-id'), 10)
    if (v('sp-mfg-data')) params.manufacturer_data = v('sp-mfg-data')
  } else if (frame === 'ibeacon') {
    params.uuid = v('sp-uuid'); params.major = parseInt(v('sp-major'), 10) || 0
    params.minor = parseInt(v('sp-minor'), 10) || 0; params.tx_power = parseInt(v('sp-tx'), 10) || -59
  } else if (frame === 'eddystone-url') {
    params.url = v('sp-url')
  } else if (frame === 'eddystone-uid') {
    params.namespace = v('sp-ns'); params.instance = v('sp-inst')
  }
  const task = startTask('BLE spoof', frame)
  try {
    const d = await apiPost('/bluetooth/spoof', params)
    task.done('Advertising', `${d.frame}, ${d.duration}s`)
    refreshSpoofStatus(body)
  } catch (e) { task.fail('Spoof failed', e.message) }
}

async function stopSpoof(body) {
  try { await apiPost('/bluetooth/spoof/stop'); notify('Spoof stopped', 'success'); refreshSpoofStatus(body) }
  catch (e) { notify('Stop failed', 'error', e.message) }
}

async function refreshSpoofStatus(body) {
  const el = body.querySelector('#sp-status')
  if (!el) return
  try {
    const d = await apiGet('/bluetooth/spoof/status')
    el.innerHTML = d.running
      ? `<div class="rounded-lg bg-success/15 text-success text-xs px-3 py-2 flex items-center gap-2"><i class="fa-solid fa-tower-broadcast"></i>Advertising (pid ${esc(d.pid)})</div>`
      : `<div class="rounded-lg bg-base-300/40 text-base-content/60 text-xs px-3 py-2">Not advertising</div>`
  } catch (e) { el.innerHTML = '' }
}

// ---------------------------------------------------------------- Classic (BR/EDR) + SDP
async function scanClassic(body) {
  const dur = parseInt(body.querySelector('#b-classic-dur')?.value, 10) || 10
  const out = body.querySelector('#b-out')
  out.innerHTML = spinner(`Scanning Classic (BR/EDR) devices for ${dur}s...`)
  const task = startTask('Classic scan')
  try {
    const d = await apiGet(`/bluetooth/classic-scan?duration=${dur}`, { timeout: (dur + 30) * 1000 })
    const devs = d.devices || []
    task.done('Classic scan complete', `${devs.length} device(s)`)
    if (!devs.length) return (out.innerHTML = empty('No Classic devices found. Make sure targets are discoverable.', 'fa-bluetooth'))
    out.innerHTML = devs.map(classicRow).join('')
    out.querySelectorAll('[data-sdp]').forEach((b) => b.addEventListener('click', () => sdp(body, b.dataset.sdp)))
  } catch (e) {
    task.fail('Classic scan failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

function classicRow(d) {
  const detailId = 'sdp-' + d.mac.replace(/:/g, '')
  const meta = [d.mac, d.type || 'device'].join(' · ') + (d.rssi != null ? ` · ${d.rssi} dBm` : '')
  return `<div class="rounded-xl bg-base-200/50 p-3 mb-2">
    <div class="flex items-center justify-between gap-3">
      <div class="min-w-0">
        <div class="font-semibold text-sm truncate">${esc(d.name || 'Unknown')}</div>
        <div class="text-[0.65rem] text-base-content/45 font-mono">${esc(meta)}</div>
      </div>
      <button class="btn btn-ghost btn-xs gap-1 shrink-0" data-sdp="${esc(d.mac)}"><i class="fa-solid fa-list-ul"></i>SDP</button>
    </div>
    <div id="${detailId}" class="mt-2"></div>
  </div>`
}

async function sdp(body, mac) {
  const wrap = body.querySelector('#sdp-' + mac.replace(/:/g, ''))
  if (!wrap) return
  wrap.innerHTML = spinner('Browsing SDP services...')
  const task = startTask('SDP browse', mac)
  try {
    const d = await apiPost('/bluetooth/sdp', { mac }, { timeout: 30000 })
    const services = d.services || []
    task.done('SDP browse complete', `${services.length} service(s)`)
    if (!services.length) return (wrap.innerHTML = infoBox('No SDP services advertised.'))
    wrap.innerHTML = sdpTable(services)
  } catch (e) {
    task.fail('SDP browse failed', e.message)
    wrap.innerHTML = errorBox(e.message)
  }
}

function sdpTable(services) {
  return `<div class="overflow-x-auto"><table class="table table-xs">
    <thead><tr><th>Service</th><th>Proto</th><th>Ch</th></tr></thead>
    <tbody>${services.map((s) => `<tr>
      <td>${esc(s.name || (s.service_classes && s.service_classes[0]) || 'Unknown')}</td>
      <td class="text-xs">${esc(s.protocol || '-')}</td>
      <td class="text-xs">${esc(s.channel ?? '-')}</td>
    </tr>`).join('')}</tbody>
  </table></div>`
}
