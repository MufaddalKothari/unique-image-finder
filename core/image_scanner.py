"""
core/image_scanner.py

Scans directories for images, collects metadata, and generates hashes.

Notes:
- Allows working with very large images by adjusting PIL's MAX_IMAGE_PIXELS.
- Extracts filesystem creation date and common EXIF fields (Copyright, Artist, DateTimeOriginal, Make, Model, ImageDescription, XPAuthor-like tags),
  and attempts to extract XMP/IPTC 'Origin' using core/xmp_origin.extract_origin_from_jpeg.
"""
import os
import logging
import hashlib
from typing import List, Optional
from PIL import Image, UnidentifiedImageError, ImageFile, ExifTags

# Allow PIL to load very large images — you're working with large images regularly.
# Setting to None disables the safety check. If you'd prefer to enforce a high cap,
# set to a large integer.
Image.MAX_IMAGE_PIXELS = None

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Import the XMP origin helper (keep import local-friendly if module missing)
try:
    from .xmp_origin import extract_origin_from_jpeg
except Exception:
    # If helper not present or import fails, define a no-op fallback
    def extract_origin_from_jpeg(path: str) -> Optional[str]:
        return None


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

        # Creation time (filesystem)
        try:
            self.created = int(os.path.getctime(path))
        except OSError as e:
            logger.warning("Could not get creation time for %s: %s", path, e)
            self.created = None

        self.dimensions = None  # (width, height)
        self.mode = None        # e.g., "RGB"

        # Common EXIF fields we will surface
        self.copyright = None
        self.artist = None
        self.datetime_original = None
        self.make = None
        self.model = None
        self.image_description = None
        # Origin from XMP/IPTC (best-effort)
        self.origin = None

        # Try to open the image to read dimensions, mode, and EXIF
        try:
            with Image.open(path) as img:
                img.load()
                self.dimensions = img.size
                self.mode = img.mode

                # Try to get EXIF data if present
                exif_raw = None
                try:
                    exif_raw = img._getexif() or {}
                except Exception:
                    exif_raw = {}

                if exif_raw:
                    # Map numeric tags to names
                    for tag, value in exif_raw.items():
                        name = ExifTags.TAGS.get(tag, tag)
                        if name == 'Copyright' and value:
                            self.copyright = _decode_exif_value(value)
                        elif name in ('Artist',) and value:
                            self.artist = _decode_exif_value(value)
                        elif name in ('DateTimeOriginal', 'DateTime') and value:
                            self.datetime_original = str(value)
                        elif name == 'Make' and value:
                            self.make = str(value)
                        elif name == 'Model' and value:
                            self.model = str(value)
                        elif name in ('ImageDescription',) and value:
                            self.image_description = str(value)
                        else:
                            # also handle XP tags like XPAuthor, XPTitle, XPComment which may appear as byte arrays
                            if isinstance(name, str) and name.startswith('XP') and value:
                                decoded = _decode_exif_value(value)
                                # heuristically assign XPAuthor to artist if artist missing
                                if name in ('XPAuthor', 'XPUserComment') and decoded and not self.artist:
                                    self.artist = decoded
                                elif name == 'XPComment' and decoded and not self.image_description:
                                    self.image_description = decoded

                # Best-effort: try XMP/IPTC origin extraction from JPEG (works for many files)
                try:
                    self.origin = extract_origin_from_jpeg(path)
                except Exception:
                    self.origin = None

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


def _decode_exif_value(value):
    """
    Decode EXIF values which may be bytes, tuples, or other types.
    Handles Windows XP-style UTF-16LE byte-arrays and tuples of ints.
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode('utf-16le').rstrip('\x00')
        except Exception:
            try:
                return value.decode('utf-8', errors='ignore')
            except Exception:
                return value.decode('latin-1', errors='ignore')
    if isinstance(value, tuple):
        try:
            b = bytes(value)
            return b.decode('utf-16le').rstrip('\x00')
        except Exception:
            return str(value)
    return str(value)


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
