// Central polling store. One place owns the timers that hit /api/status,
// /api/system/info, /api/network/status and /api/system/version. Anything that
// needs live data subscribes instead of spinning up its own intervals.

import { apiGet } from './api.js'

const state = {
  online: false,
  status: null, // /api/status payload
  system: null, // /api/system/info payload
  network: null, // /api/network/status payload
  version: null, // /api/system/version payload
}

const listeners = new Set()
let started = false

function emit() {
  listeners.forEach((fn) => fn(state))
}

export function subscribe(fn) {
  listeners.add(fn)
  fn(state)
  return () => listeners.delete(fn)
}

export function getState() {
  return state
}

async function pollStatus() {
  try {
    const data = await apiGet('/status', { timeout: 8000 })
    state.status = data
    state.online = true
  } catch (e) {
    state.online = false
  }
  emit()
}

async function pollSystem() {
  try {
    state.system = await apiGet('/system/info', { timeout: 8000 })
    emit()
  } catch (e) {
    /* connectivity handled by pollStatus */
  }
}

async function pollNetwork() {
  try {
    state.network = await apiGet('/network/status', { timeout: 10000 })
    emit()
  } catch (e) {
    /* ignore */
  }
}

async function pollVersion() {
  try {
    state.version = await apiGet('/system/version', { timeout: 8000 })
    emit()
  } catch (e) {
    /* ignore */
  }
}

export function refreshAll() {
  pollStatus()
  pollSystem()
  pollNetwork()
  pollVersion()
}

export function startPolling() {
  if (started) return
  started = true
  refreshAll()
  setInterval(pollStatus, 5000)
  setInterval(pollSystem, 10000)
  setInterval(pollNetwork, 10000)
  setInterval(pollVersion, 60000)
}
