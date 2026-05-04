#!/bin/bash
################################################################################
# ChonkyFlipper Maintenance Mode
# Switch from AP mode to Client mode for updates
################################################################################

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="/opt/chonkyflipper/config/maintenance-network.conf"

show_help() {
    echo "Usage: sudo ./maintenance-mode.sh [command]"
    echo ""
    echo "Commands:"
    echo "  enable <SSID> <PASSWORD>  - Enable client mode, connect to WiFi"
    echo "  disable                   - Return to AP mode (Chonky_Control)"
    echo "  status                    - Show current network mode"
    echo "  usb-tether                - Enable USB-C Ethernet (connect to laptop)"
    echo ""
    echo "Examples:"
    echo "  sudo ./maintenance-mode.sh enable MyHotspot mypassword123"
    echo "  sudo ./maintenance-mode.sh usb-tether"
    echo "  sudo ./maintenance-mode.sh disable"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "Error: Please run as root: sudo ./maintenance-mode.sh"
        exit 1
    fi
}

save_network() {
    local ssid="$1"
    local password="$2"
    cat > "$CONFIG_FILE" << EOF
SSID=$ssid
PASSWORD=$password
EOF
    chmod 600 "$CONFIG_FILE"
}

get_ssid() {
    grep '^SSID=' "$CONFIG_FILE" 2>/dev/null | cut -d= -f2
}

get_password() {
    grep '^PASSWORD=' "$CONFIG_FILE" 2>/dev/null | cut -d= -f2
}

stop_ap_services() {
    echo "🛑 Stopping ChonkyFlipper AP services..."
    systemctl stop hostapd 2>/dev/null || true
    systemctl stop dnsmasq 2>/dev/null || true
    systemctl disable hostapd 2>/dev/null || true
    systemctl disable dnsmasq 2>/dev/null || true
    
    # Release wlan0 if it was managed by hostapd
    ip addr flush dev wlan0 2>/dev/null || true
}

start_ap_services() {
    echo "Starting ChonkyFlipper AP mode (Chonky_Control)..."
    systemctl enable hostapd 2>/dev/null || true
    systemctl enable dnsmasq 2>/dev/null || true
    systemctl start hostapd 2>/dev/null || true
    systemctl start dnsmasq 2>/dev/null || true
}

enable_client_mode() {
    local ssid="$1"
    local password="$2"
    
    if [ -z "$ssid" ] || [ -z "$password" ]; then
        # Try to load from saved config
        ssid=$(get_ssid)
        password=$(get_password)
        
        if [ -z "$ssid" ]; then
            echo "Error: No SSID provided and no saved network found."
            echo "Usage: sudo ./maintenance-mode.sh enable <SSID> <PASSWORD>"
            exit 1
        fi
        
        echo "Using saved network: $ssid"
    else
        save_network "$ssid" "$password"
    fi
    
    stop_ap_services
    
    echo "Connecting to: $ssid"
    
    # Use wpa_supplicant to connect
    cat > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf << EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=DE

network={
    ssid="$ssid"
    psk="$password"
    key_mgmt=WPA-PSK
}
EOF
    
    chmod 600 /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
    
    # Enable systemd-networkd for DHCP client
    systemctl enable systemd-networkd 2>/dev/null || true
    systemctl start systemd-networkd 2>/dev/null || true
    
    # Start wpa_supplicant
    systemctl enable wpa_supplicant@wlan0 2>/dev/null || true
    systemctl stop wpa_supplicant@wlan0 2>/dev/null || true
    systemctl start wpa_supplicant@wlan0
    
    # Wait for connection
    echo "Waiting for connection..."
    for i in {1..30}; do
        if ip addr show wlan0 | grep -q "inet "; then
            echo "Connected!"
            ip addr show wlan0 | grep "inet " | head -1
            echo ""
            echo "You can now:"
            echo "  - apt update && apt upgrade"
            echo "  - git pull"
            echo "  - Or install new packages"
            echo ""
            echo "To return to AP mode: sudo ./maintenance-mode.sh disable"
            return 0
        fi
        sleep 1
    done
    
    echo "Warning: Connection timeout. Check SSID/password."
    return 1
}

