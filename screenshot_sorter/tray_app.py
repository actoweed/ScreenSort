"""System tray application — no tkinter, pure Win32 via ctypes."""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_FILE = Path.home() / ".screenshot_sorter_config.json"
_DEFAULT_DIRS = [
    Path.home() / "Pictures" / "Screenshots",
    Path.home() / "Pictures",
    Path.home() / "Desktop",
]

# Win32 constants
MB_OK            = 0x0
MB_YESNO         = 0x4
MB_ICONINFO      = 0x40
MB_ICONERROR     = 0x10
MB_ICONQUESTION  = 0x20
IDYES            = 6

_user32   = ctypes.windll.user32
_shell32  = ctypes.windll.shell32
_ole32    = ctypes.windll.ole32
_comdlg32 = ctypes.windll.comdlg32


def _msgbox(title: str, text: str, style: int = MB_OK | MB_ICONINFO) -> int:
    # Run in its own thread so it never blocks the pystray event loop
    result: list[int] = [0]
    done = threading.Event()
    def _run():
        result[0] = _user32.MessageBoxW(0, text, title, style)
        done.set()
    threading.Thread(target=_run, daemon=True).start()
    done.wait()
    return result[0]



def _folder_dialog(title: str, initial: str = "") -> str | None:
    """Show a folder picker using shell32 BrowseForFolder."""
    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [
            ("hwndOwner",      wt.HWND),
            ("pidlRoot",       ctypes.c_void_p),
            ("pszDisplayName", wt.LPWSTR),
            ("lpszTitle",      wt.LPCWSTR),
            ("ulFlags",        wt.UINT),
            ("lpfn",           ctypes.c_void_p),
            ("lParam",         ctypes.c_void_p),
            ("iImage",         ctypes.c_int),
        ]

    BIF_RETURNONLYFSDIRS = 0x0001
    BIF_NEWDIALOGSTYLE   = 0x0040
    buf = ctypes.create_unicode_buffer(260)
    bi = BROWSEINFOW()
    bi.lpszTitle      = title
    bi.pszDisplayName = buf
    bi.ulFlags        = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE

    _ole32.CoInitialize(None)
    pidl = _shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return None

    path_buf = ctypes.create_unicode_buffer(260)
    _shell32.SHGetPathFromIDListW(pidl, path_buf)
    _ole32.CoTaskMemFree(pidl)
    result = path_buf.value
    return result if result else None


def _find_default_folder() -> Path:
    for d in _DEFAULT_DIRS:
        if d.exists():
            return d
    return Path.home()


def _load_cfg() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "watch_folder": str(_find_default_folder()),
        "output_folder": "",
        "confidence_threshold": 0.10,
    }


def _save_cfg(cfg: dict) -> None:
    _CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Watcher logic
# ---------------------------------------------------------------------------

