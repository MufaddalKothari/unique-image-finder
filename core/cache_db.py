import os
import sqlite3
import json
import time
import threading
import logging
from typing import Optional, List, Dict, Any, Tuple

from pathlib import Path

LOG = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".unique_image_finder", "cache.db")


def _normalize_path(path: str) -> str:
    """
    Normalize a path to a stable canonical form used as the DB key.
    Uses Path.resolve(strict=False) with a fallback to abspath. This avoids
    mismatch like "./img.jpg" vs "/abs/path/img.jpg" or minor symlink differences.
    """
    try:
        return str(Path(path).expanduser().resolve(strict=False))
    except Exception:
        return os.path.abspath(path)


def _stat_path(path: str) -> Optional[Tuple[int, int]]:
    """
    Return (mtime, size) as integers for stable comparisons, or None if stat fails.
    mtime is returned as int(seconds) to match storage in the DB.
    """
    try:
        st = os.stat(path)
        return (int(st.st_mtime), int(st.st_size))
    except Exception:
        return None


class CacheDB:
    """
    Lightweight SQLite wrapper for cached directories, files and jobs.
    Thread-safe (simple lock) for single-process use.

    Notes on improvements made:
    - Paths are normalized before storing and before lookup to avoid cache-key mismatches.
    - upsert_file now stores normalized path and records a status ('ok' or 'unreadable').
    - get_hashes_for_paths validates stored mtime/size (and hash_size when provided)
      against current file metadata before returning a hash. The returned dict keys
      are the original input paths (preserving existing caller expectations).
    - Added methods to reset/clear the DB so you can start from scratch.
    - Added informational logging in upsert_file so callers can see when a file gets persisted.
    - Added bulk_upsert_files to efficiently insert/update many rows in a single transaction
      and produce a single summary log entry.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
        # use check_same_thread=False so connection may be used across threads with explicit locking
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._apply_pragmas()
        self._init_schema()

    def _apply_pragmas(self):
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.close()

    def _init_schema(self):
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS dirs (
                  dir_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  path TEXT UNIQUE NOT NULL,
                  prefix_bits INTEGER NOT NULL DEFAULT 16,
                  last_indexed INTEGER,
                  status TEXT,
                  note TEXT
                );

                CREATE TABLE IF NOT EXISTS files (
                  path TEXT PRIMARY KEY,
                  dir_id INTEGER NOT NULL,
                  size INTEGER,
                  mtime INTEGER,
                  hash_hex TEXT,
                  prefix INTEGER,
                  hash_size INTEGER NOT NULL DEFAULT 16,
                  status TEXT,
                  updated_at INTEGER,
                  FOREIGN KEY(dir_id) REFERENCES dirs(dir_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_files_dir_prefix ON files(dir_id, prefix);

                CREATE TABLE IF NOT EXISTS jobs (
                  job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  dir_id INTEGER,
                  job_type TEXT NOT NULL,
                  params TEXT,
                  state TEXT NOT NULL DEFAULT 'queued',
                  progress REAL DEFAULT 0.0,
                  created_at INTEGER,
                  started_at INTEGER,
                  finished_at INTEGER,
                  last_error TEXT,
                  FOREIGN KEY(dir_id) REFERENCES dirs(dir_id) ON DELETE SET NULL
                );
                """
            )
            self._conn.commit()
            cur.close()

    # ----- DB reset / clear utilities -----
    def reset_database(self, backup: bool = True) -> None:
        """
        Reset the entire database file and recreate schema.

        If backup=True the existing DB file will be renamed with a timestamp suffix before recreating.
        This is the cleanest way to "start from scratch".
        """
        with self._lock:
            # close current connection
            try:
                self._conn.close()
            except Exception:
                pass

            if os.path.exists(self.path):
                if backup:
                    ts = int(time.time())
                    bak = f"{self.path}.bak.{ts}"
                    try:
                        os.replace(self.path, bak)
                        LOG.info("CacheDB: existing DB backed up to %s", bak)
                    except Exception as e:
                        LOG.warning("CacheDB: failed to backup DB to %s: %s", bak, e)
                        try:
                            os.remove(self.path)
                        except Exception:
                            LOG.exception("CacheDB: failed to remove DB file %s", self.path)
                else:
                    try:
                        os.remove(self.path)
                    except Exception:
                        LOG.exception("CacheDB: failed to remove DB file %s", self.path)

            # re-create connection and schema
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._apply_pragmas()
            self._init_schema()
            LOG.info("CacheDB: reset database at %s", self.path)

    def clear_all_rows(self) -> None:
        """
        Keep the DB file but delete all rows from files, dirs and jobs.
        Useful if you want the same file but start indexing from scratch.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM files")
            cur.execute("DELETE FROM dirs")
            cur.execute("DELETE FROM jobs")
            self._conn.commit()
            cur.close()
            LOG.info("CacheDB: cleared all rows from database %s", self.path)

    # ----- dir operations -----
    def add_dir(self, path: str, prefix_bits: int = 16) -> int:
        """
        Insert or return an existing dir_id for the normalized directory path.
        """
        p_norm = _normalize_path(path)
        with self._lock:
            cur = self._conn.cursor()
            now = int(time.time())
            try:
                cur.execute(
                    "INSERT INTO dirs (path, prefix_bits, last_indexed, status) VALUES (?, ?, ?, ?)",
                    (p_norm, prefix_bits, None, "idle"),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                # already exists
                pass
            cur.execute("SELECT dir_id FROM dirs WHERE path = ?", (p_norm,))
            row = cur.fetchone()
            cur.close()
            return row["dir_id"]

    def list_dirs(self) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM dirs ORDER BY dir_id DESC")
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows

    def get_dir(self, dir_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM dirs WHERE dir_id = ?", (dir_id,))
            r = cur.fetchone()
            cur.close()
            return dict(r) if r else None

    def remove_dir(self, dir_id: int):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM files WHERE dir_id = ?", (dir_id,))
            cur.execute("DELETE FROM dirs WHERE dir_id = ?", (dir_id,))
            self._conn.commit()
            cur.close()

    def update_dir_status(self, dir_id: int, status: str, last_indexed: Optional[int] = None):
        with self._lock:
            cur = self._conn.cursor()
            if last_indexed is not None:
                cur.execute(
                    "UPDATE dirs SET status = ?, last_indexed = ? WHERE dir_id = ?",
                    (status, last_indexed, dir_id),
                )
            else:
                cur.execute("UPDATE dirs SET status = ? WHERE dir_id = ?", (status, dir_id))
            self._conn.commit()
            cur.close()

    # ----- file operations -----
    def upsert_file(
        self,
        path: str,
        dir_id: int,
        size: int,
        mtime: int,
        hash_hex: Optional[str],
        prefix: Optional[int],
        hash_size: int,
    ):
        """
        Insert or update a file row. Path is normalized before storage to ensure consistent keys.
        If hash_hex is None, the row's status will be set to 'unreadable' so callers can skip it quickly.

        This method now logs an informational message when a file's precomputed hash is stored
        (or when it is marked unreadable). This is the recommended place to emit "file added
        to precomputed DB" logs because upsert_file is the canonical write path for cached files.
        """
        now = int(time.time())
        p_norm = _normalize_path(path)
        status = "ok" if hash_hex else "unreadable"
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO files (path, dir_id, size, mtime, hash_hex, prefix, hash_size, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    size=excluded.size, mtime=excluded.mtime, hash_hex=excluded.hash_hex,
                    prefix=excluded.prefix, hash_size=excluded.hash_size, status=excluded.status, updated_at=excluded.updated_at
                """,
                (p_norm, dir_id, int(size), int(mtime), hash_hex, prefix, int(hash_size), status, now),
            )
            self._conn.commit()
            cur.close()

            # Informational logging: callers can monitor these logs to confirm precomputation storage.
            if hash_hex:
                LOG.info("CacheDB: stored precomputed hash for %s (dir_id=%s, hash_size=%s)", p_norm, dir_id, hash_size)
            else:
                LOG.info("CacheDB: stored unreadable sentinel for %s (dir_id=%s)", p_norm, dir_id)

    def bulk_upsert_files(
        self,
        files: List[Dict[str, Any]],
        dir_id: int,
        default_hash_size: int,
        batch_size: int = 500,
    ) -> int:
        """
        Efficiently insert or update many file rows in a single transaction (batched).
        `files` is a list of dict-like items with keys:
            - path (required)
            - size (optional; fallback to 0)
            - mtime (optional; fallback to 0)
            - hash_hex (optional; if missing -> 'unreadable' status)
            - prefix (optional; may be None)
            - hash_size (optional; if missing uses default_hash_size)

        Returns the number of rows processed (inserted or updated).
        Produces a single INFO log summarizing the result.
        """
        if not files:
            return 0

        now = int(time.time())
        tuples: List[Tuple[Any, ...]] = []
        for f in files:
            path = f.get("path")
            if not path:
                continue
            p_norm = _normalize_path(path)
            size = int(f.get("size") or 0)
            mtime = int(f.get("mtime") or 0)
            hash_hex = f.get("hash_hex")
            prefix = f.get("prefix")
            hash_size = int(f.get("hash_size") or default_hash_size)
            status = "ok" if hash_hex else "unreadable"
            tuples.append((p_norm, dir_id, size, mtime, hash_hex, prefix, hash_size, status, now))

        if not tuples:
            return 0

        stmt = """
                INSERT INTO files (path, dir_id, size, mtime, hash_hex, prefix, hash_size, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    size=excluded.size, mtime=excluded.mtime, hash_hex=excluded.hash_hex,
                    prefix=excluded.prefix, hash_size=excluded.hash_size, status=excluded.status, updated_at=excluded.updated_at
                """

        processed = 0
        with self._lock:
            cur = self._conn.cursor()
            try:
                # batch executemany for memory safety on large lists
                for i in range(0, len(tuples), batch_size):
                    batch = tuples[i : i + batch_size]
                    cur.executemany(stmt, batch)
                    processed += len(batch)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                LOG.exception("CacheDB: bulk_upsert_files failed; rolled back transaction")
                cur.close()
                return 0
            cur.close()

        LOG.info("CacheDB: bulk upserted %d files into dir_id=%s (hash_size=%s)", processed, dir_id, default_hash_size)
        return processed

    def delete_files_for_dir(self, dir_id: int, paths: Optional[List[str]] = None):
        with self._lock:
            cur = self._conn.cursor()
            if paths:
                # normalize incoming paths for deletion
                tuples = [(_normalize_path(p), dir_id) for p in paths]
                cur.executemany("DELETE FROM files WHERE path = ? AND dir_id = ?", tuples)
            else:
                cur.execute("DELETE FROM files WHERE dir_id = ?", (dir_id,))
            self._conn.commit()
            cur.close()

    def get_files_by_dir(self, dir_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM files WHERE dir_id = ?", (dir_id,))
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows

    # ----- jobs -----
    def enqueue_job(self, job_type: str, dir_id: Optional[int] = None, params: Optional[dict] = None) -> int:
        now = int(time.time())
        params_json = json.dumps(params or {})
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO jobs (dir_id, job_type, params, state, progress, created_at) VALUES (?, ?, ?, 'queued', 0.0, ?)",
                (dir_id, job_type, params_json, now),
            )
            job_id = cur.lastrowid
            self._conn.commit()
            cur.close()
            return job_id

    def dequeue_job(self) -> Optional[Dict[str, Any]]:
        """
        Basic dequeue: try to atomically pick the oldest queued job and mark running.
        NOTE: not perfect concurrency for multi-process; designed for single-process worker.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT job_id FROM jobs WHERE state = 'queued' ORDER BY created_at ASC LIMIT 1")
            r = cur.fetchone()
            if not r:
                cur.close()
                return None
            job_id = r["job_id"]
            now = int(time.time())
            cur.execute("UPDATE jobs SET state = 'running', started_at = ? WHERE job_id = ?", (now, job_id))
            self._conn.commit()
            cur.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            job = dict(cur.fetchone())
            cur.close()
            # parse params
            job["params"] = json.loads(job.get("params") or "{}")
            return job

    def update_job_state(self, job_id: int, state: str, progress: Optional[float] = None, last_error: Optional[str] = None):
        with self._lock:
            cur = self._conn.cursor()
            now = int(time.time())
            if state in ("completed", "failed", "cancelled"):
                cur.execute(
                    "UPDATE jobs SET state = ?, progress = ?, last_error = ?, finished_at = ? WHERE job_id = ?",
                    (state, progress or 1.0, last_error, now, job_id),
                )
            else:
                cur.execute(
                    "UPDATE jobs SET state = ?, progress = ?, last_error = ? WHERE job_id = ?",
                    (state, progress or 0.0, last_error, job_id),
                )
            self._conn.commit()
            cur.close()

            # Optional: if job completed and params include a 'processed_count', log summary here.
            if state == "completed":
                try:
                    # Attempt to read processed_count from job params (not enforced)
                    cur = self._conn.cursor()
                    cur.execute("SELECT params FROM jobs WHERE job_id = ?", (job_id,))
                    r = cur.fetchone()
                    if r:
                        params = json.loads(r["params"] or "{}")
                        processed = params.get("processed_count")
                        if processed is not None:
                            LOG.info("CacheDB: job %s completed, processed %d files", job_id, int(processed))
                    cur.close()
                except Exception:
                    LOG.debug("CacheDB: could not read job params for summary log for job %s", job_id)

    def update_job_progress(self, job_id: int, progress: float):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("UPDATE jobs SET progress = ? WHERE job_id = ?", (float(progress), job_id))
            self._conn.commit()
            cur.close()

    def get_hashes_for_paths(self, paths: List[str], hash_size: Optional[int] = None) -> Dict[str, str]:
        """
        Return a dict mapping the original input path -> hash_hex for the given paths if present and valid in DB.

        Validation rules:
        - The stored row's status must not be 'unreadable'
        - If hash_size is provided the stored hash_size must match
        - The stored mtime and size must match the current file stat (prevents stale reuse)

        This function preserves the original caller's path strings as keys in the returned dict
        (so existing callers do not need to change).
        """
        if not paths:
            return {}
        out: Dict[str, str] = {}
        with self._lock:
            cur = self._conn.cursor()
            # Build mapping original -> normalized to allow single-row lookups
            orig_to_norm = {p: _normalize_path(p) for p in paths}
            # Query for all normalized paths that exist in DB
            placeholders = ",".join("?" for _ in orig_to_norm)
            query = f"SELECT path, mtime, size, hash_hex, status, hash_size FROM files WHERE path IN ({placeholders})"
            cur.execute(query, tuple(orig_to_norm.values()))
            rows = {r["path"]: r for r in cur.fetchall()}

            for orig_p, p_norm in orig_to_norm.items():
                stat = _stat_path(orig_p)
                if stat is None:
                    # file currently missing/unreadable on disk
                    continue
                mtime, size = stat
                row = rows.get(p_norm)
                if not row:
                    continue
                r_mtime = int(row["mtime"]) if row["mtime"] is not None else None
                r_size = int(row["size"]) if row["size"] is not None else None
                r_hash_hex = row["hash_hex"]
                r_status = row["status"]
                r_hash_size = int(row["hash_size"]) if row["hash_size"] is not None else None

                if r_status == "unreadable":
                    continue
                if r_hash_hex is None:
                    continue
                if hash_size is not None and r_hash_size is not None and int(r_hash_size) != int(hash_size):
                    # stored hash size doesn't match requested; skip (caller may re-compute)
                    continue
                # Validate metadata (mtime+size)
                if r_mtime == mtime and r_size == size:
                    out[orig_p] = r_hash_hex
            cur.close()
            return out

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass