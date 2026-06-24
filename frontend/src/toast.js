// Toast + long-running task notifications.
//
// Two flavours:
//   notify(msg, type)  -> a transient toast that auto-dismisses.
//   startTask(label)   -> a persistent "running" toast with a live spinner for
//                         scans/attacks/captures. Returns a handle you finish
//                         with .done() / .fail() / .update(). It also feeds the
//                         "active tasks" counter shown in the header.

import { esc } from './util.js'

let container = null
const activeTasks = new Set()
const taskListeners = new Set()

const ICONS = {
  info: 'fa-circle-info',
  success: 'fa-circle-check',
  error: 'fa-circle-exclamation',
  warning: 'fa-triangle-exclamation',
  running: 'fa-spinner fa-spin',
}

const TONE = {
  info: 'border-info/40 text-info',
  success: 'border-success/40 text-success',
  error: 'border-error/40 text-error',
  warning: 'border-warning/40 text-warning',
  running: 'border-primary/50 text-primary',
}

function ensureContainer() {
  if (container) return container
  container = document.createElement('div')
  // pointer-events-none so the (often empty) container never swallows clicks
  // meant for the UI underneath it (e.g. the theme toggle). Each toast
  // re-enables pointer events on itself.
  container.className =
    'toast toast-top toast-end z-[60] max-w-[92vw] sm:max-w-sm p-3 sm:p-4 pointer-events-none'
  document.body.appendChild(container)
  return container
}

function buildToast(type, title, detail) {
  const el = document.createElement('div')
  el.className =
    'pointer-events-auto w-full rounded-xl border bg-base-100/95 backdrop-blur ' +
    'shadow-lg shadow-black/10 px-4 py-3 flex items-start gap-3 touch-pan-y ' +
    'motion-preset-slide-left motion-duration-300 ' +
    (TONE[type] || TONE.info)
  el.innerHTML = `
    <i class="fa-solid ${ICONS[type] || ICONS.info} mt-0.5 text-base"></i>
    <div class="min-w-0 flex-1">
      <div class="text-sm font-semibold text-base-content toast-title">${esc(title)}</div>
      <div class="text-xs text-base-content/60 mt-0.5 break-words toast-detail ${detail ? '' : 'hidden'}">${esc(detail || '')}</div>
    </div>
    <button class="toast-close shrink-0 -mr-1 -mt-0.5 w-6 h-6 grid place-items-center rounded-md text-base-content/40 hover:text-base-content hover:bg-base-content/10 transition-colors" aria-label="Dismiss">
      <i class="fa-solid fa-xmark text-sm"></i>
    </button>
  `
  el.querySelector('.toast-close').addEventListener('click', () => dismiss(el))
  attachSwipe(el)
  return el
}

// Swipe-to-dismiss (mobile): drag a toast to the right to flick it away.
function attachSwipe(el) {
  let startX = 0
  let dx = 0
  let dragging = false

  el.addEventListener(
    'touchstart',
    (e) => {
      startX = e.touches[0].clientX
      dx = 0
      dragging = true
      el.style.transition = 'none'
    },
    { passive: true },
  )
  el.addEventListener(
    'touchmove',
    (e) => {
      if (!dragging) return
      dx = e.touches[0].clientX - startX
      if (dx < 0) dx = 0 // only allow swiping toward the edge (right)
      el.style.transform = `translateX(${dx}px)`
      el.style.opacity = String(Math.max(0, 1 - dx / 200))
    },
    { passive: true },
  )
  const end = () => {
    if (!dragging) return
    dragging = false
    el.style.transition = ''
    if (dx > 80) {
      dismiss(el)
    } else {
      el.style.transform = ''
      el.style.opacity = ''
    }
  }
  el.addEventListener('touchend', end)
  el.addEventListener('touchcancel', end)
}

function dismiss(el) {
  if (!el || !el.isConnected) return
  el.classList.remove('motion-preset-slide-left')
  el.classList.add('motion-opacity-out-0', 'motion-translate-x-out-100', 'motion-duration-200')
  setTimeout(() => el.remove(), 220)
}

export function notify(title, type = 'info', detail = '', ttl = 4200) {
  const root = ensureContainer()
  const el = buildToast(type, title, detail)
  root.appendChild(el)
  if (ttl) setTimeout(() => dismiss(el), ttl)
  return el
}

export function startTask(label, detail = '') {
  const root = ensureContainer()
  const el = buildToast('running', label, detail)
  root.appendChild(el)

  const token = {}
  activeTasks.add(token)
  emitTaskChange()

  const finish = (type, title, msg, ttl) => {
    activeTasks.delete(token)
    emitTaskChange()
    el.className = el.className
      .replace(TONE.running, TONE[type] || TONE.info)
      .replace('motion-preset-slide-left', '')
    const icon = el.querySelector('i')
    if (icon) icon.className = `fa-solid ${ICONS[type] || ICONS.info} mt-0.5 text-base`
    setText(el, '.toast-title', title || label)
    if (msg !== undefined) setText(el, '.toast-detail', msg)
    setTimeout(() => dismiss(el), ttl)
  }

  return {
    update(msg) {
      setText(el, '.toast-detail', msg)
    },
    done(title, msg) {
      finish('success', title, msg, 4000)
    },
    fail(title, msg) {
      finish('error', title, msg, 6000)
    },
    info(title, msg) {
      finish('info', title, msg, 4000)
    },
  }
}

function setText(el, sel, text) {
  const t = el.querySelector(sel)
  if (!t) return
  t.textContent = text || ''
  t.classList.toggle('hidden', !text)
}

function emitTaskChange() {
  taskListeners.forEach((fn) => fn(activeTasks.size))
}

export function onTaskCountChange(fn) {
  taskListeners.add(fn)
  fn(activeTasks.size)
  return () => taskListeners.delete(fn)
}

export function activeTaskCount() {
  return activeTasks.size
}
