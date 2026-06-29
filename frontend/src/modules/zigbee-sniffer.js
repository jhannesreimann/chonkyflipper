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
      <button id="zs-scan" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-magnifying-glass"></i>Scan ch 11-14</button>
    `)}
    <div id="zs-results">${empty('Scan Zigbee channels to discover PANs.', 'fa-search')}</div>
  `)
  body.querySelector('#zs-scan').addEventListener('click', () => doScan(body))
}

async function doScan(body) {
  const out = body.querySelector('#zs-results')
  out.innerHTML = spinner('Capturing packets on channel 11 (15s) to discover devices...')
  try {
    // First capture packets on ch 11 (main Zigbee channel)
    await apiPost('/zigbee/audit/capture', { channel: 11, duration: 15 })
    // Then discover devices from the latest capture
    const d = await apiPost('/zigbee/audit/discover', {})
    if (!d.success) { out.innerHTML = errorBox(d.error || 'Discovery failed'); return }
    const devs = d.devices || []
    if (!devs.length) { out.innerHTML = empty('No devices found. Try capturing on a different channel.', 'fa-search'); return }
    let html = '<div class="text-[0.65rem] text-base-content/45 mb-3">' + d.packets_analyzed + ' packets from ' + esc(d.file || 'capture') + '</div>'
    html += '<div class="flex flex-col gap-2">'
    devs.forEach(function(dev) {
      var roleClass = 'badge-ghost'
      if (dev.role === 'Coordinator') roleClass = 'badge-warning'
      else if (dev.role === 'Router') roleClass = 'badge-info'
      else if (dev.role === 'Active End Device') roleClass = 'badge-accent'
      else roleClass = 'badge-ghost'

      var secHtml = dev.is_encrypted
        ? '<span class="badge badge-xs badge-success gap-1" title="Traffic is encrypted with a network key"><i class="fa-solid fa-lock text-[0.5rem]"></i>Encrypted</span>'
        : '<span class="badge badge-xs badge-error gap-1" title="Traffic is in plaintext - no encryption detected"><i class="fa-solid fa-lock-open text-[0.5rem]"></i>Plaintext</span>'

      var protoBadges = ''
      if (dev.has_zigbee) protoBadges += '<span class="badge badge-xs badge-outline mr-1" title="Zigbee network layer (NWK) detected">Zigbee</span>'
      if (dev.has_ipv6) protoBadges += '<span class="badge badge-xs badge-outline mr-1" title="IPv6/6LoWPAN traffic detected">IPv6</span>'

      var label = dev.friendly_name || dev.mac
      var metaHtml = ''
      if (dev.model) metaHtml += '<span class="mr-2">' + esc(dev.model) + '</span>'
      if (dev.vendor) metaHtml += '<span class="text-base-content/40">' + esc(dev.vendor) + '</span>'
      if (dev.description) metaHtml += '<span class="text-base-content/40 ml-1">(' + esc(dev.description) + ')</span>'

      html += '<div class="rounded-lg bg-base-200/50 p-3 border border-base-300/40">' +
        '<div class="flex items-center justify-between">' +
          '<div class="min-w-0 flex-1">' +
            '<div class="flex items-center gap-2">' +
              '<span class="font-semibold text-sm truncate">' + esc(label) + '</span>' +
              (dev.friendly_name ? '' : '<code class="text-[0.65rem] text-base-content/40 font-mono">' + esc(dev.mac) + '</code>') +
            '</div>' +
            '<div class="text-[0.65rem] text-base-content/45 mt-0.5">PAN ' + esc(dev.pan || '?') + ' · ' + dev.packets + ' packets' + (metaHtml ? ' · ' + metaHtml : '') + '</div></div>' +
          '<div class="flex flex-col items-end gap-1 shrink-0">' +
            '<span class="badge badge-sm ' + roleClass + '" title="' + esc(dev.role_desc || '') + '">' + esc(dev.role) + '</span>' +
            '<div class="flex flex-wrap gap-1 justify-end">' + secHtml + protoBadges + '</div>' +
          '</div>' +
        '</div></div>'
    })
    html += '</div>'
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

function parseKeysFromOutput(output) {
  var keys = []
  var lines = (output || '').split('\n')
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim()
    // zbdsniff outputs lines like: Network Key: 00112233445566778899AABBCCDDEEFF
    var m = line.match(/key:\s*([0-9a-fA-F]{32})/i)
    if (m) { keys.push({ hex: m[1].toUpperCase(), type: 'Network' }); continue }
    m = line.match(/link key:?\s*([0-9a-fA-F]{32})/i)
    if (m) { keys.push({ hex: m[1].toUpperCase(), type: 'Link' }); continue }
    m = line.match(/TC link key:?\s*([0-9a-fA-F]{32})/i)
    if (m) { keys.push({ hex: m[1].toUpperCase(), type: 'TC Link' }); continue }
    // Fallback: any 32-char hex
    m = line.match(/([0-9A-Fa-f]{32})/)
    if (m && !line.includes('Processing') && !line.includes('Processed')) {
      keys.push({ hex: m[1].toUpperCase(), type: 'Key' })
    }
  }
  return keys
}

async function doExtract(body) {
  const file = body.querySelector('#zs-extract-file')?.value?.trim()
  if (!file) { notify('Enter a capture filename', 'warning'); return }
  const out = body.querySelector('#zs-extract-output')
  out.innerHTML = spinner('Extracting keys...')
  try {
    const d = await apiPost('/zigbee/audit/extract-keys', { file: '/opt/chonkyflipper/data/zigbee_captures/' + file })
    if (!d.success) { out.innerHTML = errorBox(d.error || 'Extraction failed'); return }
    var keys = parseKeysFromOutput(d.output || '')
    var html = '<div class="text-sm text-success mb-3"><i class="fa-solid fa-circle-check mr-1"></i>Key extraction complete</div>'
    if (keys.length > 0) {
      html += '<div class="flex flex-col gap-2 mb-3">'
      keys.forEach(function(k) {
        html += '<div class="rounded-lg bg-success/10 border border-success/30 p-3">' +
          '<div class="flex items-center gap-2 mb-1"><span class="badge badge-sm badge-success">' + esc(k.type) + ' Key</span></div>' +
          '<code class="text-sm font-mono text-success break-all select-all">' + esc(k.hex.match(/.{1,2}/g).join(':')) + '</code>' +
          '</div>'
      })
      html += '</div>'
      html += '<div class="rounded-lg bg-info/10 border border-info/30 p-3 text-xs">' +
        '<div class="font-semibold text-info mb-1"><i class="fa-solid fa-circle-info mr-1"></i>What you can do with this key</div>' +
        '<ul class="list-disc pl-4 space-y-1 text-base-content/70">' +
          '<li>Decrypt all captured Zigbee traffic from this network in Wireshark</li>' +
          '<li>Replay encrypted commands that were captured (via a TX-capable dongle)</li>' +
          '<li>Identify the network for further attacks (key uniquely identifies the PAN)</li>' +
          '<li>Use with <code class="text-xs bg-base-300 px-1 rounded">zbdsniff -k KEY</code> to decrypt more captures offline</li>' +
        '</ul></div>'
    } else {
      html += '<div class="rounded-lg bg-base-200/50 p-3 text-xs text-base-content/50">' +
        '<p>No keys found in this capture. The network may use encryption that requires active probing, or no key transport was observed.</p>' +
        '<p class="mt-2">Raw output:</p>' +
        '<pre class="text-xs bg-base-300/50 rounded-lg p-2 mt-1 overflow-x-auto max-h-32">' + esc(d.output || '(empty)') + '</pre></div>'
    }
    out.innerHTML = html
  } catch (e) {
    out.innerHTML = errorBox(e.message)
  }
}
