"""
core/comparator.py

Contains logic for comparing ImageFileObj objects for duplicates and uniques using
size, name, and metadata. Hash-based comparisons are left for future wiring (imagehash + hash_cache).
"""

from typing import List, Tuple, Dict, Any

def _match_metadata(a, b):
    """Return list of reasons for metadata matches (dimensions, mode)."""
    reasons = []
    if getattr(a, "dimensions", None) and getattr(b, "dimensions", None) and a.dimensions == b.dimensions:
        reasons.append("dimensions")
    if getattr(a, "mode", None) and getattr(b, "mode", None) and a.mode == b.mode:
        reasons.append("mode")
    return reasons

def find_duplicates(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> List[Tuple]:
    """
    Find duplicate pairs between ref_files and work_files according to criteria.

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
            if criteria.get("name") and getattr(r, "name", None) and getattr(w, "name", None) and r.name == w.name:
                reasons.append("name")
            if criteria.get("metadata"):
                reasons += _match_metadata(r, w)
            # hash criteria not implemented here (requires imagehash & cache)
            # Accept pair if any criterion matched
            if reasons:
                # dedupe reasons while preserving order
                unique_reasons = list(dict.fromkeys(reasons))
                matches.append((r, w, unique_reasons))
    return matches

def find_uniques(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> Tuple[List, List]:
    """
    Return (unique_in_ref, unique_in_work) based on simple exact filename/size/metadata key
    depending on criteria. Conservative: if a file's composed key exists in other set, it's not unique.
    """
    def key(f):
        parts = []
        if criteria.get("name"):
            parts.append(f.name or "")
        if criteria.get("size"):
            parts.append(str(f.size) if getattr(f, "size", None) is not None else "")
        if criteria.get("metadata"):
            parts.append(str(f.dimensions) if getattr(f, "dimensions", None) else "")
            parts.append(f.mode or "")
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