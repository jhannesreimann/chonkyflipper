// Small DOM + formatting helpers. No framework, just thin sugar so the module
// code stays readable.

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

export function esc(text) {
  if (text === null || text === undefined) return ''
  return String(text).replace(/[&<>"']/g, (c) => ESC[c])
}

// Tagged template that escapes interpolated values by default. Wrap a value in
// raw() to opt out (for pre-built HTML fragments).
export function html(strings, ...values) {
  return strings.reduce((acc, str, i) => {
    if (i === 0) return str
    const v = values[i - 1]
    const piece = v && v.__raw ? v.value : esc(v)
    return acc + piece + str
  }, '')
}

export function raw(value) {
  return { __raw: true, value: value ?? '' }
}

// Font Awesome ships some glyphs only in the "brands" style. Using fa-solid on
// those renders an empty box, so resolve the correct style prefix per icon.
const FA_BRANDS = new Set([
  'fa-bluetooth',
  'fa-bluetooth-b',
  'fa-github',
  'fa-usb',
  'fa-raspberry-pi',
])

export function faClass(name) {
  if (!name) return 'fa-solid'
  // Allow callers to pass a full class ("fa-brands fa-github") untouched.
  if (name.includes('fa-brands') || name.includes('fa-solid') || name.includes('fa-regular')) return name
  return `${FA_BRANDS.has(name) ? 'fa-brands' : 'fa-solid'} ${name}`
}

// Query helpers scoped to an optional root.
export const $ = (sel, root = document) => root.querySelector(sel)
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel))

// Render an HTML string into a container element.
export function mount(container, htmlStr) {
  container.innerHTML = htmlStr
  return container
}

// Signal strength (dBm) to a 0-4 bar fontawesome icon set.
export function signalBars(dbm) {
  if (dbm === null || dbm === undefined) return ''
  let level = 1
  if (dbm >= -50) level = 4
  else if (dbm >= -60) level = 3
  else if (dbm >= -72) level = 2
  return `<span class="inline-flex items-end gap-[2px] h-3 align-middle">${[1, 2, 3, 4]
    .map(
      (i) =>
        `<span class="w-[3px] rounded-sm ${i <= level ? 'bg-primary' : 'bg-base-content/20'}" style="height:${i * 25}%"></span>`,
    )
    .join('')}</span>`
}

export function fmtBytes(n) {
  if (!n && n !== 0) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1048576).toFixed(1)} MB`
}

export function timeAgoShort(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    return ''
  }
}

// Wire up onclick handlers declared as data-action on freshly rendered HTML.
// handlers is a map of action-name -> fn(event, element).
export function bindActions(root, handlers) {
  $$('[data-action]', root).forEach((el) => {
    const fn = handlers[el.dataset.action]
    if (fn) el.addEventListener('click', (e) => fn(e, el))
  })
}
