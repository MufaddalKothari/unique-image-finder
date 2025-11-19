```markdown
# Image Comparison Application (PyQt5)

A minimal starter application for comparing image folders. Features:
- Search by size, name, metadata
- Hash UI controls (dropdown presets) and info dialog (wiring for imagehash is left optional)
- Find uniques option (shows only uniques)
- Thumbnails for duplicates and uniques
- Comparison modal with metadata table and delete actions
- Bulk actions: Delete All Duplicates (deletes the working-side duplicates), Keep All (remove from view), Save Uniques to a new directory
- Safe handling of very large images (Pillow decompression limit disabled)

Requirements
------------
Create a virtual environment and install:
```
pip install -r requirements.txt
```

Run
---
From project root:
```
python main.py
```

Project structure
-----------------
```
├── main.py
├── requirements.txt
├── README.md
├── core/
│   ├── hash_cache.py
│   ├── image_scanner.py
│   └── comparator.py
└── ui/
    ├── main_window.py
    ├── comparison_modal.py
    ├── hash_info_dialog.py
    └── styles.py
```

Packaging as ZIP
----------------
On macOS / Linux:
```
zip -r image_comparator.zip .
```
On Windows (PowerShell):
```
Compress-Archive -Path * -DestinationPath image_comparator.zip
```

Notes & Next steps
------------------
- The hash UI is implemented; to get hash matching you need to integrate `imagehash` and call into `core/hash_cache.py` to compute/store hashes. I can do that next if you'd like.
- Deletions are immediate `os.remove` operations. If you want a safer default, I can implement "move to Trash" or "move to a configurable Trash folder" instead.
- Large-image preview generation currently uses QPixmap (Pillow loading in the scanner is tolerant). If you encounter memory issues, I can implement thumbnail-only streaming (generate small preview files or use Image.thumbnail before loading into Qt).
