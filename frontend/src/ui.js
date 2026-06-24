// Reusable presentational fragments shared by the module views.
import { esc, faClass } from './util.js'

export function pageHead(icon, title, subtitle = '') {
  return `
  <div class="flex items-center gap-3 mb-5">
    <div class="grid place-items-center w-11 h-11 rounded-xl bg-primary/15 text-primary text-lg shrink-0">
      <i class="${faClass(icon)}"></i>
    </div>
    <div class="min-w-0">
      <h1 class="text-xl font-extrabold tracking-tight truncate">${esc(title)}</h1>
      ${subtitle ? `<p class="text-xs text-base-content/55 truncate">${esc(subtitle)}</p>` : ''}
    </div>
  </div>`
}

export function card(bodyHtml, { className = '' } = {}) {
  return `<section class="surface p-4 sm:p-5 ${className}">${bodyHtml}</section>`
}

export function sectionTitle(title, right = '') {
  return `
  <div class="flex items-center justify-between gap-3 mb-3">
    <h2 class="font-bold text-sm">${esc(title)}</h2>
    ${right ? `<div class="flex items-center gap-2">${right}</div>` : ''}
  </div>`
}

export function empty(msg, icon = 'fa-inbox') {
  return `
  <div class="flex flex-col items-center justify-center text-center py-10 text-base-content/45">
    <i class="${faClass(icon)} text-2xl mb-2"></i>
    <p class="text-sm">${esc(msg)}</p>
  </div>`
}

export function errorBox(msg) {
  return `
  <div class="rounded-xl border border-error/30 bg-error/10 text-error text-sm px-4 py-3 flex items-start gap-2">
    <i class="fa-solid fa-triangle-exclamation mt-0.5"></i>
    <span>${esc(msg)}</span>
  </div>`
}

export function infoBox(msg, icon = 'fa-circle-info') {
  return `
  <div class="rounded-xl border border-base-300 bg-base-200/60 text-base-content/70 text-xs px-3.5 py-2.5 flex items-start gap-2">
    <i class="${faClass(icon)} mt-0.5 text-base-content/40"></i>
    <span>${msg}</span>
  </div>`
}

export function spinner(label = 'Working...') {
  return `
  <div class="flex items-center justify-center gap-3 py-10 text-base-content/55">
    <span class="loading loading-spinner loading-md text-primary"></span>
    <span class="text-sm">${esc(label)}</span>
  </div>`
}

const RISK = {
  critical: 'badge-error',
  high: 'badge-warning',
  medium: 'badge-info',
  low: 'badge-success',
  none: 'badge-ghost',
}

export function riskBadge(risk) {
  const r = (risk || 'low').toLowerCase()
  return `<span class="badge badge-sm ${RISK[r] || 'badge-ghost'} badge-outline font-semibold">${esc(r.toUpperCase())}</span>`
}

// Tab bar. tabs = [{id,label,icon}]. Returns markup; caller wires clicks via
// data-tab attributes.
export function tabBar(tabs, activeId) {
  return `
  <div role="tablist" class="tabs tabs-box bg-base-200 p-1 mb-4">
    ${tabs
      .map(
        (t) => `
      <a role="tab" data-tab="${t.id}"
         class="tab gap-2 ${t.id === activeId ? 'tab-active' : ''}">
        ${t.icon ? `<i class="fa-solid ${t.icon} text-xs"></i>` : ''}${esc(t.label)}
      </a>`,
      )
      .join('')}
  </div>`
}
