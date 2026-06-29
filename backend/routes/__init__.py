"""
Blueprint registration. Import and register all route blueprints.
"""

from .status import bp as status_bp
from .wifi import bp as wifi_bp
from .bluetooth import bp as bluetooth_bp
from .ir import bp as ir_bp
from .subghz import bp as subghz_bp
from .nfc import bp as nfc_bp
from .badusb import bp as badusb_bp
from .zigbee import bp as zigbee_bp
from .zigbee_audit import bp as zigbee_audit_bp
from .network import bp as network_bp
from .loot import bp as loot_bp


def register_blueprints(app):
    """Register all route blueprints on the Flask app."""
    for bp in (status_bp, wifi_bp, bluetooth_bp, ir_bp, subghz_bp,
               nfc_bp, badusb_bp, zigbee_bp, zigbee_audit_bp,
               network_bp, loot_bp):
        app.register_blueprint(bp)
