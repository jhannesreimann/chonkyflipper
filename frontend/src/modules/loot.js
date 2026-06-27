// Loot: browse, download, and delete captured files (PCAPs, IR/Sub-GHz, NFC)
// without SSHing into the Pi.
import { apiGet, apiDelete } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, spinner } from '../ui.js'
import { esc, fmtBytes } from '../util.js'
import { startTask } from '../toast.js'

const CAT_ICON = {
  pcap: 'fa-wifi',
  ir: 'fa-tower-broadcast',
  subghz: 'fa-satellite-dish',
  nfc: 'fa-id-card',
}

export default function renderLoot(root) {
  root.innerHTML = `
    ${pageHead('fa-box-archive', 'Loot', 'Captured files on the device')}
    ${card(`
      ${sectionTitle('Files', `<button id="loot-refresh" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Refresh</button>`)}
      <div id="loot-out">${spinner('Loading files...')}</div>
    `)}
  `
  root.querySelector('#loot-refresh').addEventListener('click', () => load(root))
  load(root)
}

async function load(root) {
  const out = root.querySelector('#loot-out')
  out.innerHTML = spinner('Loading files...')
  try {
    const d = await apiGet('/loot')
    const files = d.files || []
    if (!files.length) return (out.innerHTML = empty('No captured files yet.', 'fa-box-open'))
    out.innerHTML = `
      <div class="overflow-x-auto"><table class="table table-sm">
        <thead><tr><th>File</th><th>Type</th><th>Size</th><th>When</th><th></th></tr></thead>
        <tbody>${files.map(fileRow).join('')}</tbody>
      </table></div>`
    out
      .querySelectorAll('[data-del]')
      .forEach((b) => b.addEventListener('click', () => del(root, b.dataset.cat, b.dataset.name)))
  } catch (e) {
    out.innerHTML = errorBox(e.message)
  }
}

function fileRow(f) {
  const href = `/api/loot/download?category=${encodeURIComponent(f.category)}&name=${encodeURIComponent(f.name)}`
  return `<tr>
    <td class="font-mono text-xs break-all">${esc(f.name)}</td>
    <td class="text-xs whitespace-nowrap"><i class="fa-solid ${CAT_ICON[f.category] || 'fa-file'} mr-1 text-base-content/40"></i>${esc(f.category_label)}</td>
    <td class="text-xs whitespace-nowrap">${fmtBytes(f.size)}</td>
    <td class="text-xs whitespace-nowrap">${esc(whenStr(f.modified))}</td>
    <td class="text-right whitespace-nowrap">
      <a href="${href}" class="btn btn-ghost btn-xs gap-1" download title="Download"><i class="fa-solid fa-download"></i></a>
      <button class="btn btn-ghost btn-xs text-error gap-1" data-del data-cat="${esc(f.category)}" data-name="${esc(f.name)}" title="Delete"><i class="fa-solid fa-trash"></i></button>
    </td>
  </tr>`
}

async function del(root, category, name) {
  if (!confirm(`Delete "${name}"?`)) return
  const task = startTask('Delete file', name)
  try {
    await apiDelete(`/loot?category=${encodeURIComponent(category)}&name=${encodeURIComponent(name)}`)
    task.done('File deleted', name)
    load(root)
  } catch (e) {
    task.fail('Delete failed', e.message)
  }
}

function whenStr(mtime) {
  if (!mtime) return ''
  try {
    return new Date(mtime * 1000).toLocaleString()
  } catch (e) {
    return ''
  }
}
