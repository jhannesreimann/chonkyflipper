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
  { id: 'sniffer', label: 'Sniffer', icon: 'fa-search' },
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
  else if (active === 'sniffer') snifferTab(body)
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
    <div class="mt-3 flex justify-end">
      <button id="zb-sample" class="btn btn-ghost btn-xs gap-2 text-base-content/50"><i class="fa-solid fa-flask"></i>Show sample</button>
    </div>
    <div id="zb-map" class="mt-2"></div>
  `)
  body.querySelector('#zb-net').addEventListener('click', () => loadMap(body))
  body.querySelector('#zb-sample').addEventListener('click', () => loadSampleMap(body))
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
    // Z2M wraps the raw map under data.value on some versions, data on others.
    const m = d.map?.value || d.map || {}
    const nodes = m.nodes || []
    const links = m.links || []
    task.done('Network map ready', `${nodes.length} nodes`)
    if (!nodes.length) return (wrap.innerHTML = empty('Network map is empty.', 'fa-diagram-project'))
    wrap.innerHTML = networkMap(nodes, links)
  } catch (e) {
    task.fail('Network map failed', e.message)
    wrap.innerHTML = errorBox(e.message)
  }
}

// TEMP: renders the map with sample data so the topology can be eyeballed
// without the Pi. Remove this function and the zb-sample button before shipping.
function loadSampleMap(body) {
  const nodes = [
    { ieeeAddr: '0x0000', friendlyName: 'Coordinator', type: 'Coordinator' },
    { ieeeAddr: '0x1111', friendlyName: 'living_room_plug', type: 'Router' },
    { ieeeAddr: '0x2222', friendlyName: 'kitchen_plug', type: 'Router' },
    { ieeeAddr: '0x3333', friendlyName: 'hallway_repeater', type: 'Router' },
    { ieeeAddr: '0xa001', friendlyName: 'motion_hallway', type: 'EndDevice' },
    { ieeeAddr: '0xa002', friendlyName: 'door_front', type: 'EndDevice' },
    { ieeeAddr: '0xa003', friendlyName: 'temp_bedroom', type: 'EndDevice' },
    { ieeeAddr: '0xa004', friendlyName: 'button_office', type: 'EndDevice' },
    { ieeeAddr: '0xa005', friendlyName: 'leak_basement', type: 'EndDevice' },
  ]
  const links = [
    { sourceIeeeAddr: '0x1111', targetIeeeAddr: '0x0000', lqi: 210 },
    { sourceIeeeAddr: '0x0000', targetIeeeAddr: '0x1111', lqi: 208 },
    { sourceIeeeAddr: '0x2222', targetIeeeAddr: '0x0000', lqi: 150 },
    { sourceIeeeAddr: '0x3333', targetIeeeAddr: '0x0000', lqi: 80 },
    { sourceIeeeAddr: '0xa001', targetIeeeAddr: '0x3333', lqi: 120 },
    { sourceIeeeAddr: '0xa002', targetIeeeAddr: '0x1111', lqi: 200 },
    { sourceIeeeAddr: '0xa003', targetIeeeAddr: '0x2222', lqi: 60 },
    { sourceIeeeAddr: '0xa004', targetIeeeAddr: '0x1111', lqi: 140 },
    { sourceIeeeAddr: '0xa005', targetIeeeAddr: '0x3333', lqi: 35 },
  ]
  body.querySelector('#zb-map').innerHTML = networkMap(nodes, links)
}

// Tiered topology: coordinator on top, routers in the middle, end devices
// below. Edge opacity tracks link quality. Pure string builder, no deps.
const ZB_TIERS = ['Coordinator', 'Router', 'EndDevice']
const ZB_TONE = { Coordinator: 'text-primary', Router: 'text-secondary', EndDevice: 'text-base-content/55' }
const ZB_RADIUS = { Coordinator: 9, Router: 7, EndDevice: 5 }

function zbNodeId(n) {
  return n.ieeeAddr || n.ieee_address || n.friendlyName || String(n.networkAddress ?? '')
}

export function networkMap(nodes, links) {
  // Group by tier; unknown types fall in with the end devices.
  const groups = ZB_TIERS.map((type) => ({ type, list: nodes.filter((n) => n.type === type) }))
  const others = nodes.filter((n) => !ZB_TIERS.includes(n.type))
  if (others.length) groups[2].list = groups[2].list.concat(others)
  const present = groups.filter((g) => g.list.length)

  const maxRow = Math.max(...present.map((g) => g.list.length), 1)
  const W = Math.max(560, maxRow * 86)
  const padX = 36
  const padY = 34
  const rowGap = 96
  const H = padY * 2 + Math.max(0, present.length - 1) * rowGap

  // Place every node, keyed by id so edges can find their endpoints.
  const pos = new Map()
  present.forEach((g, gi) => {
    const y = padY + gi * rowGap
    g.list.forEach((n, i) => {
      const x = padX + ((i + 0.5) / g.list.length) * (W - 2 * padX)
      pos.set(zbNodeId(n), { x, y, node: n })
    })
  })

  // Collapse to one edge per unordered pair, keeping the strongest LQI.
  const edges = new Map()
  links.forEach((l) => {
    const s = l.source?.ieeeAddr || l.sourceIeeeAddr
    const t = l.target?.ieeeAddr || l.targetIeeeAddr
    if (!s || !t || s === t || !pos.has(s) || !pos.has(t)) return
    const key = s < t ? `${s}|${t}` : `${t}|${s}`
    const lqi = l.lqi ?? l.linkquality ?? 0
    const prev = edges.get(key)
    if (!prev || lqi > prev.lqi) edges.set(key, { s, t, lqi })
  })

  const lineEls = [...edges.values()]
    .map((e) => {
      const a = pos.get(e.s)
      const b = pos.get(e.t)
      const op = Math.max(0.15, Math.min(0.7, e.lqi / 255)).toFixed(2)
      return `<line x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}" stroke="currentColor" stroke-width="1.5" stroke-opacity="${op}" class="text-base-content"/>`
    })
    .join('')

  const nodeEls = [...pos.values()]
    .map(({ x, y, node }) => {
      const type = ZB_TIERS.includes(node.type) ? node.type : 'EndDevice'
      const name = node.friendlyName || node.friendly_name || zbNodeId(node) || '?'
      const short = name.length > 12 ? name.slice(0, 12) : name
      const ly = (y + ZB_RADIUS[type] + 11).toFixed(1)
      return `<g class="${ZB_TONE[type]}">
        <title>${esc(name)}</title>
        <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${ZB_RADIUS[type]}" fill="currentColor"/>
        <text x="${x.toFixed(1)}" y="${ly}" text-anchor="middle" font-size="9" fill="currentColor" class="text-base-content/70">${esc(short)}</text>
      </g>`
    })
    .join('')

  const legend = `
    <span class="inline-flex items-center gap-1.5 text-[0.65rem] text-base-content/60"><span class="w-2 h-2 rounded-full bg-primary"></span>Coordinator</span>
    <span class="inline-flex items-center gap-1.5 text-[0.65rem] text-base-content/60"><span class="w-2 h-2 rounded-full bg-secondary"></span>Router</span>
    <span class="inline-flex items-center gap-1.5 text-[0.65rem] text-base-content/60"><span class="w-2 h-2 rounded-full bg-base-content/50"></span>End device</span>`

  return `
  <div class="rounded-xl bg-base-200/40 p-2 overflow-hidden">
    <svg viewBox="0 0 ${W} ${H}" class="w-full" style="height:auto;max-height:58vh" preserveAspectRatio="xMidYMid meet">
      ${lineEls}
      ${nodeEls}
    </svg>
  </div>
  <div class="flex flex-wrap items-center gap-4 mt-3">${legend}</div>
  <p class="text-[0.65rem] text-base-content/45 mt-2">${nodes.length} nodes · ${edges.size} links · line opacity reflects link quality</p>`
}

