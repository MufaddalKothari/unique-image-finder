"""
core/comparator.py

Comparator updated to:
- Use dhash (difference hash) as the single, fixed perceptual hash algorithm.
- When hash-based matching is requested and the UI asks for uniques (find_uniques_ref / find_uniques_work),
  compute the duplicate pairs using dhash, then invert that set to return uniques (images that did NOT participate
  in any duplicate pair). This ensures "find uniques" with hashing returns files not matched by hash pairs.

Notes:
- Hash computation runs in parallel with a per-file timeout to avoid hangs.
- Bucketing by hash prefix is used when datasets are large to reduce pairwise comparisons.
- Debug logs are emitted for hashing progress and counts. Enable logging.debug in main.py to see them.
- Reference hashes are cached using core.hashstore.HashStore (SQLite-backed).
"""
from typing import List, Tuple, Dict, Any
from datetime import datetime
from PIL import Image, ImageOps
import imagehash
import logging
import os
import concurrent.futures

from core.hashstore import HashStore

logger = logging.getLogger(__name__)

# Default hash size for dhash (16x16 produces 256-bit hashes)
DEFAULT_HASH_SIZE = 16


def _get_field_value(f, field_name):
    """Return a normalized value for the given field on ImageFileObj f."""
    val = None
    if field_name == "name":
        val = getattr(f, "name", None)
    elif field_name == "size":
        val = getattr(f, "size", None)
    elif field_name == "mtime":
        val = getattr(f, "mtime", None)
    elif field_name == "created":
        val = getattr(f, "created", None)
    elif field_name == "dimensions":
        val = getattr(f, "dimensions", None)
    elif field_name == "mode":
        val = getattr(f, "mode", None)
    elif field_name == "make":
        val = getattr(f, "make", None)
    elif field_name == "model":
        val = getattr(f, "model", None)
    elif field_name == "artist":
        val = getattr(f, "artist", None)
    elif field_name == "copyright":
        val = getattr(f, "copyright", None)
    elif field_name == "datetime_original":
        val = getattr(f, "datetime_original", None)
    elif field_name == "origin":
        val = getattr(f, "origin", None)
    else:
        val = getattr(f, field_name, None)

    if val is None:
        return None
    if isinstance(val, (tuple, list)):
        return tuple(val)
    if isinstance(val, int):
        return int(val)
    s = str(val).strip()
    if field_name in ("name", "artist", "copyright", "make", "model", "origin"):
        s = s.lower()
    return s


def _build_key(f, fields: List[str]):
    parts = []
    for fld in fields:
        parts.append(str(_get_field_value(f, fld)))
    return "|".join(parts)


def _match_metadata(a, b):
    """Local metadata matching fallback."""
    reasons = []
    if getattr(a, "dimensions", None) and getattr(b, "dimensions", None) and a.dimensions == b.dimensions:
        reasons.append("dimensions")
    if getattr(a, "mode", None) and getattr(b, "mode", None) and a.mode == b.mode:
        reasons.append("mode")
    if getattr(a, "created", None) is not None and getattr(b, "created", None) is not None:
        try:
            if int(a.created) == int(b.created):
                reasons.append("created")
        except Exception:
            pass
    ca = getattr(a, "copyright", None)
    cb = getattr(b, "copyright", None)
    if ca and cb and str(ca).strip() == str(cb).strip():
        reasons.append("copyright")
    aa = getattr(a, "artist", None)
    ab = getattr(b, "artist", None)
    if aa and ab and str(aa).strip() == str(ab).strip():
        reasons.append("artist")
    da = getattr(a, "datetime_original", None)
    db = getattr(b, "datetime_original", None)
    if da and db and str(da).strip() == str(db).strip():
        reasons.append("datetime_original")
    ma = getattr(a, "make", None)
    mb = getattr(b, "make", None)
    if ma and mb and str(ma).strip() == str(mb).strip():
        reasons.append("make")
    moa = getattr(a, "model", None)
    mob = getattr(b, "model", None)
    if moa and mob and str(moa).strip() == str(mob).strip():
        reasons.append("model")
    ia = getattr(a, "image_description", None)
    ib = getattr(b, "image_description", None)
    if ia and ib and str(ia).strip() == str(ib).strip():
        reasons.append("image_description")
    oa = getattr(a, "origin", None)
    ob = getattr(b, "origin", None)
    if oa and ob and str(oa).strip() == str(ob).strip():
        reasons.append("origin")
    return reasons


# ---------- Hash helpers (dhash, parallel safe with per-file timeout) ----------

