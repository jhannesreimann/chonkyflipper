#!/bin/bash
################################################################################
# ChonkyFlipper Installation Script
# Run on Kali Linux Raspberry Pi
################################################################################

set -e

echo "==================================================="
echo "  ChonkyFlipper Installation Script"
echo "  Mobile IoT Pentesting Rig"
echo "==================================================="

# Configuration
INSTALL_DIR="/opt/chonkyflipper"
SERVICE_USER="chonky"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd)"

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Error: Please run as root: sudo ./install.sh"
    exit 1
fi

echo ""
echo "Step 1: Installing system dependencies..."
apt-get update
apt-get install -y \
    python3-pip \
    python3-venv \
    aircrack-ng \
    tcpdump \
    nmap \
    bluetooth \
    bluez \
    libbluetooth-dev \
    i2c-tools \
    hostapd \
    dnsmasq \
    nginx \
    screen \
    git \
    linux-headers-$(uname -r) \
    build-essential \
    bc \
    dkms \
    libelf-dev \
    rfkill \
    iw \
    swig \
    python3-dev \
    ir-keytable

# Note: pigpio daemon compilation fails on newer kernels
# The Python pigpio library will be installed via pip for client mode
# For IR timing, consider using gpiod or manual sysfs GPIO instead

# Install AWUS036ACS (RTL8811AU) WiFi adapter driver (optional)
echo ""
echo "Step 2: Installing AWUS036ACS WiFi driver (optional)..."
if [ ! -d "/usr/src/8821au-5.12.5.2" ]; then
    git clone https://github.com/morrownr/8821au-20210708.git /tmp/8821au 2>/dev/null || true
    if [ -d "/tmp/8821au" ]; then
        cd /tmp/8821au
        ./install-driver.sh NoPrompt 2>/dev/null || echo "Warning: Driver build failed, continuing without. Onboard WiFi will be used."
        cd -
        rm -rf /tmp/8821au
    fi
else
    echo "Driver already installed, skipping."
fi

# Enable I2C and SPI (Kali doesn't have raspi-config)
echo ""
echo "Step 3: Enabling I2C and SPI interfaces..."
# Kali on Pi4 uses /boot/firmware/config.txt
if [ -f /boot/firmware/config.txt ]; then
    BOOT_CONFIG=/boot/firmware/config.txt
else
    BOOT_CONFIG=/boot/config.txt
fi
if ! grep -q "^dtparam=i2c_arm=on" "$BOOT_CONFIG"; then
    sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/g' "$BOOT_CONFIG"
    if ! grep -q "^dtparam=i2c_arm=on" "$BOOT_CONFIG"; then
        echo "dtparam=i2c_arm=on" >> "$BOOT_CONFIG"
    fi
fi
if ! grep -q "^dtparam=spi=on" "$BOOT_CONFIG"; then
    sed -i 's/^#dtparam=spi=on/dtparam=spi=on/g' "$BOOT_CONFIG"
    if ! grep -q "^dtparam=spi=on" "$BOOT_CONFIG"; then
        echo "dtparam=spi=on" >> "$BOOT_CONFIG"
    fi
fi
# Load modules
modprobe i2c-dev 2>/dev/null || true
modprobe spidev 2>/dev/null || true

# Enable USB OTG device mode for BadUSB (USB HID gadget)
# Comment out otg_mode=1 on Pi 4 (which forces host mode) to allow legacy DWC2 device mode
if grep -q '^otg_mode=1' "$BOOT_CONFIG" 2>/dev/null; then
    sed -i 's/^otg_mode=1/#otg_mode=1 # Commented out for legacy DWC2 device mode \/ BadUSB/g' "$BOOT_CONFIG" 2>/dev/null || true
fi
if ! grep -q '^dtoverlay=dwc2' "$BOOT_CONFIG" 2>/dev/null; then
    echo 'dtoverlay=dwc2' >> "$BOOT_CONFIG"
fi
for module in dwc2 libcomposite; do
    if ! grep -q "^$module" /etc/modules 2>/dev/null; then
        echo "$module" >> /etc/modules
    fi
