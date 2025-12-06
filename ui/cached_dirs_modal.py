# ui/cached_dirs_modal.py
# Regenerated cached directories modal with colored action buttons and improved info display.
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QListWidgetItem,
    QWidget, QMessageBox, QFileDialog, QProgressBar, QSizePolicy
)
from PyQt5.QtCore import Qt
from core.cache_db import CacheDB
from core.indexer import Indexer
import os
import time
import logging

logger = logging.getLogger(__name__)


class CacheCard(QWidget):
    def __init__(self, dir_row: dict, db: CacheDB, parent=None):
        super().__init__(parent)
        self.dir_row = dir_row
        self.db = db
        self.dir_id = dir_row["dir_id"]
        self.path = dir_row["path"]

        self.setObjectName("cache_card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        self.label = QLabel(self.path)
        self.label.setMinimumWidth(320)
        self.info = QLabel()
        self.info.setStyleSheet("color: rgba(0,0,0,0.55);")
        self.info.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # action buttons with object names for styles
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("cache_refresh_btn")
        self.rehash_btn = QPushButton("Rehash")
        self.rehash_btn.setObjectName("cache_rehash_btn")
        self.open_btn = QPushButton("Open")
        self.open_btn.setObjectName("cache_open_btn")

        layout.addWidget(self.label)
        layout.addWidget(self.info, 1)
        layout.addWidget(self.refresh_btn)
        layout.addWidget(self.rehash_btn)
        layout.addWidget(self.open_btn)
        self.setMaximumHeight(56)

        self.update_info()

    def update_info(self):
        try:
            files = self.db.get_files_by_dir(self.dir_id)
            total = len(files)
            last_indexed = self.dir_row.get("last_indexed")
            last_txt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_indexed)) if last_indexed else "never"
            # count hashed rows (hash_hex not null)
            hashed = sum(1 for f in files if f.get("hash_hex"))
            self.info.setText(f"files indexed: {hashed}/{total} • last indexed: {last_txt}")
        except Exception as e:
            logger.exception("Failed to update card info: %s", e)
            self.info.setText("info unavailable")


class CachedDirsModal(QDialog):
    def __init__(self, db: CacheDB, indexer: Indexer, parent=None):
        super().__init__(parent)
        self.db = db
        self.indexer = indexer
        self.setWindowTitle("Cached directories")
        self.setModal(True)
        self.resize(800, 480)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(10)

        top_row = QHBoxLayout()
        self.add_btn = QPushButton("Add directory")
        self.add_btn.setObjectName("cache_add_btn")
        self.close_btn = QPushButton("Close")
        top_row.addWidget(self.add_btn)
        top_row.addStretch(1)
        top_row.addWidget(self.close_btn)
        self.layout.addLayout(top_row)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(6)
        self.layout.addWidget(self.list_widget, 1)

        # connections
        self.add_btn.clicked.connect(self._on_add)
        self.close_btn.clicked.connect(self.accept)

        # initial refresh
        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        dirs = self.db.list_dirs()
        for d in dirs:
            item = QListWidgetItem()
            widget = CacheCard(d, self.db)
            # wire buttons (capture current d)
            widget.refresh_btn.clicked.connect(lambda _, did=d["dir_id"]: self._on_refresh(did))
            widget.rehash_btn.clicked.connect(lambda _, did=d["dir_id"]: self._on_rehash(did))
            widget.open_btn.clicked.connect(lambda _, p=d["path"]: self._on_open(p))
            item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def _on_add(self):
        dlg = QFileDialog(self, caption="Select directory to cache")
        dlg.setFileMode(QFileDialog.Directory)
        if not dlg.exec_():
            return
        path = dlg.selectedFiles()[0]
        if not os.path.isdir(path):
            QMessageBox.information(self, "Not a folder", "Please select a valid folder.")
            return
        dir_id = self.db.add_dir(path)
        self.indexer.enqueue("index", dir_id)
        QMessageBox.information(self, "Queued", f"Directory queued for background indexing:\n{path}")
        self._refresh_list()

    def _on_refresh(self, dir_id: int):
        try:
            self.indexer.enqueue("refresh", dir_id)
            QMessageBox.information(self, "Queued", "Refresh (incremental) queued.")
        except Exception as e:
            logger.exception("Failed to enqueue refresh: %s", e)
            QMessageBox.warning(self, "Error", "Could not queue refresh.")
        self._refresh_list()

    def _on_rehash(self, dir_id: int):
        try:
            self.indexer.enqueue("rehash", dir_id)
            QMessageBox.information(self, "Queued", "Rehash (full) queued.")
        except Exception as e:
            logger.exception("Failed to enqueue rehash: %s", e)
            QMessageBox.warning(self, "Error", "Could not queue rehash.")
        self._refresh_list()

    def _on_open(self, path: str):
        try:
            if os.path.isdir(path):
                # platform neutral attempt to open; prefer native when available
                try:
                    os.startfile(path)
                except AttributeError:
                    # use open on macOS / xdg-open on Linux
                    if os.name == "posix":
                        if sys.platform == "darwin":
                            os.system(f"open {repr(path)}")
                        else:
                            os.system(f"xdg-open {repr(path)}")
            else:
                QMessageBox.information(self, "Not found", "Directory not found on disk.")
        except Exception as e:
            logger.exception("Failed to open folder: %s", e)
            QMessageBox.warning(self, "Error", "Could not open folder.")

    def exec_and_refresh(self):
        """
        Convenience: exec_() then refresh list on exit.
        """
        res = self.exec_()
        self._refresh_list()
        return res