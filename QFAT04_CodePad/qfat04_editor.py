"""
qfat04_editor.py
The Editing Engine.
PlainEditor, ScintillaEditor, EditorPage (language-aware), DropTabWidget,
EditorShortcutFilter.
"""

import os

from qgis.PyQt.QtCore import Qt, QEvent, QObject, QSize, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QKeySequence
from qgis.PyQt.QtWidgets import (
    QPlainTextEdit,
    QStackedWidget,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QWidget,
    QVBoxLayout,
)

from .qfat04_config import (
    DEFAULT_EDITOR_SHORTCUTS,
    get_theme,
    language_for_extension,
    load_languages,
)
from .qfat04_languages import (
    TRY_QSCI,
    BasicHighlighter,
)

if TRY_QSCI:
    from qgis.PyQt.Qsci import QsciScintilla
    from .qfat04_languages import TuflowLexer


# ---------------------------------------------------------------------------
# EOL helper
# ---------------------------------------------------------------------------
def detect_eol(text):
    if "\r\n" in text:
        return "CRLF"
    if "\n" in text:
        return "LF"
    return "CRLF"


# ---------------------------------------------------------------------------
# Plain-text editor wrapper
# ---------------------------------------------------------------------------
class PlainEditor(QPlainTextEdit):
    cursorInfoChanged = pyqtSignal(int, int)
    filesDropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.highlighter = None
        self.cursorPositionChanged.connect(self._emit_cursor)

    def dragEnterEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if paths: self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else: super().dropEvent(event)

    def _emit_cursor(self):
        c = self.textCursor()
        self.cursorInfoChanged.emit(c.blockNumber() + 1, c.columnNumber() + 1)

    def set_language(self, language_key, config):
        self.highlighter = BasicHighlighter(self.document(), language_key, config)

    def set_editor_config(self, config):
        theme = get_theme(config["theme"])
        font  = QFont(config["font_family"], config["font_size"])
        self.setFont(font)
        self.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if config["wrap"] else QPlainTextEdit.NoWrap
        )
        self.setTabStopDistance(
            self.fontMetrics().horizontalAdvance(" ") * config["tab_width"]
        )
        self.setStyleSheet(
            "QPlainTextEdit { background:%s; color:%s; selection-background-color:%s; }"
            % (theme["paper"], theme["text"], theme["selection"])
        )

    # Uniform API
    def editor_text(self):           return self.toPlainText()
    def set_editor_text(self, text): self.setPlainText(text)
    def set_modified(self, value):   self.document().setModified(value)
    def is_modified(self):           return self.document().isModified()
    def hasSelectedText(self):       return self.textCursor().hasSelection()
    def selectedText(self):          return self.textCursor().selectedText()

    def find_next(self, text, use_regex=False):
        return False if use_regex else self.find(text)

    def find_prev(self, text, use_regex=False):
        from qgis.PyQt.QtGui import QTextDocument
        flags = QTextDocument.FindBackward
        if use_regex:
            return False
        return bool(self.find(text, flags))

    def replace_next(self, find_text, replace_text):
        cursor = self.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == find_text:
            cursor.insertText(replace_text)
        return self.find(find_text)

    def replace_all(self, find_text, replace_text):
        text  = self.toPlainText()
        count = text.count(find_text)
        if count:
            self.setPlainText(text.replace(find_text, replace_text))
        return count


