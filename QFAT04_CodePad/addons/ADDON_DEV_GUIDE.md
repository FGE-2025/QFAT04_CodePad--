# QFAT04 CodePad-- Addon Development Guide

*Document version: matches plugin v1.0.38+*

## Overview

QFAT04 addons are single `.py` files placed in this `addons/` folder. Each addon is self-contained — no changes to core plugin code are needed.

Drop your `.py` file here, open **Addons → Manage Addons → Refresh**, enable it, and restart or reload.

---

## Versioning Convention

**Always include the version in TWO places:**

1. **In the filename:** `my_addon_v0.3.py` (optional but recommended for parallel versions)
2. **Inside the file:** `__version__ = "0.3"` at the top, and reference it in the `register()` `name` field:
   ```python
   __version__ = "0.3"
   ...
   "name": "My Addon  v" + __version__,
   ```

**Always increment the version on every change.** Stale plugin installs in QGIS are a common source of hard-to-diagnose bugs — incrementing the version makes mismatches obvious.

---

## Minimal Addon Template

```python
"""
my_addon.py  v0.1
Short description of what this addon does.
"""
__version__ = "0.1"

def register():
    return {
        "id": "my_addon",                          # Unique ID (must match filename without .py)
        "name": "My Addon  v" + __version__,       # Display name in Addon Manager
        "description": "What it does.",            # Shown in Addon Manager list
        "core": False,                             # True = auto-enabled on first install
        "builtin": True,                           # True = ships with the plugin
        "hooks": {
            # Add the hooks you need (see Hook Reference below)
        },
    }
```

Save as `addons/my_addon.py`. That's it.

---

## Register Dict Fields

| Field         | Type | Required | Description                                                                              |
|---------------|------|----------|------------------------------------------------------------------------------------------|
| `id`          | str  | Yes      | Unique identifier. Must match the filename (without `.py`).                              |
| `name`        | str  | Yes      | Display name shown in Addon Manager. Include the version.                                |
| `description` | str  | Yes      | Short description shown in Addon Manager.                                                |
| `core`        | bool | No       | If `True`, addon is auto-enabled on first install. User can still disable. Default `False`.|
| `builtin`     | bool | No       | If `True`, marks the addon as shipping with the plugin (informational).                  |
| `hooks`       | dict | Yes      | Maps hook names to callbacks. See Hook Reference.                                        |

### Core Addons

When `"core": True`, the addon is added to the enabled list on first install. However, users **can disable** core addons — the plugin tracks this in `disabled_core_addons` QSettings key so a later reinstall won't re-enable them against the user's wishes.

---

## Hook Reference

### `on_startup`
**When:** Once, after the full UI is built and all addons are loaded.
**Signature:** `fn(dock)`

### `on_shutdown`
**When:** Plugin is unloaded (QGIS closing, plugin reload, etc).
**Signature:** `fn(dock)`

**Critical:** If your addon connects to QGIS signals (e.g. `QgsProject.writeProject`), you **must** disconnect them here. Store a reference to your handler so you can disconnect it specifically — never call `signal.disconnect()` with no argument (that disconnects ALL slots from all plugins).

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

### `on_file_opened`
**When:** A file is opened in a new tab.
**Signature:** `fn(dock, page, path)`

### `on_file_saved`
**When:** A file is saved.
**Signature:** `fn(dock, page, path)`

### `on_tab_changed`
**When:** User switches to a different editor tab.
**Signature:** `fn(dock, page)` — `page` is the new active `EditorPage`, or `None`.

### `editor_context_builder`
**When:** User right-clicks in the editor.
**Signature:** `fn(dock, menu) -> bool`
**Return:** `True` if you added items, `False` otherwise.

```python
def _build_menu(dock, menu):
    page = dock.current_page()
    if not page:
        return False
    menu.addAction("My Action", lambda: do_something(dock))
    return True

"hooks": {"editor_context_builder": _build_menu}
```

### `panel`
**When:** Plugin startup (after UI is built).
**Signature:** `fn(dock) -> dict`
**Return:** Dict with panel info.

```python
def _create_panel(dock):
    return {
        "id": "my_panel",          # Unique panel ID
        "title": "My Panel",       # Tab/dock title
        "widget": my_widget,       # QWidget instance
        "area": "bottom",          # "left", "right", "top", or "bottom"
    }

"hooks": {"panel": _create_panel}
```

