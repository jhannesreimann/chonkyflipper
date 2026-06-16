# ChonkyFlipper Backend Modules
# IoT Pentesting Hardware Controllers
#
# Imports here are LAZY -- we do not eagerly import modules that require
# hardware-specific libraries (spidev, board, adafruit_pn532, RPi.GPIO).
# The get_module() factory in app.py handles instantiation on first use.
#
# Module files can still be imported directly when you know the hardware is
# present (e.g. from within the venv on the Pi):
#   from modules.wifi import WiFiModule
#   from modules.bluetooth import BluetoothModule
#   from modules.ir import IRModule
#   from modules.cc1101 import CC1101Module
#   from modules.pn532 import PN532Module
#   from modules.badusb import BadUSBModule
#   from modules.zigbee import ZigbeeModule

__all__ = [
    'WiFiModule',
    'BluetoothModule',
    'IRModule',
    'CC1101Module',
    'PN532Module',
    'BadUSBModule',
    'ZigbeeModule',
]
