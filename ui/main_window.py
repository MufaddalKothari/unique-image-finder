# ui/main_window.py
# UI polish changes requested:
# 1) Off-white (less white) theme and a dark theme toggle (top-right).
# 2) Colorful, shorter Adobe-style buttons with icons where appropriate.
# 3) Tab headers more visible, expanded across center area.
# 4) Remove the big "Unique Image Finder" header.
# 5) Remember last reference & working folders using QSettings.
# 6) Drag & drop support for reference and working path inputs.
# 7) Curved progress bar styling comes from ui/styles.py.
# 8) Footer copyright label.
#
# This file replaces the previous ui/main_window.py. It uses GLASSY_STYLE / DARK_STYLE
# from ui.styles and standard icons via style().standardIcon or unicode fallbacks.

import os
import shutil
from pathlib import Path
from typing import List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QGroupBox, QFileDialog, QCheckBox, QProgressBar, QScrollArea,
    QSizePolicy, QFrame, QMessageBox, QToolButton, QMenu, QAction, QSlider,
    QTabWidget, QApplication, QStyle, QSpacerItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QSettings, QUrl
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtWidgets import QGraphicsDropShadowEffect
from core.image_scanner import scan_images_in_directory, ImageFileObj
from core.comparator import find_duplicates, find_uniques
from .styles import GLASSY_STYLE, DARK_STYLE
from .comparison_modal import ComparisonModal
from .hash_info_dialog import HashInfoDialog
from send2trash import send2trash
import logging

logger = logging.getLogger(__name__)

