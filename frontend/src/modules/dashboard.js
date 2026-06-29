// Overview: at-a-glance system health, hardware module availability and
// network state. Reads everything from the shared polling store.
import { subscribe } from '../state.js'
import { pageHead, card, sectionTitle } from '../ui.js'
import { esc, faClass } from '../util.js'

const MODULES = [
  { key: 'wifi', label: 'Wi-Fi', icon: 'fa-wifi', route: 'wifi' },
  { key: 'bluetooth', label: 'Bluetooth', icon: 'fa-bluetooth-b', route: 'bluetooth' },
  { key: 'cc1101', label: 'Sub-1GHz', icon: 'fa-satellite-dish', route: 'subghz' },
  { key: 'zigbee', label: 'Zigbee', icon: 'fa-house-signal', route: 'zigbee' },
  { key: 'zigbee-audit', label: 'Zigbee Sniffer', icon: 'fa-search', route: 'zigbee-sniffer' },
  { key: 'ir', label: 'Infrared', icon: 'fa-tower-broadcast', route: 'ir' },
  { key: 'pn532', label: 'NFC / RFID', icon: 'fa-id-card', route: 'nfc' },
]

function tile(icon, label, valueId) {
  return `
  <div class="stat-tile">
    <div class="flex items-center gap-2 text-base-content/50 text-xs font-medium">
      <i class="fa-solid ${icon}"></i><span>${esc(label)}</span>
    </div>
    <div id="${valueId}" class="text-lg font-bold tracking-tight truncate">-</div>
  </div>`
}

export default function renderDashboard(root) {
  root.innerHTML = `
    ${pageHead('fa-gauge-high', 'Overview', 'Live status of the rig')}

    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
      ${tile('fa-microchip', 'Host', 'd-host')}
      ${tile('fa-clock', 'Uptime', 'd-uptime')}
      ${tile('fa-temperature-half', 'Temperature', 'd-temp')}
      ${tile('fa-battery-three-quarters', 'Battery', 'd-batt')}
    </div>

    ${card(`
      ${sectionTitle('Hardware modules')}
      <div id="d-modules" class="grid grid-cols-2 sm:grid-cols-3 gap-3"></div>
    `, { className: 'mb-4' })}

    ${card(`
      ${sectionTitle('Network')}
      <div id="d-network" class="grid sm:grid-cols-2 gap-3"></div>
    `)}
  `

  const update = (s) => {
    if (!document.body.contains(root)) return unsub()

    const st = s.status || {}
    setText('d-host', st.hostname || 'chonkyflipper')
    setText('d-uptime', s.system?.uptime ? s.system.uptime.replace('up ', '') : '-')
    setText('d-temp', s.system?.temperature || '-')

    const pct = st.power?.battery_percentage
    const battEl = document.getElementById('d-batt')
    if (battEl) {
      if (pct !== null && pct !== undefined) {
        const tone = pct >= 60 ? 'text-success' : pct >= 20 ? 'text-warning' : 'text-error'
        battEl.className = `text-lg font-bold tracking-tight ${tone}`
        battEl.innerHTML = `${pct}%${st.power.is_charging ? ' <i class="fa-solid fa-bolt text-warning text-sm"></i>' : ''}`
      } else {
        battEl.textContent = 'UPS active'
      }
    }

    renderModules(st.modules || {})
    renderNetwork(s.network)
  }

  const unsub = subscribe(update)
}

function renderModules(modules) {
  const wrap = document.getElementById('d-modules')
  if (!wrap) return
  wrap.innerHTML = MODULES.map((m) => {
    const avail = modules[m.key]?.available
    return `
    <a href="#/${m.route}" class="rounded-xl border border-base-300/70 p-3 flex items-center gap-3
        hover:border-primary/50 hover:bg-base-200/60 transition-colors">
      <span class="grid place-items-center w-9 h-9 rounded-lg ${avail ? 'bg-primary/15 text-primary' : 'bg-base-300/60 text-base-content/40'}">
        <i class="${faClass(m.icon)}"></i>
      </span>
      <span class="min-w-0">
        <span class="block text-sm font-semibold truncate">${esc(m.label)}</span>
        <span class="block text-[0.65rem] ${avail ? 'text-success' : 'text-base-content/40'}">
          <i class="fa-solid ${avail ? 'fa-circle-check' : 'fa-circle-xmark'} mr-1"></i>${avail ? 'Ready' : 'Offline'}
        </span>
      </span>
    </a>`
  }).join('')
}

function renderNetwork(net) {
  const wrap = document.getElementById('d-network')
  if (!wrap) return
  if (!net) {
    wrap.innerHTML = `<p class="text-sm text-base-content/45">Loading network status...</p>`
    return
  }
  const row = (icon, label, value, tone) => `
    <div class="flex items-center gap-3 rounded-xl bg-base-200/50 px-3 py-2.5">
      <i class="fa-solid ${icon} text-base-content/45 w-5 text-center"></i>
      <span class="text-sm font-medium flex-1">${esc(label)}</span>
      <span class="text-xs font-semibold ${tone}">${value}</span>
    </div>`

  const eth = net.ethernet || {}
  const wc = net.wifi_client || {}
  const items = []
  items.push(
    row('fa-network-wired', 'LAN', eth.connected ? esc(eth.ip || 'connected') : 'Down',
      eth.connected ? 'text-success' : 'text-base-content/40'),
  )
  items.push(
    row('fa-tower-cell', 'Access Point', net.ap_mode ? esc(net.ap_ssid || 'up') : 'Down',
      net.ap_mode ? 'text-success' : 'text-base-content/40'),
  )
  if (wc.adapter_present) {
    items.push(
      row('fa-wifi', 'Wi-Fi client', wc.connected ? esc(wc.ssid || 'connected') : 'Not connected',
        wc.connected ? 'text-success' : 'text-warning'),
    )
  }
  const src = net.internet_source
  const srcLabel = net.internet_available
    ? (src === 'ethernet' ? 'via LAN' : src === 'wifi' ? 'via Wi-Fi' : 'online')
    : 'Offline'
  items.push(
    row('fa-globe', 'Internet', srcLabel, net.internet_available ? 'text-success' : 'text-error'),
  )
  wrap.innerHTML = items.join('')
}

function setText(id, text) {
  const el = document.getElementById(id)
  if (el) el.textContent = text
}
