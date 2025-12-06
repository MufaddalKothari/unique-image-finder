"""
Simple background indexing worker.

- Polls CacheDB job queue (jobs table).
- For index / refresh / rehash jobs, computes dhash using Pillow + imagehash via a ThreadPoolExecutor.
- Writes results back to CacheDB in batches.

This is a straightforward single-process worker designed for desktop use.
"""
import os
import time
import threading
import concurrent.futures
from typing import List, Dict, Any, Optional

from PIL import Image, ImageOps, UnidentifiedImageError
import imagehash

from core.cache_db import CacheDB
import logging

logger = logging.getLogger(__name__)


def _compute_dhash(path: str, hash_size: int = 16) -> Dict[str, Any]:
    try:
        with Image.open(path) as im:
            try:
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            try:
                h = imagehash.dhash(im, hash_size=hash_size)
            except TypeError:
                h = imagehash.dhash(im)
            return {"hex": str(h), "int": int(str(h), 16)}
    except (UnidentifiedImageError, OSError, ValueError) as e:
        return {"error": f"cannot open image: {e}"}
    except Exception as e:
        return {"error": str(e)}


class Indexer:
    def __init__(self, db: Optional[CacheDB] = None, max_workers: Optional[int] = None):
        self.db = db or CacheDB()
        self._stop = threading.Event()
        cpu = os.cpu_count() or 2
        default_workers = min(8, max(1, cpu - 1))
        self.max_workers = max_workers or default_workers
        self._thread = None
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)

        # config
        self.batch_size = 64
        self.hash_size = 16
        self.prefix_bits_default = 16

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Indexer started with %d workers", self.max_workers)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass

    def enqueue(self, job_type: str, dir_id: Optional[int] = None, params: Optional[Dict] = None):
        return self.db.enqueue_job(job_type, dir_id, params)

    def _run_loop(self):
        while not self._stop.is_set():
            job = self.db.dequeue_job()
            if not job:
                time.sleep(0.6)
                continue
            try:
                self._run_job(job)
                self.db.update_job_state(job["job_id"], "completed", progress=1.0)
            except Exception as e:
                logger.exception("Job failed: %s", e)
                self.db.update_job_state(job["job_id"], "failed", last_error=str(e))
            # small sleep to yield
            time.sleep(0.05)

    def _run_job(self, job: Dict[str, Any]):
        job_type = job["job_type"]
        dir_id = job.get("dir_id")
        job_id = job["job_id"]
        logger.info("Processing job: %s id=%s dir=%s", job_type, job_id, dir_id)
        if job_type == "index":
            self._run_index(dir_id, job_id)
        elif job_type == "refresh":
            self._run_refresh(dir_id, job_id)
        elif job_type == "rehash":
            self._run_rehash(dir_id, job_id)
        elif job_type == "gc":
            self._run_gc(job_id)
        else:
            logger.warning("Unknown job type: %s", job_type)

    def _collect_files(self, root: str) -> List[Dict[str, Any]]:
        out = []
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                    out.append({"path": p, "size": st.st_size, "mtime": int(st.st_mtime)})
                except Exception:
                    continue
        return out

    def _run_index(self, dir_id: int, job_id: int):
        d = self.db.get_dir(dir_id)
        if not d:
            raise RuntimeError("dir not found for id=%s" % dir_id)
        dir_path = d["path"]
        self.db.update_dir_status(dir_id, "indexing")
        entries = self._collect_files(dir_path)
        existing_rows = {r["path"]: r for r in self.db.get_files_by_dir(dir_id)}
        to_process = []
        to_delete = []
        for e in entries:
            if e["path"] not in existing_rows:
                to_process.append(e)
            else:
                row = existing_rows[e["path"]]
                if (row.get("size") != e["size"]) or (row.get("mtime") != e["mtime"]):
                    to_process.append(e)
        for p in existing_rows.keys():
            if not os.path.exists(p):
                to_delete.append(p)
        # delete removed
        if to_delete:
            self.db.delete_files_for_dir(dir_id, to_delete)
        total = max(1, len(to_process))
        processed = 0
        # process in batches
        for i in range(0, len(to_process), self.batch_size):
            batch = to_process[i : i + self.batch_size]
            futures = {self._executor.submit(_compute_dhash, it["path"], self.hash_size): it for it in batch}
            for fut in concurrent.futures.as_completed(futures):
                fmeta = futures[fut]
                res = fut.result()
                if "error" in res:
                    # upsert as error status
                    self.db.upsert_file(fmeta["path"], dir_id, fmeta["size"], fmeta["mtime"], None, None, self.hash_size)
                else:
                    hexv = res["hex"]
                    intv = res["int"]
                    prefix = intv >> (self.hash_size * self.hash_size - self.prefix_bits_default) if self.prefix_bits_default < (self.hash_size*self.hash_size) else intv
                    self.db.upsert_file(fmeta["path"], dir_id, fmeta["size"], fmeta["mtime"], hexv, prefix, self.hash_size)
                processed += 1
                self.db.update_job_progress(job_id, processed / total)
        self.db.update_dir_status(dir_id, "idle", last_indexed=int(time.time()))

    def _run_refresh(self, dir_id: int, job_id: int):
        # For simplicity, refresh calls index run (incremental behavior above)
        self._run_index(dir_id, job_id)

    def _run_rehash(self, dir_id: int, job_id: int):
        d = self.db.get_dir(dir_id)
        if not d:
            raise RuntimeError("dir not found")
        rows = self.db.get_files_by_dir(dir_id)
        total = max(1, len(rows))
        processed = 0
        for i in range(0, len(rows), self.batch_size):
            batch = rows[i : i + self.batch_size]
            futures = {self._executor.submit(_compute_dhash, r["path"], self.hash_size): r for r in batch}
            for fut in concurrent.futures.as_completed(futures):
                row = futures[fut]
                res = fut.result()
                if "error" in res:
                    self.db.upsert_file(row["path"], dir_id, row.get("size", 0), row.get("mtime", 0), None, None, self.hash_size)
                else:
                    hexv = res["hex"]
                    intv = res["int"]
                    prefix = intv >> (self.hash_size * self.hash_size - self.prefix_bits_default) if self.prefix_bits_default < (self.hash_size*self.hash_size) else intv
                    self.db.upsert_file(row["path"], dir_id, row.get("size", 0), row.get("mtime", 0), hexv, prefix, self.hash_size)
                processed += 1
                self.db.update_job_progress(job_id, processed / total)
        self.db.update_dir_status(dir_id, "idle", last_indexed=int(time.time()))

    def _run_gc(self, job_id: int):
        # simple no-op for now; could remove missing rows older than threshold
        time.sleep(0.1)
        self.db.update_job_state(job_id, "completed", progress=1.0)