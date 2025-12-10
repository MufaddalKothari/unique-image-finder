from pathlib import Path
import os
import logging
from typing import List, Dict, Optional
import concurrent.futures

from PIL import Image, UnidentifiedImageError
import imagehash

logger = logging.getLogger(__name__)


def _normalize_path(p: str) -> str:
    """
    Return a canonical, non-strict resolved path string suitable for use as dict keys.
    - Uses Path.resolve(strict=False) so missing files won't raise.
    - Applies os.path.normcase to make keys case-consistent on case-insensitive OSes.
    """
    try:
        # Use resolve(strict=False) so we don't raise for missing files
        rp = Path(p).resolve(strict=False)
        rp_str = str(rp)
    except Exception:
        # Fallback to abspath if something odd happens
        rp_str = os.path.abspath(p)

    # Normalize case where appropriate (Windows mostly)
    try:
        rp_str = os.path.normcase(rp_str)
    except Exception:
        # Ignore normcase errors and return raw string
        pass

    return rp_str


def _hash_one(path: str, hash_size: int) -> Optional[imagehash.ImageHash]:
    """
    Compute dhash for a single file path. Returns None on failure.
    """
    try:
        with Image.open(path) as im:
            # imagehash will handle mode conversions as necessary
            return imagehash.dhash(im, hash_size=hash_size)
    except (UnidentifiedImageError, OSError, ValueError) as e:
        logger.debug("Cannot open image for hashing %s: %s", path, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error hashing image %s: %s", path, e)
        return None


def _compute_hashes_parallel(paths: List[str], hash_size: int) -> Dict[str, imagehash.ImageHash]:
    """
    Compute image hashes for a list of file paths in parallel.

    IMPORTANT: This function normalizes/ canonicalizes keys before computing and returns a
    mapping keyed by canonical (normalized) paths. Duplicate input paths that resolve to the
    same canonical path are deduplicated so the file is hashed only once.

    Returns:
        Dict[canonical_path -> imagehash.ImageHash]
    """
    if not paths:
        return {}

    # Build mapping from canonical path -> one representative original path (for reading)
    canon_to_original: Dict[str, str] = {}
    for p in paths:
        if not p:
            continue
        try:
            canon = _normalize_path(p)
        except Exception:
            # fall back to os.path.abspath
            canon = os.path.normcase(os.path.abspath(p))
        # Keep first observed original path for this canonical path (saves duplicate hashing)
        if canon not in canon_to_original:
            canon_to_original[canon] = p

    canon_paths = list(canon_to_original.keys())
    to_compute = [canon_to_original[canon] for canon in canon_paths]

    logger.debug("Computing hashes for %d unique canonical paths (from %d inputs)", len(canon_paths), len(paths))

    results: Dict[str, imagehash.ImageHash] = {}

    # ThreadPool is fine because PIL image IO is I/O bound
    max_workers = min(32, (os.cpu_count() or 1) + 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exe:
        future_to_canon = {
            exe.submit(_hash_one, orig_path, hash_size): canon
            for canon, orig_path in canon_to_original.items()
        }

        for fut in concurrent.futures.as_completed(future_to_canon):
            canon = future_to_canon[fut]
            try:
                h = fut.result()
                if h is not None:
                    results[canon] = h
                else:
                    logger.debug("Hash computation returned None for %s", canon)
            except Exception:
                logger.exception("Exception computing hash for %s", canon)

    return results