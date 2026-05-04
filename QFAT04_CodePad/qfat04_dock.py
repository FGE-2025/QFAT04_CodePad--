"""
qfat04_dock.py
The Main Shell. Fixed Global Drag and Drop and AddonManager Integration.
"""
import os
import copy
import re

from qgis.PyQt.QtCore import Qt, QProcess, QEvent, QSettings, QTimer, QUrl
from qgis.PyQt.QtGui import QGuiApplication, QKeySequence, QFont
from qgis.PyQt.QtWidgets import (
    QAction, QCheckBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, 
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, 
    QMenu, QMenuBar, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, 
    QStatusBar, QTabWidget, QTextBrowser, QTextEdit, QToolBar, QTreeWidget, QTreeWidgetItem, 
    QVBoxLayout, QWidget,
)

from .qfat04_config import (
    TEXT_EXTS, RUN_EXTS, DEFAULT_EDITOR_SHORTCUTS, load_config, save_config, 
    save_theme, load_editor_shortcuts, save_editor_shortcuts, load_languages, 
    save_languages, language_display_name, make_language_key,
    load_addon_shortcut_overrides, save_addon_shortcut_overrides,
)
from .qfat04_editor import EditorPage, DropTabWidget, EditorShortcutFilter, detect_eol
from .qfat04_addons import AddonManager
from .qfat04_runners import RunController
from .qfat04_dialogs import (
    LanguageEditorDialog, LanguageManagerDialog, SettingsDialog, 
    ShortcutsDialog, PlaceholderDialog, AddonManagerDialog
)

class CodePadFloatingWindow(QWidget):
    """Standalone window that hosts the CodePad inner_window when detached."""
    def __init__(self, dock, inner_widget):
        super().__init__(None, Qt.Window)  # No parent + Qt.Window → independent OS window
        self.dock = dock
        self._closing_to_dock = False
        self.setWindowTitle("QFAT04 CodePad--")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner_widget)
        inner_widget.show()
        # Copy icon from dock
        self.setWindowIcon(self.dock.windowIcon())

    def set_always_on_top(self, enabled):
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def closeEvent(self, event):
        if self._closing_to_dock:
            # Being closed by reattach_to_dock — allow
            event.accept()
            return
        # User clicked X on floating window → reattach to dock
        event.ignore()
        self.dock.reattach_to_dock()

