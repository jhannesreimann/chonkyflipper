// NFC / RFID via PN532. Read a card (UID + block 4) and write/clone a 16-byte
// block to a (magic) Mifare Classic card.
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox } from '../ui.js'
import { esc } from '../util.js'
import { startTask } from '../toast.js'

let lastRead = null

export default function renderNfc(root) {
  root.innerHTML = `
    ${pageHead('fa-id-card', 'NFC / RFID', 'PN532 · I2C 0x24')}
    <div class="grid lg:grid-cols-2 gap-4">
      ${card(`
        ${sectionTitle('Read card', `<button id="n-read" class="btn btn-primary btn-sm gap-2"><i class="fa-solid fa-wifi"></i>Read</button>`)}
        <div id="n-read-out">${empty('Hold a card near the reader and press Read.', 'fa-id-card')}</div>
      `)}
      ${card(`
        ${sectionTitle('Write / clone')}
        ${infoBox('Writes 16 bytes to block 4 of a Mifare Classic card using the default key. Requires a writable / magic card.')}
        <label class="form-control mt-3">
          <span class="label-text text-xs mb-1">Payload (hex or text, 16 bytes)</span>
          <input id="n-payload" class="input input-bordered input-sm font-mono" placeholder="deadbeef... or plain text" />
        </label>
        <label class="form-control mt-2">
          <span class="label-text text-xs mb-1">Lock to UID (optional)</span>
          <input id="n-uid" class="input input-bordered input-sm font-mono" placeholder="leave blank for any card" />
        </label>
        <button id="n-write" class="btn btn-secondary btn-sm gap-2 mt-4"><i class="fa-solid fa-pen"></i>Write block</button>
        <div id="n-write-out" class="mt-3"></div>
      `)}
    </div>
  `
  root.querySelector('#n-read').addEventListener('click', () => read(root))
  root.querySelector('#n-write').addEventListener('click', () => write(root))
}

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
      </dl>
      ${d.block_data ? `<button id="n-clone" class="btn btn-ghost btn-sm gap-2 mt-3"><i class="fa-solid fa-clone"></i>Use for clone</button>` : ''}`
    const clone = out.querySelector('#n-clone')
    if (clone)
      clone.addEventListener('click', () => {
        root.querySelector('#n-payload').value = d.block_data
        root.querySelector('#n-uid').value = ''
      })
  } catch (e) {
    task.fail('Read failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}

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
  } catch (e) {
    task.fail('Write failed', e.message)
    out.innerHTML = errorBox(e.message)
  }
}
