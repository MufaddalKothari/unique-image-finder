"""
SQLite helper + hash-aware _hash_one integration.

Provides:
- init_db(conn) -> creates the images table and indexes if needed.
- get_image_by_canonical(conn, canonical_path) -> returns a sqlite3.Row or None
- update_image(conn, ...) -> placeholder (left blank as requested)
- _hash_one(path, hash_size, db_conn=None) -> checks DB for canonical path before computing dhash

Notes:
- This module defines a canonical normalization used for DB keys (_normalize_path).
- It also provides conversions between imagehash.ImageHash <-> integer so stored integer
  full_hash values can be converted back to ImageHash objects if needed.
- The update_image function is intentionally left empty (pass) per your request.
"""

from pathlib import Path
import os
import sqlite3
import logging
from typing import Optional

from PIL import Image, UnidentifiedImageError
import imagehash
import numpy as np

logger = logging.getLogger(__name__)

# SQL table + index DDL
_IMAGES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_directory_name TEXT NOT NULL,
  canonical_path TEXT NOT NULL UNIQUE,
  dhash16 INTEGER NOT NULL,
  full_hash INTEGER NULL,
  full_hash_blob BLOB NULL,
  full_hash_prefix INTEGER NULL,
  hash_bits INTEGER NOT NULL,
  last_seen INTEGER NULL
);
"""

_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_images_parent ON images(parent_directory_name);",
    "CREATE INDEX IF NOT EXISTS idx_images_dhash16 ON images(dhash16);",
    "CREATE INDEX IF NOT EXISTS idx_images_parent_dhash ON images(parent_directory_name, dhash16);",
    "CREATE INDEX IF NOT EXISTS idx_images_prefix ON images(full_hash_prefix);",
]


def _normalize_path(p: str) -> str:
    """
    Normalize a path to a canonical string suitable for use as the canonical_path key.
    Uses Path.resolve(strict=False) + os.path.normcase to be robust across platforms.
    """
    try:
        rp = Path(p).resolve(strict=False)
        rp_str = str(rp)
    except Exception:
        rp_str = os.path.abspath(p)
    try:
        rp_str = os.path.normcase(rp_str)
    except Exception:
        pass
    return rp_str


def init_db(conn: sqlite3.Connection) -> None:
    """
    Ensure the images table and indexes exist. Idempotent.
    """
    cur = conn.cursor()
    cur.execute(_IMAGES_TABLE_DDL)
    for idx in _INDEX_DDL:
        cur.execute(idx)
    conn.commit()


def get_image_by_canonical(conn: sqlite3.Connection, canonical_path: str) -> Optional[sqlite3.Row]:
    """
    Return the DB row for canonical_path, or None if not present.
    The returned row is sqlite3.Row (mapping-like). Caller may read fields:
      - 'dhash16', 'full_hash', 'full_hash_blob', 'full_hash_prefix', 'hash_bits', etc.
    """
    # ensure row factory for dict-like access
    old_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM images WHERE canonical_path = ?", (canonical_path,))
        row = cur.fetchone()
        return row
    finally:
        conn.row_factory = old_factory


def update_image(conn: sqlite3.Connection, *args, **kwargs) -> None:
    """
    Placeholder for upsert/update logic. Left intentionally blank as requested.
    Implement with INSERT ... ON CONFLICT(canonical_path) DO UPDATE or similar once ready.
    """
    pass


def _imagehash_to_int(h: imagehash.ImageHash) -> int:
    """
    Convert imagehash.ImageHash -> integer (row-major order).
    The conversion is defined such that int_to_imagehash is its inverse.
    """
    # h.hash is a numpy array of shape (N, N) with boolean-like values
    arr = getattr(h, "hash", None)
    if arr is None:
        raise ValueError("Provided ImageHash has no .hash array")
    flat = arr.flatten()  # row-major
    val = 0
    for bit in flat:
        val = (val << 1) | (1 if bit else 0)
    return val


def _int_to_imagehash(val: int, hash_size: int) -> imagehash.ImageHash:
    """
    Convert integer -> imagehash.ImageHash with shape (hash_size, hash_size).
    The integer is interpreted in the same row-major order as _imagehash_to_int.
    """
    hash_bits = hash_size * hash_size
    # Build bit list from most-significant to least-significant bits
    bits = [(val >> (hash_bits - 1 - i)) & 1 for i in range(hash_bits)]
    arr = np.array(bits, dtype=bool).reshape((hash_size, hash_size))
    return imagehash.ImageHash(arr)


def _hash_one(path: str, hash_size: int, db_conn: Optional[sqlite3.Connection] = None) -> Optional[imagehash.ImageHash]:
    """
    Compute dhash for one image path, but first check the database (if provided)
    for an existing record with the canonical path. If a matching DB row with a
    stored full_hash integer exists and matches the requested hash_size (in bits),
    reconstruct and return an imagehash.ImageHash without re-opening/re-hashing the file.

    If no DB row is present (or stored data is incompatible) this falls back to
    computing the hash from the image file via PIL + imagehash.dhash and returns it.

    Note: update/insert of newly computed hashes is left to update_image (a no-op here).
    """
    canon = _normalize_path(path)

    # ensure DB table exists and check for existing entry
    if db_conn is not None:
        try:
            init_db(db_conn)
        except Exception:
            # log but continue to computing hash; DB shouldn't block hashing
            logger.exception("init_db failed; proceeding to compute hash from file")

        try:
            row = get_image_by_canonical(db_conn, canon)
        except Exception:
            logger.exception("DB read failed for %s; proceeding to compute hash", canon)
            row = None

        if row:
            # If we have an integer full_hash and the stored hash_bits equals expected bits,
            # reconstruct and return ImageHash without reading file.
            try:
                stored_hash_bits = int(row["hash_bits"])
                expected_bits = hash_size * hash_size
                if row["full_hash"] is not None and stored_hash_bits == expected_bits:
                    full_int = int(row["full_hash"])
                    return _int_to_imagehash(full_int, hash_size)
                # If there is a full_hash_blob (for >64-bit hashes), we could reconstruct too
                if row["full_hash_blob"] is not None:
                    blob = row["full_hash_blob"]
                    # convert bytes to int (big-endian) and try to reconstruct if bit length matches
                    full_int = int.from_bytes(blob, byteorder="big")
                    if stored_hash_bits == expected_bits:
                        return _int_to_imagehash(full_int, hash_size)
            except Exception:
                logger.exception("Failed to reconstruct ImageHash from DB row for %s", canon)
            # If DB row exists but cannot be used, fall back to computing below.

    # Compute hash from image file (fallback)
    try:
        with Image.open(path) as im:
            # imagehash.dhash expects an Image and will convert as needed
            h = imagehash.dhash(im, hash_size=hash_size)
            return h
    except (UnidentifiedImageError, OSError, ValueError) as e:
        logger.debug("Cannot open image for hashing %s: %s", path, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error hashing image %s: %s", path, e)
        return None