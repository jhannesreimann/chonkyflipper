// Wi-Fi: scan, monitor mode, wifite audit, probe capture, targeted attacks and
// packet capture. Long actions surface as toast tasks.
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner, tabBar, riskBadge } from '../ui.js'
import { esc, signalBars, fmtBytes } from '../util.js'
import { startTask, notify } from '../toast.js'

const TABS = [
  { id: 'scan', label: 'Scan', icon: 'fa-magnifying-glass' },
  { id: 'audit', label: 'Audit', icon: 'fa-shield-halved' },
  { id: 'probes', label: 'Probes', icon: 'fa-satellite' },
  { id: 'attack', label: 'Attack', icon: 'fa-burst' },
  { id: 'capture', label: 'Capture', icon: 'fa-floppy-disk' },
]

let active = 'scan'

export default function renderWifi(root) {
  root.innerHTML = `
    ${pageHead('fa-wifi', 'Wi-Fi', 'Alfa AWUS036ACS · wlan1')}
    ${tabBar(TABS, active)}
    <div id="wifi-body"></div>
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
  const body = root.querySelector('#wifi-body')
  if (active === 'scan') return scanTab(body)
  if (active === 'audit') return auditTab(body)
  if (active === 'probes') return probesTab(body)
  if (active === 'attack') return attackTab(body)
  if (active === 'capture') return captureTab(body)
}

// ---------------------------------------------------------------- Scan
function scanTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Nearby networks', `
      <button id="w-managed" class="btn btn-ghost btn-sm btn-square" title="Restore managed mode (fixes scanning after an attack)"><i class="fa-solid fa-rotate-left"></i></button>
      <button id="w-mon" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-tower-broadcast"></i>Monitor</button>
      <button id="w-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass"></i>Scan</button>
    `)}
    <div id="w-results">${empty('Run a scan to discover access points.', 'fa-wifi')}</div>
  `)
  body.querySelector('#w-scan').addEventListener('click', () => doScan(body))
  body.querySelector('#w-managed').addEventListener('click', () => restoreManaged())
  body.querySelector('#w-mon').addEventListener('click', async () => {
    const task = startTask('Enabling monitor mode')
    try {
      const d = await apiPost('/wifi/start_monitor')
      task.done('Monitor mode', d.interface ? `Active on ${d.interface}` : 'Enabled')
    } catch (e) {
      task.fail('Monitor mode failed', e.message)
    }
  })
}

// wifite / monitor mode leave wlan1 unable to scan. Restore managed mode so the
// Scan tab (wpa_cli) works again.
async function restoreManaged() {
  const task = startTask('Restoring managed mode')
  try {
    await apiPost('/wifi/stop_monitor', {}, { timeout: 20000 })
    task.done('Managed mode restored', 'Scanning is available again')
  } catch (e) {
    task.fail('Could not restore managed mode', e.message)
  }
}