# ---------------------------------------------------------------------------
# QScintilla editor wrapper
# ---------------------------------------------------------------------------
class ScintillaEditor(QsciScintilla if TRY_QSCI else object):
    cursorInfoChanged = pyqtSignal(int, int)
    filesDropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self._lexer = None
        self.setUtf8(True)
        self.cursorPositionChanged.connect(self._emit_cursor)

    def dragEnterEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if paths: self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else: super().dropEvent(event)

    def _emit_cursor(self, line, index):
        self.cursorInfoChanged.emit(line + 1, index + 1)

    def set_language(self, language_key, config):
        self._lexer = TuflowLexer(self, language_key, config)
        self.setLexer(self._lexer)

    def set_editor_config(self, config):
        theme = get_theme(config["theme"])
        font  = QFont(config["font_family"], config["font_size"])
        self.setFont(font)
        self.SendScintilla(self.SCI_STYLESETFONT, self.STYLE_DEFAULT,
                           bytes(config["font_family"], "utf-8"))
        self.SendScintilla(self.SCI_STYLESETSIZE, self.STYLE_DEFAULT, config["font_size"])
        self.SendScintilla(self.SCI_STYLECLEARALL)
        self.setMarginsBackgroundColor(QColor(theme["margin_bg"]))
        self.setMarginsForegroundColor(QColor(theme["margin_fg"]))
        self.setPaper(QColor(theme["paper"]))
        self.setColor(QColor(theme["text"]))
        self.setCaretForegroundColor(QColor(theme["caret"]))
        self.setSelectionBackgroundColor(QColor(theme["selection"]))
        self.setMatchedBraceBackgroundColor(QColor(theme["brace_bg"]))
        self.setMatchedBraceForegroundColor(QColor(theme["brace_fg"]))
        self.setBraceMatching(
            self.SloppyBraceMatch if config["brace_matching"] else self.NoBraceMatch
        )
        self.setMarginLineNumbers(0, config["show_line_numbers"])
        self.setMarginWidth(0, "0000" if config["show_line_numbers"] else 0)
        self.setMarginsFont(font)
        self.setTabWidth(config["tab_width"])
        self.setIndentationsUseTabs(False)
        self.setIndentationGuides(config["show_indent_guides"])
        self.setAutoIndent(True)
        self.setWrapMode(self.WrapWord if config["wrap"] else self.WrapNone)
        self.setWhitespaceVisibility(
            self.WsVisible if config["show_whitespace"] else self.WsInvisible
        )
        try:
            self.setEolVisibility(config["show_eol"])
        except Exception:
            pass
        self.zoomTo(config["zoom"])
        if self._lexer is not None:
            self._lexer.config = config
            self._lexer._set_fonts()
            try:
                self.recolor()
            except Exception:
                self.setLexer(None)
                self.setLexer(self._lexer)
        # Folding margin — must be configured AFTER lexer so fold levels exist
        if config["folding"]:
            self.setFolding(self.PlainFoldStyle)
            # Margin 2 is the fold margin
            self.setMarginType(2, self.SymbolMargin)
            self.setMarginWidth(2, 14)
            self.setMarginSensitivity(2, True)
            self.setFoldMarginColors(
                QColor(theme["margin_bg"]), QColor(theme["margin_bg"])
            )
            # Send fold property so the custom lexer activates fold-level setting
            self.SendScintilla(self.SCI_SETPROPERTY, b"fold", b"1")
            self.SendScintilla(self.SCI_SETPROPERTY, b"fold.compact", b"0")
        else:
            self.setFolding(self.NoFoldStyle)
            self.setMarginWidth(2, 0)

    # Uniform API
    def editor_text(self):           return self.text()
    def set_editor_text(self, text): self.setText(text)
    def set_modified(self, value):   self.setModified(value)
    def is_modified(self):           return self.isModified()

    def find_next(self, text, use_regex=False):
        line, index = self.getCursorPosition()
        return self.findFirst(text, use_regex, False, False, True, True, line, index)

    def find_prev(self, text, use_regex=False):
        line, index = self.getCursorPosition()
        # Move back one char so we don't re-match current selection
        if index > 0: index -= 1
        elif line > 0: line -= 1; index = len(self.text(line))
        return self.findFirst(text, use_regex, False, False, True, False, line, index)

    def replace_next(self, find_text, replace_text):
        if self.hasSelectedText() and self.selectedText() == find_text:
            self.replaceSelectedText(replace_text)
        return self.find_next(find_text, False)

    def replace_all(self, find_text, replace_text):
        text  = self.text()
        count = text.count(find_text)
        if count:
            self.setText(text.replace(find_text, replace_text))
        return count


