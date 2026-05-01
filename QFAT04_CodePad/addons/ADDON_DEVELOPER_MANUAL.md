# QFAT04 CodePad-- Addon Developer Manual

*Document version: v1.0.43*

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Register Dict Fields](#register-dict-fields)
4. [Hook Reference](#hook-reference)
5. [Addon Helper API (100 methods)](#addon-helper-api)
6. [QScintilla Editor Reference](#qscintilla-editor-reference)
7. [Scintilla Indicator System](#scintilla-indicator-system)
8. [Style-Based Token Detection](#style-based-token-detection)
9. [Per-Editor State Pattern](#per-editor-state-pattern)
10. [Enable / Disable Lifecycle](#enable--disable-lifecycle)
11. [Language Definition Structure](#language-definition-structure)
12. [Importing From Other Addons](#importing-from-other-addons)
13. [Storing Addon Settings](#storing-addon-settings)
14. [Guarding Against Deleted Qt Objects](#guarding-against-deleted-qt-objects)
15. [Floating Window Mode](#floating-window-mode)
16. [Addon Manager UI](#addon-manager-ui)
17. [Versioning Convention](#versioning-convention)
18. [Complete Examples](#complete-examples)
19. [Critical Rules](#critical-rules)
20. [Troubleshooting](#troubleshooting)

---

## 1. Overview

QFAT04 addons are single `.py` files placed in the `addons/` folder. Each addon is self-contained — no changes to core plugin code are needed.

Drop your `.py` file there, open **Addons → Manage Addons → Refresh**, enable it, and restart or reload.

### Architecture

```
QFAT04_CodePad/
├── qfat04_plugin.py       ← QGIS entry (initGui/unload)
├── qfat04_dock.py          ← Main QDockWidget + 100 addon helpers
├── qfat04_config.py        ← QSettings, load/save config, language loading
├── qfat04_editor.py        ← EditorPage, DropTabWidget, QScintilla setup
├── qfat04_addons.py        ← AddonManager: discover, load, fire hooks
├── qfat04_runners.py       ← RunController: QProcess for F5/F6
├── qfat04_dialogs.py       ← All UI dialogs inc. AddonManagerDialog
├── qfat04_languages.py     ← Language detection helpers
└── addons/
    ├── __init__.py
    ├── ADDON_DEV_GUIDE.md
    └── *.py                ← addon files
```

### Key Objects

| Object | Type | Access | Purpose |
|--------|------|--------|---------|
| `dock` | `QFAT04Dock` (QDockWidget) | Passed to all hooks | Main shell, owns all UI |
| `dock.iface` | `QgisInterface` | `dock.iface` | Full QGIS API |
| `dock.config` | `dict` | `dock.config` | Plugin settings |
| `dock.languages` | `dict` | `dock.languages` | All language definitions |
| `dock.tabs` | `DropTabWidget` | `dock.tabs` | Tab bar of editor pages |
| `dock.addon_manager` | `AddonManager` | `dock.addon_manager` | Addon registry + hooks |
| `dock.inner_window` | `QMainWindow` | `dock.inner_window` | Hosts toolbar, menus, panels |
| `page` | `EditorPage` | `dock.current_page()` | One tab = one page |
| `page.editor` | `QsciScintilla` | `page.editor` | The text editor widget |
| `page.path` | `str` or `None` | `page.path` | File path (None if untitled) |
| `page.language` | `str` | `page.language` | Language key e.g. `"python"` |
| `page.editor_kind` | `str` | `page.editor_kind` | Always `"scintilla"` currently |

---

## 2. Quick Start

```python
"""my_addon.py  v0.1"""
__version__ = "0.1"

def register():
    return {
        "id": "my_addon",
        "name": "My Addon  v" + __version__,
        "description": "What it does.",
        "core": False,
        "builtin": True,
        "hooks": {},
    }
```

Save as `addons/my_addon.py`. That's it.

---

## 3. Register Dict Fields

| Field         | Type | Required | Description |
|---------------|------|----------|-------------|
| `id`          | str  | Yes      | Unique identifier. Must match filename without `.py`. |
| `name`        | str  | Yes      | Display name in Addon Manager. Include version. |
| `description` | str  | Yes      | Short description shown in Addon Manager. |
| `core`        | bool | No       | Auto-enabled on first install. User can still disable. Default `False`. |
| `builtin`     | bool | No       | Ships with the plugin (informational). |
| `hooks`       | dict | Yes      | Maps hook names to callbacks. |

### Core Addons

`"core": True` means auto-enabled on first install. Users **can disable** — tracked in `disabled_core_addons` QSettings so reinstalls won't re-enable.

---

## 4. Hook Reference

### Lifecycle Hooks

| Hook | Signature | When |
|------|-----------|------|
| `on_startup` | `fn(dock)` | Once, after UI + addon loading complete |
| `on_shutdown` | `fn(dock)` | Plugin unload / QGIS exit |
| `on_enable` | `fn(dock)` | User enables addon in Addon Manager *(v1.0.42+)* |
| `on_disable` | `fn(dock)` | User disables addon in Addon Manager *(v1.0.42+)* |

**Critical:** If your addon connects to QGIS signals, disconnect in `on_shutdown` and `on_disable`. Store handler references:

```python
_write_handler = None

def _on_startup(dock):
    global _write_handler
    _write_handler = lambda _doc=None: _save_state(dock)
    QgsProject.instance().writeProject.connect(_write_handler)

def _on_shutdown(dock):
    global _write_handler
    if _write_handler is not None:
        try:
            QgsProject.instance().writeProject.disconnect(_write_handler)
        except Exception:
            pass
        _write_handler = None
```

### Event Hooks

| Hook | Signature | When |
|------|-----------|------|
| `on_file_opened` | `fn(dock, page, path)` | After file opened |
| `on_file_saved` | `fn(dock, page, path)` | After file saved |
| `on_tab_changed` | `fn(dock, page)` | Active tab switched. `page` may be `None`. |

### UI Hooks

| Hook | Type | When |
|------|------|------|
| `editor_context_builder` | `fn(dock, menu) → bool` | Right-click in editor |
| `panel` | `fn(dock) → {"id","title","widget","area"}` | Startup — create dock panel |
| `main_menu` | `list[{"name","callback"}]` | Addons menu built |
| `toolbar_button` | `list[{"name","callback"}]` | Startup — add toolbar buttons |
| `statusbar_widget` | `fn(dock) → QWidget` | Startup — add to statusbar |
| `shortcuts` | `list[{"key","name","addon","callback"}]` | Startup — register shortcuts |
| `settings_dialog` | `fn(dock)` | "Settings..." in Addon Manager |
| `language_editor_tab` | fn | Language Editor opened (advanced) |

### Run Hooks

| Hook | Signature | When |
|------|-----------|------|
| `run_handler` | `fn(dock, page) → bool` | F5. Return `True` to claim. **Check extension first.** |
| `pre_run` | `fn(dock, page) → bool` | After run_handler, before save. Return `False` to cancel. |

---

## 5. Addon Helper API

All 100 methods live on `dock`. Call as `dock.method_name(...)`. All accept `None` for page arguments safely.

### #1–6: Language & Comment

| # | Method | Returns | Description |
|---|--------|---------|-------------|
| 1 | `get_comment_chars(page)` | `([prefixes], block_open, block_close)` | Comment chars for page's language |
| 2 | `get_language_def(page)` | `dict` | Full language definition dict |
| 3 | `get_all_page_text(page)` | `str` | Full text, safe for both backends |
| 4 | `get_selection_info(page)` | `(text, l1, c1, l2, c2)` or `None` | Selected text + range |
| 5 | `get_byte_offset(page, line, col)` | `int` | Byte offset for Scintilla ops. Alias for `char_to_byte_pos`. |
| 6 | `is_comment_style(page, byte_pos)` | `bool` | True if position is in a comment (styles 1,2,3,12,15) |

### #7–18: Cursor, Navigation, Indicators

| # | Method | Returns | Description |
|---|--------|---------|-------------|
| 7 | `get_word_at_cursor(page)` | `str` | Word under cursor |
| 8 | `get_line_at_cursor(page)` | `(line_num, text)` | 0-based line + text |
| 9 | `get_file_ext(page)` | `str` | Lowercase extension with dot, or `""` |
| 10 | `get_all_pages()` | `list[EditorPage]` | All open pages |
| 11 | `get_page_by_path(path)` | `EditorPage` or `None` | Find page by file path |
| 12 | `set_selection(page, l1, c1, l2, c2)` | — | Set selection range (0-based) |
| 13 | `insert_text(page, text)` | — | Insert at cursor |
| 14 | `goto_line(page, line)` | — | Move cursor + scroll (0-based) |
| 15 | `get_visible_range(page)` | `(first, last)` | Currently visible line range |
| 16 | `is_modified_any()` | `bool` | Any tab has unsaved changes |
| 17 | `get_indicator_range()` | `(20, 31)` | Addon-safe indicator number range |
| 18 | `flash_line(page, line, duration_ms=300)` | — | Brief highlight using indicator 19 |

### #19–40: File Metadata, Search, Bookmarks, Utilities

| # | Method | Returns | Description |
|---|--------|---------|-------------|
| 19 | `get_encoding(page)` | `str` | File encoding, e.g. `"utf-8"` |
| 20 | `get_eol(page)` | `str` | `"CRLF"` or `"LF"` |
| 21 | `get_tab_index(page)` | `int` | Index in tab bar, or -1 |
| 22 | `get_tab_title(page)` | `str` | Displayed tab title |
| 23 | `get_editor_backend(page)` | `str` | `"scintilla"` or other |
| 24 | `get_zoom_level()` | `int` | Current zoom level |
| 25 | `get_theme_colors()` | `dict` | Current theme colors (bg, fg, comment, keyword...) |
| 26 | `get_font()` | `QFont` | Current editor font |
| 27 | `get_line_count(page)` | `int` | Total lines |
| 28 | `get_char_count(page)` | `int` | Total characters |
| 29 | `get_cursor_position(page)` | `(line, col)` | 0-based cursor position |
| 30 | `find_text_in_page(page, text, case=False, regex=False)` | `list[(line,col,length)]` | Find all matches |
| 31 | `replace_in_page(page, old, new, case=False, all_occurrences=False)` | `int` | Count replaced |
| 32 | `get_folded_lines(page)` | `list[int]` | Folded line numbers |
| 33 | `toggle_fold(page, line)` | — | Fold/unfold at line |
| 34 | `get_bookmarks(page)` | `list[int]` | Bookmarked line numbers (marker 1) |
| 35 | `set_bookmark(page, line, on=True)` | — | Add/remove bookmark |
| 36 | `get_open_paths()` | `list[str]` | All open file paths (excl. untitled) |
| 37 | `close_page(page, force=False)` | — | Close tab. `force` skips save prompt. |
| 38 | `run_in_console(code_str)` | `(stdout, stderr)` | Execute Python in QGIS context |
| 39 | `get_addon_panel(addon_id)` | `QDockWidget` or `None` | Panel for an addon |
| 40 | `show_notification(msg, timeout=3000)` | — | Brief statusbar message, auto-clears |

### #41–52: Language Definition Accessors

| # | Method | Returns | Description |
|---|--------|---------|-------------|
| 41 | `get_keywords_by_group(page, group=None)` | `list[str]` | Keywords. `None` = all groups. |
| 42 | `get_keyword_groups(page)` | `list[dict]` | `[{"name":..., "words":[...]}]` |
| 43 | `get_operators(page)` | `list[str]` | Operator strings |
| 44 | `get_delimiters(page)` | `list[dict]` | `{"open","close","escape"}` |
| 45 | `get_variable_patterns(page)` | `list[str]` | Regex patterns for variables |
| 46 | `get_path_pattern(page)` | `str` | Regex for file paths, or `""` |
| 47 | `get_lang_extensions(page)` | `list[str]` | File extensions for the language |
| 48 | `get_base_engine(page)` | `str` | Base syntax engine (`"python"`, `"batch"`, ...) |
| 49 | `is_case_sensitive(page)` | `bool` | Language case sensitivity |
| 50 | `get_number_style(page)` | `dict` or `None` | Number highlighting config |
| 51 | `get_prefix_modes(page)` | `dict` | Prefix mode definitions |
| 52 | `get_fold_rules(page)` | `dict` | Folding config |

### #53–75: Scintilla Style, Tokens, Indicators, Byte Ops

| # | Method | Returns | Description |
|---|--------|---------|-------------|
| 53 | `get_style_at(page, byte_pos)` | `int` | Lexer style ID at byte position |
| 54 | `is_string_style(page, byte_pos)` | `bool` | True if inside string literal (styles 4,6,7,3,13) |
| 55 | `is_keyword_style(page, byte_pos)` | `bool` | True if on a keyword (styles 5,8,14) |
| 56 | `get_token_at_cursor(page)` | `(text, style_id, start_col, end_col)` or `None` | Token under cursor |
| 57 | `get_all_tokens_in_line(page, line)` | `list[(text, style_id)]` | All tokens in a line |
| 58 | `get_style_map(page)` | `dict{int: str}` | Style IDs → descriptive names |
| 59 | `get_margin_width(page, margin_num)` | `int` | Margin pixel width |
| 60 | `set_margin_width(page, margin_num, width)` | — | Set margin width |
| 61 | `add_margin_marker(page, line, marker_num)` | `int` | Add marker, returns handle |
| 62 | `clear_margin_markers(page, marker_num)` | — | Clear all markers of type |
| 63 | `get_annotation(page, line)` | `str` | Annotation text at line |
| 64 | `set_annotation(page, line, text, style=None)` | — | Set annotation at line |
| 65 | `clear_annotations(page)` | — | Remove all annotations |
| 66 | `send_scintilla(page, msg, wparam=0, lparam=0)` | result or `None` | Safe SendScintilla wrapper |
| 67 | `get_text_range(page, start_pos, end_pos)` | `str` | Text between byte positions |
| 68 | `char_to_byte_pos(page, line, col)` | `int` | Byte offset for (line, col) |
| 69 | `byte_to_char_pos(page, byte_pos)` | `(line, col)` | Line/col from byte offset |
| 70 | `get_line_byte_start(page, line)` | `int` | Byte offset where line starts |
| 71 | `get_document_bytes(page)` | `int` | Total byte length |
| 72 | `get_lexer_language(page)` | `str` | QScintilla lexer name |
| 73 | `get_all_language_keys()` | `list[str]` | All registered language keys |
| 74 | `get_language_display_name(lang_key)` | `str` | Human-readable language name |
| 75 | `register_indicator(addon_id, indicator_num)` | `bool` | Claim indicator. False = collision. |

### #76–85: Extended Helpers

| # | Method | Returns | Description |
|---|--------|---------|-------------|
| 76 | `get_language_for_ext(ext)` | `str` | Language key for extension |
| 77 | `highlight_range(page, l1, c1, l2, c2, indicator_num)` | — | Fill indicator between positions |
| 78 | `clear_indicator(page, indicator_num)` | — | Clear all of an indicator in doc |
| 79 | `get_modified_pages()` | `list[EditorPage]` | Pages with unsaved changes |
| 80 | `get_untitled_pages()` | `list[EditorPage]` | Pages with no path |
| 81 | `get_text_under_cursor(page, pattern=r"\w+")` | `str` | Regex-configurable word grab |
| 82 | `get_lines(page, start, end)` | `list[str]` | Line texts for range [start, end) |
| 83 | `batch_operation(page, fn)` | — | Wrap `fn(page)` in undo group |
| 84 | `get_project_dir()` | `str` or `None` | QGIS project directory |
| 85 | `is_addon_enabled(addon_id)` | `bool` | Check if addon is enabled |

### #86–100: Indent, Config, Convenience

| # | Method | Returns | Description |
|---|--------|---------|-------------|
| 86 | `get_indent_at_line(page, line)` | `str` | Leading whitespace string |
| 87 | `get_indent_level(page, line)` | `int` | Indent depth (normalized) |
| 88 | `get_tab_width()` | `int` | Configured tab width |
| 89 | `get_sibling_files(page)` | `list[str]` | Files in same directory |
| 90 | `get_recently_opened()` | `list[str]` | Recent file paths |
| 91 | `get_active_addons()` | `list[str]` | Enabled addon IDs |
| 92 | `get_addon_registry()` | `dict` | Deep copy of addon registry |
| 93 | `is_scintilla(page)` | `bool` | True if QScintilla editor |
| 94 | `get_lexer(page)` | `QsciLexer` or `None` | Current lexer instance |
| 95 | `get_line_indent_guide_visible()` | `bool` | Indent guides shown |
| 96 | `get_wrap_mode()` | `bool` | Word wrap enabled |
| 97 | `get_matching_brace(page)` | `(line, col)` or `None` | Matching brace position |
| 98 | `select_line(page, line)` | — | Select entire line |
| 99 | `select_word(page)` | — | Select word under cursor |
| 100 | `duplicate_selection(page)` | — | Duplicate selection or current line |

### Pre-existing helpers (before v1.0.43)

These were available before the 100-helper API:

| Method | Description |
|--------|-------------|
| `current_page()` | Active EditorPage or None |
| `current_editor()` | Active editor widget or None |
| `new_tab(path=None)` | Open new tab |
| `open_paths([path1, ...])` | Open multiple files |
| `scroll_editor(line, center=False)` | Scroll to line (1-based) |
| `scroll_editor_h(col)` | Horizontal scroll |
| `get_scroll_position()` | `(first_visible_line, h_offset)` |
| `set_scroll_position(line, h_offset)` | Restore scroll |
| `get_panel(panel_id)` | QDockWidget for a panel |
| `get_panel_size(panel_id)` | `(width, height)` |
| `set_panel_size(panel_id, w, h)` | Set panel size |

### Output Panels

```python
dock.console.append("Console message")         # Console panel
dock.messages.append("Status message")         # Messages — preferred for addons
dock.find_results.append("Find result")        # Find Results panel
```

---

## 6. QScintilla Editor Reference

`page.editor` is a `QsciScintilla` subclass, **not** QTextEdit. Use the correct APIs:

| Task | Use | Don't use |
|------|-----|-----------|
| Full text | `editor.text()` or `editor.editor_text()` | `toPlainText()` |
| Selected text | `editor.selectedText()` | `textCursor().selectedText()` |
| Line text | `editor.text(line_num)` (0-based) | `document().findBlockByNumber()` |
| Cursor pos | `editor.getCursorPosition()` → `(line, col)` | `textCursor().blockNumber()` |
| Selection range | `editor.getSelection()` → `(l1, c1, l2, c2)` | `textCursor().selectionStart()` |
| Selection signal | `editor.selectionChanged` | — |
| Cursor signal | `editor.cursorPositionChanged` | — |
| Scroll signal | `editor.verticalScrollBar().valueChanged` | — |
| Low-level | `editor.SendScintilla(SCI_*, w, l)` | — |

### Check editor kind first

```python
if dock.is_scintilla(page):
    line, col = page.editor.getCursorPosition()
```

### SendScintilla Binding Quirks

- Passing `bytes` as `lParam` is **unreliable** in PyQt. `SCI_SEARCHINTARGET` fails silently.
- **Workaround**: use Python string search + integer offsets via `dock.char_to_byte_pos()`.
- Prefer `editor.findFirst()` / `findNext()` over raw `SCI_SEARCHINTARGET`.

---

## 7. Scintilla Indicator System

Indicators (0–31) are shared. Collisions overwrite each other.

### Allocation

| Range | Purpose |
|-------|---------|
| 0–7 | Scintilla built-in / lexer (reserved) |
| 8–19 | Core plugin (search, find, match-brace, flash) |
| 20–31 | Addons — use `dock.register_indicator("my_id", 29)` |

### Setup

```python
_IND = 29
dock.register_indicator("my_addon", _IND)

ed = page.editor
col = QColor("#FFD54F")
bgr = (col.blue() << 16) | (col.green() << 8) | col.red()  # Note: BGR
ed.SendScintilla(2080, _IND, 7)     # SCI_INDICSETSTYLE → INDIC_ROUNDBOX
ed.SendScintilla(2082, _IND, bgr)   # SCI_INDICSETFORE
ed.SendScintilla(2523, _IND, 110)   # SCI_INDICSETALPHA
```

### Fill / Clear

```python
ed.SendScintilla(2500, _IND)                          # SCI_SETINDICATORCURRENT
ed.SendScintilla(2504, byte_start, byte_length)        # SCI_INDICATORFILLRANGE
ed.SendScintilla(2505, byte_start, byte_length)        # SCI_INDICATORCLEARRANGE
```

Or use the high-level helpers:

```python
dock.highlight_range(page, line1, col1, line2, col2, _IND)
dock.clear_indicator(page, _IND)
```

**Positions are byte offsets**, not character offsets. Use:

```python
byte_start = dock.char_to_byte_pos(page, line, col)
```

---

## 8. Style-Based Token Detection

Use the lexer's style assignment to identify token types:

```python
style = dock.get_style_at(page, byte_pos)

# Or use convenience methods:
dock.is_comment_style(page, byte_pos)   # styles {1, 2, 3, 12, 15}
dock.is_string_style(page, byte_pos)    # styles {4, 6, 7, 3, 13}
dock.is_keyword_style(page, byte_pos)   # styles {5, 8, 14}
```

For a full map of style IDs → names for the current lexer:

```python
style_map = dock.get_style_map(page)
# → {0: "Default", 1: "Comment", 5: "Keyword", ...}
```

Get all tokens in a line:

```python
tokens = dock.get_all_tokens_in_line(page, line_num)
# → [("def", 5), (" ", 0), ("my_func", 11), ("(", 10), ...]
```

**Note:** Style IDs vary per lexer. The convenience methods use common IDs that work for most languages but aren't universal.

---

## 9. Per-Editor State Pattern

When an addon tracks per-tab state, attach it to the editor widget:

```python
def _attach_if_needed(page, dock):
    ed = getattr(page, "editor", None)
    if ed is None or getattr(ed, "_my_addon_state", None) is not None:
        return
    ed._my_addon_state = MyState(ed, dock)
```

### Stale Attributes Across Plugin Reload

On reload, old `_my_addon_state` **persists** on the editor widget. Clear in `on_startup`:

```python
def _attach_all(dock):
    for page in dock.get_all_pages():
        ed = getattr(page, "editor", None)
        if ed is not None and hasattr(ed, "_my_addon_state"):
            try:
                ed._my_addon_state.detach()
            except Exception:
                pass
            ed._my_addon_state = None
        _attach_if_needed(page, dock)
```

---

## 10. Enable / Disable Lifecycle

*(v1.0.42+)*

The Addon Manager fires `on_enable` / `on_disable` hooks when the user toggles and clicks OK. Signal-based addons can wire/unwire cleanly:

```python
_handlers = {}

def _attach_to(page):
    ed = getattr(page, "editor", None)
    if ed is None or id(ed) in _handlers:
        return
    h = lambda: _on_selection_changed(ed)
    ed.selectionChanged.connect(h)
    _handlers[id(ed)] = (ed, h)

def _detach_all():
    for eid, (ed, h) in list(_handlers.items()):
        try:
            ed.selectionChanged.disconnect(h)
        except Exception:
            pass
    _handlers.clear()

def register():
    return {
        "id": "my_highlighter",
        "hooks": {
            "on_startup": lambda dock: [_attach_to(p) for p in dock.get_all_pages()],
            "on_shutdown": lambda dock: _detach_all(),
            "on_enable": lambda dock: [_attach_to(p) for p in dock.get_all_pages()],
            "on_disable": lambda dock: _detach_all(),
            "on_file_opened": lambda dock, page, path: _attach_to(page),
        },
    }
```

### Addon Manager Status Column

| Status | Meaning |
|--------|---------|
| `✓ Live` (green) | Addon has `on_enable`/`on_disable` — change is immediate |
| `⚠ Restart` (orange) | Lacks those hooks — QGIS restart needed |

### What Hooks Don't Do

`on_enable`/`on_disable` do **not** remove panels, toolbar buttons, or modules from `sys.modules`. For those, restart is still needed.

---

## 11. Language Definition Structure

`dock.languages` is a dict keyed by language key (e.g. `"python"`, `"tuflow"`).

### Key Fields

| Field | Type | Example |
|-------|------|---------|
| `default_name` | str | `"Python"` |
| `base` | str | `"python"` — syntax engine |
| `extensions` | list | `[".py", ".pyw"]` |
| `case_sensitive` | bool | `True` |
| `comment_prefixes` | list | `["#"]` |
| `block_comment_open` | str | `""` (or `"/*"` for C-like) |
| `block_comment_close` | str | `""` (or `"*/"` for C-like) |
| `keyword_groups` | list | `[{"name":"Built-in","words":["def","class",...]}]` |
| `operators1` | list | `["+", "-", "=", ...]` |
| `delimiters` | list | `[{"open":"(", "close":")", "escape":""}]` |
| `variable_patterns` | list | Regex patterns for variables |
| `path_pattern` | str | Regex for file path detection |
| `folding` | dict | Fold rule config |
| `number_style` | dict | Number highlighting config |
| `prefix_modes` | dict | Prefix mode definitions |

### Accessing

```python
lang = dock.get_language_def(page)         # full dict
prefixes, bopen, bclose = dock.get_comment_chars(page)  # comment chars
keywords = dock.get_keywords_by_group(page)              # all keywords
keywords_g0 = dock.get_keywords_by_group(page, 0)       # first group only
ops = dock.get_operators(page)                            # operators
```

---

## 12. Importing From Other Addons

Addons are loaded via `importlib.util.spec_from_file_location` — not as a package. Relative imports work inconsistently.

**Bulletproof pattern:**

```python
try:
    from .fuzzy_loader import extract_fuzzy_paths
    _HAS_DEP = True
except ImportError:
    try:
        import sys, os, importlib.util
        _path = os.path.join(os.path.dirname(__file__), "fuzzy_loader.py")
        _mod = sys.modules.get("fuzzy_loader")
        if _mod is None and os.path.exists(_path):
            _spec = importlib.util.spec_from_file_location("fuzzy_loader", _path)
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
        extract_fuzzy_paths = _mod.extract_fuzzy_paths
        _HAS_DEP = True
    except Exception:
        _HAS_DEP = False
```

Then gracefully handle the missing dependency:

```python
if not _HAS_DEP:
    act = menu.addAction("Requires Fuzzy Loader addon")
    act.setEnabled(False)
    return True
```

---

## 13. Storing Addon Settings

Use `QSettings()` with a unique prefix:

```python
from qgis.PyQt.QtCore import QSettings

_S_ROOT = "QFAT/QFAT04/addon_myaddon/"
s = QSettings()
s.setValue(_S_ROOT + "some_key", value)
value = s.value(_S_ROOT + "some_key", default, type=str)
```

### QSettings Location for Enabled Addons

```python
QSettings().value("QFAT/QFAT04/enabled_addons")
# → "fuzzy_loader|python_console|tab_restore|..."
```

Or use: `dock.is_addon_enabled("my_addon")` / `dock.get_active_addons()`.

---

## 14. Guarding Against Deleted Qt Objects

If your addon connects to QGIS-level signals, they may fire **after** plugin unload. Accessing `dock.tabs` at that point raises `RuntimeError: wrapped C/C++ object has been deleted`.

```python
def _is_dock_alive(dock):
    try:
        from qgis.PyQt import sip
    except ImportError:
        try:
            import sip
        except ImportError:
            return True
    try:
        if sip.isdeleted(dock) or sip.isdeleted(dock.tabs):
            return False
    except Exception:
        return False
    return True

def _on_write_project(dock):
    if not _is_dock_alive(dock):
        return
    # safe to access dock.tabs, dock.messages...
```

---

## 15. Floating Window Mode

*(v1.0.28+)*

CodePad can detach to a standalone window (like QGIS attribute table).

```python
dock.is_floating_window()     # True if detached
dock.detach_to_window()       # Switch to floating
dock.reattach_to_dock()       # Switch back
dock._floating_window         # CodePadFloatingWindow or None
```

Settings persisted: `display_mode`, `always_on_top`, `floating_geometry`, `dock_area`, `dock_size`.

---

## 16. Addon Manager UI

The Addon Manager dialog has 5 columns:

| Column | Content |
|--------|---------|
| **On** (✓) | Checkbox. Sortable — groups enabled/disabled. |
| **Addon** | Display name. Core addons in **bold**. |
| **Description** | From `register()`. |
| **Settings** | "Settings..." button if `settings_dialog` hook exists. |
| **Status** | `✓ Live` or `⚠ Restart` when toggled. |

All columns sortable by clicking headers.

---

## 17. Versioning Convention

**Always include the version in TWO places:**

1. `__version__ = "0.3"` at the top of the file
2. In the `register()` name field: `"name": "My Addon  v" + __version__`

**Always increment on every change.** Stale installs are the #1 source of hard-to-diagnose bugs.

---

## 18. Complete Examples

### Example 1: Line Counter Panel

```python
"""line_counter.py  v0.1 — Shows live line count."""
__version__ = "0.1"
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QLabel
from qgis.PyQt.QtCore import Qt

class _Widget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self); layout.setContentsMargins(4,4,4,4)
        self.label = QLabel("No file open"); self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

    def refresh(self, dock, page):
        if not page:
            self.label.setText("No file open"); return
        self.label.setText("%d lines" % dock.get_line_count(page))

_w = _Widget()

def register():
    return {
        "id": "line_counter",
        "name": "Line Counter  v" + __version__,
        "description": "Shows live line count for the active file.",
        "hooks": {
            "panel": lambda dock: {"id":"line_counter","title":"Lines","widget":_w,"area":"bottom"},
            "on_tab_changed": lambda dock, page: _w.refresh(dock, page),
            "on_file_saved": lambda dock, page, path: _w.refresh(dock, page),
            "on_startup": lambda dock: _w.refresh(dock, dock.current_page()),
        },
    }
```

### Example 2: Selection Highlighter with Live Enable/Disable

```python
"""selection_highlight.py  v0.1 — Highlight all matches of selected word."""
__version__ = "0.1"
from qgis.PyQt.QtGui import QColor

_IND = 29
_handlers = {}

def _setup_indicator(ed):
    col = QColor("#FFD54F")
    bgr = (col.blue() << 16) | (col.green() << 8) | col.red()
    ed.SendScintilla(2080, _IND, 7)    # ROUNDBOX
    ed.SendScintilla(2082, _IND, bgr)
    ed.SendScintilla(2523, _IND, 110)

def _on_sel_changed(dock, page, ed):
    dock.clear_indicator(page, _IND)
    word = dock.get_word_at_cursor(page)
    if not word or len(word) < 2:
        return
    for line, col, length in dock.find_text_in_page(page, word, case=True):
        byte_start = dock.char_to_byte_pos(page, line, col)
        ed.SendScintilla(2500, _IND)
        ed.SendScintilla(2504, byte_start, len(word.encode("utf-8")))

def _attach(page, dock):
    ed = getattr(page, "editor", None)
    if ed is None or id(ed) in _handlers:
        return
    dock.register_indicator("selection_highlight", _IND)
    _setup_indicator(ed)
    h = lambda: _on_sel_changed(dock, page, ed)
    ed.selectionChanged.connect(h)
    _handlers[id(ed)] = (ed, h)

def _detach_all():
    for eid, (ed, h) in list(_handlers.items()):
        try: ed.selectionChanged.disconnect(h)
        except: pass
    _handlers.clear()

def _enable(dock):
    for p in dock.get_all_pages():
        _attach(p, dock)

def register():
    return {
        "id": "selection_highlight",
        "name": "Selection Highlighter  v" + __version__,
        "description": "Highlight all occurrences of selected word. Supports live toggle.",
        "hooks": {
            "on_startup": _enable,
            "on_shutdown": lambda dock: _detach_all(),
            "on_enable": _enable,
            "on_disable": lambda dock: _detach_all(),
            "on_file_opened": lambda dock, page, path: _attach(page, dock),
        },
    }
```

### Example 3: Comment-Aware Run Handler

```python
"""tuflow_runner.py  v0.1 — Custom F5 for TUFLOW .tcf files."""
__version__ = "0.1"
import os, subprocess

def _run(dock, page):
    if page is None:
        return False
    ext = dock.get_file_ext(page)
    if ext not in {".tcf", ".tgc", ".ecf"}:
        return False
    # Get comment prefix for current language
    prefixes, _, _ = dock.get_comment_chars(page)
    prefix = prefixes[0] if prefixes else "!"
    dock.show_notification("Running TUFLOW: %s" % os.path.basename(page.path))
    # ... launch logic ...
    return True

def register():
    return {
        "id": "tuflow_runner",
        "name": "TUFLOW Runner  v" + __version__,
        "description": "Custom F5 for TUFLOW control files.",
        "hooks": {"run_handler": _run},
    }
```

---

## 19. Critical Rules

1. **Disconnect all signals in `on_shutdown` and `on_disable`.** Store handler references; disconnect specifically. Never `signal.disconnect()` with no args.

2. **Guard with `sip.isdeleted()`** before accessing dock widgets in deferred callbacks.

3. **Never create signal/timer connections in repeatedly-called code** unless proven non-duplicating.

4. **Only claim your file types in `run_handler`.** Check extension before returning `True`.

5. **Always increment the version** on every change.

6. **Wrap addon-to-addon imports in try/except** with the bulletproof pattern.

7. **Use `QSettings()` with unique prefix** like `QFAT/QFAT04/addon_<id>/`.

8. **Use `dock.messages.append()`** for output, not `print()`.

9. **Signal-based addons should implement `on_enable`/`on_disable`.** Without them, disable has no effect until restart.

10. **Don't pass `bytes` as lParam to `SendScintilla`.** Compute positions in Python, pass integer offsets.

11. **Reserve indicator numbers ≥ 20 for addons.** Use `dock.register_indicator()`. Document the number in your module header.

---

## 20. Troubleshooting

| Problem | Solution |
|---------|----------|
| Addon not showing up | Click Refresh in Addon Manager. Check QGIS Python console for errors. |
| Hook not firing | Check addon is enabled. Core addons auto-enable but can be disabled. |
| Import errors from other addons | Use the bulletproof import pattern. |
| `TypeError: takes N args but M given` | Stale install. Reinstall + increment version. |
| Panel not appearing | `panel` hook runs at startup only. Restart after enabling. |
| Settings not saving | Use `QSettings()` with unique key prefix. |
| Context menu blank | `editor_context_builder` returned `False`. Check detection logic. |
| `RuntimeError: C/C++ object deleted` | Accessing dock after deletion. Use `sip.isdeleted()` guard. |
| F5 runs wrong interpreter | `run_handler` not checking extension. Filter before returning `True`. |
| PowerShell WinError 2 | Not on PATH. Set full path in Preferences → Interpreters → PowerShell. |
| Addon still active after disable | No `on_disable` hook. Add it, or restart QGIS. |
| Highlights overwrite search | Indicator collision. Use number ≥ 20, register with `dock.register_indicator()`. |
| `SendScintilla` returns -1 | Don't pass `bytes` as lParam. Use Python search + integer offsets. |
| Stale per-editor state after reload | Clear `_my_addon_state` in `on_startup` before re-attaching. |
