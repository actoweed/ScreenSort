"""watchdog-based folder watcher that feeds new images into the pipeline."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

_SUPPORTED = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


class _ImageHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[Path], None]) -> None:
        super().__init__()
        self._callback = callback

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() in _SUPPORTED:
            logger.debug("New file detected: %s", path)
            # Brief pause so the file is fully written before we read it.
            time.sleep(0.5)
            self._callback(path)


def watch(folder: Path, callback: Callable[[Path], None]) -> None:
    """Block and watch *folder*, calling *callback* for each new image file."""
    handler = _ImageHandler(callback)
    observer = Observer()
    observer.schedule(handler, str(folder), recursive=False)
    observer.start()
    logger.info("Watching %s for new images — press Ctrl+C to stop.", folder)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping watcher…")
    finally:
        observer.stop()
        observer.join()
