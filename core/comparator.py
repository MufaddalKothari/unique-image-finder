# core/comparator.py
# Complete comparator implementation providing:
# - find_duplicates(ref_files, work_files, criteria)
# - find_uniques(ref_files, work_files, criteria)
#
# This implementation:

# - Computes missing hashes in a ThreadPoolExecutor (safe on macOS)
# - Uses integer popcount((a ^ b)) for Hamming distance checks with a compatibility fallback

from core.hash_utils import _compute_hashes_parallel, _normalize_path
from typing import List, Tuple, Dict, Any, Optional
import logging
import os
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from collections import defaultdict
from PIL import Image, ImageOps, UnidentifiedImageError
import imagehash

logger = logging.getLogger(__name__)

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

def find_matches(
    ref_files: List[Any],
    work_files: List[Any],
    criteria: Dict[str, Any],
) -> Tuple[List[Tuple[Any, Any, List[str]]], List[Any], List[Any]]:
    """
    Unified function that computes duplicate matches and uniques in one pass.

    Returns a tuple: (matches, uniques_ref, uniques_work)
      - matches: List of (ref_obj, work_obj, [reasons])
      - uniques_ref: list of ref objects that had NO match in work_files
      - uniques_work: list of work objects that had NO match in ref_files

    Behavior:
    - If criteria['hash'] is truthy, uses hash-based comparison (fast).
      * Hashing is done once for both sets using _compute_hashes_parallel which returns
        canonical_path -> ImageHash. Canonicalization is performed by that helper.
      * Hamming threshold is derived from criteria['similarity'] and criteria['hash_size'].
      * Matching: compares everything with everything and records all matches (no early break).
      * uniques are determined by canonical-path membership in matched sets.
    - If criteria['hash'] is falsy, falls back to metadata (name/size) logic:
      * matches: basename equality (same as previous non-hash behavior).
      * uniques: determined by (basename, size) absence (same as previous non-hash).
    """
    matches: List[Tuple[Any, Any, List[str]]] = []
    uniques_ref: List[Any] = []
    uniques_work: List[Any] = []

    if not ref_files and not work_files:
        return matches, uniques_ref, uniques_work
    if not ref_files:
        return matches, [], list(work_files or [])
    if not work_files:
        return matches, list(ref_files or []), []

    use_hash = bool(criteria.get("hash"))
    hash_size = int(criteria.get("hash_size") or DEFAULT_HASH_SIZE)
    similarity = float(criteria.get("similarity") or 90.0)
    hash_bits = hash_size * hash_size
    max_hamming = _max_hamming_from_similarity(hash_bits, similarity)

    logger.debug(
        "find_matches: use_hash=%s hash_size=%d similarity=%s%% -> max_hamming=%d",
        use_hash,
        hash_size,
        similarity,
        max_hamming,
    )

    if not use_hash:
        # Non-hash: matches by basename (old behavior), uniques by basename+size (old behavior)
        ref_map_by_basename = {os.path.basename(f.path): f for f in ref_files if getattr(f, "path", None)}
        for w in work_files:
            name = os.path.basename(getattr(w, "path", ""))
            ref = ref_map_by_basename.get(name)
            if ref:
                matches.append((ref, w, ["name"]))

        # Uniques using (basename, size)
        work_map = {}
        for w in work_files:
            key = (os.path.basename(getattr(w, "path", "")), getattr(w, "size", None))
            work_map.setdefault(key, []).append(w)
        for r in ref_files:
            key = (os.path.basename(getattr(r, "path", "")), getattr(r, "size", None))
            if key not in work_map:
                uniques_ref.append(r)

        ref_map = {}
        for r in ref_files:
            key = (os.path.basename(getattr(r, "path", "")), getattr(r, "size", None))
            ref_map.setdefault(key, []).append(r)
        for w in work_files:
            key = (os.path.basename(getattr(w, "path", "")), getattr(w, "size", None))
            if key not in ref_map:
                uniques_work.append(w)

        return matches, uniques_ref, uniques_work

    # HASH-BASED PATH
    # Build canonical-path -> [objects] maps and collect original input paths for hashing
    ref_canon_to_objs: Dict[str, List[Any]] = defaultdict(list)
    ref_input_paths: List[str] = []
    for f in ref_files:
        p = getattr(f, "path", None)
        if not p:
            continue
        canon = _normalize_path(p)
        ref_canon_to_objs[canon].append(f)
        ref_input_paths.append(p)

    work_canon_to_objs: Dict[str, List[Any]] = defaultdict(list)
    work_input_paths: List[str] = []
    for w in work_files:
        p = getattr(w, "path", None)
        if not p:
            continue
        canon = _normalize_path(p)
        work_canon_to_objs[canon].append(w)
        work_input_paths.append(p)

    # Compute hashes (these return canonical_path -> ImageHash)
    ref_hash_map = _compute_hashes_parallel(ref_input_paths, hash_size)
    work_hash_map = _compute_hashes_parallel(work_input_paths, hash_size)

    # Convert to integer bitmasks for fast hamming
    ref_int_map: Dict[str, int] = {}
    for canon_path, h in ref_hash_map.items():
        try:
            if h is not None:
                ref_int_map[canon_path] = _imagehash_to_int(h)
        except Exception:
            logger.debug("Failed to convert ref hash to int for %s", canon_path)

    work_int_map: Dict[str, int] = {}
    for canon_path, h in work_hash_map.items():
        try:
            if h is not None:
                work_int_map[canon_path] = _imagehash_to_int(h)
        except Exception:
            logger.debug("Failed to convert work hash to int for %s", canon_path)

    # For duplicate matching:
    matched_ref_canons = set()
    matched_work_canons = set()

    # Compare everything-with-everything and record all matches (no early break)
    # Iterate over each work object and compare it against all ref canonical hashes.
    for w_obj in work_files:
        wp = getattr(w_obj, "path", None)
        if not wp:
            continue
        wp_canon = _normalize_path(wp)
        if wp_canon not in work_int_map:
            continue
        wint = work_int_map[wp_canon]

        # Compare with every ref canonical hash and record matches
        for rp_canon, rint in ref_int_map.items():
            try:
                dist = _hamming_distance_int(rint, wint)
            except Exception:
                continue
            if dist <= max_hamming:
                # Record match(s) between all ref objects under rp_canon and this single work object
                refs = ref_canon_to_objs.get(rp_canon, [])
                for ref_obj in refs:
                    matches.append((ref_obj, w_obj, [f"dhash:{dist}"]))
                matched_ref_canons.add(rp_canon)
                matched_work_canons.add(wp_canon)

    # Compute uniques: objects whose canonical paths were not matched
    for canon, ref_objs in ref_canon_to_objs.items():
        if canon not in matched_ref_canons:
            uniques_ref.extend(ref_objs)

    for canon, work_objs in work_canon_to_objs.items():
        if canon not in matched_work_canons:
            uniques_work.extend(work_objs)

    return matches, uniques_ref, uniques_work


# Backwards-compatible thin wrappers
def find_duplicates(ref_files: List[Any], work_files: List[Any], criteria: Dict[str, Any]) -> List[Tuple[Any, Any, List[str]]]:
    """Return only matches (keeps old API)."""
    matches, _, _ = find_matches(ref_files, work_files, criteria)
    return matches


def find_uniques(ref_files: List[Any], work_files: List[Any], criteria: Dict[str, Any]) -> Tuple[List[Any], List[Any]]:
    """Return only uniques (keeps old API)."""
    _, uniques_ref, uniques_work = find_matches(ref_files, work_files, criteria)
    return uniques_ref, uniques_work