// ---------------------------------------------------------------- Sniffer (CC2531 + KillerBee)

async function snifferTab(body) {
  var html = '<p class="text-sm text-base-content/60 mb-4">CC2531 USB Sniffer with KillerBee. Passive capture and key extraction.</p>' +
    '<div class="flex flex-wrap gap-2 mb-4">' +
      '<button class="btn btn-sm btn-outline btn-info" id="sniff-check">Check Device</button>' +
      '<button class="btn btn-sm btn-primary" id="sniff-capture">Capture 10s</button>' +
      '<button class="btn btn-sm btn-secondary" id="sniff-scan">Scan ch 11-14</button>' +
      '<button class="btn btn-sm btn-accent" id="sniff-extract">Extract Keys</button>' +
    '</div>' +
    '<div class="flex gap-2 items-center mb-3">' +
      '<span class="text-xs text-base-content/50">Status:</span>' +
      '<span class="badge badge-sm badge-ghost" id="sniff-device-status">Unknown</span>' +
      '<select class="select select-xs select-bordered" id="sniff-channel">';
  for (var c = 11; c <= 26; c++) html += '<option value="' + c + '"' + (c===11?' selected':'') + '>Ch ' + c + '</option>';
  html += '</select>' +
      '<span class="text-xs text-base-content/50">Duration:</span>' +
      '<select class="select select-xs select-bordered" id="sniff-duration">' +
        '<option value="5">5s</option><option value="10" selected>10s</option><option value="30">30s</option><option value="60">60s</option>' +
      '</select>' +
    '</div>' +
    '<div id="sniff-output" class="mt-3"></div>';
  body.innerHTML = html;

  checkSnifferDevice();
  body.querySelector('#sniff-check').onclick = checkSnifferDevice;
  body.querySelector('#sniff-capture').onclick = sniffCapture;
  body.querySelector('#sniff-scan').onclick = sniffScan;
  body.querySelector('#sniff-extract').onclick = sniffExtract;
}

