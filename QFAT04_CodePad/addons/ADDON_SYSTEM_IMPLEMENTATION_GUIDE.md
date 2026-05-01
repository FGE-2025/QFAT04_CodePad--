# QGIS Plugin Addon System — Implementation Guide

*How to reproduce the QFAT04 CodePad addon manager + hook system in any QGIS plugin.*

Target audience: plugin developers who want a modular, user-extensible plugin where end-users can drop `.py` files into a folder to add features without editing core code.

---

## 1. Architecture Overview

```
MyPlugin/
├── __init__.py
├── metadata.txt
├── my_plugin.py          ← QGIS entry point (initGui/unload)
├── my_dock.py            ← Main QDockWidget (or main dialog)
├── my_config.py          ← QSettings wrapper
├── my_addon_manager.py   ← AddonManager class  ★ CORE
├── my_dialogs.py         ← contains AddonManagerDialog  ★ UI
└── addons/
    ├── __init__.py       ← empty
    ├── ADDON_DEV_GUIDE.md ← for addon authors
    └── sample_addon.py   ← example
```

**Three pieces make the system work:**

1. **AddonManager** — discovers `.py` files, calls their `register()`, stores hooks in a registry, fires hooks on events.
2. **AddonManagerDialog** — user-facing checkbox list to enable/disable, with sort + settings access.
3. **Hook integration points in core** — main plugin code calls `addon_manager.fire_hook(...)` at key moments.

---

## 2. The Addon Contract

Every addon `.py` file in `addons/` must export one function:

```python
def register():
    return {
        "id": "unique_addon_id",              # must be unique
        "name": "Display Name",
        "description": "One-line summary",
        "core": False,                         # True = enabled by default on new install
        "version": "1.0",
        "hooks": {
            "on_startup": on_startup,          # fn(dock)
            "on_file_opened": on_opened,       # fn(dock, page, path)
            "panel": make_panel,                # fn(dock) -> {"title","widget","area","id"}
            "toolbar_button": {"name":..., "callback": fn(dock)},
            "settings_dialog": open_settings,  # fn(dock) -> None  (for ⚙ gear icon)
            # ...any hook your plugin fires
        },
    }
```

The AddonManager calls `register()`, stores the returned dict in `self.registry[id]`, and later calls hooks by name.

---

## 3. AddonManager — Copy This File

Create `my_addon_manager.py`:

