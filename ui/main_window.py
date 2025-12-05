# ui/main_window.py
# Fixes:
# - Restored progress bar (self.progress) on the options/search row so on_search_clicked can call self.progress.setValue(0).
# - Added a persistent left-toggle button (self.left_toggle_btn) outside the panel so the panel can be reopened after hiding.
# - Styled buttons use objectName for targeted styling in ui/styles.py.
# - Kept Search on the same row as other hash controls.
#
# Overwrite ui/main_window.py with this file and restart the app.

import os
import shutil
from pathlib import Path
from typing import List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QFileDialog, QCheckBox, QProgressBar, QScrollArea,
    QSizePolicy, QFrame, QMessageBox, QToolButton, QMenu, QAction, QSlider,
    QTabWidget, QApplication, QStyle, QTreeView, QFileSystemModel
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QSettings, QDir, QModelIndex
from PyQt5.QtGui import QPixmap, QIcon
from core.image_scanner import scan_images_in_directory, ImageFileObj
from core.comparator import find_duplicates, find_uniques
from .styles import GLASSY_STYLE, DARK_STYLE
from .comparison_modal import ComparisonModal
from .hash_info_dialog import HashInfoDialog
from send2trash import send2trash
import logging

logger = logging.getLogger(__name__)

# DropLineEdit (directory drag-drop)
class DropLineEdit(QLineEdit):
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


