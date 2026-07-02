// NFC / RFID via PN532. Read a card (UID + block 4), write/clone a 16-byte
// block to a (magic) Mifare Classic card, full sector dump/clone, mfoc key
// recovery, and browse saved captures.
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner } from '../ui.js'
import { esc, fmtBytes, timeAgoShort } from '../util.js'
import { startTask, notify } from '../toast.js'

let lastRead = null
let lastDump = null

export default function renderNfc(root) {
  root.innerHTML = `
    ${pageHead('fa-id-card', 'NFC / RFID', 'PN532 · I2C 0x24')}
    <div class="grid lg:grid-cols-2 gap-4">
      ${renderReadCard()}
      ${renderWriteCard()}
    </div>
    <div class="mt-4" id="n-advanced"></div>
    <div class="mt-4" id="n-history"></div>
  `
  root.querySelector('#n-read').addEventListener('click', () => read(root))
  root.querySelector('#n-dump').addEventListener('click', () => dumpCard(root))
  root.querySelector('#n-write').addEventListener('click', () => write(root))
  root.querySelector('#n-clone-btn').addEventListener('click', () => cloneToForm(root))
  renderAdvanced(root)
  loadHistory(root)
}

function renderReadCard() {
  return card(`
    ${sectionTitle('Read & dump', `
      <button id="n-dump" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-database"></i>Dump</button>
      <button id="n-read" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-wifi"></i>Read</button>
    `)}
    <div id="n-read-out">${empty('Hold a card near the reader. Read gets UID+block 4. Dump reads all accessible sectors.', 'fa-id-card')}</div>
  `)
}

function renderWriteCard() {
  return card(`
    ${sectionTitle('Write / clone')}
    <div class="rounded-xl bg-base-200/40 p-4 space-y-3">
      ${infoBox('Block write: writes 16 bytes to block 4 of a Mifare Classic card using the default key. Requires a writable / magic card. For full sector dumps use Clone from saved below.')}
      <label class="block">
        <span class="text-xs font-medium text-base-content/70 pb-1.5 block">Payload (hex or text, 16 bytes)</span>
        <div class="flex flex-wrap items-center gap-1.5">
          <input id="n-payload" class="input input-sm input-bordered flex-1 font-mono" placeholder="deadbeef... or plain text" />
          <button id="n-clone-btn" class="btn btn-ghost btn-xs gap-1" title="Copy last read block data"><i class="fa-solid fa-clone"></i></button>
        </div>
      </label>
      <label class="block">
        <span class="text-xs font-medium text-base-content/70 pb-1.5 block">Lock to UID (optional)</span>
        <input id="n-uid" class="input input-sm input-bordered w-full font-mono" placeholder="Leave blank for any card" />
      </label>
      <button id="n-write" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-pen"></i>Write block</button>
      <div id="n-write-out"></div>
    </div>
  `)
}

// ---------------------------------------------------------------- Read