```python
"""AddonManager — discovers, loads, and dispatches addon hooks."""
import os
import importlib.util
import traceback

class AddonManager:
    def __init__(self, host):
        """host = the main dock/window object addons interact with."""
        self.host = host
        self.registry = {}      # addon_id -> data dict
        self._panels = {}       # addon_id -> QDockWidget (for panel hook)
        self.addon_dir = os.path.join(os.path.dirname(__file__), "addons")

        # Deferred load — UI must build first, addons load after
        from qgis.PyQt.QtCore import QTimer, QSettings
        delay = int(QSettings().value("MyPlugin/delay_addon_load", 5000))
        QTimer.singleShot(delay, self._load_startup_addons)

    # -------- Discovery --------

    def _load_startup_addons(self):
        """Load core + user-enabled addons. If 'scan on startup' is on,
        also discover disabled addons so they appear in the manager table
        (dormant — hooks don't fire since filtered by enabled_addons)."""
        from qgis.PyQt.QtCore import QSettings
        scan_all = QSettings().value("MyPlugin/addon_scan_on_startup", False, type=bool)
        enabled = self.host.config.get("enabled_addons", [])
        if not os.path.exists(self.addon_dir):
            return
        for filename in sorted(os.listdir(self.addon_dir)):
            if filename.endswith(".py") and not filename.startswith("__"):
                self._load_one(filename, enabled, scan_all)
        self._ensure_core_enabled()
        self.create_addon_panels()
        self.create_toolbar_buttons()
        self.fire_hook("on_startup")

    def _load_one(self, filename, enabled, scan_all):
        addon_id = filename[:-3]
        filepath = os.path.join(self.addon_dir, filename)
        try:
            spec = importlib.util.spec_from_file_location(addon_id, filepath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "register"):
                data = mod.register()
                data["module"] = mod
                aid = data.get("id", addon_id)
                is_core = data.get("core", False)
                if scan_all or is_core or aid in enabled:
                    self.registry[aid] = data
        except Exception as e:
            print(f"AddonManager: Failed to load {filename}: {e}")
            traceback.print_exc()

    def load_all(self, load_everything=False, skip_core_check=False):
        """Refresh button: re-scan from scratch."""
        self.registry = {}
        if not os.path.exists(self.addon_dir):
            return
        enabled = self.host.config.get("enabled_addons", [])
        for filename in sorted(os.listdir(self.addon_dir)):
            if filename.endswith(".py") and not filename.startswith("__"):
                self._load_one(filename, enabled, load_everything)
        if not skip_core_check:
            self._ensure_core_enabled()

    # -------- Core-addon handling --------

    def _ensure_core_enabled(self):
        """Core addons are auto-enabled on first install, BUT respect user's
        explicit disable. Tracked via 'disabled_core_addons' in QSettings."""
        from qgis.PyQt.QtCore import QSettings
        s = QSettings()
        disabled_cores = set(
            s.value("MyPlugin/disabled_core_addons", "", type=str).split("|")
        ) - {""}
        enabled = self.host.config.get("enabled_addons", [])
        changed = False
        for aid, data in self.registry.items():
            if data.get("core", False) and aid not in enabled and aid not in disabled_cores:
                enabled.append(aid)
                changed = True
        if changed:
            self.host.config["enabled_addons"] = enabled
            from .my_config import save_config
            save_config(self.host.config)

    # -------- Hook dispatch --------

    def get_active_hooks(self, hook_name):
        """Return list of callables/dicts for the given hook, from enabled addons only."""
        enabled = self.host.config.get("enabled_addons", [])
        hooks = []
        for aid, data in self.registry.items():
            if aid in enabled:
                h = data.get("hooks", {}).get(hook_name, [])
                hooks.extend(h if isinstance(h, list) else [h])
        return hooks

    def fire_hook(self, hook_name, *args, **kwargs):
        """Call all active hooks for the given name."""
        for fn in self.get_active_hooks(hook_name):
            try:
                if callable(fn):
                    fn(self.host, *args, **kwargs)
            except Exception as e:
                print(f"Addon hook '{hook_name}' error: {e}")
                traceback.print_exc()

    # -------- Standard hook materialisation --------

    def create_addon_panels(self):
        """For every active addon returning a 'panel' hook, create a QDockWidget."""
        from qgis.PyQt.QtWidgets import QDockWidget
        from qgis.PyQt.QtCore import Qt
        area_map = {"left": Qt.LeftDockWidgetArea, "right": Qt.RightDockWidgetArea,
                    "top": Qt.TopDockWidgetArea, "bottom": Qt.BottomDockWidgetArea}
        for fn in self.get_active_hooks("panel"):
            try:
                if not callable(fn):
                    continue
                result = fn(self.host)
                if not (result and isinstance(result, dict)):
                    continue
                widget = result.get("widget")
                if not widget:
                    continue
                title = result.get("title", "Addon Panel")
                area = result.get("area", "bottom")
                addon_id = result.get("id", title)
                dock_w = QDockWidget(title, self.host.inner_window)
                dock_w.setObjectName(f"MyPlugin_Addon_{addon_id}")
                dock_w.setWidget(widget)
                self.host.inner_window.addDockWidget(
                    area_map.get(area, Qt.BottomDockWidgetArea), dock_w)
                self._panels[addon_id] = dock_w
            except Exception as e:
                print(f"Addon panel error: {e}")
                traceback.print_exc()

    def create_toolbar_buttons(self):
        """For every 'toolbar_button' hook (dict), add an action to the main toolbar."""
        for hook in self.get_active_hooks("toolbar_button"):
            if isinstance(hook, dict):
                name = hook.get("name", "Addon")
                cb = hook.get("callback")
                if cb and hasattr(self.host, "main_toolbar"):
                    act = self.host.main_toolbar.addAction(name)
                    act.triggered.connect(lambda _=False, f=cb: f(self.host))
```

