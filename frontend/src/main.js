import './style.css'

import { subscribe, startPolling, getState } from './state.js'
import { onTaskCountChange } from './toast.js'
import { esc, faClass } from './util.js'

import renderDashboard from './modules/dashboard.js'
import renderWifi from './modules/wifi.js'
import renderBluetooth from './modules/bluetooth.js'
import renderIr from './modules/ir.js'
import renderSubghz from './modules/subghz.js'
import renderNfc from './modules/nfc.js'
import renderZigbee from './modules/zigbee.js'
import renderBadusb from './modules/badusb.js'
import renderSettings from './modules/settings.js'

// Sidebar registry. statusKey maps to the module name in /api/status so the
// sidebar can show a live availability dot. Entries without a statusKey are
// always-on app sections.
const ROUTES = [
  { id: 'dashboard', label: 'Overview', icon: 'fa-gauge-high', render: renderDashboard, group: 'main' },
  { id: 'wifi', label: 'Wi-Fi', icon: 'fa-wifi', render: renderWifi, statusKey: 'wifi', group: 'radios' },
  { id: 'bluetooth', label: 'Bluetooth', icon: 'fa-bluetooth-b', render: renderBluetooth, statusKey: 'bluetooth', group: 'radios' },
  { id: 'subghz', label: 'Sub-1GHz', icon: 'fa-satellite-dish', render: renderSubghz, statusKey: 'cc1101', group: 'radios' },
  { id: 'zigbee', label: 'Zigbee', icon: 'fa-house-signal', render: renderZigbee, statusKey: 'zigbee', group: 'radios' },
  { id: 'ir', label: 'Infrared', icon: 'fa-tower-broadcast', render: renderIr, statusKey: 'ir', group: 'devices' },
  { id: 'nfc', label: 'NFC / RFID', icon: 'fa-id-card', render: renderNfc, statusKey: 'pn532', group: 'devices' },
  { id: 'badusb', label: 'BadUSB', icon: 'fa-keyboard', render: renderBadusb, group: 'devices' },
  { id: 'settings', label: 'Settings', icon: 'fa-sliders', render: renderSettings, group: 'system' },
]

const GROUPS = [
  { id: 'main', label: '' },
  { id: 'radios', label: 'Radios' },
  { id: 'devices', label: 'Devices' },
  { id: 'system', label: 'System' },
]

let currentId = null

function shell() {
  return `
  <div class="drawer lg:drawer-open">
    <input id="nav-drawer" type="checkbox" class="drawer-toggle" />

    <div class="drawer-content flex flex-col min-h-screen">
      ${header()}
      <main id="view" class="flex-1 px-4 sm:px-6 py-5 max-w-6xl w-full mx-auto"></main>
    </div>

    <div class="drawer-side z-40">
      <label for="nav-drawer" aria-label="close sidebar" class="drawer-overlay"></label>
      ${sidebar()}
    </div>
  </div>`
}

function header() {
  return `
  <header class="sticky top-0 z-30 bg-base-100/85 backdrop-blur border-b border-base-300/70">
    <div class="flex items-center gap-3 px-4 sm:px-6 h-16">
      <label for="nav-drawer" class="btn btn-ghost btn-sm btn-square lg:hidden" aria-label="Open menu">
        <i class="fa-solid fa-bars text-lg"></i>
      </label>

      <div class="flex items-center gap-3 min-w-0">
        <img src="/assets/logo1.png" alt="ChonkyFlipper" class="h-14 w-14 object-contain shrink-0" />
        <div class="leading-tight min-w-0">
          <div class="font-extrabold tracking-tight truncate">ChonkyFlipper</div>
          <div id="hdr-subtitle" class="text-[0.65rem] text-base-content/50 truncate">IoT auditing rig</div>
        </div>
      </div>

      <div class="flex-1"></div>

      <div id="hdr-tasks" class="hidden items-center gap-2 mr-1 text-xs font-medium text-primary motion-preset-fade">
        <i class="fa-solid fa-spinner fa-spin"></i>
        <span id="hdr-tasks-count">0</span>
      </div>

      <div id="hdr-status" class="flex items-center gap-2 text-xs font-medium px-2.5 py-1.5 rounded-full bg-base-200">
        <span id="hdr-dot" class="w-2 h-2 rounded-full bg-base-content/30"></span>
        <span id="hdr-status-text" class="hidden sm:inline">Connecting</span>
      </div>

      <button id="theme-btn" class="btn btn-ghost btn-sm btn-square" aria-label="Toggle theme" title="Toggle light / dark">
        <i class="fa-solid fa-moon"></i>
      </button>
    </div>
  </header>`
}

