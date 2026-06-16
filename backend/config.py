#!/usr/bin/env python3
"""
ChonkyFlipper central configuration.
All paths and constants live here instead of being hardcoded in modules.
"""

INSTALL_DIR = '/opt/chonkyflipper'
VENV_DIR = f'{INSTALL_DIR}/venv'
SIGNALS_IR = f'{INSTALL_DIR}/signals/ir'
SIGNALS_SUBGHZ = f'{INSTALL_DIR}/signals/subghz'
CARDS_DIR = f'{INSTALL_DIR}/cards'
PAYLOADS_DIR = f'{INSTALL_DIR}/payloads'
DATA_DIR = f'{INSTALL_DIR}/data'
CAPTURES_DIR = f'{INSTALL_DIR}/captures'
LOGS_DIR = f'{INSTALL_DIR}/logs'
CONFIG_DIR = f'{INSTALL_DIR}/config'
VERSION_FILE = f'{INSTALL_DIR}/VERSION'

IR_DB_PATH = f'{DATA_DIR}/ir_payloads.db'
IRDB_REPO_DIR = f'{DATA_DIR}/irdb'

REPO_DIR = '/home/kali/chonkyflipper'
FRONTEND_DIR = '/var/www/html'

# Zigbee2MQTT
Z2M_DIR = '/opt/zigbee2mqtt'
Z2M_USB_DEVICE = '/dev/ttyUSB0'
MQTT_BROKER = 'localhost'
MQTT_PORT = 1883

# Service user for sudo -n commands
SERVICE_USER = 'chonky'

# Hardware detection paths
WLAN1_PATH = '/sys/class/net/wlan1'
HCI0_PATH = '/sys/class/bluetooth/hci0'
LIRC0_PATH = '/dev/lirc0'
SPI0_PATH = '/sys/bus/spi/devices/spi0.0'
HIDG0_PATH = '/dev/hidg0'
