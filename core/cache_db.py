import os
import sqlite3
import json
import time
import threading
from typing import Optional, List, Dict, Any

DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".unique_image_finder", "cache.db")


class CacheDB:
    """
    Lightweight SQLite wrapper for cached directories, files and jobs.
    Thread-safe (simple lock) for single-process use.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
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

    # ----- dir operations -----
    def add_dir(self, path: str, prefix_bits: int = 16) -> int:
        with self._lock:
            cur = self._conn.cursor()
            now = int(time.time())
            try:
                cur.execute(
                    "INSERT INTO dirs (path, prefix_bits, last_indexed, status) VALUES (?, ?, ?, ?)",
                    (path, prefix_bits, None, "idle"),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                # already exists
                pass
            cur.execute("SELECT dir_id FROM dirs WHERE path = ?", (path,))
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
    def upsert_file(self, path: str, dir_id: int, size: int, mtime: int, hash_hex: Optional[str], prefix: Optional[int], hash_size: int):
        now = int(time.time())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO files (path, dir_id, size, mtime, hash_hex, prefix, hash_size, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ok', ?)
                ON CONFLICT(path) DO UPDATE SET
                    size=excluded.size, mtime=excluded.mtime, hash_hex=excluded.hash_hex,
                    prefix=excluded.prefix, hash_size=excluded.hash_size, status='ok', updated_at=excluded.updated_at
                """,
                (path, dir_id, size, mtime, hash_hex, prefix, hash_size, now),
            )
            self._conn.commit()
            cur.close()

    def delete_files_for_dir(self, dir_id: int, paths: Optional[List[str]] = None):
        with self._lock:
            cur = self._conn.cursor()
            if paths:
                cur.executemany("DELETE FROM files WHERE path = ? AND dir_id = ?", [(p, dir_id) for p in paths])
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

    def update_job_progress(self, job_id: int, progress: float):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("UPDATE jobs SET progress = ? WHERE job_id = ?", (float(progress), job_id))
            self._conn.commit()
            cur.close()

    def get_hashes_for_paths(self, paths: List[str], hash_size: Optional[int] = None) -> Dict[str, str]:
        """
        Return a dict path -> hash_hex for the given paths if present in DB.
        If hash_size is provided, prefer rows with that hash_size (otherwise return any).
        """
        if not paths:
            return {}
        with self._lock:
            cur = self._conn.cursor()
            placeholders = ",".join("?" for _ in paths)
            if hash_size is not None:
                query = f"SELECT path, hash_hex FROM files WHERE path IN ({placeholders}) AND hash_size = ?"
                cur.execute(query, (*paths, int(hash_size)))
            else:
                query = f"SELECT path, hash_hex FROM files WHERE path IN ({placeholders})"
                cur.execute(query, tuple(paths))
            out = {}
            for r in cur.fetchall():
                if r["hash_hex"]:
                    out[r["path"]] = r["hash_hex"]
            cur.close()
            return out

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass