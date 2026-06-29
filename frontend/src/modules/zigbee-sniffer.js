// Zigbee Sniffer -- CC2531 USB dongle + KillerBee
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner, tabBar } from '../ui.js'
import { esc, fmtBytes } from '../util.js'
import { startTask, notify } from '../toast.js'

const TABS = [
  { id: 'scan', label: 'Scan', icon: 'fa-magnifying-glass' },
  { id: 'capture', label: 'Capture', icon: 'fa-floppy-disk' },
  { id: 'extract', label: 'Extract', icon: 'fa-key' },
]

let active = 'scan'

export default function renderZigbeeSniffer(root) {
  root.innerHTML = `
    ${pageHead('fa-search', 'Zigbee Sniffer', 'CC2531 USB Dongle · KillerBee')}
    ${tabBar(TABS, active)}
    <div id="zs-body"></div>
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
  const body = root.querySelector('#zs-body')
  if (active === 'scan') scanTab(body)
  else if (active === 'capture') captureTab(body)
  else if (active === 'extract') extractTab(body)
}

// ---------------------------------------------------------------- Scan
async function scanTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('PAN Discovery', `
      <button id="zs-dev-check" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-plug"></i>Check</button>
      <button id="zs-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass"></i>Scan ch 11-14</button>
    `)}
    <div id="zs-dev-status" class="text-xs text-base-content/50 mb-2"></div>
    <div id="zs-results">${empty('Check device then scan for Zigbee PANs.', 'fa-search')}</div>
  `)
  body.querySelector('#zs-scan').addEventListener('click', () => doScan(body))
  body.querySelector('#zs-dev-check').addEventListener('click', () => checkDevice(body))
  checkDevice(body)
}

async function checkDevice(body) {
  const el = body.querySelector('#zs-dev-status')
  try {
    const d = await apiGet('/zigbee/audit/device')
    el.innerHTML = d.cc2531_present
      ? '<span class="badge badge-success badge-sm gap-1"><i class="fa-solid fa-circle-check text-[0.5rem]"></i>CC2531 connected</span>'
      : '<span class="badge badge-error badge-sm gap-1"><i class="fa-solid fa-circle-xmark text-[0.5rem]"></i>Not found</span>'
  } catch (e) {
    el.innerHTML = '<span class="badge badge-ghost badge-sm">Error</span>'
  }
}

async function doScan(body) {
  const out = body.querySelector('#zs-results')
  out.innerHTML = spinner('Scanning channels 11-14 for Zigbee PANs...')
  try {
    const d = await apiPost('/zigbee/audit/scan', { channels: '11-14', duration: 12 })
    if (!d.success) { out.innerHTML = errorBox(d.error || 'Scan failed'); return }
    // Show output
    const pans = d.pans || []
    let html = '<div class="text-xs text-base-content/50 mb-3">' + (d.file ? 'Results saved to ' + esc(d.file.split('/').pop()) : '') + '</div>'
    if (pans.length > 0) {
      html += '<div class="flex flex-col gap-2">' + pans.map((p, i) =>
        '<div class="rounded-lg bg-base-200/50 p-3 border border-base-300/40">' +
          '<div class="flex items-center gap-2"><span class="badge badge-sm badge-primary">' + (i+1) + '</span><span class="font-mono text-xs">' + esc(String(p).substring(0,80)) + '</span></div>' +
        '</div>'
      ).join('') + '</div>'
    } else if (d.output) {
      html += '<pre class="text-xs text-base-content/60 bg-base-200/50 rounded-lg p-3 overflow-x-auto max-h-64">' + esc(d.output.substring(0,2000)) + '</pre>'
    } else {
      html += empty('No PANs found on channels 11-14.', 'fa-search')
    }
    out.innerHTML = html
  } catch (e) {
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- Capture
async function captureTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Packet Capture', `
      <button id="zs-cap-go" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-record-vinyl"></i>Capture</button>
    `)}
    <div class="flex flex-wrap gap-2 mb-3 text-xs items-center">
      <span class="text-base-content/50">Channel:</span>
      <select id="zs-ch" class="select select-xs select-bordered">
        ${[11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26].map(c => `<option value="${c}" ${c===11?'selected':''}>${c}</option>`).join('')}
      </select>
      <span class="text-base-content/50 ml-2">Duration:</span>
      <select id="zs-dur" class="select select-xs select-bordered">
        <option value="5">5s</option><option value="10" selected>10s</option><option value="30">30s</option><option value="60">60s</option>
      </select>
    </div>
    <div id="zs-cap-status" class="text-xs text-base-content/50 mb-2"></div>
    <div id="zs-captures">${empty('Captured files will appear here.', 'fa-floppy-disk')}</div>
  `)
  body.querySelector('#zs-cap-go').addEventListener('click', () => doCapture(body))
  loadCaptures(body)
}