# ---------------------------------------------------------------------------
# EditorPage – one tab in the tab widget
# ---------------------------------------------------------------------------
class EditorPage(QWidget):
    stateChanged               = pyqtSignal()
    editorContextMenuRequested = pyqtSignal(object)
    filesDropped               = pyqtSignal(list)

    def __init__(self, config, path=None, parent=None):
        super().__init__(parent)
        self.path        = path
        self.config      = dict(config)
        self.language    = "auto"
        self.editor_kind = "plain"
        self.encoding    = "UTF-8"
        self.eol         = "CRLF"
        self._build_editor()
        # Don't let the editor's preferred width inflate the dock when switching tabs
        self.editor.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        # The page itself
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor)

        self.editor.setContextMenuPolicy(Qt.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self._on_editor_context_menu)

        self._connect_signals()
        if path:
            self.load_from_path(path)
        else:
            self.apply_config(self.config)

    def _on_editor_context_menu(self, pos):
        self.editorContextMenuRequested.emit(self.editor.mapToGlobal(pos))

    def _build_editor(self):
        backend = self.config.get("editor_backend", "auto")
        use_scintilla = (backend in ("auto", "scintilla")) and TRY_QSCI
        if use_scintilla:
            try:
                self.editor      = ScintillaEditor()
                self.editor_kind = "scintilla"
                return
            except Exception:
                pass
        self.editor      = PlainEditor()
        self.editor_kind = "plain"

    def _connect_signals(self):
        # Wired once — never inside refresh loops
        if self.editor_kind == "scintilla":
            self.editor.modificationChanged.connect(lambda *_: self.stateChanged.emit())
        else:
            self.editor.document().modificationChanged.connect(lambda *_: self.stateChanged.emit())
        self.editor.cursorInfoChanged.connect(self._notify_cursor)
        self.editor.filesDropped.connect(self.filesDropped.emit)

    def _notify_cursor(self, line, col):
        pass  # overridden externally via signal connection

    # ------------------------------------------------------------------
    def title(self):
        base = os.path.basename(self.path) if self.path else "Untitled"
        return ("*" + base) if self.is_modified() else base

    def detect_language(self):
        """Use the language registry to detect language from file extension."""
        ext       = os.path.splitext(self.path or "")[1].lower()
        languages = self.config.get("languages") or load_languages()
        return language_for_extension(languages, ext)

    def set_language_profile(self, language_key):
        self.language = language_key
        self.editor.set_language(self.language, self.config)
        self.editor.set_editor_config(self.config)

    def apply_config(self, config):
        self.config = dict(config)
        if not getattr(self, "language", None) or self.language == "auto":
            self.language = self.detect_language()
        self.editor.set_language(self.language, self.config)
        self.editor.set_editor_config(self.config)

    def load_from_path(self, path):
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            text = f.read()
        self.path     = path
        self.encoding = "UTF-8"
        self.eol      = detect_eol(text)
        # Clear lexer before setting text
        if self.editor_kind == "scintilla":
            self.editor.setLexer(None)
        self.editor.set_editor_text(text)
        # Apply config WITHOUT lexer for large files — defer lexer attachment
        if self.editor_kind == "scintilla" and len(text) > 5000:
            self._deferred_config = dict(self.config)
            # Apply editor config (margins, colors, etc.) but skip lexer
            self.editor.set_editor_config(self.config)
            if not getattr(self, "language", None) or self.language == "auto":
                self.language = self.detect_language()
            from qgis.PyQt.QtCore import QTimer
            QTimer.singleShot(500, self._attach_deferred_lexer)
        else:
            self.apply_config(self.config)
        self.set_modified(False)

    def _attach_deferred_lexer(self):
        """Attach the lexer after UI has rendered the plain text."""
        if hasattr(self, '_deferred_config'):
            self.apply_config(self._deferred_config)
            del self._deferred_config

    def save(self):
        if not self.path:
            return False
        with open(self.path, "w", encoding="utf-8", errors="replace", newline="") as f:
            f.write(self.editor.editor_text())
        self.set_modified(False)
        self.stateChanged.emit()
        return True

    def set_modified(self, value): self.editor.set_modified(value)
    def is_modified(self):         return self.editor.is_modified()