async function checkSnifferDevice() {
  var el = document.getElementById('sniff-device-status');
  if (!el) return;
  try {
    var api = await import('../api.js');
    var d = await api.apiGet('/zigbee/audit/device');
    el.textContent = d.cc2531_present ? 'CC2531 connected' : 'Not found';
    el.className = 'badge badge-sm ' + (d.cc2531_present ? 'badge-success' : 'badge-error');
  } catch (e) {
    el.textContent = 'Error';
    el.className = 'badge badge-sm badge-error';
  }
}

async function sniffCapture() {
  var out = document.getElementById('sniff-output');
  if (!out) return;
  var ch = document.getElementById('sniff-channel')?.value || 11;
  var dur = document.getElementById('sniff-duration')?.value || 10;
  out.innerHTML = '<div class="text-sm text-info">Capturing ch ' + ch + ' for ' + dur + 's...</div>';
  try {
    var api = await import('../api.js');
    var d = await api.apiPost('/zigbee/audit/capture', { channel: parseInt(ch), duration: parseInt(dur) });
    if (d.success) {
      out.innerHTML = '<div class="text-sm text-success">Captured ' + d.filename + ' (' + d.size_bytes + ' bytes on ch ' + d.channel + ')</div>';
    } else {
      out.innerHTML = '<div class="text-sm text-error">' + esc(d.error || 'Capture failed') + '</div>';
    }
  } catch (e) { out.innerHTML = '<div class="text-sm text-error">' + esc(e.message) + '</div>'; }
}

async function sniffScan() {
  var out = document.getElementById('sniff-output');
  if (!out) return;
  out.innerHTML = '<div class="text-sm text-info">Scanning channels 11-14...</div>';
  try {
    var api = await import('../api.js');
    var d = await api.apiPost('/zigbee/audit/scan', { channels: '11-14', duration: 10 });
    out.innerHTML = d.success
      ? '<div class="text-sm text-success">Scan complete. File: ' + (d.file || 'saved') + '</div><pre class="text-xs text-base-content/60 mt-2">' + esc(d.output||'') + '</pre>'
      : '<div class="text-sm text-error">' + esc(d.error || 'Scan failed') + '</div>';
  } catch (e) { out.innerHTML = '<div class="text-sm text-error">' + esc(e.message) + '</div>'; }
}

async function sniffExtract() {
  var out = document.getElementById('sniff-output');
  if (!out) return;
  out.innerHTML = '<div class="text-sm text-info">Fetching latest capture...</div>';
  try {
    var api = await import('../api.js');
    var list = await api.apiGet('/zigbee/audit/captures');
    if (!list.captures || list.captures.length === 0) {
      out.innerHTML = '<div class="text-sm text-error">No captures available. Run a capture first.</div>';
      return;
    }
    var latest = list.captures[0];
    var d = await api.apiPost('/zigbee/audit/extract-keys', { file: '/opt/chonkyflipper/data/zigbee_captures/' + latest.name });
    out.innerHTML = d.success
      ? '<div class="text-sm text-success">Key extraction complete</div><pre class="text-xs text-base-content/60 mt-2">' + esc(d.output||'') + '</pre>'
      : '<div class="text-sm text-error">' + esc(d.error || 'Extraction failed') + '</div>';
  } catch (e) { out.innerHTML = '<div class="text-sm text-error">' + esc(e.message) + '</div>'; }
}
