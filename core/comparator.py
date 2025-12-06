# core/comparator.py
# Updated comparator to use CacheDB prefix lookup for candidate pruning.
# If CacheDB is present and reference files belong to cached directories,
# comparator queries the DB for candidate ref rows by prefix and only compares those.

from typing import List, Tuple, Dict, Any, Optional
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError
import imagehash

logger = logging.getLogger(__name__)

# Optional components
try:
    from core.hashstore import HashStore
except Exception:
    HashStore = None

try:
    from core.cache_db import CacheDB
except Exception:
    CacheDB = None

# Defaults
DEFAULT_HASH_SIZE = 16
DEFAULT_MAX_WORKERS = max(1, (os.cpu_count() or 2) - 1)


# --- helpers ----------------------------------------------------------------
def _image_dhash(path: str, hash_size: int = DEFAULT_HASH_SIZE) -> Optional[imagehash.ImageHash]:
    try:
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
            return h
    except (UnidentifiedImageError, OSError, ValueError) as e:
        logger.debug("Failed to open image for hashing %s: %s", path, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error hashing %s: %s", path, e)
        return None


def _compute_hashes_parallel(paths: List[str], hash_size: int = DEFAULT_HASH_SIZE, max_workers: int = DEFAULT_MAX_WORKERS) -> Dict[str, imagehash.ImageHash]:
    out: Dict[str, imagehash.ImageHash] = {}
    if not paths:
        return out
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_image_dhash, p, hash_size): p for p in paths}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                h = fut.result()
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
    return int(str(h), 16)


def _popcount(n: int) -> int:
    try:
        return n.bit_count()
    except AttributeError:
        return bin(n).count("1")


def _hamming_distance_int(a: int, b: int) -> int:
    return _popcount(a ^ b)


def _max_hamming_from_similarity(hash_bits: int, similarity_percent: float) -> int:
    if similarity_percent <= 0:
        return hash_bits
    if similarity_percent >= 100:
        return 0
    return int(round((1.0 - (similarity_percent / 100.0)) * hash_bits))


