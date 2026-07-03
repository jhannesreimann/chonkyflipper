#!/bin/bash
################################################################################
# ChonkyFlipper Update Script
# Pulls latest code from GitHub and deploys it.
#
# Internet can come from:
#   - eth0 (LAN cable)              ← seamless: AP stays up
#   - usb0 (USB tether)
#
# Run as root: sudo /opt/chonkyflipper/update.sh
################################################################################

set -e

INSTALL_DIR="/opt/chonkyflipper"
REPO_DIR="/home/kali/chonkyflipper"
FRONTEND_DIR="/var/www/html"

# -- Run git commands as kali user to avoid mixed root/kali ownership in .git --
run_git() {
    if [ "$(id -u)" = "0" ] && id kali &>/dev/null; then
        sudo -u kali git "$@"
    else
        git "$@"
    fi
}

# -- Ensure git can use SSH keys (needed when running as root via sudo) --
if [ -z "$GIT_SSH_COMMAND" ] && [ -f /home/kali/.ssh/id_ed25519 ]; then
    export GIT_SSH_COMMAND="ssh -i /home/kali/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new"
fi

echo "🔄 ChonkyFlipper Update"
echo "========================"
echo ""

# -- Check internet (try multiple interfaces) --
echo "Checking internet connectivity..."
if ! ping -c 1 -W 3 github.com &>/dev/null; then
    echo "❌ No internet connection to github.com"
    echo ""
    echo "   Options:"
    echo "   1. Connect Ethernet cable (LAN)  --  seamless, AP stays up"
    echo "   2. USB tether: sudo /opt/chonkyflipper/maintenance-mode.sh usb-tether"
    exit 1
fi
echo "✅ Internet: reachable"
echo ""

# -- Verify repo exists --
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "❌ Git repository not found at $REPO_DIR"
    echo "   Clone it first:"
    echo "   git clone https://github.com/jhannesreimann/chonkyflipper.git $REPO_DIR"
    exit 1
fi

# -- Git pull --
cd "$REPO_DIR"
OLD_COMMIT=$(run_git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "Current version: $OLD_COMMIT"

echo "Pulling updates from GitHub..."
GIT_TERMINAL_PROMPT=0 run_git pull origin main 2>&1 || {
    echo ""
    echo "❌ Git pull failed."
    echo "   If this is a private repo, set up a GitHub token:"
    echo "   git remote set-url origin https://TOKEN@github.com/jhannesreimann/chonkyflipper.git"
    exit 1
}

NEW_COMMIT=$(run_git rev-parse --short HEAD)
echo "New version:      $NEW_COMMIT"
echo ""

# Write version file so the Flask API (running as chonky user) can read it
echo "$NEW_COMMIT" > "$INSTALL_DIR/VERSION"
chown chonky:chonky "$INSTALL_DIR/VERSION"

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
    echo "Git is up to date, still deploying files..."
else
    echo "Changes:"
    run_git --no-pager log --oneline "${OLD_COMMIT}..${NEW_COMMIT}" 2>/dev/null || echo "  (detailed log unavailable)"
fi
echo ""

# -- Update backend files --
echo "Updating backend..."
for item in app.py config.py utils.py requirements.txt setup-gadget.sh maintenance-mode.sh bt-deep-scan.sh ble-advertiser.py ble-advert-logger.py modules routes; do
    src="$REPO_DIR/backend/$item"
    if [ -e "$src" ]; then
        cp -r "$src" "$INSTALL_DIR/"
        echo "  ✓ backend/$item"
    fi
done

# Copy payloads (BadUSB scripts from backend, IR codes from repo root)
if [ -d "$REPO_DIR/backend/payloads" ]; then
    cp -r "$REPO_DIR/backend/payloads/"* "$INSTALL_DIR/payloads/" 2>/dev/null || true
fi
if [ -d "$REPO_DIR/payloads" ]; then
    mkdir -p "$INSTALL_DIR/payloads"
    cp -r "$REPO_DIR/payloads/"* "$INSTALL_DIR/payloads/"
    echo "  ✓ payloads (IR + BadUSB)"
fi

# -- Update update.sh itself --
if [ -f "$REPO_DIR/update.sh" ]; then
    cp "$REPO_DIR/update.sh" "$INSTALL_DIR/"
    chmod +x "$INSTALL_DIR/update.sh"
    echo "  ✓ update.sh (self-updated)"
fi

# -- Create data directory for databases --
mkdir -p "$INSTALL_DIR/data"
chown chonky:chonky "$INSTALL_DIR/data"
echo "  ✓ data directory"

# -- Build & deploy frontend (Vite + Tailwind v4 + DaisyUI) --
echo "Building frontend..."
if [ -d "$REPO_DIR/frontend" ]; then
    if command -v npm >/dev/null 2>&1; then
        # Build as the kali user so node_modules stays kali-owned (the repo
        # lives under /home/kali). npm ci is reproducible; fall back to install.
        ( cd "$REPO_DIR/frontend" \
          && (sudo -u kali npm ci --no-audit --no-fund 2>&1 || sudo -u kali npm install --no-audit --no-fund 2>&1) | tail -3 \
          && sudo -u kali npm run build 2>&1 | tail -5 )

        if [ -d "$REPO_DIR/frontend/dist" ]; then
            rm -rf "${FRONTEND_DIR:?}/"*
            cp -r "$REPO_DIR/frontend/dist/"* "$FRONTEND_DIR/"
            echo "  ✓ frontend/dist → $FRONTEND_DIR"
        else
            echo "  ✗ frontend build produced no dist/ -- leaving existing files in place"
        fi
    else
        echo "  ⚠ npm not found -- cannot build the dashboard. Install Node.js (>= 20) to deploy the frontend."
    fi
fi

# -- Update Python dependencies --
echo "Checking Python dependencies..."
if [ -f "$INSTALL_DIR/venv/bin/activate" ]; then
    source "$INSTALL_DIR/venv/bin/activate"
    pip install -r "$INSTALL_DIR/requirements.txt" --quiet 2>&1 | tail -1
    echo "  ✓ dependencies checked"
else
    echo "  ⚠ venv not found, skipping pip install"
fi

# -- Fix permissions --
chown -R chonky:chonky "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/setup-gadget.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/maintenance-mode.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/bt-deep-scan.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/update.sh" 2>/dev/null || true

# -- Restart service --
echo ""
echo "Restarting ChonkyFlipper service..."
systemctl restart chonkyflipper

echo ""
echo "✅ Update complete: $OLD_COMMIT → $NEW_COMMIT"
echo "   The backend restarted  --  dashboard will reconnect automatically."
