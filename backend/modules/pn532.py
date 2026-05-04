#!/usr/bin/env python3
"""
PN532 Module - RFID/NFC Reader/Writer
I2C interface (can also use SPI or HSU)
Supports: Mifare Classic, Ultralight, DESFire, FeliCa
"""

import subprocess
import os
import json
import time
from datetime import datetime

class PN532Module:
    """PN532 NFC/RFID module via I2C, GPIO 2 (SDA) / GPIO 3 (SCL)"""
    
    def __init__(self, i2c_bus=1, address=0x24):
        self.i2c_bus = i2c_bus
        self.address = address
        self.cards_dir = '/opt/chonkyflipper/cards'
        os.makedirs(self.cards_dir, exist_ok=True)
    
    def _ensure_i2c(self):
        """Ensure I2C interface is enabled and device is detected"""
        try:
            # Check if I2C device exists
            result = subprocess.run(
                ['i2cdetect', '-y', str(self.i2c_bus)],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # Check for PN532 at expected address
            addr_hex = hex(self.address).replace('0x', '')
            if addr_hex in result.stdout or str(self.address) in result.stdout:
                return {'success': True, 'device': f'0x{addr_hex}'}
            
            return {
                'success': False,
                'error': f'PN532 not detected at I2C address 0x{addr_hex}',
                'hint': 'Check wiring and run: sudo i2cdetect -y 1'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'hint': 'Enable I2C with: sudo raspi-config'
            }
    
    def read_card(self, timeout=10):
        """
        Read NFC/RFID card data
        Returns UID, card type, and any stored data
        """
        # Check I2C
        i2c_check = self._ensure_i2c()
        if not i2c_check['success']:
            return i2c_check
        
        # Placeholder for actual PN532 reading
        # This would require:
        # 1. Send InListPassiveTarget command
        # 2. Wait for card detection
        # 3. Read UID
        # 4. Authenticate (if protected)
        # 5. Read data sectors
        
        return {
            'success': True,
            'status': 'placeholder - implement PN532 I2C communication',
            'uid': None,
            'card_type': None,
            'data': None,
            'timestamp': datetime.now().isoformat()
        }
    
    def write_card(self, uid=None, payload=None, sector=1):
        """
        Write data to NFC/RFID card
        uid: Target card UID (optional, for verification)
        payload: Data to write
        sector: Which sector/block to write (Mifare Classic)
        """
        i2c_check = self._ensure_i2c()
        if not i2c_check['success']:
            return i2c_check
        
        # TODO: Implement card writing
        # 1. Detect card
        # 2. Authenticate sector
        # 3. Write data blocks
        # 4. Verify write
        
        return {
            'success': True,
            'status': 'placeholder - implement PN532 write',
            'target_uid': uid,
            'sector': sector,
            'payload_size': len(payload) if payload else 0
        }
    
    def emulate_card(self, uid, card_type='MifareClassic'):
        """
        Emulate an NFC card (card emulation mode)
        Useful for testing readers/cloning
        """
        return {
            'success': False,
            'message': 'Card emulation requires PN532 firmware support',
            'uid': uid,
            'type': card_type
        }
    
    def save_card(self, uid, data, name=None):
        """Save card data to file for later use"""
        if name is None:
            name = f'card_{uid}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        
        filepath = os.path.join(self.cards_dir, f'{name}.json')
        
        card_data = {
            'name': name,
            'uid': uid,
            'timestamp': datetime.now().isoformat(),
            'data': data,
            'type': 'unknown'
        }
        
        with open(filepath, 'w') as f:
            json.dump(card_data, f, indent=2)
        
        return {
            'success': True,
            'name': name,
            'filepath': filepath,
            'uid': uid
        }
    
    def list_saved_cards(self):
        """List all saved card data"""
        cards = []
        try:
            for filename in os.listdir(self.cards_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(self.cards_dir, filename)
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                        cards.append({
                            'name': data.get('name', filename),
                            'uid': data.get('uid'),
                            'timestamp': data.get('timestamp'),
                            'type': data.get('type', 'unknown')
                        })
        except Exception as e:
            return {'error': str(e)}
        
        return {'cards': cards}
    
    def clone_card(self, source_uid, target_card=None):
        """
        Clone card data to a writable card
        source_uid: Card to clone
        target_card: Writable card (UID-changeable Chinese magic card)
        """
        # Mifare Classic "Chinese magic cards" allow UID changes
        # This requires special write commands
        
        return {
            'success': False,
            'message': 'Card cloning requires special UID-changeable cards',
            'source': source_uid,
            'target': target_card
        }
    
    def detect_card_type(self, atqa, sak):
        """
        Detect card type from ATQA and SAK values
        ATQA: Answer To Request (Type A)
        SAK: Select Acknowledge
        """
        # Common card type detection
        type_map = {
            '0004': 'Mifare Classic 1K',
            '0002': 'Mifare Classic 4K',
            '0044': 'Mifare Ultralight',
            '0344': 'Mifare DESFire',
            '0003': 'Mifare Ultralight C',
        }
        
        atqa_str = f'{atqa:04x}' if isinstance(atqa, int) else atqa
        
        return type_map.get(atqa_str, 'Unknown')
