"""
selection_highlighter.py  v0.1
Highlights all occurrences of the selected text on the active page.
"""
__version__ = "0.19"

from qgis.PyQt.QtCore import QSettings, QTimer, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QCheckBox, QSpinBox,
    QPushButton, QLabel, QColorDialog, QDialogButtonBox,
)

try:
    from qgis.PyQt import sip
except ImportError:
    try:
        import sip
    except ImportError:
        sip = None

# ---------------------------------------------------------------- settings ---
_S_ROOT = "QFAT/QFAT04/addon_selection_highlighter/"
_INDICATOR_NUM = 29  # high number to avoid collisions with lexer/search indicators
_DEBOUNCE_MS = 60

_DEFAULTS = {
    "case_sensitive": False,      # 1. default insensitive
    "whole_word": True,           # 2. default ON
    "min_length": 2,              # 3. min selection length
    "skip_multiline": True,       # 4. skip if selection spans lines
    "include_active": False,      # 5. skip active selection itself by default
    "exclude_comments": False,    # skip matches inside comments, default OFF
    "debug": False,               # debug output to Messages panel
    "color": "#FFD54F",           # 8. adjustable colour (amber)
    "alpha": 110,                 # highlight translucency (0-255)
}

def _get(key):
    s = QSettings()
    v = s.value(_S_ROOT + key, _DEFAULTS[key])
    t = type(_DEFAULTS[key])
    if t is bool:
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes", "on")
        return bool(int(v)) if not isinstance(v, bool) else v
    if t is int:
        try:
            return int(v)
        except Exception:
            return _DEFAULTS[key]
    return str(v)

def _set(key, value):
    QSettings().setValue(_S_ROOT + key, value)

def _dbg(dock, text):
    if _get("debug") and dock and hasattr(dock, "messages"):
        try:
            dock.messages.append("[SEL_HL] " + text)
        except Exception:
            pass