Bottom panels are tabified with Console. Left panels are tabified with Files.

### `main_menu`
**When:** Addons menu is built.
**Type:** List of dicts.

```python
"hooks": {
    "main_menu": [
        {"name": "Do Something", "callback": lambda dock: do_something(dock)},
    ]
}
```

### `toolbar_button`
**When:** Plugin startup.
**Type:** List of dicts.

```python
"hooks": {
    "toolbar_button": [
        {"name": "My Button", "callback": lambda dock: do_something(dock)},
    ]
}
```

### `statusbar_widget`
**When:** Plugin startup.
**Signature:** `fn(dock) -> QWidget`

### `shortcuts`
**When:** Plugin startup.
**Type:** List of dicts.

```python
"hooks": {
    "shortcuts": [
        {
            "key": "Ctrl+Shift+G",
            "name": "Load GIS Layer",
            "addon": "My Addon",
            "callback": lambda dock: do_something(dock),
        },
    ]
}
```

Shortcuts use `Qt.WidgetWithChildrenShortcut` context — they only fire when focus is inside the QFAT04 dock, so they won't conflict with QGIS global shortcuts.

**User overrides:** Addon shortcuts are surfaced in the **Editor Shortcut Manager** (Settings → Shortcuts…), grouped by addon name. Users can edit, clear, or reset any addon shortcut — overrides persist in QSettings. The `key` in the hook is the **default** — addons should not assume their declared key remains active at runtime.

### `settings_dialog`
**When:** User clicks "Settings..." in Addon Manager (or double-clicks the addon row).
**Signature:** `fn(dock) -> None` (opens a QDialog)

The Addon Manager table shows a "Settings..." button in column 3 for addons that register this hook.

### `run_handler` *(since v1.0.18)*
**When:** User triggers Run (F5), **before** save-first check and runner dispatch.
**Signature:** `fn(dock, page) -> bool`
**Return:** `True` to claim the run (stops all further processing); any other value to pass through.

**Important:** Only claim files your addon knows how to run. Check the extension:

```python
def _run_handler(dock, page):
    import os
    if page is None:
        return False
    if not page.path:
        # Untitled tab — claim if you want to run unsaved buffers
        return False
    ext = os.path.splitext(page.path)[1].lower()
    if ext not in {".py", ".pyw"}:
        return False  # let core handle .ps1, .bat, .r, etc.
    my_custom_runner(dock, page)
    return True
```

If your `run_handler` returns `True` for all files (without checking extension), you will break F5 for every file type. This was the cause of a bug where .ps1 files were incorrectly routed through the Python runner.

### `pre_run` *(since v1.0.18)*
**When:** After `run_handler` hooks, **before** save-first check. Fires only if no `run_handler` claimed the run.
**Signature:** `fn(dock, page) -> bool`
**Return:** `False` to cancel the run; any other value to continue.

### `language_editor_tab` *(advanced)*
**When:** Language Editor dialog is opened.
**Purpose:** Add custom tabs to the language editor.

---

## Dock API Reference

### Current Editor
```python
dock.current_page()                # Active EditorPage, or None
dock.current_page().path           # File path, or None if untitled
dock.current_page().editor         # The QScintilla editor widget
dock.current_page().editor.editor_text()  # Full text content
dock.current_page().editor.selected_text()  # Selected text
dock.current_page().is_modified()  # True if unsaved changes
```

### Tab Management
```python
dock.tabs                           # DropTabWidget (QTabWidget subclass)
dock.tabs.count()                   # Number of open tabs
dock.tabs.widget(i)                 # EditorPage at index i
dock.new_tab(path=None)             # Open a new tab (empty or with file)
dock.open_paths([path1, path2])     # Open multiple files
```

### Config & Languages
```python
dock.config                      # Full config dict
dock.languages                   # All language definitions
dock.config.get("theme", "Dark")
dock.config.get("enabled_addons", [])
```

### Output Panels
```python
dock.console.append("Console message")           # Console panel
dock.messages.append("Status message")           # Messages panel  ← preferred for addon output
dock.find_results.append("Find results entry")   # Find Results panel
```

