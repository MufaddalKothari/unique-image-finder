"""
core/hash_cache.py

Implements a simple SQLite-based hash cache scaffold.
You can extend this to store/lookup perceptual hashes (ahash/dhash/phash/whash).
"""

import sqlite3
from typing import Optional

class HashCache:
    def __init__(self, db_path="hash_cache.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS image_hashes (
                path TEXT,
                hash_type TEXT,
                hash_value TEXT,
                hash_size INTEGER,
                mtime INTEGER,
                size INTEGER,
                PRIMARY KEY (path, hash_type, hash_size)
            )""")
        self.conn.commit()

    def get_hash(self, path: str, hash_type: str, hash_size: int, mtime: int, size: int) -> Optional[str]:
        c = self.conn.cursor()
        c.execute("""
            SELECT hash_value FROM image_hashes
            WHERE path=? AND hash_type=? AND hash_size=? AND mtime=? AND size=?
        """, (path, hash_type, hash_size, mtime, size))
        row = c.fetchone()
        return row[0] if row else None

    def set_hash(self, path: str, hash_type: str, hash_value: str, hash_size: int, mtime: int, size: int):
        c = self.conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO image_hashes
            (path, hash_type, hash_value, hash_size, mtime, size)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (path, hash_type, hash_value, hash_size, mtime, size))
        self.conn.commit()