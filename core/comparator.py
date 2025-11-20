"""
core/comparator.py

Contains logic for comparing ImageFileObj objects for duplicates and uniques using
size, name, metadata (expanded) and placeholder for hash-based comparisons.
"""
from typing import List, Tuple, Dict, Any
from datetime import datetime

def _format_ts(ts):
    try:
        return datetime.fromtimestamp(int(ts)).isoformat(sep=' ')
    except Exception:
        return str(ts)

def _match_metadata(a, b):
    """
    Compare extended metadata fields between two image objects and return a list
    of reasons (human-friendly keys) that matched.

    Fields compared:
      - dimensions
      - mode
      - created (filesystem creation time)
      - copyright
      - artist
      - datetime_original (EXIF DateTimeOriginal)
      - make (camera make)
      - model (camera model)
      - image_description
      - origin (if available in metadata)
    """
    reasons = []

    # dimensions and mode (existing checks)
    if getattr(a, "dimensions", None) and getattr(b, "dimensions", None) and a.dimensions == b.dimensions:
        reasons.append("dimensions")
    if getattr(a, "mode", None) and getattr(b, "mode", None) and a.mode == b.mode:
        reasons.append("mode")

    # Filesystem creation time (exact match)
    if getattr(a, "created", None) is not None and getattr(b, "created", None) is not None:
        try:
            if int(a.created) == int(b.created):
                reasons.append("created")
            else:
                # optional: consider same-day equivalence (not added to reasons unless equal)
                pass
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

    # Origin (non-standard; some tools/windows show origin in details tab; may come from XMP/IPTC/XP tags).
    oa = getattr(a, "origin", None)
    ob = getattr(b, "origin", None)
    if oa and ob and str(oa).strip() == str(ob).strip():
        reasons.append("origin")

    return reasons

# Existing comparator logic (keeps other functionality)
def _match_metadata_simple(a, b):
    """Backward-compat simple metadata matching (dimensions & mode only)."""
    reasons = []
    if getattr(a, "dimensions", None) and getattr(b, "dimensions", None) and a.dimensions == b.dimensions:
        reasons.append("dimensions")
    if getattr(a, "mode", None) and getattr(b, "mode", None) and a.mode == b.mode:
        reasons.append("mode")
    return reasons

def find_duplicates(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> List[Tuple]:
    """
    Find duplicate pairs between ref_files and work_files according to criteria.

    criteria keys (booleans and optional params):
      - size: match by file size
      - name: match by filename
      - metadata: match by image metadata (dimensions, mode, and expanded fields)
      - hash: match by hash (not implemented here)
      - hash_type, hash_size, similarity: parameters for hashing (unused here)
    Returns list of tuples: (ref_file, work_file, [reasons])
    """
    matches = []
    if not ref_files or not work_files:
        return matches

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
            if criteria.get("name") and r.name and w.name and r.name == w.name:
                reasons.append("name")
            if criteria.get("metadata"):
                reasons += _match_metadata(r, w)
            # hash criteria not implemented here (requires imagehash & cache)
            # Accept pair if any criterion matched
            if reasons:
                matches.append((r, w, list(dict.fromkeys(reasons))))  # unique reasons
    return matches

def find_uniques(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> Tuple[List, List]:
    """
    Return (unique_in_ref, unique_in_work) using composed key from criteria.
    """
    try:
        def key(f):
            parts = []
            if criteria.get("name"):
                parts.append(f.name or "")
            if criteria.get("size"):
                parts.append(str(f.size) if getattr(f, "size", None) is not None else "")
            if criteria.get("metadata"):
                parts.append(str(f.dimensions) if getattr(f, "dimensions", None) else "")
                parts.append(f.mode or "")
                # include some extended metadata in uniqueness key as optional
                parts.append(str(getattr(f, "datetime_original", "") or ""))
                parts.append(str(getattr(f, "artist", "") or ""))
                parts.append(str(getattr(f, "copyright", "") or ""))
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
    except Exception as e:
        import logging
        logging.exception("find_uniques error: %s", e)
        # On error, return empty lists instead of None so callers don't crash.
        return [], []