# ---------------------------------------------------------------- per-page ---
# Each EditorPage's editor gets one Highlighter attached as ._sel_highlighter
class _Highlighter:
    def __init__(self, editor, dock=None, page=None):
        self.editor = editor
        self.dock = dock
        self.page = page
        self._last_needle = ""
        self._last_sel_range = (-1, -1)
        self.timer = QTimer(editor)
        self.timer.setSingleShot(True)
        self.timer.setInterval(_DEBOUNCE_MS)
        self.timer.timeout.connect(self._scan)
        self._scroll_timer = QTimer(editor)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(_DEBOUNCE_MS)
        self._scroll_timer.timeout.connect(self._rescan_current)
        # Connect once per editor instance
        self._sel_connected = False
        self._scroll_connected = False
        # Try multiple signal names — QScintilla subclass may differ
        for sig_name in ("selectionChanged", "cursorPositionChanged", "SCN_UPDATEUI"):
            try:
                sig = getattr(editor, sig_name, None)
                if sig is not None and hasattr(sig, "connect"):
                    sig.connect(self._on_selection_changed)
                    self._sel_connected = True
                    self._sel_signal_name = sig_name
                    break
            except Exception:
                continue
        # Scroll signal: QsciScintilla exposes verticalScrollBar()
        try:
            sb = editor.verticalScrollBar()
            sb.valueChanged.connect(self._on_scroll)
            self._scroll_connected = True
        except Exception:
            pass
        self._configure_indicator()

    def _msg(self, text):
        if not _get("debug"):
            return
        try:
            if self.dock and hasattr(self.dock, "messages"):
                self.dock.messages.append("[SEL_HL] " + text)
        except Exception:
            pass

    # --- Scintilla helpers ---
    def _send(self, msg, w=0, l=0):
        try:
            return self.editor.SendScintilla(msg, w, l)
        except Exception:
            return 0

    def _configure_indicator(self):
        ed = self.editor
        try:
            # INDIC_ROUNDBOX = 7
            SCI_INDICSETSTYLE = 2080
            SCI_INDICSETFORE = 2082
            SCI_INDICSETALPHA = 2523
            SCI_INDICSETOUTLINEALPHA = 2558
            SCI_INDICSETUNDER = 2510
            ed.SendScintilla(SCI_INDICSETSTYLE, _INDICATOR_NUM, 7)
            col = QColor(_get("color"))
            # Scintilla colour is 0x00BBGGRR
            bgr = (col.blue() << 16) | (col.green() << 8) | col.red()
            ed.SendScintilla(SCI_INDICSETFORE, _INDICATOR_NUM, bgr)
            ed.SendScintilla(SCI_INDICSETALPHA, _INDICATOR_NUM, int(_get("alpha")))
            ed.SendScintilla(SCI_INDICSETOUTLINEALPHA, _INDICATOR_NUM, min(255, int(_get("alpha")) + 40))
            ed.SendScintilla(SCI_INDICSETUNDER, _INDICATOR_NUM, 1)  # draw under text
        except Exception:
            pass

    def reload_indicator(self):
        self._configure_indicator()
        self._scan()

    def clear(self):
        ed = self.editor
        try:
            SCI_SETINDICATORCURRENT = 2500
            SCI_INDICATORCLEARRANGE = 2505
            length = ed.SendScintilla(2006)  # SCI_GETLENGTH
            ed.SendScintilla(SCI_SETINDICATORCURRENT, _INDICATOR_NUM)
            ed.SendScintilla(SCI_INDICATORCLEARRANGE, 0, length)
        except Exception:
            pass

    def _on_selection_changed(self):
        self.timer.start()

    def _on_scroll(self, _value=None):
        # Only matters if we currently have something to highlight
        if self._last_needle:
            self._scroll_timer.start()

    def _rescan_current(self):
        # Triggered by scroll: re-highlight visible range using cached needle
        if not self._last_needle:
            return
        self._scan()

    def _visible_line_range(self):
        """Return (first_doc_line, last_doc_line) of visible area, padded."""
        ed = self.editor
        SCI_GETFIRSTVISIBLELINE = 2152
        SCI_LINESONSCREEN = 2370
        SCI_DOCLINEFROMVISIBLE = 2221
        SCI_GETLINECOUNT = 2154
        try:
            first_vis = ed.SendScintilla(SCI_GETFIRSTVISIBLELINE)
            on_screen = ed.SendScintilla(SCI_LINESONSCREEN)
            line_count = ed.SendScintilla(SCI_GETLINECOUNT)
            pad = 5
            first_doc = ed.SendScintilla(SCI_DOCLINEFROMVISIBLE, max(0, first_vis - pad))
            last_doc = ed.SendScintilla(SCI_DOCLINEFROMVISIBLE, first_vis + on_screen + pad)
            if last_doc >= line_count:
                last_doc = line_count - 1
            return max(0, int(first_doc)), max(0, int(last_doc))
        except Exception:
            return 0, 0

    def _scan(self):
        ed = self.editor
        if sip is not None:
            try:
                if sip.isdeleted(ed):
                    return
            except Exception:
                pass
        self.clear()
        # Get selected text — try both APIs
        sel = ""
        try:
            sel = ed.selectedText()
        except Exception:
            pass
        if not sel:
            try:
                sel = ed.selected_text()
            except Exception:
                pass
        if not sel:
            self._last_needle = ""
            return
        # 4. Skip multi-line
        if _get("skip_multiline") and ("\n" in sel or "\r" in sel
                                       or "\u2029" in sel):
            self._last_needle = ""
            return
        # 3. Min length
        if len(sel.strip()) < max(1, _get("min_length")):
            self._last_needle = ""
            return
        self._last_needle = sel

        # Active selection byte range (cache once, not per-hit)
        include_active = _get("include_active")
        sel_start_byte = sel_end_byte = -1
        if not include_active:
            try:
                sel_start_byte = ed.SendScintilla(2143)  # SCI_GETSELECTIONSTART
                sel_end_byte = ed.SendScintilla(2145)    # SCI_GETSELECTIONEND
            except Exception:
                pass

        # Visible line range
        vis_first_line, vis_last_line = self._visible_line_range()

        case = _get("case_sensitive")
        word = _get("whole_word")
        exclude_comments = _get("exclude_comments")
        needle = sel if case else sel.lower()
        needle_len = len(sel.encode("utf-8"))

        # Resolve comment prefixes from core language definition
        comment_prefixes = []
        if exclude_comments and self.dock and self.page:
            try:
                lang_key = getattr(self.page, "language", None)
                if lang_key and hasattr(self.dock, "languages"):
                    lang_def = self.dock.languages.get(lang_key, {})
                    comment_prefixes = list(lang_def.get("comment_prefixes", []))
            except Exception:
                pass

        SCI_SETINDICATORCURRENT = 2500
        SCI_INDICATORFILLRANGE = 2504
        SCI_POSITIONFROMLINE = 2167

        try:
            ed.SendScintilla(SCI_SETINDICATORCURRENT, _INDICATOR_NUM)
        except Exception:
            return

        hits = 0
        for line_num in range(vis_first_line, vis_last_line + 1):
            try:
                line_text = ed.text(line_num)
            except Exception:
                continue
            if not line_text:
                continue
            try:
                line_start_byte = ed.SendScintilla(SCI_POSITIONFROMLINE, line_num)
            except Exception:
                continue

            search_in = line_text if case else line_text.lower()
            start = 0
            while True:
                idx = search_in.find(needle, start)
                if idx < 0:
                    break

                # Whole word check (char-level in the line)
                if word:
                    if idx > 0:
                        c = line_text[idx - 1]
                        if c.isalnum() or c == "_":
                            start = idx + 1
                            continue
                    end_ch = idx + len(sel)
                    if end_ch < len(line_text):
                        c = line_text[end_ch]
                        if c.isalnum() or c == "_":
                            start = idx + 1
                            continue

                # Byte offset within line
                prefix_bytes = len(line_text[:idx].encode("utf-8"))
                abs_byte = int(line_start_byte) + prefix_bytes

                # Exclude active selection
                if not include_active:
                    if abs_byte == sel_start_byte and (abs_byte + needle_len) == sel_end_byte:
                        start = idx + len(sel)
                        continue

                # Exclude comments (use core language comment_prefixes)
                if exclude_comments and comment_prefixes:
                    # Find earliest comment prefix in line_text before idx
                    in_comment = False
                    for cp in comment_prefixes:
                        cp_idx = line_text.find(cp)
                        if 0 <= cp_idx <= idx:
                            in_comment = True
                            break
                    if in_comment:
                        start = idx + len(sel)
                        continue

                try:
                    ed.SendScintilla(SCI_INDICATORFILLRANGE, abs_byte, needle_len)
                    hits += 1
                except Exception:
                    pass
                start = idx + len(sel)
                if start <= idx:
                    start = idx + 1

    def detach(self):
        self._msg("detach: sel_connected=%s scroll_connected=%s sig=%s" % (
            self._sel_connected, self._scroll_connected,
            getattr(self, "_sel_signal_name", "NONE")))
        try:
            if self._sel_connected:
                sig_name = getattr(self, "_sel_signal_name", "selectionChanged")
                sig = getattr(self.editor, sig_name, None)
                if sig is not None:
                    sig.disconnect(self._on_selection_changed)
                    self._msg("disconnected %s OK" % sig_name)
                else:
                    self._msg("sig %s not found" % sig_name)
        except Exception as e:
            self._msg("disconnect FAILED: %s" % e)
        try:
            if self._scroll_connected:
                self.editor.verticalScrollBar().valueChanged.disconnect(self._on_scroll)
        except Exception:
            pass
        try:
            self.timer.stop()
            self._scroll_timer.stop()
        except Exception:
            pass
        self._last_needle = ""
        self.clear()