done

# Configure Pi 4 full power-off for PiPower5 safe shutdown
echo ""
echo "Step 4: Configuring Pi 4 shutdown behaviour for PiPower5..."
if ! grep -q 'power_off_on_halt=1' "$BOOT_CONFIG" 2>/dev/null; then
    echo 'power_off_on_halt=1' >> "$BOOT_CONFIG"
fi
echo "Note: PiPower5 output cutoff is handled by pipower-shutdown.service"
echo "(I2C command to MCU at final.target, no GPIO overlay needed)"

# Install PiPower5 management tool
echo ""
echo "Step 5: Installing PiPower5 tool..."
if [ ! -d "/opt/pipower5" ]; then
    git clone https://github.com/sunfounder/pipower5 /opt/pipower5
    cd /opt/pipower5
    python3 install.py --no-reboot 2>/dev/null || python3 install.py || true
    cd -
else
    echo "PiPower5 tool already installed, skipping."
fi

# Install PiPower5 shutdown hook: sends I2C command to cut battery output.
# Uses systemd-shutdown hook directory -- runs AFTER filesystems are
# unmounted and synced, right before the kernel powers off.
# SDSIG jumper must stay on PI3V3 for Pi 4.
echo ""
echo "Step 5b: Installing PiPower5 shutdown hook..."
mkdir -p /lib/systemd/system-shutdown
cat > /lib/systemd/system-shutdown/pipower-shutdown << 'SCRIPTEOF'
#!/bin/bash
# Runs AFTER all filesystems are unmounted and synced.
# systemd-shutdown executes scripts here as the very last thing.
i2ctransfer -y 1 w4@0x5C 0xAC 0x03 0x00 0xAE 2>/dev/null || true
SCRIPTEOF
chmod +x /lib/systemd/system-shutdown/pipower-shutdown
echo "Shutdown hook installed"

# Create service user
echo ""
echo "Step 6: Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /bin/false -G gpio,i2c,spi,bluetooth,video,netdev,dialout "$SERVICE_USER"
else
    usermod -aG video,netdev,dialout "$SERVICE_USER" || true
fi

# Create directories
echo ""
echo "Step 7: Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/captures"
mkdir -p "$INSTALL_DIR/signals/ir"
mkdir -p "$INSTALL_DIR/signals/subghz"
mkdir -p "$INSTALL_DIR/cards"
mkdir -p "$INSTALL_DIR/payloads"
mkdir -p "$INSTALL_DIR/logs"
mkdir -p "$INSTALL_DIR/data"

