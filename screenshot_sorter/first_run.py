"""
First-run bootstrap: installs heavy ML dependencies, then launches tray app.
Uses only ctypes (no tkinter, no external deps) for the progress window.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import subprocess
import sys
import threading
from pathlib import Path

_HEAVY_DEPS = [
    "torch>=2.0.0",
    "open-clip-torch>=2.24.0",
    "tqdm>=4.65.0",
]

_MARKER = Path(__file__).parent.parent / ".deps_installed"


def _deps_installed() -> bool:
    if not _MARKER.exists():
        return False
    try:
        import torch      # noqa: F401
        import open_clip  # noqa: F401
        return True
    except ImportError:
        return False


def _msgbox(title: str, text: str, error: bool = False) -> None:
    MB_OK = 0x0
    MB_ICONERROR = 0x10
    MB_ICONINFORMATION = 0x40
    icon = MB_ICONERROR if error else MB_ICONINFORMATION
    ctypes.windll.user32.MessageBoxW(0, text, title, MB_OK | icon)


def _install_deps_blocking() -> tuple[bool, str]:
    """Run pip install, return (success, error_output)."""
    python = sys.executable
    cmd = [
        python, "-m", "pip", "install",
        "--quiet", "--no-warn-script-location",
    ] + _HEAVY_DEPS
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode == 0:
        _MARKER.touch()
        return True, ""
    return False, (result.stdout + result.stderr)[-500:]


def _show_progress_and_install() -> None:
    """
    Show a Windows progress dialog (indeterminate) while installing.
    Uses the native TaskDialog via comctl32 if available,
    otherwise falls back to a simple MessageBox that closes on completion.
    """
    # We use a separate thread for the blocking install,
    # and show a non-blocking marquee progress via Windows API.

    done = threading.Event()
    result: dict = {"ok": False, "err": ""}

    def _worker():
        ok, err = _install_deps_blocking()
        result["ok"] = ok
        result["err"] = err
        done.set()

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    # Try to show a native progress window using win32 directly
    _show_native_progress(done)

    worker.join()

    if result["ok"]:
        _start_tray()
    else:
        _msgbox(
            "Screenshot Sorter - Error",
            "Failed to install dependencies.\n\n"
            "Please check your internet connection and try again.\n\n"
            + result["err"],
            error=True,
        )


def _show_native_progress(done: threading.Event) -> None:
    """
    Create a simple Win32 window with a progress bar (marquee).
    Blocks until `done` is set.
    """
    import ctypes.wintypes as wt

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
    )

    WS_OVERLAPPED  = 0x00000000
    WS_CAPTION     = 0x00C00000
    WS_SYSMENU     = 0x00080000
    WS_VISIBLE     = 0x10000000
    WS_CHILD       = 0x40000000
    WS_CLIPCHILDREN= 0x02000000
    SS_CENTER      = 0x00000001
    PBS_MARQUEE    = 0x08
    PBS_SMOOTH     = 0x01
    WM_DESTROY     = 0x0002
    WM_CLOSE       = 0x0010
    WM_TIMER       = 0x0113
    WM_CREATE      = 0x0001
    PBM_SETMARQUEE = 0x400 + 10
    PBM_SETRANGE   = 0x400 + 1

    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    comctl32 = ctypes.windll.comctl32
    comctl32.InitCommonControls()

    hinstance = kernel32.GetModuleHandleW(None)
    cls_name  = "SSProgressWnd"

    hwnd_holder: list[int] = [0]
    pb_holder:   list[int] = [0]

    @WNDPROC
    def _wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_CLOSE:
            return 0  # prevent manual close during install
        if msg == WM_TIMER:
            if done.is_set():
                user32.DestroyWindow(hwnd)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # Register window class
    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style",         ctypes.c_uint),
            ("lpfnWndProc",   WNDPROC),
            ("cbClsExtra",    ctypes.c_int),
            ("cbWndExtra",    ctypes.c_int),
            ("hInstance",     wt.HINSTANCE),
            ("hIcon",         wt.HICON),
            ("hCursor",       wt.HANDLE),
            ("hbrBackground", wt.HBRUSH),
            ("lpszMenuName",  wt.LPCWSTR),
            ("lpszClassName", wt.LPCWSTR),
        ]

    wc = WNDCLASSW()
    wc.lpfnWndProc   = _wndproc
    wc.hInstance     = hinstance
    wc.hbrBackground = ctypes.cast(6, wt.HBRUSH)  # COLOR_WINDOW+1
    wc.lpszClassName = cls_name
    wc.hCursor       = user32.LoadCursorW(0, ctypes.cast(32512, wt.LPCWSTR))
    user32.RegisterClassW(ctypes.byref(wc))

    W, H = 420, 160
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    x  = (sw - W) // 2
    y  = (sh - H) // 2

    hwnd = user32.CreateWindowExW(
        0, cls_name, "Screenshot Sorter",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE | WS_CLIPCHILDREN,
        x, y, W, H,
        0, 0, hinstance, None,
    )
    hwnd_holder[0] = hwnd

    # Static label
    user32.CreateWindowExW(
        0, "STATIC",
        "Downloading AI models (~600 MB), please wait...",
        WS_CHILD | WS_VISIBLE | SS_CENTER,
        20, 30, 380, 40,
        hwnd, 0, hinstance, None,
    )

    # Second label
    user32.CreateWindowExW(
        0, "STATIC",
        "This will take a few minutes on first launch.",
        WS_CHILD | WS_VISIBLE | SS_CENTER,
        20, 65, 380, 20,
        hwnd, 0, hinstance, None,
    )

    # Progress bar (marquee)
    pb = user32.CreateWindowExW(
        0, "msctls_progress32", "",
        WS_CHILD | WS_VISIBLE | PBS_MARQUEE | PBS_SMOOTH,
        20, 100, 380, 20,
        hwnd, 0, hinstance, None,
    )
    pb_holder[0] = pb

    # Start marquee animation (interval 30ms)
    user32.SendMessageW(pb, PBM_SETMARQUEE, 1, 30)

    # Timer to poll done flag every 500ms
    user32.SetTimer(hwnd, 1, 500, None)

    # Message loop
    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd",    wt.HWND),
            ("message", wt.UINT),
            ("wParam",  wt.WPARAM),
            ("lParam",  wt.LPARAM),
            ("time",    wt.DWORD),
            ("pt",      wt.POINT),
        ]

    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def _start_tray() -> None:
    from screenshot_sorter.tray_app import main as tray_main
    tray_main()


def main() -> None:
    silent = "--silent" in sys.argv

    if _deps_installed():
        _start_tray()
        return

    if silent:
        ok, _ = _install_deps_blocking()
        if ok:
            _start_tray()
        return

    _show_progress_and_install()


if __name__ == "__main__":
    main()
