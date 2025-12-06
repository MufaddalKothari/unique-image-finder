# core/comparator.py
# Complete comparator implementation providing:
# - find_duplicates(ref_files, work_files, criteria)
# - find_uniques(ref_files, work_files, criteria)
#
# This implementation:
# - Uses HashStore for transient in-memory or on-disk cache (if available)
# - Consults CacheDB (if available) to reuse persisted dhash hex values
# - Computes missing hashes in a ThreadPoolExecutor (safe on macOS)
# - Uses integer popcount((a ^ b)) for Hamming distance checks with a compatibility fallback
#
# The code is defensive: if CacheDB or HashStore are missing it still works.

from typing import List, Tuple, Dict, Any, Optional
import logging
import os
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError
import imagehash

logger = logging.getLogger(__name__)

# Try to import optional modules (these exist in the repo)
try:
    from core.hashstore import HashStore
except Exception:
    HashStore = None

try:
    from core.cache_db import CacheDB
except Exception:
    CacheDB = None

# Default hash size (dhash parameter)
DEFAULT_HASH_SIZE = 16
# Default thread pool size
DEFAULT_MAX_WORKERS = max(1, (os.cpu_count() or 2) - 1)


# --- helpers ----------------------------------------------------------------
def _image_dhash(path: str, hash_size: int = DEFAULT_HASH_SIZE) -> Optional[imagehash.ImageHash]:
    """
    Compute dhash for a file path. Returns an imagehash.ImageHash or None on error.
    """
    try:
        with Image.open(path) as im:
            # apply exif transpose if available
            try:
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            # imagehash.dhash returns ImageHash
            try:
                h = imagehash.dhash(im, hash_size=hash_size)
            except TypeError:
                h = imagehash.dhash(im)
            return h
    except (UnidentifiedImageError, OSError, ValueError) as e:
        logger.debug("Failed to open image for hashing %s: %s", path, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error hashing %s: %s", path, e)
        return None


def _compute_hashes_parallel(paths: List[str], hash_size: int = DEFAULT_HASH_SIZE, max_workers: int = DEFAULT_MAX_WORKERS, timeout_per_future: Optional[float] = None) -> Dict[str, imagehash.ImageHash]:
    """
    Compute hashes for multiple paths in parallel using ThreadPoolExecutor.
    Returns dict path -> ImageHash (only successful entries present).
    """
    out: Dict[str, imagehash.ImageHash] = {}
    if not paths:
        return out
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_image_dhash, p, hash_size): p for p in paths}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                h = fut.result(timeout=timeout_per_future)
                if h is not None:
                    out[p] = h
            except Exception as e:
                logger.debug("Hashing failed for %s: %s", p, e)
    return out


def _hex_to_imagehash(hexstr: str) -> Optional[imagehash.ImageHash]:
    try:
        return imagehash.hex_to_hash(hexstr)
    except Exception:
        return None


def _imagehash_to_int(h: imagehash.ImageHash) -> int:
    # imagehash.ImageHash.__str__ returns hex string
    return int(str(h), 16)


def _popcount(n: int) -> int:
    """
    Portable popcount (works on Python versions without int.bit_count).
    n is non-negative (we call on XOR results).
    """
    try:
        return n.bit_count()  # Python 3.8+
    except AttributeError:
        # fallback for older Python: use bin
        return bin(n).count("1")


def _hamming_distance_int(a: int, b: int) -> int:
    x = a ^ b
    return _popcount(x)


def _max_hamming_from_similarity(hash_bits: int, similarity_percent: float) -> int:
    # similarity_percent is e.g. 90.0 => max allowed hamming bits
    if similarity_percent <= 0:
        return hash_bits
    if similarity_percent >= 100:
        return 0
    max_hamming = int(round((1.0 - (similarity_percent / 100.0)) * hash_bits))
    return max_hamming


