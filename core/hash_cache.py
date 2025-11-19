"""
core/hash_cache.py

Implements a simple SQLite-based hash cache and an integrated compute-or-get helper that
uses the `imagehash` library to compute perceptual hashes and caches them by path/hash_type/hash_size/mtime/size.
"""

import sqlite3
import os
import logging
from typing import Optional
from PIL import Image

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

try:
    import imagehash
except Exception:
    imagehash = None

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

    def compute_or_get_hash(self, path: str, hash_type: str, hash_size: int) -> Optional[str]:
        """Compute hash using imagehash (if available) or return cached value when available.

        Returns the hexadecimal string representation of the hash, or None if imagehash is missing.
        """
        if imagehash is None:
            logger.warning("imagehash library is not installed; hash comparisons are disabled.")
            return None

        try:
            stat = os.stat(path)
            mtime = int(stat.st_mtime)
            size = int(stat.st_size)
        except Exception:
            mtime = 0
            size = 0

        cached = self.get_hash(path, hash_type, hash_size, mtime, size)
        if cached:
            return cached

        # Compute hash
        try:
            with Image.open(path) as img:
                img.load()
                ht = hash_type.lower()
                if ht.startswith("average") or ht == "ahash":
                    h = imagehash.average_hash(img, hash_size)
                elif ht.startswith("perceptual") or ht == "phash":
                    h = imagehash.phash(img, hash_size)
                elif ht.startswith("difference") or ht == "dhash":
                    h = imagehash.dhash(img, hash_size)
                elif ht.startswith("wavelet") or ht == "whash":
                    h = imagehash.whash(img, hash_size)
                else:
                    h = imagehash.phash(img, hash_size)

                hexstr = h.__str__()
                # Cache it
                self.set_hash(path, hash_type, hexstr, hash_size, mtime, size)
                return hexstr
        except Exception as e:
            logger.warning("Failed to compute hash for %s: %s", path, e)
            return None

"""
def find_duplicates(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> List[Tuple]:
    """
    Find duplicate pairs between ref_files and work_files according to criteria.

    Returns list of tuples: (ref_file, work_file, [reasons])
    """
    matches = []
    if not ref_files or not work_files:
        return matches

    use_hash = bool(criteria.get("hash"))
    hash_type = criteria.get("hash_type")
    hash_size = criteria.get("hash_size") or 8
    similarity = criteria.get("similarity") or 90

    # Pre-index work files by simple keys if criteria asked for it
    index_by_size = {}
    index_by_name = {}
    for w in work_files:
        if criteria.get("size") and getattr(w, "size", None) is not None:
            index_by_size.setdefault(w.size, []).append(w)
        if criteria.get("name") and getattr(w, "name", None):
            index_by_name.setdefault(w.name, []).append(w)

    for r in ref_files:
        possible = set()
        # If size criterion, begin from size bucket
        if criteria.get("size") and getattr(r, "size", None) is not None:
            possible.update(index_by_size.get(r.size, []))
        # If name criterion, include name bucket
        if criteria.get("name") and getattr(r, "name", None):
            possible.update(index_by_name.get(r.name, []))
        # If neither size nor name selected, compare against all work files (fall back)
        if not criteria.get("size") and not criteria.get("name"):
            possible.update(work_files)

        # Evaluate each candidate for matching reasons
        for w in possible:
            reasons = []
            if criteria.get("size") and getattr(r, "size", None) is not None and getattr(w, "size", None) is not None and r.size == w.size:
                reasons.append("size")
            if criteria.get("name") and getattr(r, "name", None) and getattr(w, "name", None) and r.name == w.name:
                reasons.append("name")
            if criteria.get("metadata"):
                reasons += _match_metadata(r, w)

            if use_hash and hash_type:
                # compute or get cached hashes
                h1 = _hash_cache.compute_or_get_hash(r.path, hash_type, hash_size)
                h2 = _hash_cache.compute_or_get_hash(w.path, hash_type, hash_size)
                if h1 and h2:
                    max_bits = hash_size * hash_size
                    # compute hamming
                    dist = _hamming_distance_from_hex(h1, h2, hash_size)
                    # allowed distance
                    allowed = int(round((1.0 - (similarity / 100.0)) * max_bits))
                    if dist <= allowed:
                        reasons.append(f"hash({hash_type})")
                else:
                    # if hashing not available, skip
                    pass

            # Accept pair if any criterion matched
            if reasons:
                unique_reasons = list(dict.fromkeys(reasons))
                matches.append((r, w, unique_reasons))
    return matches

def find_uniques(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> Tuple[List, List]:
    """
    Return (unique_in_ref, unique_in_work) based on simple exact filename/size/metadata key
    depending on criteria. Conservative: if a file's composed key exists in other set, it's not unique.
    """
    def key(f):
        parts = []
        if criteria.get("name"):
            parts.append(f.name or "")
        if criteria.get("size"):
            parts.append(str(f.size) if getattr(f, "size", None) is not None else "")
        if criteria.get("metadata"):
            parts.append(str(f.dimensions) if getattr(f, "dimensions", None) else "")
            parts.append(f.mode or "")
        # If no criteria selected fall back to filename
        if not parts:
            parts.append(f.name or "")
        return "|".join(parts)

    ref_keys = {key(f): f for f in ref_files}
    work_keys = {key(f): f for f in work_files}

    unique_in_ref = []
    unique_in_work = []

    for k, f in ref_keys.items():
        if k not in work_keys:
            unique_in_ref.append(f)
    for k, f in work_keys.items():
        if k not in ref_keys:
            unique_in_work.append(f)

    return unique_in_ref, unique_in_work
"""