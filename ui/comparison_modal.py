from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpacerItem, QSizePolicy,
    QMessageBox, QTableWidget, QTableWidgetItem
)
from PyQt5.QtGui import QPixmap, QColor
from PyQt5.QtCore import Qt
import os

class ComparisonModal(QDialog):
    """
    Comparison modal shows the two images side-by-side and displays metadata
    in a two-column table. It accepts a callback to notify the caller about
    delete actions. The callback signature: callback(action: str, paths: list[str])
    where action is one of: 'delete_both', 'delete_ref', 'delete_work', 'keep_both'
    """

    def __init__(self, image1_path, image2_path, meta1: dict, meta2: dict, match_criteria: str, action_callback=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Comparison")
        self.setMinimumWidth(900)
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
                img1_label.setPixmap(pix1.scaled(400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
                img2_label.setPixmap(pix2.scaled(400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                img2_label.setText("Unable to load image")
        else:
            img2_label.setText("Missing")

        imgs_layout.addWidget(img2_label)
        layout.addLayout(imgs_layout)

        # Metadata table
        table = QTableWidget()
        keys = ["name", "size", "path", "dimensions", "mode", "mtime"]
        table.setRowCount(len(keys))
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Reference", "Working"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)

        for row, key in enumerate(keys):
            left_val = meta1.get(key, "")
            right_val = meta2.get(key, "")
            left_item = QTableWidgetItem(str(left_val))
            right_item = QTableWidgetItem(str(right_val))

            # Highlight if equal and non-empty
            if left_val != "" and left_val == right_val:
                left_item.setBackground(QColor(255, 230, 230))  # subtle red tint
                right_item.setBackground(QColor(255, 230, 230))

            table.setItem(row, 0, left_item)
            table.setItem(row, 1, right_item)
            table.setVerticalHeaderItem(row, QTableWidgetItem(key.capitalize()))

        table.resizeColumnsToContents()
        table.setFixedHeight(min(200 + 30 * len(keys), 400))
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