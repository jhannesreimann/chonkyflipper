// Infrared: browse the Flipper-IRDB library (brands -> devices -> buttons),
// search, sync updates, and manage recorded signals (record / send / delete).
import { apiGet, apiPost, apiDelete } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner, tabBar } from '../ui.js'
import { esc } from '../util.js'
import { startTask, notify } from '../toast.js'

const TABS = [
  { id: 'library', label: 'Library', icon: 'fa-book' },
  { id: 'signals', label: 'My signals', icon: 'fa-tower-broadcast' },
]

let active = 'library'

export default function renderIr(root) {
  root.innerHTML = `
    ${pageHead('fa-tower-broadcast', 'Infrared', 'KY-005 TX · KY-022 RX')}
    ${tabBar(TABS, active)}
    <div id="ir-body"></div>
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
  const body = root.querySelector('#ir-body')
  if (active === 'library') libraryView(body)
  else signalsView(body)
}

// ================================================================ Library
function libraryView(body) {
  body.innerHTML = card(`
    <div class="flex gap-2 mb-3">
      <input id="ir-search" type="search" placeholder="Search brands, devices, buttons..."
             class="input input-bordered input-sm flex-1" />
      <button id="ir-search-btn" class="btn btn-primary btn-sm btn-square"><i class="fa-solid fa-magnifying-glass"></i></button>
    </div>
    <div id="ir-crumb" class="text-xs text-base-content/60 mb-3 hidden"></div>
    <div id="ir-lib" class="overflow-y-auto overscroll-contain max-h-[55vh] sm:max-h-[60vh] -mx-1 px-1"></div>
    <div class="flex items-center justify-between mt-4 pt-3 border-t border-base-300/60">
      <span id="ir-stats" class="text-[0.65rem] text-base-content/45"></span>
      <button id="ir-sync" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Check updates</button>
    </div>
  `)
  const search = body.querySelector('#ir-search')
  body.querySelector('#ir-search-btn').addEventListener('click', () => doSearch(body, search.value.trim()))
  search.addEventListener('keyup', (e) => {
    if (e.key === 'Enter') doSearch(body, search.value.trim())
  })
  body.querySelector('#ir-sync').addEventListener('click', () => syncCheck(body))
  showBrands(body)
}

function crumb(body, parts) {
  const el = body.querySelector('#ir-crumb')
  el.classList.toggle('hidden', !parts.length)
  el.innerHTML = parts
    .map((p, i) =>
      p.action
        ? `<a class="link link-hover text-primary" data-crumb="${i}">${esc(p.label)}</a>`
        : `<span class="font-semibold text-base-content">${esc(p.label)}</span>`,
    )
    .join('<i class="fa-solid fa-angle-right text-base-content/30 mx-1.5 text-[0.6rem]"></i>')
  el.querySelectorAll('[data-crumb]').forEach((a) =>
    a.addEventListener('click', () => parts[parseInt(a.dataset.crumb)].action()),
  )
}

async function showBrands(body) {
  crumb(body, [])
  const lib = body.querySelector('#ir-lib')
  lib.innerHTML = spinner('Loading library...')
  try {
    const d = await apiGet('/ir/library/brands', { timeout: 20000 })
    const brands = d.brands || []
    const stats = body.querySelector('#ir-stats')
    if (!brands.length) {
      lib.innerHTML = empty('Library is empty. Run "Check updates" to sync from Flipper-IRDB.', 'fa-book')
      if (stats) stats.textContent = 'Empty library'
      return
    }
    if (stats)
      stats.textContent = `${d.total} brands · ${brands.reduce((s, b) => s + (b.device_count || 0), 0)} devices`
    lib.innerHTML = `<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">${brands
      .map(
        (b) => `
      <button class="rounded-xl border border-base-300/70 p-3 text-left hover:border-primary/50 hover:bg-base-200/60 transition-colors" data-brand="${esc(b.slug)}">
        <div class="font-semibold text-sm truncate">${esc(b.name)}</div>
        <div class="text-[0.65rem] text-base-content/45">${b.device_count} devices</div>
      </button>`,
      )
      .join('')}</div>`
    lib.querySelectorAll('[data-brand]').forEach((b) =>
      b.addEventListener('click', () => showDevices(body, b.dataset.brand)),
    )
  } catch (e) {
    lib.innerHTML = errorBox(e.message)
  }
}

async function showDevices(body, slug) {
  const lib = body.querySelector('#ir-lib')
  lib.innerHTML = spinner('Loading devices...')
  try {
    const d = await apiGet(`/ir/library/brands/${encodeURIComponent(slug)}/devices`)
    crumb(body, [
      { label: 'All brands', action: () => showBrands(body) },
      { label: d.brand?.name || slug },
    ])
    const devices = d.devices || []
    if (!devices.length) return (lib.innerHTML = empty('No devices for this brand.'))
    lib.innerHTML = devices.map((dev) => deviceRow(dev)).join('')
    lib.querySelectorAll('[data-dev]').forEach((el) =>
      el.addEventListener('click', () => showButtons(body, parseInt(el.dataset.dev), el.dataset.name, slug, d.brand?.name)),
    )
  } catch (e) {
    lib.innerHTML = errorBox(e.message)
  }
}

function deviceRow(dev) {
  return `
  <button class="w-full flex items-center justify-between gap-3 rounded-xl bg-base-200/50 px-3 py-2.5 mb-2 hover:bg-base-200 transition-colors text-left"
          data-dev="${dev.id}" data-name="${esc(dev.name)}">
    <span class="min-w-0">
      <span class="block font-medium text-sm truncate">${esc(dev.name)}</span>
      <span class="block text-[0.65rem] text-base-content/45">${dev.button_count} buttons</span>
    </span>
    <i class="fa-solid fa-angle-right text-base-content/30"></i>
  </button>`
}

async function showButtons(body, deviceId, deviceName, brandSlug, brandName) {
  const lib = body.querySelector('#ir-lib')
  lib.innerHTML = spinner('Loading buttons...')
  try {
    const d = await apiGet(`/ir/library/devices/${deviceId}/buttons`)
    crumb(body, [
      { label: 'All brands', action: () => showBrands(body) },
      { label: brandName || 'Brand', action: () => showDevices(body, brandSlug) },
      { label: deviceName },
    ])
    const buttons = d.buttons || []
    if (!buttons.length) return (lib.innerHTML = empty('No buttons for this device.'))
    lib.innerHTML = `<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">${buttons
      .map((b) => {
        const power = (b.button_id || '').includes('power')
        return `<button class="btn btn-sm ${power ? 'btn-primary' : 'btn-outline'} justify-start gap-2"
          data-btn="${esc(b.button_id)}" title="${esc(b.protocol || b.protocol_hint || '')}">
          <i class="fa-solid ${power ? 'fa-power-off' : 'fa-circle-dot'} text-xs"></i>${esc(b.label)}</button>`
      })
      .join('')}</div>`
    lib.querySelectorAll('[data-btn]').forEach((b) =>
      b.addEventListener('click', () => sendLibraryButton(deviceId, b.dataset.btn)),
    )
  } catch (e) {
    lib.innerHTML = errorBox(e.message)
  }
}

async function sendLibraryButton(deviceId, buttonId) {
  const task = startTask('Sending IR', buttonId)
  try {
    const d = await apiPost(`/ir/library/devices/${deviceId}/send`, { button_id: buttonId })
    if (!d.success) throw new Error(d.error || 'Send failed')
    task.done('IR sent', buttonId)
  } catch (e) {
    task.fail('IR send failed', e.message)
  }
}

async function doSearch(body, q) {
  if (!q) return showBrands(body)
  const lib = body.querySelector('#ir-lib')
  crumb(body, [{ label: 'All brands', action: () => showBrands(body) }, { label: `Search: ${q}` }])
  lib.innerHTML = spinner('Searching...')
  try {
    const d = await apiGet(`/ir/library/search?q=${encodeURIComponent(q)}`)
    const r = d.results || {}
    let html = ''
    if (r.brands?.length) {
      html += `<div class="eyebrow mb-2">Brands</div>`
      html += r.brands.map((b) => deviceRowLink('brand', b.slug, b.name, `${b.count} devices`)).join('')
    }
    if (r.devices?.length) {
      html += `<div class="eyebrow mt-4 mb-2">Devices</div>`
      html += r.devices.map((dv) => deviceRowLink('dev', dv.id, dv.name, dv.brand_name, dv.brand_slug, dv.brand_name)).join('')
    }
    html = html || empty(`No results for "${q}".`)
    lib.innerHTML = html
    lib.querySelectorAll('[data-go-brand]').forEach((el) =>
      el.addEventListener('click', () => showDevices(body, el.dataset.goBrand)),
    )
    lib.querySelectorAll('[data-go-dev]').forEach((el) =>
      el.addEventListener('click', () =>
        showButtons(body, parseInt(el.dataset.goDev), el.dataset.name, el.dataset.brandSlug, el.dataset.brandName),
      ),
    )
  } catch (e) {
    lib.innerHTML = errorBox(e.message)
  }
}

function deviceRowLink(kind, id, name, meta, brandSlug = '', brandName = '') {
  const attr =
    kind === 'brand'
      ? `data-go-brand="${esc(id)}"`
      : `data-go-dev="${id}" data-name="${esc(name)}" data-brand-slug="${esc(brandSlug)}" data-brand-name="${esc(brandName)}"`
  return `
  <button class="w-full flex items-center justify-between gap-3 rounded-xl bg-base-200/50 px-3 py-2.5 mb-2 hover:bg-base-200 transition-colors text-left" ${attr}>
    <span class="min-w-0"><span class="block font-medium text-sm truncate">${esc(name)}</span>
      <span class="block text-[0.65rem] text-base-content/45">${esc(meta || '')}</span></span>
    <i class="fa-solid fa-angle-right text-base-content/30"></i>
  </button>`
}

async function syncCheck(body) {
  const task = startTask('IR library sync', 'Checking for updates')
  try {
    const c = await apiPost('/ir/sync/check', {}, { timeout: 30000 })
    if (c.error) throw new Error(c.error)
    if (!c.has_updates) return task.done('Library up to date')
    task.update(c.new_commits === -1 ? 'Cloning full library...' : `Syncing ${c.new_commits} commits...`)
    const s = await apiPost('/ir/sync/start')
    if (!s.success) throw new Error(s.error || 'Sync failed')
    const poll = setInterval(async () => {
      try {
        const st = await apiGet('/ir/sync/status')
        if (st.running) {
          task.update(`${st.progress}/${st.total} ${st.current || ''}`)
          return
        }
        clearInterval(poll)
        if (st.result?.success) {
          task.done('Sync complete', `${st.result.files_added} new, ${st.result.files_updated} updated`)
          showBrands(body)
        } else if (st.error) task.fail('Sync error', st.error)
        else {
          task.done('Sync complete')
          showBrands(body)
        }
      } catch (e) {
        clearInterval(poll)
        task.fail('Lost sync status', e.message)
      }
    }, 1500)
  } catch (e) {
    task.fail('Sync failed', e.message)
  }
}

// ================================================================ My signals
function signalsView(body) {
  body.innerHTML = `
    ${card(`
      ${sectionTitle('Record', `<button id="ir-refresh" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Refresh</button>`)}
      ${infoBox('Point a remote at the KY-022 receiver and press a button during the 5s window.')}
      <button id="ir-rec" class="btn btn-primary btn-sm gap-2 mt-3"><i class="fa-solid fa-circle text-error"></i>Record 5s</button>
    `, { className: 'mb-4' })}
    ${card(`
      ${sectionTitle('Recorded signals')}
      <div id="ir-sig-list"></div>
    `)}
  `
  body.querySelector('#ir-rec').addEventListener('click', () => record(body))
  body.querySelector('#ir-refresh').addEventListener('click', () => loadSignals(body))
  loadSignals(body)
}

async function record(body) {
  const task = startTask('Recording IR', 'Press a remote button')
  try {
    const d = await apiPost('/ir/record', { duration: 5 }, { timeout: 15000 })
    if (!d.success) throw new Error(d.error || 'Record failed')
    task.done('Signal captured', d.preview || d.name)
    loadSignals(body)
  } catch (e) {
    task.fail('Record failed', e.message)
  }
}

async function loadSignals(body) {
  const list = body.querySelector('#ir-sig-list')
  list.innerHTML = spinner('Loading signals...')
  try {
    const d = await apiGet('/ir/signals')
    const sigs = d.signals || []
    if (!sigs.length) return (list.innerHTML = empty('No signals recorded yet.', 'fa-tower-broadcast'))
    list.innerHTML = `
      <div class="overflow-x-auto"><table class="table table-sm">
        <thead><tr><th>Signal</th><th>Protocol</th><th>Pulses</th><th></th></tr></thead>
        <tbody>${sigs.map(sigRow).join('')}</tbody>
      </table></div>`
    list.querySelectorAll('[data-send]').forEach((b) =>
      b.addEventListener('click', () => sendSignal(b.dataset.send)),
    )
    list.querySelectorAll('[data-del]').forEach((b) =>
      b.addEventListener('click', () => deleteSignal(body, b.dataset.del)),
    )
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

function sigRow(s) {
  return `
  <tr>
    <td class="font-medium">${esc(s.name)}</td>
    <td class="text-xs">${esc(s.protocol || '?')}</td>
    <td class="text-xs">${esc(s.pulses ?? 0)}</td>
    <td class="text-right whitespace-nowrap">
      <button class="btn btn-ghost btn-xs gap-1" data-send="${esc(s.name)}"><i class="fa-solid fa-paper-plane"></i>Send</button>
      <button class="btn btn-ghost btn-xs text-error gap-1" data-del="${esc(s.name)}" title="Delete signal"><i class="fa-solid fa-trash"></i></button>
    </td>
  </tr>`
}

async function sendSignal(name) {
  const task = startTask('Transmitting IR', name)
  try {
    const d = await apiPost('/ir/transmit', { signal_id: name })
    if (!d.success) throw new Error(d.error || 'Transmit failed')
    task.done('Signal sent', name)
  } catch (e) {
    task.fail('Transmit failed', e.message)
  }
}

async function deleteSignal(body, name) {
  if (!confirm(`Delete signal "${name}"? This removes it from the device.`)) return
  try {
    const d = await apiDelete(`/ir/signals/${encodeURIComponent(name)}`)
    if (!d.success) throw new Error(d.error || 'Delete failed')
    notify('Signal deleted', 'success', name)
    loadSignals(body)
  } catch (e) {
    notify('Delete failed', 'error', e.message)
  }
}
