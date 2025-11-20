"""
core/xmp_origin.py

Small helper for extracting XMP/IPTC 'Origin' (or similar source fields) from JPEG files.

Approach:
- Read JPEG bytes and locate the XMP packet (APP1 segment containing <x:xmpmeta> ... </x:xmpmeta>).
- Parse the XMP XML and look for common tags that may contain source/origin information:
  - dc:source
  - photoshop:Source
  - Iptc4xmpCore:Source
  - dc:creator (first entry)
  - xmpMM:DerivedFrom / xmpMM:History (if present)
- Return the first non-empty textual value found, otherwise None.

This helper uses only the Python stdlib + ElementTree and should be safe to include without extra deps.
"""
from typing import Optional
import xml.etree.ElementTree as ET
import re
import logging

logger = logging.getLogger(__name__)

# Common XMP namespaces we may encounter
_XMP_NS = {
    'dc': 'http://purl.org/dc/elements/1.1/',
    'photoshop': 'http://ns.adobe.com/photoshop/1.0/',
    'Iptc4xmpCore': 'http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/',
    'xmpMM': 'http://ns.adobe.com/xap/1.0/mm/',
    'xmp': 'http://ns.adobe.com/xap/1.0/',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
}

# Candidate XMP tags (QName tuples: (prefix, localname))
_CANDIDATE_TAGS = [
    ('dc', 'source'),
    ('photoshop', 'Source'),
    ('Iptc4xmpCore', 'Source'),
    ('dc', 'creator'),
    ('xmpMM', 'DerivedFrom'),
    ('xmpMM', 'History'),
    ('photoshop', 'Author'),        # sometimes used
    ('dc', 'publisher'),
]

# quick regex to find XMP packet in JPEG APP1 blocks
_XMP_START_RE = re.compile(b'<x:?xmpmeta', re.IGNORECASE)
_XMP_END_RE = re.compile(b'</x:?xmpmeta>', re.IGNORECASE)


def _find_xmp_packet(jpeg_bytes: bytes) -> Optional[bytes]:
    """
    Find the XMP XML packet within JPEG bytes and return the XML bytes (including root tags),
    or None if not found.
    """
    start_match = _XMP_START_RE.search(jpeg_bytes)
    if not start_match:
        return None
    start_index = start_match.start()
    end_match = _XMP_END_RE.search(jpeg_bytes, pos=start_index)
    if not end_match:
        return None
    end_index = end_match.end()
    return jpeg_bytes[start_index:end_index]


def _safe_decode(b: bytes) -> str:
    # Try common encodings; XMP is typically UTF-8 or UTF-16
    for enc in ('utf-8', 'utf-16', 'utf-16le', 'utf-16be', 'latin-1'):
        try:
            return b.decode(enc)
        except Exception:
            pass
    # fallback with replacement
    return b.decode('utf-8', errors='replace')


def _first_text_from_element(elem: ET.Element) -> Optional[str]:
    if elem is None:
        return None
    # If element contains rdf:Alt / rdf:li children, prefer first li text
    rdf_ns = _XMP_NS.get('rdf')
    if rdf_ns:
        li = elem.find('.//{'+rdf_ns+'}li')
        if li is not None and li.text:
            return li.text.strip()
    # Direct text
    if elem.text and elem.text.strip():
        return elem.text.strip()
    # Sometimes children contain the useful text
    for child in elem:
        if child.text and child.text.strip():
            return child.text.strip()
    return None


def extract_origin_from_jpeg(path: str) -> Optional[str]:
    """
    Attempt to extract an 'Origin' / 'Source' value from XMP or IPTC-like data embedded in a JPEG.
    Returns the string value if found, otherwise None.
    """
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except Exception as e:
        logger.debug("Could not read file for XMP extraction: %s (%s)", path, e)
        return None

    packet = _find_xmp_packet(data)
    if not packet:
        return None

    xml_text = _safe_decode(packet)
    try:
        for prefix, uri in _XMP_NS.items():
            ET.register_namespace(prefix, uri)
        root = ET.fromstring(xml_text)
    except Exception as e:
        logger.debug("Failed to parse XMP XML for %s: %s", path, e)
        return None

    # Search candidate tags in order
    for prefix, local in _CANDIDATE_TAGS:
        nsuri = _XMP_NS.get(prefix)
        if not nsuri:
            continue
        qname = './/{'+nsuri+'}'+local
        elem = root.find(qname)
        txt = _first_text_from_element(elem) if elem is not None else None
        if txt:
            return txt

    # As a fallback, look for any element whose local-name contains 'origin' or 'source'
    for elem in root.iter():
        tag = elem.tag
        if isinstance(tag, str) and ('origin' in tag.lower() or 'source' in tag.lower()):
            candidate = _first_text_from_element(elem)
            if candidate:
                return candidate

    return None
