"""
core/comparator.py

Rewritten comparator: constructs comparison keys using selected fields and compares files exactly on those fields.
"""
from typing import List, Tuple, Dict, Any
from datetime import datetime


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


def find_duplicates(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> List[Tuple]:
    """
    Find duplicate pairs using exact equality of the selected fields. If no fields selected, fall back to size/name as prior behavior.
    Returns list of tuples: (ref_file, work_file, [matched_fields])
    """
    matches = []
    if not ref_files or not work_files:
        return matches

    fields = criteria.get("fields") or []

    # If no explicit fields selected, use legacy options
    if not fields:
        # fallback to previous behavior using size/name/metadata flags
        # import the metadata matcher from this module if present (keeps older behavior)
        try:
            from core.comparator import _match_metadata  # pragma: no cover
        except Exception:
            _match_metadata = lambda a, b: []

        # simple O(n*m) fallback
        for r in ref_files:
            for w in work_files:
                reasons = []
                if criteria.get("size") and getattr(r, "size", None) is not None and getattr(w, "size", None) is not None and r.size == w.size:
                    reasons.append("size")
                if criteria.get("name") and getattr(r, "name", None) and getattr(w, "name", None) and r.name == w.name:
                    reasons.append("name")
                if criteria.get("metadata"):
                    reasons += _match_metadata(r, w)
                if reasons:
                    matches.append((r, w, list(dict.fromkeys(reasons))))
        return matches

    # Build index of work files by key
    index = {}
    for w in work_files:
        key = _build_key(w, fields)
        index.setdefault(key, []).append(w)

    for r in ref_files:
        key = _build_key(r, fields)
        if key in index and key != "None|None|None":
            # all fields matched exactly
            for w in index[key]:
                # compute which specific fields matched (non-empty and equal)
                matched = []
                for fld in fields:
                    va = _get_field_value(r, fld)
                    vb = _get_field_value(w, fld)
                    if va is not None and vb is not None and va == vb:
                        matched.append(fld)
                if matched:
                    matches.append((r, w, matched))
    return matches


def find_uniques(ref_files: List, work_files: List, criteria: Dict[str, Any]) -> Tuple[List, List]:
    """
    Return unique_in_ref, unique_in_work using keys based on selected fields (or legacy behavior).
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
        import logging
        logging.exception("find_uniques error: %s", e)
        return [], []