class QFAT04Dock(QDockWidget):
    def __init__(self, iface):
        super().__init__("QFAT04 CodePad--", iface.mainWindow())
        self.iface            = iface
        self.config           = load_config()
        self.languages        = self.config.get("languages") or load_languages()
        self.config["languages"] = self.languages
        self.recent_files     = []
        self.editor_shortcuts = load_editor_shortcuts()
        self.setObjectName("QFAT04_CodePad_Dock")

        self._runner            = RunController()
        self.editor_key_filter  = EditorShortcutFilter(self)
        self.toolbar_action_map = {}
        self.language_actions   = {}
        self.language_menu      = None
        
        self.addon_manager = AddonManager(self)
        self._floating_window = None
        self._flash_state = None
        self.setAcceptDrops(True)
        self._build_ui()

    def _install_global_drop_targets(self):
        self.setAcceptDrops(True)
        for child in self.findChildren(QWidget):
            child.setAcceptDrops(True)
            child.removeEventFilter(self)
            child.installEventFilter(self)
            if hasattr(child, 'viewport') and callable(child.viewport):
                vp = child.viewport()
                if vp:
                    vp.setAcceptDrops(True)
                    vp.removeEventFilter(self)
                    vp.installEventFilter(self)

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            mime = event.mimeData()
            if mime and mime.hasUrls():
                if et == QEvent.Drop:
                    paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
                    if paths:
                        self.open_paths(paths)
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    def _build_ui(self):
        self.inner_window = QMainWindow()
        self.inner_window.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)
        self.setWidget(self.inner_window)

        self._build_panels()
        self.menu_bar = self._build_menu()
        self.inner_window.setMenuBar(self.menu_bar)
        self._build_toolbar()
        self._build_statusbar()
        self.inner_window.setCentralWidget(self._build_central())

        self.inner_window.addDockWidget(Qt.LeftDockWidgetArea,   self.dock_files)
        self.dock_files.hide()

        self.inner_window.addDockWidget(Qt.BottomDockWidgetArea, self.dock_console)
        self.inner_window.addDockWidget(Qt.BottomDockWidgetArea, self.dock_messages)
        self.inner_window.addDockWidget(Qt.BottomDockWidgetArea, self.dock_find_results)
        self.inner_window.tabifyDockWidget(self.dock_console,    self.dock_messages)
        self.inner_window.tabifyDockWidget(self.dock_messages,   self.dock_find_results)
        self.dock_console.raise_()

        self.inner_window.addDockWidget(Qt.TopDockWidgetArea, self.dock_search)
        self.dock_search.setFloating(True)
        self.dock_search.resize(700, 40)
        self.dock_search.hide()  # hidden by default, Ctrl+F shows it

        self.new_tab()
        self._refresh_titles()
        self._refresh_recent_menu()
        self._update_status()
        _drop_delay = int(QSettings().value("QFAT/QFAT04/delay_drop_targets", 1000))
        QTimer.singleShot(_drop_delay, self._install_global_drop_targets)
        # Addon panels/toolbar/shortcuts created by deferred _load_startup_addons

    def _build_panels(self):
        self.dock_files = QDockWidget("Files", self.inner_window)
        self.dock_files.setObjectName("QFAT04_DockFiles")
        self.files_tree = QTreeWidget(); self.files_tree.setHeaderLabels(["Files"])
        self.files_tree.itemDoubleClicked.connect(self._open_from_tree)
        self.dock_files.setWidget(self.files_tree)

        self.dock_console = QDockWidget("Console", self.inner_window)
        self.dock_console.setObjectName("QFAT04_DockConsole")
        self.console = QTextEdit(); self.console.setReadOnly(True)
        self.console.setContextMenuPolicy(Qt.CustomContextMenu)
        self.console.customContextMenuRequested.connect(lambda pos: self._panel_context(self.console, pos))
        self.dock_console.setWidget(self.console)

        self.dock_messages = QDockWidget("Messages", self.inner_window)
        self.dock_messages.setObjectName("QFAT04_DockMessages")
        self.messages = QTextEdit(); self.messages.setReadOnly(True)
        self.messages.setContextMenuPolicy(Qt.CustomContextMenu)
        self.messages.customContextMenuRequested.connect(lambda pos: self._panel_context(self.messages, pos))
        self.dock_messages.setWidget(self.messages)

        self.dock_find_results = QDockWidget("Find Results", self.inner_window)
        self.dock_find_results.setObjectName("QFAT04_DockFindResults")
        # Legacy panel kept for addon backward compat — hidden by default
        self.find_results = QTextBrowser(); self.find_results.setReadOnly(True)
        self.find_results.setOpenLinks(False)
        self.find_results.anchorClicked.connect(self._on_find_result_clicked)
        self.find_results.setContextMenuPolicy(Qt.CustomContextMenu)
        self.find_results.customContextMenuRequested.connect(lambda pos: self._panel_context(self.find_results, pos))
        self.dock_find_results.setWidget(self.find_results)
        self.dock_find_results.hide()

        # ── Search dock (single-row, movable) ──────────────────────
        self.dock_search = QDockWidget("Search", self.inner_window)
        self.dock_search.setObjectName("QFAT04_DockSearch")
        self.dock_search.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        _sbar_ss = (
            "QLineEdit { padding:1px 2px; font-size:7pt; }"
            "QPushButton { padding:0px 4px; font-size:7pt; }"
            "QCheckBox { font-size:7pt; spacing:2px; }"
        )
        search_w = QWidget(); search_w.setStyleSheet(_sbar_ss)
        slay_outer = QVBoxLayout(search_w); slay_outer.setContentsMargins(2, 1, 2, 1); slay_outer.setSpacing(2)
        # Top row: find/replace controls
        search_row = QWidget()
        slay = QHBoxLayout(search_row); slay.setContentsMargins(0, 0, 0, 0); slay.setSpacing(3)
        self.find_text     = QLineEdit(); self.find_text.setPlaceholderText("Find"); self.find_text.setMinimumWidth(40); self.find_text.setMaximumHeight(20)
        self.btn_find      = QPushButton("Find Next");  self.btn_find.setMaximumHeight(20)
        self.btn_find_prev = QPushButton("Find Prev");  self.btn_find_prev.setMaximumHeight(20)
        self.chk_regex     = QCheckBox("Regex");   self.chk_regex.setToolTip("Use regular expressions")
        self.replace_text  = QLineEdit(); self.replace_text.setPlaceholderText("Replace"); self.replace_text.setMinimumWidth(40); self.replace_text.setMaximumHeight(20)
        self.btn_replace     = QPushButton("Replace");  self.btn_replace.setMaximumHeight(20)
        self.btn_replace_all = QPushButton("Replace All");  self.btn_replace_all.setMaximumHeight(20)
        self.btn_find_all    = QPushButton("Find All"); self.btn_find_all.setMaximumHeight(20); self.btn_find_all.setToolTip("Find all occurrences in current file")
        self.btn_find_all_files = QPushButton("Find All Files"); self.btn_find_all_files.setMaximumHeight(20); self.btn_find_all_files.setToolTip("Find all occurrences in all open files")
        self.btn_replace_all_files = QPushButton("Replace All Files"); self.btn_replace_all_files.setMaximumHeight(20); self.btn_replace_all_files.setToolTip("Replace all occurrences in all open files")
        self.btn_clear_results = QPushButton("Clear"); self.btn_clear_results.setMaximumHeight(20); self.btn_clear_results.setToolTip("Clear find results")
        self.find_text.returnPressed.connect(self.find_next)
        self.btn_find.clicked.connect(self.find_next)
        self.btn_find_prev.clicked.connect(self.find_prev)
        self.btn_replace.clicked.connect(self.replace_next)
        self.btn_replace_all.clicked.connect(self.replace_all)
        self.btn_find_all.clicked.connect(self.find_all)
        self.btn_find_all_files.clicked.connect(self.find_all_files)
        self.btn_replace_all_files.clicked.connect(self.replace_all_files)
        self.btn_clear_results.clicked.connect(self._clear_find_results)
        for w in [self.find_text, self.btn_find_prev, self.btn_find, self.chk_regex,
                  self.replace_text, self.btn_replace, self.btn_replace_all,
                  self.btn_find_all, self.btn_find_all_files, self.btn_replace_all_files,
                  self.btn_clear_results]:
            slay.addWidget(w)
        slay.setStretch(0, 1)  # find_text stretches
        slay.setStretch(4, 1)  # replace_text stretches
        slay_outer.addWidget(search_row)
        # Bottom: inline find results (hidden by default)
        # Inline find results tree (collapsible groups, expandable height)
        self.inline_find_results = QTreeWidget()
        self.inline_find_results.setHeaderLabels(["Result", "Line", "Col"])
        self.inline_find_results.setRootIsDecorated(True)
        self.inline_find_results.setColumnWidth(0, 500)
        self.inline_find_results.setColumnWidth(1, 50)
        self.inline_find_results.setColumnWidth(2, 40)
        self.inline_find_results.setStyleSheet("QTreeWidget { font-size: 8pt; }")
        self.inline_find_results.setMinimumHeight(0)
        self.inline_find_results.itemDoubleClicked.connect(self._on_result_item_clicked)
        self.inline_find_results.hide()
        slay_outer.addWidget(self.inline_find_results, 1)
        self.dock_search.setWidget(search_w)

    def _build_menu(self):
        mb = QMenuBar()
        file_menu      = mb.addMenu("File")
        edit_menu      = mb.addMenu("Edit")
        search_menu    = mb.addMenu("Search")
        self.view_menu = mb.addMenu("View")
        encoding_menu  = mb.addMenu("Encoding")
        language_menu  = mb.addMenu("Language")
        run_menu       = mb.addMenu("Run")
        
        self.addons_menu = mb.addMenu("Addons")
        self.rebuild_addons_menu()
        
        settings_menu  = mb.addMenu("Settings")
        help_menu      = mb.addMenu("Help")
        self.language_menu = language_menu

        self.recent_menu    = QMenu("Open Recent", self)
        self.act_open       = QAction("Open...", self);          self.act_open.setShortcut("Ctrl+O");  self.act_open.triggered.connect(self.open_file)
        self.act_save       = QAction("Save", self);             self.act_save.setShortcut("Ctrl+S"); self.act_save.setShortcutContext(Qt.WidgetWithChildrenShortcut);  self.act_save.triggered.connect(self.save_current); self.act_save.setEnabled(False)
        self.act_save_as    = QAction("Save As...", self);       self.act_save_as.triggered.connect(self.save_current_as)
        self.act_save_all   = QAction("Save All", self);         self.act_save_all.triggered.connect(self.save_all)
        self.act_reload     = QAction("Reload from Disk", self); self.act_reload.triggered.connect(self.reload_current)
        self.act_print      = QAction("Print...", self);         self.act_print.triggered.connect(self.print_current)
        self.act_new        = QAction("New Tab", self);          self.act_new.triggered.connect(lambda: self.new_tab())
        self.act_close      = QAction("Close Tab", self);        self.act_close.triggered.connect(self.close_current_tab)
        self.act_close_others = QAction("Close Others", self);   self.act_close_others.triggered.connect(self.close_other_tabs)
        self.act_close_right  = QAction("Close All to Right", self); self.act_close_right.triggered.connect(self.close_tabs_to_right)
        for act in [self.act_new, self.act_open]: file_menu.addAction(act)
        file_menu.addMenu(self.recent_menu)
        file_menu.addSeparator()
        for act in [self.act_save, self.act_save_as, self.act_save_all, self.act_reload]: file_menu.addAction(act)
        file_menu.addSeparator(); file_menu.addAction(self.act_print); file_menu.addSeparator()
        for act in [self.act_close, self.act_close_others, self.act_close_right]: file_menu.addAction(act)

        self.act_undo       = QAction("Undo",       self); self.act_undo.triggered.connect(self.edit_undo)
        self.act_redo       = QAction("Redo",       self); self.act_redo.triggered.connect(self.edit_redo)
        self.act_cut        = QAction("Cut",        self); self.act_cut.triggered.connect(self.edit_cut)
        self.act_copy       = QAction("Copy",       self); self.act_copy.triggered.connect(self.edit_copy)
        self.act_paste      = QAction("Paste",      self); self.act_paste.triggered.connect(self.edit_paste)
        self.act_select_all = QAction("Select All", self); self.act_select_all.triggered.connect(self.edit_select_all)
        self.act_toggle_comment = QAction("Toggle Comment", self); self.act_toggle_comment.triggered.connect(self.toggle_comment)
        self.act_duplicate_line = QAction("Duplicate Line", self); self.act_duplicate_line.triggered.connect(self.duplicate_line)
        self.addAction(self.act_toggle_comment); self.addAction(self.act_duplicate_line)
        for act in [self.act_undo, self.act_redo, self.act_cut, self.act_copy, self.act_paste,
                    self.act_select_all, self.act_toggle_comment, self.act_duplicate_line]:
            edit_menu.addAction(act)
        self.editor_shortcut_actions = {
            "toggle_comment": self.act_toggle_comment,
            "duplicate_line": self.act_duplicate_line,
        }
        self._apply_editor_shortcuts()

        self.act_find      = QAction("Find", self);        self.act_find.setShortcut(QKeySequence("Ctrl+F")); self.act_find.setShortcutContext(Qt.WidgetWithChildrenShortcut); self.act_find.triggered.connect(self.trigger_find)
        self.act_replace   = QAction("Replace", self);     self.act_replace.setShortcut(QKeySequence("Ctrl+H")); self.act_replace.setShortcutContext(Qt.WidgetWithChildrenShortcut); self.act_replace.triggered.connect(self.trigger_replace)
        self.act_find_next = QAction("Find Next", self);   self.act_find_next.setShortcut(QKeySequence("F3")); self.act_find_next.setShortcutContext(Qt.WidgetWithChildrenShortcut); self.act_find_next.triggered.connect(self.find_next)
        self.act_find_prev = QAction("Find Previous", self); self.act_find_prev.setShortcut(QKeySequence("Shift+F3")); self.act_find_prev.setShortcutContext(Qt.WidgetWithChildrenShortcut); self.act_find_prev.triggered.connect(self.find_prev)
        self.act_replace_next = QAction("Replace Next", self); self.act_replace_next.triggered.connect(self.replace_next)
        self.act_replace_all  = QAction("Replace All",  self); self.act_replace_all.triggered.connect(self.replace_all)
        self.act_find_all     = QAction("Find All in Current File", self); self.act_find_all.triggered.connect(self.find_all)
        self.act_find_all_files = QAction("Find All in All Files", self); self.act_find_all_files.triggered.connect(self.find_all_files)
        self.act_replace_all_files = QAction("Replace All in All Files", self); self.act_replace_all_files.triggered.connect(self.replace_all_files)
        for act in [self.act_find, self.act_find_next, self.act_find_prev, self.act_replace, self.act_replace_next, self.act_replace_all]:
            search_menu.addAction(act)
        search_menu.addSeparator()
        for act in [self.act_find_all, self.act_find_all_files, self.act_replace_all_files]:
            search_menu.addAction(act)
        self.addAction(self.act_find); self.addAction(self.act_replace)
        self.addAction(self.act_find_next); self.addAction(self.act_find_prev)

        self.view_menu.addAction(self.dock_files.toggleViewAction())
        self.view_menu.addAction(self.dock_console.toggleViewAction())
        self.view_menu.addAction(self.dock_messages.toggleViewAction())
        self.act_toggle_search = QAction("Search Bar", self, checkable=True)
        self.act_toggle_search.setChecked(False)
        self.act_toggle_search.setShortcut(QKeySequence("Ctrl+F"))
        self.act_toggle_search.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.act_toggle_search.triggered.connect(self._toggle_search_bar)
        self.view_menu.addAction(self.act_toggle_search)
        self.view_menu.addSeparator()
        self.act_whitespace   = QAction("Show Whitespace",    self, checkable=True); self.act_whitespace.setChecked(self.config["show_whitespace"]); self.act_whitespace.triggered.connect(self.toggle_whitespace)
        self.act_eol          = QAction("Show End of Line",   self, checkable=True); self.act_eol.setChecked(self.config["show_eol"]);               self.act_eol.triggered.connect(self.toggle_eol)
        self.act_indent       = QAction("Show Indent Guides", self, checkable=True); self.act_indent.setChecked(self.config["show_indent_guides"]);   self.act_indent.triggered.connect(self.toggle_indent_guides)
        self.act_line_numbers = QAction("Show Line Numbers",  self, checkable=True); self.act_line_numbers.setChecked(self.config["show_line_numbers"]); self.act_line_numbers.triggered.connect(self.toggle_line_numbers)
        self.act_wrap         = QAction("Word Wrap",          self, checkable=True); self.act_wrap.setChecked(self.config["wrap"]);                   self.act_wrap.triggered.connect(self.toggle_wrap)
        self.act_zoom_in  = QAction("Zoom In",  self); self.act_zoom_in.setShortcut("Ctrl++"); self.act_zoom_in.triggered.connect(self.zoom_in)
        self.act_zoom_out = QAction("Zoom Out", self); self.act_zoom_out.setShortcut("Ctrl+-"); self.act_zoom_out.triggered.connect(self.zoom_out)
        # Float toggle (detach to floating window).
        self.act_float = QAction("Floating Mode", self, checkable=True)
        self.act_float.setToolTip("Toggle floating window mode")
        self.act_float.triggered.connect(self._on_float_action_triggered)
        for act in [self.act_whitespace, self.act_eol, self.act_indent, self.act_line_numbers,
                    self.act_wrap, self.act_zoom_in, self.act_zoom_out]:
            self.view_menu.addAction(act)

        reopen_menu  = encoding_menu.addMenu("Reopen with Encoding")
        convert_menu = encoding_menu.addMenu("Convert to Encoding")
        eol_menu     = encoding_menu.addMenu("EOL Conversion")
        self._encoding_actions = {}
        for label in ["UTF-8", "UTF-8 BOM", "ANSI / System", "UTF-16 LE", "UTF-16 BE"]:
            act_r = QAction(label, self, triggered=lambda _=False, x=label: self.reopen_with_encoding(x))
            act_c = QAction(label, self, triggered=lambda _=False, x=label: self.convert_encoding(x))
            reopen_menu.addAction(act_r)
            convert_menu.addAction(act_c)
            self._encoding_actions[label] = (act_r, act_c)
        for label in ["Windows (CRLF)", "Unix (LF)"]:
            eol_menu.addAction(QAction(label, self, triggered=lambda _=False, x=label: self.convert_eol(x)))

        self.rebuild_language_menu()

        self.act_run          = QAction("Run Internal",  self); self.act_run.setShortcut("F5");          self.act_run.triggered.connect(self.run_current)
        self.act_run_external = QAction("Run External",  self); self.act_run_external.setShortcut("F6"); self.act_run_external.triggered.connect(self.run_external)
        self.act_stop         = QAction("Stop Script",   self); self.act_stop.triggered.connect(self.stop_process)
        run_menu.addAction(self.act_run); run_menu.addAction(self.act_run_external); run_menu.addSeparator(); run_menu.addAction(self.act_stop)

        self.act_prefs          = QAction("Preferences...",              self); self.act_prefs.triggered.connect(self.open_settings)
        self.act_shortcuts      = QAction("Editor Shortcuts...",           self); self.act_shortcuts.triggered.connect(self.open_shortcuts)
        self.act_qgis_shortcuts = QAction("QGIS Shortcuts...",             self); self.act_qgis_shortcuts.triggered.connect(self.open_qgis_shortcuts)
        settings_menu.addAction(self.act_prefs)
        settings_menu.addAction(self.act_shortcuts)
        settings_menu.addAction(self.act_qgis_shortcuts)

        help_menu.addAction(QAction("About QFAT04 CodePad--", self, triggered=self.open_about))
        return mb

    def _build_toolbar(self):
        self.main_toolbar = QToolBar("Main Toolbar", self.inner_window)
        self.main_toolbar.setObjectName("QFAT04_MainToolbar")
        self.main_toolbar.setStyleSheet("""
            QToolBar { border:none; spacing:3px; padding:3px; }
            QToolButton { padding:5px 10px; border-radius:4px; border:1px solid transparent; background:transparent; }
            QToolButton:hover { background:rgba(128,128,128,0.15); border:1px solid rgba(128,128,128,0.3); }
            QToolButton:pressed { background:rgba(128,128,128,0.25); }
            QToolButton:disabled { color:rgba(128,128,128,0.5); }
        """)
        self.inner_window.addToolBar(Qt.TopToolBarArea, self.main_toolbar)
        self.toolbar_action_map = {
            "open": self.act_open, "save": self.act_save,
            "save_as": self.act_save_as, "save_all": self.act_save_all,
            "reload": self.act_reload, "print": self.act_print,
            "new": self.act_new, "close": self.act_close,
            "run":  self.act_run,  "run_external": self.act_run_external, "stop": self.act_stop,
            "undo": self.act_undo, "redo": self.act_redo,
            "cut": self.act_cut, "copy": self.act_copy, "paste": self.act_paste,
            "find": self.act_find, "replace": self.act_replace,
            "prefs": self.act_prefs, "shortcuts": self.act_shortcuts,
            "zoom_in": self.act_zoom_in, "zoom_out": self.act_zoom_out,
            "float": self.act_float,
        }
        self._build_pin_button()
        self._refresh_toolbar()
        if self.view_menu.actions():
            first = self.view_menu.actions()[0]
            self.view_menu.insertAction(first, self.main_toolbar.toggleViewAction())
            self.view_menu.insertSeparator(first)

    def _refresh_toolbar(self):
        self.main_toolbar.clear()
        for key in self.config.get("toolbar_items", []):
            if key in self.toolbar_action_map:
                self.main_toolbar.addAction(self.toolbar_action_map[key])
        # Re-attach pin action (clear() removes it)
        if hasattr(self, "act_pin"):
            self.main_toolbar.addSeparator()
            self.main_toolbar.addAction(self.act_pin)
            self._sync_float_ui()

    def _build_pin_button(self):
        # Pin (always-on-top) action. Visible only when in floating window mode.
        self.act_pin = QAction("Stay on top", self)
        self.act_pin.setCheckable(True)
        self.act_pin.setToolTip("Always on top")
        _on_top = QSettings().value("QFAT/QFAT04/always_on_top", False, type=bool)
        self.act_pin.setChecked(_on_top)
        self.act_pin.toggled.connect(self._on_pin_toggled)
        self.act_pin.setVisible(False)

    def _on_float_action_triggered(self, checked):
        """User clicked the toolbar float button — detach or reattach."""
        if checked:
            self.detach_to_window()
        else:
            self.reattach_to_dock()

    def _on_pin_toggled(self, checked):
        QSettings().setValue("QFAT/QFAT04/always_on_top", bool(checked))
        self._update_pin_style(checked)
        if hasattr(self, '_floating_window') and self._floating_window is not None:
            self._floating_window.set_always_on_top(bool(checked))

    def _update_pin_style(self, on):
        if not hasattr(self, 'act_pin'):
            return
        try:
            w = self.main_toolbar.widgetForAction(self.act_pin)
            if w is not None:
                if on:
                    w.setStyleSheet("QToolButton { color: #e74c3c; font-weight: bold; }")
                else:
                    w.setStyleSheet("QToolButton { color: grey; }")
        except Exception:
            pass

    def _apply_always_on_top(self, enabled):
        if hasattr(self, '_floating_window') and self._floating_window is not None:
            self._floating_window.set_always_on_top(enabled)

    def _apply_floating_flags(self):
        # Called on startup restore — just detach
        self.detach_to_window()

    def _sync_float_ui(self):
        floating = self.is_floating_window()
        if hasattr(self, "act_float"):
            self.act_float.blockSignals(True)
            self.act_float.setChecked(floating)
            self.act_float.blockSignals(False)
        if hasattr(self, "act_pin"):
            self.act_pin.setVisible(floating)
            self.act_pin.setEnabled(floating)
            if floating:
                QTimer.singleShot(0, lambda: self._update_pin_style(self.act_pin.isChecked()))

    def is_floating_window(self):
        return hasattr(self, '_floating_window') and self._floating_window is not None and self._floating_window.isVisible()

    def detach_to_window(self):
        """Move inner_window into a standalone CodePadFloatingWindow."""
        if self.is_floating_window():
            return
        # Save inner_window reference
        inner = self.inner_window
        # Remove from dock (setWidget(None) doesn't work well, use placeholder)
        placeholder = QWidget()
        self.setWidget(placeholder)
        self.hide()
        # Create floating window
        self._floating_window = CodePadFloatingWindow(self, inner)
        # Restore geometry
        geom = QSettings().value("QFAT/QFAT04/floating_geometry", None)
        if geom is not None:
            try:
                self._floating_window.restoreGeometry(geom)
            except Exception:
                self._floating_window.resize(900, 700)
        else:
            self._floating_window.resize(900, 700)
        # Apply always-on-top
        on_top = QSettings().value("QFAT/QFAT04/always_on_top", False, type=bool)
        if on_top:
            self._floating_window.set_always_on_top(True)
        self._floating_window.show()
        QSettings().setValue("QFAT/QFAT04/display_mode", "floating")
        self._refresh_toolbar()
        self._sync_float_ui()

    def reattach_to_dock(self):
        """Move inner_window back into the dock widget."""
        if not hasattr(self, '_floating_window') or self._floating_window is None:
            return
        # Save geometry before closing
        try:
            QSettings().setValue("QFAT/QFAT04/floating_geometry", self._floating_window.saveGeometry())
        except Exception:
            pass
        inner = self.inner_window
        # Take inner_window back from floating window
        self._floating_window._closing_to_dock = True
        inner.setParent(None)
        self.setWidget(inner)
        self._floating_window.close()
        self._floating_window.deleteLater()
        self._floating_window = None
        self.show()
        self.raise_()
        self.activateWindow()
        QSettings().setValue("QFAT/QFAT04/display_mode", "docked")
        self._refresh_toolbar()
        self._sync_float_ui()

    def _build_statusbar(self):
        self.status_bar = QStatusBar()
        self.inner_window.setStatusBar(self.status_bar)
        self.lbl_path    = QLabel("Path: -")
        self.lbl_lang    = QLabel("Language: Plain Text")
        self.lbl_enc     = QLabel("Encoding: UTF-8")
        self.lbl_eol     = QLabel("EOL: CRLF")
        self.lbl_cursor  = QLabel("Ln 1, Col 1")
        self.lbl_zoom    = QLabel("Zoom: 0")
        self.lbl_backend = QLabel("Backend: Unknown")
        self.lbl_status  = QLabel("Idle")
        for w in [self.lbl_path, self.lbl_lang, self.lbl_enc, self.lbl_eol,
                  self.lbl_cursor, self.lbl_zoom, self.lbl_backend, self.lbl_status]:
            w.setMinimumWidth(1)
            self.status_bar.addWidget(w)

    def _build_central(self):
        central = QWidget(); layout = QVBoxLayout(central); layout.setContentsMargins(4, 2, 4, 4)

        editor_host   = QWidget(); editor_layout = QVBoxLayout(editor_host); editor_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = DropTabWidget()
        self.tabs.set_tab_limits(
            self.config.get("tab_min_width", 60),
            self.config.get("tab_max_width", 180),
        )
        self.tabs.set_tab_font_size(self.config.get("tab_font_size", 8))
        self.tabs.set_show_close_button(self.config.get("show_tab_close", True))
        self.tabs.set_inflate_active(self.config.get("tab_inflate_active", False))
        self.tabs.filesDropped.connect(self.open_paths)
        self.tabs.contextRequested.connect(self._show_tab_menu)
        self.tabs.tabCloseRequested.connect(self.close_tab_at)
        self.tabs.currentChanged.connect(self._current_changed)
        self.tab_menu_btn = QPushButton("▼"); self.tab_menu_btn.setFlat(True)
        self.tab_menu_btn.setMaximumWidth(24); self.tab_menu_btn.setToolTip("List Open Tabs")
        self.tab_menu_btn.clicked.connect(self._show_tab_dropdown)
        self.tabs.setCornerWidget(self.tab_menu_btn, Qt.TopRightCorner)
        editor_layout.addWidget(self.tabs)
        layout.addWidget(editor_host, 1)
        return central

    def _show_tab_dropdown(self):
        menu = QMenu(self)
        for i in range(self.tabs.count()):
            act = menu.addAction(self.tabs.fullTabText(i))
            act.setCheckable(True); act.setChecked(i == self.tabs.currentIndex())
            act.triggered.connect(lambda checked, idx=i: self.tabs.setCurrentIndex(idx))
        menu.exec_(self.tab_menu_btn.mapToGlobal(self.tab_menu_btn.rect().bottomLeft()))

    def rebuild_language_menu(self):
        if not self.language_menu: return
        self.language_menu.clear()
        self.language_actions = {}
        act = QAction("Auto Detect", self)
        act.triggered.connect(lambda _=False: self.set_current_language("auto"))
        self.language_menu.addAction(act)
        self.language_actions["auto"] = act
        self.language_menu.addSeparator()

        # Use saved order
        saved_order = QSettings().value("QFAT/QFAT04/language_order", "", type=str)
        saved_order = [x for x in saved_order.split("|") if x] if saved_order else []
        all_keys = list(self.languages.keys())
        ordered_keys = []
        for k in saved_order:
            if k in all_keys:
                ordered_keys.append(k)
        for k in all_keys:
            if k not in ordered_keys:
                ordered_keys.append(k)

        for key in ordered_keys:
            lang = self.languages[key]
            title = lang.get("name", lang.get("default_name", key))
            act   = QAction(title, self)
            act.triggered.connect(lambda _=False, x=key: self.set_current_language(x))
            self.language_menu.addAction(act)
            self.language_actions[key] = act

        self.language_menu.addSeparator()
        self.language_menu.addAction(
            QAction("Language Manager...", self, triggered=self.open_language_manager)
        )
        self._update_language_menu_checks()

    def _update_language_menu_checks(self):
        for act in self.language_actions.values():
            act.setCheckable(False)
        if not hasattr(self, "tabs") or self.tabs is None:
            return
        page = self.current_page()
        current = page.language if page else None
        if current and current in self.language_actions:
            self.language_actions[current].setCheckable(True)
            self.language_actions[current].setChecked(True)

    def set_current_language(self, language_key):
        page = self.current_page()
        if not page:
            return
        if language_key == "auto":
            page.language = page.detect_language()
        else:
            page.language = language_key if language_key in self.languages else "text"
        page.apply_config(self.config)
        self._populate_outline(page)
        self._update_status()
        self.lbl_status.setText("Language: %s" % language_display_name(self.languages, page.language))
        self._update_language_menu_checks()

    def open_language_manager(self, select_key=None):
        dlg = LanguageManagerDialog(self.languages, self, dock=self)
        if select_key:
            dlg.select_key(select_key)
        if dlg.exec_():
            self._apply_language_changes(dlg.values())
            # Save language order
            order = dlg.get_language_order()
            QSettings().setValue("QFAT/QFAT04/language_order", "|".join(order))

    def edit_current_language(self):
        page = self.current_page()
        key  = (page.language if page and page.language in self.languages else "text")
        lang = copy.deepcopy(self.languages.get(key, self.languages.get("text", {})))
        dlg  = LanguageEditorDialog(key, lang, self,
                                    allow_delete=not lang.get("builtin", False))
        if dlg.exec_():
            if dlg.delete_requested and not lang.get("builtin", False):
                self.languages.pop(key, None)
                if page and page.language == key:
                    page.language = "text"
            else:
                import datetime
                new_key = dlg.language_key
                updated = dlg.values()
                updated["builtin"] = bool(lang.get("builtin", False) and new_key == key)
                updated["_last_modified"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                if new_key != key and not lang.get("builtin", False) and key in self.languages:
                    self.languages.pop(key, None)
                self.languages[new_key] = updated
                if page:
                    page.language = new_key
            self._apply_language_changes(self.languages)

    def _apply_language_changes(self, languages):
        self.languages = languages
        self.config["languages"] = self.languages
        save_config(self.config)
        self.rebuild_language_menu()
        for i in range(self.tabs.count()):
            p = self.tabs.widget(i)
            if getattr(p, "language", None) not in self.languages:
                p.language = p.detect_language()
            p.apply_config(self.config)
        self._update_status()

    def rebuild_addons_menu(self):
        if not hasattr(self, 'addons_menu'): return
        self.addons_menu.clear()
        menu_hooks = self.addon_manager.get_active_hooks("main_menu")
        for hook in menu_hooks:
            act = self.addons_menu.addAction(hook["name"])
            act.triggered.connect(lambda _=False, cb=hook["callback"]: cb(self))
        if menu_hooks:
            self.addons_menu.addSeparator()
        self.addons_menu.addAction("Manage Addons...", self.open_addon_manager)

    def open_addon_manager(self):
        try:
            old_enabled = set(self.config.get("enabled_addons", []))
            dlg = AddonManagerDialog(self.addon_manager, self.config, self)
            if dlg.exec_():
                new_enabled = dlg.get_enabled_addons()
                self.config["enabled_addons"] = new_enabled
                save_config(self.config)
                new_set = set(new_enabled)
                # Fire on_disable for addons that were enabled and are now disabled
                for aid in old_enabled - new_set:
                    self.addon_manager.fire_hook_for_addon("on_disable", aid)
                # Fire on_enable for addons that were disabled and are now enabled
                for aid in new_set - old_enabled:
                    self.addon_manager.fire_hook_for_addon("on_enable", aid)
                self.addon_manager.load_all(skip_core_check=True)
                self.rebuild_addons_menu()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Addon Manager", "Error opening Addon Manager:\n%s" % str(e))

    def current_page(self):
        return self.tabs.currentWidget() if hasattr(self, "tabs") and self.tabs else None

    def current_editor(self):
        page = self.current_page()
        return page.editor if page else None

    def _show_editor_context_menu(self, global_pos):
        menu = QMenu(self)
        builders = self.addon_manager.get_active_hooks("editor_context_builder")
        added_any = False
        for build_func in builders:
            if build_func(self, menu):
                added_any = True
        if added_any:
            menu.addSeparator()
            
        menu.addAction(self.act_undo)
        menu.addAction(self.act_redo)
        menu.addSeparator()
        menu.addAction(self.act_cut)
        menu.addAction(self.act_copy)
        menu.addAction(self.act_paste)
        menu.addSeparator()
        menu.addAction(self.act_toggle_comment)
        menu.addAction(self.act_duplicate_line)
        menu.addSeparator()
        menu.addAction(self.act_select_all)
        
        menu.exec_(global_pos)

    def _shortcut_text(self, key):
        return self.editor_shortcuts.get(key, DEFAULT_EDITOR_SHORTCUTS.get(key, ""))

    def _configure_editor_shortcut_action(self, action, key):
        action.setShortcut(QKeySequence(self._shortcut_text(key)))
        action.setShortcutContext(Qt.WidgetShortcut)

    def _apply_editor_shortcuts(self):
        if not hasattr(self, "editor_shortcut_actions"):
            return
        for key, action in self.editor_shortcut_actions.items():
            self._configure_editor_shortcut_action(action, key)

    def _attach_editor_shortcuts_to_page(self, page):
        if not page or not hasattr(self, "editor_shortcut_actions"):
            return
        editor   = page.editor
        attached = getattr(editor, "_qfat04_attached_shortcuts", set())
        for key, action in self.editor_shortcut_actions.items():
            if key not in attached:
                editor.addAction(action); attached.add(key)
        editor._qfat04_attached_shortcuts = attached
        if page.editor_kind == "scintilla":
            try:
                for key in self.editor_shortcut_actions:
                    sc = self._shortcut_text(key)
                    if not sc:
                        continue
                    parts = sc.split("+"); mod = 0; key_val = 0
                    for p in parts:
                        p = p.strip().upper()
                        if   p == "CTRL":  mod |= 2
                        elif p == "SHIFT": mod |= 1
                        elif p == "ALT":   mod |= 4
                        elif p == "META":  mod |= 16
                        else:
                            if len(p) == 1: key_val = ord(p)
                            elif p.startswith("F") and p[1:].isdigit(): key_val = 300 + (int(p[1:]) - 1)
                    if key_val > 0:
                        editor.SendScintilla(2071, key_val | (mod << 16))
            except Exception:
                pass

    def _editor_call(self, name, *args, **kwargs):
        editor = self.current_editor()
        if editor is None: return None
        fn = getattr(editor, name, None)
        if callable(fn): return fn(*args, **kwargs)
        return None

    def _register_addon_shortcuts(self):
        """Register shortcuts from addons via the 'shortcuts' hook.
        Detects conflicts with built-in and other addon shortcuts.
        User overrides from QSettings take precedence over addon defaults."""
        from qgis.PyQt.QtWidgets import QShortcut
        # Clean up any previously registered addon shortcuts to avoid duplicates
        for old in getattr(self, "_addon_shortcuts", []):
            try:
                sc = old.get("shortcut")
                if sc is not None:
                    sc.setParent(None)
                    sc.deleteLater()
            except Exception:
                pass
        self._addon_shortcuts = []  # list of {"key", "default_key", "name", "addon", "shortcut", "callback"}
        overrides = load_addon_shortcut_overrides()
        hooks = self.addon_manager.get_active_hooks("shortcuts")
        seen_keys = {}
        # Collect built-in shortcuts for conflict detection
        for key, seq_text in self.editor_shortcuts.items():
            if seq_text:
                norm = QKeySequence(seq_text).toString(QKeySequence.PortableText)
                if norm:
                    seen_keys[norm] = "Built-in: %s" % key
        for hook_data in hooks:
            if not isinstance(hook_data, list):
                hook_data = [hook_data]
            for entry in hook_data:
                if not isinstance(entry, dict):
                    continue
                default_key = entry.get("key", "")
                name = entry.get("name", "Unknown")
                callback = entry.get("callback")
                addon_name = entry.get("addon", "Addon")
                if not callable(callback):
                    continue
                override_id = "%s::%s" % (addon_name, name)
                key_seq = overrides.get(override_id, default_key)
                if not key_seq:
                    # still register entry (no binding) so user can assign one
                    self._addon_shortcuts.append({
                        "key": "", "default_key": default_key, "name": name,
                        "addon": addon_name, "shortcut": None, "callback": callback,
                    })
                    continue
                norm = QKeySequence(key_seq).toString(QKeySequence.PortableText)
                if norm in seen_keys:
                    print("QFAT04 AddonManager: Shortcut conflict — '%s' (%s) "
                          "conflicts with %s" % (key_seq, name, seen_keys[norm]))
                else:
                    seen_keys[norm] = "Addon: %s — %s" % (addon_name, name)
                sc = QShortcut(QKeySequence(key_seq), self.inner_window)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                dock_ref = self
                sc.activated.connect(lambda _cb=callback, _d=dock_ref: _cb(_d))
                self._addon_shortcuts.append({
                    "key": key_seq, "default_key": default_key, "name": name,
                    "addon": addon_name, "shortcut": sc, "callback": callback,
                })

    def _get_addon_shortcuts(self):
        """Return list of addon shortcut dicts for the Shortcuts Manager."""
        return getattr(self, "_addon_shortcuts", [])

    # ------------------------------------------------------------------
    # Scroll & Panel API (for addons)
    # ------------------------------------------------------------------
    def scroll_editor(self, line, center=False):
        """Scroll the active editor to a line number (1-based).
        If center=True, place the line in the middle of the viewport."""
        page = self.current_page()
        if not page:
            return
        editor = page.editor
        line0 = max(0, line - 1)
        if page.editor_kind == "scintilla":
            if center:
                visible = editor.SendScintilla(editor.SCI_LINESONSCREEN)
                first = max(0, line0 - visible // 2)
                editor.SendScintilla(editor.SCI_SETFIRSTVISIBLELINE, first)
            else:
                editor.ensureLineVisible(line0)
            editor.setCursorPosition(line0, 0)
        else:
            cursor = editor.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.NextBlock, cursor.MoveAnchor, line0)
            editor.setTextCursor(cursor)
            editor.ensureCursorVisible()

    def scroll_editor_h(self, col):
        """Scroll the active editor horizontally to a column offset."""
        page = self.current_page()
        if not page:
            return
        if page.editor_kind == "scintilla":
            page.editor.SendScintilla(page.editor.SCI_SETXOFFSET, col)

    def get_scroll_position(self):
        """Return (first_visible_line, h_offset) for the active editor."""
        page = self.current_page()
        if not page:
            return (0, 0)
        if page.editor_kind == "scintilla":
            line = page.editor.SendScintilla(page.editor.SCI_GETFIRSTVISIBLELINE)
            hoff = page.editor.SendScintilla(page.editor.SCI_GETXOFFSET)
            return (line, hoff)
        return (0, 0)

    def set_scroll_position(self, line, h_offset=0):
        """Restore scroll position for the active editor."""
        page = self.current_page()
        if not page:
            return
        if page.editor_kind == "scintilla":
            page.editor.SendScintilla(page.editor.SCI_SETFIRSTVISIBLELINE, line)
            page.editor.SendScintilla(page.editor.SCI_SETXOFFSET, h_offset)

    def get_panel(self, panel_id):
        """Return the QDockWidget for a panel by ID, or None."""
        return self.addon_manager._panels.get(panel_id)

    def get_panel_size(self, panel_id):
        """Return (width, height) of a panel by ID."""
        panel = self.get_panel(panel_id)
        if panel:
            return (panel.width(), panel.height())
        return (0, 0)

    def set_panel_size(self, panel_id, width=None, height=None):
        """Resize a panel by ID. Pass None to keep the current dimension."""
        panel = self.get_panel(panel_id)
        if not panel:
            return
        w = width if width is not None else panel.width()
        h = height if height is not None else panel.height()
        panel.resize(w, h)

    def edit_undo(self):       self._editor_call("undo")
    def edit_redo(self):       self._editor_call("redo")
    def edit_cut(self):        self._editor_call("cut")
    def edit_copy(self):       self._editor_call("copy")
    def edit_paste(self):      self._editor_call("paste")
    def edit_select_all(self): self._editor_call("selectAll")
    def trigger_find(self):
        self.dock_search.setVisible(True); self.dock_search.raise_()
        if hasattr(self, "act_toggle_search"): self.act_toggle_search.setChecked(True)
        if self.dock_search.isFloating():
            self.dock_search.activateWindow()
        # Auto-populate with selected text
        page = self.current_page()
        if page:
            sel = page.editor.selected_text() if hasattr(page.editor, 'selected_text') else ""
            if sel and "\n" not in sel:
                self.find_text.setText(sel)
        self.find_text.setFocus(); self.find_text.selectAll()
    def trigger_replace(self):
        self.dock_search.setVisible(True); self.dock_search.raise_()
        if hasattr(self, "act_toggle_search"): self.act_toggle_search.setChecked(True)
        if self.dock_search.isFloating():
            self.dock_search.activateWindow()
        # Auto-populate find field with selected text
        page = self.current_page()
        if page:
            sel = page.editor.selected_text() if hasattr(page.editor, 'selected_text') else ""
            if sel and "\n" not in sel:
                self.find_text.setText(sel)
        self.replace_text.setFocus(); self.replace_text.selectAll()

    def duplicate_line(self):
        page = self.current_page()
        if not page: return
        editor = page.editor; editor.setFocus()
        try:
            if page.editor_kind == "scintilla":
                if editor.hasSelectedText(): editor.SendScintilla(2469) 
                else:                        editor.SendScintilla(2404) 
            else:
                cursor = editor.textCursor()
                if cursor.hasSelection():
                    text = cursor.selectedText(); pos = cursor.selectionEnd()
                    cursor.setPosition(pos); cursor.insertText(text)
                else:
                    cursor.beginEditBlock()
                    cursor.movePosition(cursor.StartOfLine); cursor.movePosition(cursor.EndOfLine, cursor.KeepAnchor)
                    text = cursor.selectedText(); cursor.movePosition(cursor.EndOfLine)
                    cursor.insertText("\n" + text); cursor.endEditBlock()
        except Exception as e:
            self._append_console("Duplicate line error: %s\n" % e)

    def toggle_comment(self):
        page = self.current_page()
        if not page: return
        editor = page.editor; editor.setFocus()
        lang_def      = self.languages.get(page.language, {})
        prefixes      = lang_def.get("comment_prefixes", [])
        if not prefixes:
            # Tier 2 fallback — same defaults the highlighter uses
            base = lang_def.get("base", page.language)
            tier2_defaults = {
                "tuflow":     ["!", "#"],
                "powershell": ["#"],
                "batch":      ["REM", "::"],
                "python":     ["#"],
                "r":          ["#"],
                "sql":        ["--"],
                "html":       ["<!--"],
            }
            prefixes = tier2_defaults.get(base, ["!"])
        default_prefix = prefixes[0]  # used when adding a comment

        def _find_prefix(stripped_text):
            """Return (prefix, length) if line starts with any known prefix, else (None, 0)."""
            for pf in prefixes:
                if stripped_text.startswith(pf):
                    return pf, len(pf)
            return None, 0

        try:
            if page.editor_kind == "scintilla":
                orig_lf, orig_if, orig_lt, orig_it = editor.getSelection()
                has_sel = (orig_lf != -1)
                if not has_sel:
                    lf, i_from = editor.getCursorPosition(); lt = lf
                    orig_lf, orig_if, orig_lt, orig_it = lf, i_from, lf, i_from
                else:
                    lf = orig_lf; lt = orig_lt
                    if orig_it == 0 and orig_lt > orig_lf: lt -= 1
                sf = st = 0
                editor.beginUndoAction()
                for i in range(lf, lt + 1):
                    text = editor.text(i); stripped = text.lstrip()
                    if not stripped: continue
                    indent_len = len(text) - len(stripped)
                    found_pf, pf_len = _find_prefix(stripped)
                    if found_pf:
                        # Remove the detected prefix + optional trailing space
                        remove_len = pf_len
                        if len(stripped) > pf_len and stripped[pf_len] == " ":
                            remove_len += 1
                        editor.setSelection(i, indent_len, i, indent_len + remove_len)
                        editor.replaceSelectedText("")
                        if i == orig_lf and orig_if > indent_len: sf -= remove_len
                        if i == orig_lt and orig_it > indent_len: st -= remove_len
                    else:
                        # Add the default prefix + space
                        insert_text = default_prefix + " "
                        dp_len = len(insert_text)
                        editor.insertAt(insert_text, i, indent_len)
                        if i == orig_lf and orig_if >= indent_len: sf += dp_len
                        if i == orig_lt and orig_it >= indent_len: st += dp_len
                editor.endUndoAction()
                if has_sel:
                    editor.setSelection(orig_lf, max(0, orig_if + sf), orig_lt, max(0, orig_it + st))
                else:
                    editor.setCursorPosition(orig_lf, max(0, orig_if + sf))
            else:
                cursor = editor.textCursor(); has_sel = cursor.hasSelection()
                sp = cursor.selectionStart(); ep = cursor.selectionEnd()
                cursor.setPosition(sp); sb = cursor.blockNumber(); sc = cursor.columnNumber()
                cursor.setPosition(ep); eb = cursor.blockNumber(); ec = cursor.columnNumber()
                if eb > sb and ec == 0: eb -= 1
                ss = se = 0
                cursor.beginEditBlock()
                for i in range(sb, eb + 1):
                    cursor.movePosition(cursor.Start); cursor.movePosition(cursor.NextBlock, cursor.MoveAnchor, i)
                    cursor.movePosition(cursor.StartOfLine); cursor.movePosition(cursor.EndOfLine, cursor.KeepAnchor)
                    line_text = cursor.selectedText(); stripped = line_text.lstrip()
                    if not stripped: continue
                    indent_len = len(line_text) - len(stripped)
                    cursor.movePosition(cursor.StartOfLine); cursor.movePosition(cursor.Right, cursor.MoveAnchor, indent_len)
                    found_pf, pf_len = _find_prefix(stripped)
                    if found_pf:
                        remove_len = pf_len
                        if len(stripped) > pf_len and stripped[pf_len] == " ":
                            remove_len += 1
                        for _ in range(remove_len): cursor.deleteChar()
                        shift = -remove_len
                    else:
                        insert_text = default_prefix + " "
                        cursor.insertText(insert_text)
                        shift = len(insert_text)
                    if i == sb and sc > indent_len: ss += shift
                    if i == eb and ec > indent_len: se += shift
                    elif i < eb: se += shift
                cursor.endEditBlock()
                nc = editor.textCursor()
                if has_sel:
                    nc.setPosition(max(0, sp + ss)); nc.setPosition(max(0, ep + se), nc.KeepAnchor)
                else:
                    nc.setPosition(max(0, sp + ss))
                editor.setTextCursor(nc)
        except Exception as e:
            self._append_console("Toggle comment error: %s\n" % e)

    def _file_label(self, path): return os.path.basename(path) if path else "Untitled"

    def _index_of_path(self, path):
        norm = os.path.normcase(os.path.abspath(path))
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            if page.path and os.path.normcase(os.path.abspath(page.path)) == norm:
                return i
        return -1

    def new_tab(self, path=None):
        if path:
            existing = self._index_of_path(path)
            if existing >= 0:
                self.tabs.setCurrentIndex(existing)
                return self.tabs.widget(existing)
        page = EditorPage(self.config, path)
        page.editor.cursorInfoChanged.connect(self._update_cursor_label)
        page.stateChanged.connect(self._refresh_titles)
        page.editorContextMenuRequested.connect(self._show_editor_context_menu)
        page.filesDropped.connect(self.open_paths)
        self._attach_editor_shortcuts_to_page(page)
        page.editor.installEventFilter(self.editor_key_filter)
        if hasattr(page.editor, "viewport") and page.editor.viewport():
            page.editor.viewport().installEventFilter(self.editor_key_filter)
        idx = self.tabs.addTab(page, page.title())
        if path: self.tabs.setTabToolTip(idx, path)
        self.tabs.setCurrentIndex(idx)
        self._refresh_backend_label()
        self._populate_files_tree()
        self._populate_outline(page)
        self._install_global_drop_targets()
        return page

    def open_paths(self, paths):
        for path in paths:
            if os.path.isdir(path): continue
            if os.path.splitext(path)[1].lower() in TEXT_EXTS or os.path.isfile(path):
                page = self.new_tab(path)
                if path not in self.recent_files:
                    self.recent_files.insert(0, path)
                self.addon_manager.fire_hook("on_file_opened", page, path)
        self._refresh_titles()

    def _populate_files_tree(self):
        self.files_tree.clear()
        open_item = QTreeWidgetItem(self.files_tree, ["Open Tabs"])
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            item = QTreeWidgetItem(open_item, [self._file_label(page.path)])
            item.setData(0, Qt.UserRole, i)
            if page.path: item.setToolTip(0, page.path)
        recent_item = QTreeWidgetItem(self.files_tree, ["Recent Files"])
        for path in self.recent_files[:10]:
            item = QTreeWidgetItem(recent_item, [os.path.basename(path)])
            item.setData(0, Qt.UserRole + 1, path); item.setToolTip(0, path)
        self.files_tree.expandAll()

    def _populate_outline(self, page):
        """Stub — outline is now an addon (outline_panel.py)."""
        pass

    def _open_from_tree(self, item, _col):
        tab_idx = item.data(0, Qt.UserRole)
        if isinstance(tab_idx, int): self.tabs.setCurrentIndex(tab_idx); return
        path = item.data(0, Qt.UserRole + 1)
        if isinstance(path, str) and path: self.open_paths([path])

    def _show_tab_menu(self, idx, global_pos):
        if idx < 0: return
        self.tabs.setCurrentIndex(idx)
        menu = QMenu(self)
        menu.addAction("Save", self.save_current); menu.addAction("Save As...", self.save_current_as); menu.addAction("Reload from Disk", self.reload_current)
        menu.addAction("Rename File...", self._rename_current_file)
        menu.addAction("Show in Explorer", self.show_in_explorer_tab); menu.addSeparator()
        menu.addAction("Close", self.close_current_tab); menu.addAction("Close Others", self.close_other_tabs); menu.addAction("Close All to Right", self.close_tabs_to_right)
        menu.exec_(global_pos)

    def close_tab_at(self, idx):
        if idx < 0: return
        page = self.tabs.widget(idx)
        if page and page.is_modified():
            ans = QMessageBox.question(self, "Unsaved changes", "Save changes to %s?" % self._file_label(page.path),
                                       QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if ans == QMessageBox.Cancel: return
            if ans == QMessageBox.Yes: self.tabs.setCurrentIndex(idx); self.save_current()
        self.tabs.removeTab(idx)
        if self.tabs.count() == 0: self.new_tab()
        self._refresh_titles()

    def close_current_tab(self): self.close_tab_at(self.tabs.currentIndex())

    def _panel_context(self, widget, pos):
        """Right-click context menu for Console/Messages/Find Results panels."""
        menu = widget.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Clear", widget.clear)
        menu.exec_(widget.mapToGlobal(pos))

    def _rename_current_file(self):
        """Rename the file on disk for the current tab."""
        page = self.current_page()
        if not page or not page.path or not os.path.exists(page.path):
            QMessageBox.information(self, "Rename File", "File is not saved or does not exist.")
            return
        old_path = page.path
        old_name = os.path.basename(old_path)
        old_dir = os.path.dirname(old_path)
        new_name, ok = QInputDialog.getText(self, "Rename File", "New filename:", text=old_name)
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        new_path = os.path.join(old_dir, new_name.strip())
        if os.path.exists(new_path):
            QMessageBox.warning(self, "Rename File", "A file with that name already exists.")
            return
        try:
            os.rename(old_path, new_path)
            page.path = new_path
            page.editor.path = new_path if hasattr(page.editor, "path") else None
            self._refresh_titles()
            self._update_status()
            # Re-detect language based on new extension
            new_lang = page.detect_language()
            if new_lang != page.language:
                page.set_language_profile(new_lang)
        except Exception as e:
            QMessageBox.warning(self, "Rename File", "Failed to rename:\n%s" % str(e))
    def close_other_tabs(self):
        current = self.tabs.currentIndex()
        for idx in reversed(range(self.tabs.count())):
            if idx != current: self.close_tab_at(idx)
    def close_tabs_to_right(self):
        current = self.tabs.currentIndex()
        for idx in reversed(range(current + 1, self.tabs.count())): self.close_tab_at(idx)

    def _current_changed(self, _idx):
        page = self.current_page()
        self._refresh_backend_label(); self._populate_files_tree(); self._populate_outline(page)
        self._update_status(); self._update_language_menu_checks()
        if page: self.act_save.setEnabled(page.is_modified())
        self.addon_manager.fire_hook("on_tab_changed", page)

    def _refresh_backend_label(self):
        page = self.current_page()
        if page: self.lbl_backend.setText("Backend: %s" % ("QScintilla" if page.editor_kind == "scintilla" else "Plain"))

    def _refresh_titles(self, *_args):
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            self.tabs.setTabText(i, page.title()); self.tabs.setTabToolTip(i, page.path or "Untitled")
        self._refresh_backend_label(); self._update_status()
        page = self.current_page()
        if page: self.act_save.setEnabled(page.is_modified())

    def _append_console(self, text):
        if not text: return
        self.console.moveCursor(self.console.textCursor().End)
        self.console.insertPlainText(text)
        self.console.moveCursor(self.console.textCursor().End)

    def _update_cursor_label(self, line, col):
        self.lbl_cursor.setText("Ln %d, Col %d" % (line, col))

    def _update_status(self):
        page = self.current_page()
        if page is None: return
        self.lbl_path.setText("Path: %s" % (page.path or "Untitled"))
        self.lbl_lang.setText("Language: %s" % language_display_name(self.languages, page.language))
        self.lbl_enc.setText("Encoding: %s" % page.encoding)
        self.lbl_eol.setText("EOL: %s"       % page.eol)
        self.lbl_zoom.setText("Zoom: %s"     % self.config.get("zoom", 0))
        # Bold current encoding in menus
        current_enc = getattr(page, "encoding", "UTF-8")
        for label, (act_r, act_c) in self._encoding_actions.items():
            is_current = (label == current_enc)
            font = act_r.font()
            font.setBold(is_current)
            act_r.setFont(font)
            act_c.setFont(font)

    def _refresh_recent_menu(self):
        if not hasattr(self, "recent_menu"): return
        self.recent_menu.clear()
        seen = []; [seen.append(p) for p in self.recent_files if p and p not in seen]
        self.recent_files = seen[:15]
        if not self.recent_files:
            act = QAction("(Empty)", self); act.setEnabled(False); self.recent_menu.addAction(act)
        else:
            for path in self.recent_files:
                self.recent_menu.addAction(QAction(os.path.basename(path), self, triggered=lambda _=False, x=path: self.open_paths([x])))
            self.recent_menu.addSeparator()
            self.recent_menu.addAction(QAction("Clear Recent Files", self, triggered=self.clear_recent_files))

    def clear_recent_files(self):
        self.recent_files = []; self._refresh_recent_menu()

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open file", "", "Text files (*.*)")
        if path:
            self.open_paths([path])
            if path not in self.recent_files: self.recent_files.insert(0, path)
            self._refresh_recent_menu(); self.lbl_status.setText("Opened")

    def save_current(self):
        page = self.current_page()
        if page is None: return
        if not page.path:
            path, _ = QFileDialog.getSaveFileName(self, "Save file", "", "Text files (*.*)")
            if not path: return
            page.path = path
            page.language = "auto"
            page.apply_config(self.config)
            self._update_status()
            self._update_language_menu_checks()
        try:
            page.save(); self.lbl_status.setText("Saved"); self._refresh_titles()
            self.addon_manager.fire_hook("on_file_saved", page, page.path)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def save_current_as(self):
        page = self.current_page()
        if page is None: return
        path, _ = QFileDialog.getSaveFileName(self, "Save file as", page.path or "", "Text files (*.*)")
        if not path: return
        page.path = path; 
        page.language = "auto"
        page.apply_config(self.config)
        self._update_status()
        self._update_language_menu_checks()
        self.save_current()

    def save_all(self):
        for i in range(self.tabs.count()):
            self.tabs.setCurrentIndex(i)
            page = self.tabs.widget(i)
            if page and page.is_modified(): self.save_current()
        self.lbl_status.setText("Saved all")

    def reload_current(self):
        page = self.current_page()
        if page is None or not page.path: return
        try:
            page.load_from_path(page.path); self.lbl_status.setText("Reloaded"); self._refresh_titles()
        except Exception as e:
            QMessageBox.critical(self, "Reload failed", str(e))

    def print_current(self):
        PlaceholderDialog("Print", "Print UI placeholder in this build.", self).exec_()

    def reopen_with_encoding(self, encoding_name):
        page = self.current_page()
        if not page or not page.path: return
        page.encoding = encoding_name; self.lbl_status.setText("Reopen with Encoding: %s" % encoding_name); self._update_status()

    def convert_encoding(self, encoding_name):
        page = self.current_page()
        if not page: return
        page.encoding = encoding_name; self.lbl_status.setText("Convert Encoding: %s" % encoding_name); self._update_status()

    def convert_eol(self, eol_name):
        page = self.current_page()
        if not page: return
        page.eol = "CRLF" if "CRLF" in eol_name else "LF"; self.lbl_status.setText("EOL: %s" % page.eol); self._update_status()

    def _toggle_flag(self, key, action=None):
        self.config[key] = not self.config[key]; save_config(self.config)
        if action: action.setChecked(self.config[key])
        for i in range(self.tabs.count()): self.tabs.widget(i).apply_config(self.config)

    def toggle_whitespace(self):    self._toggle_flag("show_whitespace",    self.act_whitespace)
    def toggle_eol(self):           self._toggle_flag("show_eol",           self.act_eol)
    def toggle_indent_guides(self): self._toggle_flag("show_indent_guides", self.act_indent)
    def toggle_line_numbers(self):  self._toggle_flag("show_line_numbers",  self.act_line_numbers)
    def toggle_wrap(self):          self._toggle_flag("wrap",               self.act_wrap)

    def zoom_in(self):
        self.config["zoom"] = min(self.config.get("zoom", 0) + 1, 20); save_config(self.config)
        for i in range(self.tabs.count()): self.tabs.widget(i).apply_config(self.config)
        self._update_status()

    def zoom_out(self):
        self.config["zoom"] = max(self.config.get("zoom", 0) - 1, -8); save_config(self.config)
        for i in range(self.tabs.count()): self.tabs.widget(i).apply_config(self.config)
        self._update_status()

    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec_():
            # Preserve fields not managed by SettingsDialog
            preserved_addons = self.config.get("enabled_addons", [])
            preserved_languages = self.config.get("languages", {})
            self.config = dlg.values()
            self.config["enabled_addons"] = preserved_addons
            if "languages" not in self.config:
                self.config["languages"] = preserved_languages
            save_config(self.config)
            self.act_whitespace.setChecked(self.config["show_whitespace"])
            self.act_eol.setChecked(self.config["show_eol"])
            self.act_indent.setChecked(self.config["show_indent_guides"])
            self.act_line_numbers.setChecked(self.config["show_line_numbers"])
            self.act_wrap.setChecked(self.config["wrap"])
            for i in range(self.tabs.count()): self.tabs.widget(i).apply_config(self.config)
            self.tabs.set_tab_limits(
                self.config.get("tab_min_width", 60),
                self.config.get("tab_max_width", 180),
            )
            self.tabs.set_tab_font_size(self.config.get("tab_font_size", 8))
            self.tabs.set_show_close_button(self.config.get("show_tab_close", True))
            self.tabs.set_inflate_active(self.config.get("tab_inflate_active", False))
            self._refresh_toolbar(); self.lbl_status.setText("Settings applied"); self._refresh_titles()

    def open_shortcuts(self):
        dlg = ShortcutsDialog(self)
        if dlg.exec_() == QDialog.Accepted and dlg.was_accepted():
            self.editor_shortcuts = dict(dlg.shortcuts)
            save_editor_shortcuts(self.editor_shortcuts)
            self._apply_editor_shortcuts()
            for i in range(self.tabs.count()):
                self._attach_editor_shortcuts_to_page(self.tabs.widget(i))
            # Persist addon shortcut overrides (only deltas vs defaults) and re-register
            if hasattr(dlg, "addon_overrides"):
                deltas = {}
                defaults = {
                    "%s::%s" % (a.get("addon",""), a.get("name","")): a.get("default_key","")
                    for a in self._get_addon_shortcuts()
                }
                for oid, seq in dlg.addon_overrides.items():
                    if seq != defaults.get(oid, ""):
                        deltas[oid] = seq
                save_addon_shortcut_overrides(deltas)
                if hasattr(self, "_register_addon_shortcuts"):
                    self._register_addon_shortcuts()

    def open_qgis_shortcuts(self):
        PlaceholderDialog("QGIS Shortcuts",
                          "Use the QGIS Keyboard Shortcuts Manager for application-level shortcuts.", self).exec_()

    def open_about(self):
        plugin_dir = os.path.dirname(__file__)
        # Read version from metadata.txt (single source of truth)
        version = ""
        try:
            meta_path = os.path.join(plugin_dir, "metadata.txt")
            with open(meta_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("version="):
                        version = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
        about_path = os.path.join(plugin_dir, "about.txt")
        try:
            with open(about_path, "r", encoding="utf-8") as f:
                about_text = f.read()
        except Exception:
            about_text = "QFAT04 CodePad--\n\nCould not load about.txt"
        if version:
            # Inject version into first line
            lines = about_text.split("\n", 1)
            lines[0] = lines[0].rstrip() + " v" + version
            about_text = "\n".join(lines)
        PlaceholderDialog("About QFAT04 CodePad--", about_text, self).exec_()

    def _toggle_search_bar(self, checked=None):
        """Show/hide the search dock. Ctrl+F shows and focuses it."""
        if checked is None:
            checked = not self.dock_search.isVisible()
        self.dock_search.setVisible(checked)
        if hasattr(self, "act_toggle_search"):
            self.act_toggle_search.setChecked(checked)
        if checked:
            self.dock_search.raise_()
            self.find_text.setFocus()
            self.find_text.selectAll()
        else:
            # Hide inline results when search bar closes
            if hasattr(self, "inline_find_results"):
                self.inline_find_results.hide()
            self._clear_flash()

    def _show_inline_results(self):
        """Show the inline find results tree below the search bar and resize dock."""
        self.inline_find_results.show()
        self.dock_search.setVisible(True)
        self.dock_search.raise_()
        cur = self.dock_search.size()
        if cur.height() < 300:
            self.dock_search.resize(max(cur.width(), 700), 350)

    def _clear_find_results(self):
        """Clear all results from the inline tree."""
        self.inline_find_results.clear()
        self.lbl_status.setText("Results cleared")

    def find_prev(self):
        page = self.current_page()
        if page is None: return
        text = self.find_text.text().strip()
        if not text: return
        ok = page.editor.find_prev(text, self.chk_regex.isChecked())
        if not ok and page.editor_kind == "plain":
            cursor = page.editor.textCursor()
            cursor.movePosition(cursor.End)
            page.editor.setTextCursor(cursor)
            ok = page.editor.find_prev(text, self.chk_regex.isChecked())
        tab_idx = self.tabs.currentIndex()
        label = self._file_label(page.path)
        if ok and self.is_scintilla(page):
            # getSelection returns actual match start
            sel_l1, sel_c1, sel_l2, sel_c2 = page.editor.getSelection()
            line, col = (sel_l1, sel_c1) if sel_l1 >= 0 else page.editor.getCursorPosition()
            line_text = (page.editor.text(line) or "").strip()
            if len(line_text) > 120: line_text = line_text[:120] + "..."
            item = QTreeWidgetItem(self.inline_find_results,
                ["%s: %s" % (label, line_text), str(line + 1), str(col + 1)])
            item.setData(0, Qt.UserRole, (tab_idx, line + 1, col + 1, len(text)))
            self.inline_find_results.scrollToItem(item)
            if not self.inline_find_results.isVisible():
                self._show_inline_results()
            self._flash_scintilla(page.editor, line, col, len(text))
            self.lbl_status.setText("Found: Ln %d, Col %d" % (line + 1, col + 1))
        else:
            from qgis.PyQt.QtGui import QColor
            item = QTreeWidgetItem(self.inline_find_results,
                ["%s: \"%s\" — not found" % (label, text), "", ""])
            item.setForeground(0, QColor("#e74c3c"))
            self.inline_find_results.scrollToItem(item)
            if not self.inline_find_results.isVisible():
                self._show_inline_results()
            self.lbl_status.setText("Not found: %s" % text)

    def run_external(self):
        """Launch the script in an external OS terminal window."""
        from .qfat04_config import get_run_exts
        page = self.current_page()
        if page is None or not page.path:
            QMessageBox.information(self, "Run External", "Save the script first."); return
        ext = os.path.splitext(page.path)[1].lower()
        run_exts = get_run_exts()
        if ext not in run_exts:
            QMessageBox.information(self, "Run External",
                "Extension '%s' is not configured as runnable.\nRunnable: %s" % (ext, " ".join(sorted(run_exts)))); return
        if page.is_modified(): self.save_current()
        import subprocess, platform, shutil
        path  = page.path
        work  = os.path.dirname(path)
        plat  = platform.system()
        try:
            if plat == "Windows":
                if ext == ".ps1":
                    from .qfat04_runners import _resolve_powershell
                    ps = _resolve_powershell()
                    subprocess.Popen(
                        [ps, "-NoExit", "-ExecutionPolicy", "Bypass", "-File", path],
                        creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=work)
                elif ext in {".py", ".pyw"}:
                    python = shutil.which("python3") or shutil.which("python") or "python"
                    subprocess.Popen(
                        [python, path],
                        creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=work)
                elif ext in {".r"}:
                    rscript = shutil.which("Rscript") or "Rscript"
                    subprocess.Popen(
                        [rscript, "--vanilla", path],
                        creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=work)
                else:
                    subprocess.Popen(
                        ["cmd.exe", "/k", path],
                        creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=work)
            elif plat == "Darwin":
                script = "cd %s && %s; exec bash" % (
                    work.replace('"', '\"'), path.replace('"', '\"'))
                subprocess.Popen(["open", "-a", "Terminal", "--args", "bash", "-c", script])
            else:
                for term in ["x-terminal-emulator", "gnome-terminal", "xterm"]:
                    try:
                        subprocess.Popen([term, "--", "bash", "-c",
                                          "cd %s && %s; read -p 'Press enter...'" % (work, path)])
                        break
                    except FileNotFoundError:
                        continue
            self.lbl_status.setText("Launched in external terminal")
        except Exception as e:
            QMessageBox.warning(self, "Run External", "Failed to launch terminal:\n%s" % e)

    def find_next(self):
        page = self.current_page()
        if page is None: return
        text = self.find_text.text().strip()
        if not text: return
        ok = page.editor.find_next(text, self.chk_regex.isChecked())
        if not ok and page.editor_kind == "plain":
            cursor = page.editor.textCursor(); cursor.movePosition(cursor.Start)
            page.editor.setTextCursor(cursor); ok = page.editor.find_next(text, self.chk_regex.isChecked())
        tab_idx = self.tabs.currentIndex()
        label = self._file_label(page.path)
        if ok and self.is_scintilla(page):
            line, col = page.editor.getCursorPosition()
            # getCursorPosition returns END of selection — adjust to start
            sel_l1, sel_c1, sel_l2, sel_c2 = page.editor.getSelection()
            if sel_l1 >= 0:
                line, col = sel_l1, sel_c1
            line_text = (page.editor.text(line) or "").strip()
            if len(line_text) > 120: line_text = line_text[:120] + "..."
            item = QTreeWidgetItem(self.inline_find_results,
                ["%s: %s" % (label, line_text), str(line + 1), str(col + 1)])
            item.setData(0, Qt.UserRole, (tab_idx, line + 1, col + 1, len(text)))
            self.inline_find_results.scrollToItem(item)
            if not self.inline_find_results.isVisible():
                self._show_inline_results()
            self._flash_scintilla(page.editor, line, col, len(text))
            self.lbl_status.setText("Found: Ln %d, Col %d" % (line + 1, col + 1))
        else:
            from qgis.PyQt.QtGui import QColor
            item = QTreeWidgetItem(self.inline_find_results,
                ["%s: \"%s\" — not found" % (label, text), "", ""])
            item.setForeground(0, QColor("#e74c3c"))
            self.inline_find_results.scrollToItem(item)
            if not self.inline_find_results.isVisible():
                self._show_inline_results()
            self.lbl_status.setText("Not found: %s" % text)

    def replace_next(self):
        page = self.current_page()
        if page is None: return
        ft = self.find_text.text(); rt = self.replace_text.text()
        if not ft: return
        page.editor.replace_next(ft, rt); self.lbl_status.setText("Replace next"); self._refresh_titles()

    def replace_all(self):
        page = self.current_page()
        if page is None: return
        ft = self.find_text.text(); rt = self.replace_text.text()
        if not ft: return
        content = page.editor.editor_text()
        use_regex = self.chk_regex.isChecked()
        matches = self._find_all_in_text(content, ft, use_regex)
        label = self._file_label(page.path)
        tab_idx = self.tabs.currentIndex()
        count = page.editor.replace_all(ft, rt)
        self.inline_find_results.clear()
        lines = content.splitlines()
        parent = QTreeWidgetItem(self.inline_find_results,
            ["Replace All: \"%s\" → \"%s\" — %d in %s" % (ft, rt, count, label), "", ""])
        parent.setExpanded(True)
        from qgis.PyQt.QtGui import QFont as _QF
        f = parent.font(0); f.setBold(True); parent.setFont(0, f)
        for line_no, col, match_text in matches:
            line_preview = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
            if len(line_preview) > 120: line_preview = line_preview[:120] + "..."
            child = QTreeWidgetItem(parent, [line_preview, str(line_no), str(col)])
            child.setData(0, Qt.UserRole, (tab_idx, line_no, col, len(match_text)))
        self._show_inline_results()
        self.lbl_status.setText("Replace all: %d" % count); self._refresh_titles()

    def replace_all_files(self):
        """Replace all occurrences in all open files."""
        ft = self.find_text.text(); rt = self.replace_text.text()
        if not ft: return
        use_regex = self.chk_regex.isChecked()
        total = 0
        self.inline_find_results.clear()
        from qgis.PyQt.QtGui import QFont as _QF
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            if not hasattr(page, "editor"): continue
            content = page.editor.editor_text()
            matches = self._find_all_in_text(content, ft, use_regex)
            label = self._file_label(page.path)
            if not matches:
                parent = QTreeWidgetItem(self.inline_find_results, ["%s — 0 replacements" % label, "", ""])
                parent.setExpanded(False)
                continue
            count = page.editor.replace_all(ft, rt)
            parent = QTreeWidgetItem(self.inline_find_results, ["%s — %d replacement(s)" % (label, count), "", ""])
            f = parent.font(0); f.setBold(True); parent.setFont(0, f)
            parent.setExpanded(False)
            lines = content.splitlines()
            for line_no, col, match_text in matches:
                line_preview = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
                if len(line_preview) > 120: line_preview = line_preview[:120] + "..."
                child = QTreeWidgetItem(parent, [line_preview, str(line_no), str(col)])
                child.setData(0, Qt.UserRole, (i, line_no, col, len(match_text)))
            total += count
        summary = QTreeWidgetItem(self.inline_find_results, ["Total: %d replacement(s)" % total, "", ""])
        f = summary.font(0); f.setBold(True); summary.setFont(0, f)
        self._show_inline_results()
        self.lbl_status.setText("Replace All Files: %d" % total); self._refresh_titles()

    def find_all(self):
        """Find all occurrences in current file, output to inline results tree."""
        page = self.current_page()
        if page is None: return
        pattern = self.find_text.text()
        if not pattern: return
        content = page.editor.editor_text()
        use_regex = self.chk_regex.isChecked()
        matches = self._find_all_in_text(content, pattern, use_regex)
        tab_idx = self.tabs.currentIndex()
        label = self._file_label(page.path)
        self.inline_find_results.clear()
        from qgis.PyQt.QtGui import QFont as _QF
        parent = QTreeWidgetItem(self.inline_find_results,
            ["%s — \"%s\" — %d match(es)" % (label, pattern, len(matches)), "", ""])
        f = parent.font(0); f.setBold(True); parent.setFont(0, f)
        parent.setExpanded(True)
        lines = content.splitlines()
        for line_no, col, match_text in matches:
            line_preview = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
            if len(line_preview) > 120: line_preview = line_preview[:120] + "..."
            child = QTreeWidgetItem(parent, [line_preview, str(line_no), str(col)])
            child.setData(0, Qt.UserRole, (tab_idx, line_no, col, len(match_text)))
        self._show_inline_results()
        self.lbl_status.setText("Find All: %d match(es)" % len(matches))

    def find_all_files(self):
        """Find all occurrences in all open files, output to inline results tree."""
        pattern = self.find_text.text()
        if not pattern: return
        use_regex = self.chk_regex.isChecked()
        total = 0
        self.inline_find_results.clear()
        from qgis.PyQt.QtGui import QFont as _QF
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            if not hasattr(page, "editor"): continue
            content = page.editor.editor_text()
            matches = self._find_all_in_text(content, pattern, use_regex)
            label = self._file_label(page.path)
            parent = QTreeWidgetItem(self.inline_find_results,
                ["%s — %d match(es)" % (label, len(matches)), "", ""])
            f = parent.font(0); f.setBold(True); parent.setFont(0, f)
            parent.setExpanded(False)  # collapsed by default
            if matches:
                lines = content.splitlines()
                for line_no, col, match_text in matches:
                    line_preview = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
                    if len(line_preview) > 120: line_preview = line_preview[:120] + "..."
                    child = QTreeWidgetItem(parent, [line_preview, str(line_no), str(col)])
                    child.setData(0, Qt.UserRole, (i, line_no, col, len(match_text)))
            total += len(matches)
        summary = QTreeWidgetItem(self.inline_find_results,
            ["Total: %d match(es) across %d file(s)" % (total, self.tabs.count()), "", ""])
        f = summary.font(0); f.setBold(True); summary.setFont(0, f)
        self._show_inline_results()
        self.lbl_status.setText("Find All Files: %d match(es)" % total)

    def _on_result_item_clicked(self, item, column):
        """Navigate to file + line when double-clicking a result in the tree."""
        data = item.data(0, Qt.UserRole)
        if data is None:
            return  # clicked a group header, not a result
        try:
            tab_idx, line_no, col, length = data
            if 0 <= tab_idx < self.tabs.count():
                self.tabs.setCurrentIndex(tab_idx)
                page = self.tabs.widget(tab_idx)
                if hasattr(page, "editor"):
                    if page.editor_kind == "scintilla":
                        page.editor.setCursorPosition(line_no - 1, col - 1 if col > 0 else 0)
                        page.editor.ensureLineVisible(line_no - 1)
                        if length > 0:
                            page.editor.setSelection(line_no - 1, col - 1, line_no - 1, col - 1 + length)
                            self._flash_scintilla(page.editor, line_no - 1, col - 1, length)
                    else:
                        cursor = page.editor.textCursor()
                        block = page.editor.document().findBlockByLineNumber(line_no - 1)
                        if block.isValid():
                            pos = block.position() + (col - 1 if col > 0 else 0)
                            cursor.setPosition(pos)
                            if length > 0:
                                cursor.setPosition(pos + length, cursor.KeepAnchor)
                            page.editor.setTextCursor(cursor)
                            page.editor.ensureCursorVisible()
                            if length > 0:
                                self._flash_plain(page.editor, pos, length)
        except Exception:
            pass

    def _on_find_result_clicked(self, url):
        """Navigate to file + line when clicking a result link, flash-highlight the match."""
        href = url.toString()
        if not href.startswith("nav:"):
            return
        try:
            parts = href.replace("nav:", "").split(":")
            tab_idx = int(parts[0])
            line_no = int(parts[1])
            col = int(parts[2]) if len(parts) > 2 else 0
            length = int(parts[3]) if len(parts) > 3 else 0
            if 0 <= tab_idx < self.tabs.count():
                self.tabs.setCurrentIndex(tab_idx)
                page = self.tabs.widget(tab_idx)
                if hasattr(page, "editor"):
                    if page.editor_kind == "scintilla":
                        page.editor.setCursorPosition(line_no - 1, col - 1 if col > 0 else 0)
                        page.editor.ensureLineVisible(line_no - 1)
                        if length > 0:
                            # Select the match text
                            page.editor.setSelection(line_no - 1, col - 1, line_no - 1, col - 1 + length)
                            # Flash: use indicator for temporary highlight
                            self._flash_scintilla(page.editor, line_no - 1, col - 1, length)
                    else:
                        cursor = page.editor.textCursor()
                        block = page.editor.document().findBlockByLineNumber(line_no - 1)
                        if block.isValid():
                            pos = block.position() + (col - 1 if col > 0 else 0)
                            cursor.setPosition(pos)
                            if length > 0:
                                cursor.setPosition(pos + length, cursor.KeepAnchor)
                            page.editor.setTextCursor(cursor)
                            page.editor.ensureCursorVisible()
                            if length > 0:
                                self._flash_plain(page.editor, pos, length)
        except Exception:
            pass

    def _flash_plain(self, editor, pos, length):
        """Temporarily highlight a range in PlainTextEdit, clear after 1.5s."""
        from qgis.PyQt.QtGui import QTextCharFormat, QColor
        from qgis.PyQt.QtCore import QTimer
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#FFD700"))  # gold highlight
        cursor = editor.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + length, cursor.KeepAnchor)
        # Store extra selections
        sel = type(editor).ExtraSelection() if hasattr(type(editor), 'ExtraSelection') else None
        if sel is not None:
            sel.cursor = cursor
            sel.format = fmt
            old_extras = editor.extraSelections()
            editor.setExtraSelections(old_extras + [sel])
            QTimer.singleShot(1500, lambda: editor.setExtraSelections(
                [s for s in editor.extraSelections() if s is not sel]))
        else:
            # Fallback: just select it
            editor.setTextCursor(cursor)

    def _flash_scintilla(self, editor, line, col, length):
        """Highlight a range in QScintilla. Persists until next flash or _clear_flash."""
        # Clear previous flash
        self._clear_flash()
        INDIC_ID = 15
        editor.SendScintilla(editor.SCI_INDICSETSTYLE, INDIC_ID, 6)  # INDIC_FULLBOX
        editor.SendScintilla(editor.SCI_INDICSETFORE, INDIC_ID, 0x0000FF)  # red in BGR
        editor.SendScintilla(editor.SCI_INDICSETALPHA, INDIC_ID, 180)
        editor.SendScintilla(editor.SCI_INDICSETOUTLINEALPHA, INDIC_ID, 255)
        editor.SendScintilla(editor.SCI_INDICSETUNDER, INDIC_ID, 1)
        editor.SendScintilla(editor.SCI_SETINDICATORCURRENT, INDIC_ID)
        start_pos = editor.positionFromLineIndex(line, col)
        editor.SendScintilla(editor.SCI_INDICATORFILLRANGE, start_pos, length)
        self._flash_state = (editor, INDIC_ID, start_pos, length)

    def _clear_flash(self):
        """Clear previous flash highlight if any."""
        if hasattr(self, "_flash_state") and self._flash_state is not None:
            try:
                editor, indic_id, start_pos, length = self._flash_state
                editor.SendScintilla(editor.SCI_SETINDICATORCURRENT, indic_id)
                editor.SendScintilla(editor.SCI_INDICATORCLEARRANGE, start_pos, length)
            except Exception:
                pass
            self._flash_state = None

    def _find_all_in_text(self, content, pattern, use_regex):
        """Return list of (line_no, col, match_text) for all matches."""
        results = []
        try:
            if use_regex:
                for m in re.finditer(pattern, content):
                    pos = m.start()
                    line_no = content[:pos].count("\n") + 1
                    col = pos - content[:pos].rfind("\n")
                    results.append((line_no, col, m.group()))
            else:
                idx = 0
                lp = pattern.lower()
                lc = content.lower()
                while True:
                    idx = lc.find(lp, idx)
                    if idx < 0: break
                    line_no = content[:idx].count("\n") + 1
                    col = idx - content[:idx].rfind("\n")
                    results.append((line_no, col, content[idx:idx + len(pattern)]))
                    idx += 1
        except re.error:
            pass
        return results

    def run_current(self):
        from .qfat04_config import get_run_exts
        page = self.current_page()
        # Addon run_handler hook — returns True to claim the run entirely
        try:
            for hook in self.addon_manager.get_active_hooks("run_handler"):
                if callable(hook):
                    try:
                        if hook(self, page) is True:
                            return
                    except Exception as e:
                        print("QFAT04 run_handler error: %s" % e)
        except Exception:
            pass
        # Addon pre_run hook — return False to cancel
        try:
            for hook in self.addon_manager.get_active_hooks("pre_run"):
                if callable(hook):
                    try:
                        if hook(self, page) is False:
                            return
                    except Exception as e:
                        print("QFAT04 pre_run error: %s" % e)
        except Exception:
            pass
        if page is None or not page.path:
            QMessageBox.information(self, "Run", "Save the script first."); return
        ext = os.path.splitext(page.path)[1].lower()
        run_exts = get_run_exts()
        if ext not in run_exts:
            QMessageBox.information(self, "Run",
                "Extension '%s' is not configured as runnable.\nRunnable: %s" % (ext, " ".join(sorted(run_exts)))); return
        if page.is_modified(): self.save_current()

        # Python files: run in QGIS's built-in Python
        if ext in {".py", ".pyw"}:
            self._run_python_internal(page.path)
            return

        # Everything else: QProcess
        if self._runner.is_running():
            QMessageBox.information(self, "Run", "A process is already running."); return
        self.dock_console.show(); self.dock_console.raise_(); self.console.clear()
        try:
            program, args, work_dir = self._runner.start(
                page.path,
                on_stdout=self._append_console,
                on_stderr=self._append_console,
                on_finished=self._on_process_finished,
            )
        except ValueError as e:
            QMessageBox.information(self, "Run", str(e)); return
        self.lbl_status.setText("Running")
        self._append_console("Working directory: %s\nCommand: %s %s\n\n" % (work_dir, program, " ".join(args)))

    def _run_python_internal(self, path):
        """Run a Python file using QGIS's built-in Python interpreter."""
        import sys
        import traceback
        import io
        self.dock_console.show(); self.dock_console.raise_(); self.console.clear()
        work_dir = os.path.dirname(os.path.abspath(path))
        self._append_console("Running in QGIS Python: %s\nWorking directory: %s\n\n" % (path, work_dir))
        self.lbl_status.setText("Running (QGIS Python)")

        # Capture stdout/stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        old_cwd = os.getcwd()
        capture = io.StringIO()

        try:
            os.chdir(work_dir)
            sys.stdout = capture
            sys.stderr = capture

            # Build globals with useful references
            run_globals = {
                "__file__": path,
                "__name__": "__main__",
                "__builtins__": __builtins__,
                "iface": self.iface,
            }
            with open(path, "r", encoding="utf-8") as f:
                code = f.read()
            exec(compile(code, path, "exec"), run_globals)  # nosec B102 - intentional: user script execution (editor feature)

        except Exception:
            capture.write("\n" + traceback.format_exc())
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            os.chdir(old_cwd)

        output = capture.getvalue()
        if output:
            self._append_console(output)
        self._append_console("\n--- Finished ---\n")
        self.lbl_status.setText("Finished")

    def _on_process_finished(self, exit_code, exit_status):
        from qgis.PyQt.QtCore import QProcess as _QP
        status_text = "Finished" if exit_status == _QP.NormalExit else "Crashed"
        self._append_console("\nProcess ended: %s, exit code: %d\n" % (status_text, exit_code))
        self.lbl_status.setText(status_text)

    def stop_process(self):
        if self._runner.is_running():
            self._runner.stop(); self.lbl_status.setText("Stopped")
            self._append_console("\nProcess killed by user.\n")


    def show_in_explorer_tab(self):
        page = self.current_page()
        if page and page.path and os.path.exists(page.path):
            import subprocess, platform
            if platform.system() == "Windows":
                subprocess.run(['explorer', '/select,', os.path.normpath(page.path)])
            elif platform.system() == "Darwin":
                subprocess.run(['open', '-R', page.path])
            else:
                subprocess.run(['xdg-open', os.path.dirname(page.path)])
        else:
            QMessageBox.information(self, "Show in Explorer", "File is not saved or does not exist.")

    # =====================================================================
    # Addon Helper API  (v1.0.43+)
    # Safe to call from addons. Handle None pages, missing attrs, editor
    # kind differences gracefully. All page args accept EditorPage or None.
    # =====================================================================

    # ── 1-6: Language comment / definition ───────────────────────────────

    def get_comment_chars(self, page):
        """#1 → (line_prefixes:list, block_open:str, block_close:str)"""
        lang = self.get_language_def(page)
        return (lang.get("comment_prefixes", []),
                lang.get("block_comment_open", ""),
                lang.get("block_comment_close", ""))

    def get_language_def(self, page):
        """#2 → full language dict for the page's current language."""
        if not page: return {}
        key = getattr(page, "language", "text")
        return self.languages.get(key, self.languages.get("text", {}))

    def get_all_page_text(self, page):
        """#3 → full text content, safe for both editor backends."""
        if not page: return ""
        ed = getattr(page, "editor", None)
        if ed is None: return ""
        if hasattr(ed, "editor_text"): return ed.editor_text()
        if hasattr(ed, "text") and callable(ed.text): return ed.text()
        if hasattr(ed, "toPlainText"): return ed.toPlainText()
        return ""

    def get_selection_info(self, page):
        """#4 → (text, line1, col1, line2, col2) or None if no selection."""
        if not page: return None
        ed = getattr(page, "editor", None)
        if ed is None: return None
        if self.is_scintilla(page):
            l1, c1, l2, c2 = ed.getSelection()
            if l1 == -1: return None
            return (ed.selectedText(), l1, c1, l2, c2)
        return None

    def get_byte_offset(self, page, line, col):
        """#5 → byte offset in document for (line, col). Alias for char_to_byte_pos."""
        return self.char_to_byte_pos(page, line, col)

    def is_comment_style(self, page, byte_pos):
        """#6 → True if byte_pos is inside a comment (by lexer style)."""
        style = self.get_style_at(page, byte_pos)
        return style in {1, 2, 3, 12, 15}

    # ── 7-18: Editor content / cursor / navigation ──────────────────────

    def get_word_at_cursor(self, page):
        """#7 → word under cursor, or ''."""
        if not page or not self.is_scintilla(page): return ""
        ed = page.editor
        line, col = ed.getCursorPosition()
        text = ed.text(line)
        if not text: return ""
        import re
        left = text[:col]
        right = text[col:]
        m_l = re.search(r'(\w+)$', left)
        m_r = re.search(r'^(\w+)', right)
        return (m_l.group(1) if m_l else "") + (m_r.group(1) if m_r else "")

    def get_line_at_cursor(self, page):
        """#8 → (line_num, line_text) 0-based, or (-1, '')."""
        if not page or not self.is_scintilla(page): return (-1, "")
        ed = page.editor
        line, _ = ed.getCursorPosition()
        return (line, ed.text(line))

    def get_file_ext(self, page):
        """#9 → lowercase extension with dot, or ''."""
        if not page or not getattr(page, "path", None): return ""
        return os.path.splitext(page.path)[1].lower()

    def get_all_pages(self):
        """#10 → list of all EditorPage objects."""
        return [self.tabs.widget(i) for i in range(self.tabs.count())
                if self.tabs.widget(i) is not None]

    def get_page_by_path(self, path):
        """#11 → EditorPage matching path, or None."""
        if not path: return None
        norm = os.path.normpath(path)
        for p in self.get_all_pages():
            if getattr(p, "path", None) and os.path.normpath(p.path) == norm:
                return p
        return None

    def set_selection(self, page, line1, col1, line2, col2):
        """#12 → set selection range (0-based)."""
        if page and self.is_scintilla(page):
            page.editor.setSelection(line1, col1, line2, col2)

    def insert_text(self, page, text):
        """#13 → insert text at cursor position."""
        if page and self.is_scintilla(page):
            page.editor.insert(text)

    def goto_line(self, page, line):
        """#14 → move cursor to line (0-based) and scroll into view."""
        if page and self.is_scintilla(page):
            page.editor.setCursorPosition(line, 0)
            page.editor.ensureLineVisible(line)

    def get_visible_range(self, page):
        """#15 → (first_visible_line, last_visible_line)."""
        if not page or not self.is_scintilla(page): return (0, 0)
        ed = page.editor
        first = ed.firstVisibleLine()
        lines_on_screen = ed.SendScintilla(0x0944)  # SCI_LINESONSCREEN
        return (first, first + lines_on_screen - 1)

    def is_modified_any(self):
        """#16 → True if any tab has unsaved changes."""
        return any(p.is_modified() for p in self.get_all_pages() if hasattr(p, "is_modified"))

    def get_indicator_range(self):
        """#17 → (20, 31) addon-safe indicator number range."""
        return (20, 31)

    def flash_line(self, page, line, duration_ms=300):
        """#18 → briefly highlight a line using indicator 19 (reserved for flash)."""
        if not page or not self.is_scintilla(page): return
        ed = page.editor
        _IND = 19
        ed.SendScintilla(2080, _IND, 6)   # INDIC_FULLBOX
        ed.SendScintilla(2082, _IND, 0x0060CFFF)  # orange BGR
        ed.SendScintilla(2523, _IND, 80)   # alpha
        byte_start = self.get_line_byte_start(page, line)
        line_text = ed.text(line)
        byte_len = len(line_text.encode("utf-8")) if line_text else 0
        if byte_len <= 0: return
        ed.SendScintilla(2500, _IND)       # SCI_SETINDICATORCURRENT
        ed.SendScintilla(2504, byte_start, byte_len)  # FILL
        QTimer.singleShot(duration_ms, lambda: ed.SendScintilla(2505, byte_start, byte_len))

    # ── 19-40: File / tab / editor metadata ─────────────────────────────

    def get_encoding(self, page):
        """#19 → encoding string, e.g. 'utf-8'."""
        if not page: return "utf-8"
        return getattr(page, "encoding", "utf-8") or "utf-8"

    def get_eol(self, page):
        """#20 → 'CRLF' or 'LF'."""
        if not page: return "LF"
        return getattr(page, "eol", "LF") or "LF"

    def get_tab_index(self, page):
        """#21 → index in tab bar, or -1."""
        if not page: return -1
        return self.tabs.indexOf(page)

    def get_tab_title(self, page):
        """#22 → displayed tab title."""
        idx = self.get_tab_index(page)
        if idx < 0: return ""
        return self.tabs.tabText(idx)

    def get_editor_backend(self, page):
        """#23 → 'scintilla' or other."""
        if not page: return ""
        return getattr(page, "editor_kind", "")

    def get_zoom_level(self):
        """#24 → current zoom int."""
        return self.config.get("zoom", 0)

    def get_theme_colors(self):
        """#25 → dict of current theme colors."""
        from .qfat04_config import SETTINGS_ROOT, load_config
        import json
        theme_name = self.config.get("theme", "Dark")
        theme_dir = os.path.join(os.path.dirname(__file__), "themes")
        colors = {}
        # Load base theme
        theme_file = os.path.join(theme_dir, theme_name.lower() + ".json")
        if os.path.exists(theme_file):
            try:
                with open(theme_file, "r", encoding="utf-8") as f:
                    colors = json.load(f)
            except Exception:
                pass
        # Merge overrides from QSettings
        from qgis.PyQt.QtCore import QSettings
        s = QSettings()
        override_key = SETTINGS_ROOT + "/theme_overrides/" + theme_name
        raw = s.value(override_key, "", type=str)
        if raw:
            try:
                overrides = json.loads(raw)
                colors.update(overrides)
            except Exception:
                pass
        return colors

    def get_font(self):
        """#26 → current editor QFont."""
        page = self.current_page()
        if page and self.is_scintilla(page):
            lexer = page.editor.lexer()
            if lexer: return lexer.font(0)
        return QFont("Consolas", 10)

    def get_line_count(self, page):
        """#27 → total number of lines."""
        if not page or not self.is_scintilla(page): return 0
        return page.editor.lines()

    def get_char_count(self, page):
        """#28 → total character count."""
        return len(self.get_all_page_text(page))

    def get_cursor_position(self, page):
        """#29 → (line, col) 0-based."""
        if not page or not self.is_scintilla(page): return (0, 0)
        return page.editor.getCursorPosition()

    def find_text_in_page(self, page, text, case=False, regex=False):
        """#30 → list of (line, col, length) matches."""
        if not page or not text: return []
        import re as _re
        content = self.get_all_page_text(page)
        if not content: return []
        flags = 0 if case else _re.IGNORECASE
        if not regex:
            text = _re.escape(text)
        results = []
        try:
            for m in _re.finditer(text, content, flags):
                start = m.start()
                prefix = content[:start]
                line = prefix.count("\n")
                last_nl = prefix.rfind("\n")
                col = start - last_nl - 1 if last_nl >= 0 else start
                results.append((line, col, len(m.group(0))))
        except _re.error:
            pass
        return results

    def replace_in_page(self, page, old, new, case=False, all_occurrences=False):
        """#31 → count of replacements made."""
        if not page or not self.is_scintilla(page) or not old: return 0
        import re as _re
        ed = page.editor
        content = self.get_all_page_text(page)
        flags = 0 if case else _re.IGNORECASE
        escaped = _re.escape(old)
        if all_occurrences:
            result, count = _re.subn(escaped, new, content, flags=flags)
        else:
            result, count = _re.subn(escaped, new, content, count=1, flags=flags)
        if count > 0:
            ed.beginUndoAction()
            ed.selectAll()
            ed.replaceSelectedText(result)
            ed.endUndoAction()
        return count

    def get_folded_lines(self, page):
        """#32 → list of folded (collapsed) line numbers."""
        if not page or not self.is_scintilla(page): return []
        ed = page.editor
        result = []
        for line in range(ed.lines()):
            if ed.SendScintilla(2230, line) & 1:  # SCI_GETFOLDEXPANDED
                pass
            else:
                if ed.SendScintilla(2223, line) & 0x2000:  # SCI_GETLEXERSTYLEBITSMASK header
                    result.append(line)
        return result

    def toggle_fold(self, page, line):
        """#33 → fold/unfold at line."""
        if page and self.is_scintilla(page):
            page.editor.foldLine(line)

    def get_bookmarks(self, page):
        """#34 → list of bookmarked line numbers (marker 1)."""
        if not page or not self.is_scintilla(page): return []
        ed = page.editor
        result = []
        line = ed.markerFindNext(0, 0x2)  # marker bit 1
        while line >= 0:
            result.append(line)
            line = ed.markerFindNext(line + 1, 0x2)
        return result

    def set_bookmark(self, page, line, on=True):
        """#35 → add or remove bookmark (marker 1) at line."""
        if not page or not self.is_scintilla(page): return
        ed = page.editor
        if on:
            ed.markerAdd(line, 1)
        else:
            ed.markerDelete(line, 1)

    def get_open_paths(self):
        """#36 → list of all open file paths (excluding untitled)."""
        return [p.path for p in self.get_all_pages()
                if getattr(p, "path", None)]

    def close_page(self, page, force=False):
        """#37 → close a tab. force=True skips save prompt."""
        if not page: return
        idx = self.get_tab_index(page)
        if idx < 0: return
        if force and hasattr(page, "_set_unmodified"):
            page._set_unmodified()
        elif force:
            try: page.editor.setModified(False)
            except Exception: pass
        self.close_tab_at(idx)

    def run_in_console(self, code_str):
        """#38 → execute Python code in QGIS console context. Returns (output, error)."""
        import io, sys, contextlib
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exec(code_str, {"__builtins__": __builtins__, "iface": self.iface,  # nosec B102 - intentional: user script execution (editor feature)
                                "QgsProject": __import__("qgis.core", fromlist=["QgsProject"]).QgsProject})
        except Exception as e:
            stderr_buf.write(str(e))
        return (stdout_buf.getvalue(), stderr_buf.getvalue())

    def get_addon_panel(self, addon_id):
        """#39 → QDockWidget for an addon's panel, or None."""
        return self.addon_manager._panels.get(addon_id, None)

    def show_notification(self, msg, timeout=3000):
        """#40 → brief statusbar message that auto-clears."""
        self.lbl_status.setText(msg)
        QTimer.singleShot(timeout, lambda: self.lbl_status.setText("Idle"))

    # ── 41-52: Language definition accessors ─────────────────────────────

    def get_keywords_by_group(self, page, group=None):
        """#41 → keyword list. group=None → all; group=int → specific group."""
        lang = self.get_language_def(page)
        groups = lang.get("keyword_groups", [])
        if group is not None:
            if 0 <= group < len(groups):
                return list(groups[group].get("words", []))
            return []
        result = []
        for g in groups:
            result.extend(g.get("words", []))
        return result

    def get_keyword_groups(self, page):
        """#42 → list of keyword group dicts."""
        return list(self.get_language_def(page).get("keyword_groups", []))

    def get_operators(self, page):
        """#43 → list of operator strings."""
        return list(self.get_language_def(page).get("operators1", []))

    def get_delimiters(self, page):
        """#44 → list of delimiter dicts {"open","close","escape"}."""
        return list(self.get_language_def(page).get("delimiters", []))

    def get_variable_patterns(self, page):
        """#45 → list of regex patterns for variables."""
        return list(self.get_language_def(page).get("variable_patterns", []))

    def get_path_pattern(self, page):
        """#46 → regex pattern for file paths, or ''."""
        return self.get_language_def(page).get("path_pattern", "")

    def get_lang_extensions(self, page):
        """#47 → list of file extensions for the page's language."""
        return list(self.get_language_def(page).get("extensions", []))

    def get_base_engine(self, page):
        """#48 → base syntax engine name ('python', 'batch', etc.)."""
        lang = self.get_language_def(page)
        return lang.get("base", getattr(page, "language", "text"))

    def is_case_sensitive(self, page):
        """#49 → bool — whether the language is case-sensitive."""
        return bool(self.get_language_def(page).get("case_sensitive", True))

    def get_number_style(self, page):
        """#50 → number highlighting style dict or None."""
        return self.get_language_def(page).get("number_style", None)

    def get_prefix_modes(self, page):
        """#51 → prefix mode definitions."""
        return self.get_language_def(page).get("prefix_modes", {})

    def get_fold_rules(self, page):
        """#52 → folding config dict."""
        return self.get_language_def(page).get("folding", {})

    # ── 53-75: Scintilla style / indicator / annotation / byte ops ──────

    def get_style_at(self, page, byte_pos):
        """#53 → lexer style ID at byte position."""
        if not page or not self.is_scintilla(page): return 0
        return page.editor.SendScintilla(2010, byte_pos)  # SCI_GETSTYLEAT

    def is_string_style(self, page, byte_pos):
        """#54 → True if byte_pos is inside a string literal."""
        style = self.get_style_at(page, byte_pos)
        return style in {4, 6, 7, 3, 13}  # common string styles across lexers

    def is_keyword_style(self, page, byte_pos):
        """#55 → True if byte_pos is on a keyword."""
        style = self.get_style_at(page, byte_pos)
        return style in {5, 8, 14}  # common keyword styles

    def get_token_at_cursor(self, page):
        """#56 → (text, style_id, start_col, end_col) or None."""
        if not page or not self.is_scintilla(page): return None
        ed = page.editor
        line, col = ed.getCursorPosition()
        line_text = ed.text(line)
        if not line_text or col >= len(line_text.rstrip('\r\n')): return None
        line_bytes = line_text.encode("utf-8")
        line_start = self.get_line_byte_start(page, line)
        byte_col = len(line_text[:col].encode("utf-8"))
        cur_style = ed.SendScintilla(2010, line_start + byte_col)
        # Walk left
        sc = col
        while sc > 0:
            bc = len(line_text[:sc - 1].encode("utf-8"))
            if ed.SendScintilla(2010, line_start + bc) != cur_style: break
            sc -= 1
        # Walk right
        ec = col
        text_len = len(line_text.rstrip('\r\n'))
        while ec < text_len:
            bc = len(line_text[:ec + 1].encode("utf-8"))
            if ed.SendScintilla(2010, line_start + bc - 1) != cur_style: break
            ec += 1
        return (line_text[sc:ec], cur_style, sc, ec)

    def get_all_tokens_in_line(self, page, line):
        """#57 → list of (text, style_id) tuples for a line."""
        if not page or not self.is_scintilla(page): return []
        ed = page.editor
        if line < 0 or line >= ed.lines(): return []
        line_text = ed.text(line)
        if not line_text: return []
        stripped = line_text.rstrip('\r\n')
        if not stripped: return []
        line_start = self.get_line_byte_start(page, line)
        tokens = []
        cur_style = ed.SendScintilla(2010, line_start)
        cur_chars = []
        for i, ch in enumerate(stripped):
            byte_off = len(stripped[:i].encode("utf-8"))
            style = ed.SendScintilla(2010, line_start + byte_off)
            if style != cur_style:
                if cur_chars:
                    tokens.append(("".join(cur_chars), cur_style))
                cur_style = style
                cur_chars = [ch]
            else:
                cur_chars.append(ch)
        if cur_chars:
            tokens.append(("".join(cur_chars), cur_style))
        return tokens

    def get_style_map(self, page):
        """#58 → dict mapping style IDs to descriptive names for current lexer."""
        if not page or not self.is_scintilla(page): return {}
        lexer = page.editor.lexer()
        if not lexer: return {}
        result = {}
        for i in range(128):
            try:
                desc = lexer.description(i)
                if desc:
                    result[i] = desc
            except Exception:
                pass
        return result

    def get_margin_width(self, page, margin_num):
        """#59 → pixel width of margin."""
        if not page or not self.is_scintilla(page): return 0
        return page.editor.marginWidth(margin_num)

    def set_margin_width(self, page, margin_num, width):
        """#60 → set margin width in pixels."""
        if page and self.is_scintilla(page):
            page.editor.setMarginWidth(margin_num, width)

    def add_margin_marker(self, page, line, marker_num):
        """#61 → add a marker to margin at line. Returns marker handle."""
        if not page or not self.is_scintilla(page): return -1
        return page.editor.markerAdd(line, marker_num)

    def clear_margin_markers(self, page, marker_num):
        """#62 → clear all markers of given type."""
        if page and self.is_scintilla(page):
            page.editor.markerDeleteAll(marker_num)

    def get_annotation(self, page, line):
        """#63 → annotation text at line, or ''."""
        if not page or not self.is_scintilla(page): return ""
        return page.editor.annotation(line) or ""

    def set_annotation(self, page, line, text, style=None):
        """#64 → set annotation text at line."""
        if not page or not self.is_scintilla(page): return
        ed = page.editor
        if style is not None:
            try:
                from qgis.PyQt.Qsci import QsciStyledText
                ed.annotate(line, QsciStyledText(text, style))
            except Exception:
                ed.annotate(line, text, 0)
        else:
            ed.annotate(line, text, 0)

    def clear_annotations(self, page):
        """#65 → remove all annotations."""
        if page and self.is_scintilla(page):
            page.editor.clearAnnotations()

    def send_scintilla(self, page, msg, wparam=0, lparam=0):
        """#66 → safe SendScintilla wrapper. Returns result or None."""
        if not page or not self.is_scintilla(page): return None
        try:
            return page.editor.SendScintilla(msg, wparam, lparam)
        except Exception:
            return None

    def get_text_range(self, page, start_pos, end_pos):
        """#67 → text between byte positions."""
        if not page or not self.is_scintilla(page): return ""
        ed = page.editor
        length = end_pos - start_pos
        if length <= 0: return ""
        buf = bytearray(length + 1)
        try:
            ed.SendScintilla(2162, 0, start_pos)     # SCI_SETTARGETSTART
            ed.SendScintilla(2163, 0, end_pos)        # SCI_SETTARGETEND
        except Exception:
            pass
        # Fallback: extract from full text
        full = self.get_all_page_text(page).encode("utf-8")
        return full[start_pos:end_pos].decode("utf-8", errors="replace")

    def char_to_byte_pos(self, page, line, col):
        """#68 → byte offset in document for (line, col) 0-based."""
        if not page or not self.is_scintilla(page): return 0
        ed = page.editor
        byte_pos = 0
        for i in range(min(line, ed.lines())):
            byte_pos += len((ed.text(i) or "").encode("utf-8"))
        line_text = ed.text(line) or ""
        byte_pos += len(line_text[:col].encode("utf-8"))
        return byte_pos

    def byte_to_char_pos(self, page, byte_pos):
        """#69 → (line, col) from byte offset."""
        if not page or not self.is_scintilla(page): return (0, 0)
        ed = page.editor
        running = 0
        for i in range(ed.lines()):
            line_bytes = len((ed.text(i) or "").encode("utf-8"))
            if running + line_bytes > byte_pos:
                remainder = byte_pos - running
                line_text = ed.text(i) or ""
                encoded = line_text.encode("utf-8")
                col = len(encoded[:remainder].decode("utf-8", errors="replace"))
                return (i, col)
            running += line_bytes
        return (max(0, ed.lines() - 1), 0)

    def get_line_byte_start(self, page, line):
        """#70 → byte offset where line starts."""
        if not page or not self.is_scintilla(page): return 0
        ed = page.editor
        byte_pos = 0
        for i in range(min(line, ed.lines())):
            byte_pos += len((ed.text(i) or "").encode("utf-8"))
        return byte_pos

    def get_document_bytes(self, page):
        """#71 → total byte length of document."""
        if not page or not self.is_scintilla(page): return 0
        return page.editor.SendScintilla(2006)  # SCI_GETLENGTH

    def get_lexer_language(self, page):
        """#72 → QScintilla lexer name string, or ''."""
        if not page or not self.is_scintilla(page): return ""
        lexer = page.editor.lexer()
        return lexer.language() if lexer else ""

    def get_all_language_keys(self):
        """#73 → list of all registered language keys."""
        return list(self.languages.keys())

    def get_language_display_name(self, lang_key):
        """#74 → human-readable name for a language key."""
        from .qfat04_config import language_display_name
        return language_display_name(self.languages, lang_key)

    def register_indicator(self, addon_id, indicator_num):
        """#75 → claim an indicator number. Returns True if available, False if collision."""
        if not hasattr(self, "_indicator_registry"):
            self._indicator_registry = {}
        if indicator_num in self._indicator_registry:
            existing = self._indicator_registry[indicator_num]
            if existing != addon_id:
                return False
        self._indicator_registry[indicator_num] = addon_id
        return True

    # ── 76-85: Extended helpers ──────────────────────────────────────────

    def get_language_for_ext(self, ext):
        """#76 → language key for a file extension, or 'text'."""
        ext = ext.lower().lstrip(".")
        for key, lang in self.languages.items():
            exts = [e.lower().lstrip(".") for e in lang.get("extensions", [])]
            if ext in exts:
                return key
        return "text"

    def highlight_range(self, page, line1, col1, line2, col2, indicator_num):
        """#77 → fill indicator between two positions."""
        if not page or not self.is_scintilla(page): return
        ed = page.editor
        start = self.char_to_byte_pos(page, line1, col1)
        end = self.char_to_byte_pos(page, line2, col2)
        if end <= start: return
        ed.SendScintilla(2500, indicator_num)  # SCI_SETINDICATORCURRENT
        ed.SendScintilla(2504, start, end - start)  # SCI_INDICATORFILLRANGE

    def clear_indicator(self, page, indicator_num):
        """#78 → clear all instances of an indicator in the document."""
        if not page or not self.is_scintilla(page): return
        ed = page.editor
        length = ed.SendScintilla(2006)  # SCI_GETLENGTH
        if length <= 0: return
        ed.SendScintilla(2500, indicator_num)  # SCI_SETINDICATORCURRENT
        ed.SendScintilla(2505, 0, length)  # SCI_INDICATORCLEARRANGE

    def get_modified_pages(self):
        """#79 → list of pages with unsaved changes."""
        return [p for p in self.get_all_pages() if hasattr(p, "is_modified") and p.is_modified()]

    def get_untitled_pages(self):
        """#80 → list of pages with no file path."""
        return [p for p in self.get_all_pages() if not getattr(p, "path", None)]

    def get_text_under_cursor(self, page, pattern=r"\w+"):
        """#81 → text matching regex pattern around cursor."""
        if not page or not self.is_scintilla(page): return ""
        import re
        ed = page.editor
        line, col = ed.getCursorPosition()
        text = ed.text(line) or ""
        for m in re.finditer(pattern, text):
            if m.start() <= col <= m.end():
                return m.group(0)
        return ""

    def get_lines(self, page, start, end):
        """#82 → list of line texts for range [start, end) 0-based."""
        if not page or not self.is_scintilla(page): return []
        ed = page.editor
        return [ed.text(i) for i in range(max(0, start), min(end, ed.lines()))]

    def batch_operation(self, page, fn):
        """#83 → wrap fn(page) in beginUndoAction/endUndoAction."""
        if not page or not self.is_scintilla(page): return
        page.editor.beginUndoAction()
        try:
            fn(page)
        finally:
            page.editor.endUndoAction()

    def get_project_dir(self):
        """#84 → QGIS project directory or None."""
        try:
            from qgis.core import QgsProject
            path = QgsProject.instance().fileName()
            if path:
                return os.path.dirname(path)
        except Exception:
            pass
        return None

    def is_addon_enabled(self, addon_id):
        """#85 → True if addon_id is in the enabled list."""
        return addon_id in self.config.get("enabled_addons", [])

    # ── 86-100: Indent / misc / convenience ─────────────────────────────

    def get_indent_at_line(self, page, line):
        """#86 → leading whitespace string."""
        if not page or not self.is_scintilla(page): return ""
        text = page.editor.text(line) or ""
        return text[: len(text) - len(text.lstrip())]

    def get_indent_level(self, page, line):
        """#87 → indent depth (spaces, with tabs converted by tab_width)."""
        indent = self.get_indent_at_line(page, line)
        tw = self.get_tab_width()
        return sum(tw if c == '\t' else 1 for c in indent)

    def get_tab_width(self):
        """#88 → configured tab width int."""
        return self.config.get("tab_width", 4)

    def get_sibling_files(self, page):
        """#89 → list of files in same directory as current page."""
        if not page or not getattr(page, "path", None): return []
        d = os.path.dirname(page.path)
        if not os.path.isdir(d): return []
        try:
            return [os.path.join(d, f) for f in sorted(os.listdir(d))
                    if os.path.isfile(os.path.join(d, f))]
        except Exception:
            return []

    def get_recently_opened(self):
        """#90 → list of recent file paths."""
        return list(self.recent_files)

    def get_active_addons(self):
        """#91 → list of enabled addon IDs."""
        return list(self.config.get("enabled_addons", []))

    def get_addon_registry(self):
        """#92 → copy of full addon registry dict."""
        import copy as _copy
        return _copy.deepcopy(self.addon_manager.registry)

    def is_scintilla(self, page):
        """#93 → True if page uses QScintilla editor."""
        if not page: return False
        return getattr(page, "editor_kind", "") == "scintilla"

    def get_lexer(self, page):
        """#94 → QsciLexer instance or None."""
        if not page or not self.is_scintilla(page): return None
        return page.editor.lexer()

    def get_line_indent_guide_visible(self):
        """#95 → bool — whether indent guides are shown."""
        return self.config.get("show_indent_guides", True)

    def get_wrap_mode(self):
        """#96 → bool — whether word wrap is enabled."""
        return self.config.get("wrap", False)

    def get_matching_brace(self, page):
        """#97 → (line, col) of matching brace at cursor, or None."""
        if not page or not self.is_scintilla(page): return None
        ed = page.editor
        pos = ed.SendScintilla(2166)  # SCI_GETCURRENTPOS
        match_pos = ed.SendScintilla(2353, pos)  # SCI_BRACEMATCH
        if match_pos < 0:
            # Try one char before cursor
            if pos > 0:
                match_pos = ed.SendScintilla(2353, pos - 1)
        if match_pos < 0: return None
        return self.byte_to_char_pos(page, match_pos)

    def select_line(self, page, line):
        """#98 → select entire line (0-based)."""
        if not page or not self.is_scintilla(page): return
        ed = page.editor
        if line < 0 or line >= ed.lines(): return
        text = ed.text(line) or ""
        end_col = len(text.rstrip('\r\n'))
        ed.setSelection(line, 0, line, end_col)

    def select_word(self, page):
        """#99 → select word under cursor."""
        if not page or not self.is_scintilla(page): return
        ed = page.editor
        pos = ed.SendScintilla(2166)  # SCI_GETCURRENTPOS
        start = ed.SendScintilla(2266, pos)  # SCI_WORDSTARTPOSITION
        end = ed.SendScintilla(2267, pos)    # SCI_WORDENDPOSITION
        if end > start:
            l1, c1 = self.byte_to_char_pos(page, start)
            l2, c2 = self.byte_to_char_pos(page, end)
            ed.setSelection(l1, c1, l2, c2)

    def duplicate_selection(self, page):
        """#100 → duplicate selected text, or current line if no selection."""
        if not page or not self.is_scintilla(page): return
        ed = page.editor
        if ed.hasSelectedText():
            text = ed.selectedText()
            l1, c1, l2, c2 = ed.getSelection()
            ed.beginUndoAction()
            ed.setCursorPosition(l2, c2)
            ed.insert(text)
            ed.endUndoAction()
        else:
            line, _ = ed.getCursorPosition()
            text = ed.text(line)
            ed.beginUndoAction()
            ed.setCursorPosition(line, 0)
            ed.insert(text)
            ed.endUndoAction()
