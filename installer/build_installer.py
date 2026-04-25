"""
Сборщик NSIS-установщика для Screenshot Sorter.

Запустить: python installer/build_installer.py
Результат: installer/Output/Install_ScreenshotSorter.exe
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

INSTALLER_DIR = Path(__file__).parent.resolve()
REPO_DIR = INSTALLER_DIR.parent
BOOTSTRAP_DIR = INSTALLER_DIR / "bootstrap"
ASSETS_DIR = INSTALLER_DIR / "assets"
OUTPUT_DIR = INSTALLER_DIR / "Output"

PYTHON_VERSION = "3.11.9"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)
PYTHON_EMBED_ZIP = BOOTSTRAP_DIR / f"python-{PYTHON_VERSION}-embed-amd64.zip"

GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
GET_PIP_FILE = BOOTSTRAP_DIR / "get-pip.py"

NSIS_CANDIDATES = [
    r"C:\Program Files (x86)\NSIS\makensis.exe",
    r"C:\Program Files\NSIS\makensis.exe",
]


def _print(msg: str, ok: bool | None = None) -> None:
    prefix = {True: "[OK] ", False: "[!!] ", None: "  >> "}[ok]
    print(prefix + msg)


def _download(url: str, dest: Path) -> None:
    if dest.exists():
        _print(f"Уже скачан: {dest.name}", ok=True)
        return
    _print(f"Скачиваю {dest.name}…")
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    _print(f"Скачан: {dest.name}", ok=True)


def _find_makensis() -> Path | None:
    for p in NSIS_CANDIDATES:
        if Path(p).exists():
            return Path(p)
    result = shutil.which("makensis")
    return Path(result) if result else None


def _make_ico() -> None:
    """Generate a minimal valid .ico file (32x32, blue camera)."""
    ico_path = ASSETS_DIR / "icon.ico"
    if ico_path.exists():
        return
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw

        size = 32
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([1, 1, 30, 30], fill=(52, 152, 219))
        draw.rectangle([7, 12, 25, 23], fill="white")
        draw.ellipse([12, 14, 20, 21], fill=(52, 73, 94))
        ico_path_str = str(ico_path)
        img.save(ico_path_str, format="ICO", sizes=[(32, 32)])
        _print("Иконка создана", ok=True)
    except Exception as exc:
        _print(f"Pillow недоступен для иконки ({exc}), используем заглушку", ok=None)
        # Write a minimal 1x1 transparent ICO as fallback
        _write_minimal_ico(ico_path)


def _write_minimal_ico(path: Path) -> None:
    """Write a minimal valid 16x16 ICO file."""
    # 16x16 RGBA ICO — hand-crafted bytes
    width = height = 16
    bpp = 32
    img_data_size = width * height * 4  # RGBA
    # BMP header for ICO (BITMAPINFOHEADER = 40 bytes)
    bi_size = 40
    # ICO header: 6 bytes
    # Image directory: 16 bytes
    # BMP header: 40 bytes
    # Pixel data: img_data_size bytes
    header = struct.pack("<HHH", 0, 1, 1)  # reserved, type=1(ICO), count=1
    data_offset = 6 + 16 + bi_size
    dir_entry = struct.pack(
        "<BBBBHHII",
        width, height, 0, 0,    # width, height, color count, reserved
        1, bpp,                  # planes, bit count
        bi_size + img_data_size, # size of image data
        data_offset,             # offset
    )
    bmp_header = struct.pack(
        "<IiiHHIIiiII",
        bi_size, width, height * 2,  # height*2 for ICO
        1, bpp, 0, img_data_size,
        0, 0, 0, 0,
    )
    # Blue pixels (BGRA)
    pixels = b"\x90\x60\x20\xFF" * (width * height)
    path.write_bytes(header + dir_entry + bmp_header + pixels)


def _patch_pth(embed_dir: Path) -> None:
    """Enable site-packages in Python embeddable by uncommenting import site."""
    pth_files = list(embed_dir.glob("python*._pth"))
    for pth in pth_files:
        content = pth.read_text(encoding="utf-8")
        patched = content.replace("#import site", "import site")
        if patched != content:
            pth.write_text(patched, encoding="utf-8")
            _print(f"Пропатчен {pth.name}", ok=True)


def _build() -> None:
    print()
    print("=" * 55)
    print("  Screenshot Sorter — сборка установщика")
    print("=" * 55)
    print()

    makensis = _find_makensis()
    if makensis is None:
        _print(
            "NSIS не найден. Скачай с https://nsis.sourceforge.io/Download и установи.",
            ok=False,
        )
        sys.exit(1)
    _print(f"NSIS найден: {makensis}", ok=True)

    # 1. Download assets
    _download(PYTHON_EMBED_URL, PYTHON_EMBED_ZIP)
    _download(GET_PIP_URL, GET_PIP_FILE)
    _make_ico()

    # 2. Extract Python embeddable to bootstrap/python/
    python_dir = BOOTSTRAP_DIR / "python"
    if not python_dir.exists():
        _print("Распаковываю Python embeddable…")
        with zipfile.ZipFile(PYTHON_EMBED_ZIP) as zf:
            zf.extractall(python_dir)
        _patch_pth(python_dir)
        _print("Python embeddable готов", ok=True)
    else:
        _patch_pth(python_dir)
        _print("Python embeddable уже распакован", ok=True)

    # 3. Verify key files exist before NSIS run
    required = [
        BOOTSTRAP_DIR / "python" / "python.exe",
        BOOTSTRAP_DIR / "python" / "pythonw.exe",
        BOOTSTRAP_DIR / "get-pip.py",
        ASSETS_DIR / "icon.ico",
        INSTALLER_DIR / "installer.nsi",
    ]
    for f in required:
        if not f.exists():
            _print(f"Не найден обязательный файл: {f}", ok=False)
            sys.exit(1)

    # 4. Run makensis
    nsi_script = INSTALLER_DIR / "installer.nsi"
    OUTPUT_DIR.mkdir(exist_ok=True)
    _print("Запускаю NSIS…")
    result = subprocess.run(
        [str(makensis), f'/DINSTALLER_DIR={INSTALLER_DIR}', str(nsi_script)],
        capture_output=False,
        cwd=str(INSTALLER_DIR),
    )
    if result.returncode != 0:
        _print("Ошибка сборки NSIS", ok=False)
        sys.exit(1)

    output_exe = OUTPUT_DIR / "Install_ScreenshotSorter.exe"
    if output_exe.exists():
        size_mb = output_exe.stat().st_size / 1024 / 1024
        print()
        print("=" * 55)
        _print(f"Готово! {output_exe}", ok=True)
        _print(f"Размер: {size_mb:.1f} МБ", ok=None)
        print("  Отправь этот файл пользователям — больше ничего не нужно.")
        print("=" * 55)
    else:
        _print("Файл установщика не найден после сборки", ok=False)
        sys.exit(1)


if __name__ == "__main__":
    _build()
