# Unique Image Finder

An Application for scanning directories to find duplicate and unique images using multiple criteria (size, name, metadata, perceptual hashing). Built with Python, Pillow for image processing and PyQt5 for the GUI.

This README explains how to create and use a dedicated virtual environment named `unq_img` on Linux, macOS and Windows, install required packages via `pip` and `requirements.txt`, run the application, and use the quick-start scripts.

---

## Quick start (one-liner)

From the project root, run this (Linux/macOS):

```
python3 -m venv unq_img && source unq_img/bin/activate && pip install --upgrade pip && pip install -r requirements.txt && python main.py
```

On Windows (PowerShell):

```
python -m venv unq_img; .\unq_img\Scripts\Activate.ps1; python -m pip install --upgrade pip; pip install -r requirements.txt; python main.py
```

---

## Prerequisites

- Python 3.7+ (3.8+ recommended)
- Git (optional, for cloning the repository)
- On some Linux distributions you may need system Qt packages if PyQt5 wheels fail to install:
  - Debian/Ubuntu example:
    sudo apt update
    sudo apt install -y qtbase5-dev qt5-default qttools5-dev-tools

---

## Create and activate the virtual environment `unq_img`

Linux and macOS (bash / zsh):

1. Open a terminal and go to the project root:
   cd /path/to/unique-image-finder

2. Create the venv:
   python3 -m venv unq_img

3. Activate it:
   source unq_img/bin/activate

4. Upgrade pip (recommended):
   pip install --upgrade pip

Windows (Command Prompt):

1. Open Command Prompt and go to the project root:
   cd C:\path\to\unique-image-finder

2. Create the venv:
   python -m venv unq_img

3. Activate it:
   .\unq_img\Scripts\activate

4. Upgrade pip:
   pip install --upgrade pip

Windows (PowerShell):

1. Open PowerShell and go to the project root:
   cd C:\path\to\unique-image-finder

2. Create the venv:
   python -m venv unq_img

3. If PowerShell blocks script execution, enable user-level remote-signed scripts (run once as Administrator or adjust scope as needed):
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

4. Activate it:
   .\unq_img\Scripts\Activate.ps1

5. Upgrade pip:
   pip install --upgrade pip

---

## Install dependencies

With the virtual environment activated, run:

```
pip install -r requirements.txt
```

This will install:
- PyQt5
- Pillow
- imagehash (used for perceptual hashing)

Notes:
- If `pip install PyQt5` fails on Linux, try installing the system Qt packages first (see Prerequisites above).

---

## Run the application

Make sure the virtual environment `unq_img` is activated, then from the project root run:

```
python main.py
```

The application window should open. Use "Browse Reference" and "Browse Working" to select folders, choose search options (size / name / metadata / hash), then click "Search".

---

## Quick-start scripts

Two convenience scripts are included in the `scripts/` folder:

- `scripts/quick_start.sh` — a POSIX shell script that creates/activates the venv, installs requirements, and launches the app (Linux/macOS).
- `scripts/quick_start.ps1` — a PowerShell script for Windows that does the same.

Run them from project root (make executable on Unix first):

```
# macOS / Linux
chmod +x scripts/quick_start.sh
./scripts/quick_start.sh

# Windows (PowerShell)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
./scripts/quick_start.ps1
```

---

## Image hashing and tuning

This project includes an optional perceptual hashing integration using the `imagehash` library. Use the UI "By Hash" checkbox and the hash controls (type, size, similarity) to tune detection sensitivity. Hashes are computed and cached in an SQLite DB via `core/hash_cache.py` to avoid recomputing on repeated runs.

Tuning tips:
- Start with pHash (Perceptual Hash) size 8 and similarity 90% as a good general-purpose setting.
- Use smaller sizes (4) with high similarity (98+) for near-exact duplicates (renames/copies).
- Use wHash or larger sizes for resized/cropped variants and lower similarity (80-90).

---

## Troubleshooting

- "ModuleNotFoundError: No module named 'PyQt5'": ensure venv is activated and run `pip install -r requirements.txt`.
- Pillow DecompressionBomb warning/error: the scanner disables Pillow's MAX_IMAGE_PIXELS to support large images; update Pillow if needed: `pip install --upgrade Pillow`.
- File permission errors when deleting or copying: ensure your user has the necessary filesystem permissions.

---

## Screenshots

Add screenshots or GIFs here. (Place image files under `docs/` and reference them with Markdown.)

Example:
````markdown
![Main window screenshot](docs/screenshot-main.png)
````

---

## License

No license specified for this repository.