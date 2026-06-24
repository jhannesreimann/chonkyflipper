// Zigbee via Zigbee2MQTT. Devices, lifecycle/state events, bridge info and
// pairing. The dashboard/events endpoints only exist on newer backends, so we
// fall back to the raw /zigbee/devices registry when they 404.
import { apiGet, apiPost, apiDelete } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner, tabBar } from '../ui.js'
import { esc, timeAgoShort } from '../util.js'
import { startTask, notify } from '../toast.js'

const TABS = [
  { id: 'devices', label: 'Devices', icon: 'fa-microchip' },
  { id: 'events', label: 'Events', icon: 'fa-list' },
  { id: 'bridge', label: 'Bridge', icon: 'fa-network-wired' },
]

let active = 'devices'

export default function renderZigbee(root) {
  root.innerHTML = `
    ${pageHead('fa-house-signal', 'Zigbee', 'SONOFF MG21 · Zigbee2MQTT')}
    ${tabBar(TABS, active)}
    <div id="zb-body"></div>
  `
  root.querySelectorAll('[data-tab]').forEach((el) =>
    el.addEventListener('click', () => {
      active = el.dataset.tab
      root.querySelectorAll('[data-tab]').forEach((t) => t.classList.toggle('tab-active', t.dataset.tab === active))
      paint(root)
    }),
  )
  paint(root)
}

function paint(root) {
  const body = root.querySelector('#zb-body')
  if (active === 'devices') devicesTab(body)
  else if (active === 'events') eventsTab(body)
  else bridgeTab(body)
}

// ---------------------------------------------------------------- Devices
function devicesTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Paired devices', `
      <button id="zb-refresh" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Refresh</button>
      <button id="zb-join" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-plus"></i>Permit join</button>
    `)}
    <div id="zb-join-status"></div>
    <div id="zb-devices" class="mt-2"></div>
  `)
  body.querySelector('#zb-refresh').addEventListener('click', () => loadDevices(body))
  body.querySelector('#zb-join').addEventListener('click', () => permitJoin(body))
  loadDevices(body)
}

async function loadDevices(body) {
  const wrap = body.querySelector('#zb-devices')
  wrap.innerHTML = spinner('Loading devices...')
  try {
    const d = await apiGet('/zigbee/dashboard', { timeout: 15000 })
    if (!d.success) throw new Error(d.error || 'Failed')
    const devices = (d.devices || []).filter((x) => x.type !== 'Coordinator')
    if (!devices.length) return (wrap.innerHTML = empty('No devices paired. Use Permit join to add one.', 'fa-microchip'))
    wrap.innerHTML = devices.map(deviceCard).join('')
    wrap.querySelectorAll('[data-toggle]').forEach((b) =>
      b.addEventListener('click', () => toggle(body, b.dataset.toggle, b.dataset.next)),
    )
    wrap.querySelectorAll('[data-rename]').forEach((b) =>
      b.addEventListener('click', () => rename(body, b.dataset.rename)),
    )
    wrap.querySelectorAll('[data-remove]').forEach((b) =>
      b.addEventListener('click', () => remove(body, b.dataset.remove)),
    )
  } catch (e) {
    wrap.innerHTML = errorBox(e.message)
  }
}

