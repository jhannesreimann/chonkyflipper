"""
Central hardware-module factory.

Route blueprints call get_module(name) instead of importing each hardware
module class directly. Instances are created lazily on first use and then
cached for the lifetime of the worker process, so a module that keeps state
(the Zigbee MQTT subscription, the Bluetooth spoof daemon, the advert logger)
survives across requests.
"""

import sys
import importlib

from config import INSTALL_DIR

# The backend package is deployed to INSTALL_DIR on the Pi. Make sure its
# modules are importable no matter what working directory the worker starts in.
if INSTALL_DIR not in sys.path:
    sys.path.insert(0, INSTALL_DIR)

_MODULE_CLASSES = {
    'wifi': 'modules.wifi.WiFiModule',
    'bluetooth': 'modules.bluetooth.BluetoothModule',
    'ir': 'modules.ir.IRModule',
    'cc1101': 'modules.cc1101.CC1101Module',
    'pn532': 'modules.pn532.PN532Module',
    'badusb': 'modules.badusb.BadUSBModule',
    'zigbee': 'modules.zigbee.ZigbeeModule',
    'zigbee_audit': 'modules.zigbee_audit.ZigbeeAuditModule',
}

_instances = {}


def get_module(name):
    """Return the cached hardware-module instance for name, creating it on first use."""
    if name not in _instances:
        try:
            target = _MODULE_CLASSES[name]
        except KeyError:
            raise KeyError(f'unknown hardware module: {name}')
        mod_path, cls_name = target.rsplit('.', 1)
        mod = importlib.import_module(mod_path)
        _instances[name] = getattr(mod, cls_name)()
    return _instances[name]
