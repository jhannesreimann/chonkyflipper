// Bluetooth scanner: BLE (scan / beacons / advert log / GATT) and Classic (BR/EDR
// discovery + SDP service enumeration), switched via a mode toggle.
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner } from '../ui.js'
import { esc, fmtBytes } from '../util.js'
import { startTask, notify } from '../toast.js'

let mode = 'le'

export default function renderBluetooth(root) {
  root.innerHTML = `
    ${pageHead('fa-bluetooth-b', 'Bluetooth', 'Built-in dual-mode · hci0')}
    ${card(`
      <div class="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div class="join">
          <button class="join-item btn btn-sm ${mode === 'le' ? 'btn-active' : ''}" data-mode="le">BLE</button>
          <button class="join-item btn btn-sm ${mode === 'classic' ? 'btn-active' : ''}" data-mode="classic">Classic</button>
        </div>
        <div id="b-actions" class="flex items-center gap-2"></div>
      </div>
      <div class="flex items-center gap-2 mb-3">
        <select id="b-hci-dur" class="select select-xs select-bordered w-auto">
          <option value="10">10s</option>
          <option value="30" selected>30s</option>
          <option value="60">60s</option>
        </select>
        <button id="b-hci" class="btn btn-ghost btn-xs gap-1"><i class="fa-solid fa-wave-square"></i>Capture HCI (Wireshark)</button>
      </div>
      <div id="b-out">${empty('Scan to discover nearby devices.', 'fa-bluetooth')}</div>
    `)}
  `
  root.querySelectorAll('[data-mode]').forEach((b) =>
    b.addEventListener('click', () => {
      if (mode === b.dataset.mode) return
      mode = b.dataset.mode
      renderBluetooth(root)
    }),
  )
  renderActions(root)
  root
    .querySelector('#b-hci')
    .addEventListener('click', () => captureHci(root, parseInt(root.querySelector('#b-hci-dur').value, 10) || 30))
}

function renderActions(root) {
  const el = root.querySelector('#b-actions')
  if (mode === 'le') {
    el.innerHTML = `
      <select id="b-cap-dur" class="select select-sm select-bordered w-auto">
        <option value="15">15s</option>
        <option value="30" selected>30s</option>
        <option value="60">60s</option>
      </select>
      <button id="b-capture" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-clock-rotate-left"></i>Log</button>
      <button id="b-beacons" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-satellite-dish"></i>Beacons</button>
      <button id="b-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass"></i>Scan</button>`
    el.querySelector('#b-scan').addEventListener('click', () => scan(root))
    el.querySelector('#b-beacons').addEventListener('click', () => beacons(root))
    el.querySelector('#b-capture').addEventListener('click', () => captureAdverts(root))
  } else {
    el.innerHTML = `<button id="b-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass"></i>Scan</button>`
    el.querySelector('#b-scan').addEventListener('click', () => scanClassic(root))
  }
}