function deviceCard(d) {
  const name = d.friendly_name || '?'
  const meta = [d.vendor, d.model].filter(Boolean).join(' ') || d.type || 'device'
  const dot = d.available === true ? 'bg-success' : d.available === false ? 'bg-error' : 'bg-base-content/30'

  const badges = []
  if (d.battery != null) {
    const tone = d.battery >= 60 ? 'text-success' : d.battery >= 20 ? 'text-warning' : 'text-error'
    badges.push(`<span class="text-[0.65rem] ${tone}"><i class="fa-solid fa-battery-half mr-1"></i>${d.battery}%</span>`)
  }
  if (d.linkquality != null) {
    badges.push(`<span class="text-[0.65rem] text-base-content/50"><i class="fa-solid fa-signal mr-1"></i>LQI ${d.linkquality}</span>`)
  }

  const actions = []
  if (d.state === 'ON' || d.state === 'OFF') {
    const next = d.state === 'ON' ? 'OFF' : 'ON'
    actions.push(`<button class="btn btn-ghost btn-xs gap-1" data-toggle="${esc(name)}" data-next="${next}"><i class="fa-solid fa-power-off"></i>Turn ${next === 'ON' ? 'on' : 'off'}</button>`)
  }
  actions.push(`<button class="btn btn-ghost btn-xs gap-1" data-rename="${esc(name)}"><i class="fa-solid fa-pen"></i>Rename</button>`)
  actions.push(`<button class="btn btn-ghost btn-xs text-error gap-1" data-remove="${esc(name)}"><i class="fa-solid fa-trash"></i>Remove</button>`)

  return `
  <div class="rounded-xl bg-base-200/50 p-3 mb-2">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2 font-semibold text-sm">
          <span class="w-2 h-2 rounded-full ${dot}"></span>
          <span class="truncate">${esc(name)}</span>
        </div>
        <div class="text-[0.65rem] text-base-content/45 mt-0.5">${esc(meta)}</div>
      </div>
      <div class="flex flex-col items-end gap-0.5 shrink-0">${badges.join('')}</div>
    </div>
    <div class="flex flex-wrap gap-1 mt-2">${actions.join('')}</div>
  </div>`
}

async function permitJoin(body) {
  const status = body.querySelector('#zb-join-status')
  const task = startTask('Zigbee join', 'Opening network for 4 min')
  try {
    const d = await apiPost('/zigbee/permit_join', { enable: true, duration: 254 })
    if (!d.success) throw new Error(d.error || 'Failed')
    task.done('Join mode active', 'Put device into pairing mode')
    status.innerHTML = infoBox('Join mode active for 4 minutes. Put your device into pairing mode now.', 'fa-circle-check')
  } catch (e) {
    task.fail('Permit join failed', e.message)
    status.innerHTML = errorBox(e.message)
  }
}

async function toggle(body, name, next) {
  const task = startTask('Zigbee', `${name} -> ${next}`)
  try {
    const d = await apiPost(`/zigbee/device/${encodeURIComponent(name)}/set`, { state: next })
    if (!d.success) throw new Error(d.error || 'Failed')
    task.done('State changed', `${name}: ${next}`)
    loadDevices(body)
  } catch (e) {
    task.fail('Toggle failed', e.message)
  }
}

async function rename(body, name) {
  const to = prompt(`Rename "${name}" to:`, name)
  if (!to || to === name) return
  try {
    const d = await apiPost(`/zigbee/device/${encodeURIComponent(name)}/rename`, { to })
    if (!d.success) throw new Error(d.error || 'Failed')
    notify('Device renamed', 'success', `${name} -> ${to}`)
    loadDevices(body)
  } catch (e) {
    notify('Rename failed', 'error', e.message)
  }
}

async function remove(body, name) {
  if (!confirm(`Remove "${name}" from the Zigbee network?`)) return
  const task = startTask('Removing device', name)
  try {
    const d = await apiDelete(`/zigbee/device/${encodeURIComponent(name)}`)
    if (!d.success) throw new Error(d.error || 'Failed')
    task.done('Device removed', name)
    loadDevices(body)
  } catch (e) {
    task.fail('Remove failed', e.message)
  }
}