The **Messages panel** (`dock.messages`) is the right place for addon status output — it doesn't interfere with Python console output, and users can right-click → Clear it.

### Inner Window (advanced panel placement)
```python
dock.inner_window                # QMainWindow inside the dock
dock.inner_window.addDockWidget(Qt.LeftDockWidgetArea, my_dock_widget)
```

### Scroll API
```python
dock.scroll_editor(line, center=True)        # Scroll to line (1-based)
dock.scroll_editor_h(col)                    # Horizontal scroll to column
dock.get_scroll_position()                   # Returns (first_visible_line, h_offset)
dock.set_scroll_position(line, h_offset)     # Restore a saved scroll position
```

### Panel API
```python
dock.get_panel(panel_id)                      # QDockWidget for a panel, or None
dock.get_panel_size(panel_id)                 # Returns (width, height)
dock.set_panel_size(panel_id, width, height)  # Pass None to keep a dimension
```

### QGIS Interface
```python
dock.iface                        # QgisInterface — full QGIS API access
dock.iface.mainWindow()           # QGIS main window
dock.iface.mapCanvas()            # Map canvas
dock.iface.layerTreeView()        # Layer tree / TOC
```

### Floating Window *(since v1.0.28)*
```python
dock.is_floating_window()         # True if detached to standalone window
dock.detach_to_window()           # Switch to floating mode
dock.reattach_to_dock()           # Switch back to docked mode
dock._floating_window             # CodePadFloatingWindow instance (or None)
```

---

## Storing Addon Settings

Use `QSettings()` with a unique prefix to avoid conflicts:

```python
from qgis.PyQt.QtCore import QSettings

_S_ROOT = "QFAT/QFAT04/addon_myaddon/"

s = QSettings()
s.setValue(_S_ROOT + "some_key", value)
value = s.value(_S_ROOT + "some_key", default, type=str)
```

Settings persist in the Windows Registry (or equivalent) and survive plugin upgrades.

---

## Guarding Against Deleted Qt Objects

If your addon connects to QGIS-level signals (like `QgsProject.writeProject`), those signals may fire **after** the plugin is unloaded and the dock widget is destroyed. Accessing `dock.tabs` or `dock.messages` at that point raises `RuntimeError: wrapped C/C++ object has been deleted`.

**Always guard with `sip.isdeleted()`:**

```python
def _is_dock_alive(dock):
    """Check if dock and its tabs widget are still valid Qt objects."""
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
    # ... safe to access dock.tabs, dock.messages, etc.
```

And **always disconnect in `on_shutdown`** using a stored handler reference (see the `on_shutdown` hook section above).

---

## Importing From Other Addons

Addons are loaded via `importlib.util.spec_from_file_location` as **standalone modules**, not as part of a package. Relative imports (`from .other_addon import ...`) **work inconsistently**.

Use this **bulletproof import pattern**:

```python
try:
    from .fuzzy_loader import extract_fuzzy_paths, _get_gis_exts
    _HAS_DEPENDENCY = True
except ImportError:
    try:
        import sys, os, importlib.util
        _other_path = os.path.join(os.path.dirname(__file__), "fuzzy_loader.py")
        _other = sys.modules.get("fuzzy_loader")
        if _other is None and os.path.exists(_other_path):
            _spec = importlib.util.spec_from_file_location("fuzzy_loader", _other_path)
            _other = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_other)
        extract_fuzzy_paths = _other.extract_fuzzy_paths
        _get_gis_exts = _other._get_gis_exts
        _HAS_DEPENDENCY = True
    except Exception:
        _HAS_DEPENDENCY = False
```

Then gracefully handle the missing dependency:

```python
def _build_context_menu(dock, menu):
    if not _HAS_DEPENDENCY:
        act = menu.addAction("My Addon: requires Fuzzy Loader addon")
        act.setEnabled(False)
        return True
    # ... normal logic ...
```

---

## The Addon Manager UI

The Addon Manager (Addons → Manage Addons) displays a table with four columns:

| Column | Content |
|--------|---------|
| **On** (✓) | Checkbox — enable/disable. Sortable by clicking the header. |
| **Addon** | Display name from `register()`. Core addons shown in **bold**. |
| **Description** | From `register()`. |
| **Settings** | "Settings..." button, shown only if `settings_dialog` hook is registered. |