def _compute_dhash_for_path(path: str, hash_size: int):
    """Compute dhash for a single path. Returns (path, ImageHash) or raises."""
    if not path or not os.path.exists(path):
        raise FileNotFoundError(path)
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
        return path, h


def _compute_hashes_parallel(paths: List[str], hash_size: int, max_workers: int = None, per_file_timeout: float = 8.0):
    """
    Compute dhash for each path in parallel with per-file timeout.
    Returns dict path->ImageHash for successful computations.
    """
    result = {}
    if not paths:
        return result

    try:
        cpu = os.cpu_count() or 2
        default_workers = min(8, max(1, cpu))
    except Exception:
        default_workers = 4
    max_workers = max_workers or default_workers

    logger.debug("Starting dhash computation for %d files (workers=%d, timeout=%.1fs)", len(paths), max_workers, per_file_timeout)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_compute_dhash_for_path, p, hash_size): p for p in paths}
        for fut in concurrent.futures.as_completed(futures):
            p = futures[fut]
            try:
                path, h = fut.result(timeout=per_file_timeout)
                result[path] = h
            except concurrent.futures.TimeoutError:
                logger.warning("Hash computation timed out for %s (>%ss). Skipping.", p, per_file_timeout)
                try:
                    fut.cancel()
                except Exception:
                    pass
            except Exception as e:
                logger.debug("Hash computation failed for %s: %s", p, e)
    logger.debug("Completed dhash: computed %d hashes (requested %d files)", len(result), len(paths))
    return result


def _imagehash_to_int(h: imagehash.ImageHash) -> int:
    """Convert ImageHash.hash boolean array into an integer bitmask (flattened row-major)."""
    arr = getattr(h, "hash", None)
    if arr is None:
        try:
            return int(str(h), 16)
        except Exception:
            return 0
    flat = arr.flatten().astype(int)
    bits = 0
    for b in flat:
        bits = (bits << 1) | (1 if b else 0)
    return bits


def _hash_hamming_distance(h1: imagehash.ImageHash, h2: imagehash.ImageHash) -> int:
    """Return Hamming distance (integer) between two ImageHash objects."""
    try:
        arr1 = getattr(h1, "hash", None)
        arr2 = getattr(h2, "hash", None)
        if arr1 is not None and arr2 is not None:
            try:
                import numpy as _np
                return int(_np.count_nonzero(arr1 != arr2))
            except Exception:
                flat1 = list(arr1.flatten()) if hasattr(arr1, "flatten") else list(arr1)
                flat2 = list(arr2.flatten()) if hasattr(arr2, "flatten") else list(arr2)
                return sum(1 for a, b in zip(flat1, flat2) if a != b)
        else:
            return int(h1 - h2)
    except Exception:
        try:
            return int(h1 - h2)
        except Exception:
            return 0


def _hash_similarity_percent_from_distance(dist: int, num_bits: int) -> float:
    if num_bits == 0:
        return 0.0
    sim = 100.0 * (1.0 - (dist / float(num_bits)))
    return max(0.0, min(100.0, sim))


# ---------- Main comparator functions ----------

