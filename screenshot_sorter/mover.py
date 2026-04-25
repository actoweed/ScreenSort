"""File move operations with logging and dry-run support."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def move_image(
    src: Path,
    dest_dir: Path,
    category: str,
    confidence: float,
    dry_run: bool = False,
) -> Path:
    """Move *src* into *dest_dir/category/* and return the destination path."""
    target_dir = dest_dir / category
    dest = target_dir / src.name

    # Avoid collisions: append a counter if the filename already exists.
    if not dry_run and dest.exists() and dest != src:
        stem, suffix = src.stem, src.suffix
        counter = 1
        while dest.exists():
            dest = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    confidence_pct = f"{confidence * 100:.1f}%"
    arrow = "-->" if not dry_run else "~~>"

    if dry_run:
        logger.info(
            "[dry-run] %s %s %s  (confidence: %s)",
            src.name,
            arrow,
            dest.relative_to(dest_dir.parent) if dest_dir.parent in dest.parents else dest,
            confidence_pct,
        )
        return dest

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    logger.info(
        "%s %s %s  (confidence: %s)",
        src.name,
        arrow,
        dest.relative_to(dest_dir.parent) if dest_dir.parent in dest.parents else dest,
        confidence_pct,
    )
    return dest
