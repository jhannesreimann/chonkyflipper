#!/usr/bin/env python3
"""
BadUSB Payload Database - SQLite storage for DuckyScript payload library.
Provides hierarchical browsing (OS -> categories -> payloads), search, and
full-text retrieval. Modelled after the IR payload DB (ir_db.py).
"""

import sqlite3
import os
import json


class BadUSBDB:
    """SQLite-backed BadUSB payload database."""

    SCHEMA_VERSION = 1

    OS_TYPES = [
        ('Cross-Platform', 'cross-platform'),
        ('Windows', 'windows'),
        ('Linux', 'linux'),
        ('macOS', 'macos'),
        ('Android', 'android'),
        ('iOS', 'ios'),
    ]

    CATEGORIES = [
        'recon',
        'credentials',
        'exfiltration',
        'execution',
        'persistence',
        'C2',
        'remote_access',
        'phishing',
        'prank',
        'general',
        'mobile',
        'incident_response',
    ]

    def __init__(self, db_path=None):
        if db_path is None:
            candidates = [
                '/opt/chonkyflipper/data/badusb_payloads.db',
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             '..', 'data', 'badusb_payloads.db'),
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
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=10000')
        conn.row_factory = sqlite3.Row
        self._conn = conn
        return conn

    def init_db(self):
        """Create tables and seed OS types / categories if empty."""
        conn = self._connect()
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS os_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                os_id INTEGER REFERENCES os_types(id) ON DELETE SET NULL,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                description TEXT DEFAULT '',
                author TEXT DEFAULT '',
                target TEXT DEFAULT '',
                source_repo TEXT DEFAULT '',
                source_path TEXT DEFAULT '',
                content TEXT NOT NULL,
                layout TEXT DEFAULT 'us',
                props TEXT DEFAULT '',
                payload_version TEXT DEFAULT '',
                imported_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source_repo, source_path)
            );

            CREATE INDEX IF NOT EXISTS idx_payloads_os ON payloads(os_id);
            CREATE INDEX IF NOT EXISTS idx_payloads_category ON payloads(category_id);
            CREATE INDEX IF NOT EXISTS idx_payloads_name ON payloads(name);

            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        ''')

        # Enable FTS5
        try:
            conn.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS payloads_fts
                USING fts5(name, description, target, content, content=payloads, content_rowid=id)
            ''')
        except Exception:
            pass  # FTS5 may not be compiled in

        # Seed OS types
        cur = conn.execute('SELECT COUNT(*) FROM os_types')
        if cur.fetchone()[0] == 0:
            for name, slug in self.OS_TYPES:
                conn.execute('INSERT INTO os_types (name, slug) VALUES (?, ?)',
                             (name, slug))

        # Seed categories
        cur = conn.execute('SELECT COUNT(*) FROM categories')
        if cur.fetchone()[0] == 0:
            for cat in self.CATEGORIES:
                slug = cat.lower().replace(' ', '_')
                conn.execute('INSERT INTO categories (name, slug) VALUES (?, ?)',
                             (cat, slug))

        # Apply schema version if empty
        cur = conn.execute('SELECT COUNT(*) FROM schema_version')
        if cur.fetchone()[0] == 0:
            conn.execute('INSERT INTO schema_version (version) VALUES (?)',
                         (self.SCHEMA_VERSION,))

        conn.commit()
        return {'success': True, 'db_path': self.db_path}

    # OS types

    def get_os_types(self):
        """Return all OS types with payload counts."""
        conn = self._connect()
        rows = conn.execute('''
            SELECT o.id, o.name, o.slug, COUNT(p.id) as payload_count
            FROM os_types o
            LEFT JOIN payloads p ON p.os_id = o.id
            GROUP BY o.id
            ORDER BY o.name
        ''').fetchall()
        return [dict(r) for r in rows]

    def _get_os_id(self, slug):
        conn = self._connect()
        row = conn.execute('SELECT id FROM os_types WHERE slug = ?', (slug,)).fetchone()
        return row['id'] if row else None

    def _resolve_os(self, target_text, dirpath='', content=''):
        """Infer OS slug from REM Target: text, directory name, or content."""
        t = (target_text or '').lower()
        d = (dirpath or '').lower()
        c = (content or '').lower()

        # Content-based detection (strongest signal for Windows)
        if 'powershell' in c or 'cmd.exe' in c or 'reg add' in c or 'wmic ' in c:
            return 'windows'
        if 'ipconfig' in c or 'netsh ' in c:
            return 'windows'
        if 'bash ' in c or '/etc/' in c or '#!/bin/bash' in c:
            return 'linux'
        if 'apt-get' in c or 'systemctl' in c:
            return 'linux'
        if 'osascript' in c or 'open -a' in c:
            return 'macos'

        combined = f'{t} {d}'
        if 'windows' in t or 'win' in t:
            return 'windows'
        if 'linux' in combined or 'ubuntu' in combined or 'debian' in combined or 'kali' in combined:
            return 'linux'
        if 'unix-like' in d:
            return 'linux'
        if 'gnu-linux' in d:
            return 'linux'
        if 'macos' in combined or 'mac os' in combined or 'osx' in combined:
            return 'macos'
        if '/macos/' in d or 'macos' in d:
            return 'macos'
        if t.startswith('mac') and 'macos' not in t and 'machine' not in t:
            return 'macos'
        if 'android' in combined:
            return 'android'
        if 'ios' in combined or 'iphone' in combined or 'ipad' in combined:
            return 'ios'
        return 'cross-platform'

    # Categories

    def get_categories(self, os_slug=None):
        """Return categories with payload counts, optionally filtered by OS."""
        conn = self._connect()
        if os_slug:
            rows = conn.execute('''
                SELECT c.id, c.name, c.slug, COUNT(p.id) as payload_count
                FROM categories c
                JOIN payloads p ON p.category_id = c.id
                JOIN os_types o ON o.id = p.os_id
                WHERE o.slug = ?
                GROUP BY c.id
                ORDER BY c.name
            ''', (os_slug,)).fetchall()
        else:
            rows = conn.execute('''
                SELECT c.id, c.name, c.slug, COUNT(p.id) as payload_count
                FROM categories c
                LEFT JOIN payloads p ON p.category_id = c.id
                GROUP BY c.id
                ORDER BY c.name
            ''').fetchall()
        return [dict(r) for r in rows]

    def _get_category_id(self, slug):
        conn = self._connect()
        row = conn.execute('SELECT id FROM categories WHERE slug = ?', (slug,)).fetchone()
        return row['id'] if row else None

    def _resolve_category(self, text, dirpath=''):
        """Infer category from REM Category: header or directory path."""
        if text:
            t = text.lower().replace(' ', '_').replace('-', '_')
            for cat in self.CATEGORIES:
                if cat.lower() in t:
                    return cat.lower().replace(' ', '_')
        if dirpath:
            d = dirpath.lower()
            for cat in self.CATEGORIES:
                if cat.lower() in d:
                    return cat.lower().replace(' ', '_')
        return 'general'

    # Payloads

    def get_payloads(self, os_slug=None, category_slug=None, offset=0, limit=100):
        """List payloads, optionally filtered by OS and/or category."""
        conn = self._connect()
        params = []
        where = []
        if os_slug:
            where.append('o.slug = ?')
            params.append(os_slug)
        if category_slug:
            where.append('c.slug = ?')
            params.append(category_slug)

        clause = ('WHERE ' + ' AND '.join(where)) if where else ''
        rows = conn.execute(f'''
            SELECT p.id, p.name, p.slug, p.description, p.author, p.target,
                   p.source_repo, p.layout, p.payload_version,
                   o.name as os_name, o.slug as os_slug,
                   c.name as category_name, c.slug as category_slug
            FROM payloads p
            LEFT JOIN os_types o ON o.id = p.os_id
            LEFT JOIN categories c ON c.id = p.category_id
            {clause}
            ORDER BY p.name
            LIMIT ? OFFSET ?
        ''', params + [limit, offset]).fetchall()
        return [dict(r) for r in rows]

    def get_payload(self, payload_id):
        """Get a single payload with full content and metadata."""
        conn = self._connect()
        row = conn.execute('''
            SELECT p.*, o.name as os_name, o.slug as os_slug,
                   c.name as category_name, c.slug as category_slug
            FROM payloads p
            LEFT JOIN os_types o ON o.id = p.os_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE p.id = ?
        ''', (payload_id,)).fetchone()
        return dict(row) if row else None

    def insert_payload(self, name, content, os_slug='cross-platform',
                       category_slug='general', description='', author='',
                       target='', source_repo='', source_path='', layout='us',
                       props='', payload_version=''):
        """Insert or replace a payload. Returns payload id."""
        conn = self._connect()
        os_id = self._get_os_id(os_slug) or self._get_os_id('cross-platform')
        cat_id = self._get_category_id(category_slug) or self._get_category_id('general')

        slug = name.lower().replace(' ', '_').replace('-', '_').replace('/', '_')

        conn.execute('''
            INSERT OR REPLACE INTO payloads
            (os_id, category_id, name, slug, description, author, target,
             source_repo, source_path, content, layout, props, payload_version,
             updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ''', (os_id, cat_id, name, slug, description, author, target,
              source_repo, source_path, content, layout, props, payload_version))
        conn.commit()

        # Update FTS index
        try:
            conn.execute('''
                INSERT INTO payloads_fts(rowid, name, description, target, content)
                VALUES (?, ?, ?, ?, ?)
            ''', (conn.execute('SELECT last_insert_rowid()').fetchone()[0],
                  name, description, target, content))
        except Exception:
            pass

        row = conn.execute(
            'SELECT id FROM payloads WHERE source_repo = ? AND source_path = ?',
            (source_repo, source_path)
        ).fetchone()
        return row['id'] if row else None

    # Search

    def search(self, query):
        """Full-text search across payload name, description, target and content."""
        if not query or not query.strip():
            return {'payloads': [], 'query': query}

        conn = self._connect()
        q = query.strip()

        # Try FTS5 first
        try:
            rows = conn.execute('''
                SELECT p.id, p.name, p.slug, p.description, p.author, p.target,
                       p.source_repo, p.layout, p.payload_version,
                       o.name as os_name, o.slug as os_slug,
                       c.name as category_name, c.slug as category_slug
                FROM payloads_fts f
                JOIN payloads p ON p.id = f.rowid
                LEFT JOIN os_types o ON o.id = p.os_id
                LEFT JOIN categories c ON c.id = p.category_id
                WHERE payloads_fts MATCH ?
                ORDER BY rank
                LIMIT 50
            ''', (q,)).fetchall()
            return {'payloads': [dict(r) for r in rows], 'query': q}
        except Exception:
            pass

        # Fallback to LIKE
        like = f'%{q}%'
        rows = conn.execute('''
            SELECT p.id, p.name, p.slug, p.description, p.author, p.target,
                   p.source_repo, p.layout, p.payload_version,
                   o.name as os_name, o.slug as os_slug,
                   c.name as category_name, c.slug as category_slug
            FROM payloads p
            LEFT JOIN os_types o ON o.id = p.os_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE p.name LIKE ? OR p.description LIKE ? OR p.target LIKE ?
               OR p.content LIKE ?
            ORDER BY p.name
            LIMIT 50
        ''', (like, like, like, like)).fetchall()
        return {'payloads': [dict(r) for r in rows], 'query': q}

    # Seed from filesystem

    def seed_from_filesystem(self, payloads_dir):
        """Import existing .txt payload files from the payloads/badusb/ directory."""
        badusb_dir = os.path.join(payloads_dir, 'badusb')
        if not os.path.isdir(badusb_dir):
            return {'imported': 0, 'skipped': 0, 'message': 'No payloads dir'}

        imported = 0
        skipped = 0

        for rootdir, _dirs, files in os.walk(badusb_dir):
            for fname in files:
                if not fname.endswith('.txt'):
                    continue
                filepath = os.path.join(rootdir, fname)
                rel = os.path.relpath(filepath, badusb_dir)

                # Check if already imported
                existing = self._find_by_source('filesystem', rel)
                if existing:
                    skipped += 1
                    continue

                try:
                    with open(filepath, 'r') as f:
                        content = f.read()
                except Exception:
                    skipped += 1
                    continue

                headers = self._parse_rem_headers(content)
                name = headers.get('title') or fname.replace('.txt', '').replace('_', ' ').title()
                os_slug = self._resolve_os(headers.get('target', ''), content=content)
                if not headers.get('target'):
                    # Infer from directory structure
                    dir_os = os.path.dirname(rel).split(os.sep)[0] if os.sep in rel else ''
                    os_slug = self._resolve_os(dir_os, content=content)
                cat = self._resolve_category(
                    headers.get('category', ''),
                    os.path.dirname(rel)
                )

                self.insert_payload(
                    name=name, content=content, os_slug=os_slug,
                    category_slug=cat,
                    description=headers.get('description', ''),
                    author=headers.get('author', ''),
                    target=headers.get('target', ''),
                    source_repo='filesystem', source_path=rel,
                    layout=headers.get('layout', 'us'),
                    props=headers.get('props', ''),
                    payload_version=headers.get('version', ''),
                )
                imported += 1

        return {'imported': imported, 'skipped': skipped}

    # REM header parsing

    def _parse_rem_headers(self, content):
        """Extract metadata from REM comment headers in DuckyScript."""
        headers = {}
        patterns = {
            'title': r'REM\s+#?\s*Title\s*:\s*(.+)',
            'author': r'REM\s+#?\s*Author\s*:\s*(.+)',
            'description': r'REM\s+#?\s*Description\s*:\s*(.+)',
            'target': r'REM\s+#?\s*Target\s*:\s*(.+)',
            'category': r'REM\s+#?\s*Category\s*:\s*(.+)',
            'props': r'REM\s+#?\s*Props\s*:\s*(.+)',
            'version': r'REM\s+#?\s*Version\s*:\s*(.+)',
            'layout': r'REM\s+#?\s*Layout\s*:\s*(.+)',
        }
        import re
        for line in content.split('\n'):
            line = line.strip()
            if not line.upper().startswith('REM '):
                if line and not line.upper().startswith('REM'):
                    if headers:
                        break
                continue
            for key, pat in patterns.items():
                m = re.match(pat, line, re.IGNORECASE)
                if m:
                    val = m.group(1).strip().rstrip('|').strip()
                    headers[key] = val
        return headers

    def _find_by_source(self, repo, path):
        conn = self._connect()
        row = conn.execute(
            'SELECT id FROM payloads WHERE source_repo = ? AND source_path = ?',
            (repo, path)
        ).fetchone()
        return row['id'] if row else None

    # Stats

    def get_stats(self):
        """Return database statistics."""
        conn = self._connect()
        total = conn.execute('SELECT COUNT(*) FROM payloads').fetchone()[0]

        os_rows = conn.execute('''
            SELECT o.name, o.slug, COUNT(p.id) as cnt
            FROM os_types o
            LEFT JOIN payloads p ON p.os_id = o.id
            GROUP BY o.id ORDER BY cnt DESC
        ''').fetchall()

        cat_rows = conn.execute('''
            SELECT c.name, c.slug, COUNT(p.id) as cnt
            FROM categories c
            LEFT JOIN payloads p ON p.category_id = c.id
            GROUP BY c.id ORDER BY cnt DESC
        ''').fetchall()

        return {
            'total': total,
            'by_os': {r['slug']: r['cnt'] for r in os_rows},
            'by_category': {r['slug']: r['cnt'] for r in cat_rows},
        }

    # Sync State

    def get_sync_state(self, key):
        conn = self._connect()
        row = conn.execute(
            'SELECT value FROM sync_state WHERE key = ?', (key,)
        ).fetchone()
        return row['value'] if row else None

    def set_sync_state(self, key, value):
        conn = self._connect()
        conn.execute('''
            INSERT OR REPLACE INTO sync_state (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
        ''', (key, value))
        conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