# ---------------------------------------------------------------- registry ---
_attached = []  # list of _Highlighter; weakref-like via sip.isdeleted checks

def _attach_if_needed(page, dock=None):
    if page is None:
        return
    ed = getattr(page, "editor", None)
    if ed is None:
        _dbg(dock, "attach_if_needed: no editor")
        return
    existing = getattr(ed, "_sel_highlighter", None)
    if existing is not None:
        _dbg(dock, "attach_if_needed: SKIP, attr exists=%r" % existing)
        return
    h = _Highlighter(ed, dock, page)
    ed._sel_highlighter = h
    _attached.append(h)
    _dbg(dock, "attach_if_needed: appended, total=%d" % len(_attached))

def _rescan_all():
    for h in list(_attached):
        try:
            if sip is not None and sip.isdeleted(h.editor):
                _attached.remove(h)
                continue
        except Exception:
            pass
        h.reload_indicator()

def _attach_all(dock):
    count = 0
    try:
        for i in range(dock.tabs.count()):
            page = dock.tabs.widget(i)
            if page is not None:
                ed = getattr(page, "editor", None)
                if ed is not None and hasattr(ed, "_sel_highlighter"):
                    try:
                        if ed._sel_highlighter:
                            ed._sel_highlighter.detach()
                    except Exception:
                        pass
                    ed._sel_highlighter = None
                _attach_if_needed(page, dock)
                if ed is not None and getattr(ed, "_sel_highlighter", None) is not None:
                    count += 1
    except Exception as e:
        _dbg(dock, "attach_all err: %s" % e)
    _dbg(dock, "attach_all: %d tabs attached" % count)

# ---------------------------------------------------------------- hooks ------
def _on_startup(dock):
    _attach_all(dock)

def _on_tab_changed(dock, page):
    _attach_if_needed(page, dock)

def _on_file_opened(dock, page, path):
    _attach_if_needed(page, dock)

