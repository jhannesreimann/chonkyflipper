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

# Configure Pi 4 full power-off for PiPower5 safe shutdown
echo ""
echo "Step 4: Configuring Pi 4 shutdown behaviour for PiPower5..."
if ! grep -q 'power_off_on_halt=1' "$BOOT_CONFIG" 2>/dev/null; then
    echo 'power_off_on_halt=1' >> "$BOOT_CONFIG"
fi

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

# Create service user
echo ""
echo "Step 6: Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /bin/false -G gpio,i2c,spi,bluetooth,video "$SERVICE_USER"
else
    usermod -aG video "$SERVICE_USER" || true
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

# Copy backend files
echo ""
echo "Step 8: Copying backend files..."
cp -r backend/* "$INSTALL_DIR/"

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
echo "Step 11: Configuring Wi-Fi Access Point (Chonky_Control)..."

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
address=/chonkyflipper.local/192.168.4.1
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
echo "Step 12: Installing systemd service..."
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

# Enable and start services
systemctl daemon-reload
systemctl enable chonkyflipper

# Start AP services (after reboot)
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq

# Deploy frontend via nginx
echo ""
echo "Step 13: Deploying frontend..."
mkdir -p /var/www/html
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd)"
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

# Create git update helper
cat > "$INSTALL_DIR/update.sh" << 'EOFUPDATE'
#!/bin/bash
# ChonkyFlipper Update Script
# Run when in maintenance mode (with internet)

set -e

INSTALL_DIR="/opt/chonkyflipper"
REPO_DIR="/home/kali/chonkyflipper"

echo "Updating ChonkyFlipper..."

if ! ping -c 1 github.com &>/dev/null; then
    echo "Error: No internet connection. Switch to maintenance mode first."
    exit 1
fi

if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"
    git pull
    cp -r backend/* "$INSTALL_DIR/"
    cp -r frontend/* /var/www/html/
else
    echo "Error: git repository not found at $REPO_DIR"
    exit 1
fi

systemctl restart chonkyflipper
echo "Update complete."
EOFUPDATE
chmod +x "$INSTALL_DIR/update.sh"

# Create settings file for maintenance network
mkdir -p "$INSTALL_DIR/config"
touch "$INSTALL_DIR/config/maintenance-network.conf"
chmod 600 "$INSTALL_DIR/config/maintenance-network.conf"

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
echo "  NOTE: A reboot is required for I2C/SPI/fan/shutdown changes to take effect."
echo "  Run: sudo reboot"
echo ""
echo "Logs: /opt/chonkyflipper/logs/"