function sidebar() {
  const links = GROUPS.map((g) => {
    const items = ROUTES.filter((r) => r.group === g.id)
    if (!items.length) return ''
    const heading = g.label
      ? `<div class="eyebrow px-3 pt-4 pb-1">${esc(g.label)}</div>`
      : ''
    return (
      heading +
      items
        .map(
          (r) => `
        <a class="nav-link" data-route="${r.id}" href="#/${r.id}">
          <i class="${faClass(r.icon)} nav-ico"></i>
          <span class="flex-1">${esc(r.label)}</span>
          ${r.statusKey ? `<span class="nav-dot w-1.5 h-1.5 rounded-full bg-base-content/20" data-status="${r.statusKey}"></span>` : ''}
        </a>`,
        )
        .join('')
    )
  }).join('')

  return `
  <aside class="w-72 min-h-full bg-base-100 border-r border-base-300/70 flex flex-col">
    <div class="px-5 pt-5 pb-3 flex items-center gap-3 border-b border-base-300/60">
      <img src="/assets/logo1.png" alt="" class="h-11 w-11 object-contain" />
      <div class="leading-tight">
        <div class="font-bold text-sm">Control Center</div>
        <div class="text-[0.65rem] text-base-content/50">Chonky_Control</div>
      </div>
    </div>

    <nav class="flex-1 overflow-y-auto px-3 pb-4">${links}</nav>

    <div class="px-4 py-3 border-t border-base-300/60 text-[0.65rem] text-base-content/45 flex items-center justify-between">
      <span id="side-version">main @ ...</span>
      <span id="side-batt"></span>
    </div>
  </aside>`
}

function navigate() {
  const id = (location.hash.replace(/^#\/?/, '') || 'dashboard').split('/')[0]
  const route = ROUTES.find((r) => r.id === id) || ROUTES[0]
  if (route.id === currentId) return
  currentId = route.id

  document.querySelectorAll('.nav-link').forEach((el) => {
    el.classList.toggle('active', el.dataset.route === route.id)
  })
  document.getElementById('hdr-subtitle').textContent = route.label

  const view = document.getElementById('view')
  view.innerHTML = ''
  view.scrollTop = 0
  const section = document.createElement('div')
  section.className = 'motion-preset-fade motion-duration-300'
  view.appendChild(section)
  route.render(section)

  // Close the mobile drawer after navigating.
  const drawer = document.getElementById('nav-drawer')
  if (drawer) drawer.checked = false
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
  try {
    localStorage.setItem('chonky-theme', theme)
  } catch (e) {}
  const icon = document.querySelector('#theme-btn i')
  if (icon) icon.className = theme === 'chonky-dark' ? 'fa-solid fa-moon' : 'fa-solid fa-sun'
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', theme === 'chonky-dark' ? '#16140f' : '#ffffff')
}

function wireHeader() {
  document.getElementById('theme-btn').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme')
    applyTheme(cur === 'chonky-dark' ? 'chonky' : 'chonky-dark')
  })

  onTaskCountChange((count) => {
    const wrap = document.getElementById('hdr-tasks')
    document.getElementById('hdr-tasks-count').textContent = count
    wrap.classList.toggle('hidden', count === 0)
    wrap.classList.toggle('flex', count > 0)
  })
}

function reflectState(s) {
  const dot = document.getElementById('hdr-dot')
  const text = document.getElementById('hdr-status-text')
  if (dot) {
    dot.className = `w-2 h-2 rounded-full ${s.online ? 'bg-success motion-preset-pulse' : 'bg-error'}`
  }
  if (text) text.textContent = s.online ? 'Online' : 'Offline'

  // Sidebar availability dots
  if (s.status && s.status.modules) {
    document.querySelectorAll('.nav-dot').forEach((el) => {
      const m = s.status.modules[el.dataset.status]
      el.className = `nav-dot w-1.5 h-1.5 rounded-full ${m && m.available ? 'bg-success' : 'bg-base-content/20'}`
      el.title = m && m.available ? 'ready' : 'offline'
    })
  }

  // Sidebar footer: version + battery
  const ver = document.getElementById('side-version')
  if (ver && s.version && s.version.sha && s.version.sha !== 'unknown') {
    ver.textContent = `main @ ${s.version.sha}`
  }
  const batt = document.getElementById('side-batt')
  if (batt && s.status && s.status.power) {
    const pct = s.status.power.battery_percentage
    if (pct !== null && pct !== undefined) {
      const charging = s.status.power.is_charging ? ' fa-bolt' : ''
      batt.innerHTML = `<i class="fa-solid fa-battery-half"></i> ${pct}%${charging ? '<i class="fa-solid fa-bolt ml-0.5"></i>' : ''}`
    }
  }
}

function boot() {
  const app = document.getElementById('app')
  app.innerHTML = shell()

  applyTheme(localStorage.getItem('chonky-theme') || 'chonky-dark')
  wireHeader()

  window.addEventListener('hashchange', navigate)
  navigate()

  subscribe(reflectState)
  startPolling()
}

boot()
