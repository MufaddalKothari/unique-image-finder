"""
core/comparator.py

Rewritten comparator: constructs comparison keys using selected fields and compares files exactly on those fields.
Also supports perceptual hashing (imagehash) when criteria['hash'] is True.

Improvements:
- Robust Hamming distance computation using numpy when available.
- Defensive logging showing unique hash counts for ref/work sets to help debug overmatching.
- No circular imports; includes local _match_metadata fallback.
"""
from typing import List, Tuple, Dict, Any
from datetime import datetime
from PIL import Image, ImageOps
import imagehash
import logging
import os

logger = logging.getLogger(__name__)


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
        # Fallback to getattr
        val = getattr(f, field_name, None)

    # Normalize
    if val is None:
        return None
    # For tuples (dimensions) keep as-is but convert to tuple for stable key
    if isinstance(val, (tuple, list)):
        return tuple(val)
    if isinstance(val, int):
        return int(val)
    s = str(val).strip()
    # Lowercase where appropriate (strings like artist/copyright/camera make/model)
    if field_name in ("name", "artist", "copyright", "make", "model", "origin"):
        s = s.lower()
    return s


def _build_key(f, fields: List[str]):
    parts = []
    for fld in fields:
        parts.append(str(_get_field_value(f, fld)))
    return "|".join(parts)


def _match_metadata(a, b):
    """
    Local metadata matching fallback function.
    Returns list of matching reason strings.
    """
    reasons = []

    # dimensions and mode
    if getattr(a, "dimensions", None) and getattr(b, "dimensions", None) and a.dimensions == b.dimensions:
        reasons.append("dimensions")
    if getattr(a, "mode", None) and getattr(b, "mode", None) and a.mode == b.mode:
        reasons.append("mode")

    # Filesystem creation time (exact match)
    if getattr(a, "created", None) is not None and getattr(b, "created", None) is not None:
        try:
            if int(a.created) == int(b.created):
                reasons.append("created")
        except Exception:
            pass

    # Copyright
    ca = getattr(a, "copyright", None)
    cb = getattr(b, "copyright", None)
    if ca and cb and str(ca).strip() == str(cb).strip():
        reasons.append("copyright")

    # Artist / Author
    aa = getattr(a, "artist", None)
    ab = getattr(b, "artist", None)
    if aa and ab and str(aa).strip() == str(ab).strip():
        reasons.append("artist")

    # EXIF original datetime
    da = getattr(a, "datetime_original", None)
    db = getattr(b, "datetime_original", None)
    if da and db and str(da).strip() == str(db).strip():
        reasons.append("datetime_original")

    # Camera make/model
    ma = getattr(a, "make", None)
    mb = getattr(b, "make", None)
    if ma and mb and str(ma).strip() == str(mb).strip():
        reasons.append("make")
    moa = getattr(a, "model", None)
    mob = getattr(b, "model", None)
    if moa and mob and str(moa).strip() == str(mob).strip():
        reasons.append("model")

    # Image description / caption
    ia = getattr(a, "image_description", None)
    ib = getattr(b, "image_description", None)
    if ia and ib and str(ia).strip() == str(ib).strip():
        reasons.append("image_description")

    # Origin (XMP/IPTC)
    oa = getattr(a, "origin", None)
    ob = getattr(b, "origin", None)
    if oa and ob and str(oa).strip() == str(ob).strip():
        reasons.append("origin")

    return reasons


# helper to compute imagehash for a path with caching
def _compute_hashes_for_paths(paths: List[str], hash_type: str, hash_size: int) -> Dict[str, imagehash.ImageHash]:
    """
    Compute imagehash.ImageHash for each path. Returns dict path->ImageHash.
    Errors are logged and that path is omitted from the returned dict.
    """
    mapper = {
        "Average Hash": imagehash.average_hash,
        "Perceptual Hash": imagehash.phash,
        "Difference Hash": imagehash.dhash,
        "Wavelet Hash": imagehash.whash,
    }
    func = mapper.get(hash_type, imagehash.phash)
    hashes = {}
    for p in paths:
        try:
            if not p or not os.path.exists(p):
                continue
            with Image.open(p) as im:
                # respect orientation tags
                try:
                    im = ImageOps.exif_transpose(im)
                except Exception:
                    pass
                # ensure RGB for consistent hashing
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGB")
                # imagehash functions accept hash_size kw for most functions
                try:
                    h = func(im, hash_size=hash_size)
                except TypeError:
                    # fallback if function doesn't accept hash_size kw
                    h = func(im)
                hashes[p] = h
        except Exception as e:
            logger.debug("Failed to compute hash for %s: %s", p, e)
    return hashes


