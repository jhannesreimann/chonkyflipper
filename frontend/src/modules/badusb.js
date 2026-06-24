// BadUSB: list DuckyScript payloads and execute them over the USB HID gadget.
import { apiGet, apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty, errorBox, infoBox, spinner } from '../ui.js'
import { esc } from '../util.js'
import { startTask } from '../toast.js'

export default function renderBadusb(root) {
  root.innerHTML = `
    ${pageHead('fa-keyboard', 'BadUSB', 'USB HID gadget · /dev/hidg0')}
    ${card(`
      ${infoBox('<span class="text-warning font-semibold">The USB-C port must be plugged into the target machine.</span> Payloads type as a keyboard the moment you run them.')}
      ${sectionTitle('Payloads', `<button id="bu-refresh" class="btn btn-ghost btn-sm gap-2"><i class="fa-solid fa-rotate"></i>Refresh</button>`)}
      <div id="bu-list">${spinner('Loading payloads...')}</div>
    `)}
  `
  root.querySelector('#bu-refresh').addEventListener('click', () => load(root))
  load(root)
}

async function load(root) {
  const list = root.querySelector('#bu-list')
  list.innerHTML = spinner('Loading payloads...')
  try {
    const d = await apiGet('/badusb/payloads')
    const payloads = d.payloads || []
    if (!payloads.length) return (list.innerHTML = empty('No DuckyScript payloads found.', 'fa-keyboard'))
    list.innerHTML = `<div class="grid sm:grid-cols-2 gap-3">${payloads
      .map(
        (name) => `
      <div class="flex items-center justify-between gap-3 rounded-xl bg-base-200/50 px-3 py-2.5">
        <span class="font-mono text-sm truncate"><i class="fa-solid fa-file-code text-base-content/40 mr-2"></i>${esc(name)}</span>
        <button class="btn btn-error btn-outline btn-sm gap-2" data-run="${esc(name)}"><i class="fa-solid fa-play"></i>Run</button>
      </div>`,
      )
      .join('')}</div>`
    list.querySelectorAll('[data-run]').forEach((b) =>
      b.addEventListener('click', () => execute(b.dataset.run)),
    )
  } catch (e) {
    list.innerHTML = errorBox(e.message)
  }
}

async function execute(payload) {
  const task = startTask('Running payload', payload)
  try {
    const d = await apiPost('/badusb/execute', { payload }, { timeout: 60000 })
    if (!d.success) throw new Error(d.error || 'Execution failed')
    task.done('Payload executed', payload)
  } catch (e) {
    task.fail('Payload failed', e.message)
  }
}
