# core/hashstore.py
"""
HashStore - single, authoritative transient cache for image hashes.

Goals / guarantees implemented here:
- Consistent cache keying: paths are normalized (resolved absolute paths) before lookups.
- Consistent storage format: hashes are ALWAYS stored as hex strings.
- Cache validity: stored entry is validated against current mtime+size and hash_size.
- Bulk-friendly API: bulk_get(paths, hash_size) returns path -> hex for valid cached entries.
- Flexible set: accepts imagehash.ImageHash or hex string and stores hex string.
- Unreadable sentinel: if a file cannot be read/stat'd the DB can be updated with status='UNREADABLE'
- Thread-friendly sqlite usage (per-instance connection with simple locking)
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple, Union

from PIL import Image, UnidentifiedImageError
import imagehash

LOG = logging.getLogger(__name__)

UNREADABLE = "UNREADABLE"


def _normalize_path(path: str) -> str:
    try:
        # Prefer a canonical resolved absolute path. On failure fall back to abspath.
        return str(Path(path).expanduser().resolve(strict=False))
    except Exception:
        return os.path.abspath(path)


def _stat_path(path: str) -> Optional[Tuple[float, int]]:
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except Exception:
        return None


class HashStore:
    """
    A lightweight sqlite-backed cache for image hashes.

    Usage:
      hs = HashStore(db_path="...")           # or no-arg for default local DB
      hits = hs.bulk_get(list_of_paths, 16)   # returns dict path -> hex_hash (only for valid entries)
      hs.set(path, imagehash_or_hex, 16)      # stores (overwrites) entry
      hs.get(path, 16)                        # get single entry or None
      hs.close()
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # default to a local DB file in repo run dir (safe fallback)
            db_path = os.path.join(os.getcwd(), ".image_hash_cache.db")
        self.db_path = db_path
        # connection per-instance; sqlite is used with simple serialization
        self._conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS hashes (
                path TEXT PRIMARY KEY,
                mtime REAL,
                size INTEGER,
                hex TEXT,
                status TEXT,
                hash_size INTEGER
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_hashes_path ON hashes(path)")
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # -------------------------
    # low-level helpers
    # -------------------------
    def _row_for_path(self, path_norm: str) -> Optional[Tuple[float, int, Optional[str], Optional[str], Optional[int]]]:
        cur = self._conn.cursor()
        cur.execute("SELECT mtime, size, hex, status, hash_size FROM hashes WHERE path = ?", (path_norm,))
        return cur.fetchone()

    def _write_row(
        self,
        path_norm: str,
        mtime: float,
        size: int,
        hexv: Optional[str],
        status: Optional[str],
        hash_size: Optional[int],
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO hashes (path, mtime, size, hex, status, hash_size)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (path_norm, mtime, size, hexv, status, hash_size),
        )
        self._conn.commit()

    # -------------------------
    # public API
    # -------------------------
    def bulk_get(self, paths: Iterable[str], hash_size: int) -> Dict[str, str]:
        """
        Return mapping of normalized path -> hex string for entries considered valid.
        Valid means:
         - DB has a row AND
         - row.hash_size == requested hash_size AND
         - row.status is not UNREADABLE AND
         - row.mtime == current file mtime and row.size == current file size

        Any path not satisfying the above will be omitted from the returned dict.
        """
        out: Dict[str, str] = {}
        with self._lock:
            for p in paths:
                p_norm = _normalize_path(p)
                stat = _stat_path(p_norm)
                if stat is None:
                    # file not present / unreadable on disk; omit (do not create row here)
                    continue
                mtime, size = stat
                row = self._row_for_path(p_norm)
                if not row:
                    continue
                r_mtime, r_size, r_hex, r_status, r_hash_size = row
                if r_status == UNREADABLE:
                    continue
                if r_hash_size != hash_size:
                    continue
                # validate metadata
                if r_mtime == mtime and r_size == size and r_hex:
                    out[p] = r_hex
            return out

    def get(self, path: str, hash_size: int) -> Optional[str]:
        """Single-path convenience wrapper returning hex string or None."""
        p_norm = _normalize_path(path)
        with self._lock:
            stat = _stat_path(p_norm)
            if stat is None:
                return None
            mtime, size = stat
            row = self._row_for_path(p_norm)
            if not row:
                return None
            r_mtime, r_size, r_hex, r_status, r_hash_size = row
            if r_status == UNREADABLE:
                return None
            if r_hash_size != hash_size:
                return None
            if r_mtime == mtime and r_size == size and r_hex:
                return r_hex
            return None

    def set(self, path: str, value: Union[str, imagehash.ImageHash, None], hash_size: int) -> None:
        """
        Store an entry for `path`.
        - `value` may be:
            - hex string (e.g. ImageHash.__str__())
            - imagehash.ImageHash instance
            - None -> mark as UNREADABLE sentinel
        The DB stores hex strings (or NULL for unreadable) + current mtime/size + hash_size.
        """
        p_norm = _normalize_path(path)

        stat = _stat_path(p_norm)
        if stat is None:
            # mark unreadable with zero metadata: future runs will re-attempt stat and skip fast
            with self._lock:
                self._write_row(p_norm, 0.0, 0, None, UNREADABLE, hash_size)
            return

        mtime, size = stat
        hexv: Optional[str]
        status: Optional[str] = None
        if value is None:
            hexv = None
            status = UNREADABLE
        elif isinstance(value, imagehash.ImageHash):
            hexv = str(value)
        elif isinstance(value, str):
            hexv = value
        else:
            # try to coerce
            try:
                hexv = str(value)
            except Exception:
                hexv = None
                status = UNREADABLE

        with self._lock:
            self._write_row(p_norm, mtime, size, hexv, status, hash_size)

    # Convenience wrapper used by older code that expects an imagehash.ImageHash back:
    def get_as_imagehash(self, path: str, hash_size: int) -> Optional[imagehash.ImageHash]:
        hexv = self.get(path, hash_size)
        if not hexv:
            return None
        try:
            return imagehash.hex_to_hash(hexv)
        except Exception:
            return None