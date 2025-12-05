# ui/main_window.py
# UI updates requested:
# 1) Ubuntu Mono font usage
# 2) Left panel directory-only browser (no files shown), minimal display: "name (N)"
# 3) Left panel hide/collapse
# 4) Tab headers show counts (updated when results ready and on tab switch)
# 5) Stylized compare dropdown, theme toggle and info button (object names for styles)
# 6) Search button uses text "Search" (no icon)
# 7) Improved modern scrollbars come from ui/styles.py
#
# Replace ui/main_window.py with this file. Tested for compatibility with earlier changes.

import os
import shutil
from pathlib import Path
from typing import List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QFileDialog, QCheckBox, QProgressBar, QScrollArea,
    QSizePolicy, QFrame, QMessageBox, QToolButton, QMenu, QAction, QSlider,
    QTabWidget, QApplication, QStyle, QTreeView, QFileSystemModel, QListWidgetItem
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


# Subclass QFileSystemModel to show directories only and append counts to display text
class DirOnlyModel(QFileSystemModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # show dirs only
        self.setFilter(QDir.NoDotAndDotDot | QDir.Dirs)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        # Only change the display role text for first column (name)
        if role == Qt.DisplayRole and index.column() == 0:
            # get base name
            name = super().data(index, role)
            # count files inside (not recursive) and show only the number
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
        # apply theme
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

        # Left panel (dir-only tree)
        self.left_panel = QFrame()
        self.left_panel.setObjectName("left_panel")
        self.left_panel.setMinimumWidth(220)
        self.left_panel.setMaximumWidth(360)
        lp_layout = QVBoxLayout(self.left_panel)
        lp_layout.setContentsMargins(8,8,8,8)
        lp_layout.setSpacing(6)

        # Collapse button
        self.collapse_btn = QToolButton()
        self.collapse_btn.setText("◀")
        self.collapse_btn.setToolTip("Hide/Show browser panel")
        self.collapse_btn.setCheckable(True)
        self.collapse_btn.clicked.connect(self._toggle_left_panel)
        lp_layout.addWidget(self.collapse_btn)

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
        # show directories only and minimal columns
        self.browser_tree.setRootIndex(self.fs_model.index(last_root) if os.path.isdir(last_root) else self.fs_model.index(QDir.rootPath()))
        self.browser_tree.setHeaderHidden(True)
        # hide columns other than name
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

        # Top row: reference/work inputs + stylized controls
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
        # stylized compare dropdown, theme toggle, info button
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
        # theme toggle button (styled)
        self.theme_btn = QToolButton()
        self.theme_btn.setObjectName("theme_toggle_btn")
        self.theme_btn.setCheckable(True)
        self.theme_btn.setChecked(self._settings.value("theme","light")=="dark")
        self._apply_theme_button_text()
        self.theme_btn.clicked.connect(self._on_theme_toggle)
        # info button
        self.info_btn = QToolButton()
        self.info_btn.setObjectName("info_btn")
        self.info_btn.setText("ℹ")
        self.info_btn.clicked.connect(self._open_hash_info)

        top_row.addWidget(self.field_selector_btn)
        top_row.addWidget(self.theme_btn)
        top_row.addWidget(self.info_btn)

        content_layout.addLayout(top_row)

        # Options row (compact)
        options_row = QHBoxLayout()
        self.hash_cb = QCheckBox("By Hash (dhash, size=16)")
        self.sim_slider = QSlider(Qt.Horizontal)
        self.sim_slider.setMinimum(50)
        self.sim_slider.setMaximum(100)
        self.sim_slider.setValue(int(self._settings.value("similarity",90)))
        self.sim_slider.setFixedWidth(200)
        self.sim_lbl = QLabel(f"{self.sim_slider.value()}%")
        self.sim_slider.valueChanged.connect(lambda v: self.sim_lbl.setText(f"{v}%"))
        options_row.addWidget(self.hash_cb)
        options_row.addWidget(QLabel("Similarity:"))
        options_row.addWidget(self.sim_slider)
        options_row.addWidget(self.sim_lbl)
        content_layout.addLayout(options_row)

        # Search row (text button)
        search_row = QHBoxLayout()
        self.search_btn = make_button("Search", object_name="search_btn", style_class="search")
        self.search_btn.clicked.connect(self.on_search_clicked)
        self.search_btn.setMinimumWidth(84)
        self.progress = QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(16)
        search_row.addWidget(self.search_btn)
        search_row.addWidget(self.progress)
        content_layout.addLayout(search_row)

        # Tab header counts label (above tabs)
        self.tab_count_label = QLabel("")  # updated on results and tab change
        content_layout.addWidget(self.tab_count_label)

        # Tabs area (do not force expand: labels won't be hidden)
        self.tabs = QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # duplicates tab
        self.duplicates_container = QWidget()
        self.duplicates_layout = QVBoxLayout(self.duplicates_container)
        self.duplicates_layout.setAlignment(Qt.AlignTop)
        self.duplicates_scroll = QScrollArea()
        self.duplicates_scroll.setWidgetResizable(True)
        self.duplicates_scroll.setWidget(self.duplicates_container)
        self.tabs.addTab(self.duplicates_scroll, "Duplicates")

        # uniques ref
        self.uniques_ref_container = QWidget()
        self.uniques_ref_layout = QVBoxLayout(self.uniques_ref_container)
        self.uniques_ref_layout.setAlignment(Qt.AlignTop)
        self.uniques_ref_scroll = QScrollArea()
        self.uniques_ref_scroll.setWidgetResizable(True)
        self.uniques_ref_scroll.setWidget(self.uniques_ref_container)
        self.tabs.addTab(self.uniques_ref_scroll, "Uniques (Reference)")

        # uniques work
        self.uniques_work_container = QWidget()
        self.uniques_work_layout = QVBoxLayout(self.uniques_work_container)
        self.uniques_work_layout.setAlignment(Qt.AlignTop)
        self.uniques_work_scroll = QScrollArea()
        self.uniques_work_scroll.setWidgetResizable(True)
        self.uniques_work_scroll.setWidget(self.uniques_work_container)
        self.tabs.addTab(self.uniques_work_scroll, "Uniques (Working)")

        content_layout.addWidget(self.tabs, 1)

        # Footer with compact buttons and copyright
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

        # assemble main layout
        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(self.main_content)

        # internal state
        self._thread = None
        self._last_results = None
        self._selected_paths = set()
        self._last_tree_index = None

    # restore settings
    def _restore_settings(self):
        # apply browser root if present
        root = self._settings.value("browser_root", str(Path.home()))
        if os.path.isdir(root):
            self.browser_tree.setRootIndex(self.fs_model.index(root))
        # theme button text
        self._apply_theme_button_text()

    # left panel helpers
    def _toggle_left_panel(self):
        if self.collapse_btn.isChecked():
            self.left_panel.hide()
            self.collapse_btn.setText("▶")
        else:
            self.left_panel.show()
            self.collapse_btn.setText("◀")

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

    # theme & style
    def _apply_theme_button_text(self):
        self.theme_btn.setText("🌙" if self._settings.value("theme","light")=="dark" else "☀️")

    def _on_theme_toggle(self):
        new = "dark" if self._settings.value("theme","light")!="dark" else "light"
        self._settings.setValue("theme", new)
        self._apply_theme(new)
        self._apply_theme_button_text()

    # browsing helpers
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
        self._clear_tabs()
        self.progress.setValue(0)
        self._thread = SearchThread(ref, work, criteria)
        self._thread.progress.connect(self._on_progress)
        self._thread.results_ready.connect(self._on_results_ready)
        self._thread.finished.connect(self._on_search_finished)
        self._thread.start()

    def _on_progress(self, v:int):
        self.progress.setValue(v)

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
        # update tab count label for currently visible tab
        self._update_tab_count_label(self.tabs.currentIndex())
        # populate content
        self._clear_tabs()
        if duplicates:
            self._add_label(self.duplicates_layout, "<b>Duplicates / Matches</b>")
            for r,w, reasons in duplicates:
                self._add_duplicate(r,w,reasons)
        else:
            self._add_label(self.duplicates_layout, "No duplicates found.")
        self._add_label(self.uniques_ref_layout, "<b>Uniques (Reference)</b>")
        if uref:
            for f in uref:
                self._add_unique(f, side="ref")
        else:
            self._add_label(self.uniques_ref_layout, "<i>No unique files in Reference</i>")
        self._add_label(self.uniques_work_layout, "<b>Uniques (Working)</b>")
        if uwork:
            for f in uwork:
                self._add_unique(f, side="work")
        else:
            self._add_label(self.uniques_work_layout, "<i>No unique files in Working</i>")
        self.search_btn.setEnabled(True)
        self.progress.setValue(100)

    def _on_tab_changed(self, index:int):
        self._update_tab_count_label(index)

    def _update_tab_count_label(self, index:int):
        # read counts from tab text (already set) and display summary
        txt = self.tabs.tabText(index)
        # Build summary: Duplicates: X | Unique Ref: Y | Unique Work: Z
        dup_text = self.tabs.tabText(0)
        ref_text = self.tabs.tabText(1)
        work_text = self.tabs.tabText(2)
        self.tab_count_label.setText(f"{dup_text}    |    {ref_text}    |    {work_text}")

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
        cb_r.stateChanged.connect(lambda s, p=r.path: self._toggle_selection(p,s))
        cb_w = QCheckBox()
        cb_w.stateChanged.connect(lambda s, p=w.path: self._toggle_selection(p,s))
        thumb_r = QLabel()
        pixr = QPixmap(r.path)
        if not pixr.isNull():
            thumb_r.setPixmap(pixr.scaled(92,92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        thumb_w = QLabel()
        pixw = QPixmap(w.path)
        if not pixw.isNull():
            thumb_w.setPixmap(pixw.scaled(92,92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        info = QLabel(f"Ref: {r.path}\nWork: {w.path}\nMatch: {', '.join(reasons)}")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        compare_btn = make_button("Compare", style_class="neutral")
        compare_btn.clicked.connect(lambda _, a=r,b=w,rs=reasons: self._open_compare_modal(a,b,rs))
        rl.addWidget(cb_r)
        rl.addWidget(thumb_r)
        rl.addWidget(cb_w)
        rl.addWidget(thumb_w)
        rl.addWidget(info,1)
        rl.addWidget(compare_btn)
        self.duplicates_layout.addWidget(row)

    def _add_unique(self, f: ImageFileObj, side:str="ref"):
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row.setStyleSheet("background: rgba(255,255,255,0.02); border-radius:8px;")
        rl = QHBoxLayout(row)
        cb = QCheckBox()
        cb.stateChanged.connect(lambda s, p=f.path: self._toggle_selection(p,s))
        thumb = QLabel()
        pix = QPixmap(f.path)
        if not pix.isNull():
            thumb.setPixmap(pix.scaled(112,112, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        info = QLabel(f"{'Reference' if side=='ref' else 'Working'} unique\nName: {f.name}\nSize: {f.size}\nDims: {f.dimensions}\nPath: {f.path}")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_btn = make_button("Open", style_class="neutral")
        open_btn.clicked.connect(lambda _, p=f.path: os.startfile(p) if os.path.exists(p) else None)
        rl.addWidget(cb)
        rl.addWidget(thumb)
        rl.addWidget(info,1)
        rl.addWidget(open_btn)
        if side=="ref":
            self.uniques_ref_layout.addWidget(row)
        else:
            self.uniques_work_layout.addWidget(row)

    def _toggle_selection(self, path:str, state):
        if state==Qt.Checked:
            self._selected_paths.add(path)
        else:
            self._selected_paths.discard(path)
        self._update_selected_count()

    def _update_selected_count(self):
        self.footer_label.setText(f"© Mufaddal Kothari    Selected: {len(self._selected_paths)}")

    def _open_compare_modal(self, a:ImageFileObj, b:ImageFileObj, reasons):
        meta1 = {"name":a.name,"size":a.size,"path":a.path,"dimensions":a.dimensions}
        meta2 = {"name":b.name,"size":b.size,"path":b.path,"dimensions":b.dimensions}
        modal = ComparisonModal(a.path,b.path,meta1,meta2,", ".join(reasons), action_callback=self._on_modal_action, parent=self)
        modal.exec_()

    def _on_modal_action(self, action:str, paths:List[str]):
        if action.startswith("delete") and paths:
            for p in paths:
                try:
                    if os.path.exists(p):
                        send2trash(p)
                except Exception:
                    pass
            self._remove_widgets_for_paths(paths)

    def _remove_widgets_for_paths(self, paths:List[str]):
        path_set = set(paths)
        for layout in (self.duplicates_layout, self.uniques_ref_layout, self.uniques_work_layout):
            i=0
            while i < layout.count():
                item = layout.itemAt(i)
                widget = item.widget()
                should_remove=False
                if widget:
                    labels = widget.findChildren(QLabel)
                    for lbl in labels:
                        txt = lbl.text() or ""
                        for p in path_set:
                            if p in txt:
                                should_remove=True
                                break
                        if should_remove:
                            break
                if should_remove:
                    w = layout.takeAt(i).widget()
                    if w:
                        w.deleteLater()
                else:
                    i+=1

    def _on_delete_all_duplicates(self):
        if not self._last_results:
            QMessageBox.information(self,"No results","No search results.")
            return
        duplicates = self._last_results.get("duplicates",[])
        if not duplicates:
            QMessageBox.information(self,"No duplicates","No duplicates found.")
            return
        reply = QMessageBox.question(self,"Confirm delete all duplicates","Delete duplicate working files? (Move to Trash)", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        to_delete = [w.path for (r,w,_) in duplicates if getattr(w,"path",None)]
        for p in to_delete:
            try:
                if os.path.exists(p):
                    send2trash(p)
            except Exception:
                pass
        self._remove_widgets_for_paths(to_delete)
        QMessageBox.information(self,"Done","Duplicates moved to Trash.")

    def _on_keep_all_duplicates(self):
        if not self._last_results:
            QMessageBox.information(self,"No results","No search results.")
            return
        duplicates = self._last_results.get("duplicates",[])
        if not duplicates:
            QMessageBox.information(self,"No duplicates","No duplicates found.")
            return
        to_remove=[]
        for (r,w,_) in duplicates:
            to_remove.extend([r.path,w.path])
        self._remove_widgets_for_paths(to_remove)
        QMessageBox.information(self,"Done","Duplicates removed from view (kept on disk).")

    def _on_save_uniques(self):
        if not self._last_results:
            QMessageBox.information(self,"No results","No search results.")
            return
        unique_in_ref = self._last_results.get("unique_in_ref",[])
        unique_in_work = self._last_results.get("unique_in_work",[])
        if not unique_in_ref and not unique_in_work:
            QMessageBox.information(self,"No uniques","No unique files found.")
            return
        dlg = QFileDialog(self, caption="Select destination folder")
        dlg.setFileMode(QFileDialog.Directory)
        if dlg.exec_():
            dest = dlg.selectedFiles()[0]
            dest_path = Path(dest)
            errors=[]
            def _copy_list(list_files, sub):
                if not list_files:
                    return
                folder = dest_path / sub
                folder.mkdir(parents=True, exist_ok=True)
                for f in list_files:
                    src = Path(f.path)
                    if not src.exists():
                        errors.append((str(src),"Missing"))
                        continue
                    dest_file = folder / src.name
                    try:
                        shutil.copy2(str(src), str(dest_file))
                    except Exception as e:
                        errors.append((str(src), str(e)))
            _copy_list(unique_in_ref, "reference_uniques")
            _copy_list(unique_in_work, "working_uniques")
            if errors:
                QMessageBox.warning(self,"Copy errors", f"Some files failed to copy: {errors}")
            else:
                QMessageBox.information(self,"Done", f"Copied uniques to {dest_path}")

    def _on_move_selected(self):
        if not self._selected_paths:
            QMessageBox.information(self,"No selection","No files selected.")
            return
        dlg = QFileDialog(self, caption="Select destination folder")
        dlg.setFileMode(QFileDialog.Directory)
        if dlg.exec_():
            dest = dlg.selectedFiles()[0]
            for p in list(self._selected_paths):
                try:
                    if os.path.exists(p):
                        shutil.move(p, os.path.join(dest, os.path.basename(p)))
                        self._remove_widgets_for_paths([p])
                        self._selected_paths.discard(p)
                except Exception:
                    pass
            self._update_selected_count()
            QMessageBox.information(self,"Done","Moved selected files.")

    def _on_delete_selected(self):
        if not self._selected_paths:
            QMessageBox.information(self,"No selection","No files selected.")
            return
        reply = QMessageBox.question(self,"Confirm delete", f"Move {len(self._selected_paths)} items to Trash?", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        for p in list(self._selected_paths):
            try:
                if os.path.exists(p):
                    send2trash(p)
                    self._remove_widgets_for_paths([p])
                    self._selected_paths.discard(p)
            except Exception:
                pass
        self._update_selected_count()
        QMessageBox.information(self,"Done","Deleted selected files.")

    def _on_search_finished(self):
        self.search_btn.setEnabled(True)
        self.progress.setValue(100)
