// BadUSB: browse the synced payload library (OS -> category -> payload),
// search, sync updates, and execute payloads. Files tab for filesystem payloads.
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner, tabBar } from '../ui.js'
import { esc } from '../util.js'
import { startTask, notify } from '../toast.js'

const TABS = [
  { id: 'library', label: 'Library', icon: 'fa-book' },
  { id: 'files', label: 'Files', icon: 'fa-folder' },
]

let active = 'library'
let selectedLayout = 'us'

export default function renderBadusb(root) {
  root.innerHTML = `
    ${pageHead('fa-keyboard', 'BadUSB', 'USB HID gadget · /dev/hidg0')}
    ${tabBar(TABS, active)}
    <div id="bu-body"></div>
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
  const body = root.querySelector('#bu-body')
  if (active === 'library') libraryView(body)
  else filesView(body)
}

// ================================================================ Library tab

let navOS = null       // current OS slug filter, null = all
let navCategory = null // current category slug, null = at OS level
let navPayload = null  // current payload id, null = at list level

function libraryView(body) {
  body.innerHTML = card(`
    <div class="flex flex-wrap items-center gap-2 mb-3">
      <div class="flex items-center gap-1.5 flex-1 min-w-0">
        <input id="bu-search" type="search" placeholder="Search payloads..."
               class="input input-bordered input-sm flex-1" />
        <button id="bu-search-btn" class="btn btn-primary btn-sm btn-square"><i class="fa-solid fa-magnifying-glass"></i></button>
      </div>
      <div class="flex items-center gap-2">
        <label class="text-xs text-base-content/60 hidden sm:inline">Target layout</label>
        <select id="bu-layout" class="select select-bordered select-sm w-16" title="Keyboard layout of the target machine"></select>
      </div>
    </div>
    <div id="bu-os-row" class="flex flex-wrap gap-1.5 mb-3"></div>
    <div id="bu-crumb" class="text-xs text-base-content/60 mb-3 hidden"></div>
    <div id="bu-list" class="overflow-y-auto overscroll-contain max-h-[55vh] sm:max-h-[60vh] -mx-1 px-1"></div>
    <div class="flex items-center justify-between mt-4 pt-3 border-t border-base-300/60">
      <span id="bu-stats" class="text-[0.65rem] text-base-content/45"></span>
      <button id="bu-sync" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-cloud-arrow-down"></i>Sync repos</button>
    </div>
  `)

  const search = body.querySelector('#bu-search')
  body.querySelector('#bu-search-btn').addEventListener('click', () => doSearch(body, search.value.trim()))
  search.addEventListener('keyup', (e) => {
    if (e.key === 'Enter') doSearch(body, search.value.trim())
  })
  body.querySelector('#bu-sync').addEventListener('click', () => syncStart(body))

  const layoutSel = body.querySelector('#bu-layout')
  layoutSel.innerHTML = ['us', 'de'].map((l) => `<option value="${l}"${l === selectedLayout ? ' selected' : ''}>${l.toUpperCase()}</option>`).join('')
  layoutSel.addEventListener('change', (e) => { selectedLayout = e.target.value })

  // Reset nav and show OS grid
  navOS = null; navCategory = null; navPayload = null
  loadOSGrid(body)
}

// -- breadcrumbs --------------------------------------------------------------

function crumb(body, parts) {
  const el = body.querySelector('#bu-crumb')
  el.classList.toggle('hidden', !parts.length)
  el.innerHTML = parts
    .map((p, i) =>
      p.action
        ? `<a class="link link-hover text-primary cursor-pointer" data-crumb="${i}">${esc(p.label)}</a>`
        : `<span class="font-semibold text-base-content">${esc(p.label)}</span>`,
    )
    .join('<i class="fa-solid fa-angle-right text-base-content/30 mx-1.5 text-[0.6rem]"></i>')
  el.querySelectorAll('[data-crumb]').forEach((a) =>
    a.addEventListener('click', () => parts[parseInt(a.dataset.crumb)].action()),
  )
}

// -- OS grid ------------------------------------------------------------------

async function loadOSGrid(body) {
  navOS = null; navCategory = null; navPayload = null
  crumb(body, [])
  const list = body.querySelector('#bu-list')
  const stats = body.querySelector('#bu-stats')
  list.innerHTML = spinner('Loading library...')

  try {
    const d = await apiGet('/badusb/library/os', { timeout: 15000 })
    const osTypes = d.os_types || []
    // OS filter pills
    const osRow = body.querySelector('#bu-os-row')
    osRow.innerHTML = [
      `<button class="btn btn-xs ${navOS === null ? 'btn-primary' : 'btn-ghost'}" data-os-all>All</button>`,
      ...osTypes.map((o) =>
        `<button class="btn btn-xs ${navOS === o.slug ? 'btn-primary' : 'btn-ghost'}" data-os="${esc(o.slug)}">${esc(o.name)} <span class="text-base-content/40 ml-0.5">${o.payload_count}</span></button>`,
      ),
    ].join('')
    osRow.querySelectorAll('[data-os-all]').forEach((b) =>
      b.addEventListener('click', () => { navOS = null; loadOSGrid(body) }),
    )
    osRow.querySelectorAll('[data-os]').forEach((b) =>
      b.addEventListener('click', () => { navOS = b.dataset.os; loadCategoryGrid(body) }),
    )

    if (stats) {
      const total = osTypes.reduce((s, o) => s + o.payload_count, 0)
      stats.textContent = `${total} payloads across ${osTypes.length} platforms`
    }
    if (!osTypes.length) {
      list.innerHTML = empty('Library is empty. Run "Sync repos" to import payloads from GitHub.', 'fa-book')
      return
    }
    // Show category grid
    loadCategoryGrid(body)
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

// -- Category grid ------------------------------------------------------------

async function loadCategoryGrid(body) {
  navCategory = null; navPayload = null
  const list = body.querySelector('#bu-list')
  list.innerHTML = spinner('Loading categories...')

  try {
    const params = navOS ? `?os=${encodeURIComponent(navOS)}` : ''
    const d = await apiGet(`/badusb/library/categories${params}`, { timeout: 10000 })
    const cats = d.categories || []

    const osLabel = navOS
      ? (navOS.charAt(0).toUpperCase() + navOS.slice(1))
      : 'All platforms'
    crumb(body, [{ label: osLabel, action: () => loadOSGrid(body) }])

    if (!cats.length) {
      list.innerHTML = empty('No categories for this platform.', 'fa-folder')
      return
    }

    list.innerHTML = `<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">${cats
      .map((c) => `
      <button class="rounded-xl border border-base-300/70 p-3 text-left hover:border-primary/50 hover:bg-base-200/60 transition-colors" data-cat="${esc(c.slug)}">
        <div class="font-semibold text-sm truncate">${esc(c.name.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()))}</div>
        <div class="text-[0.65rem] text-base-content/45">${c.payload_count} payloads</div>
      </button>`,
      )
      .join('')}</div>`
    list.querySelectorAll('[data-cat]').forEach((b) =>
      b.addEventListener('click', () => { navCategory = b.dataset.cat; loadPayloadList(body) }),
    )
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

// -- Payload list -------------------------------------------------------------

async function loadPayloadList(body) {
  navPayload = null
  const list = body.querySelector('#bu-list')
  list.innerHTML = spinner('Loading payloads...')

  try {
    const params = new URLSearchParams()
    if (navOS) params.set('os', navOS)
    if (navCategory) params.set('category', navCategory)
    const d = await apiGet(`/badusb/library/payloads?${params.toString()}`, { timeout: 10000 })
    const payloads = d.payloads || []

    const osLabel = navOS
      ? (navOS.charAt(0).toUpperCase() + navOS.slice(1))
      : 'All platforms'
    const catLabel = navCategory
      ? navCategory.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
      : 'All categories'

    crumb(body, [
      { label: osLabel, action: () => { navCategory = null; loadCategoryGrid(body) } },
      { label: catLabel },
    ])

    if (!payloads.length) {
      list.innerHTML = empty('No payloads in this category.', 'fa-file-code')
      return
    }

    list.innerHTML = payloads.map((p) => payloadRow(p)).join('')
    list.querySelectorAll('[data-payload]').forEach((el) =>
      el.addEventListener('click', () => showPayloadDetail(body, parseInt(el.dataset.payload))),
    )
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

function payloadRow(p) {
  const osBadge = `<span class="badge badge-xs badge-outline">${esc(p.os_name || '?')}</span>`
  return `
  <button class="w-full flex items-center justify-between gap-3 rounded-xl bg-base-200/50 px-3 py-2.5 mb-2 hover:bg-base-200 transition-colors text-left"
          data-payload="${p.id}">
    <span class="min-w-0">
      <span class="block font-medium text-sm truncate">${esc(p.name)}</span>
      <span class="flex items-center gap-1.5 mt-0.5">
        ${osBadge}
        <span class="text-[0.65rem] text-base-content/45">${esc(p.category_name || '')}</span>
        ${p.author ? `<span class="text-[0.65rem] text-base-content/30">by ${esc(p.author)}</span>` : ''}
      </span>
    </span>
    <i class="fa-solid fa-angle-right text-base-content/30"></i>
  </button>`
}

// -- Payload detail -----------------------------------------------------------

async function showPayloadDetail(body, payloadId) {
  navPayload = payloadId
  const list = body.querySelector('#bu-list')
  list.innerHTML = spinner('Loading payload...')

  try {
    const d = await apiGet(`/badusb/library/payload/${payloadId}`, { timeout: 10000 })
    const p = d

    // Breadcrumb: OS -> Category -> Payload
    const osLabel = p.os_name || 'All'
    const catLabel = (p.category_name || 'general').replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())

    crumb(body, [
      { label: osLabel, action: () => { navCategory = null; navPayload = null; loadCategoryGrid(body) } },
      { label: catLabel, action: () => { navPayload = null; loadPayloadList(body) } },
      { label: p.name },
    ])

    const lines = (p.content || '').split('\n').length
    list.innerHTML = `
      <div class="space-y-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h3 class="font-semibold text-base">${esc(p.name)}</h3>
            <div class="flex flex-wrap items-center gap-1.5 mt-1">
              ${p.os_name ? `<span class="badge badge-sm badge-primary">${esc(p.os_name)}</span>` : ''}
              ${p.category_name ? `<span class="badge badge-sm badge-ghost">${esc(p.category_name)}</span>` : ''}
              ${p.layout ? `<span class="badge badge-xs badge-outline">${esc(p.layout.toUpperCase())}</span>` : ''}
              ${p.target ? `<span class="text-xs text-base-content/60">${esc(p.target)}</span>` : ''}
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button id="bu-arm-btn" class="btn btn-warning btn-outline btn-sm gap-1.5" title="Arm to auto-fire when USB is plugged into target"><i class="fa-solid fa-bolt"></i>Arm</button>
            <button id="bu-edit-btn" class="btn btn-outline btn-sm gap-1.5"><i class="fa-solid fa-pen-to-square"></i>Edit</button>
            <button id="bu-run-btn" class="btn btn-primary btn-sm gap-1.5"><i class="fa-solid fa-play"></i>Run</button>
          </div>
        </div>

        ${p.description ? `<p class="text-sm text-base-content/70 italic">${esc(p.description)}</p>` : ''}

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          ${p.author ? `<div><span class="text-base-content/40">Author</span><br>${esc(p.author)}</div>` : ''}
          ${p.source_repo && p.source_repo !== 'filesystem' ? `<div><span class="text-base-content/40">Source</span><br><a class="link link-hover" href="https://github.com/${esc(p.source_repo)}" target="_blank" rel="noopener">${esc(p.source_repo)}</a></div>` : ''}
          ${p.payload_version ? `<div><span class="text-base-content/40">Version</span><br>${esc(p.payload_version)}</div>` : ''}
          <div><span class="text-base-content/40">Size</span><br>${lines} lines</div>
        </div>

        <div>
          <div class="text-xs text-base-content/40 mb-1 font-semibold uppercase tracking-wide">Script Preview</div>
          <pre id="bu-preview" class="rounded-xl bg-base-300/50 p-4 text-xs font-mono leading-relaxed overflow-x-auto max-h-[40vh]">${esc(p.content || '')}</pre>
        </div>

        <div id="bu-edit-area" class="hidden">
          <div class="text-xs text-base-content/40 mb-1 font-semibold uppercase tracking-wide">Edit Script</div>
          <textarea id="bu-editor" class="textarea textarea-bordered w-full font-mono text-xs leading-relaxed" rows="14">${esc(p.content || '')}</textarea>
          <div class="flex gap-2 mt-2">
            <button id="bu-edit-run" class="btn btn-primary btn-sm gap-1.5"><i class="fa-solid fa-play"></i>Run edited</button>
            <button id="bu-edit-cancel" class="btn btn-ghost btn-sm">Cancel</button>
          </div>
        </div>
      </div>`

    // Arm button
    body.querySelector('#bu-arm-btn').addEventListener('click', () => armPayload(payloadId, p.name, p.content, p.layout))
    // Run button
    body.querySelector('#bu-run-btn').addEventListener('click', () => executePayload(payloadId, p.name))
    // Edit toggle
    body.querySelector('#bu-edit-btn').addEventListener('click', () => {
      const area = body.querySelector('#bu-edit-area')
      area.classList.toggle('hidden')
    })
    body.querySelector('#bu-edit-cancel').addEventListener('click', () => {
      body.querySelector('#bu-edit-area').classList.add('hidden')
    })
    body.querySelector('#bu-edit-run').addEventListener('click', () => {
      const edited = body.querySelector('#bu-editor').value
      executeContent(edited, p.name)
    })
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

// -- Search -------------------------------------------------------------------

async function doSearch(body, q) {
  if (!q) {
    if (navPayload) showPayloadDetail(body, navPayload)
    else if (navCategory) loadPayloadList(body)
    else loadOSGrid(body)
    return
  }
  const list = body.querySelector('#bu-list')
  crumb(body, [{ label: `Search: ${q}`, action: () => loadOSGrid(body) }])
  list.innerHTML = spinner('Searching...')
  try {
    const d = await apiGet(`/badusb/library/search?q=${encodeURIComponent(q)}`, { timeout: 10000 })
    const payloads = d.payloads || []
    if (!payloads.length) {
      list.innerHTML = empty(`No results for "${q}".`, 'fa-magnifying-glass')
      return
    }
    list.innerHTML = payloads.map((p) => payloadRow(p)).join('')
    list.querySelectorAll('[data-payload]').forEach((el) =>
      el.addEventListener('click', () => showPayloadDetail(body, parseInt(el.dataset.payload))),
    )
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

// -- Sync ---------------------------------------------------------------------

async function syncStart(body) {
  const btn = body.querySelector('#bu-sync')
  btn.disabled = true
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>Syncing...'

  try {
    const chk = await apiPost('/badusb/library/sync/check', {}, { timeout: 30000 })
    const repos = chk.repos || {}
    const needClone = Object.values(repos).some((r) => r.status === 'not_cloned')
    if (!needClone && Object.values(repos).every((r) => r.status === 'up_to_date')) {
      notify('Payload library is up to date', 'info')
      btn.disabled = false
      btn.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i>Sync repos'
      return
    }

    const task = startTask('Syncing payload library', 'Cloning repos and importing...')
    const start = await apiPost('/badusb/library/sync/start', {}, { timeout: 60000 })
    if (!start.success) throw new Error(start.error || 'Sync start failed')

    // Poll for completion
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 1000))
      const status = await apiGet('/badusb/library/sync/status', { timeout: 5000 })
      if (!status.running) {
        const result = status.result || {}
        const added = (result.repos || []).reduce((s, r) => s + (r.files_added || 0), 0)
        task.done('Sync complete', `${added} payloads imported`)
        btn.disabled = false
        btn.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i>Sync repos'
        loadOSGrid(body)
        return
      }
      task.update(`Importing... ${status.current} (${status.progress}/${status.total})`)
    }
    task.done('Sync started', 'Still running in background')
  } catch (e) {
    notify(e.message, 'error')
  }
  btn.disabled = false
  btn.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i>Sync repos'
}

// -- Execute ------------------------------------------------------------------

async function executePayload(payloadId, name) {
  const task = startTask('Running payload', `${name} (${selectedLayout.toUpperCase()})`)
  try {
    const d = await apiPost('/badusb/execute', { id: payloadId, layout: selectedLayout }, { timeout: 60000 })
    if (!d.success) throw new Error(d.error || 'Execution failed')
    const note = d.skipped_chars ? `${name} - ${d.skipped_chars} char(s) skipped` : name
    task.done('Payload executed', note)
  } catch (e) {
    task.fail('Payload failed', e.message)
  }
}

async function executeContent(content, label) {
  const task = startTask('Running edited payload', `${label} (${selectedLayout.toUpperCase()})`)
  try {
    const d = await apiPost('/badusb/execute', { content, layout: selectedLayout, label }, { timeout: 60000 })
    if (!d.success) throw new Error(d.error || 'Execution failed')
    task.done('Payload executed', label)
  } catch (e) {
    task.fail('Payload failed', e.message)
  }
}

async function armPayload(payloadId, name, content, layout) {
  try {
    const d = await apiPost('/badusb/arm', { id: payloadId, content, layout: layout || selectedLayout, payload: name }, { timeout: 5000 })
    if (!d.success) throw new Error(d.error || 'Arm failed')
    notify(`Armed: "${name}" will fire when USB is connected`, 'warning')
  } catch (e) {
    notify(e.message, 'error')
  }
}

// ================================================================ Files tab

function filesView(body) {
  body.innerHTML = card(`
    ${infoBox('<span class="text-warning font-semibold">The USB-C port must be plugged into the target machine.</span> Payloads type as a keyboard the moment you run them.')}
    ${sectionTitle(
      'Payloads on disk',
      `<div class="flex items-center gap-2">
        <label class="text-sm text-base-content/60">Target layout</label>
        <select id="bu-layout-f" class="select select-bordered select-sm w-20" title="Keyboard layout of the target machine"></select>
        <button id="bu-refresh" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Refresh</button>
      </div>`,
    )}
    <div id="bu-list-f">${spinner('Loading payloads...')}</div>
  `)

  body.querySelector('#bu-refresh').addEventListener('click', () => loadFiles(body))
  const sel = body.querySelector('#bu-layout-f')
  sel.innerHTML = ['us', 'de'].map((l) => `<option value="${l}"${l === selectedLayout ? ' selected' : ''}>${l.toUpperCase()}</option>`).join('')
  sel.addEventListener('change', (e) => { selectedLayout = e.target.value })
  loadFiles(body)
}

async function loadFiles(body) {
  const list = body.querySelector('#bu-list-f')
  list.innerHTML = spinner('Loading payloads...')
  try {
    const d = await apiGet('/badusb/payloads')
    const payloads = d.payloads || []
    if (!payloads.length) return (list.innerHTML = empty('No DuckyScript payloads found.', 'fa-keyboard'))
    list.innerHTML = `<div class="grid sm:grid-cols-2 gap-3">${payloads
      .map((name) => `
      <div class="flex items-center justify-between gap-3 rounded-xl bg-base-200/50 px-3 py-2.5">
        <span class="font-mono text-sm truncate"><i class="fa-solid fa-file-code text-base-content/40 mr-2"></i>${esc(name)}</span>
        <button class="btn btn-error btn-outline btn-sm gap-2" data-run="${esc(name)}"><i class="fa-solid fa-play"></i>Run</button>
      </div>`,
      )
      .join('')}</div>`
    list.querySelectorAll('[data-run]').forEach((b) =>
      b.addEventListener('click', () => executeFile(b.dataset.run)),
    )
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

async function executeFile(payload) {
  const task = startTask('Running payload', `${payload} (${selectedLayout.toUpperCase()})`)
  try {
    const d = await apiPost('/badusb/execute', { payload, layout: selectedLayout }, { timeout: 60000 })
    if (!d.success) throw new Error(d.error || 'Execution failed')
    const note = d.skipped_chars ? `${payload} - ${d.skipped_chars} char(s) skipped` : payload
    task.done('Payload executed', note)
  } catch (e) {
    task.fail('Payload failed', e.message)
  }
}
