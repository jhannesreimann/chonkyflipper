#!/usr/bin/env python3
"""
ChonkyFlipper Backend - Flask API Server
Mobile IoT Pentesting Rig Controller
"""

from flask import Flask
from flask_cors import CORS
from routes import register_blueprints

app = Flask(__name__)
CORS(app)

# Lazy-loaded hardware module instances
_modules = {}


def get_module(name):
    """Lazy-load and return a hardware module instance."""
    if name not in _modules:
        module_map = {
            'wifi': 'modules.wifi.WiFiModule',
            'bluetooth': 'modules.bluetooth.BluetoothModule',
            'ir': 'modules.ir.IRModule',
            'cc1101': 'modules.cc1101.CC1101Module',
            'pn532': 'modules.pn532.PN532Module',
            'badusb': 'modules.badusb.BadUSBModule',
            'zigbee': 'modules.zigbee.ZigbeeModule',
        }
        mod_path, cls_name = module_map[name].rsplit('.', 1)
        mod = __import__(mod_path, fromlist=[cls_name])
        _modules[name] = getattr(mod, cls_name)()
    return _modules[name]


# Register all API route blueprints
register_blueprints(app)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