# Copy backend files
echo ""
echo "Step 8: Copying backend files..."
cp -r backend/* "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/setup-gadget.sh"

# Copy update script (lives in repo root, not backend/)
if [ -f "$SCRIPT_DIR/update.sh" ]; then
    cp "$SCRIPT_DIR/update.sh" "$INSTALL_DIR/"
    chmod +x "$INSTALL_DIR/update.sh"
fi

# Seed IR and BadUSB payloads (never overwrites existing files)
if [ -d "$SCRIPT_DIR/payloads/ir" ]; then
    mkdir -p "$INSTALL_DIR/payloads/ir"
    cp -n "$SCRIPT_DIR/payloads/ir/"*.json "$INSTALL_DIR/payloads/ir/" 2>/dev/null || true
fi
if [ -d "$SCRIPT_DIR/payloads/badusb" ]; then
    mkdir -p "$INSTALL_DIR/payloads/badusb"
    cp -n "$SCRIPT_DIR/payloads/badusb/"*.txt "$INSTALL_DIR/payloads/badusb/" 2>/dev/null || true
fi

# Set permissions
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"

# Create Python virtual environment
echo ""
echo "Step 9: Setting up Python environment..."
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Install pipower5 from local source (not available on PyPI)
if [ -d "/opt/pipower5" ]; then
    echo "Installing pipower5 from local source..."
    pip install /opt/pipower5/ 2>&1 | tail -3
fi

# Configure PWM fan on GPIO 12 & IR Transmitter/Receiver
echo ""
echo "Step 10: Configuring PWM fan (GPIO 12) & IR Transmitter/Receiver..."
# Remove any old simple gpio-fan overlays to avoid conflicts
sed -i '/^dtoverlay=gpio-fan/d' "$BOOT_CONFIG" 2>/dev/null || true
if ! grep -q '^dtoverlay=pwm-gpio-fan' "$BOOT_CONFIG" 2>/dev/null; then
    echo 'dtoverlay=pwm-gpio-fan,fan_gpio=12' >> "$BOOT_CONFIG"
fi
if ! grep -q '^dtoverlay=gpio-ir,' "$BOOT_CONFIG" 2>/dev/null; then
    echo 'dtoverlay=gpio-ir,gpio_pin=27' >> "$BOOT_CONFIG"
fi
if ! grep -q '^dtoverlay=gpio-ir-tx' "$BOOT_CONFIG" 2>/dev/null; then
    echo 'dtoverlay=gpio-ir-tx,gpio_pin=17' >> "$BOOT_CONFIG"
fi

# Configure hostapd and dnsmasq for AP mode
echo ""
echo "Step 11: Pinning WiFi interface names..."
# Without this udev rule, USB vs SDIO driver probe order at boot can swap
# wlan0/wlan1 assignments. The Alfa adapter might claim wlan0, leaving the
# internal WiFi as wlan1 — hostapd (configured for wlan0) then fails.
cat > /etc/udev/rules.d/70-persistent-wifi.rules << 'UDEVEOF'
# Pin internal Pi WiFi as wlan0 (Broadcom brcmfmac)
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="brcmfmac", NAME="wlan0"

# Pin Alfa USB adapter as wlan1 (Realtek rtl8821au)
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="rtl8821au", NAME="wlan1"
UDEVEOF

echo "Step 12: Configuring Wi-Fi Access Point (Chonky_Control)..."

# Create hostapd configuration
cat > /etc/hostapd/hostapd.conf << 'EOF'
interface=wlan0
driver=nl80211
ssid=Chonky_Control
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=chonky123
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Update hostapd defaults to point to config
if ! grep -q 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' /etc/default/hostapd 2>/dev/null; then
    echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd
fi

# Create dnsmasq configuration for AP mode
cat > /etc/dnsmasq.conf << 'EOF'
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
dhcp-option=3,192.168.4.1
dhcp-option=6,192.168.4.1
server=8.8.8.8
server=8.8.4.4
address=/chonkyflipper.pi/192.168.4.1
EOF

# Configure static IP for wlan0 via systemd service (interfaces.d not reliable on Kali)
cat > /etc/systemd/system/wlan0-static-ip.service << 'EOF'
[Unit]
Description=Set static IP on wlan0 for AP mode
After=network.target hostapd.service
Requires=hostapd.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/ip addr add 192.168.4.1/24 dev wlan0
ExecStartPost=/sbin/ip link set wlan0 up
ExecStop=/sbin/ip addr flush dev wlan0

[Install]
WantedBy=multi-user.target
EOF
systemctl enable wlan0-static-ip

# Install systemd service
echo ""
echo "Step 13: Installing systemd service..."
cat > /etc/systemd/system/chonkyflipper.service << 'EOF'
[Unit]
Description=ChonkyFlipper IoT Pentesting Backend
After=network.target

[Service]
Type=simple
User=chonky
Group=chonky
WorkingDirectory=/opt/chonkyflipper
Environment="PATH=/opt/chonkyflipper/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/opt/chonkyflipper/venv/bin/gunicorn -b 0.0.0.0:5000 -w 2 --access-logfile /opt/chonkyflipper/logs/access.log --error-logfile /opt/chonkyflipper/logs/error.log app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# BadUSB gadget service  --  runs setup-gadget.sh before the Flask backend starts
cat > /etc/systemd/system/chonky-gadget.service << 'EOF'
[Unit]
Description=ChonkyFlipper USB HID Gadget Setup
After=sysinit.target local-fs.target
Before=chonkyflipper.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/chonkyflipper/setup-gadget.sh

[Install]
WantedBy=multi-user.target
EOF

# Allow the service user to write to /dev/hidg0 without root
echo 'KERNEL=="hidg*", MODE="0666"' > /etc/udev/rules.d/99-chonky-hidg.rules

# Allow service user to run privileged operations without a password prompt
cat > /etc/sudoers.d/chonky-ops << 'EOFSUDOERS'
chonky ALL=(ALL) NOPASSWD: /sbin/shutdown
chonky ALL=(ALL) NOPASSWD: /opt/chonkyflipper/update.sh
chonky ALL=(ALL) NOPASSWD: /usr/sbin/iw dev wlan1 scan
chonky ALL=(ALL) NOPASSWD: /usr/sbin/wpa_cli -i wlan1 scan
chonky ALL=(ALL) NOPASSWD: /usr/sbin/wpa_cli -i wlan1 scan_results
chonky ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/wpa_supplicant/wpa_supplicant-wlan1.conf
chonky ALL=(ALL) NOPASSWD: /usr/bin/systemctl start wpa_supplicant@wlan1
chonky ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop wpa_supplicant@wlan1
chonky ALL=(ALL) NOPASSWD: /usr/bin/systemctl enable wpa_supplicant@wlan1
chonky ALL=(ALL) NOPASSWD: /usr/bin/systemctl disable wpa_supplicant@wlan1
chonky ALL=(ALL) NOPASSWD: /usr/sbin/ip addr flush dev wlan1
chonky ALL=(ALL) NOPASSWD: /usr/sbin/ip link set wlan1 up
chonky ALL=(ALL) NOPASSWD: /usr/sbin/i2cdetect -y 1
chonky ALL=(ALL) NOPASSWD: /usr/bin/rm -f /var/run/wpa_supplicant/wlan1
EOFSUDOERS
chmod 440 /etc/sudoers.d/chonky-ops

# Enable and start services
systemctl daemon-reload
systemctl enable chonkyflipper
systemctl enable chonky-gadget

# Start AP services (after reboot)
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq

# Deploy frontend via nginx
echo ""
echo "Step 14: Deploying frontend..."
mkdir -p /var/www/html
cp -r "$SCRIPT_DIR/frontend/"* /var/www/html/
cat > /etc/nginx/sites-available/chonky << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        root /var/www/html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:5000/api/;
        proxy_set_header Host $host;
    }
}
EOF
ln -sf /etc/nginx/sites-available/chonky /etc/nginx/sites-enabled/chonky
rm -f /etc/nginx/sites-enabled/default
systemctl enable nginx

# Copy maintenance-mode script
echo ""
echo "Copying maintenance mode script..."
cp "$SCRIPT_DIR/backend/maintenance-mode.sh" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/maintenance-mode.sh"

# Create git update helper (already copied from repo in Step 8)
# The update.sh is a tracked file in the repo and is deployed alongside backend files.
# It is invoked via: sudo /opt/chonkyflipper/update.sh
echo ""
echo "Verifying update script..."
if [ ! -f "$INSTALL_DIR/update.sh" ]; then
    echo "Warning: update.sh not found  --  update functionality will be unavailable."
else
    chmod +x "$INSTALL_DIR/update.sh"
    echo "Update script deployed."
fi

# Create settings file for maintenance network
mkdir -p "$INSTALL_DIR/config"
touch "$INSTALL_DIR/config/maintenance-network.conf"
chmod 600 "$INSTALL_DIR/config/maintenance-network.conf"

# Install MQTT broker (mosquitto) for Zigbee2MQTT
echo ""
echo "Step 15: Installing MQTT broker (mosquitto)..."
apt-get install -y mosquitto mosquitto-clients
systemctl enable mosquitto
systemctl start mosquitto

# Install Node.js (required by Zigbee2MQTT, minimum version 22)
echo ""
echo "Step 16: Installing Node.js..."
if command -v node &>/dev/null; then
    NODE_MAJOR=$(node --version | cut -d'.' -f1 | tr -d 'v')
else
    NODE_MAJOR=0
fi
if [ "$NODE_MAJOR" -lt 22 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs
fi

# Install Zigbee2MQTT
echo ""
echo "Step 17: Installing Zigbee2MQTT..."
if [ ! -d "/opt/zigbee2mqtt" ]; then
    git clone --depth 1 https://github.com/Koenkk/zigbee2mqtt.git /opt/zigbee2mqtt
fi
cd /opt/zigbee2mqtt

# Install pnpm (Zigbee2MQTT 2.x uses pnpm, not npm)
if ! command -v pnpm &>/dev/null; then
    npm install -g pnpm 2>&1 | tail -3
fi
pnpm install --frozen-lockfile 2>&1 | tail -5
cd "$INSTALL_DIR"

# Create Zigbee2MQTT data dir and default config (only if not already configured)
mkdir -p /opt/zigbee2mqtt/data
if [ ! -f /opt/zigbee2mqtt/data/configuration.yaml ]; then
    cat > /opt/zigbee2mqtt/data/configuration.yaml << 'EOF'
homeassistant: false
permit_join: false
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://localhost:1883
serial:
  port: /dev/ttyUSB0
  adapter: ember
advanced:
  log_level: warn
  pan_id: GENERATE
  network_key: GENERATE
frontend: false
EOF
fi

# Dedicated service user with dialout access (needed for /dev/ttyUSB0)
# Home dir set to /opt/zigbee2mqtt so pnpm has a writable cache location
if ! id zigbee2mqtt &>/dev/null; then
    useradd -r -s /bin/false -d /opt/zigbee2mqtt -G dialout zigbee2mqtt
fi
chown -R zigbee2mqtt:zigbee2mqtt /opt/zigbee2mqtt

# Allow chonky service user to manage the zigbee2mqtt service
cat >> /etc/sudoers.d/chonky-ops << 'EOFSUDOERS'
chonky ALL=(ALL) NOPASSWD: /usr/bin/systemctl start zigbee2mqtt
chonky ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop zigbee2mqtt
chonky ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart zigbee2mqtt
chonky ALL=(ALL) NOPASSWD: /usr/bin/systemctl status zigbee2mqtt
EOFSUDOERS

# Zigbee2MQTT systemd service
cat > /etc/systemd/system/zigbee2mqtt.service << 'EOF'
[Unit]
Description=Zigbee2MQTT
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
Environment=NODE_ENV=production
Environment=HOME=/opt/zigbee2mqtt
ExecStart=/usr/bin/node index.js
WorkingDirectory=/opt/zigbee2mqtt
Restart=on-failure
RestartSec=10s
User=zigbee2mqtt
Group=zigbee2mqtt
SupplementaryGroups=dialout

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
# Enable but do not start — requires Zigbee USB dongle to be present first
systemctl enable zigbee2mqtt

echo ""
echo "==================================================="
echo "  Installation Complete!"
echo "==================================================="
echo ""
echo "Next steps:"
echo "  1. Start services: sudo systemctl start chonkyflipper"
echo "  2. Check status:   sudo systemctl status chonkyflipper"
echo "  3. API available:  http://<pi-ip>:5000/api/status"
echo ""
echo "  4. Dashboard: http://192.168.4.1 (after reboot, connect to Chonky_Control)"
echo "  5. AP SSID: Chonky_Control / Password: chonky123"
echo "  6. Maintenance mode: sudo /opt/chonkyflipper/maintenance-mode.sh"
echo ""
echo "  Zigbee:"
echo "  7. Connect your Zigbee USB dongle (CC2531, SONOFF Zigbee 3.0, etc.)"
echo "  8. Verify serial port: ls /dev/ttyUSB* /dev/ttyACM*"
echo "     If not /dev/ttyUSB0, update: /opt/zigbee2mqtt/data/configuration.yaml"
echo "  9. Start Zigbee2MQTT: sudo systemctl start zigbee2mqtt"
echo "     API: GET /api/zigbee/devices  POST /api/zigbee/permit_join"
echo ""
echo "  NOTE: A reboot is required for I2C/SPI/fan/shutdown changes to take effect."
echo "  Run: sudo reboot"
echo ""
echo "Logs: /opt/chonkyflipper/logs/"
