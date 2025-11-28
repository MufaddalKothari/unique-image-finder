# ui/main_window.py
# Updates:
# - When any fields are checked in the Compare fields dropdown, the hash checkbox & controls are disabled.
# - When hash is checked, the Compare fields dropdown is disabled.
# - Folder labels now include the requested hints "(More Images)" and "(Less Images)".
# - Ensures nested directories are scanned (scan_images_in_directory uses os.walk by default).

import os
import shutil
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QGroupBox, QFileDialog, QComboBox, QCheckBox, QProgressBar,
    QScrollArea, QSizePolicy, QFrame, QMessageBox, QToolButton, QMenu, QAction
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QGraphicsDropShadowEffect
from core.image_scanner import scan_images_in_directory, ImageFileObj
from core.comparator import find_duplicates, find_uniques
from .styles import GLASSY_STYLE
from .comparison_modal import ComparisonModal
from .hash_info_dialog import HashInfoDialog
from send2trash import send2trash

class SearchThread(QThread):
    results_ready = pyqtSignal(object)   # will emit a dict with results
    progress = pyqtSignal(int)

    def __init__(self, ref_dir, work_dir, criteria):
        super().__init__()
        self.ref_dir = ref_dir
        self.work_dir = work_dir
        self.criteria = criteria

    def run(self):
        # Scan both directories (scan_images_in_directory recurses by default)
        self.progress.emit(5)
        ref_files = scan_images_in_directory(self.ref_dir) if self.ref_dir else []
        self.progress.emit(40)
        work_files = scan_images_in_directory(self.work_dir) if self.work_dir else []
        self.progress.emit(70)

        duplicates = []
        uniques = ([], [])
        try:
            duplicates = find_duplicates(ref_files, work_files, self.criteria)
        except Exception as e:
            import logging
            logging.exception("find_duplicates failed: %s", e)

        try:
            uniques = find_uniques(ref_files, work_files, self.criteria)
            if uniques is None:
                uniques = ([], [])
        except Exception as e:
            import logging
            logging.exception("find_uniques failed: %s", e)
            uniques = ([], [])

        self.progress.emit(95)

        self.results_ready.emit({
            "duplicates": duplicates,
            "unique_in_ref": uniques[0],
            "unique_in_work": uniques[1],
            "ref_files": ref_files,
            "work_files": work_files,
            "criteria": self.criteria
        })
        self.progress.emit(100)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Comparison Application")
        self.setMinimumWidth(1200)
        try:
            self.setStyleSheet(GLASSY_STYLE)
        except Exception:
            pass

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("🖼️ Image Comparison Application")
        header.setStyleSheet("font-size:28px; font-weight:700; padding:14px 0px 12px 5px;")
        layout.addWidget(header)

        # Directory selectors (labels include the hints the user requested)
        dir_layout = QHBoxLayout()
        self.ref_dir = QLineEdit()
        self.work_dir = QLineEdit()
        ref_btn = QPushButton("Browse Reference")
        work_btn = QPushButton("Browse Working")
        ref_btn.clicked.connect(lambda: self.browse_dir(self.ref_dir))
        work_btn.clicked.connect(lambda: self.browse_dir(self.work_dir))
        dir_layout.addWidget(QLabel("Reference Folder (More Images):"))
        dir_layout.addWidget(self.ref_dir)
        dir_layout.addWidget(ref_btn)
        dir_layout.addSpacing(15)
        dir_layout.addWidget(QLabel("Working Folder (Less Images):"))
        dir_layout.addWidget(self.work_dir)
        dir_layout.addWidget(work_btn)
        layout.addLayout(dir_layout)

        # Search options group
        opts_group = QGroupBox("Search Options")
        opts_layout = QHBoxLayout()

        # Field selector (QToolButton + QMenu); when any field is checked, disable hashing
        self.field_selector_btn = QToolButton()
        self.field_selector_btn.setText("Compare fields ▾")
        self.field_selector_btn.setPopupMode(QToolButton.InstantPopup)
        self.field_menu = QMenu(self)
        self.field_actions = {}
        fields = [
            ("Name", "name"),
            ("Size (bytes)", "size"),
            ("Created (fs)", "created"),
            ("Last modified (mtime)", "mtime"),
            ("Dimensions", "dimensions"),
            ("Mode", "mode"),
            ("Camera Make", "make"),
            ("Camera Model", "model"),
            ("Artist / Author", "artist"),
            ("Copyright", "copyright"),
            ("EXIF DateTimeOriginal", "datetime_original"),
            ("Origin (XMP/IPTC)", "origin"),
        ]
        for label, key in fields:
            act = QAction(label, self)
            act.setCheckable(True)
            # connect toggled to handler to enforce mutual exclusivity with hash
            act.toggled.connect(self._on_field_toggled)
            self.field_menu.addAction(act)
            self.field_actions[key] = act
        self.field_selector_btn.setMenu(self.field_menu)

        # Find Uniques checkbox (preserved)
        self.find_uniques_cb = QCheckBox("Find Uniques")

        # Hash checkbox and controls (when checked, disable field selector)
        self.hash_cb = QCheckBox("By Hash")
        self.hash_cb.stateChanged.connect(self._on_hash_toggled)
        self.hash_type = QComboBox()
        self.hash_type.addItems(["Average Hash", "Perceptual Hash", "Difference Hash", "Wavelet Hash"])
        self.hash_size_combo = QComboBox()
        hash_size_presets = ["4", "6", "8", "10", "12", "14", "16"]
        self.hash_size_combo.addItems(hash_size_presets)
        self.hash_size_combo.setCurrentText("8")
        self.similarity_combo = QComboBox()
        similarity_presets = ["50", "60", "70", "75", "80", "85", "90", "95", "98", "100"]
        self.similarity_combo.addItems(similarity_presets)
        self.similarity_combo.setCurrentText("90")
        self.hash_info_btn = QToolButton()
        self.hash_info_btn.setText("ℹ")
        self.hash_info_btn.setAutoRaise(True)
        self.hash_info_btn.clicked.connect(self._open_hash_info)

        opts_layout.addWidget(self.field_selector_btn)
        opts_layout.addWidget(self.find_uniques_cb)
        opts_layout.addWidget(self.hash_cb)
        opts_layout.addWidget(QLabel("Type:"))
        opts_layout.addWidget(self.hash_type)
        opts_layout.addWidget(self.hash_info_btn)
        opts_layout.addWidget(QLabel("Hash Size:"))
        opts_layout.addWidget(self.hash_size_combo)
        opts_layout.addWidget(QLabel("Similarity (%):"))
        opts_layout.addWidget(self.similarity_combo)

        opts_group.setLayout(opts_layout)
        layout.addWidget(opts_group)

        # Search button and progress
        act_layout = QHBoxLayout()
        self.search_btn = QPushButton("🔍 Search")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        act_layout.addWidget(self.search_btn)
        act_layout.addWidget(self.progress)
        layout.addLayout(act_layout)

        # Results area
        self.results_area = QScrollArea()
        self.results_area.setWidgetResizable(True)
        layout.addWidget(self.results_area)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignTop)
        self.results_area.setWidget(self.results_container)

        # Footer with bulk buttons
        bulk_layout = QHBoxLayout()
        self.delete_btn = QPushButton("🗑️ Delete All Duplicates")
        self.keep_btn = QPushButton("✅ Keep All Duplicates")
        self.save_uniques_btn = QPushButton("💾 Save Uniques to New Directory")

        # Move / Delete dropdowns (styled externally)
        self.move_btn = QToolButton()
        self.move_btn.setText("Move ▾")
        self.move_btn.setPopupMode(QToolButton.InstantPopup)
        self.move_menu = QMenu(self)
        move_to_folder_action = QAction("Move selected to folder...", self)
        self.move_menu.addAction(move_to_folder_action)
        self.move_btn.setMenu(self.move_menu)

        self.delete_drop_btn = QToolButton()
        self.delete_drop_btn.setText("Delete ▾")
        self.delete_drop_btn.setPopupMode(QToolButton.InstantPopup)
        self.delete_menu = QMenu(self)
        delete_selected_action = QAction("Delete selected (move to Trash)", self)
        self.delete_menu.addAction(delete_selected_action)
        self.delete_drop_btn.setMenu(self.delete_menu)

        # Selected count
        self.selected_count_lbl = QLabel("Selected: 0")

        bulk_layout.addWidget(self.delete_btn)
        bulk_layout.addWidget(self.keep_btn)
        bulk_layout.addWidget(self.save_uniques_btn)
        bulk_layout.addStretch()
        bulk_layout.addWidget(self.move_btn)
        bulk_layout.addWidget(self.delete_drop_btn)
        bulk_layout.addWidget(self.selected_count_lbl)
        layout.addLayout(bulk_layout)

        # Connections
        self.search_btn.clicked.connect(self.on_search_clicked)
        self.delete_btn.clicked.connect(self._on_delete_all_duplicates)
        self.keep_btn.clicked.connect(self._on_keep_all_duplicates)
        self.save_uniques_btn.clicked.connect(self._on_save_uniques)
        move_to_folder_action.triggered.connect(self._on_move_selected)
        delete_selected_action.triggered.connect(self._on_delete_selected)

        self._thread = None
        self._last_results = None
        self._selected_paths = set()

    def _open_hash_info(self):
        dlg = HashInfoDialog(self)
        dlg.exec_()

    def browse_dir(self, target_line_edit):
        dlg = QFileDialog(self)
        dlg.setFileMode(QFileDialog.Directory)
        if dlg.exec_():
            target_line_edit.setText(dlg.selectedFiles()[0])

    def _on_field_toggled(self, checked):
        # If any field is checked, disable hash controls; if none checked, enable them
        any_checked = any(act.isChecked() for act in self.field_actions.values())
        self.hash_cb.setEnabled(not any_checked)
        self.hash_type.setEnabled(not any_checked)
        self.hash_size_combo.setEnabled(not any_checked)
        self.similarity_combo.setEnabled(not any_checked)
        self.hash_info_btn.setEnabled(not any_checked)
        # If enabling hash controls, do not auto-check the hash checkbox; user must check it explicitly

    def _on_hash_toggled(self, state):
        checked = state == Qt.Checked
        # When hash is checked, disable field selector so fields cannot be selected concurrently
        self.field_selector_btn.setEnabled(not checked)
        # Also temporarily disable actions inside the menu to prevent toggling while hash enabled
        for act in self.field_actions.values():
            act.setEnabled(not checked)

    def _get_selected_fields(self):
        return [k for k, act in self.field_actions.items() if act.isChecked()]

    def on_search_clicked(self):
        ref = self.ref_dir.text().strip()
        work = self.work_dir.text().strip()
        if not ref or not work:
            self._clear_results()
            self.results_layout.addWidget(QLabel("Please select both reference and working directories."))
            return

        # gather criteria fields
        fields = self._get_selected_fields()
        hash_size_val = int(self.hash_size_combo.currentText()) if self.hash_cb.isChecked() else None
        similarity_val = int(self.similarity_combo.currentText()) if self.hash_cb.isChecked() else None

        criteria = {
            "fields": fields,
            "size": False,
            "name": False,
            "metadata": True,
            "hash": self.hash_cb.isChecked(),
            "hash_type": self.hash_type.currentText() if self.hash_cb.isChecked() else None,
            "hash_size": hash_size_val,
            "similarity": similarity_val,
            "find_uniques": bool(self.find_uniques_cb.isChecked())
        }

        # disable UI while searching
        self.search_btn.setEnabled(False)
        self._clear_results()
        self.progress.setValue(0)

        self._thread = SearchThread(ref, work, criteria)
        self._thread.progress.connect(self._on_progress)
        self._thread.results_ready.connect(self._on_results_ready)
        self._thread.finished.connect(self._on_search_finished)
        self._thread.start()

    # --- remaining UI methods omitted for brevity (no functional changes) ---
    def _on_progress(self, value):
        self.progress.setValue(value)

    def _on_results_ready(self, payload):
        # (same logic as before; omitted here to keep the file focused on requested changes)
        # Ensure selected paths cleared on new results
        self._last_results = payload
        self._selected_paths.clear()
        self._update_selected_count()
        # ... existing rendering code continues unchanged ...
        duplicates = payload.get("duplicates", [])
        unique_in_ref = payload.get("unique_in_ref", [])
        unique_in_work = payload.get("unique_in_work", [])
        criteria = payload.get("criteria", {})

        if criteria.get("find_uniques"):
            header = QLabel("<b>Uniques</b>")
            self.results_layout.addWidget(header)
            if unique_in_ref:
                self.results_layout.addWidget(QLabel("<i>Only in Reference</i>"))
                for f in unique_in_ref:
                    self._add_unique_widget(f, side="ref")
            if unique_in_work:
                self.results_layout.addWidget(QLabel("<i>Only in Working</i>"))
                for f in unique_in_work:
                    self._add_unique_widget(f, side="work")
            return

        if duplicates:
            header = QLabel("<b>Duplicates / Matches</b>")
            self.results_layout.addWidget(header)
            for (r, w, reasons) in duplicates:
                self._add_duplicate_widget(r, w, reasons)

        if unique_in_ref or unique_in_work:
            header = QLabel("<b>Uniques</b>")
            self.results_layout.addWidget(header)
            if unique_in_ref:
                self.results_layout.addWidget(QLabel("<i>Only in Reference</i>"))
                for f in unique_in_ref:
                    self._add_unique_widget(f, side="ref")
            if unique_in_work:
                self.results_layout.addWidget(QLabel("<i>Only in Working</i>"))
                for f in unique_in_work:
                    self._add_unique_widget(f, side="work")

    # _add_duplicate_widget, _add_unique_widget, _on_path_toggled, _update_selected_count,
    # _open_compare_modal, _on_modal_action, _remove_widgets_for_paths, _on_delete_all_duplicates,
    # _on_keep_all_duplicates, _on_save_uniques, _on_move_selected, _on_delete_selected,
    # _clear_results, _on_search_finished
    # have the same implementations as before (unchanged). If you want I can paste them fully here.