async function doScan(body) {
  const out = body.querySelector('#w-results')
  out.innerHTML = spinner('Scanning for networks...')
  const task = startTask('Scanning Wi-Fi')
  try {
    const d = await apiGet('/wifi/scan', { timeout: 30000 })
    const nets = d.networks || []
    task.done('Scan complete', `${nets.length} networks`)
    if (!nets.length) return (out.innerHTML = empty('No networks found.'))
    out.innerHTML = `
      <div class="overflow-x-auto -mx-1">
        <table class="table table-sm">
          <thead><tr><th>Network</th><th>Security</th><th>Risk</th><th>Ch</th><th>Signal</th></tr></thead>
          <tbody>${nets.map(netRow).join('')}</tbody>
        </table>
      </div>`
  } catch (e) {
    task.fail('Scan failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

function netRow(n) {
  return `
  <tr>
    <td>
      <div class="font-medium">${esc(n.ssid || 'Hidden network')}</div>
      <div class="text-[0.65rem] text-base-content/40 font-mono">${esc(n.bssid || '-')}</div>
    </td>
    <td class="text-xs">${esc(n.security || '?')}</td>
    <td>${riskBadge(n.risk)}</td>
    <td class="text-xs">${esc(n.channel ?? '-')}</td>
    <td class="whitespace-nowrap">${signalBars(n.signal_dbm)} <span class="text-[0.65rem] text-base-content/50">${n.signal_dbm !== undefined ? n.signal_dbm + ' dBm' : ''}</span></td>
  </tr>`
}

// ---------------------------------------------------------------- Audit
function auditTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Vulnerability audit', `<button id="w-audit" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-shield-halved"></i>Run audit</button>`)}
    ${infoBox('Uses <strong>wifite</strong> to find networks with active clients and flag WEP / WPS / handshake-capturable targets. Takes ~15s.')}
    <div id="w-audit-out" class="mt-3">${empty('Run an audit to find vulnerable networks.', 'fa-shield-halved')}</div>
  `)
  body.querySelector('#w-audit').addEventListener('click', async () => {
    const out = body.querySelector('#w-audit-out')
    out.innerHTML = spinner('wifite scanning (15s)...')
    const task = startTask('Wi-Fi audit', 'wifite scanning for 15s')
    try {
      const d = await apiPost('/wifi/audit/wifite-scan', { scan_time: 15 }, { timeout: 60000 })
      const targets = d.targets || []
      task.done('Audit complete', `${targets.length} target(s)`)
      if (!targets.length) return (out.innerHTML = empty('No networks with active clients detected.'))
      out.innerHTML = targets.map(auditCard).join('')
    } catch (e) {
      task.fail('Audit failed', e.message)
      out.innerHTML = errorBox(e.message)
    }
  })
}

function auditCard(t) {
  const enc = (t.encryption || '').toLowerCase()
  const vulns = []
  if (enc.includes('wep')) vulns.push('WEP - crackable in minutes')
  if (enc.includes('wpa') && !enc.includes('wpa3')) vulns.push('WPA handshake capture possible')
  if (t.wps === 'yes') vulns.push('WPS enabled (Pixie-Dust)')
  const clients = parseInt(t.clients) || 0
  if (clients > 0) vulns.push(`${clients} connected client(s)`)
  return `
  <div class="rounded-xl border-l-4 border-warning bg-base-200/50 p-3 mb-2">
    <div class="flex items-center justify-between gap-2">
      <span class="font-semibold text-sm">${esc(t.essid || '(hidden)')}</span>
      <span class="text-[0.65rem] text-base-content/50">Ch ${esc(t.channel)} · ${esc(t.power)}dB · ${esc((t.encryption || '').toUpperCase())}</span>
    </div>
    <ul class="mt-1.5 text-xs text-base-content/70 space-y-0.5">
      ${vulns.map((v) => `<li><i class="fa-solid fa-angle-right text-warning text-[0.6rem] mr-1"></i>${esc(v)}</li>`).join('')}
    </ul>
  </div>`
}

// ---------------------------------------------------------------- Probes
function probesTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Probe requests')}
    ${infoBox('Capture probe requests to reveal which networks nearby devices are searching for.')}
    <div class="flex gap-2 mt-3">
      ${[15, 30, 60].map((s) => `<button class="btn btn-sm ${s === 15 ? 'btn-primary' : 'btn-ghost'}" data-dur="${s}">${s}s</button>`).join('')}
    </div>
    <div id="w-probes-out" class="mt-3">${empty('Choose a duration to start listening.', 'fa-satellite')}</div>
  `)
  body.querySelectorAll('[data-dur]').forEach((b) =>
    b.addEventListener('click', () => doProbes(body, parseInt(b.dataset.dur))),
  )
}

async function doProbes(body, dur) {
  const out = body.querySelector('#w-probes-out')
  out.innerHTML = spinner(`Listening for ${dur}s...`)
  const task = startTask('Capturing probes', `${dur}s window`)
  try {
    const d = await apiPost('/wifi/probes', { duration: dur }, { timeout: (dur + 30) * 1000 })
    const probes = d.probes || []
    task.done('Probes captured', `${probes.length} request(s)`)
    if (!probes.length) return (out.innerHTML = empty('No probe requests captured.'))
    out.innerHTML = `
      <div class="overflow-x-auto"><table class="table table-sm">
        <thead><tr><th>Client MAC</th><th>Looking for</th></tr></thead>
        <tbody>${probes
          .map((p) => `<tr><td class="font-mono text-xs">${esc(p.client_mac)}</td><td>${esc(p.ssid || '(broadcast)')}</td></tr>`)
          .join('')}</tbody>
      </table></div>`
  } catch (e) {
    task.fail('Probe capture failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- Attack
function attackTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Targeted attack', `<button id="w-rescan" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Rescan</button>`)}
    ${infoBox('<span class="text-warning font-semibold">Only attack networks you own or are authorised to test.</span> wifite runs handshake capture + WPS in the background.')}
    <div id="w-attack-list" class="mt-3"></div>
    <div id="w-attack-result" class="console mt-3 hidden"></div>
  `)
  body.querySelector('#w-rescan').addEventListener('click', () => loadTargets(body))
  loadTargets(body)
}

async function loadTargets(body) {
  const list = body.querySelector('#w-attack-list')
  list.innerHTML = spinner('wifite scanning for targets (10s)...')
  const task = startTask('Finding targets', 'wifite scan 10s')
  try {
    const d = await apiPost('/wifi/audit/wifite-scan', { scan_time: 10 }, { timeout: 60000 })
    const targets = d.targets || []
    task.done('Scan complete', `${targets.length} target(s)`)
    if (!targets.length) return (list.innerHTML = empty('No targets with connected clients found.'))
    list.innerHTML = targets
      .map((t, i) => {
        const enc = (t.encryption || '').toLowerCase()
        const hidden = /^\([0-9A-F:]+\)$/i.test(t.essid || '')
        const name = hidden ? `(hidden ${t.essid})` : t.essid
        return `
        <div class="flex items-center justify-between gap-3 rounded-xl bg-base-200/50 px-3 py-2.5 mb-2">
          <div class="min-w-0">
            <div class="font-semibold text-sm truncate">${esc(name)}</div>
            <div class="text-[0.65rem] text-base-content/50">Ch ${esc(t.channel)} · ${esc(t.power)}dB · ${esc(t.clients)} clients · ${esc(enc.toUpperCase())}${t.wps === 'yes' ? ' · WPS' : ''}</div>
          </div>
          <button class="btn btn-error btn-sm btn-outline gap-2" data-attack="${i}"><i class="fa-solid fa-burst"></i>Attack</button>
        </div>`
      })
      .join('')
    list.querySelectorAll('[data-attack]').forEach((b) =>
      b.addEventListener('click', () => runAttack(body, targets[parseInt(b.dataset.attack)])),
    )
  } catch (e) {
    task.fail('Target scan failed', e.message)
    list.innerHTML = errorBox(e.message)
  }
}

async function runAttack(body, target) {
  const ch = parseInt(target.channel) || 0
  const res = body.querySelector('#w-attack-result')
  res.classList.remove('hidden')
  res.textContent = `Starting wifite attack on ${target.essid} (ch ${ch})...`
  const task = startTask('Wi-Fi attack', `${target.essid}`)
  try {
    const start = await apiPost('/wifi/audit/wifite-attack', { scan_time: 1, attack_time: 120, channel: ch })
    if (!start.success) throw new Error(start.error || 'Failed to start')
    let secs = 0
    const poll = setInterval(async () => {
      secs += 5
      res.textContent = `wifite attacking ${target.essid}... (${secs}s)`
      task.update(`${secs}s elapsed`)
      try {
        const chk = await apiGet('/wifi/audit/wifite-status')
        if (!chk.running) {
          clearInterval(poll)
          const scan = await apiPost('/wifi/audit/wifite-scan', { scan_time: 5 }, { timeout: 40000 })
          if (scan.cracked && scan.cracked.length) {
            const keys = scan.cracked.map((c) => `${c.essid || c.bssid}: ${c.key || c.psk || c.pin || 'found'}`).join('\n')
            res.textContent = `CRACKED:\n${keys}`
            task.done('Attack finished', 'Key recovered')
          } else {
            res.textContent = 'Attack finished. No keys cracked. Handshakes (if any) saved to /root/hs/'
            task.info('Attack finished', 'No key cracked')
          }
          // wifite leaves wlan1 in monitor mode -- return it to managed so the
          // Scan tab works without a manual reset.
          apiPost('/wifi/stop_monitor').catch(() => {})
        }
      } catch (e) {
        /* keep polling */
      }
      if (secs > 180) {
        clearInterval(poll)
        res.textContent = 'Attack timed out after 3 min (wifite may still be running).'
        task.info('Attack timed out')
        apiPost('/wifi/stop_monitor').catch(() => {})
      }
    }, 5000)
  } catch (e) {
    task.fail('Attack failed', e.message)
    res.textContent = e.message
  }
}

// ---------------------------------------------------------------- Capture
function captureTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Packet capture')}
    <label class="form-control w-full max-w-xs">
      <span class="label-text text-xs mb-1">Filter</span>
      <select id="w-cap-filter" class="select select-bordered select-sm">
        <option value="">All packets</option>
        <option value="beacons">Beacons</option>
        <option value="probes">Probe requests</option>
        <option value="management">Management frames</option>
        <option value="data">Data frames</option>
        <option value="control">Control frames</option>
      </select>
    </label>
    <button id="w-cap" class="btn btn-primary btn-sm gap-2 mt-4"><i class="fa-solid fa-floppy-disk"></i>Capture 60s</button>
    <div id="w-cap-out" class="mt-3"></div>
  `)
  body.querySelector('#w-cap').addEventListener('click', async () => {
    const filter = body.querySelector('#w-cap-filter').value || null
    const out = body.querySelector('#w-cap-out')
    out.innerHTML = spinner('Capturing for 60s...')
    const task = startTask('Packet capture', `filter: ${filter || 'all'}`)
    try {
      const d = await apiPost('/wifi/capture', { duration: 60, filter }, { timeout: 90000 })
      task.done('Capture saved', `${d.filename || ''} (${fmtBytes(d.size_bytes)})`)
      out.innerHTML = infoBox(`Saved <strong>${esc(d.filename || 'capture.pcap')}</strong> · ${fmtBytes(d.size_bytes)}`, 'fa-circle-check')
    } catch (e) {
      task.fail('Capture failed', e.message)
      out.innerHTML = errorBox(e.message)
    }
  })
}
