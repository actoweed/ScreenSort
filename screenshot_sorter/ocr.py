"""EasyOCR text extraction and SQLite search index."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT UNIQUE NOT NULL,
    category    TEXT,
    ocr_text    TEXT,
    phash       TEXT,
    indexed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
    path,
    ocr_text,
    content='images',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS images_ai AFTER INSERT ON images BEGIN
    INSERT INTO images_fts(rowid, path, ocr_text) VALUES (new.id, new.path, new.ocr_text);
END;
CREATE TRIGGER IF NOT EXISTS images_ad AFTER DELETE ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, path, ocr_text) VALUES ('delete', old.id, old.path, old.ocr_text);
END;
CREATE TRIGGER IF NOT EXISTS images_au AFTER UPDATE ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, path, ocr_text) VALUES ('delete', old.id, old.path, old.ocr_text);
    INSERT INTO images_fts(rowid, path, ocr_text) VALUES (new.id, new.path, new.ocr_text);
END;
"""


class OCRIndex:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._reader = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def _get_reader(self):
        if self._reader is None:
            try:
                import easyocr
                logger.info("Loading EasyOCR model (first run downloads ~200 MB)…")
                self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            except ImportError:
                logger.warning("easyocr not installed; OCR indexing disabled")
                self._reader = False
        return self._reader if self._reader is not False else None

    def extract_text(self, image_path: Path) -> str:
        reader = self._get_reader()
        if reader is None:
            return ""
        try:
            import numpy as np
            from PIL import Image

            # Pass numpy array instead of path — OpenCV can't handle non-ASCII
            # paths on Windows (encodes them as CP1252, corrupting Cyrillic).
            img_array = np.array(Image.open(image_path).convert("RGB"))
            results = reader.readtext(img_array, detail=0)
            return " ".join(results).strip()
        except Exception as exc:
            logger.warning("OCR failed for %s: %s", image_path, exc)
            return ""

    def upsert(self, path: Path, category: str, ocr_text: str, phash: str) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO images (path, category, ocr_text, phash)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                category   = excluded.category,
                ocr_text   = excluded.ocr_text,
                phash      = excluded.phash,
                indexed_at = CURRENT_TIMESTAMP
            """,
            (str(path), category, ocr_text, phash),
        )
        conn.commit()

    def search(self, query: str) -> list[dict]:
        conn = self._get_conn()
        # Wrap in double quotes for phrase search; fall back to prefix if that fails
        safe_query = f'"{query}"'
        try:
            rows = conn.execute(
                """
                SELECT i.path, i.category, i.ocr_text, i.indexed_at
                FROM images_fts f
                JOIN images i ON i.id = f.rowid
                WHERE images_fts MATCH ?
                ORDER BY rank
                """,
                (safe_query,),
            ).fetchall()
        except Exception:
            # Fall back to simple LIKE search if FTS fails
            like = f"%{query}%"
            rows = conn.execute(
                """
                SELECT path, category, ocr_text, indexed_at
                FROM images
                WHERE ocr_text LIKE ? OR path LIKE ?
                ORDER BY indexed_at DESC
                """,
                (like, like),
            ).fetchall()
        return [
            {"path": r[0], "category": r[1], "ocr_text": r[2], "indexed_at": r[3]}
            for r in rows
        ]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
