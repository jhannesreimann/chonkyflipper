// Thin fetch wrapper around the ChonkyFlipper REST API.
// In dev, Vite proxies /api to the Pi (see vite.config.js). In production the
// built files are served by nginx on the Pi which proxies /api to gunicorn,
// so a relative base works in both cases.

const API_URL = '/api'

async function parse(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `HTTP ${res.status}`)
  }
  return res.json()
}

export function apiGet(path, { timeout = 20000 } = {}) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeout)
  return fetch(`${API_URL}${path}`, { signal: ctrl.signal })
    .then(parse)
    .finally(() => clearTimeout(t))
}

export function apiPost(path, body = {}, { timeout = 180000 } = {}) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeout)
  return fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: ctrl.signal,
  })
    .then(parse)
    .finally(() => clearTimeout(t))
}

export function apiDelete(path, { timeout = 20000 } = {}) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeout)
  return fetch(`${API_URL}${path}`, { method: 'DELETE', signal: ctrl.signal })
    .then(parse)
    .finally(() => clearTimeout(t))
}