All columns are sortable by clicking the header. The "On" column sorts checked items together using a custom `QTreeWidgetItem.__lt__` override.

---

## The Fuzzy Family — Reference Implementation

The four built-in fuzzy addons are good references for common patterns:

| Addon              | Role                                       | Key technique                           |
|--------------------|--------------------------------------------|-----------------------------------------|
| **fuzzy_loader**   | Extract paths from text, open/load files  | Pre-compiled regex, comment stripping   |
| **fuzzy_locator**  | Find matching layers in QGIS TOC          | TOC selection via `layerTreeView()`     |
| **fuzzy_creator**  | Create missing GIS files from references  | `QgsVectorFileWriter`, schema templates |
| **fuzzy_exporter** | Copy GIS files + sidecars to destination  | `shutil.copy2`, sidecar collection      |

---

## Complete Example: Line Counter Panel

```python
"""
line_counter.py  v0.1
Shows live line count for the active file.
"""
__version__ = "0.1"

from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QLabel
from qgis.PyQt.QtCore import Qt


class LineCounterWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.label = QLabel("No file open")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

    def update(self, dock, page):
        if not page:
            self.label.setText("No file open")
            return
        text = page.editor.editor_text()
        lines = len(text.splitlines())
        self.label.setText("%d lines" % lines)


_widget = LineCounterWidget()


def _panel(dock):
    return {"id": "line_counter", "title": "Line Counter",
            "widget": _widget, "area": "bottom"}


def _on_tab(dock, page):
    _widget.update(dock, page)


def _startup(dock):
    _widget.update(dock, dock.current_page())


def register():
    return {
        "id": "line_counter",
        "name": "Line Counter  v" + __version__,
        "description": "Shows live line count for the active file.",
        "core": False,
        "builtin": False,
        "hooks": {
            "panel": _panel,
            "on_tab_changed": _on_tab,
            "on_file_saved": lambda dock, page, path: _widget.update(dock, page),
            "on_startup": _startup,
        },
    }
```

---

## The Editor is QScintilla, Not QTextEdit

`page.editor` is a `QsciScintilla` subclass. This affects which APIs work:

| Task                   | Use                                                     | Don't use                          |
|------------------------|---------------------------------------------------------|------------------------------------|
| Get full text          | `editor.text()` or `editor.editor_text()` (wrapper)     | `editor.toPlainText()`             |
| Get selected text      | `editor.selectedText()`                                 | `editor.textCursor().selectedText()` |
| Get line text          | `editor.text(line_num)` (0-based)                       | `document().findBlockByNumber()`   |
| Get cursor line/col    | `editor.getCursorPosition()` → `(line, col)`, 0-based   | `textCursor().blockNumber()`       |
| Get selection range    | `editor.getSelection()` → `(l1, c1, l2, c2)`            | `textCursor().selectionStart()`    |
| Connect to selection   | `editor.selectionChanged` or `cursorPositionChanged`    | —                                  |
| Scroll detection       | `editor.verticalScrollBar().valueChanged`               | —                                  |
| Low-level messages     | `editor.SendScintilla(SCI_*, w, l)`                     | —                                  |

### `EditorPage.editor_kind`

Check this before calling editor APIs — currently `"scintilla"` but documented for future-proofing:

```python
if page.editor_kind == "scintilla":
    line_num, col = page.editor.getCursorPosition()
else:
    pass  # fallback
```

### SendScintilla Binding Quirks

- `SendScintilla(msg, len, bytes_obj)` — passing `bytes` as `lParam` is **unreliable** in PyQt bindings. `SCI_SEARCHINTARGET` in particular fails silently.
- **Workaround**: use Python-side string search on `editor.text(line_num)` and compute byte offsets via `line_text[:idx].encode('utf-8')`, then pass the integer offset to `SCI_INDICATORFILLRANGE`.
- For search, prefer `editor.findFirst()` / `findNext()` over raw `SendScintilla(SCI_SEARCHINTARGET, ...)`.

---

## Scintilla Indicator Number Allocation

Indicators (0–31) are a shared resource — lexers, search-highlight, and addons all compete. Collisions cause highlights from one feature to overwrite another.

**Reservations:**