def find_duplicates(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> List[Tuple]:
    """
    Find duplicate pairs: field-exact matches and/or dhash similarity.
    Returns list of tuples: (ref_file_obj, work_file_obj, [matched_reasons])
    """
    matches = []
    if not ref_files or not work_files:
        return matches

    fields = criteria.get("fields") or []
    found_pairs = set()

    # 1) Field-based exact matches (if fields are selected)
    if fields:
        index = {}
        for w in work_files:
            key = _build_key(w, fields)
            index.setdefault(key, []).append(w)
        for r in ref_files:
            key = _build_key(r, fields)
            if key and key in index:
                for w in index[key]:
                    pair_key = (r.path, w.path)
                    if pair_key in found_pairs:
                        continue
                    matched = []
                    for fld in fields:
                        va = _get_field_value(r, fld)
                        vb = _get_field_value(w, fld)
                        if va is not None and vb is not None and va == vb:
                            matched.append(fld)
                    if matched:
                        matches.append((r, w, matched))
                        found_pairs.add(pair_key)

    # 2) Legacy fallback only if NOT hashing and no explicit fields selected
    if not fields and not criteria.get("hash"):
        logger.debug("Running legacy fallback matching (metadata/name/size)")
        for r in ref_files:
            for w in work_files:
                pair_key = (r.path, w.path)
                if pair_key in found_pairs:
                    continue
                reasons = []
                if criteria.get("size") and getattr(r, "size", None) is not None and getattr(w, "size", None) is not None and r.size == w.size:
                    reasons.append("size")
                if criteria.get("name") and getattr(r, "name", None) and getattr(w, "name", None) and r.name == w.name:
                    reasons.append("name")
                if criteria.get("metadata"):
                    reasons += _match_metadata(r, w)
                if reasons:
                    matches.append((r, w, list(dict.fromkeys(reasons))))
                    found_pairs.add(pair_key)
    else:
        if not fields and criteria.get("hash"):
            logger.debug("Skipping legacy fallback because hash-based matching requested")

    # 3) Hash-based matching (dhash only)
    if criteria.get("hash"):
        hash_size = int(criteria.get("hash_size") or DEFAULT_HASH_SIZE)
        similarity_threshold = float(criteria.get("similarity") or 90.0)

        ref_paths = [f.path for f in ref_files if getattr(f, "path", None)]
        work_paths = [f.path for f in work_files if getattr(f, "path", None)]

        logger.debug("Starting dhash matching: ref=%d work=%d hash_size=%d similarity=%s%%",
                     len(ref_paths), len(work_paths), hash_size, similarity_threshold)

        # Use HashStore for caching reference hashes
        hash_store = HashStore()
        try:
            # Fetch cached ref hashes
            ref_hashes = hash_store.bulk_get(ref_paths, hash_size)
            cached_count = len(ref_hashes)

            # Compute missing ref hashes
            missing_ref_paths = [p for p in ref_paths if p not in ref_hashes]
            if missing_ref_paths:
                logger.debug("Computing %d missing reference hashes (cached=%d)", len(missing_ref_paths), cached_count)
                computed_ref = _compute_hashes_parallel(missing_ref_paths, hash_size, max_workers=min(8, (os.cpu_count() or 4)), per_file_timeout=8.0)
                # Store newly computed hashes
                for p, h in computed_ref.items():
                    hash_store.set(p, h, hash_size)
                ref_hashes.update(computed_ref)
            else:
                logger.debug("All %d reference hashes retrieved from cache", cached_count)

            # Compute work hashes on the fly (not cached)
            work_hashes = _compute_hashes_parallel(work_paths, hash_size, max_workers=min(8, (os.cpu_count() or 4)), per_file_timeout=8.0)
        finally:
            hash_store.close()

        if not ref_hashes:
            logger.warning("No reference hashes computed (0). Hash-based matching will yield no matches.")
        if not work_hashes:
            logger.warning("No work hashes computed (0). Hash-based matching will yield no matches.")

        try:
            unique_ref_hashes = len(set(str(h) for h in ref_hashes.values()))
            unique_work_hashes = len(set(str(h) for h in work_hashes.values()))
            logger.debug("DHashing: %d ref hashes (%d unique); %d work hashes (%d unique)",
                         len(ref_hashes), unique_ref_hashes, len(work_hashes), unique_work_hashes)
        except Exception:
            pass

        # convert similarity% -> max Hamming distance allowed (integer)
        num_bits = (hash_size * hash_size) if hash_size and isinstance(hash_size, int) else 64
        max_dist = int((1.0 - (similarity_threshold / 100.0)) * num_bits)
        logger.debug("dhash bits=%d similarity=%s%% -> max_hamming=%d", num_bits, similarity_threshold, max_dist)

        # prepare integer representations for bucketing
        work_items = []
        for p, h in work_hashes.items():
            work_items.append((p, h, _imagehash_to_int(h)))
        ref_items = []
        for p, h in ref_hashes.items():
            ref_items.append((p, h, _imagehash_to_int(h)))

        # bucket if many items
        prefix_bits = 0
        total_work = len(work_items)
        if total_work > 500:
            prefix_bits = min(16, num_bits // 2)
        elif total_work > 200:
            prefix_bits = min(12, num_bits // 2)

        buckets: Dict[int, List[Tuple[str, imagehash.ImageHash, int]]] = {}
        if prefix_bits > 0:
            shift = max(0, num_bits - prefix_bits)
            for item in work_items:
                p, h, intval = item
                prefix = intval >> shift
                buckets.setdefault(prefix, []).append(item)
            logger.debug("Bucketing work hashes with prefix_bits=%d produced %d buckets", prefix_bits, len(buckets))

        # compare
        for rp, rh, rint in ref_items:
            candidates = buckets.get(rint >> max(0, num_bits - prefix_bits), []) if prefix_bits > 0 else work_items
            for wp, wh, wint in candidates:
                pair_key = (rp, wp)
                if pair_key in found_pairs:
                    continue
                dist = _hash_hamming_distance(rh, wh)
                if dist <= max_dist:
                    # find objects by path
                    r_obj = next((f for f in ref_files if getattr(f, "path", None) == rp), None)
                    w_obj = next((f for f in work_files if getattr(f, "path", None) == wp), None)
                    if r_obj is None or w_obj is None:
                        continue
                    sim = _hash_similarity_percent_from_distance(dist, num_bits)
                    matches.append((r_obj, w_obj, [f"dhash({int(sim)}%)"]))
                    found_pairs.add(pair_key)

    return matches


def find_uniques(ref_files: List, work_files: List, criteria: Dict[str, Any]):
    """
    Return unique_in_ref, unique_in_work.

    Behavior:
    - If hash-based matching is requested, compute duplicate pairs using the same dhash logic
      and then return uniques as the images not participating in any duplicate pair.
    - Otherwise, fall back to the field/legacy uniqueness behavior.
    """
    try:
        fields = criteria.get("fields") or []

        # If hashing requested: compute duplicate participants and invert
        if criteria.get("hash"):
            logger.debug("find_uniques: hash-based unique detection requested; computing duplicates to invert")
            # reuse find_duplicates to compute pairs (but avoid recursion by calling the dhash section directly is complex).
            # Simpler: perform the same hash workflow here to gather matched paths, then invert.
            hash_size = int(criteria.get("hash_size") or DEFAULT_HASH_SIZE)
            similarity_threshold = float(criteria.get("similarity") or 90.0)

            ref_paths = [f.path for f in ref_files if getattr(f, "path", None)]
            work_paths = [f.path for f in work_files if getattr(f, "path", None)]

            # Use HashStore for caching reference hashes
            hash_store = HashStore()
            try:
                # Fetch cached ref hashes
                ref_hashes = hash_store.bulk_get(ref_paths, hash_size)
                cached_count = len(ref_hashes)

                # Compute missing ref hashes
                missing_ref_paths = [p for p in ref_paths if p not in ref_hashes]
                if missing_ref_paths:
                    logger.debug("Computing %d missing reference hashes (cached=%d)", len(missing_ref_paths), cached_count)
                    computed_ref = _compute_hashes_parallel(missing_ref_paths, hash_size, max_workers=min(8, (os.cpu_count() or 4)), per_file_timeout=8.0)
                    # Store newly computed hashes
                    for p, h in computed_ref.items():
                        hash_store.set(p, h, hash_size)
                    ref_hashes.update(computed_ref)
                else:
                    logger.debug("All %d reference hashes retrieved from cache", cached_count)

                # Compute work hashes on the fly (not cached)
                work_hashes = _compute_hashes_parallel(work_paths, hash_size, max_workers=min(8, (os.cpu_count() or 4)), per_file_timeout=8.0)
            finally:
                hash_store.close()

            num_bits = (hash_size * hash_size) if hash_size and isinstance(hash_size, int) else 64
            max_dist = int((1.0 - (similarity_threshold / 100.0)) * num_bits)

            matched_ref_paths = set()
            matched_work_paths = set()

            # pairwise compare (or use bucketing like in find_duplicates)
            work_items = [(p, h, _imagehash_to_int(h)) for p, h in work_hashes.items()]
            ref_items = [(p, h, _imagehash_to_int(h)) for p, h in ref_hashes.items()]

            # simple pairwise comparison (prefer correctness over micro-optimizations here)
            for rp, rh, rint in ref_items:
                for wp, wh, wint in work_items:
                    try:
                        dist = _hash_hamming_distance(rh, wh)
                    except Exception:
                        continue
                    if dist <= max_dist:
                        matched_ref_paths.add(rp)
                        matched_work_paths.add(wp)

            unique_in_ref = [f for f in ref_files if getattr(f, "path", None) not in matched_ref_paths]
            unique_in_work = [f for f in work_files if getattr(f, "path", None) not in matched_work_paths]

            logger.debug("find_uniques (hash): matched_ref=%d matched_work=%d unique_ref=%d unique_work=%d",
                         len(matched_ref_paths), len(matched_work_paths), len(unique_in_ref), len(unique_in_work))

            return unique_in_ref, unique_in_work

        # Non-hash path: use fields or legacy behavior
        def key(f):
            if not fields:
                parts = []
                if criteria.get("name"):
                    parts.append(f.name or "")
                if criteria.get("size"):
                    parts.append(str(f.size) if getattr(f, "size", None) is not None else "")
                if criteria.get("metadata"):
                    parts.append(str(f.dimensions) if getattr(f, "dimensions", None) else "")
                    parts.append(f.mode or "")
                if not parts:
                    parts.append(f.name or "")
                return "|".join(parts)
            else:
                return _build_key(f, fields)

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
    except Exception as e:
        logging.exception("find_uniques error: %s", e)
        return [], []
