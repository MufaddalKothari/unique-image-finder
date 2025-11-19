"""
core/image_scanner.py

Scans directories for images, collects metadata, and generates hashes.

Notes:
- Allows working with very large images by adjusting PIL's MAX_IMAGE_PIXELS.
- Uses Image.DecompressionBombError (via getattr fallback) to handle older/newer Pillow versions.
- Robust on unreadable files and logs issues.
"""

import os
import logging
import hashlib
from typing import List
from PIL import Image, UnidentifiedImageError, ImageFile

# Allow PIL to load very large images — you're working with large images regularly.
# Setting to None disables the safety check. If you'd prefer to enforce a high cap,
# set to a large integer.
Image.MAX_IMAGE_PIXELS = None

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class ImageFileObj:
    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path)

        # Safely get file size and mtime (may fail on broken symlinks or permission errors)
        try:
            self.size = os.path.getsize(path)
        except OSError as e:
            logger.warning("Could not get size for %s: %s", path, e)
            self.size = None

        try:
            self.mtime = int(os.path.getmtime(path))
        except OSError as e:
            logger.warning("Could not get mtime for %s: %s", path, e)
            self.mtime = None

        self.dimensions = None  # (width, height)
        self.mode = None        # e.g., "RGB"

        # Try to open the image to read dimensions and mode
        try:
            # Use ImageFile.LOAD_TRUNCATED_IMAGES if needed, but prefer explicit handling
            with Image.open(path) as img:
                img.load()
                self.dimensions = img.size
                self.mode = img.mode
        except getattr(Image, "DecompressionBombError", Exception) as e:
            # Handle decompression bomb via Image.DecompressionBombError if available
            logger.warning("DecompressionBombError for %s: %s", path, e)
            try:
                # Try again after ensuring MAX_IMAGE_PIXELS is disabled
                Image.MAX_IMAGE_PIXELS = None
                with Image.open(path) as img:
                    img.load()
                    self.dimensions = img.size
                    self.mode = img.mode
            except Exception as e2:
                logger.warning("Cannot open large image %s even after disabling limit: %s", path, e2)
        except (UnidentifiedImageError, OSError, ValueError) as e:
            # Not a valid/readable image or can't be opened; we keep dimensions/mode as None
            logger.debug("Cannot open image %s: %s", path, e)

    def compute_md5(self) -> str:
        """Compute MD5 of the file contents in a memory-friendly way."""
        h = hashlib.md5()
        try:
            with open(self.path, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except OSError as e:
            logger.error("Failed to compute MD5 for %s: %s", self.path, e)
            return ""


def scan_images_in_directory(directory: str, recursive: bool = True) -> List[ImageFileObj]:
    """Scan a directory for image files and return a list of ImageFileObj objects.

    Non-readable files and failures to read are logged and skipped.
    """
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp"}
    result: List[ImageFileObj] = []

    if not os.path.isdir(directory):
        logger.error("Provided path is not a directory: %s", directory)
        return result

    for root, _, files in os.walk(directory):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in exts:
                full_path = os.path.join(root, file)
                try:
                    img = ImageFileObj(full_path)
                    result.append(img)
                except Exception as e:
                    # Catch-all to prevent a broken file from stopping the whole scan
                    logger.warning("Skipping file %s due to error: %s", full_path, e)
        if not recursive:
            break

    logger.info("Scanned %d image(s) in %s", len(result), directory)
    return result