| Range   | Purpose                                    |
|---------|--------------------------------------------|
| 0–7     | Scintilla built-in / lexer (reserved)      |
| 8–19    | Core plugin features (search, find, match-brace) |
| 20–31   | Addons — allocate your own, document it    |

Addons should pick a high, specific number (e.g. `29`) and document it in their module header.

### Indicator Setup Reference

```python
_INDICATOR_NUM = 29
SCI_INDICSETSTYLE = 2080
SCI_INDICSETFORE = 2082        # lParam is 0x00BBGGRR (BGR, not RGB)
SCI_INDICSETALPHA = 2523
SCI_INDICSETOUTLINEALPHA = 2558
SCI_INDICSETUNDER = 2510       # draw under text (1) vs over (0)

col = QColor("#FFD54F")
bgr = (col.blue() << 16) | (col.green() << 8) | col.red()
ed.SendScintilla(SCI_INDICSETSTYLE, _INDICATOR_NUM, 7)  # INDIC_ROUNDBOX
ed.SendScintilla(SCI_INDICSETFORE, _INDICATOR_NUM, bgr)
ed.SendScintilla(SCI_INDICSETALPHA, _INDICATOR_NUM, 110)
```

### Fill / Clear Range

```python
SCI_SETINDICATORCURRENT = 2500
SCI_INDICATORFILLRANGE = 2504    # fill bytes [start, start+length)
SCI_INDICATORCLEARRANGE = 2505   # clear bytes [start, start+length)

ed.SendScintilla(SCI_SETINDICATORCURRENT, _INDICATOR_NUM)
ed.SendScintilla(SCI_INDICATORFILLRANGE, byte_start, byte_length)
```

**Note:** positions are **byte** offsets, not character offsets. UTF-8 multibyte chars require encoding the prefix to compute offset:

```python
byte_start = line_start_byte + len(line_text[:char_idx].encode("utf-8"))
```

---

## Style-Based Exclusion (Comments, Strings)

To skip matches inside comments or strings, use the lexer's style assignment:

```python
SCI_GETSTYLEAT = 2010
style = ed.SendScintilla(SCI_GETSTYLEAT, byte_position)
```

Common comment style IDs across QScintilla lexers: `{1, 2, 3, 12, 15}`. Not universal — varies per language.

---

## Per-Editor State Pattern

When an addon needs to track per-tab state (cached data, connected handlers), attach it to the editor widget:

```python
def _attach_if_needed(page, dock):
    ed = getattr(page, "editor", None)
    if ed is None or getattr(ed, "_my_addon_state", None) is not None:
        return
    ed._my_addon_state = MyState(ed, dock)
```

### Critical Caveat: Stale Attributes Across Plugin Reload

When the plugin reloads, the old `_my_addon_state` attribute **persists on the editor widget** — Python-level state survives QScintilla C++ object reuse. The new addon version will skip attachment because `getattr(...) is not None`.

**Fix in `on_startup`**: clear any stale attribute before attaching:

```python
def _attach_all(dock):
    for i in range(dock.tabs.count()):
        page = dock.tabs.widget(i)
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

## Addon Enable / Disable Lifecycle

*(since v1.0.42)*

The Addon Manager fires `on_enable` / `on_disable` hooks when the user toggles checkboxes and clicks OK. This lets signal-based addons wire/unwire cleanly without a QGIS restart.

### Hook Signatures

| Hook         | When                                    | Signature     |
|--------------|-----------------------------------------|---------------|
| `on_enable`  | User ticks the checkbox and clicks OK   | `fn(dock)`    |
| `on_disable` | User unticks the checkbox and clicks OK | `fn(dock)`    |

### Example: Signal-Based Addon with Clean Toggle

```python
_handlers = {}  # editor_id -> handler

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

def _on_enable(dock):
    for i in range(dock.tabs.count()):
        _attach_to(dock.tabs.widget(i))

def _on_disable(dock):
    _detach_all()

def register():
    return {
        "id": "my_highlighter",
        "name": "My Highlighter  v1.0",
        "description": "Highlights matching words. Supports live enable/disable.",
        "hooks": {
            "on_startup": _on_enable,   # same as enable — attach to all tabs
            "on_shutdown": _on_disable, # same as disable — detach all
            "on_enable": _on_enable,
            "on_disable": _on_disable,
            "on_file_opened": lambda dock, page, path: _attach_to(page),
        },
    }
