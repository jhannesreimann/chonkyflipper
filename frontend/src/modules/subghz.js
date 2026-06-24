// Sub-1GHz (CC1101): record at a chosen frequency, replay captured signals.
// The backend has no list endpoint, so recorded signals are tracked for the
// current session and replayed by name.
import { apiPost } from '../api.js'
import { pageHead, card, sectionTitle, empty } from '../ui.js'
import { esc } from '../util.js'
import { startTask } from '../toast.js'

const FREQS = [
  { v: '433.92', label: '433.92 MHz · garage / sockets' },
  { v: '868.35', label: '868.35 MHz · ISM band' },
  { v: '315.00', label: '315.00 MHz · US remotes' },
]

let recorded = [] // session-scoped {name, frequency, time}

export default function renderSubghz(root) {
  root.innerHTML = `
    ${pageHead('fa-satellite-dish', 'Sub-1GHz', 'CC1101 · 433 / 868 MHz')}
    ${card(`
      ${sectionTitle('Capture')}
      <label class="form-control w-full max-w-sm">
        <span class="label-text text-xs mb-1">Frequency</span>
        <select id="sg-freq" class="select select-bordered select-sm">
          ${FREQS.map((f) => `<option value="${f.v}">${esc(f.label)}</option>`).join('')}
        </select>
      </label>
      <button id="sg-rec" class="btn btn-primary btn-sm gap-2 mt-4"><i class="fa-solid fa-circle text-error"></i>Record 3s</button>
    `, { className: 'mb-4' })}
    ${card(`
      ${sectionTitle('Captured signals')}
      <div id="sg-list"></div>
    `)}
  `
  root.querySelector('#sg-rec').addEventListener('click', () => record(root))
  renderList(root)
}

function renderList(root) {
  const list = root.querySelector('#sg-list')
  if (!recorded.length) return (list.innerHTML = empty('No signals captured this session.', 'fa-wave-square'))
  list.innerHTML = recorded
    .map(
      (s, i) => `
    <div class="flex items-center justify-between gap-3 rounded-xl bg-base-200/50 px-3 py-2.5 mb-2">
      <div class="min-w-0">
        <div class="font-medium text-sm truncate">${esc(s.name)}</div>
        <div class="text-[0.65rem] text-base-content/50">${esc(s.frequency)} MHz · ${esc(s.time)}</div>
      </div>
      <button class="btn btn-ghost btn-sm gap-2" data-replay="${i}"><i class="fa-solid fa-paper-plane"></i>Replay</button>
    </div>`,
    )
    .join('')
  list.querySelectorAll('[data-replay]').forEach((b) =>
    b.addEventListener('click', () => replay(recorded[parseInt(b.dataset.replay)])),
  )
}

async function record(root) {
  const freq = root.querySelector('#sg-freq').value
  const task = startTask('Recording Sub-1GHz', `${freq} MHz · 3s`)
  try {
    const d = await apiPost('/subghz/record', { frequency: parseFloat(freq), duration: 3 }, { timeout: 20000 })
    if (!d.success) throw new Error(d.error || 'Record failed')
    recorded.unshift({
      name: d.name || `signal_${Date.now()}`,
      frequency: freq,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    })
    task.done('Signal captured', d.name || '')
    renderList(root)
  } catch (e) {
    task.fail('Record failed', e.message)
  }
}

async function replay(sig) {
  const task = startTask('Replaying signal', sig.name)
  try {
    const d = await apiPost('/subghz/transmit', { signal_id: sig.name }, { timeout: 20000 })
    if (!d.success) throw new Error(d.error || 'Transmit failed')
    task.done('Signal replayed', sig.name)
  } catch (e) {
    task.fail('Replay failed', e.message)
  }
}
