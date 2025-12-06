# core/comparator.py
# ... (file header and imports, unchanged) ...
from typing import List, Tuple, Dict, Any
from datetime import datetime
from PIL import Image, ImageOps
import imagehash
import logging
import os
import concurrent.futures

from core.hashstore import HashStore
# New import: CacheDB to read persisted hashes
try:
    from core.cache_db import CacheDB
except Exception:
    CacheDB = None

logger = logging.getLogger(__name__)

# existing constants and in-memory _hash_cache as before ...
DEFAULT_HASH_SIZE = 16

_hash_cache: Dict[Tuple, Tuple[Dict[str, imagehash.ImageHash], Dict[str, imagehash.ImageHash]]] = {}

# ... helper functions (_compute_dhash_for_path, _compute_hashes_parallel, _imagehash_to_int, etc.) remain unchanged ...

def find_duplicates(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> List[Tuple]:
    matches = []
    if not ref_files or not work_files:
        return matches

    # ... field-based and legacy matching logic unchanged ...

    # 3) Hash-based matching (dhash only), using HashStore for reference files.
    if criteria.get("hash"):
        hash_size = int(criteria.get("hash_size") or DEFAULT_HASH_SIZE)
        similarity_threshold = float(criteria.get("similarity") or 90.0)

        ref_paths = [f.path for f in ref_files if getattr(f, "path", None)]
        work_paths = [f.path for f in work_files if getattr(f, "path", None)]

        logger.debug("Starting dhash matching: ref=%d work=%d hash_size=%d similarity=%s%%",
                     len(ref_paths), len(work_paths), hash_size, similarity_threshold)

        # Build cache key and check transient in-memory cache first
        key = _make_hash_key(ref_paths, work_paths, hash_size, similarity_threshold)
        if key in _hash_cache:
            ref_hashes, work_hashes = _hash_cache[key]
            logger.debug("Using transient in-memory hash cache for this search (ref=%d, work=%d)", len(ref_hashes), len(work_hashes))
        else:
            store = HashStore()
            try:
                # fetch cached ref hashes from existing HashStore
                cached_ref_hashes = store.bulk_get(ref_paths, hash_size) if ref_paths else {}
                logger.debug("HashStore: cache hits=%d for reference files", len(cached_ref_hashes))
                # --- NEW: also consult CacheDB if available to retrieve persisted hashes ---
                try:
                    if CacheDB is not None:
                        cache_db = CacheDB()
                        missing_ref_paths = [p for p in ref_paths if p not in cached_ref_hashes]
                        if missing_ref_paths:
                            db_rows = cache_db.get_hashes_for_paths(missing_ref_paths, hash_size)
                            if db_rows:
                                logger.debug("CacheDB: cache hits=%d for reference files", len(db_rows))
                                # convert hex -> ImageHash and merge
                                for p, hexv in db_rows.items():
                                    try:
                                        img_hash = imagehash.hex_to_hash(hexv)
                                        cached_ref_hashes[p] = img_hash
                                    except Exception:
                                        # fallback: skip conversion error
                                        logger.debug("Failed to convert hex hash for %s from CacheDB", p)
                except Exception as e:
                    logger.debug("CacheDB lookup failed: %s", e)

                # compute missing ref hashes and persist to HashStore if necessary
                missing_ref = [p for p in ref_paths if p not in cached_ref_hashes]
                computed_ref = _compute_hashes_parallel(missing_ref, hash_size) if missing_ref else {}
                logger.debug("Computed %d missing reference hashes", len(computed_ref))
                for p, h in computed_ref.items():
                    try:
                        store.set(p, h, hash_size)
                    except Exception:
                        logger.debug("Failed to store hash for %s", p)

                # combine
                ref_hashes = {}
                ref_hashes.update(cached_ref_hashes)
                ref_hashes.update(computed_ref)

                # compute work hashes on-the-fly (do NOT store)
                work_hashes = _compute_hashes_parallel(work_paths, hash_size) if work_paths else {}
                logger.debug("Computed %d work hashes", len(work_hashes))
            finally:
                try:
                    store.close()
                except Exception:
                    pass

            # store in transient cache for reuse by find_uniques later in the same search
            _hash_cache[key] = (ref_hashes, work_hashes)

        # rest of the comparator logic (bucket/prefix, comparisons using _hash_hamming_distance) remains unchanged...
        # (copy the rest of your comparator implementation here unchanged)
        # ...
        # (return matches at end)
    return matches