```

### Addon Manager Status Column

The Addon Manager shows a status indicator when you toggle a checkbox:

| Status | Meaning |
|--------|---------|
| `✓ Live` (green) | Addon has `on_enable`/`on_disable` — change takes effect immediately |
| `⚠ Restart` (orange) | Addon lacks these hooks — QGIS restart needed for full effect |

### What Hooks Don't Do

`on_enable` / `on_disable` do **not**:

- Remove the addon module from `sys.modules`
- Destroy panels created by the `panel` hook
- Remove toolbar buttons added by `toolbar_button`

For those, a QGIS restart is still required. The hooks are designed for signal-based addons that need to connect/disconnect cleanly.

### QSettings Location for Enabled Addons

The enabled addons list is stored as a `|`-delimited string:

```python
QSettings().value("QFAT/QFAT04/enabled_addons")
# → "fuzzy_loader|python_console|tab_restore|..."
```

Addons can read this to self-gate behavior if needed.

---

## Critical Rules

1. **Disconnect all signals in `on_shutdown`.** Store handler references; disconnect them specifically. Never call `signal.disconnect()` with no argument.

2. **Guard with `sip.isdeleted()`** before accessing any dock widget attribute in deferred callbacks (timers, project signals, event filters).

3. **Never create new signal/timer/event connections inside code that runs repeatedly** (refresh/update/rebuild functions) unless you can prove it won't duplicate. Connections accumulate and fire multiple times.

4. **Only claim your file types in `run_handler`.** Check the extension before returning `True`. Returning `True` unconditionally breaks F5 for all other file types.

5. **Always increment the version** on every change. Stale installs are a top source of bugs.

6. **Wrap addon-to-addon imports in try/except** with the bulletproof pattern. Never assume another addon is present.

7. **Use `QSettings()` with a unique prefix** like `QFAT/QFAT04/addon_<your_id>/`.

8. **Use `dock.messages.append()`** for status output, not `print()`. Print goes to QGIS Python console which users may not have open.

9. **Signal-based addons should implement `on_enable` / `on_disable`.** Without these hooks, disabling an addon in the Addon Manager has no effect until QGIS restart — signals keep firing.

10. **Don't pass `bytes` as lParam to `SendScintilla`.** PyQt bindings handle this inconsistently. Compute positions in Python and pass integer offsets instead.

11. **Reserve indicator numbers ≥ 20 for addons.** Document the number in your module header. Lower numbers collide with lexers and core features.

---

## Troubleshooting

- **Addon not showing up:** Click Refresh in Addon Manager. Check QGIS Python console for load errors.
- **Hook not firing:** Verify the addon is enabled in Addon Manager. Core addons are auto-enabled on first install but can be disabled by the user.
- **Import errors from other addons:** Use the bulletproof import pattern. Don't rely on `from .other_addon import ...` alone.
- **`TypeError: function() takes N positional arguments but M were given`:** Stale install — a shared function signature changed. Reinstall the plugin and increment versions.
- **Panel not appearing:** The `panel` hook only runs at startup. After enabling, restart QGIS or reload the plugin.
- **Settings not saving:** Use `QSettings()` with a unique key prefix like `QFAT/QFAT04/addon_yourid/`.
- **Context menu blank:** Your `editor_context_builder` returned `False`. Check that the path detection / TOC selection logic is finding something.
- **`RuntimeError: wrapped C/C++ object has been deleted`:** Your addon is accessing dock widgets after they've been destroyed. See the "Guarding Against Deleted Qt Objects" section.
- **F5 runs wrong interpreter:** A `run_handler` addon is claiming files it shouldn't. Check that it filters by extension before returning `True`.
- **PowerShell not found (WinError 2):** `powershell.exe` is not on PATH. Set the full path in Preferences → Interpreters → PowerShell. Default: `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`.
- **Addon still active after disabling:** The addon doesn't implement `on_disable`. Either add `on_disable` to disconnect signals, or restart QGIS.
- **Highlights from addon overwrite search highlights:** Indicator number collision. Use a number ≥ 20 and document it.
- **`SendScintilla` search returns -1 for valid matches:** Don't pass `bytes` as lParam. Use Python string search + integer offsets instead.
