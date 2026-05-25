#!/usr/bin/env python3
"""
PN532 Module - RFID/NFC Reader/Writer
I2C interface, using adafruit-circuitpython-pn532
Supports: Mifare Classic, Ultralight, DESFire, FeliCa
"""

import os
import json
import time
from datetime import datetime
import board
import busio
from adafruit_pn532.i2c import PN532_I2C

class PN532Module:
    """PN532 NFC/RFID module via I2C, GPIO 2 (SDA) / GPIO 3 (SCL)"""
    
    def __init__(self, i2c_bus=1, address=0x24):
        self.i2c_bus = i2c_bus
        self.address = address
        self.cards_dir = '/opt/chonkyflipper/cards'
        os.makedirs(self.cards_dir, exist_ok=True)
        self.pn532 = None
        self._initialized = False
    
    def _init_sensor(self):
        """Lazy load the PN532 sensor only when needed"""
        if self._initialized:
            return True
        try:
            # Initialize I2C and PN532
            i2c = busio.I2C(board.SCL, board.SDA)
            self.pn532 = PN532_I2C(i2c, address=self.address)
            self.pn532.SAM_configuration()
            self._initialized = True
            return True
        except Exception as e:
            print(f"[-] PN532 initialization failed: {e}")
            return False
    
    def read_card(self, timeout=10):
        """
        Read NFC/RFID card data
        Returns UID, card type, and any stored data
        """
        if not self._init_sensor():
            return {
                'success': False,
                'error': 'PN532 could not be initialized. Check I2C bus wiring and permissions.'
            }
        
        try:
            # Poll for card up to timeout
            uid = self.pn532.read_passive_target(timeout=0.5)
            start_time = time.time()
            while uid is None and (time.time() - start_time) < timeout:
                uid = self.pn532.read_passive_target(timeout=0.5)
                time.sleep(0.1)
                
            if uid is not None:
                uid_hex = ''.join([f'{x:02x}' for x in uid])
                card_type = "Mifare Classic" if len(uid) == 4 else "NFC Tag"
                
                # Attempt to read sector 1 block 4 for extra data
                block_data = None
                try:
                    key = b'\xFF\xFF\xFF\xFF\xFF\xFF'
                    if len(uid) == 4:
                        if self.pn532.mifare_classic_authenticate_block(
                            uid, block_number=4, key_number=0x60, key=key
                        ):
                            data = self.pn532.mifare_classic_read_block(4)
                            if data:
                                block_data = data.hex()
                except Exception:
                    pass

                result = {
                    'success': True,
                    'uid': uid_hex,
                    'card_type': card_type,
                    'block_data': block_data,
                    'timestamp': datetime.now().isoformat()
                }
                
                # Save card to file
                self.save_card(uid_hex, {'block_4': block_data} if block_data else {}, name=f"scanned_{uid_hex}")
                return result
                
            return {
                'success': False,
                'error': 'No card detected within timeout'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Error reading card: {str(e)}'
            }
    
    def write_card(self, uid=None, payload=None, sector=1, block=4):
        """
        Write data to NFC/RFID card
        uid: Target card UID (optional, for verification)
        payload: Data to write (hex string or bytes)
        sector: Which sector/block to write (Mifare Classic)
        """
        if not self._init_sensor():
            return {
                'success': False,
                'error': 'PN532 could not be initialized. Check I2C bus wiring.'
            }
            
        if not payload:
            return {
                'success': False,
                'error': 'Payload data is required'
            }
            
        try:
            # Parse payload
            if isinstance(payload, str):
                try:
                    payload_bytes = bytes.fromhex(payload)
                except ValueError:
                    payload_bytes = payload.encode('utf-8')
            else:
                payload_bytes = bytes(payload)
                
            if len(payload_bytes) < 16:
                payload_bytes = payload_bytes + b'\x00' * (16 - len(payload_bytes))
            elif len(payload_bytes) > 16:
                payload_bytes = payload_bytes[:16]
                
            # Read UID first
            detected_uid = self.pn532.read_passive_target(timeout=5.0)
            if detected_uid is None:
                return {
                    'success': False,
                    'error': 'No card detected to write to'
                }
                
            detected_uid_hex = ''.join([f'{x:02x}' for x in detected_uid])
            if uid and detected_uid_hex != uid:
                return {
                    'success': False,
                    'error': f'UID mismatch! Target card {uid} expected, but detected {detected_uid_hex}'
                }
                
            # Authenticate and write
            key = b'\xFF\xFF\xFF\xFF\xFF\xFF'
            authenticated = self.pn532.mifare_classic_authenticate_block(
                detected_uid, block_number=block, key_number=0x60, key=key
            )
            
            if not authenticated:
                return {
                    'success': False,
                    'error': f'Failed to authenticate block {block} with default Key A'
                }
                
            self.pn532.mifare_classic_write_block(block, payload_bytes)
            verified_data = self.pn532.mifare_classic_read_block(block)
            
            return {
                'success': True,
                'status': 'Write successful',
                'target_uid': detected_uid_hex,
                'block_written': block,
                'payload_size': len(payload_bytes),
                'verified': verified_data == payload_bytes
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Error writing card: {str(e)}'
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
