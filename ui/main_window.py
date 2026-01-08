# ui/main_window.py
# Complete MainWindow implementation (full file) - consolidated and self-contained.
# Added Move Selected and Delete Selected footer buttons and ensured their handlers are present.
#
# This file depends on ui/styles.py for GLASSY_STYLE / DARK_STYLE.

import os
import shutil
from pathlib import Path
from typing import List
import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QFileDialog, QCheckBox, QProgressBar, QScrollArea,
    QSizePolicy, QFrame, QMessageBox, QToolButton, QMenu, QSlider,
    QTabWidget, QApplication, QStyle, QTreeView, QFileSystemModel
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, Signal,QThread, QSettings, QDir, QModelIndex

from PySide6.QtGui import QPixmap, QIcon
# from PyQt5 import sip
from core.image_scanner import scan_images_in_directory, ImageFileObj
from core.comparator import find_duplicates, find_uniques, find_matches
from .styles import GLASSY_STYLE, DARK_STYLE
from .comparison_modal import ComparisonModal
from .hash_info_dialog import HashInfoDialog
from send2trash import send2trash
# from core.cache_db import CacheDB
# from core.indexer import Indexer
# from .cached_dirs_modal import CachedDirsModal
logger = logging.getLogger(__name__)


class DropLineEdit(QLineEdit):
    """QLineEdit that accepts a dropped folder path."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.setPlaceholderText("Drop a folder here or click Browse")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and Path(url.toLocalFile()).is_dir():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.is_dir():
                    self.setText(str(p))
                    self.editingFinished.emit()
                    break
        event.acceptProposedAction()


class DirOnlyModel(QFileSystemModel):
    """QFileSystemModel showing directories only and displaying file counts in the label."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFilter(QDir.NoDotAndDotDot | QDir.Dirs)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        # For display role and name column, show "Name (Nfiles)"
        if role == Qt.DisplayRole and index.column() == 0:
            name = super().data(index, role)
            try:
                path = self.filePath(index)
                count = 0
                try:
                    with os.scandir(path) as it:
                        for entry in it:
                            if entry.is_file():
                                count += 1
                except Exception:
                    count = 0
                return f"{name} ({count})"
            except Exception:
                return name
        return super().data(index, role)


def make_button(text: str = "", icon: QIcon = None, object_name: str = "", style_class: str = "neutral", tooltip: str = ""):
    b = QPushButton(text)
    if icon and not icon.isNull():
        b.setIcon(icon)
    b.setProperty("class", style_class)
    if object_name:
        b.setObjectName(object_name)
    if tooltip:
        b.setToolTip(tooltip)
    b.setMinimumHeight(30)
    b.setMaximumHeight(36)
    b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    return b


class SearchThread(QThread):
    """Background thread: scans folders and runs comparator."""
    results_ready = Signal(object)
    progress = Signal(int)

    def __init__(self, ref_dir: str, work_dir: str, criteria: dict):
        super().__init__()
        self.ref_dir = ref_dir
        self.work_dir = work_dir
        self.criteria = criteria

    def run(self):
        logger.debug("SearchThread: scanning ref=%s work=%s criteria=%s", self.ref_dir, self.work_dir, self.criteria)
        self.progress.emit(5)
        ref_files = scan_images_in_directory(self.ref_dir) if self.ref_dir else []
        self.progress.emit(40)
        work_files = scan_images_in_directory(self.work_dir) if self.work_dir else []
        self.progress.emit(70)

        duplicates = []
        uniques = ([], [])
        try:
            duplicates, unique_ref,unique_work = find_matches(ref_files, work_files, self.criteria)
        except Exception:
            logger.exception("find_duplicates failed")

        self.progress.emit(95)
        self.results_ready.emit({
            "duplicates": duplicates,
            "unique_in_ref": unique_ref,
            "unique_in_work": unique_work,
            "ref_files": ref_files,
            "work_files": work_files,
            "criteria": self.criteria
        })
        self.progress.emit(100)


