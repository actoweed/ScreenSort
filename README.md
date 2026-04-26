# Screenshot Sorter

> [🇷🇺 Читать на русском](README.ru.md)

![Screenshot Sorter](assets/hero-dark.png)

Automatically sort your screenshots into categorised folders using [CLIP](https://github.com/mlfoundations/open_clip) zero-shot image classification. Runs as a **system tray app** on Windows — drop a screenshot into your folder and it's sorted instantly.

![Windows](https://img.shields.io/badge/Windows-10%2F11-blue) ![Python](https://img.shields.io/badge/Python-3.11-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

- **Tray app** — lives in the system tray, auto-sorts new screenshots as they arrive
- **Zero-shot CLIP classification** — no training data needed; just edit text prompts in `config.yaml`
- **Duplicate detection** — perceptual hashing skips near-identical images silently
- **Configurable categories** — add, rename, or remove categories by editing YAML only
- **No GPU required** — runs on CPU; first launch downloads ~400 MB of model weights

---

## Installation (Windows)

Download **`Install_ScreenshotSorter.exe`** from the [Releases](https://github.com/actoweed/ScreenSort/releases) page and run it.

- No Python required — everything is bundled
- On first launch, AI models are downloaded automatically (~400 MB)
- The app starts watching your Screenshots folder and adds itself to Windows startup

---

## Usage

After installation, the app runs in the background:

- **Tray icon** (bottom-right corner) → right-click for the menu
- **Start/Stop watching** — toggle auto-sorting
- **Change folder** — pick a different folder to watch
- **Open folder** — open the sorted output folder

User settings are saved to `%USERPROFILE%\.screenshot_sorter_config.json`.

---

## Configuration

Edit `config.yaml` (installed to `%LOCALAPPDATA%\ScreenshotSorter\config.yaml`) to customise categories:

```yaml
categories:
  code:
    description: "Source code, terminal output, or developer tools"
    prompts:
      - "a screenshot of source code in a code editor"
      - "a screenshot of a terminal or command line interface"

  invoices:
    description: "Financial documents and receipts"
    prompts:
      - "a screenshot of an invoice or receipt"
      - "a screenshot of a financial document"

# Minimum confidence to assign a category (0.0–1.0).
# Lower = more aggressive sorting, higher = more goes to 'other'
confidence_threshold: 0.10

# CLIP model — larger is more accurate but slower
# Options: ViT-B-32, ViT-B-16, ViT-L-14
clip_model: "ViT-B-32"
```

---

## How it works

1. **[CLIP](https://github.com/mlfoundations/open_clip)** embeds each image and your text prompts into the same vector space — the category whose prompt is closest to the image wins.
2. **[imagehash](https://github.com/JohannesBuchner/imagehash)** computes a perceptual hash before moving each file — near-duplicates are skipped silently.
3. **[watchdog](https://github.com/gorakhargosh/watchdog)** listens for filesystem events — no polling, zero CPU when idle.

---

## Building the installer

Requirements: Python 3.10+, [NSIS](https://nsis.sourceforge.io/Download) installed.

```bash
git clone https://github.com/actoweed/ScreenSort
cd screenshot-sorter
python installer/build_installer.py
```

The script will:
1. Download Python 3.11 embeddable runtime (~10 MB)
2. Download `get-pip.py`
3. Compile `installer/Output/Install_ScreenshotSorter.exe` via NSIS

---

## Project structure

```
screenshot-sorter/
├── config.yaml                   # Default category configuration
├── pyproject.toml
├── screenshot_sorter/
│   ├── tray_app.py               # System tray UI (Win32/pystray)
│   ├── first_run.py              # First-launch bootstrap + progress window
│   ├── classifier.py             # CLIP inference
│   ├── watcher.py                # watchdog folder watcher
│   ├── deduplicator.py           # Perceptual hash duplicate detection
│   ├── mover.py                  # File move operations
│   └── cli.py                    # CLI interface
├── installer/
│   ├── build_installer.py        # Build script — run this to produce .exe
│   ├── installer.nsi             # NSIS installer script
│   └── assets/
│       └── icon.ico
└── tests/
    └── test_classifier.py
```

---

## Development setup

```bash
git clone https://github.com/actoweed/ScreenSort
cd screenshot-sorter
pip install -e ".[dev]"

# Run tray app directly
python -m screenshot_sorter.tray_app

# CLI usage
python -m screenshot_sorter sort ./my-screenshots
python -m screenshot_sorter search "login error"

# Tests
pytest tests/
```

---

## License

MIT