disable_client_mode() {
    echo "Returning to AP mode..."
    
    # Stop client mode
    systemctl stop wpa_supplicant@wlan0 2>/dev/null || true
    systemctl disable wpa_supplicant@wlan0 2>/dev/null || true
    
    ip addr flush dev wlan0 2>/dev/null || true
    
    start_ap_services
    
    echo "AP mode restored. Connect to: Chonky_Control"
    echo "Dashboard: http://192.168.4.1"
}

enable_usb_tether() {
    echo "Enabling USB-C Ethernet (USB Gadget Mode)..."
    echo "Note: This requires USB Gadget drivers enabled in kernel."
    echo "Connect Pi to laptop via USB-C data cable."
    echo ""
    
    # Load gadget modules
    modprobe libcomposite 2>/dev/null || true
    
    # Create USB Ethernet gadget
    mkdir -p /sys/kernel/config/usb_gadget/chonky
    cd /sys/kernel/config/usb_gadget/chonky
    
    echo 0x1d6b > idVendor   # Linux Foundation
    echo 0x0104 > idProduct  # Multifunction Composite Gadget
    echo 0x0100 > bcdDevice
    echo 0x0200 > bcdUSB
    
    mkdir -p strings/0x409
    echo "1234567890" > strings/0x409/serialnumber
    echo "ChonkyFlipper" > strings/0x409/manufacturer
    echo "Chonky USB Ethernet" > strings/0x409/product
    
    mkdir -p configs/c.1/strings/0x409
    echo "USB Ethernet" > configs/c.1/strings/0x409/configuration
    
    mkdir -p functions/ecm.usb0
    echo "02:00:00:00:00:01" > functions/ecm.usb0/host_addr
    echo "02:00:00:00:00:02" > functions/ecm.usb0/dev_addr
    
    ln -s functions/ecm.usb0 configs/c.1/
    
    # Bind to USB device (varies by Pi model)
    # For Pi 4: dwc2 or xhci-hcd
    if [ -d /sys/class/udc/dwc2 ]; then
        echo "dwc2" > UDC
    elif [ -d /sys/class/udc/fe980000.usb ]; then
        echo "fe980000.usb" > UDC
    fi
    
    # Configure IP
    ip addr add 10.55.0.1/24 dev usb0 2>/dev/null || true
    ip link set usb0 up
    
    # Start DHCP server for USB interface
    dnsmasq --interface=usb0 --bind-interfaces --dhcp-range=10.55.0.2,10.55.0.10,255.255.255.0,1h 2>/dev/null || true
    
    echo "USB Ethernet enabled."
    echo "Pi IP: 10.55.0.1"
    echo "Laptop should get IP 10.55.0.2-10"
    echo ""
    echo "SSH from laptop: ssh kali@10.55.0.1"
    echo ""
    echo "To share laptop's internet with Pi:"
    echo "On laptop (Linux): sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE"
}

show_status() {
    echo "ChonkyFlipper Network Status"
    echo "================================"
    echo ""
    
    # Check AP services
    if systemctl is-active --quiet hostapd; then
        echo "AP Mode: ACTIVE (Chonky_Control)"
        echo "   SSID: Chonky_Control"
        echo "   IP: 192.168.4.1"
    else
        echo "AP Mode: inactive"
    fi
    echo ""
    
    # Check client mode
    if systemctl is-active --quiet wpa_supplicant@wlan0 2>/dev/null; then
        echo "Client Mode: ACTIVE"
        ip addr show wlan0 | grep "inet " | head -1
    else
        echo "Client Mode: inactive"
    fi
    echo ""
    
    # Check interfaces
    echo "Interfaces:"
    ip addr | grep -E "^[0-9]|inet " | head -20
    echo ""
    
    # Check if internet is reachable
    if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
        echo "Internet: REACHABLE"
    else
        echo "Internet: NOT reachable"
    fi
    echo ""
    
    # Saved network
    if [ -f "$CONFIG_FILE" ]; then
        echo "Saved network: $(get_ssid)"
    fi
}

# Main
case "${1:-}" in
    enable)
        check_root
        enable_client_mode "$2" "$3"
        ;;
    disable)
        check_root
        disable_client_mode
        ;;
    usb-tether)
        check_root
        enable_usb_tether
        ;;
    status)
        show_status
        ;;
    *)
        show_help
        ;;
esac