# --- comparator core -------------------------------------------------------
def find_duplicates(ref_files: List[Any], work_files: List[Any], criteria: Dict[str, Any]) -> List[Tuple[Any, Any, List[str]]]:
    matches: List[Tuple[Any, Any, List[str]]] = []
    if not ref_files or not work_files:
        return matches

    use_hash = bool(criteria.get("hash"))
    hash_size = int(criteria.get("hash_size") or DEFAULT_HASH_SIZE)
    similarity = float(criteria.get("similarity") or 90.0)
    hash_bits = hash_size * hash_size
    max_hamming = _max_hamming_from_similarity(hash_bits, similarity)

    logger.debug("find_duplicates: use_hash=%s hash_size=%d similarity=%s%% -> max_hamming=%d", use_hash, hash_size, similarity, max_hamming)

    # Non-hash fallback (simple name match)
    if not use_hash:
        ref_map = {os.path.basename(f.path): f for f in ref_files if getattr(f, "path", None)}
        for w in work_files:
            name = os.path.basename(getattr(w, "path", ""))
            ref = ref_map.get(name)
            if ref:
                matches.append((ref, w, ["name"]))
        return matches

    # Prepare path lists
    ref_paths = [f.path for f in ref_files if getattr(f, "path", None)]
    work_paths = [f.path for f in work_files if getattr(f, "path", None)]

    logger.debug("Starting dhash matching: ref=%d work=%d hash_size=%d similarity=%s%%", len(ref_paths), len(work_paths), hash_size, similarity)

    # Try to use HashStore + CacheDB where possible
    ref_hash_map: Dict[str, imagehash.ImageHash] = {}
    # 1) Transient HashStore
    if HashStore is not None:
        try:
            hs = HashStore()
            try:
                store_hits = hs.bulk_get(ref_paths, hash_size)
                logger.debug("HashStore: cache hits=%d for reference files", len(store_hits))
                for p, hv in store_hits.items():
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

    # 2) Use CacheDB candidate lookup when ref files are part of cached dirs
    cache_db = None
    if CacheDB is not None:
        try:
            cache_db = CacheDB()
        except Exception:
            cache_db = None

    # Build mapping: dir_id -> list of ref paths that belong to that cached dir
    dir_ref_map: Dict[int, List[str]] = {}
    dir_prefix_bits: Dict[int, int] = {}
    uncached_ref_paths: List[str] = []

    if cache_db is not None:
        # fetch cached dirs once
        cached_dirs = cache_db.list_dirs()
        # prepare for quick checking: map dir_id -> dir_path
        dir_paths = [(d["dir_id"], os.path.normpath(d["path"]), d.get("prefix_bits", 16)) for d in cached_dirs]
        for rp in ref_paths:
            matched = False
            n_rp = os.path.normpath(rp)
            for dir_id, dpath, pbits in dir_paths:
                if n_rp.startswith(dpath):
                    dir_ref_map.setdefault(dir_id, []).append(rp)
                    dir_prefix_bits[dir_id] = int(pbits or 16)
                    matched = True
                    break
            if not matched:
                uncached_ref_paths.append(rp)
    else:
        uncached_ref_paths = ref_paths.copy()

    # For any cached dir, attempt to populate ref_hash_map from DB for those ref paths
    if cache_db is not None and dir_ref_map:
        for dir_id, paths_in_dir in dir_ref_map.items():
            try:
                db_hashes = cache_db.get_hashes_for_paths(paths_in_dir, hash_size)
                logger.debug("CacheDB: found %d stored ref hashes for dir_id=%s", len(db_hashes), dir_id)
                for p, hexv in db_hashes.items():
                    ih = _hex_to_imagehash(hexv)
                    if ih:
                        ref_hash_map[p] = ih
                # any remaining missing in this dir will be added to uncached_ref_paths for compute
                for p in paths_in_dir:
                    if p not in ref_hash_map:
                        uncached_ref_paths.append(p)
            except Exception as e:
                logger.debug("CacheDB lookup failed for dir_id=%s: %s", dir_id, e)
                for p in paths_in_dir:
                    uncached_ref_paths.append(p)

    # For any remaining uncached_ref_paths, try HashStore (again) or compute
    missing_refs = [p for p in uncached_ref_paths if p not in ref_hash_map]
    if missing_refs:
        # first check HashStore again for the missing ones
        if HashStore is not None:
            try:
                hs = HashStore()
                try:
                    hits = hs.bulk_get(missing_refs, hash_size)
                    for p, hv in hits.items():
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

    # Recompute any still-missing ref hashes
    missing_refs = [p for p in missing_refs if p not in ref_hash_map]
    if missing_refs:
        logger.debug("Computing %d missing reference hashes", len(missing_refs))
        computed = _compute_hashes_parallel(missing_refs, hash_size)
        for p, h in computed.items():
            ref_hash_map[p] = h
            # try populate transient HashStore
            if HashStore is not None:
                try:
                    hs = HashStore()
                    try:
                        hs.set(p, h, hash_size)
                    finally:
                        try:
                            hs.close()
                        except Exception:
                            pass
                except Exception:
                    pass

    # Compute work hashes (we may want to cache these too in HashStore if many repeated searches use same work folders)
    logger.debug("Computing %d work hashes", len(work_paths))
    work_hash_map = _compute_hashes_parallel(work_paths, hash_size)

    # If CacheDB present, use prefix-based candidate selection to prune ref candidates per work file
    if cache_db is not None and dir_ref_map:
        # Convert work hashes to ints
        work_int_map: Dict[str, int] = {}
        for p, h in work_hash_map.items():
            try:
                work_int_map[p] = _imagehash_to_int(h)
            except Exception:
                pass

        # For each work file, check against cached-dir candidates (by prefix) plus any uncached refs (fallback)
        uncached_ref_set = set([p for p in ref_paths if p not in ref_hash_map])
        # convert fully known ref_hash_map to ints for quick compare
        ref_int_map_cached: Dict[str, int] = {}
        for p, h in ref_hash_map.items():
            try:
                ref_int_map_cached[p] = _imagehash_to_int(h)
            except Exception:
                pass

        for w_obj in work_files:
            wp = getattr(w_obj, "path", None)
            if not wp or wp not in work_int_map:
                continue
            wint = work_int_map[wp]
            matched = False
            # iterate over cached dirs that have reference files
            for dir_id, paths_in_dir in dir_ref_map.items():
                pbits = int(dir_prefix_bits.get(dir_id, 16))
                num_bits = hash_bits
                if pbits < num_bits:
                    wprefix = wint >> (num_bits - pbits)
                else:
                    wprefix = wint
                # query DB for candidates with same prefix
                try:
                    candidates = cache_db.get_candidates_by_prefix(dir_id, int(wprefix), limit=1000)
                except Exception:
                    candidates = []
                # candidates is list of (path, hash_hex)
                for rp, hexv in candidates:
                    try:
                        # convert hex to int
                        rint = int(hexv, 16)
                    except Exception:
                        continue
                    dist = _hamming_distance_int(rint, wint)
                    if dist <= max_hamming:
                        # find r_obj from ref_files list
                        r_obj = next((r for r in ref_files if getattr(r, "path", None) == rp), None)
                        matches.append((r_obj, w_obj, [f"dhash:{dist}"]))
                        matched = True
                        break
                if matched:
                    break
            if matched:
                continue
            # Fallback: check against any cached ref_hash_map that we loaded earlier
            for rp, rint in ref_int_map_cached.items():
                dist = _hamming_distance_int(rint, wint)
                if dist <= max_hamming:
                    r_obj = next((r for r in ref_files if getattr(r, "path", None) == rp), None)
                    matches.append((r_obj, w_obj, [f"dhash:{dist}"]))
                    matched = True
                    break
            if matched:
                continue
            # Final fallback: brute-force compare against any uncached refs by computing their hashes on-the-fly (already done earlier)
            for r in ref_files:
                rp = getattr(r, "path", None)
                if rp in ref_int_map_cached:
                    continue
                # try to get its hash from work we computed earlier (unlikely) or compute now (skip here for brevity)
                # We assume missing refs were handled earlier during ref hash computation phase.
                pass

        return matches

    # If no CacheDB or no cached dirs, fallback to original full-compare approach (load ref ints and compare)
    ref_int_map: Dict[str, int] = {}
    for p, h in ref_hash_map.items():
        try:
            ref_int_map[p] = _imagehash_to_int(h)
        except Exception:
            pass

    work_int_map: Dict[str, int] = {}
    for p, h in work_hash_map.items():
        try:
            work_int_map[p] = _imagehash_to_int(h)
        except Exception:
            pass

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
                matches.append((r_obj, w_obj, [f"dhash:{dist}"]))
                break

    return matches


def find_uniques(ref_files: List[Any], work_files: List[Any], criteria: Dict[str, Any]) -> Tuple[List[Any], List[Any]]:
    # For brevity and safety, reuse earlier implementation which will also benefit from the same prefix-speedups above
    # We'll use find_duplicates under the hood to mark matched sets, then compute uniques.
    duplicates = find_duplicates(ref_files, work_files, criteria)
    matched_ref = set()
    matched_work = set()
    for r, w, _ in duplicates:
        if getattr(r, "path", None):
            matched_ref.add(r.path)
        if getattr(w, "path", None):
            matched_work.add(w.path)
    unique_ref = [r for r in ref_files if getattr(r, "path", None) not in matched_ref]
    unique_work = [w for w in work_files if getattr(w, "path", None) not in matched_work]
    return unique_ref, unique_work