async function scan(root) {
  const out = root.querySelector('#b-out')
  out.innerHTML = spinner('Scanning BLE devices...')
  const task = startTask('Scanning BLE')
  try {
    const d = await apiGet('/bluetooth/scan', { timeout: 30000 })
    const devs = d.devices || []
    task.done('BLE scan complete', `${devs.length} device(s)`)
    if (!devs.length) return (out.innerHTML = empty('No BLE devices found.'))
    out.innerHTML = `
      <div class="overflow-x-auto"><table class="table table-sm">
        <thead><tr><th>Device</th><th>MAC</th><th>RSSI</th><th></th></tr></thead>
        <tbody>${devs
          .map(
            (d) => `<tr>
              <td class="font-medium">${esc(d.name || 'Unknown')}</td>
              <td class="font-mono text-xs">${esc(d.mac || '-')}</td>
              <td class="text-xs">${esc(d.rssi ?? '-')} dBm</td>
              <td class="text-right"><button class="btn btn-ghost btn-xs gap-1" data-profile="${esc(d.mac)}"><i class="fa-solid fa-sitemap"></i>Profile</button></td>
            </tr>`,
          )
          .join('')}</tbody>
      </table></div>
      <div id="b-gatt" class="mt-4"></div>`
    out
      .querySelectorAll('[data-profile]')
      .forEach((b) => b.addEventListener('click', () => profile(root, b.dataset.profile)))
  } catch (e) {
    task.fail('BLE scan failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ------------------------------------------------------------------ GATT profiling

async function profile(root, mac) {
  const out = root.querySelector('#b-gatt')
  out.innerHTML = spinner('Connecting and reading GATT...')
  const task = startTask('GATT profile', mac)
  try {
    const d = await apiPost('/bluetooth/gatt', { mac })
    const services = d.services || []
    task.done('GATT profile complete', `${services.length} service(s)`)
    if (!services.length) return (out.innerHTML = empty('No services found (device may require pairing).', 'fa-sitemap'))
    out.innerHTML = gattView(mac, services)
    out.querySelectorAll('[data-write]').forEach((btn) =>
      btn.addEventListener('click', () => gattWrite(mac, btn)),
    )
  } catch (e) {
    task.fail('GATT profile failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

function gattView(mac, services) {
  const body = services
    .map((svc) => {
      const chars = (svc.characteristics || []).map(charRow).join('')
      return `
      <div class="rounded-xl bg-base-200/50 p-3 mb-2">
        <div class="flex items-center justify-between gap-2 mb-2">
          <span class="font-semibold text-sm">${esc(svc.name || 'Unknown service')}</span>
          <span class="font-mono text-[0.6rem] text-base-content/45">${esc(shortUuid(svc.uuid))}</span>
        </div>
        ${chars || '<p class="text-xs text-base-content/45">No characteristics.</p>'}
      </div>`
    })
    .join('')
  return `
    ${sectionTitle('GATT profile', `<span class="font-mono text-[0.65rem] text-base-content/50">${esc(mac)}</span>`)}
    ${body}`
}

function charRow(c) {
  const propList = c.properties || []
  const props = propList
    .map((p) => `<span class="badge badge-xs badge-ghost">${esc(p)}</span>`)
    .join(' ')
  const val = c.value_text
    ? `<div class="text-xs mt-1"><span class="text-base-content/45">value:</span> ${esc(c.value_text)}</div>`
    : c.value_hex
      ? `<div class="text-[0.65rem] font-mono mt-1 break-all text-base-content/55">${esc(c.value_hex)}</div>`
      : ''
  const desc =
    c.descriptors && c.descriptors.length
      ? `<div class="text-[0.6rem] text-base-content/40 mt-1">${c.descriptors.length} descriptor(s)</div>`
      : ''
  const canWrite = propList.includes('write') || propList.includes('write-without-response')
  const noResp = propList.includes('write-without-response') && !propList.includes('write')
  const writeRow = canWrite
    ? `<div class="flex items-center gap-1 mt-1.5" data-write-row>
        <select class="select select-xs select-bordered w-auto" data-fmt>
          <option value="hex" selected>hex</option>
          <option value="ascii">ascii</option>
        </select>
        <input class="input input-xs input-bordered flex-1 font-mono" placeholder="value to write" data-wval />
        <button class="btn btn-xs btn-ghost gap-1" data-write="${esc(c.uuid)}" data-wr="${noResp ? '1' : ''}"><i class="fa-solid fa-pen-to-square"></i>Write</button>
      </div>`
    : ''
  return `
    <div class="rounded-lg bg-base-100/60 px-3 py-2 mb-1">
      <div class="flex items-center justify-between gap-2">
        <span class="text-xs font-medium">${esc(c.name || 'Unknown characteristic')}</span>
        <span class="flex gap-1 flex-wrap justify-end">${props}</span>
      </div>
      <div class="font-mono text-[0.6rem] text-base-content/45">${esc(shortUuid(c.uuid))}</div>
      ${val}
      ${desc}
      ${writeRow}
    </div>`
}

// Collapse the 128-bit form of an adopted UUID down to its 16-bit short id.
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
  try {
    hex = fmt === 'ascii' ? asciiToHex(rawValue) : normalizeHex(rawValue)
  } catch (e) {
    return notify('Invalid value', 'error', e.message)
  }
  if (!hex) return notify('Enter a value to write', 'warning')

  const task = startTask('GATT write', shortUuid(charUuid))
  try {
    const d = await apiPost('/bluetooth/gatt/write', {
      mac,
      char_uuid: charUuid,
      value: hex,
      without_response: withoutResponse,
    })
    task.done('Write succeeded', `${d.bytes_written} byte(s)${d.with_response ? '' : ', no response'}`)
  } catch (e) {
    task.fail('Write failed', e.message)
  }
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

async function beacons(root) {
  const out = root.querySelector('#b-out')
  out.innerHTML = spinner('Scanning for beacons...')
  const task = startTask('Scanning beacons')
  try {
    const d = await apiGet('/bluetooth/beacons', { timeout: 30000 })
    const bs = d.beacons || []
    task.done('Beacon scan complete', `${bs.length} beacon(s)`)
    if (!bs.length) return (out.innerHTML = empty('No iBeacon / Eddystone beacons detected.'))
    out.innerHTML = `
      <div class="overflow-x-auto"><table class="table table-sm">
        <thead><tr><th>Type</th><th>UUID / ID</th><th>RSSI</th></tr></thead>
        <tbody>${bs
          .map(
            (b) => `<tr>
              <td>${esc(b.type || 'beacon')}</td>
              <td class="font-mono text-[0.65rem]">${esc(b.uuid || b.namespace || b.id || '-')}</td>
              <td class="text-xs">${esc(b.rssi ?? '-')} dBm</td>
            </tr>`,
          )
          .join('')}</tbody>
      </table></div>`
  } catch (e) {
    task.fail('Beacon scan failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ------------------------------------------------------------------ advertisement log

async function captureAdverts(root) {
  const dur = parseInt(root.querySelector('#b-cap-dur').value, 10) || 30
  const out = root.querySelector('#b-out')
  out.innerHTML = spinner(`Logging advertisements for ${dur}s...`)
  const task = startTask('BLE advert log', `${dur}s window`)
  try {
    const d = await apiPost('/bluetooth/capture', { duration: dur }, { timeout: (dur + 30) * 1000 })
    const devices = d.devices || []
    task.done('Advert log complete', `${d.count} sightings · ${devices.length} device(s)`)
    if (!devices.length) return (out.innerHTML = empty('No advertisements captured.', 'fa-clock-rotate-left'))
    out.innerHTML = advertLogView(d)
  } catch (e) {
    task.fail('Advert log failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

function advertLogView(d) {
  const rows = (d.devices || [])
    .map(
      (dev) => `<tr>
        <td class="font-medium">${esc(dev.name || 'Unknown')}${dev.beacon ? ` <span class="badge badge-xs badge-ghost">${esc(dev.beacon)}</span>` : ''}</td>
        <td class="font-mono text-xs">${esc(dev.mac)}</td>
        <td class="text-xs text-center">${dev.count}</td>
        <td class="text-xs">${rssiRange(dev)}</td>
        <td class="text-xs">${esc(timeOnly(dev.last_seen))}</td>
      </tr>`,
    )
    .join('')
  return `
    ${sectionTitle('Advertisement log', `<span class="text-[0.65rem] text-base-content/50">${d.count} sightings · ${d.duration}s</span>`)}
    <div class="overflow-x-auto"><table class="table table-sm">
      <thead><tr><th>Device</th><th>MAC</th><th>Seen</th><th>RSSI</th><th>Last</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`
}

function rssiRange(dev) {
  if (dev.rssi_last === null || dev.rssi_last === undefined) return '-'
  if (dev.rssi_min === dev.rssi_max) return `${dev.rssi_last} dBm`
  return `${dev.rssi_last} <span class="text-base-content/40">(${dev.rssi_min}..${dev.rssi_max})</span>`
}

function timeOnly(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString()
  } catch (e) {
    return ''
  }
}

// ------------------------------------------------------------------ raw HCI capture

async function captureHci(root, dur) {
  const out = root.querySelector('#b-out')
  out.innerHTML = spinner(`Capturing HCI for ${dur}s...`)
  const task = startTask('HCI capture', `${dur}s`)
  try {
    const d = await apiPost('/bluetooth/capture-hci', { duration: dur }, { timeout: (dur + 30) * 1000 })
    task.done('HCI capture complete', d.filename)
    const href = `/api/loot/download?category=hci&name=${encodeURIComponent(d.filename)}`
    out.innerHTML = `
      <div class="rounded-xl bg-base-200/50 p-4 text-sm">
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

// ------------------------------------------------------------------ Classic (BR/EDR) + SDP

async function scanClassic(root) {
  const out = root.querySelector('#b-out')
  out.innerHTML = spinner('Scanning Classic (BR/EDR) devices...')
  const task = startTask('Classic scan')
  try {
    const d = await apiGet('/bluetooth/classic-scan', { timeout: 40000 })
    const devs = d.devices || []
    task.done('Classic scan complete', `${devs.length} device(s)`)
    if (!devs.length) return (out.innerHTML = empty('No Classic devices found. Make sure targets are discoverable.', 'fa-bluetooth'))
    out.innerHTML = devs.map(classicRow).join('')
    out.querySelectorAll('[data-sdp]').forEach((b) => b.addEventListener('click', () => sdp(root, b.dataset.sdp)))
  } catch (e) {
    task.fail('Classic scan failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

function classicRow(d) {
  const detailId = 'sdp-' + d.mac.replace(/:/g, '')
  const meta = [d.mac, d.type || 'device'].join(' · ') + (d.rssi != null ? ` · ${d.rssi} dBm` : '')
  return `
  <div class="rounded-xl bg-base-200/50 p-3 mb-2">
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

async function sdp(root, mac) {
  const wrap = root.querySelector('#sdp-' + mac.replace(/:/g, ''))
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
  return `
    <div class="overflow-x-auto"><table class="table table-xs">
      <thead><tr><th>Service</th><th>Proto</th><th>Ch</th></tr></thead>
      <tbody>${services
        .map(
          (s) => `<tr>
            <td>${esc(s.name || (s.service_classes && s.service_classes[0]) || 'Unknown')}</td>
            <td class="text-xs">${esc(s.protocol || '-')}</td>
            <td class="text-xs">${esc(s.channel ?? '-')}</td>
          </tr>`,
        )
        .join('')}</tbody>
    </table></div>`
}
