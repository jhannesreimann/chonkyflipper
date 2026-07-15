"""
Base class for SQLite-backed payload databases.
Provides shared connection management, schema versioning, and sync state storage.
Subclasses define their own table schemas in init_db().
"""

import sqlite3
import os


class BasePayloadDB:
    """Shared SQLite infrastructure for payload databases (IR, BadUSB)."""

    SCHEMA_VERSION = 1
    DB_FILENAME = None  # override in subclass, e.g. 'ir_payloads.db'

    def __init__(self, db_path=None):
        if db_path is None:
            candidates = [
                f'/opt/chonkyflipper/data/{self.DB_FILENAME}',
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             '..', 'data', self.DB_FILENAME),
            ]
            db_path = candidates[0]
            for p in candidates:
                if os.path.isdir(os.path.dirname(p)):
                    db_path = p
                    break
        self.db_path = db_path
        self._conn = None

    def _connect(self):
        if self._conn is not None:
            return self._conn
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=10000')
        conn.row_factory = sqlite3.Row
        self._conn = conn
        return conn

    def _ensure_schema_version(self):
        """Insert schema version row if the table is empty. Call at end of init_db()."""
        conn = self._connect()
        cur = conn.execute('SELECT COUNT(*) FROM schema_version')
        if cur.fetchone()[0] == 0:
            conn.execute('INSERT INTO schema_version (version) VALUES (?)',
                         (self.SCHEMA_VERSION,))
            conn.commit()

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

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