// ---------------------------------------------------------------- Events
function eventsTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Network events', `<button id="zb-ev-refresh" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Refresh</button>`)}
    <div id="zb-events"></div>
  `)
  body.querySelector('#zb-ev-refresh').addEventListener('click', () => loadEvents(body))
  loadEvents(body)
}

async function loadEvents(body) {
  const wrap = body.querySelector('#zb-events')
  wrap.innerHTML = spinner('Loading events...')
  try {
    const d = await apiGet('/zigbee/events?limit=50', { timeout: 15000 })
    const events = d.events || []
    if (!events.length) return (wrap.innerHTML = empty('No events recorded yet.', 'fa-list'))
    wrap.innerHTML = events.map(eventRow).join('')
  } catch (e) {
    wrap.innerHTML = errorBox(e.message)
  }
}

function eventRow(ev) {
  const lifecycle = ev.category === 'lifecycle'
  const border = lifecycle ? 'border-secondary' : 'border-base-content/20'
  const type = (ev.type || 'event').replace(/_/g, ' ').toUpperCase()
  const d = ev.detail || {}
  const parts = []
  if (ev.category === 'state') {
    ;['state', 'action', 'contact', 'occupancy', 'battery', 'linkquality', 'temperature', 'humidity'].forEach((k) => {
      if (d[k] !== undefined && d[k] !== null) parts.push(`${k}: ${d[k]}`)
    })
  } else {
    if (d.ieee_address) parts.push(d.ieee_address)
    if (d.status) parts.push(String(d.status))
  }
  return `
  <div class="rounded-lg bg-base-200/50 border-l-2 ${border} px-3 py-2 mb-1.5">
    <div class="flex items-center justify-between gap-2">
      <span class="text-xs font-semibold">${esc(type)}</span>
      <span class="text-[0.6rem] text-base-content/45">${timeAgoShort(ev.timestamp)}</span>
    </div>
    <div class="text-[0.68rem] text-base-content/55 mt-0.5">${esc([ev.device, parts.join(' · ')].filter(Boolean).join(' · '))}</div>
  </div>`
}

// ---------------------------------------------------------------- Bridge
function bridgeTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Bridge info', `<button id="zb-net" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-diagram-project"></i>Network map</button>`)}
    <div id="zb-bridge">${spinner('Loading bridge...')}</div>
    <div id="zb-map" class="mt-3"></div>
  `)
  body.querySelector('#zb-net').addEventListener('click', () => loadMap(body))
  loadBridge(body)
}

async function loadBridge(body) {
  const wrap = body.querySelector('#zb-bridge')
  try {
    const d = await apiGet('/zigbee/bridge', { timeout: 15000 })
    if (!d.success) throw new Error(d.error || 'Failed')
    const cfg = d.info?.config?.advanced || {}
    const ver = d.info?.version || d.info?.commit || '?'
    const channel = cfg.channel ?? d.info?.network?.channel ?? '?'
    const panId = d.info?.network?.pan_id ?? cfg.pan_id ?? '?'
    const state = d.state?.state || d.state || 'unknown'
    wrap.innerHTML = `
      <dl class="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-sm">
        <dt class="text-base-content/50">State</dt><dd class="font-semibold ${state === 'online' ? 'text-success' : ''}">${esc(state)}</dd>
        <dt class="text-base-content/50">Version</dt><dd>${esc(ver)}</dd>
        <dt class="text-base-content/50">Channel</dt><dd>${esc(channel)}</dd>
        <dt class="text-base-content/50">PAN ID</dt><dd class="font-mono text-xs">${esc(panId)}</dd>
        <dt class="text-base-content/50">Permit join</dt><dd>${d.info?.permit_join ? 'Open' : 'Closed'}</dd>
      </dl>`
  } catch (e) {
    wrap.innerHTML = errorBox(e.message)
  }
}

async function loadMap(body) {
  const wrap = body.querySelector('#zb-map')
  wrap.innerHTML = spinner('Building network map (up to 15s)...')
  const task = startTask('Zigbee network map')
  try {
    const d = await apiGet('/zigbee/networkmap', { timeout: 20000 })
    if (!d.success) throw new Error(d.error || 'Failed')
    const nodes = d.map?.nodes || []
    const links = d.map?.links || []
    task.done('Network map ready', `${nodes.length} nodes`)
    wrap.innerHTML = infoBox(`Map built: <strong>${nodes.length}</strong> nodes, <strong>${links.length}</strong> links.`, 'fa-diagram-project')
  } catch (e) {
    task.fail('Network map failed', e.message)
    wrap.innerHTML = errorBox(e.message)
  }
}
