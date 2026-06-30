#!/usr/bin/env python3
"""
IR Payload Database -- SQLite storage for IR signal library.
Provides hierarchical browsing (brands -> devices -> buttons) and raw signal retrieval.
"""

import sqlite3
import os
import json
import time


class IRPayloadDB:
    """SQLite-backed IR payload database."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path=None):
        if db_path is None:
            candidates = [
                '/opt/chonkyflipper/data/ir_payloads.db',
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             '..', 'data', 'ir_payloads.db'),
            ]
            db_path = candidates[0]
            for p in candidates:
                parent = os.path.dirname(p)
                if os.path.isdir(parent):
                    db_path = p
                    break

        self.db_path = db_path
        self._conn = None

    def _connect(self):
        if self._conn is not None:
            return self._conn
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.row_factory = sqlite3.Row
        self._conn = conn
        return conn

    def init_db(self):
        """Create tables and seed with legacy JSON payloads if empty."""
        conn = self._connect()
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS brands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                device_type TEXT DEFAULT '',
                icon TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_id INTEGER NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                device_type TEXT DEFAULT '',
                source_file TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(brand_id, slug)
            );

            CREATE TABLE IF NOT EXISTS buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                button_id TEXT NOT NULL,
                label TEXT NOT NULL,
                protocol TEXT DEFAULT '',
                address INTEGER,
                command INTEGER,
                address_hex TEXT DEFAULT '',
                command_hex TEXT DEFAULT '',
                frequency INTEGER DEFAULT 38000,
                duty_cycle REAL DEFAULT 0.33,
                raw_pulses TEXT DEFAULT '',
                raw_spaces TEXT DEFAULT '',
                protocol_hint TEXT DEFAULT '',
                header_pulse INTEGER,
                header_space INTEGER,
                unit_pulse INTEGER DEFAULT 560,
                unit_space_0 INTEGER DEFAULT 560,
                unit_space_1 INTEGER DEFAULT 1690,
                samsung32 INTEGER DEFAULT 0,
                sony_bits INTEGER,
                rc5_address INTEGER,
                source_file TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(device_id, button_id)
            );

            CREATE INDEX IF NOT EXISTS idx_buttons_label ON buttons(label);
            CREATE INDEX IF NOT EXISTS idx_buttons_protocol ON buttons(protocol);
            CREATE INDEX IF NOT EXISTS idx_devices_brand ON devices(brand_id);

            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        ''')

        # Apply schema version if empty
        cur = conn.execute('SELECT COUNT(*) FROM schema_version')
        if cur.fetchone()[0] == 0:
            conn.execute('INSERT INTO schema_version (version) VALUES (?)',
                         (self.SCHEMA_VERSION,))
            conn.commit()

        return {'success': True, 'db_path': self.db_path}

    # --- Brands ----------------------------------------------

    def get_brands(self, device_type=None):
        """Return all brands with device counts."""
        conn = self._connect()
        if device_type:
            rows = conn.execute('''
                SELECT b.id, b.name, b.slug, b.device_type, b.icon,
                       COUNT(d.id) as device_count
                FROM brands b
                LEFT JOIN devices d ON d.brand_id = b.id
                WHERE b.device_type = ? OR b.device_type = '' OR b.device_type = 'all'
                GROUP BY b.id
                ORDER BY b.name
            ''', (device_type,)).fetchall()
        else:
            rows = conn.execute('''
                SELECT b.id, b.name, b.slug, b.device_type, b.icon,
                       COUNT(d.id) as device_count
                FROM brands b
                LEFT JOIN devices d ON d.brand_id = b.id
                GROUP BY b.id
                ORDER BY b.name
            ''').fetchall()
        return [dict(r) for r in rows]

    def get_brand_by_slug(self, slug):
        """Get a single brand by slug."""
        conn = self._connect()
        row = conn.execute('SELECT * FROM brands WHERE slug = ?', (slug,)).fetchone()
        return dict(row) if row else None

    def insert_brand(self, name, slug=None, device_type='', icon=''):
        """Insert or ignore a brand. Returns brand id."""
        conn = self._connect()
        if slug is None:
            slug = name.lower().replace(' ', '_').replace('-', '_')
        conn.execute('''
            INSERT OR IGNORE INTO brands (name, slug, device_type, icon)
            VALUES (?, ?, ?, ?)
        ''', (name, slug, device_type, icon))
        conn.commit()
        row = conn.execute('SELECT id FROM brands WHERE slug = ?', (slug,)).fetchone()
        return row['id'] if row else None

    # --- Devices ---------------------------------------------

    def get_devices(self, brand_slug):
        """Return all devices for a brand with button counts."""
        conn = self._connect()
        rows = conn.execute('''
            SELECT d.id, d.name, d.slug, d.device_type, d.source_file,
                   d.notes, COUNT(b.id) as button_count
            FROM devices d
            JOIN brands br ON br.id = d.brand_id
            LEFT JOIN buttons b ON b.device_id = d.id
            WHERE br.slug = ?
            GROUP BY d.id
            ORDER BY d.name
        ''', (brand_slug,)).fetchall()
        return [dict(r) for r in rows]

    def get_device(self, device_id):
        """Get a single device with its brand info."""
        conn = self._connect()
        row = conn.execute('''
            SELECT d.*, br.name as brand_name, br.slug as brand_slug
            FROM devices d
            JOIN brands br ON br.id = d.brand_id
            WHERE d.id = ?
        ''', (device_id,)).fetchone()
        return dict(row) if row else None

    def insert_device(self, brand_id, name, slug=None, device_type='',
                      source_file='', notes=''):
        """Insert or ignore a device. Returns device id."""
        conn = self._connect()
        if slug is None:
            slug = name.lower().replace(' ', '_').replace('-', '_').replace('/', '_')
        conn.execute('''
            INSERT OR IGNORE INTO devices (brand_id, name, slug, device_type, source_file, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (brand_id, name, slug, device_type, source_file, notes))
        conn.commit()
        row = conn.execute(
            'SELECT id FROM devices WHERE brand_id = ? AND slug = ?',
            (brand_id, slug)
        ).fetchone()
        return row['id'] if row else None

    # --- Buttons ---------------------------------------------

    def get_buttons(self, device_id):
        """Return all buttons for a device (metadata only, no raw data)."""
        conn = self._connect()
        rows = conn.execute('''
            SELECT id, button_id, label, protocol, protocol_hint,
                   address, command, address_hex, command_hex,
                   frequency, duty_cycle
            FROM buttons
            WHERE device_id = ?
            ORDER BY label
        ''', (device_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_button_raw(self, button_id):
        """Get a single button with its raw pulse/space data for transmission."""
        conn = self._connect()
        row = conn.execute('''
            SELECT b.*, d.name as device_name, br.name as brand_name,
                   br.slug as brand_slug, d.slug as device_slug
            FROM buttons b
            JOIN devices d ON d.id = b.device_id
            JOIN brands br ON br.id = d.brand_id
            WHERE b.id = ?
        ''', (button_id,)).fetchone()
        if not row:
            return None

        btn = dict(row)

        # Parse raw data from JSON if stored
        if btn.get('raw_pulses'):
            try:
                btn['raw_pulses'] = json.loads(btn['raw_pulses'])
            except (json.JSONDecodeError, TypeError):
                btn['raw_pulses'] = []
        if btn.get('raw_spaces'):
            try:
                btn['raw_spaces'] = json.loads(btn['raw_spaces'])
            except (json.JSONDecodeError, TypeError):
                btn['raw_spaces'] = []

        return btn

    def get_button_by_device_and_id(self, device_id, button_id_str):
        """Look up a button by device_id and its string button_id."""
        conn = self._connect()
        row = conn.execute(
            'SELECT id FROM buttons WHERE device_id = ? AND button_id = ?',
            (device_id, button_id_str)
        ).fetchone()
        if not row:
            return None
        return self.get_button_raw(row['id'])

    def insert_button(self, device_id, button_id, label, protocol='',
                      address=None, command=None,
                      address_hex='', command_hex='',
                      frequency=38000, duty_cycle=0.33,
                      raw_pulses=None, raw_spaces=None,
                      protocol_hint='', header_pulse=None, header_space=None,
                      unit_pulse=560, unit_space_0=560, unit_space_1=1690,
                      samsung32=0, sony_bits=None, rc5_address=None,
                      source_file='', notes=''):
        """Insert or replace a button. Returns button id."""
        conn = self._connect()

        raw_p_str = json.dumps(raw_pulses) if raw_pulses else ''
        raw_s_str = json.dumps(raw_spaces) if raw_spaces else ''

        conn.execute('''
            INSERT OR REPLACE INTO buttons
            (device_id, button_id, label, protocol, address, command,
             address_hex, command_hex, frequency, duty_cycle,
             raw_pulses, raw_spaces, protocol_hint,
             header_pulse, header_space, unit_pulse, unit_space_0, unit_space_1,
             samsung32, sony_bits, rc5_address, source_file, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (device_id, button_id, label, protocol, address, command,
              address_hex, command_hex, frequency, duty_cycle,
              raw_p_str, raw_s_str, protocol_hint,
              header_pulse, header_space, unit_pulse, unit_space_0, unit_space_1,
              samsung32, sony_bits, rc5_address, source_file, notes))
        conn.commit()

        row = conn.execute(
            'SELECT id FROM buttons WHERE device_id = ? AND button_id = ?',
            (device_id, button_id)
        ).fetchone()
        return row['id'] if row else None

    # --- Search ----------------------------------------------

    def search(self, query):
        """Search across brands, devices, and button labels."""
        conn = self._connect()
        like = f'%{query}%'

        brand_rows = conn.execute('''
            SELECT 'brand' as type, id, name, slug, device_type,
                   (SELECT COUNT(*) FROM devices WHERE brand_id = brands.id) as count
            FROM brands
            WHERE name LIKE ? OR slug LIKE ?
            LIMIT 20
        ''', (like, like)).fetchall()

        device_rows = conn.execute('''
            SELECT 'device' as type, d.id, d.name, d.slug, d.device_type,
                   br.name as brand_name, br.slug as brand_slug,
                   (SELECT COUNT(*) FROM buttons WHERE device_id = d.id) as count
            FROM devices d
            JOIN brands br ON br.id = d.brand_id
            WHERE d.name LIKE ? OR br.name LIKE ?
            LIMIT 30
        ''', (like, like)).fetchall()

        button_rows = conn.execute('''
            SELECT 'button' as type, b.id, b.label as name, b.button_id as slug,
                   b.protocol, d.name as device_name, br.name as brand_name
            FROM buttons b
            JOIN devices d ON d.id = b.device_id
            JOIN brands br ON br.id = d.brand_id
            WHERE b.label LIKE ? OR b.button_id LIKE ?
            LIMIT 50
        ''', (like, like)).fetchall()

        return {
            'brands': [dict(r) for r in brand_rows],
            'devices': [dict(r) for r in device_rows],
            'buttons': [dict(r) for r in button_rows]
        }

    # --- Stats -----------------------------------------------

    def get_stats(self):
        """Return database statistics."""
        conn = self._connect()
        brand_count = conn.execute('SELECT COUNT(*) FROM brands').fetchone()[0]
        device_count = conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
        button_count = conn.execute('SELECT COUNT(*) FROM buttons').fetchone()[0]

        proto_rows = conn.execute('''
            SELECT protocol, COUNT(*) as cnt FROM buttons
            WHERE protocol != ''
            GROUP BY protocol ORDER BY cnt DESC
        ''').fetchall()

        return {
            'brands': brand_count,
            'devices': device_count,
            'buttons': button_count,
            'protocols': {r['protocol']: r['cnt'] for r in proto_rows}
        }

    # --- Sync State ------------------------------------------

    def get_sync_state(self, key):
        """Get a sync state value."""
        conn = self._connect()
        row = conn.execute(
            'SELECT value FROM sync_state WHERE key = ?', (key,)
        ).fetchone()
        return row['value'] if row else None

    def set_sync_state(self, key, value):
        """Set a sync state value."""
        conn = self._connect()
        conn.execute('''
            INSERT OR REPLACE INTO sync_state (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
        ''', (key, value))
        conn.commit()

    # --- Seed from legacy JSON payloads ----------------------

    def seed_from_json(self, payloads_dir):
        """Import existing JSON payload files into the database (idempotent)."""
        ir_dir = os.path.join(payloads_dir, 'ir')
        if not os.path.isdir(ir_dir):
            return {'imported': 0, 'skipped': 0, 'message': 'No payload dir'}

        imported = 0
        skipped = 0

        for filename in sorted(os.listdir(ir_dir)):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(ir_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
            except Exception:
                skipped += 1
                continue

            brand_name = data.get('brand', 'Unknown')
            device_name = data.get('device', filename.replace('.json', ''))
            protocol = data.get('protocol', 'NEC')
            notes = data.get('notes', '')
            source_urls = data.get('source_urls', [])

            brand_id = self.insert_brand(brand_name, device_type='')
            device_id = self.insert_device(
                brand_id, device_name,
                source_file=filename,
                notes=notes
            )

            for btn_id, btn in data.get('buttons', {}).items():
                addr = btn.get('address')
                cmd = btn.get('command')
                addr_hex = f'0x{addr:04X}' if addr is not None else ''
                cmd_hex = f'0x{cmd:04X}' if cmd is not None else ''

                # Build raw pulses/spaces from NEC encoder
                from modules.ir_protocols import encode_nec
                hp = data.get('header_pulse', 9000)
                hs = data.get('header_space', 4500)
                s32 = data.get('samsung32', False)
                pulses, spaces = encode_nec(
                    addr or 0, cmd or 0,
                    header_pulse=hp, header_space=hs,
                    samsung32=s32
                )

                existing = self.get_button_by_device_and_id(device_id, btn_id)
                if existing:
                    skipped += 1
                    continue

                self.insert_button(
                    device_id, btn_id, btn.get('label', btn_id),
                    protocol=protocol,
                    address=addr, command=cmd,
                    address_hex=addr_hex, command_hex=cmd_hex,
                    frequency=38000,
                    raw_pulses=pulses, raw_spaces=spaces,
                    protocol_hint=protocol,
                    header_pulse=hp, header_space=hs,
                    samsung32=1 if s32 else 0,
                    source_file=filename,
                    notes=json.dumps(source_urls) if source_urls else ''
                )
                imported += 1

        return {'imported': imported, 'skipped': skipped}

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
