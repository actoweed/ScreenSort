"""Perceptual hash-based duplicate detection."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Hamming distance threshold — images within this distance are considered duplicates.
_HASH_THRESHOLD = 8


def compute_phash(image_path: Path) -> str | None:
    try:
        import imagehash
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        return str(imagehash.phash(img))
    except Exception as exc:
        logger.warning("Could not hash %s: %s", image_path, exc)
        return None


def is_duplicate(phash: str, known_hashes: dict[str, Path]) -> Path | None:
    """Return the path of the existing duplicate, or None if unique."""
    try:
        import imagehash

        candidate = imagehash.hex_to_hash(phash)
        for existing_hash_str, existing_path in known_hashes.items():
            existing = imagehash.hex_to_hash(existing_hash_str)
            if abs(candidate - existing) <= _HASH_THRESHOLD:
                return existing_path
    except Exception as exc:
        logger.debug("Hash comparison error: %s", exc)
    return None