### Key design decisions explained

- **Deferred loading via `QTimer.singleShot`**: addons cannot block QGIS startup. Core UI builds first; addons load ~5 s later. Tunable via QSettings.
- **`core` flag**: addons marked `"core": True` are enabled by default on first install. User can disable; the plugin remembers the disable in a separate `disabled_core_addons` key so a later reinstall doesn't re-enable them.
- **`scan_on_startup` flag**: off by default (faster). When on, all addons load to registry but only enabled ones' hooks fire. This is what populates the manager dialog without running disabled code.
- **`load_all`**: used by the Refresh button — full rescan.
- **Error isolation**: every addon's `register()` and every hook fires inside `try/except` — one broken addon never breaks the plugin.

---

## 4. AddonManagerDialog — The UI

Put this in `my_dialogs.py`. The essentials:

```python
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QDialogButtonBox, QCheckBox,
)

# ---- Custom tree item so column 0 sorts by check state ----
class _AddonTreeItem(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col == 0:
            a = 1 if self.checkState(0) == Qt.Checked else 0
            b = 1 if other.checkState(0) == Qt.Checked else 0
            return a < b
        return super().__lt__(other)


class AddonManagerDialog(QDialog):
    def __init__(self, addon_manager, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Addon Manager")
        self.resize(600, 420)
        self._addon_manager = addon_manager
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enable or disable addons. Click a header to sort."))

        # Tree: [✓ On] [Addon] [Description] [Settings]
        self.addon_list = QTreeWidget()
        self.addon_list.setHeaderLabels(["On", "Addon", "Description", ""])
        self.addon_list.setRootIsDecorated(False)
        self.addon_list.setColumnWidth(0, 40)
        self.addon_list.setColumnWidth(1, 180)
        self.addon_list.setColumnWidth(3, 70)
        self.addon_list.setSortingEnabled(True)
        self.addon_list.sortByColumn(1, Qt.AscendingOrder)
        self.addon_list.itemChanged.connect(self._on_check_changed)

        active = config.get("enabled_addons", [])
        self._hidden_addons = set(
            QSettings().value("MyPlugin/hidden_addons", "", type=str).split("|")
        ) - {""}
        self._settings_btns = {}
        self._rebuild_list(active)

        layout.addWidget(self.addon_list)

        # Info row, Options row, OK/Cancel — trimmed for brevity
        self.chk_scan_startup = QCheckBox("Scan addons folder on startup")
        self.chk_scan_startup.setChecked(
            QSettings().value("MyPlugin/addon_scan_on_startup", False, type=bool))

        opt_row = QHBoxLayout()
        opt_row.addWidget(self.chk_scan_startup)
        opt_row.addStretch(1)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self._refresh_addons)
        opt_row.addWidget(btn_refresh)
        layout.addLayout(opt_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _rebuild_list(self, active_addons):
        self.addon_list.setSortingEnabled(False)
        self.addon_list.clear()
        self._settings_btns = {}
        for key, data in self._addon_manager.registry.items():
            if key in self._hidden_addons:
                continue
            item = _AddonTreeItem(["", data.get("name", key),
                                   data.get("description", ""), ""])
            item.setData(0, Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if key in active_addons else Qt.Unchecked)
            if data.get("core", False):
                item.setToolTip(1, "Core addon")
                font = item.font(1); font.setBold(True); item.setFont(1, font)
            self.addon_list.addTopLevelItem(item)

            # Per-addon Settings button via settings_dialog hook
            settings_fn = data.get("hooks", {}).get("settings_dialog")
            if settings_fn and callable(settings_fn):
                btn = QPushButton("Settings...")
                btn.setMaximumWidth(65)
                btn.clicked.connect(
                    lambda _=False, fn=settings_fn: fn(self._addon_manager.host))
                self.addon_list.setItemWidget(item, 3, btn)
                self._settings_btns[key] = btn
        self.addon_list.setSortingEnabled(True)

    def _on_check_changed(self, item, column):
        if column == 0 and self.addon_list.sortColumn() == 0:
            order = self.addon_list.header().sortIndicatorOrder()
            self.addon_list.sortItems(0, order)

    def _refresh_addons(self):
        currently_enabled = self.get_enabled_addons()
        self._addon_manager.load_all(load_everything=True)
        self._rebuild_list(currently_enabled)

    def _on_accept(self):
        s = QSettings()
        s.setValue("MyPlugin/addon_scan_on_startup", self.chk_scan_startup.isChecked())
        enabled = self.get_enabled_addons()
        # Track user-disabled core addons so they don't get auto-re-enabled
        disabled_cores = [
            aid for aid, data in self._addon_manager.registry.items()
            if data.get("core", False) and aid not in enabled
        ]
        s.setValue("MyPlugin/disabled_core_addons",
                   "|".join(disabled_cores) if disabled_cores else "")
        self.accept()

    def get_enabled_addons(self):
        return [
            self.addon_list.topLevelItem(i).data(0, Qt.UserRole)
            for i in range(self.addon_list.topLevelItemCount())
            if self.addon_list.topLevelItem(i).checkState(0) == Qt.Checked
        ]
```

