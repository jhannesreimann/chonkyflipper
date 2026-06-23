/**
 * ChonkyFlipper Frontend - API Helpers
 */

const API_BASE = window.location.origin.includes('localhost') ? 'http://localhost:5000' : '';
const API_URL = `${API_BASE}/api`;

async function apiGet(path) {
    const response = await fetch(`${API_URL}${path}`);
    if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || `HTTP ${response.status}`);
    }
    return response.json();
}

async function apiPost(path, body = {}) {
    const response = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
    }
    return response.json();
}

async function apiDelete(path) {
    const response = await fetch(`${API_URL}${path}`, { method: 'DELETE' });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
    }
    return response.json();
}
