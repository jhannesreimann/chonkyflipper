// Bluetooth LE scanner + beacon detector + GATT profiler.
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, spinner } from '../ui.js'
import { esc } from '../util.js'
import { startTask } from '../toast.js'

export default function renderBluetooth(root) {
  root.innerHTML = `
    ${pageHead('fa-bluetooth-b', 'Bluetooth', 'Built-in BLE 5.0 · hci0')}
    ${card(`
      ${sectionTitle('Devices', `
        <button id="b-beacons" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-satellite-dish"></i>Beacons</button>
        <button id="b-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass"></i>Scan</button>
      `)}
      <div id="b-out">${empty('Scan to discover nearby BLE devices.', 'fa-bluetooth')}</div>
    `)}
  `
  root.querySelector('#b-scan').addEventListener('click', () => scan(root))
  root.querySelector('#b-beacons').addEventListener('click', () => beacons(root))
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
  const props = (c.properties || [])
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
  return `
    <div class="rounded-lg bg-base-100/60 px-3 py-2 mb-1">
      <div class="flex items-center justify-between gap-2">
        <span class="text-xs font-medium">${esc(c.name || 'Unknown characteristic')}</span>
        <span class="flex gap-1 flex-wrap justify-end">${props}</span>
      </div>
      <div class="font-mono text-[0.6rem] text-base-content/45">${esc(shortUuid(c.uuid))}</div>
      ${val}
      ${desc}
    </div>`
}

// Collapse the 128-bit form of an adopted UUID down to its 16-bit short id.
function shortUuid(uuid) {
  if (!uuid) return ''
  const m = /^0000([0-9a-f]{4})-0000-1000-8000-00805f9b34fb$/i.exec(uuid)
  return m ? '0x' + m[1].toUpperCase() : uuid
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
