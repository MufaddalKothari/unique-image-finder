"""
core/image_scanner.py

Lightweight image scanner used by the UI/comparator.

Changes in this patch:
- Filters out obvious junk files early:
  - skip filenames starting with "._" (macOS resource forks),
  - skip zero-byte files,
  - quick extension whitelist to avoid trying to open non-images.
- Attempts to read basic metadata (size, mtime, dimensions, mode) with PIL where possible,
  but failures to decode are handled gracefully and logged.
- Exposes scan_images_in_directory(path) and an ImageFileObj dataclass used by the rest of the app.
"""
import os
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Quick extension whitelist (lowercase)
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp", ".heic", ".heif"
}


@dataclass
class ImageFileObj:
    path: str
    name: str
    size: Optional[int] = None
    dimensions: Optional[tuple] = None
    mode: Optional[str] = None
    mtime: Optional[float] = None
    created: Optional[float] = None
    # place-holders for other metadata fields used elsewhere
    datetime_original: Optional[str] = None
    artist: Optional[str] = None
    copyright: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    image_description: Optional[str] = None
    origin: Optional[str] = None


def _is_probable_image(path: Path) -> bool:
    name = path.name
    # Skip macOS resource fork files and dot-underscore files
    if name.startswith("._"):
        return False
    # Skip hidden system files like Thumbs.db
    if name.lower() in {"thumbs.db", ".ds_store"}:
        return False
    try:
        if path.stat().st_size == 0:
            return False
    except Exception:
        # If we can't stat, let later PIL decide
        pass
    # Quick extension check
    if path.suffix:
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            return False
    else:
        # no extension; let PIL decide but that is rare
        return True
    return True


def _try_read_image_info(path: str) -> Optional[ImageFileObj]:
    p = Path(path)
    try:
        st = p.stat()
        size = st.st_size
        mtime = st.st_mtime
        created = getattr(st, "st_ctime", None)
    except Exception:
        size = None
        mtime = None
        created = None

    # Quick reject
    if size == 0:
        logger.debug("Skipping zero-size file %s", path)
        return None

    # Try to open with PIL to get dimensions/mode
    try:
        with Image.open(path) as im:
            try:
                im = ImageOps.exif_transpose(im)
            except Exception:
                pass
            width, height = im.size
            mode = im.mode
    except (UnidentifiedImageError, OSError, ValueError) as e:
        # Not a decodable image
        logger.debug("Cannot open image %s: %s", path, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error reading image %s: %s", path, e)
        return None

    return ImageFileObj(
        path=str(p),
        name=p.name,
        size=size,
        dimensions=(width, height),
        mode=mode,
        mtime=mtime,
        created=created,
    )


def scan_images_in_directory(root: str) -> List[ImageFileObj]:
    """
    Recursively scan `root` for image files and return a list of ImageFileObj.
    Applies quick extension-based filtering and excludes obvious junk files early.
    """
    out: List[ImageFileObj] = []
    if not root:
        return out
    root_p = Path(root)
    if not root_p.exists():
        return out

    for dirpath, dirnames, filenames in os.walk(root_p):
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                if not _is_probable_image(p):
                    logger.debug("Filtered out non-image or junk file: %s", p)
                    continue
                info = _try_read_image_info(str(p))
                if info:
                    out.append(info)
                else:
                    # _try_read_image_info already logged the reason
                    continue
            except Exception as e:
                logger.debug("Skipping file due to unexpected error %s: %s", p, e)
                continue
    logger.info("Scanned %d image(s) in %s", len(out), root)
    return out
