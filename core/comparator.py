"""
core/comparator.py

Rewritten comparator: constructs comparison keys using selected fields and compares files exactly on those fields.
Also supports perceptual hashing (imagehash) when criteria['hash'] is True.

Behavior:
- If criteria['fields'] is non-empty, pairs that match exactly on ALL selected fields are reported.
- Additionally, if criteria['hash'] is True, image hashes are computed (per criteria['hash_type'] and criteria['hash_size'])
  and any pair with similarity >= criteria['similarity'] is reported (similarity is percentage based on Hamming distance).
- Returns list of tuples: (ref_file, work_file, [matched_reasons])
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
                # imagehash functions accept hash_size kw
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
    """
    if h1 is None or h2 is None:
        return 0.0
    try:
        dist = (h1 - h2)
        num_bits = h1.hash.size
        if num_bits == 0:
            return 0.0
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
        # import optional metadata matcher if present (keeps earlier behavior)
        try:
            from core.comparator import _match_metadata  # type: ignore
        except Exception:
            _match_metadata = lambda a, b: []

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
