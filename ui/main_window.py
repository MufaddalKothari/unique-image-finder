# ui/main_window.py
# Updated UI:
# - Removed the two "Find Uniques (Reference/Working)" checkboxes.
# - Added a QTabWidget in the centre results area with three tabs:
#     * Duplicates
#     * Uniques (Reference)
#     * Uniques (Working)
# - After a search, duplicates and uniques are computed once and stored in self._last_results.
#   Switching tabs simply shows the already-computed results (no recompute).
#
# Note: this file overwrites the previous ui/main_window.py. It reuses the same helper
# functions for creating duplicate/unique widgets but directs output into per-tab containers.

import os
import shutil
from pathlib import Path
from typing import List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QGroupBox, QFileDialog, QCheckBox, QProgressBar, QScrollArea,
    QSizePolicy, QFrame, QMessageBox, QToolButton, QMenu, QAction, QSlider,
    QTabWidget
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
import logging

logger = logging.getLogger(__name__)

# UI style constants
BUTTON_GLASS_STYLE = """
QPushButton, QToolButton {
    background: rgba(250,250,252,0.88);
    color: #0f1720;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 10px;
    padding: 10px 16px;
    font-size: 14px;
    font-weight: 600;
}
QPushButton:hover, QToolButton:hover {
    background: rgba(255,255,255,0.96);
}
QSlider#similarity_slider { min-height: 28px; }
"""