class MainWindow(QWidget):
    SETTINGS_ORG = "unique-image-finder"
    SETTINGS_APP = "uifinder"

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(1100)
        self._settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        theme = self._settings.value("theme", "light")
        self._apply_theme(theme)
        # self._cache_db = CacheDB()
        # self._indexer = Indexer(self._cache_db)
        # self._indexer.start()
        # internal state
        self._thread = None
        self._last_results = None
        self._selected_paths = set()
        self._last_tree_index = None

        self._build_ui()
        self._restore_settings()

    # ---------- styling ----------
    def _apply_theme(self, theme_name: str):
        if theme_name == "dark":
            self.setStyleSheet(DARK_STYLE)
        else:
            self.setStyleSheet(GLASSY_STYLE)


    # ---------- layout helpers for tab select all ----------
    def _toggle_all_in_layout(self, state, layout):
        """
        Toggle the state of all checkboxes in the given layout based on the 'Select All' checkbox,
        and update the application state (_selected_paths) accordingly.

        Args:
            state (int): The state of the 'Select All' checkbox (0 = unchecked, 2 = checked).
            layout (QVBoxLayout): The layout containing the dynamically added rows with checkboxes.
        """
        select_all = state > 0  # True if the 'Select All' checkbox is checked, False otherwise

        # Iterate over all the widgets in the layout (rows of duplicates or uniques)
        for i in range(layout.count()):
            item = layout.itemAt(i)  # Get the layout item
            if item is not None:
                row_widget = item.widget()  # This is the QFrame or row container
                if row_widget is not None:
                    # Check for any QCheckBox inside the row widget
                    checkboxes = row_widget.findChildren(QCheckBox)
                    for checkbox in checkboxes:
                        # Avoid altering the "Select All" checkbox itself
                        if checkbox != layout.itemAt(0).widget():
                            path = checkbox.property("path")  # Assume `path` is stored in the checkbox
                            if select_all and path:
                                # Add the path to the selection state
                                self._selected_paths.add(path)
                            elif not select_all and path:
                                # Remove the path from the selection state
                                self._selected_paths.discard(path)

                            checkbox.blockSignals(True)  # Prevent triggering signals while toggling
                            checkbox.setChecked(select_all)  # Set the checkbox state
                            checkbox.blockSignals(False)

        # Update the UI footer or other relevant state display
        self._update_selected_count()



    # ---------- UI construction ----------
    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # left-toggle button (visible only when panel hidden)
        self.left_toggle_btn = QToolButton()
        self.left_toggle_btn.setObjectName("left_toggle_btn")
        self.left_toggle_btn.setText("▶")
        self.left_toggle_btn.setToolTip("Show browser panel")
        self.left_toggle_btn.setVisible(False)
        self.left_toggle_btn.clicked.connect(self._show_left_panel)
        main_layout.addWidget(self.left_toggle_btn)
        # left panel
        self.left_panel = QFrame()
        self.left_panel.setObjectName("left_panel")
        self.left_panel.setMinimumWidth(220)
        self.left_panel.setMaximumWidth(360)
        lp_layout = QVBoxLayout(self.left_panel)
        lp_layout.setContentsMargins(8, 8, 8, 8)
        lp_layout.setSpacing(6)

        self.cached_btn = QPushButton("Cached")
        self.cached_btn.setObjectName("cached_btn")
        self.cached_btn.setToolTip("Open cached directories manager")
        lp_layout.insertWidget(1, self.cached_btn)  # or appropriate position
        self.cached_btn.clicked.connect(self._open_cached_modal)
        
        # collapse button inside panel
        self.collapse_btn = QToolButton()
        self.collapse_btn.setObjectName("collapse_btn")
        self.collapse_btn.setText("◀")
        self.collapse_btn.setToolTip("Hide browser panel")
        self.collapse_btn.clicked.connect(self._hide_left_panel)
        lp_layout.addWidget(self.collapse_btn, alignment=Qt.AlignLeft)

        # browser root
        self.browser_root_input = QLineEdit()
        last_root = self._settings.value("browser_root", str(Path.home()))
        self.browser_root_input.setText(last_root)
        set_root_btn = make_button("Set Root", style_class="neutral")
        set_root_btn.clicked.connect(self._set_browser_root)
        row = QHBoxLayout()
        row.addWidget(self.browser_root_input)
        row.addWidget(set_root_btn)
        lp_layout.addLayout(row)

        # dir-only tree
        self.fs_model = DirOnlyModel()
        self.fs_model.setRootPath(QDir.rootPath())
        self.browser_tree = QTreeView()
        self.browser_tree.setModel(self.fs_model)
        if os.path.isdir(last_root):
            self.browser_tree.setRootIndex(self.fs_model.index(last_root))
        self.browser_tree.setHeaderHidden(True)
        for c in range(1, self.fs_model.columnCount()):
            self.browser_tree.setColumnHidden(c, True)
        self.browser_tree.clicked.connect(self._on_tree_clicked)
        lp_layout.addWidget(self.browser_tree, 1)

        # set reference / working buttons
        btn_row = QHBoxLayout()
        set_ref_btn = make_button("As Reference", style_class="neutral")
        set_ref_btn.clicked.connect(self._set_selected_as_ref)
        set_work_btn = make_button("As Working", style_class="neutral")
        set_work_btn.clicked.connect(self._set_selected_as_work)
        btn_row.addWidget(set_ref_btn)
        btn_row.addWidget(set_work_btn)
        lp_layout.addLayout(btn_row)

        # main content
        self.main_content = QWidget()
        content_layout = QVBoxLayout(self.main_content)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(8)

        # top row - Reference / Working inputs and theme toggle
        top_row = QHBoxLayout()
        self.ref_dir = DropLineEdit()
        self.ref_dir.setText(self._settings.value("last_ref", ""))
        ref_browse = make_button("Browse", style_class="neutral")
        ref_browse.clicked.connect(lambda: self._browse_and_set(self.ref_dir))
        self.work_dir = DropLineEdit()
        self.work_dir.setText(self._settings.value("last_work", ""))
        work_browse = make_button("Browse", style_class="neutral")
        work_browse.clicked.connect(lambda: self._browse_and_set(self.work_dir))
        top_row.addWidget(QLabel("Reference (Not for Delete):"))
        top_row.addWidget(self.ref_dir, 2)  
        top_row.addWidget(ref_browse)
        top_row.addSpacing(8)
        top_row.addWidget(QLabel("Working:"))
        top_row.addWidget(self.work_dir, 2)
        top_row.addWidget(work_browse)
        top_row.addStretch(1)
        self.theme_btn = QToolButton()
        self.theme_btn.setObjectName("theme_toggle_btn")
        self.theme_btn.setCheckable(True)
        self.theme_btn.setChecked(self._settings.value("theme", "light") == "dark")
        self._apply_theme_button_text()
        self.theme_btn.clicked.connect(self._on_theme_toggle)
        top_row.addWidget(self.theme_btn)
        content_layout.addLayout(top_row)

        # options row - compare dropdown, hash, info, similarity, search, progress
        options_row = QHBoxLayout()
        self.field_selector_btn = QToolButton()
        self.field_selector_btn.setObjectName("field_selector_btn")
        self.field_selector_btn.setText("Compare fields ▾")
        self.field_selector_btn.setPopupMode(QToolButton.InstantPopup)
        self.field_menu = QMenu(self)
        self.field_actions = {}
        fields = [("Name", "name"), ("Size", "size"), ("Created", "created"), ("mtime", "mtime"), ("Dimensions", "dimensions")]
        for label, key in fields:
            act = QAction(label, self)
            act.setCheckable(True)
            act.toggled.connect(self._on_field_toggled)
            self.field_menu.addAction(act)
            self.field_actions[key] = act
        self.field_selector_btn.setMenu(self.field_menu)

        self.hash_cb = QCheckBox("By Hash (dhash, size=16)")
        self.info_btn = QToolButton()
        self.info_btn.setObjectName("info_btn")
        self.info_btn.setText("ℹ")
        self.info_btn.setToolTip("Hash info")
        self.info_btn.clicked.connect(self._open_hash_info)

        self.sim_slider = QSlider(Qt.Horizontal)
        self.sim_slider.setMinimum(50)
        self.sim_slider.setMaximum(100)
        self.sim_slider.setValue(int(self._settings.value("similarity", 90)))
        self.sim_slider.setFixedWidth(180)
        self.sim_lbl = QLabel(f"{self.sim_slider.value()}%")
        self.sim_slider.valueChanged.connect(lambda v: self.sim_lbl.setText(f"{v}%"))

        self.search_btn = make_button("Search", object_name="search_btn", style_class="search")
        self.search_btn.clicked.connect(self.on_search_clicked)
        self.search_btn.setMinimumWidth(84)

        # progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(14)
        self.progress.setFixedWidth(160)

        options_row.addWidget(self.field_selector_btn)
        options_row.addWidget(self.hash_cb)
        options_row.addWidget(self.info_btn)
        options_row.addWidget(QLabel("Similarity:"))
        options_row.addWidget(self.sim_slider)
        options_row.addWidget(self.sim_lbl)
        options_row.addStretch(1)
        options_row.addWidget(self.search_btn)
        options_row.addWidget(self.progress)
        content_layout.addLayout(options_row)

        # tabs
        self.tabs = QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Duplicates tab
        self.duplicates_container = QWidget()
        self.duplicates_layout = QVBoxLayout(self.duplicates_container)

        # Add 'Select All' checkbox for duplicates
        self.select_all_duplicates_checkbox = QCheckBox("Select All Duplicates")
        self.select_all_duplicates_checkbox.stateChanged.connect(
            lambda state: self._toggle_all_in_layout(state, self.duplicates_layout)
        )
        self.duplicates_layout.addWidget(self.select_all_duplicates_checkbox)

        self.duplicates_layout.setAlignment(Qt.AlignTop)
        self.duplicates_scroll = QScrollArea()
        self.duplicates_scroll.setWidgetResizable(True)
        self.duplicates_scroll.setWidget(self.duplicates_container)
        self.tabs.addTab(self.duplicates_scroll, "Duplicates (0)")

        # Uniques (Ref) tab
        self.uniques_ref_container = QWidget()
        self.uniques_ref_layout = QVBoxLayout(self.uniques_ref_container)

        # Add 'Select All' checkbox for uniques (Ref)
        self.select_all_uniques_ref_checkbox = QCheckBox("Select All Unique Reference Files")
        self.select_all_uniques_ref_checkbox.stateChanged.connect(
            lambda state: self._toggle_all_in_layout(state, self.uniques_ref_layout)
        )
        self.uniques_ref_layout.addWidget(self.select_all_uniques_ref_checkbox)

        self.uniques_ref_layout.setAlignment(Qt.AlignTop)
        self.uniques_ref_scroll = QScrollArea()
        self.uniques_ref_scroll.setWidgetResizable(True)
        self.uniques_ref_scroll.setWidget(self.uniques_ref_container)
        self.tabs.addTab(self.uniques_ref_scroll, "Uniques (Ref) (0)")

        # Uniques (Work) tab
        self.uniques_work_container = QWidget()
        self.uniques_work_layout = QVBoxLayout(self.uniques_work_container)

        # Add 'Select All' checkbox for uniques (Work)
        self.select_all_uniques_work_checkbox = QCheckBox("Select All Unique Working Files")
        self.select_all_uniques_work_checkbox.stateChanged.connect(
            lambda state: self._toggle_all_in_layout(state, self.uniques_work_layout)
        )
        self.uniques_work_layout.addWidget(self.select_all_uniques_work_checkbox)

        self.uniques_work_layout.setAlignment(Qt.AlignTop)
        self.uniques_work_scroll = QScrollArea()
        self.uniques_work_scroll.setWidgetResizable(True)
        self.uniques_work_scroll.setWidget(self.uniques_work_container)
        self.tabs.addTab(self.uniques_work_scroll, "Uniques (Work) (0)")

        content_layout.addWidget(self.tabs, 1)

        # footer with action buttons
        footer_row = QHBoxLayout()
        self.delete_btn = make_button("Delete duplicates from Working", style_class="danger")
        self.delete_btn.clicked.connect(self._on_delete_all_duplicates)
        self.keep_btn = make_button("Keep", style_class="success")
        self.keep_btn.clicked.connect(self._on_keep_all_duplicates)
        self.save_uniques_btn = make_button("Save Uniques from Both Folders", style_class="success")
        self.save_uniques_btn.clicked.connect(self._on_save_uniques)

        # Add Move Selected and Delete Selected buttons
        self.move_selected_btn = make_button("Move Selected", style_class="neutral")
        self.move_selected_btn.clicked.connect(self._on_move_selected)
        self.delete_selected_btn = make_button("Delete Selected", style_class="danger")
        self.delete_selected_btn.clicked.connect(self._on_delete_selected)

        footer_row.addWidget(self.delete_btn)
        footer_row.addWidget(self.keep_btn)
        footer_row.addWidget(self.save_uniques_btn)
        footer_row.addWidget(self.move_selected_btn)
        footer_row.addWidget(self.delete_selected_btn)
        footer_row.addStretch(1)
        self.footer_label = QLabel("© Mufaddal Kothari")
        self.footer_label.setObjectName("footer_label")
        footer_row.addWidget(self.footer_label)
        content_layout.addLayout(footer_row)

        # assemble
        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(self.main_content)

    # ---------- settings restoration ----------
    def _restore_settings(self):
        root = self._settings.value("browser_root", str(Path.home()))
        if os.path.isdir(root):
            self.browser_tree.setRootIndex(self.fs_model.index(root))
        self._apply_theme_button_text()

    # ---------- left panel helpers ----------
    def _hide_left_panel(self):
        self.left_panel.hide()
        self.left_toggle_btn.setVisible(True)

    def _show_left_panel(self):
        self.left_panel.show()
        self.left_toggle_btn.setVisible(False)

    def _set_browser_root(self):
        root = self.browser_root_input.text().strip() or str(Path.home())
        if os.path.isdir(root):
            self._settings.setValue("browser_root", root)
            self.browser_tree.setRootIndex(self.fs_model.index(root))

    def _on_tree_clicked(self, index: QModelIndex):
        self._last_tree_index = index

    def _set_selected_as_ref(self):
        if not self._last_tree_index:
            QMessageBox.information(self, "Select", "Select a folder in the browser.")
            return
        path = self.fs_model.filePath(self._last_tree_index)
        if os.path.isdir(path):
            self.ref_dir.setText(path)
            self._settings.setValue("last_ref", path)

    def _set_selected_as_work(self):
        if not self._last_tree_index:
            QMessageBox.information(self, "Select", "Select a folder in the browser.")
            return
        path = self.fs_model.filePath(self._last_tree_index)
        if os.path.isdir(path):
            self.work_dir.setText(path)
            self._settings.setValue("last_work", path)

    # ---------- theme and small controls ----------
    def _apply_theme_button_text(self):
        self.theme_btn.setText("🌙" if self._settings.value("theme", "light") == "dark" else "☀️")

    def _on_theme_toggle(self):
        new = "dark" if self._settings.value("theme", "light") != "dark" else "light"
        self._settings.setValue("theme", new)
        self._apply_theme(new)
        self._apply_theme_button_text()

    def _browse_and_set(self, line_edit: QLineEdit):
        dlg = QFileDialog(self)
        dlg.setFileMode(QFileDialog.Directory)
        if dlg.exec_():
            path = dlg.selectedFiles()[0]
            line_edit.setText(path)
            if line_edit is self.ref_dir:
                self._settings.setValue("last_ref", path)
            else:
                self._settings.setValue("last_work", path)

    def _open_hash_info(self):
        dlg = HashInfoDialog(self)
        dlg.exec_()

    def _on_field_toggled(self, checked: bool):
        any_checked = any(act.isChecked() for act in self.field_actions.values())
        self.hash_cb.setEnabled(not any_checked)
        self.sim_slider.setEnabled(not any_checked)
        if any_checked and self.hash_cb.isChecked():
            self.hash_cb.setChecked(False)
            # Cached Model
    def _open_cached_modal(self):
        pass
        # dlg = CachedDirsModal(self._cache_db, self._indexer, parent=self)
        # dlg.exec_()
        # refresh UI if needed after dialog closes
    # ---------- search flow ----------
    def on_search_clicked(self):
        ref = self.ref_dir.text().strip()
        work = self.work_dir.text().strip()
        if not ref or not work:
            self._clear_tabs()
            self._add_label(self.duplicates_layout, "Please select both reference and working directories.")
            return
        self._settings.setValue("last_ref", ref)
        self._settings.setValue("last_work", work)
        self._settings.setValue("similarity", self.sim_slider.value())
        fields = [k for k, v in self.field_actions.items() if v.isChecked()]
        criteria = {
            "fields": fields,
            "size": False,
            "name": False,
            "metadata": True,
            "hash": self.hash_cb.isChecked(),
            "hash_size": None,
            "similarity": int(self.sim_slider.value()) if self.hash_cb.isChecked() else None,
        }
        logger.debug("MainWindow: starting search with criteria: %s", criteria)
        self.search_btn.setEnabled(False)
        try:
            self.progress.setValue(0)
        except Exception:
            pass
        self._clear_tabs()
        self._thread = SearchThread(ref, work, criteria)
        self._thread.progress.connect(self._on_progress)
        self._thread.results_ready.connect(self._on_results_ready)
        self._thread.finished.connect(self._on_search_finished)
        self._thread.start()

    def _on_progress(self, v: int):
        try:
            self.progress.setValue(v)
        except Exception:
            pass

    def _on_results_ready(self, payload: dict):
        self._last_results = payload
        self._selected_paths.clear()

        # Extract the results
        duplicates = payload.get("duplicates", [])
        uref = payload.get("unique_in_ref", [])
        uwork = payload.get("unique_in_work", [])

        # Update tab counts
        self.tabs.setTabText(0, f"Duplicates ({len(duplicates)})")
        self.tabs.setTabText(1, f"Uniques (Ref) ({len(uref)})")
        self.tabs.setTabText(2, f"Uniques (Work) ({len(uwork)})")

        # Clear tabs
        self._clear_tabs()

        # Re-add "Select All" checkboxes
        self.select_all_duplicates_checkbox = QCheckBox("Select All Duplicates")
        self.select_all_uniques_ref_checkbox = QCheckBox("Select All Unique Reference Files")
        self.select_all_uniques_work_checkbox = QCheckBox("Select All Unique Working Files")

        # Connect "Select All" functionality
        self.select_all_duplicates_checkbox.stateChanged.connect(
            lambda state: self._toggle_all_in_layout(state, self.duplicates_layout)
        )
        self.select_all_uniques_ref_checkbox.stateChanged.connect(
            lambda state: self._toggle_all_in_layout(state, self.uniques_ref_layout)
        )
        self.select_all_uniques_work_checkbox.stateChanged.connect(
            lambda state: self._toggle_all_in_layout(state, self.uniques_work_layout)
        )

        # Add "Select All" checkboxes back to the respective layouts
        self.duplicates_layout.addWidget(self.select_all_duplicates_checkbox)
        self.uniques_ref_layout.addWidget(self.select_all_uniques_ref_checkbox)
        self.uniques_work_layout.addWidget(self.select_all_uniques_work_checkbox)

        # Reset "Select All" checkboxes to unchecked
        self.select_all_duplicates_checkbox.setChecked(False)
        self.select_all_uniques_ref_checkbox.setChecked(False)
        self.select_all_uniques_work_checkbox.setChecked(False)

        # Populate Duplicates Tab
        if duplicates:
            for r, w, reasons in duplicates:
                self._add_duplicate(r, w, reasons)
        else:
            self._add_label(self.duplicates_layout, "No duplicates found.")

        # Populate Uniques (Reference) Tab
        if uref:
            for f in uref:
                self._add_unique(f, side="ref")
        else:
            self._add_label(self.uniques_ref_layout, "<i>No unique files in Reference</i>")

        # Populate Uniques (Work) Tab
        if uwork:
            for f in uwork:
                self._add_unique(f, side="work")
        else:
            self._add_label(self.uniques_work_layout, "<i>No unique files in Working</i>")

        # Re-enable the Search button
        self.search_btn.setEnabled(True)
        try:
            self.progress.setValue(100)
        except Exception:
            pass


    def _on_search_finished(self):
        self.search_btn.setEnabled(True)
        logger.info("Search Completd")
        try:
            self.progress.setValue(100)
        except Exception:
            pass

    def _on_tab_changed(self, index: int):
        # placeholder for future lazy-load / refresh behavior
        return

    # ---------- UI helpers for rendering ----------
    def _clear_tabs(self):
        for layout in (self.duplicates_layout, self.uniques_ref_layout, self.uniques_work_layout):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()

    def _add_label(self, layout, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

    def _add_duplicate(self, r: ImageFileObj, w: ImageFileObj, reasons: List[str]):
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row.setStyleSheet("background: rgba(255,255,255,0.02); border-radius:8px;")
        rl = QHBoxLayout(row)
        cb_r = QCheckBox()
        cb_r.setProperty("path", r.path) 
        cb_r.stateChanged.connect(lambda s, p=r.path: self._toggle_selection(p, s))
        cb_w = QCheckBox()
        cb_w.setProperty("path", w.path) 
        cb_w.stateChanged.connect(lambda s, p=w.path: self._toggle_selection(p, s))
        thumb_r = QLabel()
        pixr = QPixmap(r.path)
        if not pixr.isNull():
            thumb_r.setPixmap(pixr.scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        thumb_w = QLabel()
        pixw = QPixmap(w.path)
        if not pixw.isNull():
            thumb_w.setPixmap(pixw.scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        info = QLabel(f"Ref: {r.path}\nWork: {w.path}\nMatch: {', '.join(reasons)}")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        compare_btn = make_button("Compare", style_class="neutral")
        compare_btn.clicked.connect(lambda _, a=r, b=w, rs=reasons: self._open_compare_modal(a, b, rs))
        rl.addWidget(cb_r)
        rl.addWidget(thumb_r)
        rl.addWidget(cb_w)
        rl.addWidget(thumb_w)
        rl.addWidget(info, 1)
        rl.addWidget(compare_btn)
        self.duplicates_layout.addWidget(row)

    def _add_unique(self, f: ImageFileObj, side: str = "ref"):
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row.setStyleSheet("background: rgba(255,255,255,0.02); border-radius:8px;")
        rl = QHBoxLayout(row)
        cb = QCheckBox()
        cb.setProperty("path", f.path)
        cb.stateChanged.connect(lambda s, p=f.path: self._toggle_selection(p, s))
        thumb = QLabel()
        pix = QPixmap(f.path)
        if not pix.isNull():
            thumb.setPixmap(pix.scaled(112, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        info = QLabel(f"{'Reference' if side == 'ref' else 'Working'} unique\nName: {f.name}\nSize: {f.size}\nDims: {f.dimensions}\nPath: {f.path}")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_btn = make_button("Open", style_class="neutral")
        open_btn.clicked.connect(lambda _, p=f.path: os.startfile(p) if os.path.exists(p) else None)
        rl.addWidget(cb)
        rl.addWidget(thumb)
        rl.addWidget(info, 1)
        rl.addWidget(open_btn)
        if side == "ref":
            self.uniques_ref_layout.addWidget(row)
        else:
            self.uniques_work_layout.addWidget(row)

    def _toggle_selection(self, path: str, state):
        if state == Qt.Checked:
            self._selected_paths.add(path)
        else:
            self._selected_paths.discard(path)
        self._update_selected_count()

    def _update_selected_count(self):
        self.footer_label.setText(f"© Mufaddal Kothari    Selected: {len(self._selected_paths)}")

    def _open_compare_modal(self, a: ImageFileObj, b: ImageFileObj, reasons):
        meta1 = {"name": a.name, "size": a.size, "path": a.path, "dimensions": a.dimensions}
        meta2 = {"name": b.name, "size": b.size, "path": b.path, "dimensions": b.dimensions}
        modal = ComparisonModal(a.path, b.path, meta1, meta2, ", ".join(reasons), action_callback=self._on_modal_action, parent=self)
        modal.exec_()

    def _on_modal_action(self, action: str, paths: List[str]):
        if action.startswith("delete") and paths:
            for p in paths:
                try:
                    if os.path.exists(p):
                        send2trash(p)
                except Exception:
                    pass
            self._remove_widgets_for_paths(paths)

    # ---------- file operations / actions ----------
    def _remove_widgets_for_paths(self, paths: List[str]):
        path_set = set(paths)
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
                    if w:
                        w.deleteLater()
                else:
                    i += 1

    def _on_delete_all_duplicates(self):
        """Delete all duplicate working files (move to Trash)."""
        if not getattr(self, "_last_results", None):
            QMessageBox.information(self, "No results", "No search results.")
            return
        duplicates = self._last_results.get("duplicates", [])
        if not duplicates:
            QMessageBox.information(self, "No duplicates", "No duplicates found.")
            return
        reply = QMessageBox.question(self, "Confirm delete all duplicates", "Delete all duplicate working files? (Will move to Trash)", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        to_delete = [w.path for (r, w, _) in duplicates if getattr(w, "path", None)]
        errors = []
        for p in to_delete:
            try:
                if os.path.exists(p):
                    send2trash(p)
            except Exception as e:
                errors.append((p, str(e)))
        try:
            self._remove_widgets_for_paths(to_delete)
        except Exception:
            logger.exception("Failed to remove widgets for deleted paths")
        if errors:
            QMessageBox.warning(self, "Delete errors", f"Some files could not be moved to Trash:\n{errors}")
        else:
            QMessageBox.information(self, "Done", "All duplicate working files moved to Trash.")

    def _on_keep_all_duplicates(self):
        """Remove duplicates from view (keep files on disk)."""
        if not getattr(self, "_last_results", None):
            QMessageBox.information(self, "No results", "No search results.")
            return
        duplicates = self._last_results.get("duplicates", [])
        if not duplicates:
            QMessageBox.information(self, "No duplicates", "No duplicates found.")
            return
        to_remove = []
        for (r, w, _) in duplicates:
            to_remove.extend([r.path, w.path])
        self._remove_widgets_for_paths(to_remove)
        QMessageBox.information(self, "Done", "Duplicates removed from view (kept on disk).")

    def _on_save_uniques(self):
        """Copy uniques to a chosen destination folder."""
        if not getattr(self, "_last_results", None):
            QMessageBox.information(self, "No results", "No search results.")
            return
        unique_in_ref = self._last_results.get("unique_in_ref", [])
        unique_in_work = self._last_results.get("unique_in_work", [])
        if not unique_in_ref and not unique_in_work:
            QMessageBox.information(self, "No uniques", "No unique files found.")
            return
        dlg = QFileDialog(self, caption="Select destination folder")
        dlg.setFileMode(QFileDialog.Directory)
        if dlg.exec_():
            dest = dlg.selectedFiles()[0]
            dest_path = Path(dest)
            errors = []
            def _copy_list(list_files, sub):
                if not list_files:
                    return
                folder = dest_path / sub
                folder.mkdir(parents=True, exist_ok=True)
                for f in list_files:
                    src = Path(f.path)
                    if not src.exists():
                        errors.append((str(src), "Missing"))
                        continue
                    dest_file = folder / src.name
                    try:
                        shutil.copy2(str(src), str(dest_file))
                    except Exception as e:
                        errors.append((str(src), str(e)))
            _copy_list(unique_in_ref, "reference_uniques")
            _copy_list(unique_in_work, "working_uniques")
            if errors:
                QMessageBox.warning(self, "Copy errors", f"Some files failed to copy:\n{errors}")
            else:
                QMessageBox.information(self, "Done", f"Copied uniques to {dest_path}")

    def _on_move_selected(self):
        """Move selected files (from any tab) to a user-picked folder."""
        if not self._selected_paths:
            QMessageBox.information(self, "No selection", "No files selected to move.")
            return
        dlg = QFileDialog(self, caption="Select destination folder")
        dlg.setFileMode(QFileDialog.Directory)
        if dlg.exec_():
            dest = dlg.selectedFiles()[0]
            errors = []
            for p in list(self._selected_paths):
                try:
                    if os.path.exists(p):
                        dest_path = os.path.join(dest, os.path.basename(p))
                        shutil.move(p, dest_path)
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
        """Move selected files to Trash (delete selected)."""
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