class TrayApp:
    def __init__(self) -> None:
        self._cfg = _load_cfg()
        self._stop_event = threading.Event()
        self._watcher_thread: threading.Thread | None = None
        self._status = "stopped"
        self._count = 0
        self._icon = None

    # --- watcher ---

    def _run_watcher(self) -> None:
        from .classifier import Classifier
        from .deduplicator import compute_phash, is_duplicate
        from .mover import move_image
        import yaml

        cfg_path = Path(__file__).parent.parent / "config.yaml"
        with open(cfg_path, encoding="utf-8") as fh:
            file_cfg = yaml.safe_load(fh)

        categories           = file_cfg.get("categories", {})
        model_name           = file_cfg.get("clip_model", "ViT-B-32")
        pretrained           = file_cfg.get("clip_pretrained", "openai")
        confidence_threshold = self._cfg.get(
            "confidence_threshold", file_cfg.get("confidence_threshold", 0.10)
        )

        watch_folder = Path(self._cfg["watch_folder"])
        dest_root    = (
            Path(self._cfg["output_folder"])
            if self._cfg.get("output_folder")
            else watch_folder
        )

        classifier = Classifier(
            categories=categories,
            model_name=model_name,
            pretrained=pretrained,
            confidence_threshold=confidence_threshold,
        )
        known_hashes: dict[str, Path] = {}

        def _process(image_path: Path) -> None:
            try:
                phash = compute_phash(image_path)
                if phash:
                    dup = is_duplicate(phash, known_hashes)
                    if dup:
                        return
                    known_hashes[phash] = image_path
                result = classifier.classify(image_path)
                if result is None:
                    return
                move_image(
                    src=image_path,
                    dest_dir=dest_root,
                    category=result.category,
                    confidence=result.confidence,
                )
                self._count += 1
                self._update_tooltip()
            except Exception as exc:
                logger.error("Error processing %s: %s", image_path, exc)

        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        _EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                p = Path(event.src_path)
                if p.suffix.lower() in _EXT:
                    time.sleep(0.8)
                    _process(p)

        observer = Observer()
        observer.schedule(_Handler(), str(watch_folder), recursive=False)
        observer.start()
        self._status = "running"
        self._update_tooltip()
        logger.info("Watching: %s", watch_folder)

        try:
            while not self._stop_event.is_set():
                time.sleep(1)
        finally:
            observer.stop()
            observer.join()
            self._status = "stopped"
            self._update_tooltip()

    def start_watcher(self) -> None:
        if self._watcher_thread and self._watcher_thread.is_alive():
            return
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(
            target=self._run_watcher, daemon=True
        )
        self._watcher_thread.start()

    def stop_watcher(self) -> None:
        self._stop_event.set()

    def _update_tooltip(self) -> None:
        if self._icon is None:
            return
        folder = Path(self._cfg["watch_folder"]).name
        if self._status == "running":
            text = f"Screenshot Sorter — watching {folder} ({self._count} sorted)"
        else:
            text = "Screenshot Sorter — stopped"
        try:
            self._icon.title = text
        except Exception:
            pass

    # --- menu actions ---

    def _action_toggle(self, icon, item) -> None:
        if self._status == "running":
            self.stop_watcher()
        else:
            self.start_watcher()

    def _action_change_folder(self, icon, item) -> None:
        folder = _folder_dialog(
            "Select folder to watch",
            self._cfg["watch_folder"],
        )
        if not folder:
            return
        was_running = self._status == "running"
        if was_running:
            self.stop_watcher()
            time.sleep(1.5)
        self._cfg["watch_folder"] = folder
        _save_cfg(self._cfg)
        if was_running:
            self.start_watcher()

    def _action_open_folder(self, icon, item) -> None:
        dest = (
            Path(self._cfg["output_folder"])
            if self._cfg.get("output_folder")
            else Path(self._cfg["watch_folder"])
        )
        os.startfile(str(dest))

    def _action_status(self, icon, item) -> None:
        status = "Running" if self._status == "running" else "Stopped"
        folder = self._cfg["watch_folder"]
        _msgbox(
            "Screenshot Sorter",
            f"Status: {status}\nFolder: {folder}\nSorted this session: {self._count}",
            MB_OK | MB_ICONINFO,
        )

    def _action_quit(self, icon, item) -> None:
        self.stop_watcher()
        icon.stop()

    # --- run ---

    def run(self) -> None:
        try:
            import pystray
            from PIL import Image as PILImage
        except ImportError:
            _msgbox(
                "Screenshot Sorter",
                "Missing dependencies. Please re-run the installer.",
                MB_OK | MB_ICONERROR,
            )
            sys.exit(1)

        icon_img = _make_icon()

        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: "Stop watching" if self._status == "running" else "Start watching",
                self._action_toggle,
                default=True,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open folder",      self._action_open_folder),
            pystray.MenuItem("Change folder...", self._action_change_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Status", self._action_status),
            pystray.MenuItem("Quit",   self._action_quit),
        )

        self._icon = pystray.Icon(
            "screenshot_sorter",
            icon_img,
            "Screenshot Sorter",
            menu,
        )

        threading.Thread(target=self._auto_start, daemon=True).start()
        self._icon.run()

    def _auto_start(self) -> None:
        # Wait until tray icon is fully initialized before starting watcher
        for _ in range(20):
            time.sleep(0.5)
            if self._icon is not None:
                break
        self.start_watcher()


def _make_icon():
    from PIL import Image as PILImage, ImageDraw
    size = 64
    img = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=(52, 152, 219), outline=(41, 128, 185), width=2)
    draw.rectangle([14, 24, 50, 46], fill="white")
    draw.ellipse([24, 27, 40, 43], fill=(52, 73, 94))
    draw.ellipse([27, 30, 37, 40], fill=(127, 140, 141))
    draw.rectangle([18, 20, 26, 24], fill="white")
    return img


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    app = TrayApp()
    app.run()