# --- core functions ---------------------------------------------------------
def find_duplicates(ref_files: List[Any], work_files: List[Any], criteria: Dict[str, Any]) -> List[Tuple[Any, Any, List[str]]]:
    """
    Find duplicates between ref_files and work_files.
    ref_files / work_files are lists of objects that at minimum have 'path' property.
    Returns list of tuples (ref_file_obj, work_file_obj, [reasons...])
    Criteria keys:
      - hash (bool): whether to do hash-based matching
      - hash_size (int) optional
      - similarity (float) optional (percent, e.g., 90)
      - fields (list) optional - not used here (metadata matching is out of scope)
    """
    matches: List[Tuple[Any, Any, List[str]]] = []
    if not ref_files or not work_files:
        return matches

    use_hash = bool(criteria.get("hash"))
    hash_size = int(criteria.get("hash_size") or DEFAULT_HASH_SIZE)
    similarity = float(criteria.get("similarity") or 90.0)
    hash_bits = hash_size * hash_size
    max_hamming = _max_hamming_from_similarity(hash_bits, similarity)

    logger.debug("find_duplicates: use_hash=%s hash_size=%d similarity=%s%% -> max_hamming=%d", use_hash, hash_size, similarity, max_hamming)

    if not use_hash:
        # fallback: simple path equality / name matching (very basic)
        ref_map = {os.path.basename(f.path): f for f in ref_files if getattr(f, "path", None)}
        for w in work_files:
            name = os.path.basename(getattr(w, "path", ""))
            ref = ref_map.get(name)
            if ref:
                matches.append((ref, w, ["name"]))
        return matches

    # Hash-based flow:
    # 1) prepare path lists
    ref_paths = [f.path for f in ref_files if getattr(f, "path", None)]
    work_paths = [f.path for f in work_files if getattr(f, "path", None)]

    # 2) try to get ref hashes from HashStore (in-memory / transient) and CacheDB
    ref_hash_map: Dict[str, imagehash.ImageHash] = {}
    if HashStore is not None:
        try:
            hs = HashStore()
            try:
                store_hits = hs.bulk_get(ref_paths, hash_size)
                logger.debug("HashStore: cache hits=%d for reference files", len(store_hits))
                # HashStore returns mapping path->ImageHash or maybe hex; ensure type
                for p, hv in store_hits.items():
                    # if hv is a hex string, convert; else assume ImageHash
                    if isinstance(hv, str):
                        ih = _hex_to_imagehash(hv)
                        if ih:
                            ref_hash_map[p] = ih
                    else:
                        ref_hash_map[p] = hv
            finally:
                try:
                    hs.close()
                except Exception:
                    pass
        except Exception as e:
            logger.debug("HashStore unavailable: %s", e)

    # 3) consult CacheDB for missing ref hashes (persisted)
    missing_ref_paths = [p for p in ref_paths if p not in ref_hash_map]
    if CacheDB is not None and missing_ref_paths:
        try:
            cache_db = CacheDB()
            db_hits = cache_db.get_hashes_for_paths(missing_ref_paths, hash_size)
            if db_hits:
                logger.debug("CacheDB: cache hits=%d for reference files", len(db_hits))
                for p, hexv in db_hits.items():
                    ih = _hex_to_imagehash(hexv)
                    if ih:
                        ref_hash_map[p] = ih
        except Exception as e:
            logger.debug("CacheDB lookup failed: %s", e)

    # 4) compute missing ref hashes in parallel
    missing_ref_paths = [p for p in ref_paths if p not in ref_hash_map]
    if missing_ref_paths:
        logger.debug("Computing %d missing reference hashes", len(missing_ref_paths))
        computed = _compute_hashes_parallel(missing_ref_paths, hash_size)
        # computed is path -> ImageHash
        for p, h in computed.items():
            ref_hash_map[p] = h
            # attempt to populate transient HashStore if available
            try:
                if HashStore is not None:
                    try:
                        hs = HashStore()
                        hs.set(p, h, hash_size)
                        hs.close()
                    except Exception:
                        pass
            except Exception:
                pass

    # 5) compute work hashes (do not store them)
    work_hash_map: Dict[str, imagehash.ImageHash] = {}
    if work_paths:
        logger.debug("Computing %d work hashes", len(work_paths))
        work_hash_map = _compute_hashes_parallel(work_paths, hash_size)

    # 6) convert ref_hash_map and work_hash_map to integer bitmasks for fast hamming
    ref_int_map: Dict[str, int] = {}
    for p, h in ref_hash_map.items():
        try:
            ref_int_map[p] = _imagehash_to_int(h)
        except Exception:
            # fallback: skip
            logger.debug("Failed to convert ref hash to int for %s", p)

    work_int_map: Dict[str, int] = {}
    for p, h in work_hash_map.items():
        try:
            work_int_map[p] = _imagehash_to_int(h)
        except Exception:
            logger.debug("Failed to convert work hash to int for %s", p)

    # 7) naive pairwise comparison with early pruning by prefix (if stored)
    # For now do full compare between ref and work items; for large datasets a prefix-index DB query should be used.
    for w_obj in work_files:
        wp = getattr(w_obj, "path", None)
        if not wp or wp not in work_int_map:
            continue
        wint = work_int_map[wp]
        for r_obj in ref_files:
            rp = getattr(r_obj, "path", None)
            if not rp or rp not in ref_int_map:
                continue
            rint = ref_int_map[rp]
            dist = _hamming_distance_int(rint, wint)
            if dist <= max_hamming:
                # record match; could include other reasons/details
                matches.append((r_obj, w_obj, [f"dhash:{dist}"]))
                break

    return matches


