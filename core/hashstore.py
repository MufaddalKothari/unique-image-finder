import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional

import imagehash
from PIL import Image  # only for type clarity

DEFAULT_DB = os.environ.get("UNIQUE_IMAGE_FINDER_HASH_DB") or os.path.join(str(Path.home()), ".unique_image_finder_hashes.db")


class HashStore:
    """
    Simple SQLite-backed cache for image hashes.

    Table schema:
      images (
        path TEXT PRIMARY KEY,
        mtime INTEGER,
        size INTEGER,
        hash TEXT,
        hash_size INTEGER,
        updated INTEGER
      )

    Cache lookup is based on path + mtime + size + hash_size. If mtime/size change we recompute.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True) if os.path.dirname(self.db_path) else None
        self._conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        self._ensure_table()

    def _ensure_table(self):
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
                path TEXT PRIMARY KEY,
                mtime INTEGER,
                size INTEGER,
                hash TEXT,
                hash_size INTEGER,
                updated INTEGER
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_hash_size ON images(hash_size)")
        self._conn.commit()

    def close(self):
        try:
            self._conn.commit()
            self._conn.close()
        except Exception:
            pass

    def get(self, path: str, mtime: int, size: int, hash_size: int):
        """
        Return imagehash.ImageHash object if present and matches mtime+size+hash_size, otherwise None.
        """
        cur = self._conn.cursor()
        cur.execute("SELECT hash FROM images WHERE path=? AND mtime=? AND size=? AND hash_size=?", (path, int(mtime), int(size), int(hash_size)))
        row = cur.fetchone()
        if not row:
            return None
        hexstr = row[0]
        try:
            return imagehash.hex_to_hash(hexstr)
        except Exception:
            try:
                return imagehash.hex_to_hash(hexstr)
            except Exception:
                return None

    def set(self, path: str, hash_obj, hash_size: int):
        if hash_obj is None:
            return
        hexstr = str(hash_obj)
        try:
            mtime = int(os.path.getmtime(path))
            size = int(os.path.getsize(path))
        except Exception:
            mtime = 0
            size = 0
        now = int(time.time())
        cur = self._conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO images (path, mtime, size, hash, hash_size, updated) VALUES (?, ?, ?, ?, ?, ?)",
            (path, mtime, size, hexstr, int(hash_size), now),
        )
        self._conn.commit()

    def bulk_get(self, paths, hash_size: int) -> Dict[str, object]:
        out = {}
        cur = self._conn.cursor()
        for p in paths:
            try:
                mtime = int(os.path.getmtime(p))
                size = int(os.path.getsize(p))
            except Exception:
                continue
            cur.execute("SELECT hash FROM images WHERE path=? AND mtime=? AND size=? AND hash_size=?", (p, mtime, size, int(hash_size)))
            row = cur.fetchone()
            if row:
                hexstr = row[0]
                try:
                    out[p] = imagehash.hex_to_hash(hexstr)
                except Exception:
                    continue
        return out

    def remove_missing(self, existing_paths):
        cur = self._conn.cursor()
        cur.execute("SELECT path FROM images")
        rows = cur.fetchall()
        to_delete = []
        existing_set = set(existing_paths)
        for (p,) in rows:
            if p not in existing_set:
                to_delete.append((p,))
        if to_delete:
            cur.executemany("DELETE FROM images WHERE path=?", to_delete)
            self._conn.commit()