### Critical UI gotchas

- **Sorting column 0 by checkbox**: QTreeWidget sorts columns by their displayed text. Empty text = no sort. Solution: subclass `QTreeWidgetItem.__lt__` (shown above). Do **not** stuff "1"/"0" text into the cell — it shows up next to the checkbox and looks ugly; the subclass approach keeps the cell clean.
- **Re-sort on toggle**: when user ticks/unticks, items don't auto-re-sort. Listen to `itemChanged` and re-apply `sortItems(0, order)` if column 0 is the sort column.
- **Disable sorting during rebuild**: `setSortingEnabled(False)` before `clear()` and re-adding; re-enable after. Otherwise Qt re-sorts on every `addTopLevelItem` = slow.
- **`setItemWidget` for Settings button**: the button embeds inline in the row. Avoid for large lists (tens of rows is fine; hundreds starts to lag).

---

## 5. Wiring Up the Core Plugin

In `my_dock.py` (your main QDockWidget):

```python
class MyDock(QDockWidget):
    def __init__(self, iface):
        super().__init__("My Plugin", iface.mainWindow())
        self.iface = iface
        self.config = load_config()  # must include "enabled_addons" list
        # ... build UI ...
        from .my_addon_manager import AddonManager
        self.addon_manager = AddonManager(self)  # starts deferred load
```

Then **fire hooks at every interesting moment**:

```python
def open_file(self, path):
    # ... existing open logic ...
    self.addon_manager.fire_hook("on_file_opened", page, path)

def save_file(self, path):
    # ... existing save logic ...
    self.addon_manager.fire_hook("on_file_saved", page, path)

def closeEvent(self, event):
    self.addon_manager.fire_hook("on_shutdown")
    super().closeEvent(event)
```

Open the dialog from a menu action:

```python
def open_addon_manager(self):
    from .my_dialogs import AddonManagerDialog
    dlg = AddonManagerDialog(self.addon_manager, self.config, self)
    if dlg.exec_() == QDialog.Accepted:
        self.config["enabled_addons"] = dlg.get_enabled_addons()
        save_config(self.config)
        # Optional: reload addons to pick up changes live
        self.addon_manager.load_all()
        self.addon_manager.create_addon_panels()
```

---

## 6. QSettings Keys to Reserve

Under your plugin's `SETTINGS_ROOT` (e.g. `"MyPlugin"`):

