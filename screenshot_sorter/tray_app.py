"""System tray application — no tkinter, pure Win32 via ctypes."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
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
_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

MB_OK          = 0x0
MB_ICONINFO    = 0x40
MB_ICONERROR   = 0x10

_user32  = ctypes.windll.user32
_shell32 = ctypes.windll.shell32
_ole32   = ctypes.windll.ole32


def _msgbox(title: str, text: str, style: int = MB_OK | MB_ICONINFO) -> int:
    result: list[int] = [0]
    done = threading.Event()
    def _run():
        result[0] = _user32.MessageBoxW(0, text, title, style)
        done.set()
    threading.Thread(target=_run, daemon=True).start()
    done.wait()
    return result[0]


def _folder_dialog(title: str) -> str | None:
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

    buf = ctypes.create_unicode_buffer(260)
    bi = BROWSEINFOW()
    bi.lpszTitle      = title
    bi.pszDisplayName = buf
    bi.ulFlags        = 0x0001 | 0x0040  # BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE

    _ole32.CoInitialize(None)
    pidl = _shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return None
    path_buf = ctypes.create_unicode_buffer(260)
    _shell32.SHGetPathFromIDListW(pidl, path_buf)
    _ole32.CoTaskMemFree(pidl)
    return path_buf.value or None


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
    return {"watch_folder": str(_find_default_folder()), "output_folder": "", "confidence_threshold": 0.10}


def _save_cfg(cfg: dict) -> None:
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _find_images(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _EXT]


# ---------------------------------------------------------------------------
# Progress window for batch sort (native Win32, no tkinter)
# ---------------------------------------------------------------------------

def _run_progress_window(title: str, total: int, get_done: callable, get_current: callable) -> None:
    """Show a marquee/progress window while batch sort runs. Blocking."""
    import ctypes.wintypes as wt

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    WS_VISIBLE = 0x10000000; WS_CHILD = 0x40000000
    WS_OVERLAPPED = 0x00000000; WS_CAPTION = 0x00C00000; WS_SYSMENU = 0x00080000
    WS_CLIPCHILDREN = 0x02000000; SS_CENTER = 0x01
    PBM_SETRANGE32 = 0x400 + 6; PBM_SETPOS = 0x400 + 2
    WM_DESTROY = 0x0002; WM_TIMER = 0x0113; WM_CLOSE = 0x0010
    WM_SETTEXT = 0x000C

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    comctl32 = ctypes.windll.comctl32
    comctl32.InitCommonControls()
    hinstance = kernel32.GetModuleHandleW(None)
    cls = "SSProgressWnd2"

    lbl_hwnd: list[int] = [0]
    pb_hwnd:  list[int] = [0]

    @WNDPROC
    def wndproc(hwnd, msg, wp, lp):
        if msg == WM_CLOSE:
            return 0  # prevent close during sort
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_TIMER:
            done = get_done()
            current = get_current()
            user32.SendMessageW(pb_hwnd[0], PBM_SETPOS, done, 0)
            label = f"Sorting: {current}  ({done}/{total})"
            user32.SendMessageW(lbl_hwnd[0], WM_SETTEXT, 0, label)
            if done >= total:
                user32.DestroyWindow(hwnd)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                    ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

    wc = WNDCLASSW()
    wc.lpfnWndProc = wndproc
    wc.hInstance = hinstance
    wc.hbrBackground = ctypes.cast(6, wt.HBRUSH)
    wc.lpszClassName = cls
    wc.hCursor = user32.LoadCursorW(0, ctypes.cast(32512, wt.LPCWSTR))
    user32.RegisterClassW(ctypes.byref(wc))

    W, H = 460, 120
    sw = user32.GetSystemMetrics(0); sh = user32.GetSystemMetrics(1)
    hwnd = user32.CreateWindowExW(
        0, cls, title,
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE | WS_CLIPCHILDREN,
        (sw - W) // 2, (sh - H) // 2, W, H, 0, 0, hinstance, None,
    )

    lbl = user32.CreateWindowExW(0, "STATIC", f"Starting... (0/{total})",
        WS_CHILD | WS_VISIBLE | SS_CENTER, 10, 12, 430, 20, hwnd, 0, hinstance, None)
    lbl_hwnd[0] = lbl

    pb = user32.CreateWindowExW(0, "msctls_progress32", "",
        WS_CHILD | WS_VISIBLE, 10, 42, 430, 20, hwnd, 0, hinstance, None)
    pb_hwnd[0] = pb
    user32.SendMessageW(pb, PBM_SETRANGE32, 0, total)
    user32.SendMessageW(pb, PBM_SETPOS, 0, 0)

    user32.SetTimer(hwnd, 1, 300, None)

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT),
                    ("wParam", wt.WPARAM), ("lParam", wt.LPARAM),
                    ("time", wt.DWORD), ("pt", wt.POINT)]
    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    user32.UnregisterClassW(cls, hinstance)


# ---------------------------------------------------------------------------
# Tray app
# ---------------------------------------------------------------------------

class TrayApp:
    def __init__(self) -> None:
        self._cfg        = _load_cfg()
        self._stop_event = threading.Event()
        self._watcher_thread: threading.Thread | None = None
        self._status     = "loading"
        self._count      = 0
        self._icon       = None
        self._classifier = None   # loaded once, reused

    # ------------------------------------------------------------------
    # Classifier (loaded once)
    # ------------------------------------------------------------------

    def _load_classifier(self) -> None:
        from .classifier import Classifier
        import yaml
        cfg_path = Path(__file__).parent.parent / "config.yaml"
        with open(cfg_path, encoding="utf-8") as fh:
            fc = yaml.safe_load(fh)
        self._classifier = Classifier(
            categories=fc.get("categories", {}),
            model_name=fc.get("clip_model", "ViT-B-32"),
            pretrained=fc.get("clip_pretrained", "openai"),
            confidence_threshold=self._cfg.get("confidence_threshold",
                                                fc.get("confidence_threshold", 0.10)),
        )
        self._classifier._load_model()

    def _ensure_classifier(self) -> bool:
        if self._classifier is not None:
            return True
        self._status = "loading"
        self._update_tooltip()
        try:
            self._load_classifier()
            return True
        except Exception as exc:
            logger.error("Failed to load CLIP: %s", exc)
            self._status = "stopped"
            self._update_tooltip()
            return False

    # ------------------------------------------------------------------
    # Process one image
    # ------------------------------------------------------------------

    def _process_image(self, image_path: Path, dest_root: Path,
                       known_hashes: dict) -> bool:
        from .deduplicator import compute_phash, is_duplicate
        from .mover import move_image
        try:
            phash = compute_phash(image_path)
            if phash:
                if is_duplicate(phash, known_hashes):
                    return False
                known_hashes[phash] = image_path
            result = self._classifier.classify(image_path)
            if result is None:
                return False
            move_image(src=image_path, dest_dir=dest_root,
                       category=result.category, confidence=result.confidence)
            return True
        except Exception as exc:
            logger.error("Error processing %s: %s", image_path, exc)
            return False

    # ------------------------------------------------------------------
    # Watcher (new files only)
    # ------------------------------------------------------------------

    def _run_watcher(self) -> None:
        if not self._ensure_classifier():
            return

        watch_folder = Path(self._cfg["watch_folder"])
        dest_root    = Path(self._cfg["output_folder"]) if self._cfg.get("output_folder") else watch_folder
        known_hashes: dict[str, Path] = {}

        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        app = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                p = Path(event.src_path)
                if p.suffix.lower() in _EXT:
                    time.sleep(0.8)
                    if app._process_image(p, dest_root, known_hashes):
                        app._count += 1
                        app._update_tooltip()

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
        self._watcher_thread = threading.Thread(target=self._run_watcher, daemon=True)
        self._watcher_thread.start()

    def stop_watcher(self) -> None:
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Batch sort existing folder
    # ------------------------------------------------------------------

    def _run_sort_folder(self) -> None:
        """Sort all existing images in watched folder, with progress window."""
        if not self._ensure_classifier():
            return

        watch_folder = Path(self._cfg["watch_folder"])
        dest_root    = Path(self._cfg["output_folder"]) if self._cfg.get("output_folder") else watch_folder
        images       = _find_images(watch_folder)

        if not images:
            _msgbox("Screenshot Sorter", f"No images found in:\n{watch_folder}", MB_OK | MB_ICONINFO)
            return

        total        = len(images)
        done:    list[int] = [0]
        current: list[str] = [""]
        known_hashes: dict[str, Path] = {}

        def _worker():
            for img in images:
                current[0] = img.name
                if self._process_image(img, dest_root, known_hashes):
                    self._count += 1
                done[0] += 1
            self._update_tooltip()

        threading.Thread(target=_worker, daemon=True).start()
        _run_progress_window(
            f"Sorting {total} images...",
            total,
            get_done=lambda: done[0],
            get_current=lambda: current[0],
        )
        _msgbox("Screenshot Sorter",
                f"Done! Sorted {self._count} image(s).\n\nFolder: {dest_root}",
                MB_OK | MB_ICONINFO)

    # ------------------------------------------------------------------
    # Tooltip
    # ------------------------------------------------------------------

    def _update_tooltip(self) -> None:
        if self._icon is None:
            return
        folder = Path(self._cfg["watch_folder"]).name
        if self._status == "loading":
            text = "Screenshot Sorter — loading AI model..."
        elif self._status == "running":
            text = f"Screenshot Sorter — watching {folder} ({self._count} sorted)"
        else:
            text = "Screenshot Sorter — stopped"
        try:
            self._icon.title = text
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _action_toggle(self, icon, item) -> None:
        if self._status == "running":
            self.stop_watcher()
        elif self._status != "loading":
            self.start_watcher()

    def _action_sort_now(self, icon, item) -> None:
        if self._status == "loading":
            _msgbox("Screenshot Sorter", "Still loading AI model, please wait...", MB_OK | MB_ICONINFO)
            return
        threading.Thread(target=self._run_sort_folder, daemon=True).start()

    def _action_change_folder(self, icon, item) -> None:
        folder = _folder_dialog("Select folder to watch")
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
        dest = Path(self._cfg["output_folder"]) if self._cfg.get("output_folder") else Path(self._cfg["watch_folder"])
        os.startfile(str(dest))

    def _action_status(self, icon, item) -> None:
        status = {"running": "Running", "loading": "Loading model...", "stopped": "Stopped"}.get(self._status, "?")
        _msgbox("Screenshot Sorter",
                f"Status: {status}\nFolder: {self._cfg['watch_folder']}\nSorted this session: {self._count}",
                MB_OK | MB_ICONINFO)

    def _action_quit(self, icon, item) -> None:
        self.stop_watcher()
        icon.stop()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            import pystray
        except ImportError:
            _msgbox("Screenshot Sorter", "Missing dependencies. Please re-run the installer.", MB_OK | MB_ICONERROR)
            sys.exit(1)

        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: "Stop watching" if self._status == "running" else
                             "Loading..." if self._status == "loading" else "Start watching",
                self._action_toggle,
                default=True,
                enabled=lambda item: self._status != "loading",
            ),
            pystray.MenuItem("Sort folder now", self._action_sort_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open folder",      self._action_open_folder),
            pystray.MenuItem("Change folder...", self._action_change_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Status", self._action_status),
            pystray.MenuItem("Quit",   self._action_quit),
        )

        self._icon = pystray.Icon("screenshot_sorter", _make_icon(), "Screenshot Sorter", menu)
        threading.Thread(target=self._auto_start, daemon=True).start()
        self._icon.run()

    def _auto_start(self) -> None:
        for _ in range(20):
            time.sleep(0.5)
            if self._icon is not None:
                break
        self.start_watcher()


def _make_icon():
    from PIL import Image as PILImage, ImageDraw
    size = 64
    img  = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=(52, 152, 219), outline=(41, 128, 185), width=2)
    draw.rectangle([14, 24, 50, 46], fill="white")
    draw.ellipse([24, 27, 40, 43], fill=(52, 73, 94))
    draw.ellipse([27, 30, 37, 40], fill=(127, 140, 141))
    draw.rectangle([18, 20, 26, 24], fill="white")
    return img


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
    TrayApp().run()
