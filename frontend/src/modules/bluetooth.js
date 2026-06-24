// Bluetooth LE scanner + beacon detector.
import { apiGet } from '../api.js'
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
        <thead><tr><th>Device</th><th>MAC</th><th>RSSI</th></tr></thead>
        <tbody>${devs
          .map(
            (d) => `<tr>
              <td class="font-medium">${esc(d.name || 'Unknown')}</td>
              <td class="font-mono text-xs">${esc(d.mac || '-')}</td>
              <td class="text-xs">${esc(d.rssi ?? '-')} dBm</td>
            </tr>`,
          )
          .join('')}</tbody>
      </table></div>`
  } catch (e) {
    task.fail('BLE scan failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
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