def _detach_all_from_dock(dock):
    """Walk all tabs, detach any highlighter found. Doesn't rely on _attached list."""
    count = 0
    try:
        for i in range(dock.tabs.count()):
            page = dock.tabs.widget(i)
            if page is None:
                continue
            ed = getattr(page, "editor", None)
            if ed is None:
                continue
            h = getattr(ed, "_sel_highlighter", None)
            if h is not None:
                try:
                    h.detach()
                except Exception:
                    pass
                ed._sel_highlighter = None
                count += 1
    except Exception:
        pass
    _attached.clear()
    return count

def _detach_all():
    for h in list(_attached):
        try:
            h.detach()
            if hasattr(h.editor, "_sel_highlighter"):
                h.editor._sel_highlighter = None
        except Exception:
            pass
    _attached.clear()

def _on_enable(dock):
    _dbg(dock, "on_enable fired")
    _attach_all(dock)

def _on_disable(dock):
    count = _detach_all_from_dock(dock)
    _dbg(dock, "on_disable fired, detached %d (list was %d)" % (count, len(_attached)))

def _on_shutdown(dock):
    _detach_all_from_dock(dock)

# ---------------------------------------------------------------- settings --
class _SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Selection Highlighter  v" + __version__)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.cb_case = QCheckBox("Case sensitive")
        self.cb_case.setChecked(_get("case_sensitive"))
        form.addRow(self.cb_case)

        self.cb_word = QCheckBox("Whole word only")
        self.cb_word.setChecked(_get("whole_word"))
        form.addRow(self.cb_word)

        self.cb_multi = QCheckBox("Skip multi-line selections")
        self.cb_multi.setChecked(_get("skip_multiline"))
        form.addRow(self.cb_multi)

        self.cb_active = QCheckBox("Include active selection in highlights")
        self.cb_active.setChecked(_get("include_active"))
        form.addRow(self.cb_active)

        self.cb_comments = QCheckBox("Exclude comments from highlights")
        self.cb_comments.setChecked(_get("exclude_comments"))
        form.addRow(self.cb_comments)

        self.cb_debug = QCheckBox("Debug output to Messages panel")
        self.cb_debug.setChecked(_get("debug"))
        form.addRow(self.cb_debug)

        self.sp_min = QSpinBox()
        self.sp_min.setRange(1, 50)
        self.sp_min.setValue(_get("min_length"))
        form.addRow("Min selection length:", self.sp_min)

        self.sp_alpha = QSpinBox()
        self.sp_alpha.setRange(20, 255)
        self.sp_alpha.setValue(_get("alpha"))
        form.addRow("Highlight opacity (20-255):", self.sp_alpha)

        row = QHBoxLayout()
        self._color = QColor(_get("color"))
        self.lbl_color = QLabel()
        self._refresh_swatch()
        btn_color = QPushButton("Pick colour…")
        btn_color.clicked.connect(self._pick_color)
        row.addWidget(self.lbl_color, 1)
        row.addWidget(btn_color)
        form.addRow("Highlight colour:", self._wrap(row))

        lay.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _wrap(self, layout):
        from qgis.PyQt.QtWidgets import QWidget
        w = QWidget()
        w.setLayout(layout)
        return w

    def _refresh_swatch(self):
        self.lbl_color.setAutoFillBackground(True)
        self.lbl_color.setMinimumHeight(22)
        self.lbl_color.setText("  " + self._color.name().upper())
        self.lbl_color.setStyleSheet(
            "background: %s; border: 1px solid #555; color: %s;" %
            (self._color.name(), "#000" if self._color.lightness() > 128 else "#fff")
        )

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Highlight colour")
        if c.isValid():
            self._color = c
            self._refresh_swatch()

    def _save(self):
        _set("case_sensitive", self.cb_case.isChecked())
        _set("whole_word", self.cb_word.isChecked())
        _set("skip_multiline", self.cb_multi.isChecked())
        _set("include_active", self.cb_active.isChecked())
        _set("exclude_comments", self.cb_comments.isChecked())
        _set("debug", self.cb_debug.isChecked())
        _set("min_length", self.sp_min.value())
        _set("alpha", self.sp_alpha.value())
        _set("color", self._color.name())
        _rescan_all()
        self.accept()

def _settings_dialog(dock):
    dlg = _SettingsDialog(dock)
    dlg.exec_()

# ---------------------------------------------------------------- register ---
def register():
    return {
        "id": "selection_highlighter",
        "name": "Selection Highlighter  v" + __version__,
        "description": "Highlights all occurrences of the selected text on the current page.",
        "core": False,
        "builtin": False,
        "hooks": {
            "on_startup": _on_startup,
            "on_shutdown": _on_shutdown,
            "on_enable": _on_enable,
            "on_disable": _on_disable,
            "on_tab_changed": _on_tab_changed,
            "on_file_opened": _on_file_opened,
            "settings_dialog": _settings_dialog,
        },
    }