# ---------------------------------------------------------------------------
# SmartTabBar – truncates inactive tabs, full name on active tab
# ---------------------------------------------------------------------------
class SmartTabBar(QTabBar):
    """Custom tab bar with smart truncation and configurable width limits."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_titles = {}   # idx -> full title text
        self._min_w = 60
        self._max_w = 180
        self._tab_font_size = 0   # 0 = use default
        self._inflate_active = False
        # Notepad++-style swap-on-cross drag state
        self._drag_active = False
        self._drag_index = -1
        self._drag_start_pos = None
        self._drag_threshold = 6  # px before drag starts
        self.setStyleSheet(
            "QTabBar::tab { padding: 3px 8px; background: #c0c0c0; color: #000000; "
            "  border: 1px solid #a0a0a0; border-bottom: none; margin-right: 1px; }"
            "QTabBar::tab:selected { background: #f0f0f0; color: #000000; "
            "  border-top: 3px solid #3daee9; border-left: 1px solid #a0a0a0; "
            "  border-right: 1px solid #a0a0a0; border-bottom: none; }"
            "QTabBar::tab:hover:!selected { background: #d0d0d0; }"
        )
        # Keep _full_titles in sync when tabs are reordered
        self.tabMoved.connect(self._on_tab_moved)

    # ---- Notepad++-style drag: swap with neighbour when cursor crosses midpoint ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            idx = self.tabAt(e.pos())
            if idx >= 0:
                self._drag_index = idx
                self._drag_start_pos = e.pos()
                self._drag_active = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._drag_index >= 0 and self._drag_start_pos is not None
                and (e.buttons() & Qt.LeftButton)):
            if not self._drag_active:
                if (e.pos() - self._drag_start_pos).manhattanLength() >= self._drag_threshold:
                    self._drag_active = True
            if self._drag_active:
                cur = self._drag_index
                rect = self.tabRect(cur)
                center_x = rect.center().x()
                px = e.pos().x()
                # Cursor crossed left neighbour's midpoint?
                if cur > 0 and px < self.tabRect(cur - 1).center().x():
                    self.moveTab(cur, cur - 1)
                    self._drag_index = cur - 1
                elif cur < self.count() - 1 and px > self.tabRect(cur + 1).center().x():
                    self.moveTab(cur, cur + 1)
                    self._drag_index = cur + 1
                return  # swallow — no further default processing during active drag
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_index = -1
        self._drag_start_pos = None
        self._drag_active = False
        super().mouseReleaseEvent(e)

    def set_inflate_active(self, on):
        on = bool(on)
        if self._inflate_active != on:
            self._inflate_active = on
            self._refresh_all_texts()
            self.updateGeometry()

    def _on_tab_moved(self, from_idx, to_idx):
        """Remap _full_titles when a tab is dragged to a new position."""
        moved = self._full_titles.pop(from_idx, None)
        # Shift intermediate indices
        if from_idx < to_idx:
            for i in range(from_idx, to_idx):
                if (i + 1) in self._full_titles:
                    self._full_titles[i] = self._full_titles.pop(i + 1)
        else:
            for i in range(from_idx, to_idx, -1):
                if (i - 1) in self._full_titles:
                    self._full_titles[i] = self._full_titles.pop(i - 1)
        if moved is not None:
            self._full_titles[to_idx] = moved
        self._refresh_all_texts()

    def set_tab_font_size(self, size):
        if size and size > 0:
            self._tab_font_size = size
            font = self.font()
            font.setPointSize(size)
            self.setFont(font)
        else:
            self._tab_font_size = 0
        self._refresh_all_texts()

    def set_tab_limits(self, min_w, max_w):
        changed = (self._min_w != min_w or self._max_w != max_w)
        self._min_w = max(30, min_w)
        self._max_w = max(self._min_w + 20, max_w)
        if changed:
            self._refresh_all_texts()

    def setTabText(self, idx, text):
        """Store full title, display smart-truncated version."""
        self._full_titles[idx] = text
        display = self._display_text(idx, text)
        super().setTabText(idx, display)

    def fullTabText(self, idx):
        return self._full_titles.get(idx, super().tabText(idx))

    def tabSizeHint(self, idx):
        hint = super().tabSizeHint(idx)
        is_active = (idx == self.currentIndex())
        if is_active and self._inflate_active:
            fm = QFontMetrics(self.font())
            full = self._full_titles.get(idx, super().tabText(idx))
            text_w = fm.horizontalAdvance(full) + 56  # padding + close btn space
            w = max(self._min_w, min(text_w, self._max_w * 2))
        else:
            w = max(self._min_w, min(hint.width(), self._max_w))
        return QSize(w, hint.height())

    def _display_text(self, idx, full_text):
        """Smart truncate: keep extension, ellipsis in middle."""
        is_active = (idx == self.currentIndex())
        if is_active and self._inflate_active:
            return full_text
        fm = QFontMetrics(self.font())
        # Budget = max_w minus padding and close button
        budget = self._max_w - 52  # padding + close btn space
        if budget < 20:
            budget = 20
        if fm.horizontalAdvance(full_text) <= budget:
            return full_text
        # Split into stem + ext so extension is always visible
        base = full_text
        prefix = ""
        if base.startswith("*"):
            prefix = "*"
            base = base[1:]
        dot = base.rfind(".")
        if dot > 0:
            stem = base[:dot]
            ext = base[dot:]       # e.g. ".tcf"
        else:
            stem = base
            ext = ""
        ellipsis = "\u2026"
        ext_w = fm.horizontalAdvance(ext)
        ell_w = fm.horizontalAdvance(ellipsis)
        pfx_w = fm.horizontalAdvance(prefix)
        avail = budget - ext_w - ell_w - pfx_w
        if avail < 10:
            # Very tight — just truncate from end
            return prefix + fm.elidedText(base, Qt.ElideRight, budget - pfx_w)
        # Split stem: show start and end
        half = avail // 2
        front = ""
        for ch in stem:
            test = front + ch
            if fm.horizontalAdvance(test) > half:
                break
            front = test
        back = ""
        for ch in reversed(stem):
            test = ch + back
            if fm.horizontalAdvance(test) > (avail - fm.horizontalAdvance(front)):
                break
            back = test
        return prefix + front + ellipsis + back + ext

    def _refresh_all_texts(self):
        for idx in range(self.count()):
            full = self._full_titles.get(idx, super().tabText(idx))
            display = self._display_text(idx, full)
            super().setTabText(idx, display)
        # Notepad++ style: active tab raised with top accent, inactive flat
        size_str = "font-size: %dpt;" % self._tab_font_size if self._tab_font_size else ""
        self.setStyleSheet(
            "QTabBar::tab { padding: 3px 8px; background: #c0c0c0; color: #000000; "
            "  border: 1px solid #a0a0a0; border-bottom: none; margin-right: 1px; %s }"
            "QTabBar::tab:selected { background: #f0f0f0; color: #000000; "
            "  border-top: 3px solid #3daee9; border-left: 1px solid #a0a0a0; "
            "  border-right: 1px solid #a0a0a0; border-bottom: none; }"
            "QTabBar::tab:hover:!selected { background: #d0d0d0; }" % size_str
        )

    def _on_current_changed(self, _idx):
        """Re-truncate all tabs when active tab changes (only needed if inflating active)."""
        if self._inflate_active:
            self._refresh_all_texts()

    def tabInserted(self, idx):
        # Shift stored titles for indices above the inserted one
        new_map = {}
        for k, v in self._full_titles.items():
            if k >= idx:
                new_map[k + 1] = v
            else:
                new_map[k] = v
        self._full_titles = new_map
        super().tabInserted(idx)

    def tabRemoved(self, idx):
        self._full_titles.pop(idx, None)
        new_map = {}
        for k, v in self._full_titles.items():
            if k > idx:
                new_map[k - 1] = v
            elif k < idx:
                new_map[k] = v
        self._full_titles = new_map
        super().tabRemoved(idx)


# ---------------------------------------------------------------------------
# DropTabWidget – file-drop-aware tab bar
# ---------------------------------------------------------------------------
class DropTabWidget(QTabWidget):
    filesDropped     = pyqtSignal(list)
    contextRequested = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Install custom smart tab bar
        self._smart_bar = SmartTabBar(self)
        self.setTabBar(self._smart_bar)

        self.setAcceptDrops(True)
        self.setMovable(False)  # Custom swap-on-cross drag implemented in SmartTabBar
        self.setTabsClosable(True)
        self.setDocumentMode(True)
        self.setElideMode(Qt.ElideNone)   # We handle truncation ourselves
        self.setUsesScrollButtons(True)

        self._smart_bar.setAcceptDrops(True)
        self._smart_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        self._smart_bar.customContextMenuRequested.connect(self._tab_context)
        # Connect currentChanged to refresh truncation — single connection, never duplicated
        self.currentChanged.connect(self._smart_bar._on_current_changed)
        self.installEventFilter(self)
        self._smart_bar.installEventFilter(self)
        self._install_drop_targets()

    def set_tab_limits(self, min_w, max_w):
        self._smart_bar.set_tab_limits(min_w, max_w)

    def set_tab_font_size(self, size):
        self._smart_bar.set_tab_font_size(size)

    def set_show_close_button(self, show):
        self.setTabsClosable(bool(show))

    def set_inflate_active(self, on):
        self._smart_bar.set_inflate_active(on)

    def setTabText(self, idx, text):
        """Route through SmartTabBar so it stores the full title."""
        self._smart_bar.setTabText(idx, text)

    def fullTabText(self, idx):
        return self._smart_bar.fullTabText(idx)

    def _tab_context(self, pos):
        self.contextRequested.emit(
            self.tabBar().tabAt(pos), self.tabBar().mapToGlobal(pos)
        )

    def _extract_paths(self, mime_data):
        paths = []
        if mime_data is None or not mime_data.hasUrls():
            return paths
        for url in mime_data.urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        return paths

    def _install_drop_targets(self):
        self.setAcceptDrops(True)
        self.tabBar().setAcceptDrops(True)
        for child in self.findChildren(QWidget):
            if child is self or child is self.tabBar():
                continue
            if isinstance(child, QStackedWidget) or child.parent() is self:
                child.setAcceptDrops(True)
                try:
                    child.installEventFilter(self)
                except Exception:
                    pass

    def showEvent(self, event):
        self._install_drop_targets()
        super().showEvent(event)

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (event.DragEnter, event.DragMove, event.Drop):
            paths = self._extract_paths(event.mimeData())
            if paths:
                if et == event.Drop:
                    self.filesDropped.emit(paths)
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        if self._extract_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._extract_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = self._extract_paths(event.mimeData())
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


# ---------------------------------------------------------------------------
# EditorShortcutFilter – keyboard event filter for custom shortcuts
# ---------------------------------------------------------------------------
class EditorShortcutFilter(QObject):
    def __init__(self, dock):
        super().__init__(dock)
        self.dock = dock

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress):
            key = event.key()
            if key in (0, Qt.Key_unknown, Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
                return super().eventFilter(obj, event)

            mods    = event.modifiers()
            qt_mods = 0
            if mods & Qt.ControlModifier: qt_mods |= int(Qt.ControlModifier)
            if mods & Qt.ShiftModifier:   qt_mods |= int(Qt.ShiftModifier)
            if mods & Qt.AltModifier:     qt_mods |= int(Qt.AltModifier)
            if mods & Qt.MetaModifier:    qt_mods |= int(Qt.MetaModifier)

            seq_str = QKeySequence(int(key) | qt_mods).toString(QKeySequence.PortableText)

            # Custom dynamic shortcuts
            sc_dup = QKeySequence(self.dock._shortcut_text("duplicate_line")).toString(QKeySequence.PortableText)
            sc_com = QKeySequence(self.dock._shortcut_text("toggle_comment")).toString(QKeySequence.PortableText)
            sc_sav = QKeySequence(self.dock._shortcut_text("save_file")).toString(QKeySequence.PortableText)

            # Universal Bouncer Dictionary
            # If the user presses ANY of these keys, we rip it away from Scintilla
            # and force the Dock to handle it natively.
            routes = {
                sc_dup:   self.dock.duplicate_line,
                sc_com:   self.dock.toggle_comment,
                sc_sav:   self.dock.save_current,
                "Ctrl+F": self.dock.trigger_find,
                "Ctrl+H": self.dock.trigger_replace,
                "F3":     self.dock.find_next,
                "Ctrl+O": self.dock.open_file,
                "F5":     self.dock.run_current,
                "Ctrl++": self.dock.zoom_in,
                "Ctrl+=": self.dock.zoom_in,
                "Ctrl+-": self.dock.zoom_out,
            }

            if seq_str in routes:
                if event.type() == QEvent.KeyPress:
                    routes[seq_str]()  # Execute the mapped dock function
                event.accept()         # Destroy the event so Scintilla/QGIS never sees it
                return True

        return super().eventFilter(obj, event)
