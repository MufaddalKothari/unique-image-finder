"""
ui/main_window.py

Complete main window implementing:
- directory selectors
- search options (size/name/metadata/hash with dropdowns)
- search thread that scans and compares
- results rendering (duplicates + uniques)
- comparison modal integration and deletion callbacks
- bulk actions: delete all duplicates, keep all duplicates, save uniques
"""

import os
import shutil
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QGroupBox, QFileDialog, QComboBox, QCheckBox, QProgressBar,
    QScrollArea, QSizePolicy, QFrame, QMessageBox, QToolButton
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QGraphicsDropShadowEffect
from core.image_scanner import scan_images_in_directory, ImageFileObj
from core.comparator import find_duplicates, find_uniques
from .styles import GLASSY_STYLE
from .comparison_modal import ComparisonModal
from .hash_info_dialog import HashInfoDialog

class SearchThread(QThread):
    results_ready = pyqtSignal(object)   # will emit a dict with results
    progress = pyqtSignal(int)

    def __init__(self, ref_dir, work_dir, criteria):
        super().__init__()
        self.ref_dir = ref_dir
        self.work_dir = work_dir
        self.criteria = criteria

    def run(self):
        # Scan both directories
        self.progress.emit(5)
        ref_files = scan_images_in_directory(self.ref_dir) if self.ref_dir else []
        self.progress.emit(40)
        work_files = scan_images_in_directory(self.work_dir) if self.work_dir else []
        self.progress.emit(70)

        # Find duplicates and uniques
        duplicates = find_duplicates(ref_files, work_files, self.criteria)
        uniques = find_uniques(ref_files, work_files, self.criteria)
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
        self.setStyleSheet(GLASSY_STYLE)
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("🖼️ Image Comparison Application")
        header.setStyleSheet("font-size:32px; font-weight:700; padding:18px 0px 15px 5px;")
        layout.addWidget(header)

        # Directory selectors
        dir_layout = QHBoxLayout()
        self.ref_dir = QLineEdit()
        self.work_dir = QLineEdit()
        ref_btn = QPushButton("Browse Reference")
        work_btn = QPushButton("Browse Working")
        ref_btn.clicked.connect(lambda: self.browse_dir(self.ref_dir))
        work_btn.clicked.connect(lambda: self.browse_dir(self.work_dir))
        dir_layout.addWidget(QLabel("Reference Folder:"))
        dir_layout.addWidget(self.ref_dir)
        dir_layout.addWidget(ref_btn)
        dir_layout.addSpacing(15)
        dir_layout.addWidget(QLabel("Working Folder:"))
        dir_layout.addWidget(self.work_dir)
        dir_layout.addWidget(work_btn)
        layout.addLayout(dir_layout)

        # Search options
        opts_group = QGroupBox("Search Options")
        opts_layout = QHBoxLayout()

        self.size_cb = QCheckBox("By Size")
        self.name_cb = QCheckBox("By Name")
        self.meta_cb = QCheckBox("By Metadata")
        self.unique_cb = QCheckBox("Find Uniques")
        self.hash_cb = QCheckBox("By Hash")

        # Hash controls: use dropdowns (preset integer values) instead of sliders
        self.hash_type = QComboBox()
        self.hash_type.addItems(["Average Hash", "Perceptual Hash", "Difference Hash", "Wavelet Hash"])
        self.hash_type.setEnabled(False)

        # Hash size presets (integers)
        self.hash_size_combo = QComboBox()
        hash_size_presets = ["4", "6", "8", "10", "12", "14", "16"]
        self.hash_size_combo.addItems(hash_size_presets)
        self.hash_size_combo.setCurrentText("8")
        self.hash_size_combo.setEnabled(False)

        # Similarity presets (percent integers)
        self.similarity_combo = QComboBox()
        similarity_presets = ["50", "60", "70", "75", "80", "85", "90", "95", "98", "100"]
        self.similarity_combo.addItems(similarity_presets)
        self.similarity_combo.setCurrentText("90")
        self.similarity_combo.setEnabled(False)

        # Info icon next to hash selector
        self.hash_info_btn = QToolButton()
        self.hash_info_btn.setText("ℹ")
        self.hash_info_btn.setAutoRaise(True)
        self.hash_info_btn.setEnabled(False)
        self.hash_info_btn.clicked.connect(self._open_hash_info)

        # Enable/disable hash controls when checkbox toggled
        self.hash_cb.toggled.connect(self.hash_type.setEnabled)
        self.hash_cb.toggled.connect(self.hash_size_combo.setEnabled)
        self.hash_cb.toggled.connect(self.similarity_combo.setEnabled)
        self.hash_cb.toggled.connect(self.hash_info_btn.setEnabled)

        opts_layout.addWidget(self.size_cb)
        opts_layout.addWidget(self.name_cb)
        opts_layout.addWidget(self.meta_cb)
        opts_layout.addWidget(self.hash_cb)
        opts_layout.addWidget(QLabel("Type:"))
        opts_layout.addWidget(self.hash_type)
        opts_layout.addWidget(self.hash_info_btn)
        opts_layout.addWidget(QLabel("Hash Size:"))
        opts_layout.addWidget(self.hash_size_combo)
        opts_layout.addWidget(QLabel("Similarity (%):"))
        opts_layout.addWidget(self.similarity_combo)
        opts_layout.addWidget(self.unique_cb)
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

        # Results area (scrollable)
        self.results_area = QScrollArea()
        self.results_area.setWidgetResizable(True)
        layout.addWidget(self.results_area)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignTop)
        self.results_area.setWidget(self.results_container)

        # Footer actions (bulk)
        bulk_layout = QHBoxLayout()
        self.delete_btn = QPushButton("🗑️ Delete All Duplicates")
        self.keep_btn = QPushButton("✅ Keep All Duplicates")
        self.save_uniques_btn = QPushButton("💾 Save Uniques to New Directory")
        bulk_layout.addWidget(self.delete_btn)
        bulk_layout.addWidget(self.keep_btn)
        bulk_layout.addWidget(self.save_uniques_btn)
        layout.addLayout(bulk_layout)

        # Connect signals
        self.search_btn.clicked.connect(self.on_search_clicked)
        self.delete_btn.clicked.connect(self._on_delete_all_duplicates)
        self.keep_btn.clicked.connect(self._on_keep_all_duplicates)
        self.save_uniques_btn.clicked.connect(self._on_save_uniques)

        # Add drop shadows to primary buttons for visual depth
        for btn in (self.search_btn, ref_btn, work_btn, self.delete_btn, self.keep_btn, self.save_uniques_btn):
            effect = QGraphicsDropShadowEffect(blurRadius=12, xOffset=0, yOffset=3)
            effect.setColor(Qt.gray)
            btn.setGraphicsEffect(effect)

        # thread & last results placeholder
        self._thread = None
        self._last_results = None

    def _open_hash_info(self):
        dlg = HashInfoDialog(self)
        dlg.exec_()

    def browse_dir(self, target_line_edit):
        dlg = QFileDialog(self)
        dlg.setFileMode(QFileDialog.Directory)
        if dlg.exec_():
            target_line_edit.setText(dlg.selectedFiles()[0])

    def on_search_clicked(self):
        ref = self.ref_dir.text().strip()
        work = self.work_dir.text().strip()
        if not ref or not work:
            self._clear_results()
            self.results_layout.addWidget(QLabel("Please select both reference and working directories."))
            return

        # Build criteria from UI (include selected integers for hash size and similarity)
        hash_size_val = int(self.hash_size_combo.currentText()) if self.hash_cb.isChecked() else None
        similarity_val = int(self.similarity_combo.currentText()) if self.hash_cb.isChecked() else None

        criteria = {
            "size": self.size_cb.isChecked(),
            "name": self.name_cb.isChecked(),
            "metadata": self.meta_cb.isChecked(),
            "hash": self.hash_cb.isChecked(),
            "hash_type": self.hash_type.currentText() if self.hash_cb.isChecked() else None,
            "hash_size": hash_size_val,
            "similarity": similarity_val,
            "find_uniques": self.unique_cb.isChecked()
        }

        # Disable search while working
        self.search_btn.setEnabled(False)
        self._clear_results()
        self.progress.setValue(0)

        # Start worker thread
        self._thread = SearchThread(ref, work, criteria)
        self._thread.progress.connect(self._on_progress)
        self._thread.results_ready.connect(self._on_results_ready)
        self._thread.finished.connect(self._on_search_finished)
        self._thread.start()

    def _on_progress(self, value):
        self.progress.setValue(value)

    def _on_results_ready(self, payload):
        # Store for later bulk actions
        self._last_results = payload
        duplicates = payload.get("duplicates", [])
        unique_in_ref = payload.get("unique_in_ref", [])
        unique_in_work = payload.get("unique_in_work", [])
        criteria = payload.get("criteria", {})

        # If the user explicitly asked to Find Uniques, do not show duplicates at all.
        if criteria.get("find_uniques"):
            # Show only uniques
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
            return  # do not render duplicates

        # Otherwise, show duplicates first (if any) then uniques
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

    def _add_duplicate_widget(self, r, w, reasons):
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row_layout = QHBoxLayout(row)

        # thumbnails
        thumb_r = QLabel()
        pixr = QPixmap(r.path)
        if not pixr.isNull():
            thumb_r.setPixmap(pixr.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            thumb_r.setText("No preview")

        thumb_w = QLabel()
        pixw = QPixmap(w.path)
        if not pixw.isNull():
            thumb_w.setPixmap(pixw.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            thumb_w.setText("No preview")

        info_lbl = QLabel(f"Ref: {r.path}\nWork: {w.path}\nMatch: {', '.join(reasons)}")
        compare_btn = QPushButton("Compare")
        # closure captures current r,w,reasons
        compare_btn.clicked.connect(lambda _, a=r, b=w, rs=reasons: self._open_compare_modal(a, b, rs))

        row_layout.addWidget(thumb_r)
        row_layout.addWidget(thumb_w)
        row_layout.addWidget(info_lbl)
        row_layout.addWidget(compare_btn)
        self.results_layout.addWidget(row)

    def _add_unique_widget(self, f: ImageFileObj, side: str = "ref"):
        """
        Add a thumbnail + metadata for a unique file. side indicates if it's unique
        in reference or in working folder.
        """
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row_layout = QHBoxLayout(row)

        thumb = QLabel()
        pix = QPixmap(f.path)
        if not pix.isNull():
            thumb.setPixmap(pix.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            thumb.setText("No preview")

        info_lbl = QLabel()
        info_lbl.setText(f"{'Reference' if side == 'ref' else 'Working'} unique\nName: {f.name}\nSize: {f.size}\nDims: {f.dimensions}\nPath: {f.path}")
        # Add a small action button to open in file manager or view larger
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(lambda _, p=f.path: os.startfile(p) if os.path.exists(p) else None)

        row_layout.addWidget(thumb)
        row_layout.addWidget(info_lbl)
        row_layout.addWidget(open_btn)
        self.results_layout.addWidget(row)

    def _open_compare_modal(self, ref_file, work_file, reasons):
        meta1 = {
            "name": ref_file.name,
            "size": ref_file.size,
            "path": ref_file.path,
            "dimensions": ref_file.dimensions,
            "mode": ref_file.mode,
            "mtime": ref_file.mtime
        }
        meta2 = {
            "name": work_file.name,
            "size": work_file.size,
            "path": work_file.path,
            "dimensions": work_file.dimensions,
            "mode": work_file.mode,
            "mtime": work_file.mtime
        }
        # Pass action callback so modal can ask main window to delete files
        modal = ComparisonModal(ref_file.path, work_file.path, meta1, meta2, ", ".join(reasons), action_callback=self._on_modal_action, parent=self)
        modal.exec_()

    def _on_modal_action(self, action: str, paths: list):
        """
        Called by the comparison modal when a delete/keep action is confirmed.
        action: 'delete_both', 'delete_ref', 'delete_work', 'keep_both'
        paths: list of file paths to delete (or empty list)
        """
        if action.startswith("delete") and paths:
            errors = []
            for p in paths:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception as e:
                    errors.append((p, str(e)))
            # Remove relevant widgets from UI
            self._remove_widgets_for_paths(paths)
            if errors:
                QMessageBox.warning(self, "Delete errors", f"Some files could not be deleted:\n{errors}")
        elif action == "keep_both":
            # Nothing to delete; maybe just close modal. We do nothing here.
            pass

    def _remove_widgets_for_paths(self, paths):
        """
        Remove any widgets in results_layout that reference any path in paths.
        """
        # Build a set for faster checks
        path_set = set(paths)
        i = 0
        while i < self.results_layout.count():
            item = self.results_layout.itemAt(i)
            widget = item.widget()
            should_remove = False
            if widget:
                # Check all QLabel text in widget for a path substring
                labels = widget.findChildren(QLabel)
                for lbl in labels:
                    txt = lbl.text() or ""
                    for p in path_set:
                        if p in txt:
                            should_remove = True
                            break
                    if should_remove:
                        break
            if should_remove:
                w = self.results_layout.takeAt(i).widget()
                if w is not None:
                    w.deleteLater()
                # do not increment i, because items shifted left
            else:
                i += 1

    def _on_delete_all_duplicates(self):
        """
        Delete working-side files for all duplicates found in last search.
        """
        if not self._last_results:
            QMessageBox.information(self, "No results", "No search results to act on.")
            return
        duplicates = self._last_results.get("duplicates", [])
        if not duplicates:
            QMessageBox.information(self, "No duplicates", "No duplicates found.")
            return

        reply = QMessageBox.question(self, "Confirm delete all duplicates", "Delete all duplicate files in the Working folder (this will remove the working files listed as duplicates)?", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        to_delete = []
        for (r, w, reasons) in duplicates:
            if getattr(w, "path", None):
                to_delete.append(w.path)

        errors = []
        for p in to_delete:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception as e:
                errors.append((p, str(e)))

        # Remove deleted widgets from UI
        self._remove_widgets_for_paths(to_delete)
        if errors:
            QMessageBox.warning(self, "Delete errors", f"Some files could not be deleted:\n{errors}")
        else:
            QMessageBox.information(self, "Done", "All duplicate working files deleted.")

    def _on_keep_all_duplicates(self):
        """
        Keep all duplicates: simply remove duplicates from the UI as "kept" without file ops.
        """
        if not self._last_results:
            QMessageBox.information(self, "No results", "No search results to act on.")
            return
        duplicates = self._last_results.get("duplicates", [])
        if not duplicates:
            QMessageBox.information(self, "No duplicates", "No duplicates found.")
            return

        # Remove duplicates widgets from UI (no deletion)
        to_remove_paths = []
        for (r, w, reasons) in duplicates:
            # pick both paths so any widget containing either will be removed
            to_remove_paths.append(r.path)
            to_remove_paths.append(w.path)
        self._remove_widgets_for_paths(to_remove_paths)
        QMessageBox.information(self, "Done", "Duplicates removed from view (kept on disk).")

    def _on_save_uniques(self):
        """
        Save uniques to a new directory chosen by the user.
        Copies unique files into two subfolders:
          <target>/reference_uniques/
          <target>/working_uniques/
        """
        if not self._last_results:
            QMessageBox.information(self, "No results", "No search results available. Run a search first.")
            return

        unique_in_ref = self._last_results.get("unique_in_ref", [])
        unique_in_work = self._last_results.get("unique_in_work", [])

        if not unique_in_ref and not unique_in_work:
            QMessageBox.information(self, "No uniques", "No unique files found to save.")
            return

        # Ask user to pick a destination folder
        dlg = QFileDialog(self, caption="Select destination folder")
        dlg.setFileMode(QFileDialog.Directory)
        if not dlg.exec_():
            return
        dest_dir = dlg.selectedFiles()[0]
        dest_path = Path(dest_dir)

        errors = []

        # Helper to copy list to subfolder
        def _copy_list(files, subfolder_name):
            if not files:
                return
            folder = dest_path / subfolder_name
            folder.mkdir(parents=True, exist_ok=True)
            for f in files:
                src = Path(f.path)
                if not src.exists():
                    errors.append((str(src), "Source not found"))
                    continue
                dest_file = folder / src.name
                # Handle name collision by appending a counter
                counter = 1
                base = dest_file.stem
                suffix = dest_file.suffix
                while dest_file.exists():
                    dest_file = folder / f"{base}_{counter}{suffix}"
                    counter += 1
                try:
                    shutil.copy2(str(src), str(dest_file))
                except Exception as e:
                    errors.append((str(src), str(e)))

        _copy_list(unique_in_ref, "reference_uniques")
        _copy_list(unique_in_work, "working_uniques")

        if errors:
            msg = "Some files could not be copied:\n" + "\n".join([f"{p}: {err}" for p, err in errors])
            QMessageBox.warning(self, "Copy errors", msg)
        else:
            QMessageBox.information(self, "Done", f"Unique files copied to:\n{dest_path}")

    def _clear_results(self):
        # Remove all widgets from results_layout
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_search_finished(self):
        self.search_btn.setEnabled(True)
        self.progress.setValue(100)