# Dir-only model for left tree (keeps count of files in folder display)
class DirOnlyModel(QFileSystemModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFilter(QDir.NoDotAndDotDot | QDir.Dirs)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
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
    results_ready = pyqtSignal(object)
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
    SETTINGS_ORG = "unique-image-finder"
    SETTINGS_APP = "uifinder"

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(1100)
        self._settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        theme = self._settings.value("theme", "light")
        self._apply_theme(theme)
        self._build_ui()
        self._restore_settings()

    def _apply_theme(self, theme_name: str):
        if theme_name == "dark":
            self.setStyleSheet(DARK_STYLE)
        else:
            self.setStyleSheet(GLASSY_STYLE)

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Left toggle button (always accessible) - appears when panel hidden
        self.left_toggle_btn = QToolButton()
        self.left_toggle_btn.setObjectName("left_toggle_btn")
        self.left_toggle_btn.setText("▶")
        self.left_toggle_btn.setToolTip("Show browser panel")
        self.left_toggle_btn.setVisible(False)
        self.left_toggle_btn.clicked.connect(self._show_left_panel)
        main_layout.addWidget(self.left_toggle_btn)

        # Left panel (dir-only tree)
        self.left_panel = QFrame()
        self.left_panel.setObjectName("left_panel")
        self.left_panel.setMinimumWidth(220)
        self.left_panel.setMaximumWidth(360)
        lp_layout = QVBoxLayout(self.left_panel)
        lp_layout.setContentsMargins(8,8,8,8)
        lp_layout.setSpacing(6)

        # Collapse button now inside panel (for local collapse)
        self.collapse_btn = QToolButton()
        self.collapse_btn.setObjectName("collapse_btn")
        self.collapse_btn.setText("◀")
        self.collapse_btn.setToolTip("Hide browser panel")
        self.collapse_btn.clicked.connect(self._hide_left_panel)
        lp_layout.addWidget(self.collapse_btn, alignment=Qt.AlignLeft)

        # Browser root input + set
        self.browser_root_input = QLineEdit()
        last_root = self._settings.value("browser_root", str(Path.home()))
        self.browser_root_input.setText(last_root)
        set_root_btn = make_button("Set Root", style_class="neutral")
        set_root_btn.clicked.connect(self._set_browser_root)
        row = QHBoxLayout()
        row.addWidget(self.browser_root_input)
        row.addWidget(set_root_btn)
        lp_layout.addLayout(row)

        # Dir-only model and tree view
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

        # Buttons to set selection
        btn_row = QHBoxLayout()
        set_ref_btn = make_button("As Reference", style_class="neutral")
        set_ref_btn.clicked.connect(self._set_selected_as_ref)
        set_work_btn = make_button("As Working", style_class="neutral")
        set_work_btn.clicked.connect(self._set_selected_as_work)
        btn_row.addWidget(set_ref_btn)
        btn_row.addWidget(set_work_btn)
        lp_layout.addLayout(btn_row)

        # Main content
        self.main_content = QWidget()
        content_layout = QVBoxLayout(self.main_content)
        content_layout.setContentsMargins(6,6,6,6)
        content_layout.setSpacing(8)

        # Top row: reference/work inputs + theme toggle (kept compact)
        top_row = QHBoxLayout()
        self.ref_dir = DropLineEdit()
        self.ref_dir.setText(self._settings.value("last_ref", ""))
        ref_browse = make_button("Browse", style_class="neutral")
        ref_browse.clicked.connect(lambda: self._browse_and_set(self.ref_dir))
        self.work_dir = DropLineEdit()
        self.work_dir.setText(self._settings.value("last_work", ""))
        work_browse = make_button("Browse", style_class="neutral")
        work_browse.clicked.connect(lambda: self._browse_and_set(self.work_dir))
        top_row.addWidget(QLabel("Reference:"))
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
        self.theme_btn.setChecked(self._settings.value("theme","light")=="dark")
        self._apply_theme_button_text()
        self.theme_btn.clicked.connect(self._on_theme_toggle)
        top_row.addWidget(self.theme_btn)
        content_layout.addLayout(top_row)

        # Options row: compare dropdown, hash checkbox, info button, similarity, search and progress
        options_row = QHBoxLayout()
        self.field_selector_btn = QToolButton()
        self.field_selector_btn.setObjectName("field_selector_btn")
        self.field_selector_btn.setText("Compare fields ▾")
        self.field_selector_btn.setPopupMode(QToolButton.InstantPopup)
        self.field_menu = QMenu(self)
        self.field_actions = {}
        fields = [("Name","name"), ("Size","size"), ("Created","created"), ("mtime","mtime"), ("Dimensions","dimensions")]
        for label,key in fields:
            act = QAction(label, self)
            act.setCheckable(True)
            act.toggled.connect(self._on_field_toggled)
            self.field_menu.addAction(act)
            self.field_actions[key]=act
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
        self.sim_slider.setValue(int(self._settings.value("similarity",90)))
        self.sim_slider.setFixedWidth(180)
        self.sim_lbl = QLabel(f"{self.sim_slider.value()}%")
        self.sim_slider.valueChanged.connect(lambda v: self.sim_lbl.setText(f"{v}%"))

        self.search_btn = make_button("Search", object_name="search_btn", style_class="search")
        self.search_btn.clicked.connect(self.on_search_clicked)
        self.search_btn.setMinimumWidth(84)

        # Progress (restored)
        self.progress = QProgressBar()
        self.progress.setRange(0,100)
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

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.duplicates_container = QWidget()
        self.duplicates_layout = QVBoxLayout(self.duplicates_container)
        self.duplicates_layout.setAlignment(Qt.AlignTop)
        self.duplicates_scroll = QScrollArea()
        self.duplicates_scroll.setWidgetResizable(True)
        self.duplicates_scroll.setWidget(self.duplicates_container)
        self.tabs.addTab(self.duplicates_scroll, "Duplicates (0)")

        self.uniques_ref_container = QWidget()
        self.uniques_ref_layout = QVBoxLayout(self.uniques_ref_container)
        self.uniques_ref_layout.setAlignment(Qt.AlignTop)
        self.uniques_ref_scroll = QScrollArea()
        self.uniques_ref_scroll.setWidgetResizable(True)
        self.uniques_ref_scroll.setWidget(self.uniques_ref_container)
        self.tabs.addTab(self.uniques_ref_scroll, "Uniques (Ref) (0)")

        self.uniques_work_container = QWidget()
        self.uniques_work_layout = QVBoxLayout(self.uniques_work_container)
        self.uniques_work_layout.setAlignment(Qt.AlignTop)
        self.uniques_work_scroll = QScrollArea()
        self.uniques_work_scroll.setWidgetResizable(True)
        self.uniques_work_scroll.setWidget(self.uniques_work_container)
        self.tabs.addTab(self.uniques_work_scroll, "Uniques (Work) (0)")

        content_layout.addWidget(self.tabs, 1)

        # Footer
        footer_row = QHBoxLayout()
        self.delete_btn = make_button("Delete duplicates", style_class="danger")
        self.delete_btn.clicked.connect(self._on_delete_all_duplicates)
        self.keep_btn = make_button("Keep", style_class="success")
        self.keep_btn.clicked.connect(self._on_keep_all_duplicates)
        self.save_uniques_btn = make_button("Save Uniques", style_class="success")
        self.save_uniques_btn.clicked.connect(self._on_save_uniques)
        footer_row.addWidget(self.delete_btn)
        footer_row.addWidget(self.keep_btn)
        footer_row.addWidget(self.save_uniques_btn)
        footer_row.addStretch(1)
        self.footer_label = QLabel("© Mufaddal Kothari")
        self.footer_label.setObjectName("footer_label")
        footer_row.addWidget(self.footer_label)
        content_layout.addLayout(footer_row)

        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(self.main_content)

        self._thread = None
        self._last_results = None
        self._selected_paths = set()
        self._last_tree_index = None

    def _restore_settings(self):
        root = self._settings.value("browser_root", str(Path.home()))
        if os.path.isdir(root):
            self.browser_tree.setRootIndex(self.fs_model.index(root))
        self._apply_theme_button_text()

    # left panel helpers
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

    # theme & control helpers
    def _apply_theme_button_text(self):
        self.theme_btn.setText("🌙" if self._settings.value("theme","light")=="dark" else "☀️")

    def _on_theme_toggle(self):
        new = "dark" if self._settings.value("theme","light")!="dark" else "light"
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

    # search flow
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
        fields = [k for k,v in self.field_actions.items() if v.isChecked()]
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
        # ensure progress exists and reset
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

    def _on_progress(self, v:int):
        # update progress bar safely
        try:
            self.progress.setValue(v)
        except Exception:
            pass
    def _on_delete_all_duplicates(self):
        """
        Delete all duplicate working files shown in the current results (move them to Trash).
        This method is safe if no results exist and reports any errors to the user.
        """
        # No-results guard
        if not getattr(self, "_last_results", None):
            QMessageBox.information(self, "No results", "No search results.")
            return

        duplicates = self._last_results.get("duplicates", [])
        if not duplicates:
            QMessageBox.information(self, "No duplicates", "No duplicates found.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm delete all duplicates",
            "Delete all duplicate working files? (Will move to Trash)",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # Collect working-file paths to delete
        to_delete = [w.path for (r, w, _) in duplicates if getattr(w, "path", None)]

        errors = []
        for p in to_delete:
            try:
                if os.path.exists(p):
                    send2trash(p)
            except Exception as e:
                errors.append((p, str(e)))

        # Remove widgets for deleted paths from all tabs
        try:
            self._remove_widgets_for_paths(to_delete)
        except Exception:
            logger.exception("Failed to remove widgets for deleted paths")

        if errors:
            QMessageBox.warning(self, "Delete errors", f"Some files could not be moved to Trash:\n{errors}")
        else:
            QMessageBox.information(self, "Done", "All duplicate working files moved to Trash.")
    def _on_tab_changed(self, index: int):
        """
        Called when the user switches tabs.

        Kept intentionally lightweight (no-op) to avoid side-effects; this fixes the
        AttributeError caused by connecting to a missing handler. If you want visual
        changes when tabs switch (e.g. refresh contents, lazy-load thumbnails), we
        can implement them here later.
        """
        try:
            # If you want to show a short summary in the footer or refresh the visible tab,
            # do it here. For now we keep it a no-op to prevent crashes.
            return
        except Exception:
            logger.exception("Error inside _on_tab_changed")
            return
    def _on_results_ready(self, payload: dict):
        self._last_results = payload
        self._selected_paths.clear()
        duplicates = payload.get("duplicates", [])
        uref = payload.get("unique_in_ref", [])
        uwork = payload.get("unique_in_work", [])
        # update tab texts with counts
        self.tabs.setTabText(0, f"Duplicates ({len(duplicates)})")
        self.tabs.setTabText(1, f"Uniques (Ref) ({len(uref)})")
        self.tabs.setTabText(2, f"Uniques (Work) ({len(uwork)})")
        # populate content
        self._clear_tabs()
        if duplicates:
            for r,w, reasons in duplicates:
                self._add_duplicate(r,w,reasons)
        else:
            self._add_label(self.duplicates_layout, "No duplicates found.")
        if uref:
            for f in uref:
                self._add_unique(f, side="ref")
        else:
            self._add_label(self.uniques_ref_layout, "<i>No unique files in Reference</i>")
        if uwork:
            for f in uwork:
                self._add_unique(f, side="work")
        else:
            self._add_label(self.uniques_work_layout, "<i>No unique files in Working</i>")
        self.search_btn.setEnabled(True)
        try:
            self.progress.setValue(100)
        except Exception:
            pass

    # rest of file unchanged (duplicate/unique widget helpers, file operations, etc.)
    def _on_search_finished(self):
        self.search_btn.setEnabled(True)
        try:
            self.progress.setValue(100)
        except Exception:
            pass
