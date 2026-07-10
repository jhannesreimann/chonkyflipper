// Sub-1GHz (CC1101): sweep a band into a live RSSI spectrum, capture raw OOK
// bursts off GDO0, and replay / manage saved signals. Long actions surface as
// toast tasks; the spectrum graph is drawn as inline SVG (no chart library).
import { apiGet, apiPost, apiDelete } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner, tabBar } from '../ui.js'
import { esc } from '../util.js'
import { startTask, notify } from '../toast.js'

const TABS = [
  { id: 'spectrum', label: 'Spectrum', icon: 'fa-chart-column' },
  { id: 'capture', label: 'Capture', icon: 'fa-floppy-disk' },
  { id: 'signals', label: 'Signals', icon: 'fa-tower-broadcast' },
]

// Preset bands: [start, end] MHz for the sweep, plus a nominal centre.
const BANDS = [
  { v: '433', label: '433 MHz · ISM (garage, sockets)', start: 433.0, end: 434.5, step: 25 },
  { v: '315', label: '315 MHz · US remotes', start: 314.5, end: 316.0, step: 25 },
  { v: '868', label: '868 MHz · EU ISM', start: 868.0, end: 869.0, step: 25 },
]

const CAP_FREQS = [
  { v: '433.92', label: '433.92 MHz · garage / sockets' },
  { v: '868.35', label: '868.35 MHz · EU ISM' },
  { v: '315.00', label: '315.00 MHz · US remotes' },
]

let active = 'spectrum'
let live = false // spectrum auto-repeat flag

export default function renderSubghz(root) {
  live = false
  root.innerHTML = `
    ${pageHead('fa-satellite-dish', 'Sub-1GHz', 'CC1101 · 315 / 433 / 868 MHz')}
    ${tabBar(TABS, active)}
    <div id="sg-body"></div>
  `
  root.querySelectorAll('[data-tab]').forEach((el) =>
    el.addEventListener('click', () => {
      live = false
      active = el.dataset.tab
      root.querySelectorAll('[data-tab]').forEach((t) => t.classList.toggle('tab-active', t.dataset.tab === active))
      paint(root)
    }),
  )
  paint(root)
}

function paint(root) {
  const body = root.querySelector('#sg-body')
  if (active === 'spectrum') return spectrumTab(body)
  if (active === 'capture') return captureTab(body)
  return signalsTab(body)
}

// ---------------------------------------------------------------- Spectrum
function spectrumTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Frequency spectrum', `
      <label class="flex items-center gap-2 text-xs cursor-pointer">
        <input id="sg-live" type="checkbox" class="toggle toggle-primary toggle-sm" />Live
      </label>
      <button id="sg-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-wave-square"></i>Scan</button>
    `)}
    <div class="flex flex-wrap items-end gap-3 mb-4">
      <label class="form-control">
        <span class="label-text text-xs mb-1">Band</span>
        <select id="sg-band" class="select select-bordered select-sm">
          ${BANDS.map((b) => `<option value="${b.v}">${esc(b.label)}</option>`).join('')}
        </select>
      </label>
      <label class="form-control w-24">
        <span class="label-text text-xs mb-1">Start MHz</span>
        <input id="sg-start" type="number" step="0.01" class="input input-bordered input-sm" />
      </label>
      <label class="form-control w-24">
        <span class="label-text text-xs mb-1">End MHz</span>
        <input id="sg-end" type="number" step="0.01" class="input input-bordered input-sm" />
      </label>
      <label class="form-control w-24">
        <span class="label-text text-xs mb-1">Step kHz</span>
        <input id="sg-step" type="number" step="5" class="input input-bordered input-sm" />
      </label>
    </div>
    <div id="sg-graph">${empty('Run a scan to sweep the band and plot RSSI per frequency.', 'fa-chart-column')}</div>
    <div id="sg-peak" class="mt-3"></div>
  `)
  const band = body.querySelector('#sg-band')
  const applyBand = () => {
    const b = BANDS.find((x) => x.v === band.value) || BANDS[0]
    body.querySelector('#sg-start').value = b.start
    body.querySelector('#sg-end').value = b.end
    body.querySelector('#sg-step').value = b.step
  }
  applyBand()
  band.addEventListener('change', applyBand)
  body.querySelector('#sg-scan').addEventListener('click', () => runScan(body, false))
  body.querySelector('#sg-live').addEventListener('change', (e) => {
    live = e.target.checked
    if (live) runScan(body, true)
  })
}

