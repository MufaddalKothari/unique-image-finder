from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QListWidgetItem,
    QWidget, QFrame, QMessageBox, QFileDialog, QProgressBar, QSizePolicy, QToolButton
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from core.cache_db import CacheDB
from core.indexer import Indexer
import os
import time

class CacheCard(QWidget):
    def __init__(self, dir_row: dict, parent=None):
        super().__init__(parent)
        self.dir_row = dir_row
        self.dir_id = dir_row["dir_id"]
        self.path = dir_row["path"]
        layout = QHBoxLayout(self)
        self.label = QLabel(f"{self.path}")
        self.info = QLabel("")
        self.info.setStyleSheet("color: rgba(0,0,0,0.5);")
        self.refresh_btn = QPushButton("Refresh")
        self.rehash_btn = QPushButton("Rehash")
        self.open_btn = QPushButton("Open")
        layout.addWidget(self.label, 1)
        layout.addWidget(self.info)
        layout.addWidget(self.refresh_btn)
        layout.addWidget(self.rehash_btn)
        layout.addWidget(self.open_btn)
        self.setMaximumHeight(48)

class CachedDirsModal(QDialog):
    def __init__(self, db: CacheDB, indexer: Indexer, parent=None):
        super().__init__(parent)
        self.db = db
        self.indexer = indexer
        self.setWindowTitle("Cached directories")
        self.setModal(True)
        self.resize(720, 420)
        self.layout = QVBoxLayout(self)
        top_row = QHBoxLayout()
        self.add_btn = QPushButton("Add directory")
        self.add_btn.setToolTip("Add a directory to be cached and indexed in background")
        self.close_btn = QPushButton("Close")
        top_row.addWidget(self.add_btn)
        top_row.addStretch(1)
        top_row.addWidget(self.close_btn)
        self.layout.addLayout(top_row)

        self.list_widget = QListWidget()
        self.layout.addWidget(self.list_widget, 1)

        # connections
        self.add_btn.clicked.connect(self._on_add)
        self.close_btn.clicked.connect(self.accept)

        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        dirs = self.db.list_dirs()
        for d in dirs:
            item = QListWidgetItem()
            widget = CacheCard(d)
            # update info text
            files = self.db.get_files_by_dir(d["dir_id"])
            widget.info.setText(f"files: {len(files)} | last indexed: {d.get('last_indexed')}")
            # wire buttons
            widget.refresh_btn.clicked.connect(lambda _, did=d["dir_id"]: self._on_refresh(did))
            widget.rehash_btn.clicked.connect(lambda _, did=d["dir_id"]: self._on_rehash(did))
            widget.open_btn.clicked.connect(lambda _, p=d["path"]: os.startfile(p) if os.path.isdir(p) else None)
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
        # enqueue index job
        self.indexer.enqueue("index", dir_id)
        QMessageBox.information(self, "Queued", f"Directory queued for background indexing: {path}")
        self._refresh_list()

    def _on_refresh(self, dir_id: int):
        self.indexer.enqueue("refresh", dir_id)
        QMessageBox.information(self, "Queued", "Refresh (incremental) queued.")
        self._refresh_list()

    def _on_rehash(self, dir_id: int):
        self.indexer.enqueue("rehash", dir_id)
        QMessageBox.information(self, "Queued", "Rehash (full) queued.")
        self._refresh_list()