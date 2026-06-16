/**
 * ChonkyFlipper Frontend - Utility Functions
 */

// HTML entity encoding (all five unsafe characters)
function escapeHtml(text) {
    if (!text) return '';
    const map = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
    return String(text).replace(/[&<>"']/g, c => map[c]);
}

// Safe attribute value encoding
function escapeHtmlAttr(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
        .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// WiFi signal strength to bars
function signalToBars(dbm) {
    if (dbm === null || dbm === undefined) return '';
    if (dbm >= -50) return '▁▃▅▇';
    if (dbm >= -65) return '▁▃▅';
    if (dbm >= -75) return '▁▃';
    return '▁';
}

// Activity log (max 50 entries, auto-scroll)
function log(message) {
    const container = document.getElementById('activity-log');
    if (!container) return;
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
    while (container.children.length > 50) {
        container.removeChild(container.firstChild);
    }
}

// Show loading spinner on an element. Callers replace content themselves.
function setLoading(elementId, loading) {
    const el = document.getElementById(elementId);
    if (!el) return;
    if (loading) {
        el.style.display = '';
        el.innerHTML = '<div style="display:flex;justify-content:center;padding:20px;"><div class="spinner"></div></div>';
    }
}