async function doCapture(body) {
  const ch = parseInt(body.querySelector('#zs-ch')?.value || 11)
  const dur = parseInt(body.querySelector('#zs-dur')?.value || 10)
  const task = startTask('Zigbee capture', `Ch ${ch} for ${dur}s`)
  try {
    const d = await apiPost('/zigbee/audit/capture', { channel: ch, duration: dur })
    if (d.success) {
      task.done(`${d.filename}`, `${fmtBytes(d.size_bytes)} captured`)
      loadCaptures(body)
    } else {
      task.fail('Capture failed', d.error || 'Unknown')
    }
  } catch (e) {
    task.fail('Capture error', e.message)
  }
}

async function loadCaptures(body) {
  const out = body.querySelector('#zs-captures')
  try {
    const d = await apiGet('/zigbee/audit/captures')
    const list = (d.captures || []).slice(0, 8)
    if (!list.length) { out.innerHTML = empty('No captures yet.', 'fa-floppy-disk'); return }
    out.innerHTML = '<div class="flex flex-col gap-2">' + list.map((c) =>
      '<div class="rounded-lg bg-base-200/50 p-3 border border-base-300/40 flex items-center justify-between">' +
        '<div><div class="text-sm font-semibold font-mono">' + esc(c.name) + '</div>' +
        '<div class="text-[0.65rem] text-base-content/45">' + fmtBytes(c.size_bytes) + ' · ' + esc(c.timestamp ? c.timestamp.substring(0,16) : '') + '</div></div>' +
        '<button class="btn btn-ghost btn-xs gap-1 extract-btn" data-file="' + esc(c.name) + '"><i class="fa-solid fa-key"></i></button>' +
      '</div>'
    ).join('') + '</div>'
    body.querySelectorAll('.extract-btn').forEach((b) => {
      b.addEventListener('click', () => {
        active = 'extract'
        body.closest('#zs-body')?.parentElement?.querySelectorAll('[data-tab]')?.forEach((t) => {
          t.classList.toggle('tab-active', t.dataset.tab === 'extract')
        })
        paint(body.closest('#view').querySelector('#zs-body')?.parentElement || body)
        setTimeout(() => {
          const fi = document.getElementById('zs-extract-file')
          if (fi) fi.value = b.dataset.file
        }, 100)
      })
    })
  } catch (e) {
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- Extract
async function extractTab(body) {
  body.innerHTML = card(`
    ${sectionTitle('Key Extraction', `
      <button id="zs-extract-go" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-key"></i>Extract</button>
    `)}
    <div class="form-control mb-3">
      <label class="label py-1"><span class="label-text text-xs">Capture file</span></label>
      <input id="zs-extract-file" class="input input-bordered input-sm text-xs font-mono" placeholder="e.g. zigbee_capture_20260629_100215.pcap" />
    </div>
    <div id="zs-extract-output"></div>
  `)
  body.querySelector('#zs-extract-go').addEventListener('click', () => doExtract(body))
}

async function doExtract(body) {
  const file = body.querySelector('#zs-extract-file')?.value?.trim()
  if (!file) { notify('Enter a capture filename', 'warning'); return }
  const out = body.querySelector('#zs-extract-output')
  out.innerHTML = spinner('Extracting keys...')
  try {
    const d = await apiPost('/zigbee/audit/extract-keys', { file: '/opt/chonkyflipper/data/zigbee_captures/' + file })
    if (d.success) {
      out.innerHTML = '<div class="text-sm text-success mb-2"><i class="fa-solid fa-circle-check mr-1"></i>Extraction complete</div>' +
        '<pre class="text-xs text-base-content/60 bg-base-200/50 rounded-lg p-3 overflow-x-auto max-h-64">' + esc(d.output || 'No keys found in this capture.') + '</pre>'
    } else {
      out.innerHTML = errorBox(d.error || 'Extraction failed')
    }
  } catch (e) {
    out.innerHTML = errorBox(e.message)
  }
}