async function runScan(body, loop) {
  const start = parseFloat(body.querySelector('#sg-start').value)
  const end = parseFloat(body.querySelector('#sg-end').value)
  const step = parseInt(body.querySelector('#sg-step').value) || 25
  if (!(end > start)) return notify('End must be above start', 'error')
  const graph = body.querySelector('#sg-graph')
  const btn = body.querySelector('#sg-scan')
  if (!loop) graph.innerHTML = spinner('Sweeping band...')
  if (btn) btn.disabled = true
  try {
    const d = await apiPost('/subghz/scan', { start_mhz: start, end_mhz: end, step_khz: step }, { timeout: 30000 })
    if (!d.success) throw new Error(d.error || 'Scan failed')
    const results = d.results || []
    graph.innerHTML = spectrumSvg(results)
    renderPeak(body, results)
  } catch (e) {
    live = false
    const t = body.querySelector('#sg-live')
    if (t) t.checked = false
    graph.innerHTML = errorBox(e.message)
  } finally {
    if (btn) btn.disabled = false
  }
  // Re-arm the live loop only if still on this tab and toggle is set.
  if (live && active === 'spectrum' && body.querySelector('#sg-graph')) {
    setTimeout(() => {
      if (live && body.querySelector('#sg-graph')) runScan(body, true)
    }, 400)
  }
}

// Inline SVG bar spectrum. currentColor drives fill so DaisyUI theme colours
// (text-warning / text-base-content) carry through via fill-current.
function spectrumSvg(results) {
  if (!results.length) return empty('No samples returned.', 'fa-chart-column')
  const W = 1000,
    H = 210,
    padL = 44,
    padB = 24,
    padT = 10,
    padR = 8
  const plotW = W - padL - padR
  const plotH = H - padT - padB
  const yMin = -110,
    yMax = -30
  const x0 = padL,
    yBase = padT + plotH
  const y = (dbm) => padT + plotH * (1 - (Math.max(yMin, Math.min(yMax, dbm)) - yMin) / (yMax - yMin))
  const n = results.length
  const bw = plotW / n
  const bars = results
    .map((r, i) => {
      const bx = x0 + i * bw
      const by = y(r.rssi_dbm)
      const cls = r.activity ? 'text-warning' : 'text-primary/40'
      return `<rect x="${(bx + bw * 0.12).toFixed(1)}" y="${by.toFixed(1)}" width="${(bw * 0.76).toFixed(1)}" height="${(yBase - by).toFixed(1)}" class="${cls} fill-current" rx="1"></rect>`
    })
    .join('')
  // RSSI gridlines
  const grid = [-90, -70, -50]
    .map(
      (g) =>
        `<line x1="${x0}" y1="${y(g).toFixed(1)}" x2="${W - padR}" y2="${y(g).toFixed(1)}" class="text-base-content/15 stroke-current" stroke-dasharray="3 3" stroke-width="1"></line>
         <text x="4" y="${(y(g) + 3).toFixed(1)}" class="text-base-content/45 fill-current" font-size="10">${g}</text>`,
    )
    .join('')
  // X axis frequency labels (start / mid / end)
  const f0 = results[0].frequency_mhz
  const f1 = results[n - 1].frequency_mhz
  const fm = ((f0 + f1) / 2).toFixed(2)
  const xlab = `
    <text x="${x0}" y="${H - 6}" class="text-base-content/55 fill-current" font-size="10">${f0} MHz</text>
    <text x="${(x0 + plotW / 2).toFixed(0)}" y="${H - 6}" text-anchor="middle" class="text-base-content/55 fill-current" font-size="10">${fm}</text>
    <text x="${W - padR}" y="${H - 6}" text-anchor="end" class="text-base-content/55 fill-current" font-size="10">${f1} MHz</text>`
  return `
  <div class="rounded-xl border border-base-300/60 bg-base-200/40 p-2">
    <svg viewBox="0 0 ${W} ${H}" class="w-full h-auto" preserveAspectRatio="none" role="img" aria-label="RSSI spectrum">
      ${grid}${bars}${xlab}
    </svg>
  </div>`
}

function renderPeak(body, results) {
  const el = body.querySelector('#sg-peak')
  if (!el) return
  const active = results.filter((r) => r.activity)
  if (!results.length) return (el.innerHTML = '')
  const peak = results.reduce((a, b) => (b.rssi_dbm > a.rssi_dbm ? b : a))
  el.innerHTML = `
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <span class="badge badge-sm badge-warning badge-outline gap-1"><i class="fa-solid fa-arrow-up"></i>Peak ${peak.frequency_mhz} MHz · ${peak.rssi_dbm.toFixed(0)} dBm</span>
      <span class="text-base-content/50">${active.length} active bin${active.length === 1 ? '' : 's'} above threshold</span>
    </div>`
}

