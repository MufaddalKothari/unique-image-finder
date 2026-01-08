from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpacerItem, QSizePolicy,
    QMessageBox, QTableWidget, QTableWidgetItem
)
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtCore import Qt
import os
from datetime import datetime

def _human_ts(ts):
    try:
        return datetime.fromtimestamp(int(ts)).isoformat(sep=' ')
    except Exception:
        return str(ts)

class ComparisonModal(QDialog):
    """
    Comparison modal shows the two images side-by-side and displays extended metadata
    in a two-column table. It accepts a callback to notify the caller about deletion actions.
    """

    def __init__(self, image1_path, image2_path, meta1: dict, meta2: dict, match_criteria: str, action_callback=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Comparison")
        self.setMinimumWidth(1000)
        self._action_callback = action_callback
        self._ref_path = image1_path
        self._work_path = image2_path

        layout = QVBoxLayout(self)

        imgs_layout = QHBoxLayout()
        # Left image (reference)
        img1_label = QLabel()
        if os.path.exists(image1_path):
            pix1 = QPixmap(image1_path)
            if not pix1.isNull():
                img1_label.setPixmap(pix1.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                img1_label.setText("Unable to load image")
        else:
            img1_label.setText("Missing")

        imgs_layout.addWidget(img1_label)

        imgs_layout.addSpacerItem(QSpacerItem(20, 10, QSizePolicy.Fixed, QSizePolicy.Minimum))

        # Right image (working)
        img2_label = QLabel()
        if os.path.exists(image2_path):
            pix2 = QPixmap(image2_path)
            if not pix2.isNull():
                img2_label.setPixmap(pix2.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                img2_label.setText("Unable to load image")
        else:
            img2_label.setText("Missing")

        imgs_layout.addWidget(img2_label)
        layout.addLayout(imgs_layout)

        # Metadata table: extended keys including creation & copyright/artist/origin
        keys = [
            ("Name", "name"),
            ("Size (bytes)", "size"),
            ("Path", "path"),
            ("Dims (W×H)", "dimensions"),
            ("Mode", "mode"),
            ("Created (fs)", "created"),
            ("EXIF DateTimeOriginal", "datetime_original"),
            ("Artist / Author", "artist"),
            ("Copyright", "copyright"),
            ("Camera Make", "make"),
            ("Camera Model", "model"),
            ("Image Description", "image_description"),
            ("Origin", "origin"),
            ("MTime", "mtime")
        ]

        table = QTableWidget()
        table.setRowCount(len(keys))
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Reference", "Working"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)

        for row, (label, key) in enumerate(keys):
            left_val = meta1.get(key, "")
            right_val = meta2.get(key, "")

            # Format some fields for readability
            if key in ("created", "mtime") and left_val:
                left_display = _human_ts(left_val)
            else:
                left_display = left_val

            if key in ("created", "mtime") and right_val:
                right_display = _human_ts(right_val)
            else:
                right_display = right_val

            left_item = QTableWidgetItem(str(left_display))
            right_item = QTableWidgetItem(str(right_display))

            # Highlight if equal and non-empty
            if left_display != "" and left_display == right_display:
                left_item.setBackground(QColor(255, 230, 230))  # subtle red tint
                right_item.setBackground(QColor(255, 230, 230))

            table.setItem(row, 0, left_item)
            table.setItem(row, 1, right_item)
            table.setVerticalHeaderItem(row, QTableWidgetItem(label))

        table.resizeColumnsToContents()
        table.setFixedHeight(min(240 + 28 * len(keys), 520))
        layout.addWidget(table)

        layout.addWidget(QLabel(f"<span style='color:red'>Match Criteria: {match_criteria}</span>"))

        # Actions
        btn_layout = QHBoxLayout()
        btn_delete_both = QPushButton("Delete Both")
        btn_delete_ref = QPushButton("Delete Reference")
        btn_delete_work = QPushButton("Delete Working")
        btn_keep_both = QPushButton("Keep Both")

        btn_delete_both.clicked.connect(lambda: self._confirmed_action("delete_both"))
        btn_delete_ref.clicked.connect(lambda: self._confirmed_action("delete_ref"))
        btn_delete_work.clicked.connect(lambda: self._confirmed_action("delete_work"))
        btn_keep_both.clicked.connect(lambda: self._confirmed_action("keep_both"))

        btn_layout.addWidget(btn_delete_both)
        btn_layout.addWidget(btn_delete_ref)
        btn_layout.addWidget(btn_delete_work)
        btn_layout.addWidget(btn_keep_both)
        layout.addLayout(btn_layout)

    def _confirmed_action(self, action: str):
        human = {
            "delete_both": "Delete both files?",
            "delete_ref": "Delete the reference file?",
            "delete_work": "Delete the working file?",
            "keep_both": "Keep both files (no deletions)?"
        }.get(action, "Proceed?")
        reply = QMessageBox.question(self, "Confirm", human, QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            paths = []
            if action == "delete_both":
                paths = [self._ref_path, self._work_path]
            elif action == "delete_ref":
                paths = [self._ref_path]
            elif action == "delete_work":
                paths = [self._work_path]
            elif action == "keep_both":
                paths = []
            # Notify caller
            if callable(self._action_callback):
                self._action_callback(action, paths)
            self.accept()