| Key | Type | Purpose |
|---|---|---|
| `enabled_addons` | str (pipe-separated) | List of enabled addon IDs. Stored in config, also in QSettings if you sync. |
| `addon_scan_on_startup` | bool | Load all addons (for dialog listing) vs only enabled. |
| `hidden_addons` | str (pipe-separated) | User-removed addons (file kept, hidden from list). |
| `disabled_core_addons` | str (pipe-separated) | Core addons user explicitly unticked — prevents auto-re-enable. |
| `delay_addon_load` | int (ms) | Startup delay before scanning addons. Default 5000. |

---

## 7. Sample Addon — Copy As Template

Drop this as `addons/hello_world.py`:

```python
__version__ = "1.0"

def _panel(host):
    from qgis.PyQt.QtWidgets import QLabel
    w = QLabel("Hello from addon!")
    return {"id": "hello_world", "title": "Hello", "widget": w, "area": "bottom"}

def _on_file_opened(host, page, path):
    print(f"[hello_world] File opened: {path}")

def register():
    return {
        "id": "hello_world",
        "name": f"Hello World  v{__version__}",
        "description": "Minimal addon demonstrating panel + file hook",
        "core": False,
        "version": __version__,
        "hooks": {
            "panel": _panel,
            "on_file_opened": _on_file_opened,
        },
    }
```

---

## 8. Hooks — Recommended Catalogue

Pick whichever your plugin needs. You're not obligated to implement all:

| Hook | Signature | Fires when |
|---|---|---|
| `on_startup` | `fn(host)` | Once, after UI + addon loading complete |
| `on_shutdown` | `fn(host)` | Plugin unload / QGIS exit |
| `on_file_opened` | `fn(host, page, path)` | After a file is opened |
| `on_file_saved` | `fn(host, page, path)` | After a file is saved |
| `on_tab_changed` | `fn(host, page)` | Active tab switched |
| `panel` | `fn(host) -> dict` | Create a dock panel (called once at load) |
| `toolbar_button` | `dict` | Add a button to main toolbar (added once at load) |
| `main_menu` | `list[dict]` | Add items under an "Addons" menu |
| `editor_context_builder` | `fn(host, menu) -> bool` | Right-click menu in main widget |
| `statusbar_widget` | `fn(host) -> QWidget` | Widget added to statusbar |
| `settings_dialog` | `fn(host)` | Gear icon in Addon Manager → per-addon config UI |

Firing pattern is always the same — `self.addon_manager.fire_hook("name", *extra_args)`.

---

## 9. Testing Checklist

Before shipping:

- [ ] Drop a broken `.py` in `addons/` (syntax error) → plugin still loads, error logged, other addons unaffected
- [ ] Addon that raises inside `register()` → same result
- [ ] Addon that raises inside a hook → only that hook fails, others in same list still run
- [ ] Disable a core addon → stays disabled after QGIS restart
- [ ] Enable "scan on startup" → disabled addons appear in manager but their hooks don't fire
- [ ] Click column headers → all columns sort, including the "On" checkbox column
- [ ] Toggle a checkbox while sorted by "On" → row moves to correct position

---

## 10. Common Pitfalls

**"Addon doesn't load" debug order:**
1. Is the file in the right folder? (`addons/` at plugin root)
2. Does it have a `register()` function?
3. Does `register()` return a dict with an `id`?
4. Is the ID in `enabled_addons` (or is the addon marked `core: True`)?
5. Check QGIS Python console for the `AddonManager: Failed to load…` print.

**Hooks firing at wrong time:** if a hook depends on UI state, make sure the UI is built before the AddonManager's `QTimer.singleShot` fires. The 5-second default is usually safe.

**Reload loop:** don't call `addon_manager.load_all()` inside a hook that fires frequently — it re-imports every addon. Only call on explicit Refresh or config change.

**Panels reappearing in wrong position:** if you call `create_addon_panels()` twice, you'll get duplicates. Track created panels in `self._panels` and skip if already created, or remove first.

---

## 11. Minimal Dependencies

This system uses only stdlib + `qgis.PyQt`. No third-party packages. Works on any QGIS 3.x version.