def find_uniques(ref_files: List[Any], work_files: List[Any], criteria: Dict[str, Any]) -> Tuple[List[Any], List[Any]]:
    """
    Return (unique_in_ref, unique_in_work) lists.
    If criteria.hash is True, uses hash-based uniqueness detection (fast).
    Otherwise falls back to metadata (size/name) which is less robust.
    """
    uniques_ref: List[Any] = []
    uniques_work: List[Any] = []

    use_hash = bool(criteria.get("hash"))
    hash_size = int(criteria.get("hash_size") or DEFAULT_HASH_SIZE)
    similarity = float(criteria.get("similarity") or 90.0)
    hash_bits = hash_size * hash_size
    max_hamming = _max_hamming_from_similarity(hash_bits, similarity)

    # Quick path: no inputs
    if not ref_files:
        return ([], list(work_files or []))
    if not work_files:
        return (list(ref_files or []), [])

    if not use_hash:
        # basic metadata-based uniqueness: match by size+name
        work_map = {}
        for w in work_files:
            key = (os.path.basename(getattr(w, "path", "")), getattr(w, "size", None))
            work_map.setdefault(key, []).append(w)
        for r in ref_files:
            key = (os.path.basename(getattr(r, "path", "")), getattr(r, "size", None))
            if key not in work_map:
                uniques_ref.append(r)
        # work uniques
        ref_map = {}
        for r in ref_files:
            key = (os.path.basename(getattr(r, "path", "")), getattr(r, "size", None))
            ref_map.setdefault(key, []).append(r)
        for w in work_files:
            key = (os.path.basename(getattr(w, "path", "")), getattr(w, "size", None))
            if key not in ref_map:
                uniques_work.append(w)
        return uniques_ref, uniques_work

    # Hash-based uniqueness:
    ref_paths = [f.path for f in ref_files if getattr(f, "path", None)]
    work_paths = [f.path for f in work_files if getattr(f, "path", None)]

    # Build hash maps using same flow as find_duplicates (CacheDB + HashStore + compute missing)
    ref_hash_map: Dict[str, imagehash.ImageHash] = {}
    work_hash_map: Dict[str, imagehash.ImageHash] = {}

    # Try HashStore for refs
    if HashStore is not None:
        try:
            hs = HashStore()
            try:
                r_hits = hs.bulk_get(ref_paths, hash_size)
                for p, hv in r_hits.items():
                    if isinstance(hv, str):
                        ih = _hex_to_imagehash(hv)
                        if ih:
                            ref_hash_map[p] = ih
                    else:
                        ref_hash_map[p] = hv
            finally:
                try:
                    hs.close()
                except Exception:
                    pass
        except Exception:
            pass

    # Try CacheDB for missing refs
    missing_refs = [p for p in ref_paths if p not in ref_hash_map]
    if CacheDB is not None and missing_refs:
        try:
            cdb = CacheDB()
            db_hits = cdb.get_hashes_for_paths(missing_refs, hash_size)
            for p, hexv in db_hits.items():
                ih = _hex_to_imagehash(hexv)
                if ih:
                    ref_hash_map[p] = ih
        except Exception:
            pass

    # Compute remaining ref hashes
    missing_refs = [p for p in ref_paths if p not in ref_hash_map]
    if missing_refs:
        computed_ref = _compute_hashes_parallel(missing_refs, hash_size)
        for p, h in computed_ref.items():
            ref_hash_map[p] = h
            # attempt to populate HashStore transient cache
            try:
                if HashStore is not None:
                    hs = HashStore()
                    hs.set(p, h, hash_size)
                    hs.close()
            except Exception:
                pass

    # Compute work hashes (do not store)
    work_hash_map = _compute_hashes_parallel(work_paths, hash_size)

    # Convert to ints
    ref_int_map = {p: _imagehash_to_int(h) for p, h in ref_hash_map.items() if h is not None}
    work_int_map = {p: _imagehash_to_int(h) for p, h in work_hash_map.items() if h is not None}

    # Build match sets: mark all work paths that match any ref within threshold
    matched_work_paths = set()
    matched_ref_paths = set()

    for rp, rint in ref_int_map.items():
        for wp, wint in work_int_map.items():
            try:
                dist = _hamming_distance_int(rint, wint)
            except Exception:
                continue
            if dist <= max_hamming:
                matched_ref_paths.add(rp)
                matched_work_paths.add(wp)

    # uniques are those not matched
    ref_map_by_path = {f.path: f for f in ref_files if getattr(f, "path", None)}
    work_map_by_path = {f.path: f for f in work_files if getattr(f, "path", None)}

    for p in ref_paths:
        if p not in matched_ref_paths:
            if p in ref_map_by_path:
                uniques_ref.append(ref_map_by_path[p])
    for p in work_paths:
        if p not in matched_work_paths:
            if p in work_map_by_path:
                uniques_work.append(work_map_by_path[p])

    return uniques_ref, uniques_work