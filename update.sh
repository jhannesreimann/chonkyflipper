#!/bin/bash
################################################################################
# ChonkyFlipper Update Script
# Pulls latest code from GitHub and deploys it.
#
# Internet can come from:
#   - eth0 (LAN cable)              ← seamless: AP stays up
#   - wlan0 client (maintenance mode) ← requires WiFi switching
#   - usb0 (USB tether)
#
# Run as root: sudo /opt/chonkyflipper/update.sh
################################################################################

set -e

INSTALL_DIR="/opt/chonkyflipper"
REPO_DIR="/home/kali/chonkyflipper"
FRONTEND_DIR="/var/www/html"

echo "🔄 ChonkyFlipper Update"
echo "========================"
echo ""

# ── Check internet (try multiple interfaces) ──
echo "Checking internet connectivity..."
if ! ping -c 1 -W 3 github.com &>/dev/null; then
    echo "❌ No internet connection to github.com"
    echo ""
    echo "   Options:"
    echo "   1. Connect Ethernet cable (LAN) — seamless, AP stays up"
    echo "   2. Enable maintenance mode from the dashboard"
    echo "   3. USB tether: sudo /opt/chonkyflipper/maintenance-mode.sh usb-tether"
    exit 1
fi
echo "✅ Internet: reachable"
echo ""

# ── Verify repo exists ──
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "❌ Git repository not found at $REPO_DIR"
    echo "   Clone it first:"
    echo "   git clone https://github.com/jhannesreimann/chonkyflipper.git $REPO_DIR"
    exit 1
fi

# ── Git pull ──
cd "$REPO_DIR"
OLD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "Current version: $OLD_COMMIT"

echo "Pulling updates from GitHub..."
GIT_TERMINAL_PROMPT=0 git pull origin main 2>&1 || {
    echo ""
    echo "❌ Git pull failed."
    echo "   If this is a private repo, set up a GitHub token:"
    echo "   git remote set-url origin https://TOKEN@github.com/jhannesreimann/chonkyflipper.git"
    exit 1
}

NEW_COMMIT=$(git rev-parse --short HEAD)
echo "New version:      $NEW_COMMIT"
echo ""

# Write version file so the Flask API (running as chonky user) can read it
echo "$NEW_COMMIT" > "$INSTALL_DIR/VERSION"
chown chonky:chonky "$INSTALL_DIR/VERSION"

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
    echo "✅ Already up to date — nothing to do."
    exit 0
fi

# Show what changed
echo "Changes:"
git --no-pager log --oneline "${OLD_COMMIT}..${NEW_COMMIT}" 2>/dev/null || echo "  (detailed log unavailable)"
echo ""

# ── Update backend files ──
echo "Updating backend..."
for item in app.py requirements.txt setup-gadget.sh maintenance-mode.sh modules payloads; do
    src="$REPO_DIR/backend/$item"
    if [ -e "$src" ]; then
        cp -r "$src" "$INSTALL_DIR/"
        echo "  ✓ backend/$item"
    fi
done

# ── Update update.sh itself ──
if [ -f "$REPO_DIR/update.sh" ]; then
    cp "$REPO_DIR/update.sh" "$INSTALL_DIR/"
    chmod +x "$INSTALL_DIR/update.sh"
    echo "  ✓ update.sh (self-updated)"
fi

# ── Update frontend ──
echo "Updating frontend..."
if [ -d "$REPO_DIR/frontend" ]; then
    cp -r "$REPO_DIR/frontend/"* "$FRONTEND_DIR/"
    echo "  ✓ frontend/* → $FRONTEND_DIR"
fi

# ── Update Python dependencies ──
echo "Checking Python dependencies..."
if [ -f "$INSTALL_DIR/venv/bin/activate" ]; then
    source "$INSTALL_DIR/venv/bin/activate"
    pip install -r "$INSTALL_DIR/requirements.txt" --quiet 2>&1 | tail -1
    echo "  ✓ dependencies checked"
else
    echo "  ⚠ venv not found, skipping pip install"
fi

# ── Fix permissions ──
chown -R chonky:chonky "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/setup-gadget.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/maintenance-mode.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/update.sh" 2>/dev/null || true

# ── Restart service ──
echo ""
echo "Restarting ChonkyFlipper service..."
systemctl restart chonkyflipper

echo ""
echo "✅ Update complete: $OLD_COMMIT → $NEW_COMMIT"
echo "   The backend restarted — dashboard will reconnect automatically."
