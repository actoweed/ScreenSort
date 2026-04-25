"""CLI entry point for screenshot-sorter."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
import yaml

from .classifier import Classifier
from .deduplicator import compute_phash, is_duplicate
from .mover import move_image
from .ocr import OCRIndex

_SUPPORTED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"
}

_DEFAULT_CONFIG = Path(__file__).parent.parent / "config.yaml"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stdout,
    )


def _load_config(config_path: Path) -> dict:
    with open(config_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _find_images(folder: Path) -> list[Path]:
    return [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
    ]


@click.group()
def main() -> None:
    """screenshot-sorter — classify and organise screenshots with CLIP."""


@main.command("sort")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--config", "-c",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to config.yaml (default: bundled config).",
)
@click.option(
    "--output", "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Destination root folder (default: same as FOLDER).",
)
@click.option("--dry-run", is_flag=True, help="Show what would happen without moving files.")
@click.option("--no-ocr", is_flag=True, help="Skip OCR indexing (faster).")
@click.option("--watch", is_flag=True, help="Stay running and sort new files as they arrive.")
@click.option("--verbose", "-v", is_flag=True, help="Show debug output.")
def sort_cmd(
    folder: Path,
    config: Path | None,
    output: Path | None,
    dry_run: bool,
    no_ocr: bool,
    watch: bool,
    verbose: bool,
) -> None:
    """Sort images in FOLDER into categorised subfolders."""
    _setup_logging(verbose)
    logger = logging.getLogger(__name__)

    cfg_path = config or _DEFAULT_CONFIG
    if not cfg_path.exists():
        click.echo(f"Config not found: {cfg_path}", err=True)
        raise click.Abort()

    cfg = _load_config(cfg_path)
    categories: dict = cfg.get("categories", {})
    confidence_threshold: float = cfg.get("confidence_threshold", 0.20)
    model_name: str = cfg.get("clip_model", "ViT-B-32")
    pretrained: str = cfg.get("clip_pretrained", "openai")

    dest_root = output or folder
    db_path = dest_root / ".screenshot_sorter.db"

    classifier = Classifier(
        categories=categories,
        model_name=model_name,
        pretrained=pretrained,
        confidence_threshold=confidence_threshold,
    )

    ocr_index: OCRIndex | None = None
    if not no_ocr:
        ocr_index = OCRIndex(db_path)

    # Build hash table from already-moved files to detect duplicates
    known_hashes: dict[str, Path] = {}

    def _process(image_path: Path) -> None:
        phash = compute_phash(image_path)
        if phash:
            dup = is_duplicate(phash, known_hashes)
            if dup:
                logger.info("DUPLICATE  %s  (matches %s) — skipping", image_path.name, dup.name)
                return
            known_hashes[phash] = image_path

        result = classifier.classify(image_path)
        if result is None:
            logger.warning("SKIP  %s  (could not classify)", image_path.name)
            return

        dest = move_image(
            src=image_path,
            dest_dir=dest_root,
            category=result.category,
            confidence=result.confidence,
            dry_run=dry_run,
        )

        if ocr_index is not None and not dry_run:
            text = ocr_index.extract_text(dest)
            ocr_index.upsert(dest, result.category, text, phash or "")

    # One-shot pass over existing images
    images = _find_images(folder)
    if not images:
        logger.info("No supported images found in %s", folder)
    else:
        logger.info("Found %d image(s) in %s", len(images), folder)
        for img in images:
            _process(img)

    if watch:
        from .watcher import watch as fs_watch
        fs_watch(folder, _process)

    if ocr_index:
        ocr_index.close()


@main.command("search")
@click.argument("query")
@click.option(
    "--db",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to .screenshot_sorter.db",
)
@click.option("--verbose", "-v", is_flag=True)
def search_cmd(query: str, db: Path | None, verbose: bool) -> None:
    """Search the OCR index for QUERY text."""
    _setup_logging(verbose)

    db_path = db or Path(".screenshot_sorter.db")
    if not db_path.exists():
        click.echo("No index found. Run 'sort' first.", err=True)
        raise click.Abort()

    index = OCRIndex(db_path)
    results = index.search(query)
    index.close()

    if not results:
        click.echo(f"No results for '{query}'")
        return

    click.echo(f"Found {len(results)} result(s) for '{query}':\n")
    for r in results:
        click.echo(f"  [{r['category']:10s}]  {r['path']}")
        if verbose and r["ocr_text"]:
            snippet = r["ocr_text"][:120].replace("\n", " ")
            click.echo(f"             {snippet}…")