// ---------------------------------------------------------------- Capture
function captureTab(body) {
  body.innerHTML = `
    ${card(`
      ${sectionTitle('Record OOK burst')}
      ${infoBox('Trigger the remote (garage, socket, gate) at the CC1101 antenna during the capture window. The raw pulse train is stored for exact replay.')}
      <div class="flex flex-wrap items-end gap-3 mt-3">
        <label class="form-control">
          <span class="label-text text-xs mb-1">Frequency</span>
          <select id="sg-cfreq" class="select select-bordered select-sm">
            ${CAP_FREQS.map((f) => `<option value="${f.v}">${esc(f.label)}</option>`).join('')}
          </select>
        </label>
        <label class="form-control w-28">
          <span class="label-text text-xs mb-1">Window</span>
          <select id="sg-cdur" class="select select-bordered select-sm">
            <option value="3">3 seconds</option>
            <option value="5" selected>5 seconds</option>
            <option value="10">10 seconds</option>
          </select>
        </label>
        <button id="sg-rec" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-circle text-error"></i>Record</button>
      </div>
      <div id="sg-cap-out" class="mt-4"></div>
    `)}
  `
  body.querySelector('#sg-rec').addEventListener('click', () => record(body))
}

async function record(body) {
  const freq = body.querySelector('#sg-cfreq').value
  const dur = parseInt(body.querySelector('#sg-cdur').value) || 5
  const out = body.querySelector('#sg-cap-out')
  const task = startTask('Recording Sub-1GHz', `${freq} MHz · ${dur}s`)
  out.innerHTML = spinner('Listening for a burst...')
  try {
    const d = await apiPost('/subghz/record', { frequency: parseFloat(freq), duration: dur }, { timeout: (dur + 12) * 1000 })
    if (!d.success) throw new Error(d.error || 'Record failed')
    if (d.clean) {
      task.done('Burst captured', `${d.pulses} pulses`)
      out.innerHTML = infoBox(`Captured <b>${esc(d.name)}</b> with ${d.pulses} pulses. Replay it from the Signals tab.`, 'fa-circle-check')
    } else {
      task.done('Saved (noisy)', `${d.edges} edges`)
      out.innerHTML = errorBox(d.note || 'No structured burst detected -- only noise was captured. Try again closer to the transmitter.')
    }
  } catch (e) {
    task.fail('Record failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- Signals
function signalsTab(body) {
  body.innerHTML = `
    ${card(`
      ${sectionTitle('Saved signals', `<button id="sg-refresh" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Refresh</button>`)}
      <div id="sg-list"></div>
    `)}
    <div id="sg-detail" class="mt-4"></div>
  `
  body.querySelector('#sg-refresh').addEventListener('click', () => loadSignals(body))
  loadSignals(body)
}

async function loadSignals(body) {
  const list = body.querySelector('#sg-list')
  list.innerHTML = spinner('Loading signals...')
  try {
    const d = await apiGet('/subghz/signals')
    const sigs = d.signals || []
    if (!sigs.length) return (list.innerHTML = empty('No signals captured yet. Record one from the Capture tab.', 'fa-wave-square'))
    list.innerHTML = `
      <div class="overflow-x-auto"><table class="table table-sm">
        <thead><tr><th>Signal</th><th>Freq</th><th>Pulses</th><th></th></tr></thead>
        <tbody>${sigs.map(sigRow).join('')}</tbody>
      </table></div>`
    list.querySelectorAll('[data-view]').forEach((b) =>
      b.addEventListener('click', () => viewSignal(body, b.dataset.view)),
    )
    list.querySelectorAll('[data-replay]').forEach((b) =>
      b.addEventListener('click', () => replay(b.dataset.replay)),
    )
    list.querySelectorAll('[data-del]').forEach((b) =>
      b.addEventListener('click', () => deleteSignal(body, b.dataset.del)),
    )
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

function sigRow(s) {
  const badge = s.clean
    ? '<span class="badge badge-xs badge-success badge-outline">clean</span>'
    : '<span class="badge badge-xs badge-ghost">noisy</span>'
  return `
  <tr>
    <td class="font-medium">${esc(s.name)} ${badge}</td>
    <td class="text-xs">${esc(s.frequency_mhz ?? '?')} MHz</td>
    <td class="text-xs">${esc(s.pulses ?? 0)}</td>
    <td class="text-right whitespace-nowrap">
      <button class="btn btn-ghost btn-xs gap-1" data-view="${esc(s.name)}"><i class="fa-solid fa-chart-column"></i>Graph</button>
      <button class="btn btn-ghost btn-xs gap-1" data-replay="${esc(s.name)}"><i class="fa-solid fa-paper-plane"></i>Replay</button>
      <button class="btn btn-ghost btn-xs text-error gap-1" data-del="${esc(s.name)}" title="Delete signal"><i class="fa-solid fa-trash"></i></button>
    </td>
  </tr>`
}

async function viewSignal(body, name) {
  const detail = body.querySelector('#sg-detail')
  detail.innerHTML = spinner('Loading waveform...')
  detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  try {
    const d = await apiGet(`/subghz/signals/${encodeURIComponent(name)}`)
    if (!d.success) throw new Error(d.error || 'Load failed')
    const pulses = d.pulses || []
    const totalUs = pulses.reduce((s, p) => s + (p[1] || 0), 0)
    // A long silent gap (>= 2.5 ms) between carrier-on runs marks a repeat of
    // the frame -- fobs re-send the same code several times per press.
    const bursts = pulses.filter(([lv, dur]) => !lv && dur >= 2500).length + (pulses.length ? 1 : 0)
    const truncated = pulses.length >= 4096
    const meta = [
      `${d.frequency_mhz ?? '?'} MHz`,
      `${(totalUs / 1000).toFixed(1)} ms active`,
      `${bursts} burst${bursts === 1 ? '' : 's'}`,
      d.peak_rssi_dbm != null ? `peak ${d.peak_rssi_dbm} dBm` : null,
      d.clean ? 'clean' : 'noisy',
    ]
      .filter(Boolean)
      .join(' · ')
    detail.innerHTML = card(`
      ${sectionTitle(esc(name), `<button id="sg-detail-close" class="btn btn-ghost btn-sm btn-square" title="Close"><i class="fa-solid fa-xmark"></i></button>`)}
      <div class="text-xs text-base-content/55 mb-3">${esc(meta)}</div>
      ${waveformSvg(pulses)}
      ${infoBox(`Filled bars = carrier <b>on</b> (transmitting), gaps = silent. Only the active part of the capture window is shown. Multiple bar clusters are the same code re-sent as repeated frames.${truncated ? ' <b>Capture hit the 4096-pulse cap</b>, so a longer transmission may be cut off.' : ''}`)}
    `)
    detail.querySelector('#sg-detail-close').addEventListener('click', () => (detail.innerHTML = ''))
  } catch (e) {
    detail.innerHTML = errorBox(e.message)
  }
}

// Time-domain OOK burst map: each carrier-on pulse is a filled bar placed at
// its time offset, so repeated frames read as clusters of bars with gaps.
function waveformSvg(pulses) {
  if (!pulses.length) return empty('No pulse data stored for this signal.', 'fa-wave-square')
  const total = pulses.reduce((s, p) => s + (p[1] || 0), 0) || 1
  const W = 1000,
    H = 130,
    padL = 8,
    padR = 8,
    padT = 12,
    padB = 22
  const plotW = W - padL - padR
  const top = padT + 2
  const bot = H - padB
  const bars = []
  let t = 0
  for (const [lv, d] of pulses) {
    const x0 = padL + plotW * (t / total)
    t += d || 0
    if (lv) {
      const w = Math.max(0.5, padL + plotW * (t / total) - x0)
      bars.push(`<rect x="${x0.toFixed(1)}" y="${top}" width="${w.toFixed(2)}" height="${(bot - top).toFixed(1)}" class="text-primary fill-current"></rect>`)
    }
  }
  const ms = (total / 1000).toFixed(total < 10000 ? 2 : 1)
  return `
  <div class="rounded-xl border border-base-300/60 bg-base-200/40 p-2">
    <svg viewBox="0 0 ${W} ${H}" class="w-full h-auto" preserveAspectRatio="none" role="img" aria-label="OOK burst map">
      <line x1="${padL}" y1="${bot}" x2="${W - padR}" y2="${bot}" class="text-base-content/20 stroke-current" stroke-width="1"></line>
      ${bars.join('')}
      <text x="${padL}" y="${H - 6}" class="text-base-content/55 fill-current" font-size="10">0 ms</text>
      <text x="${W - padR}" y="${H - 6}" text-anchor="end" class="text-base-content/55 fill-current" font-size="10">${ms} ms</text>
    </svg>
  </div>`
}

async function replay(name) {
  const task = startTask('Replaying signal', name)
  try {
    const d = await apiPost('/subghz/transmit', { signal_id: name, repeat: 3 }, { timeout: 20000 })
    if (!d.success) throw new Error(d.error || 'Transmit failed')
    task.done('Signal replayed', `${d.pulses} pulses · ${d.repeats}x`)
  } catch (e) {
    task.fail('Replay failed', e.message)
  }
}

async function deleteSignal(body, name) {
  if (!confirm(`Delete signal "${name}"? This removes it from the device.`)) return
  try {
    const d = await apiDelete(`/subghz/signals/${encodeURIComponent(name)}`)
    if (!d.success) throw new Error(d.error || 'Delete failed')
    notify('Signal deleted', 'success', name)
    loadSignals(body)
  } catch (e) {
    notify('Delete failed', 'error', e.message)
  }
}
