#!/bin/bash
# USB HID Keyboard Gadget Setup
# Configures /dev/hidg0 via Linux configfs for BadUSB operation.
# Run once at boot by chonky-gadget.service.

set -e

modprobe libcomposite 2>/dev/null || true

GADGET=/sys/kernel/config/usb_gadget/chonky

# Tear down any previous gadget state cleanly
if [ -d "$GADGET" ]; then
    echo "" > "$GADGET/UDC" 2>/dev/null || true
    rm -rf "$GADGET"
fi

mkdir -p "$GADGET"
cd "$GADGET"

# USB device identifiers (generic Linux HID composite gadget)
echo 0x1d6b > idVendor
echo 0x0104 > idProduct
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "CF00000001"    > strings/0x409/serialnumber
echo "ChonkyFlipper" > strings/0x409/manufacturer
echo "HID Keyboard"  > strings/0x409/product

mkdir -p configs/c.1/strings/0x409
echo "HID Keyboard" > configs/c.1/strings/0x409/configuration
echo 250            > configs/c.1/MaxPower

mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/protocol       # Keyboard
echo 1 > functions/hid.usb0/subclass       # Boot Interface
echo 8 > functions/hid.usb0/report_length  # 8-byte reports

# Standard boot-compatible keyboard HID report descriptor (63 bytes)
printf '\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' \
    > functions/hid.usb0/report_desc

ln -sf "$GADGET/functions/hid.usb0" "$GADGET/configs/c.1/"

UDC=$(ls /sys/class/udc 2>/dev/null | head -n1)
if [ -n "$UDC" ]; then
    echo "$UDC" > UDC
    echo "[+] BadUSB gadget active on $UDC -> /dev/hidg0"
else
    echo "[-] No USB Device Controller found."
    echo "    Check that dtoverlay=dwc2 is in /boot/firmware/config.txt and reboot."
    exit 1
fi