async function read(root) {
  const out = root.querySelector('#n-read-out')
  const task = startTask('Reading card', 'Hold card to reader')
  try {
    const d = await apiGet('/nfc/read', { timeout: 15000 })
    if (!d.uid) throw new Error(d.error || 'No card detected')
    lastRead = d
    task.done('Card read', d.uid)
    const caps = d.capabilities || {}
    out.innerHTML = `
      <dl class="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-sm">
        <dt class="text-base-content/50">UID</dt><dd class="font-mono font-semibold break-all">${esc(d.uid)}</dd>
        <dt class="text-base-content/50">Type</dt><dd>${cardTypeBadge(d)} <span class="text-[0.65rem] text-base-content/50 ml-1">ATQA ${esc(d.atqa || '?')} &middot; SAK ${esc(d.sak || '?')}</span></dd>
        <dt class="text-base-content/50">Security</dt><dd class="text-xs flex items-center gap-1.5">${securityBadge(d)}</dd>
        ${caps.speeds && caps.speeds.length ? `<dt class="text-base-content/50">Speed</dt><dd class="font-mono text-xs">${speedDisplay(caps)}</dd>` : ''}
        <dt class="text-base-content/50">Block 4</dt><dd class="font-mono text-xs break-all">${esc(d.block_data || '-')}</dd>
        ${d.block_data ? `<dt class="text-base-content/50">ASCII</dt><dd class="font-mono text-xs break-all">${esc(hexToAscii(d.block_data))}</dd>` : ''}
        ${techDetails(caps)}
      </dl>`
    loadHistory(root)
  } catch (e) {
    task.fail('Read failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- Full dump

async function dumpCard(root) {
  const out = root.querySelector('#n-read-out')
  const task = startTask('Dumping card', 'Hold card to reader (takes ~15-30s)')
  out.innerHTML = spinner('Dumping all accessible sectors...')
  try {
    const d = await apiPost('/nfc/dump', {}, { timeout: 60000 })
    if (!d.success) throw new Error(d.error || 'Dump failed')
    lastDump = d
    const failed = d.sectors_failed || []
    task.done('Dump complete', `${d.sectors_read}/16 sectors read`)
    let html = `<dl class="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-sm mb-3">
      <dt class="text-base-content/50">UID</dt><dd class="font-mono font-semibold">${esc(d.uid)}</dd>
      <dt class="text-base-content/50">Sectors read</dt><dd>${d.sectors_read} / 16 ${failed.length ? '<span class="text-warning">(' + failed.length + ' failed with default key)</span>' : '<span class="text-success">(all accessible)</span>'}</dd>`
    if (failed.length) html += `<dt class="text-base-content/50">Failed sectors</dt><dd class="text-xs font-mono">${esc(failed.join(', '))}</dd>`
    html += `</dl>
      <p class="text-[0.65rem] text-base-content/50 mb-2">Use Clone from saved to write this dump. For sectors that failed, use mfoc below to recover keys.</p>
      <details class="text-xs"><summary class="cursor-pointer text-base-content/50">Raw dump data</summary>
        <pre class="mt-2 text-[0.6rem] bg-base-300/50 rounded-lg p-2 overflow-x-auto max-h-48">${esc(JSON.stringify(d.sectors, null, 2))}</pre>
      </details>`
    out.innerHTML = html
  } catch (e) {
    task.fail('Dump failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- Write

async function write(root) {
  const payload = root.querySelector('#n-payload').value.trim()
  const uid = root.querySelector('#n-uid').value.trim()
  const out = root.querySelector('#n-write-out')
  if (!payload) return (out.innerHTML = errorBox('Enter a payload to write.'))
  const task = startTask('Writing card', 'Hold target card to reader')
  try {
    const d = await apiPost('/nfc/write', { uid: uid || null, payload }, { timeout: 20000 })
    if (!d.success) throw new Error(d.error || 'Write failed')
    task.done('Write complete', d.verified ? 'Verified' : 'Written (unverified)')
    out.innerHTML = infoBox(`Wrote block ${d.block_written} to <strong>${esc(d.target_uid)}</strong> · ${d.verified ? 'verified' : 'not verified'}`, 'fa-circle-check')
    loadHistory(root)
  } catch (e) {
    task.fail('Write failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

function cloneToForm(root) {
  if (!lastRead || !lastRead.block_data) return
  root.querySelector('#n-payload').value = lastRead.block_data
  root.querySelector('#n-uid').value = ''
}

// ---------------------------------------------------------------- Advanced (mfoc, clone from dump)

function renderAdvanced(root) {
  const wrap = root.querySelector('#n-advanced')
  wrap.innerHTML = card(`
    ${sectionTitle('Advanced', `
      <button id="n-mfoc-go" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-key"></i>mfoc</button>
    `)}
    <div class="rounded-xl bg-base-200/40 p-4 space-y-3">
      <p class="text-[0.7rem] text-base-content/55">Full sector dump clone and mfoc key recovery for locked sectors. Keep card on reader during operations.</p>
      <div id="n-mfoc-out"></div>
      <div id="n-adv-clone-out"></div>
    </div>
  `)
  wrap.querySelector('#n-mfoc-go').addEventListener('click', () => startMfoc(root))
}

function toggleAdvanced(root) {
  const body = root.querySelector('#n-adv-body')
  if (body) body.style.display = body.style.display === 'none' ? 'block' : 'none'
}

async function startMfoc(root) {
  const out = root.querySelector('#n-mfoc-out')
  out.innerHTML = spinner('Running mfoc (key recovery, up to 60s)...')
  const task = startTask('mfoc key recovery', 'Keep card on reader')
  try {
    const d = await apiPost('/nfc/mfoc', { timeout: 60 }, { timeout: 90000 })
    if (!d.success) throw new Error(d.error || 'mfoc failed')
    task.done('mfoc complete', d.dump_file ? `Dump saved: ${d.dump_size} bytes` : 'No dump produced')
    out.innerHTML = infoBox('mfoc completed. Check the Pi for the dump file.', 'fa-circle-check')
    if (d.stdout) {
      out.innerHTML += `<details class="mt-2"><summary class="text-xs cursor-pointer text-base-content/50">mfoc output</summary><pre class="text-[0.6rem] bg-base-300/50 rounded-lg p-2 mt-1 max-h-32 overflow-auto">${esc(d.stdout)}</pre></details>`
    }
  } catch (e) {
    task.fail('mfoc failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

async function cloneDump(root, data) {
  const out = root.querySelector('#n-adv-clone-out')
  out.innerHTML = spinner('Writing full dump to card...')
  const task = startTask('Clone dump', 'Hold magic card to reader')
  try {
    const d = await apiPost('/nfc/clone', { dump: data }, { timeout: 60000 })
    if (!d.success) throw new Error(d.error || 'Clone failed')
    task.done('Clone complete', `${d.sectors_written} sectors written`)
    let html = infoBox(`Wrote ${d.sectors_written} sectors to <strong>${esc(d.target_uid)}</strong>`, 'fa-circle-check')
    if (d.sectors_failed && Object.keys(d.sectors_failed).length) {
      html += `<p class="text-[0.65rem] text-warning mt-1">Failed sectors: ${esc(Object.keys(d.sectors_failed).join(', '))}</p>`
    }
    out.innerHTML = html
  } catch (e) {
    task.fail('Clone failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

// ---------------------------------------------------------------- History

async function loadHistory(root) {
  const wrap = root.querySelector('#n-history')
  wrap.innerHTML = card(`
    ${sectionTitle('Saved cards', `<button id="n-hist-refresh" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Refresh</button>`)}
    <div id="n-hist-list">${spinner('Loading saved cards...')}</div>
  `)
  wrap.querySelector('#n-hist-refresh').addEventListener('click', () => loadHistory(root))
  const list = wrap.querySelector('#n-hist-list')
  try {
    const d = await apiGet('/loot', { timeout: 10000 })
    const nfcFiles = (d.files || []).filter((f) => f.category === 'nfc' && f.name && f.name.endsWith('.json'))
    if (!nfcFiles.length) { list.innerHTML = empty('No saved cards yet. Read a card to save it here.', 'fa-id-card'); return }
    const recent = nfcFiles.slice(0, 12)
    const cards = []
    for (const f of recent) {
      try {
        const r = await apiGet(`/loot/download?category=nfc&name=${encodeURIComponent(f.name)}`, { timeout: 5000 })
        cards.push({ file: f, data: r })
      } catch (_) { cards.push({ file: f, data: null }) }
    }
    cards.sort((a, b) => (b.data?.timestamp || b.file.modified || '').localeCompare(a.data?.timestamp || a.file.modified || ''))
    list.innerHTML = cards.map((c) => historyRow(c.file, c.data)).join('')
    if (nfcFiles.length > 12) {
      list.innerHTML += `<p class="text-[0.65rem] text-base-content/45 mt-2 text-center">+${nfcFiles.length - 12} more saved cards</p>`
    }
    // Wire up action buttons
    list.querySelectorAll('[data-action]').forEach((el) => {
      el.addEventListener('click', () => {
        const action = el.dataset.action
        const uid = el.dataset.uid
        const block4 = el.dataset.block4
        if (action === 'clone-block') {
          root.querySelector('#n-payload').value = block4
          root.querySelector('#n-uid').value = uid !== '?' ? uid : ''
          notify('Payload copied', 'info', `Block 4 from ${uid} → write form`)
        } else if (action === 'clone-full') {
          // Fetch and write full dump
          const name = el.dataset.name
          cloneFromSaved(root, name)
        }
      })
    })
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

async function cloneFromSaved(root, name) {
  const out = root.querySelector('#n-adv-clone-out')
  if (!out) return
  try {
    const data = await apiGet(`/loot/download?category=nfc&name=${encodeURIComponent(name)}`, { timeout: 5000 })
    const dump = data?.data?.dump || data?.data
    if (!dump || typeof dump !== 'object') {
      out.innerHTML = errorBox('No sector dump data in this save file. Use Read -> Dump to capture a full dump first.')
      return
    }
    const keys = Object.keys(dump)
    if (keys.some((k) => /^\d+$/.test(k))) {
      cloneDump(root, dump)
    } else {
      out.innerHTML = errorBox('This save only has block-level data, not a full sector dump. Use the Dump button to capture full sectors.')
    }
  } catch (e) {
    if (out) out.innerHTML = errorBox(e.message)
  }
}

function historyRow(file, data) {
  const uid = data?.uid || '?'
  const cardType = data?.type || 'NFC Tag'
  const ts = data?.timestamp || file.modified || ''
  const block4 = data?.data?.block_4 || data?.data?.block_data || '-'
  const ascii = block4 !== '-' ? hexToAscii(block4) : null
  const hasDump = data?.data?.dump && Object.keys(data.data.dump).some((k) => /^\d+$/.test(k))
  const atqa = data?.data?.atqa || ''
  const sak = data?.data?.sak || ''
  // Build a fake read-result object for the badge helpers
  const badgeData = { card_type: cardType, atqa: atqa, sak: sak }
  return `
  <div class="rounded-lg bg-base-200/50 border border-base-300/40 p-3 mb-2">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="font-mono font-semibold text-sm">${esc(uid)}</span>
          ${cardTypeBadge(badgeData)}
          ${hasDump ? '<span class="badge badge-xs badge-success">full dump</span>' : ''}
        </div>
        <div class="text-[0.65rem] text-base-content/45 mt-0.5 flex items-center gap-2 flex-wrap">
          ${atqa ? '<span class="font-mono">ATQA ' + esc(atqa) + ' / SAK ' + esc(sak) + '</span>' : ''}
          <span>Block 4: <code class="text-[0.6rem] bg-base-300/50 px-1 rounded">${esc(block4)}</code></span>
          ${ascii ? '<span>&middot; ASCII: <code class="text-[0.6rem] bg-base-300/50 px-1 rounded">' + esc(ascii) + '</code></span>' : ''}
        </div>
        <div class="mt-1">${securityBadge(badgeData)}</div>
      </div>
      <div class="flex items-center gap-1 shrink-0">
        <button class="btn btn-ghost btn-xs gap-1" data-action="clone-block" data-uid="${esc(uid)}" data-block4="${esc(block4)}" title="Copy block 4 to write form"><i class="fa-solid fa-copy"></i></button>
        ${hasDump ? `<button class="btn btn-primary btn-xs gap-1" data-action="clone-full" data-name="${esc(file.name)}" title="Write full dump to magic card"><i class="fa-solid fa-download"></i></button>` : ''}
      </div>
    </div>
    <div class="flex items-center gap-3 mt-1">
      <span class="text-[0.6rem] text-base-content/45">${esc(timeAgoShort(ts))}</span>
      <span class="text-[0.6rem] text-base-content/35">${esc(file.size ? fmtBytes(file.size) : '')}</span>
    </div>
  </div>`
}

// ---------------------------------------------------------------- Helpers

function cardTypeBadge(d) {
  const t = d.card_type || ''
  let cls = 'badge badge-xs '
  let tip = ''
  if (t.includes('DESFire')) {
    cls += 'badge-success'
    tip = 'AES-128 encrypted, ISO 14443-4. Cannot crack with mfoc.'
  } else if (t.includes('Classic')) {
    cls += 'badge-warning'
    tip = 'Crypto-1 cipher (broken). Can dump/clone with default keys or mfoc.'
  } else if (t.includes('Ultralight')) {
    cls += 'badge-ghost'
    tip = 'No encryption. Plaintext read/write.'
  } else {
    cls += 'badge-ghost'
    tip = 'Type unknown. May not be readable.'
  }
  return `<span class="${cls}" title="${esc(tip)}">${esc(t)}</span>`
}

function securityBadge(d) {
  const t = d.card_type || ''
  if (t.includes('DESFire')) {
    return `<span class="badge badge-xs badge-success" title="AES-128 encrypted, cannot crack with available tools"><i class="fa-solid fa-lock text-[0.5rem] mr-1"></i>Locked</span>
      <span class="text-[0.65rem] text-base-content/50">AES-128 · ISO 14443-4 · not crackable</span>`
  }
  if (t.includes('Classic')) {
    return `<span class="badge badge-xs badge-warning" title="Crypto-1 cipher is cryptographically broken"><i class="fa-solid fa-shield-halved text-[0.5rem] mr-1"></i>Vulnerable</span>
      <span class="text-[0.65rem] text-base-content/50">Crypto-1 cipher · crackable with mfoc</span>`
  }
  if (t.includes('Ultralight')) {
    return `<span class="badge badge-xs badge-ghost" title="No encryption at all"><i class="fa-solid fa-lock-open text-[0.5rem] mr-1"></i>Open</span>
      <span class="text-[0.65rem] text-base-content/50">No encryption · plaintext read/write</span>`
  }
  return `<span class="text-[0.65rem] text-base-content/50">Unknown</span>`
}

function speedDisplay(caps) {
  const speeds = caps.speeds || []
  if (!speeds.length) return '-'
  return speeds.join(' / ') + ' kbps'
}

function techDetails(caps) {
  if (!caps || !Object.keys(caps).length) return ''
  const parts = []
  if (caps.ats) parts.push(`<span class="text-base-content/50">ATS</span> <code class="font-mono text-[0.65rem]">${esc(caps.ats)}</code>`)
  if (caps.max_frame) parts.push(`<span class="text-base-content/50">Max frame</span> ${esc(caps.max_frame)} bytes`)
  if (caps.uid_size) parts.push(`<span class="text-base-content/50">UID</span> ${esc(caps.uid_size)}`)
  if (caps.iso14443_4) parts.push(`<span class="text-base-content/50">ISO</span> 14443-4`)
  if (caps.fingerprint && caps.fingerprint.length) {
    parts.push(`<span class="text-base-content/50">Chip</span> <span class="text-[0.65rem]">${esc(caps.fingerprint.join(' or '))}</span>`)
  }
  if (!parts.length) return ''
  return `<dt class="text-base-content/50 mt-1">Details</dt><dd class="text-xs flex flex-wrap gap-x-3 gap-y-0.5">${parts.join('')}</dd>`
}

function hexToAscii(hex) {
  if (!hex) return ''
  try {
    const bytes = hex.match(/.{1,2}/g) || []
    const chars = bytes.map((b) => {
      const c = parseInt(b, 16)
      return c >= 32 && c <= 126 ? String.fromCharCode(c) : '.'
    })
    return chars.join('')
  } catch (_) { return '' }
}