# Helper: a QLineEdit that accepts directory drag-and-drop (folder path)
class DropLineEdit(QLineEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.setPlaceholderText("Drop a folder here or click Browse")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            # accept if any url is a local directory
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


# Small helper to build icon from standard style or unicode fallback
def get_icon(name: str, app: QApplication):
    style = app.style()
    mapping = {
        "search": QStyle.SP_FileDialogContentsView,
        "open": QStyle.SP_DialogOpenButton,
        "folder": QStyle.SP_DirOpenIcon,
        "delete": QStyle.SP_TrashIcon,
        "save": QStyle.SP_DialogSaveButton,
        "move": QStyle.SP_ArrowForward,
    }
    sp = mapping.get(name)
    if sp is not None:
        try:
            return style.standardIcon(sp)
        except Exception:
            pass
    # fallback: use a unicode glyph as simple icon (keeps small)
    glyphs = {
        "search": "🔍",
        "open": "📂",
        "folder": "📁",
        "delete": "🗑️",
        "save": "💾",
        "move": "➡️",
    }
    txt = glyphs.get(name, "")
    icon = QIcon()
    # create a minimal pixmap from text is more involved; return empty icon so button shows text if needed
    return icon


# Base button factory for Adobe-like buttons
def make_button(text: str = "", icon: QIcon = None, object_name: str = "", style_class: str = "neutral", tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if icon and not icon.isNull():
        b.setIcon(icon)
        # keep text minimal if icon present
        if text:
            b.setText(text)
    b.setProperty("class", style_class)
    if object_name:
        b.setObjectName(object_name)
    if tooltip:
        b.setToolTip(tooltip)
    b.setMinimumHeight(32)
    b.setMaximumHeight(36)
    b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    # shorter width: don't set fixed width, let layout control it
    return b


# UI style constants for additional inline tweaks
INLINE_BUTTON_STYLE = """
QPushButton { border: none; }
QToolButton { border: none; }
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
    SETTINGS_ORG = "unique-image-finder"
    SETTINGS_APP = "uifinder"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Unique Image Finder")
        self.setMinimumWidth(1100)

        # Load settings
        self._settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self._theme = self._settings.value("theme", "light")

        # Apply initial style
        if self._theme == "dark":
            self._apply_styles(DARK_STYLE)
        else:
            self._apply_styles(GLASSY_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        # Top bar: left has folders, right has theme toggle and small controls
        top_bar = QHBoxLayout()

        # Reference Folder line edit (Drag & Drop enabled)
        self.ref_dir = DropLineEdit()
        self.ref_dir.setText(self._settings.value("last_ref", ""))
        self.ref_dir.editingFinished.connect(self._save_ref_setting)

        ref_btn = make_button("", icon=get_icon("folder", QApplication.instance()), object_name="ref_browse", style_class="neutral", tooltip="Browse reference folder")
        ref_btn.clicked.connect(lambda: self.browse_dir(self.ref_dir))

        # Working Folder
        self.work_dir = DropLineEdit()
        self.work_dir.setText(self._settings.value("last_work", ""))
        self.work_dir.editingFinished.connect(self._save_work_setting)

        work_btn = make_button("", icon=get_icon("folder", QApplication.instance()), object_name="work_browse", style_class="neutral", tooltip="Browse working folder")
        work_btn.clicked.connect(lambda: self.browse_dir(self.work_dir))

        top_bar.addWidget(QLabel("Reference:"))
        top_bar.addWidget(self.ref_dir, 2)
        top_bar.addWidget(ref_btn)
        top_bar.addSpacing(8)
        top_bar.addWidget(QLabel("Working:"))
        top_bar.addWidget(self.work_dir, 2)
        top_bar.addWidget(work_btn)

        # spacer
        top_bar.addItem(QSpacerItem(8, 8, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # Theme toggle (icon + text)
        self.theme_btn = QToolButton()
        self.theme_btn.setCheckable(True)
        self.theme_btn.setChecked(self._theme == "dark")
        self.theme_btn.setToolTip("Toggle dark/light theme")
        if self._theme == "dark":
            self.theme_btn.setText("🌙")
        else:
            self.theme_btn.setText("☀️")
        self.theme_btn.clicked.connect(self._toggle_theme)
        top_bar.addWidget(self.theme_btn)

        layout.addLayout(top_bar)

        # Options group (fields, hash toggle, similarity slider)
        opts_group = QGroupBox()
        opts_group.setTitle("Search Options")
        opts_layout = QHBoxLayout()

        # Compare fields selector (keeps same behavior)
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

        # Hash checkbox + similarity slider (hash_size removed)
        self.hash_cb = QCheckBox("By Hash (dhash, size=16)")
        self.hash_cb.stateChanged.connect(self._on_hash_toggled)

        self.sim_slider = QSlider(Qt.Horizontal)
        self.sim_slider.setMinimum(50)
        self.sim_slider.setMaximum(100)
        self.sim_slider.setValue(int(self._settings.value("similarity", 90)))
        self.sim_slider.setTickInterval(5)
        self.sim_slider.setTickPosition(QSlider.TicksBelow)
        self.sim_slider.setFixedWidth(220)
        self.sim_slider.setObjectName("similarity_slider")
        self.sim_lbl = QLabel(f"Similarity: {self.sim_slider.value()}%")
        self.sim_slider.valueChanged.connect(lambda v: self.sim_lbl.setText(f"Similarity: {v}%"))

        self.hash_info_btn = QToolButton()
        self.hash_info_btn.setText("ℹ")
        self.hash_info_btn.setAutoRaise(True)
        self.hash_info_btn.clicked.connect(self._open_hash_info)

        opts_layout.addWidget(self.field_selector_btn)
        opts_layout.addWidget(self.hash_cb)
        opts_layout.addWidget(self.sim_lbl)
        opts_layout.addWidget(self.sim_slider)
        opts_layout.addWidget(self.hash_info_btn)
        opts_group.setLayout(opts_layout)
        layout.addWidget(opts_group)

        # Search / progress row
        act_layout = QHBoxLayout()
        # Search button: icon-only with tooltip, styled primary
        search_icon = get_icon("search", QApplication.instance())
        self.search_btn = make_button("", icon=search_icon, object_name="search_btn", style_class="search", tooltip="Search")
        self.search_btn.setObjectName("search_btn")
        self.search_btn.clicked.connect(self.on_search_clicked)
        self.search_btn.setMinimumWidth(42)
        self.search_btn.setMaximumWidth(42)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(16)
        self.progress.setTextVisible(False)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        act_layout.addWidget(self.search_btn)
        act_layout.addWidget(self.progress)
        layout.addLayout(act_layout)

        # Results area -> Tabs
        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tabs.tabBar().setExpanding(True)  # make tabs span central area
        self.tabs.setContentsMargins(0, 0, 0, 0)

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

        layout.addWidget(self.tabs, 1)

        # Footer with action buttons and copyright
        footer = QHBoxLayout()
        # colorized buttons with icons and compact widths
        delete_icon = get_icon("delete", QApplication.instance())
        save_icon = get_icon("save", QApplication.instance())
        move_icon = get_icon("move", QApplication.instance())

        self.delete_btn = make_button("", icon=delete_icon, style_class="danger", tooltip="Delete all duplicate working files")
        self.delete_btn.clicked.connect(self._on_delete_all_duplicates)
        self.keep_btn = make_button("Keep", style_class="success", tooltip="Keep all duplicates (remove from view)")
        self.keep_btn.clicked.connect(self._on_keep_all_duplicates)
        self.save_uniques_btn = make_button("", icon=save_icon, style_class="success", tooltip="Save uniques to folder")
        self.save_uniques_btn.clicked.connect(self._on_save_uniques)

        # Make buttons compact
        for b in (self.delete_btn, self.keep_btn, self.save_uniques_btn):
            b.setMaximumWidth(140)
            b.setMinimumWidth(32)

        self.move_btn = make_button("", icon=move_icon, style_class="neutral", tooltip="Move selected")
        self.move_btn.setMaximumWidth(120)
        self.move_btn.clicked.connect(self._on_move_selected)

        self.delete_drop_btn = make_button("", icon=delete_icon, style_class="danger", tooltip="Delete selected (move to Trash)")
        self.delete_drop_btn.clicked.connect(self._on_delete_selected)

        footer.addWidget(self.delete_btn)
        footer.addWidget(self.keep_btn)
        footer.addWidget(self.save_uniques_btn)
        footer.addStretch()
        footer.addWidget(self.move_btn)
        footer.addWidget(self.delete_drop_btn)

        # Copyright label at right bottom
        self.footer_label = QLabel("© Mufaddal Kothari")
        self.footer_label.setObjectName("footer_label")
        footer.addWidget(self.footer_label)

        layout.addLayout(footer)

        # Connections for thread results
        self._thread = None
        self._last_results = None
        self._selected_paths = set()

    # --- style/theme helpers ---
    def _apply_styles(self, style_text: str):
        try:
            self.setStyleSheet(style_text)
        except Exception:
            logger.exception("Failed to apply styles")

    def _toggle_theme(self):
        self._theme = "dark" if self._theme != "dark" else "light"
        self._settings.setValue("theme", self._theme)
        if self._theme == "dark":
            self.theme_btn.setText("🌙")
            self._apply_styles(DARK_STYLE)
        else:
            self.theme_btn.setText("☀️")
            self._apply_styles(GLASSY_STYLE)

    # --- persistence helpers ---
    def _save_ref_setting(self):
        self._settings.setValue("last_ref", self.ref_dir.text().strip())

    def _save_work_setting(self):
        self._settings.setValue("last_work", self.work_dir.text().strip())

    # --- UI helpers ---
    def _open_hash_info(self):
        dlg = HashInfoDialog(self)
        dlg.exec_()

    def browse_dir(self, target_line_edit: QLineEdit):
        dlg = QFileDialog(self)
        dlg.setFileMode(QFileDialog.Directory)
        if dlg.exec_():
            target_line_edit.setText(dlg.selectedFiles()[0])
            if target_line_edit is self.ref_dir:
                self._save_ref_setting()
            else:
                self._save_work_setting()

    def _on_field_toggled(self, checked: bool):
        any_checked = any(act.isChecked() for act in self.field_actions.values())
        self.hash_cb.setEnabled(not any_checked)
        self.sim_slider.setEnabled(not any_checked)
        self.hash_info_btn.setEnabled(not any_checked)
        if any_checked and self.hash_cb.isChecked():
            self.hash_cb.setChecked(False)

    def _on_hash_toggled(self, state: int):
        checked = state == Qt.Checked
        self.field_selector_btn.setEnabled(not checked)
        for act in self.field_actions.values():
            act.setEnabled(not checked)
        if checked:
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
            self._clear_all_tabs()
            self._add_label_to_layout(self.duplicates_layout, "Please select both reference and working directories.")
            return

        # Save last used folders
        self._save_ref_setting()
        self._save_work_setting()
        self._settings.setValue("similarity", self.sim_slider.value())

        fields = self._get_selected_fields()
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
        self._clear_all_tabs()
        self.progress.setValue(0)

        self._thread = SearchThread(ref, work, criteria)
        self._thread.progress.connect(self._on_progress)
        self._thread.results_ready.connect(self._on_results_ready)
        self._thread.finished.connect(self._on_search_finished)
        self._thread.start()

    def _on_progress(self, value: int):
        self.progress.setValue(value)

    # --- Results rendering & actions (tab-aware) ---
    def _on_results_ready(self, payload: dict):
        self._last_results = payload
        self._selected_paths.clear()
        self._update_selected_count()

        duplicates = payload.get("duplicates", [])
        unique_in_ref = payload.get("unique_in_ref", [])
        unique_in_work = payload.get("unique_in_work", [])

        # Populate tabs once
        self._clear_all_tabs()
        if duplicates:
            self._add_label_to_layout(self.duplicates_layout, "<b>Duplicates / Matches</b>")
            for (r, w, reasons) in duplicates:
                self._add_duplicate_widget_to_layout(self.duplicates_layout, r, w, reasons)
        else:
            self._add_label_to_layout(self.duplicates_layout, "No duplicates found.")

        self._add_label_to_layout(self.uniques_ref_layout, "<b>Uniques (Reference)</b>")
        if unique_in_ref:
            for f in unique_in_ref:
                self._add_unique_widget_to_layout(self.uniques_ref_layout, f, side="ref")
        else:
            self._add_label_to_layout(self.uniques_ref_layout, "<i>No unique files found in Reference</i>")

        self._add_label_to_layout(self.uniques_work_layout, "<b>Uniques (Working)</b>")
        if unique_in_work:
            for f in unique_in_work:
                self._add_unique_widget_to_layout(self.uniques_work_layout, f, side="work")
        else:
            self._add_label_to_layout(self.uniques_work_layout, "<i>No unique files found in Working</i>")

        # Select duplicates tab by default
        self.tabs.setCurrentIndex(0)

    # Tab layout helpers
    def _clear_all_tabs(self):
        for layout in (self.duplicates_layout, self.uniques_ref_layout, self.uniques_work_layout):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()

    def _add_label_to_layout(self, layout, text):
        lbl = QLabel()
        lbl.setText(text)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

    def _add_duplicate_widget_to_layout(self, layout, r: ImageFileObj, w: ImageFileObj, reasons: List[str]):
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row.setStyleSheet("background: rgba(255,255,255,0.02); border-radius:8px;")
        row_layout = QHBoxLayout(row)
        cb_r = QCheckBox()
        cb_r.stateChanged.connect(lambda s, p=r.path: self._on_path_toggled(p, s))
        cb_w = QCheckBox()
        cb_w.stateChanged.connect(lambda s, p=w.path: self._on_path_toggled(p, s))
        thumb_r = QLabel()
        pixr = QPixmap(r.path)
        if not pixr.isNull():
            thumb_r.setPixmap(pixr.scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            thumb_r.setText("No preview")
        thumb_w = QLabel()
        pixw = QPixmap(w.path)
        if not pixw.isNull():
            thumb_w.setPixmap(pixw.scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            thumb_w.setText("No preview")
        info_lbl = QLabel(f"Ref: {r.path}\nWork: {w.path}\nMatch: {', '.join(reasons)}")
        info_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        compare_btn = make_button("", icon=get_icon("open", QApplication.instance()), style_class="neutral", tooltip="Compare files")
        compare_btn.clicked.connect(lambda _, a=r, b=w, rs=reasons: self._open_compare_modal(a, b, rs))
        row_layout.addWidget(cb_r)
        row_layout.addWidget(thumb_r)
        row_layout.addWidget(cb_w)
        row_layout.addWidget(thumb_w)
        row_layout.addWidget(info_lbl, 1)
        row_layout.addWidget(compare_btn)
        layout.addWidget(row)

    def _add_unique_widget_to_layout(self, layout, f: ImageFileObj, side: str = "ref"):
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row.setStyleSheet("background: rgba(255,255,255,0.02); border-radius:8px;")
        row_layout = QHBoxLayout(row)
        cb = QCheckBox()
        cb.stateChanged.connect(lambda s, p=f.path: self._on_path_toggled(p, s))
        thumb = QLabel()
        pix = QPixmap(f.path)
        if not pix.isNull():
            thumb.setPixmap(pix.scaled(112, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            thumb.setText("No preview")
        info_lbl = QLabel()
        info_lbl.setText(f"{'Reference' if side == 'ref' else 'Working'} unique\nName: {f.name}\nSize: {f.size}\nDims: {f.dimensions}\nPath: {f.path}")
        info_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_btn = make_button("", icon=get_icon("open", QApplication.instance()), style_class="neutral", tooltip="Open file")
        open_btn.clicked.connect(lambda _, p=f.path: os.startfile(p) if os.path.exists(p) else None)
        row_layout.addWidget(cb)
        row_layout.addWidget(thumb)
        row_layout.addWidget(info_lbl, 1)
        row_layout.addWidget(open_btn)
        layout.addWidget(row)

    def _on_path_toggled(self, path: str, state):
        if state == Qt.Checked:
            self._selected_paths.add(path)
        else:
            self._selected_paths.discard(path)
        self._update_selected_count()

    def _update_selected_count(self):
        # Keep footer label as the selection count (not replacing copyright)
        self.footer_label.setText(f"© Mufaddal Kothari    Selected: {len(self._selected_paths)}")

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
        self._clear_all_tabs()

    def _on_search_finished(self):
        self.search_btn.setEnabled(True)
        self.progress.setValue(100)