def _hash_similarity_percent(h1: imagehash.ImageHash, h2: imagehash.ImageHash) -> float:
    """
    Compute similarity in percent between two ImageHash instances:
      similarity = 100 * (1 - (hamming_distance / num_bits))

    This implementation first attempts a numpy-based difference on the underlying arrays,
    which is robust. If numpy is not available or an unexpected error occurs, it falls
    back to imagehash's subtraction operator.
    """
    if h1 is None or h2 is None:
        return 0.0
    try:
        # Try numpy-based distance for reliability
        arr1 = getattr(h1, "hash", None)
        arr2 = getattr(h2, "hash", None)
        if arr1 is not None and arr2 is not None:
            # arr1, arr2 are numpy arrays; compute differing bits
            try:
                import numpy as _np  # local import
                dist = int(_np.count_nonzero(arr1 != arr2))
                num_bits = int(arr1.size)
            except Exception:
                # fallback to element-wise Python loop
                flat1 = arr1.flatten().tolist() if hasattr(arr1, "flatten") else list(arr1)
                flat2 = arr2.flatten().tolist() if hasattr(arr2, "flatten") else list(arr2)
                dist = sum(1 for a, b in zip(flat1, flat2) if a != b)
                num_bits = len(flat1)
        else:
            # Fallback: use imagehash subtraction which returns Hamming distance
            dist = int(h1 - h2)
            # try to infer number of bits from bit-length heuristics
            try:
                num_bits = int(h1.hash.size)
            except Exception:
                num_bits = max(1, dist)
        if num_bits == 0:
            return 0.0
        sim = 100.0 * (1.0 - (dist / float(num_bits)))
        return max(0.0, min(100.0, sim))
    except Exception as e:
        logger.debug("Hash similarity compute failed: %s", e)
        try:
            dist = int(h1 - h2)
            num_bits = getattr(h1, "hash", None).size if getattr(h1, "hash", None) is not None else 64
            sim = 100.0 * (1.0 - (dist / float(num_bits)))
            return max(0.0, min(100.0, sim))
        except Exception:
            return 0.0


def find_duplicates(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> List[Tuple]:
    """
    Find duplicate pairs using exact equality of the selected fields and/or image hash similarity.
    Returns list of tuples: (ref_file, work_file, [matched_reasons])
    """
    matches = []
    if not ref_files or not work_files:
        return matches

    fields = criteria.get("fields") or []
    found_pairs = set()  # track (ref_path, work_path) to avoid duplicates

    # 1) Field-based exact matches (if fields selected)
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

    # 2) Legacy fallback when no fields selected (size/name/metadata)
    if not fields:
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

    # 3) Hash-based matching (if requested) — compute hashes and add matches by similarity threshold
    if criteria.get("hash"):
        hash_type = criteria.get("hash_type") or "Perceptual Hash"
        hash_size = int(criteria.get("hash_size") or 8)
        similarity_threshold = float(criteria.get("similarity") or 90.0)

        # Prepare path lists and compute hashes with caching
        ref_paths = [f.path for f in ref_files if getattr(f, "path", None)]
        work_paths = [f.path for f in work_files if getattr(f, "path", None)]
        # compute hashes (only once per search)
        ref_hashes = _compute_hashes_for_paths(ref_paths, hash_type, hash_size)
        work_hashes = _compute_hashes_for_paths(work_paths, hash_type, hash_size)

        # Debugging: log unique hash counts so we can spot problems
        try:
            unique_ref_hashes = len(set(str(h) for h in ref_hashes.values()))
            unique_work_hashes = len(set(str(h) for h in work_hashes.values()))
            logger.debug("Hashing: computed %d ref hashes (%d unique); %d work hashes (%d unique)",
                         len(ref_hashes), unique_ref_hashes, len(work_hashes), unique_work_hashes)
        except Exception:
            pass

        # compare every pair (could be optimized with buckets; for now do O(n*m))
        for r in ref_files:
            rh = ref_hashes.get(r.path)
            if rh is None:
                continue
            for w in work_files:
                pair_key = (r.path, w.path)
                if pair_key in found_pairs:
                    continue
                wh = work_hashes.get(w.path)
                if wh is None:
                    continue
                sim = _hash_similarity_percent(rh, wh)
                if sim >= similarity_threshold:
                    matches.append((r, w, [f"hash({int(sim)}%)"]))
                    found_pairs.add(pair_key)

    return matches


def find_uniques(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> Tuple[List, List]:
    """
    Return unique_in_ref, unique_in_work using keys based on selected fields (or legacy behavior).
    This is defensive and always returns tuple of lists.
    """
    try:
        fields = criteria.get("fields") or []

        def key(f):
            if not fields:
                # legacy key
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