class SearchThread(QThread):
    results_ready = pyqtSignal(object)   # will emit a dict with results
    progress = pyqtSignal(int)

    def __init__(self, ref_dir: str, work_dir: str, criteria: dict):
        super().__init__()
        self.ref_dir = ref_dir
        self.work_dir = work_dir
        self.criteria = criteria

    def run(self):
        logger.debug("SearchThread: scanning ref: %s work: %s criteria: %s", self.ref_dir, self.work_dir, self.criteria)
        self.progress.emit(5)
        ref_files = scan_images_in_directory(self.ref_dir) if self.ref_dir else []
        self.progress.emit(40)
        work_files = scan_images_in_directory(self.work_dir) if self.work_dir else []
        self.progress.emit(70)

        duplicates = []
        uniques = ([], [])
        try:
            logger.debug("SearchThread: calling find_duplicates()")
            duplicates = find_duplicates(ref_files, work_files, self.criteria)
        except Exception as e:
            logger.exception("find_duplicates failed: %s", e)

        try:
            uniques = find_uniques(ref_files, work_files, self.criteria)
            if uniques is None:
                uniques = ([], [])
        except Exception as e:
            logger.exception("find_uniques failed: %s", e)
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
        self.setWindowTitle("Unique Image Finder")
        self.setMinimumWidth(1100)
        try:
            self.setStyleSheet(GLASSY_STYLE + BUTTON_GLASS_STYLE)
        except Exception:
            self.setStyleSheet(BUTTON_GLASS_STYLE)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel("🖼️ Unique Image Finder")
        header.setStyleSheet("font-size:28px; font-weight:700; padding:14px 0px 8px 5px;")
        layout.addWidget(header)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,0.05);")
        layout.addWidget(sep)

        # Directory selectors
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
        dir_layout.addSpacing(12)
        dir_layout.addWidget(QLabel("Working Folder (Less Images):"))
        dir_layout.addWidget(self.work_dir)
        dir_layout.addWidget(work_btn)
        layout.addLayout(dir_layout)

        # Options
        opts_top = QFrame()
        opts_top.setFrameShape(QFrame.HLine)
        opts_top.setStyleSheet("color: rgba(255,255,255,0.02);")
        layout.addWidget(opts_top)

        opts_group = QGroupBox("Search Options")
        opts_layout = QHBoxLayout()

        # Compare fields selector
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
            act.toggled.connect(self._on_field_toggled)
            self.field_menu.addAction(act)
            self.field_actions[key] = act
        self.field_selector_btn.setMenu(self.field_menu)
        self.field_selector_btn.setStyleSheet("QToolButton { padding: 10px 14px; font-weight:600; }")

        # Hash checkbox + similarity slider (hash_size removed; permanently 16)
        self.hash_cb = QCheckBox("By Hash (dhash, size=16)")
        self.hash_cb.stateChanged.connect(self._on_hash_toggled)

        # similarity slider and label
        self.sim_slider = QSlider(Qt.Horizontal)
        self.sim_slider.setMinimum(50)
        self.sim_slider.setMaximum(100)
        self.sim_slider.setValue(90)
        self.sim_slider.setTickInterval(5)
        self.sim_slider.setTickPosition(QSlider.TicksBelow)
        self.sim_slider.setFixedWidth(220)
        self.sim_slider.setObjectName("similarity_slider")
        self.sim_lbl = QLabel("Similarity: 90%")
        self.sim_slider.valueChanged.connect(lambda v: self.sim_lbl.setText(f"Similarity: {v}%"))

        self.hash_info_btn = QToolButton()
        self.hash_info_btn.setText("ℹ")
        self.hash_info_btn.setAutoRaise(True)
        self.hash_info_btn.clicked.connect(self._open_hash_info)

        opts_layout.addWidget(self.field_selector_btn)
        # Removed unique checkboxes here - tabs will show duplicates/uniques
        opts_layout.addStretch(1)
        opts_layout.addWidget(self.hash_cb)
        opts_layout.addWidget(self.sim_lbl)
        opts_layout.addWidget(self.sim_slider)
        opts_layout.addWidget(self.hash_info_btn)

        opts_group.setLayout(opts_layout)
        layout.addWidget(opts_group)

        opts_bot = QFrame()
        opts_bot.setFrameShape(QFrame.HLine)
        opts_bot.setStyleSheet("color: rgba(255,255,255,0.02);")
        layout.addWidget(opts_bot)

        # Search
        act_layout = QHBoxLayout()
        self.search_btn = QPushButton("🔍 Search")
        self.search_btn.setStyleSheet("font-size:15px; padding:10px 18px;")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        act_layout.addWidget(self.search_btn)
        act_layout.addWidget(self.progress)
        layout.addLayout(act_layout)

        # Results area -> Tabs: Duplicates | Uniques (Reference) | Uniques (Working)
        self.tabs = QTabWidget()
        # Duplicates tab
        self.duplicates_container = QWidget()
        self.duplicates_layout = QVBoxLayout(self.duplicates_container)
        self.duplicates_layout.setAlignment(Qt.AlignTop)
        self.duplicates_scroll = QScrollArea()
        self.duplicates_scroll.setWidgetResizable(True)
        self.duplicates_scroll.setWidget(self.duplicates_container)
        self.tabs.addTab(self.duplicates_scroll, "Duplicates")

        # Uniques (Reference) tab
        self.uniques_ref_container = QWidget()
        self.uniques_ref_layout = QVBoxLayout(self.uniques_ref_container)
        self.uniques_ref_layout.setAlignment(Qt.AlignTop)
        self.uniques_ref_scroll = QScrollArea()
        self.uniques_ref_scroll.setWidgetResizable(True)
        self.uniques_ref_scroll.setWidget(self.uniques_ref_container)
        self.tabs.addTab(self.uniques_ref_scroll, "Uniques (Reference)")

        # Uniques (Working) tab
        self.uniques_work_container = QWidget()
        self.uniques_work_layout = QVBoxLayout(self.uniques_work_container)
        self.uniques_work_layout.setAlignment(Qt.AlignTop)
        self.uniques_work_scroll = QScrollArea()
        self.uniques_work_scroll.setWidgetResizable(True)
        self.uniques_work_scroll.setWidget(self.uniques_work_container)
        self.tabs.addTab(self.uniques_work_scroll, "Uniques (Working)")

        layout.addWidget(self.tabs)

        # Footer
        footer_sep = QFrame()
        footer_sep.setFrameShape(QFrame.HLine)
        footer_sep.setStyleSheet("color: rgba(255,255,255,0.03);")
        layout.addWidget(footer_sep)

        bulk_layout = QHBoxLayout()
        self.delete_btn = QPushButton("🗑️ Delete All Duplicates")
        self.delete_btn.setProperty("class", "glass")
        self.keep_btn = QPushButton("✅ Keep All Duplicates")
        self.keep_btn.setProperty("class", "glass")
        self.save_uniques_btn = QPushButton("💾 Save Uniques to New Directory")

        self.move_btn = QToolButton()
        self.move_btn.setText("Move ▾")
        self.move_btn.setPopupMode(QToolButton.InstantPopup)
        self.move_menu = QMenu(self)
        move_action = QAction("Move selected to folder...", self)
        self.move_menu.addAction(move_action)
        self.move_btn.setMenu(self.move_menu)
        self.move_btn.setStyleSheet("QToolButton { padding:10px 16px; border-radius:10px; background: rgba(47,128,237,0.95); color:#fff; }")

        self.delete_drop_btn = QToolButton()
        self.delete_drop_btn.setText("Delete ▾")
        self.delete_drop_btn.setPopupMode(QToolButton.InstantPopup)
        self.delete_menu = QMenu(self)
        del_action = QAction("Delete selected (move to Trash)", self)
        self.delete_menu.addAction(del_action)
        self.delete_drop_btn.setMenu(self.delete_menu)
        self.delete_drop_btn.setStyleSheet("QToolButton { padding:10px 16px; border-radius:10px; background: rgba(235,87,87,0.95); color:#fff; }")

        try:
            for b in (self.move_btn, self.delete_drop_btn, self.search_btn, self.delete_btn, self.keep_btn, self.save_uniques_btn):
                eff = QGraphicsDropShadowEffect(blurRadius=8, xOffset=0, yOffset=2)
                b.setGraphicsEffect(eff)
        except Exception:
            pass

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
        move_action.triggered.connect(self._on_move_selected)
        del_action.triggered.connect(self._on_delete_selected)

        # internal state
        self._thread = None
        self._last_results = None
        self._selected_paths = set()

    # --- UI helpers ---
    def _open_hash_info(self):
        dlg = HashInfoDialog(self)
        dlg.exec_()

    def browse_dir(self, target_line_edit: QLineEdit):
        dlg = QFileDialog(self)
        dlg.setFileMode(QFileDialog.Directory)
        if dlg.exec_():
            target_line_edit.setText(dlg.selectedFiles()[0])

    def _on_field_toggled(self, checked: bool):
        any_checked = any(act.isChecked() for act in self.field_actions.values())
        # disable hash controls when fields are selected
        self.hash_cb.setEnabled(not any_checked)
        self.sim_slider.setEnabled(not any_checked)
        self.hash_info_btn.setEnabled(not any_checked)
        if any_checked and self.hash_cb.isChecked():
            # if hash was checked earlier, uncheck it to keep mutual exclusivity
            self.hash_cb.setChecked(False)

    def _on_hash_toggled(self, state: int):
        checked = state == Qt.Checked
        # disable field selector when hashing enabled
        self.field_selector_btn.setEnabled(not checked)
        for act in self.field_actions.values():
            act.setEnabled(not checked)
        if checked:
            # clear any active field checks to avoid ambiguity
            for act in self.field_actions.values():
                if act.isChecked():
                    act.setChecked(False)

    def _get_selected_fields(self) -> List[str]:
        return [k for k, act in self.field_actions.items() if act.isChecked()]

    # --- Search flow ---
    def on_search_clicked(self):
        ref = self.ref_dir.text().strip()
        work = self.work_dir.text().strip()
        if not ref or not work:
            # Clear tabs and show message in Duplicates tab
            self._clear_all_tabs()
            self._add_label_to_layout(self.duplicates_layout, "Please select both reference and working directories.")
            return

        fields = self._get_selected_fields()
        criteria = {
            "fields": fields,
            "size": False,
            "name": False,
            "metadata": True,  # comparator ignores metadata fallback when hashing is requested
            "hash": self.hash_cb.isChecked(),
            "hash_size": None,  # comparator will use DEFAULT_HASH_SIZE (16) permanently
            "similarity": int(self.sim_slider.value()) if self.hash_cb.isChecked() else None,
        }

        logger.debug("MainWindow: starting search with criteria: %s", criteria)

        self.search_btn.setEnabled(False)
        self._clear_all_tabs()
        self.progress.setValue(0)

        self._thread = SearchThread(ref, work, criteria)
        self._thread.progress.connect(self._on_progress)
        self._thread.results_ready.connect(self._on_results_ready)
        self._thread.finished.connect(self._on_search_finished)
        self._thread.start()

    def _on_progress(self, value: int):
        self.progress.setValue(value)

    # --- Results rendering & actions (now tab-aware) ---
    def _on_results_ready(self, payload: dict):
        # payload contains duplicates, unique_in_ref, unique_in_work and criteria
        self._last_results = payload
        self._selected_paths.clear()
        self._update_selected_count()

        duplicates = payload.get("duplicates", [])
        unique_in_ref = payload.get("unique_in_ref", [])
        unique_in_work = payload.get("unique_in_work", [])

        # Populate tabs once (no recompute on tab switch)
        self._clear_all_tabs()
        if duplicates:
            self._add_label_to_layout(self.duplicates_layout, "<b>Duplicates / Matches</b>")
            for (r, w, reasons) in duplicates:
                self._add_duplicate_widget_to_layout(self.duplicates_layout, r, w, reasons)
        else:
            self._add_label_to_layout(self.duplicates_layout, "No duplicates found.")

        # Uniques (Reference)
        self._add_label_to_layout(self.uniques_ref_layout, "<b>Uniques (Reference)</b>")
        if unique_in_ref:
            for f in unique_in_ref:
                self._add_unique_widget_to_layout(self.uniques_ref_layout, f, side="ref")
        else:
            self._add_label_to_layout(self.uniques_ref_layout, "<i>No unique files found in Reference</i>")

        # Uniques (Working)
        self._add_label_to_layout(self.uniques_work_layout, "<b>Uniques (Working)</b>")
        if unique_in_work:
            for f in unique_in_work:
                self._add_unique_widget_to_layout(self.uniques_work_layout, f, side="work")
        else:
            self._add_label_to_layout(self.uniques_work_layout, "<i>No unique files found in Working</i>")

        # Select first tab by default (duplicates)
        self.tabs.setCurrentIndex(0)

    # Helpers to manage tab contents
    def _clear_all_tabs(self):
        for layout in (self.duplicates_layout, self.uniques_ref_layout, self.uniques_work_layout):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()

    def _add_label_to_layout(self, layout, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

    def _add_duplicate_widget_to_layout(self, layout, r: ImageFileObj, w: ImageFileObj, reasons: List[str]):
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row_layout = QHBoxLayout(row)
        cb_r = QCheckBox()
        cb_r.stateChanged.connect(lambda s, p=r.path: self._on_path_toggled(p, s))
        cb_w = QCheckBox()
        cb_w.stateChanged.connect(lambda s, p=w.path: self._on_path_toggled(p, s))
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
        compare_btn.clicked.connect(lambda _, a=r, b=w, rs=reasons: self._open_compare_modal(a, b, rs))
        row_layout.addWidget(cb_r)
        row_layout.addWidget(thumb_r)
        row_layout.addWidget(cb_w)
        row_layout.addWidget(thumb_w)
        row_layout.addWidget(info_lbl)
        row_layout.addWidget(compare_btn)
        layout.addWidget(row)

    def _add_unique_widget_to_layout(self, layout, f: ImageFileObj, side: str = "ref"):
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row_layout = QHBoxLayout(row)
        cb = QCheckBox()
        cb.stateChanged.connect(lambda s, p=f.path: self._on_path_toggled(p, s))
        thumb = QLabel()
        pix = QPixmap(f.path)
        if not pix.isNull():
            thumb.setPixmap(pix.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            thumb.setText("No preview")
        info_lbl = QLabel()
        info_lbl.setText(f"{'Reference' if side == 'ref' else 'Working'} unique\nName: {f.name}\nSize: {f.size}\nDims: {f.dimensions}\nPath: {f.path}")
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(lambda _, p=f.path: os.startfile(p) if os.path.exists(p) else None)
        row_layout.addWidget(cb)
        row_layout.addWidget(thumb)
        row_layout.addWidget(info_lbl)
        row_layout.addWidget(open_btn)
        layout.addWidget(row)

    def _on_path_toggled(self, path: str, state):
        if state == Qt.Checked:
            self._selected_paths.add(path)
        else:
            self._selected_paths.discard(path)
        self._update_selected_count()

    def _update_selected_count(self):
        self.selected_count_lbl.setText(f"Selected: {len(self._selected_paths)}")

    def _open_compare_modal(self, ref_file: ImageFileObj, work_file: ImageFileObj, reasons: List[str]):
        meta1 = {
            "name": ref_file.name,
            "size": ref_file.size,
            "path": ref_file.path,
            "dimensions": ref_file.dimensions,
            "mode": ref_file.mode,
            "mtime": ref_file.mtime,
            "created": getattr(ref_file, 'created', None),
            "datetime_original": getattr(ref_file, 'datetime_original', None),
            "artist": getattr(ref_file, 'artist', None),
            "copyright": getattr(ref_file, 'copyright', None),
            "make": getattr(ref_file, 'make', None),
            "model": getattr(ref_file, 'model', None),
            "image_description": getattr(ref_file, 'image_description', None),
            "origin": getattr(ref_file, 'origin', None)
        }
        meta2 = {
            "name": work_file.name,
            "size": work_file.size,
            "path": work_file.path,
            "dimensions": work_file.dimensions,
            "mode": work_file.mode,
            "mtime": work_file.mtime,
            "created": getattr(work_file, 'created', None),
            "datetime_original": getattr(work_file, 'datetime_original', None),
            "artist": getattr(work_file, 'artist', None),
            "copyright": getattr(work_file, 'copyright', None),
            "make": getattr(work_file, 'make', None),
            "model": getattr(work_file, 'model', None),
            "image_description": getattr(work_file, 'image_description', None),
            "origin": getattr(work_file, 'origin', None)
        }
        modal = ComparisonModal(ref_file.path, work_file.path, meta1, meta2, ", ".join(reasons), action_callback=self._on_modal_action, parent=self)
        modal.exec_()

    def _on_modal_action(self, action: str, paths: List[str]):
        if action.startswith("delete") and paths:
            errors = []
            for p in paths:
                try:
                    if os.path.exists(p):
                        send2trash(p)
                except Exception as e:
                    errors.append((p, str(e)))
            self._remove_widgets_for_paths(paths)
            if errors:
                QMessageBox.warning(self, "Delete errors", f"Some files could not be moved to trash:\n{errors}")
        elif action == "keep_both":
            pass

    def _remove_widgets_for_paths(self, paths: List[str]):
        path_set = set(paths)
        # remove from all tabs
        for layout in (self.duplicates_layout, self.uniques_ref_layout, self.uniques_work_layout):
            i = 0
            while i < layout.count():
                item = layout.itemAt(i)
                widget = item.widget()
                should_remove = False
                if widget:
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
                    w = layout.takeAt(i).widget()
                    if w is not None:
                        w.deleteLater()
                else:
                    i += 1

    def _on_delete_all_duplicates(self):
        if not self._last_results:
            QMessageBox.information(self, "No results", "No search results to act on.")
            return
        duplicates = self._last_results.get("duplicates", [])
        if not duplicates:
            QMessageBox.information(self, "No duplicates", "No duplicates found.")
            return

        reply = QMessageBox.question(self, "Confirm delete all duplicates", "Delete all duplicate working files? (Will move to Trash)", QMessageBox.Yes | QMessageBox.No)
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
                    send2trash(p)
            except Exception as e:
                errors.append((p, str(e)))

        self._remove_widgets_for_paths(to_delete)
        if errors:
            QMessageBox.warning(self, "Delete errors", f"Some files could not be moved to trash:\n{errors}")
        else:
            QMessageBox.information(self, "Done", "All duplicate working files moved to Trash.")

    def _on_keep_all_duplicates(self):
        if not self._last_results:
            QMessageBox.information(self, "No results", "No search results to act on.")
            return
        duplicates = self._last_results.get("duplicates", [])
        if not duplicates:
            QMessageBox.information(self, "No duplicates", "No duplicates found.")
            return

        to_remove_paths = []
        for (r, w, reasons) in duplicates:
            to_remove_paths.append(r.path)
            to_remove_paths.append(w.path)
        self._remove_widgets_for_paths(to_remove_paths)
        QMessageBox.information(self, "Done", "Duplicates removed from view (kept on disk).")

    def _on_save_uniques(self):
        if not self._last_results:
            QMessageBox.information(self, "No results", "No search results available. Run a search first.")
            return

        unique_in_ref = self._last_results.get("unique_in_ref", [])
        unique_in_work = self._last_results.get("unique_in_work", [])

        if not unique_in_ref and not unique_in_work:
            QMessageBox.information(self, "No uniques", "No unique files found to save.")
            return

        dlg = QFileDialog(self, caption="Select destination folder")
        dlg.setFileMode(QFileDialog.Directory)
        if not dlg.exec_():
            return
        dest_dir = dlg.selectedFiles()[0]
        dest_path = Path(dest_dir)

        errors = []
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

    def _on_move_selected(self):
        if not self._selected_paths:
            QMessageBox.information(self, "No selection", "No files selected to move.")
            return
        dlg = QFileDialog(self, caption="Select destination folder")
        dlg.setFileMode(QFileDialog.Directory)
        if not dlg.exec_():
            return
        dest_dir = dlg.selectedFiles()[0]
        errors = []
        for p in list(self._selected_paths):
            try:
                if os.path.exists(p):
                    dest = os.path.join(dest_dir, os.path.basename(p))
                    shutil.move(p, dest)
                    self._remove_widgets_for_paths([p])
                    self._selected_paths.discard(p)
            except Exception as e:
                errors.append((p, str(e)))
        self._update_selected_count()
        if errors:
            QMessageBox.warning(self, "Move errors", f"Some files could not be moved:\n{errors}")
        else:
            QMessageBox.information(self, "Done", "Selected files moved.")

    def _on_delete_selected(self):
        if not self._selected_paths:
            QMessageBox.information(self, "No selection", "No files selected to delete.")
            return
        reply = QMessageBox.question(self, "Confirm delete", f"Move {len(self._selected_paths)} selected files to Trash?", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        errors = []
        for p in list(self._selected_paths):
            try:
                if os.path.exists(p):
                    send2trash(p)
                    self._remove_widgets_for_paths([p])
                    self._selected_paths.discard(p)
            except Exception as e:
                errors.append((p, str(e)))
        self._update_selected_count()
        if errors:
            QMessageBox.warning(self, "Delete errors", f"Some files could not be moved to trash:\n{errors}")
        else:
            QMessageBox.information(self, "Done", "Selected files moved to Trash.")

    def _clear_results(self):
        # kept for compatibility, clear all tabs
        self._clear_all_tabs()

    def _on_search_finished(self):
        self.search_btn.setEnabled(True)
        self.progress.setValue(100)
