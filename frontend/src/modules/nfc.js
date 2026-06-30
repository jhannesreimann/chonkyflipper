// NFC / RFID via PN532. Read a card (UID + block 4), write/clone a 16-byte
// block to a (magic) Mifare Classic card, and browse saved captures.
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner } from '../ui.js'
import { esc, fmtBytes, timeAgoShort } from '../util.js'
import { startTask } from '../toast.js'

let lastRead = null

export default function renderNfc(root) {
  root.innerHTML = `
    ${pageHead('fa-id-card', 'NFC / RFID', 'PN532 · I2C 0x24')}
    <div class="grid lg:grid-cols-2 gap-4">
      ${renderReadCard()}
      ${renderWriteCard()}
    </div>
    <div class="mt-4" id="n-history"></div>
  `
  root.querySelector('#n-read').addEventListener('click', () => read(root))
  root.querySelector('#n-write').addEventListener('click', () => write(root))
  root.querySelector('#n-clone-btn').addEventListener('click', () => cloneToForm(root))
  loadHistory(root)
}

function renderReadCard() {
  return card(`
    ${sectionTitle('Read card', `<button id="n-read" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-wifi"></i>Read</button>`)}
    <div id="n-read-out">${empty('Hold a card near the reader and press Read.', 'fa-id-card')}</div>
  `)
}

function renderWriteCard() {
  return card(`
    ${sectionTitle('Write / clone')}
    <div class="rounded-xl bg-base-200/40 p-4 space-y-3">
      ${infoBox('Writes 16 bytes to block 4 of a Mifare Classic card using the default key. Requires a writable / magic card.')}
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
    out.innerHTML = `
      <dl class="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-sm">
        <dt class="text-base-content/50">UID</dt><dd class="font-mono font-semibold break-all">${esc(d.uid)}</dd>
        <dt class="text-base-content/50">Type</dt><dd>${esc(d.card_type || 'Unknown')}</dd>
        <dt class="text-base-content/50">Block 4</dt><dd class="font-mono text-xs break-all">${esc(d.block_data || '-')}</dd>
        ${d.block_data ? `<dt class="text-base-content/50">ASCII</dt><dd class="font-mono text-xs break-all">${esc(hexToAscii(d.block_data))}</dd>` : ''}
      </dl>`
    // Reload history after a successful read
    loadHistory(root)
  } catch (e) {
    task.fail('Read failed', e.message)
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
    // Fetch the 12 most recent cards for full detail
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
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

function historyRow(file, data) {
  const uid = data?.uid || '?'
  const cardType = data?.type || 'NFC Tag'
  const ts = data?.timestamp || file.modified || ''
  const block4 = data?.data?.block_4 || data?.data?.block_data || '-'
  const ascii = block4 !== '-' ? hexToAscii(block4) : null
  return `
  <div class="rounded-lg bg-base-200/50 border border-base-300/40 p-3 mb-2">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <span class="font-mono font-semibold text-sm">${esc(uid)}</span>
          <span class="badge badge-xs badge-ghost">${esc(cardType)}</span>
        </div>
        <div class="text-[0.65rem] text-base-content/45 mt-0.5">
          Block 4: <code class="text-[0.6rem] bg-base-300/50 px-1 rounded">${esc(block4)}</code>
          ${ascii ? '&middot; ASCII: <code class="text-[0.6rem] bg-base-300/50 px-1 rounded">' + esc(ascii) + '</code>' : ''}
        </div>
      </div>
      <div class="flex flex-col items-end gap-0.5 shrink-0">
        <span class="text-[0.6rem] text-base-content/45">${esc(timeAgoShort(ts))}</span>
        <span class="text-[0.6rem] text-base-content/35">${esc(file.size ? fmtBytes(file.size) : '')}</span>
      </div>
    </div>
  </div>`
}

// ---------------------------------------------------------------- Helpers

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
