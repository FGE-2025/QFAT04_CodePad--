"""
qfat04_addons.py
Addon API Manager.
"""
import os
import importlib.util
import traceback

class AddonManager:
    """
    Addon API for QFAT04 TUFLOW Editor.
    
    Addons are .py files in the addons/ folder. Each provides a register() function
    that returns a dict with:
        id:          unique addon id string
        name:        display name
        description: short description
        hooks:       dict of hook_name -> callback(s)
    
    Available hooks:
        main_menu:              list of {"name": str, "callback": fn(dock)}
        editor_context_builder: fn(dock, menu) -> bool  — add items to right-click menu
        panel:                  fn(dock) -> QWidget      — create a panel widget, dock adds it
        on_tab_changed:         fn(dock, page)           — called when active tab changes
        on_file_opened:         fn(dock, page, path)     — called after a file is opened
        on_file_saved:          fn(dock, page, path)     — called after a file is saved
        toolbar_button:         list of {"name": str, "icon": str|None, "callback": fn(dock)}
        statusbar_widget:       fn(dock) -> QWidget      — create a widget for the status bar
        on_startup:             fn(dock)                  — called once after UI is built
        on_shutdown:            fn(dock)                  — called on unload
        on_enable:              fn(dock)                  — called when user enables addon in manager
        on_disable:             fn(dock)                  — called when user disables addon in manager
    """
    def __init__(self, dock):
        self.dock = dock
        self.registry = {}
        self._panels = {}  # addon_id -> QDockWidget
        self.addon_dir = os.path.join(os.path.dirname(__file__), "addons")
        # Defer all addon loading — UI builds first, addons load after
        from qgis.PyQt.QtCore import QTimer, QSettings
        _delay = int(QSettings().value("QFAT/QFAT04/delay_addon_load", 5000))
        QTimer.singleShot(_delay, self._load_startup_addons)

    def _load_startup_addons(self):
        """Load core + enabled non-core addons after UI is responsive.
        If 'scan on startup' is enabled, also discover disabled addons so they
        appear in the Addon Manager table (dormant — their hooks don't fire
        because get_active_hooks filters by enabled_addons)."""
        from qgis.PyQt.QtCore import QSettings
        scan_all = QSettings().value("QFAT/QFAT04/addon_scan_on_startup", False, type=bool)
        enabled = self.dock.config.get("enabled_addons", [])
        if not os.path.exists(self.addon_dir):
            return
        for filename in sorted(os.listdir(self.addon_dir)):
            if filename.endswith(".py") and not filename.startswith("__"):
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
                    print(f"QFAT04 AddonManager: Failed to load {filename}: {e}")
                    traceback.print_exc()
        self._ensure_core_enabled()
        self.create_addon_panels()
        self.create_toolbar_buttons()
        self.create_statusbar_widgets()
        self._register_addon_shortcuts()
        self.fire_hook("on_startup")
        if hasattr(self.dock, 'rebuild_addons_menu'):
            self.dock.rebuild_addons_menu()

    def _register_addon_shortcuts(self):
        """Delegate to dock if it has the method."""
        if hasattr(self.dock, '_register_addon_shortcuts'):
            self.dock._register_addon_shortcuts()

    def load_all(self, load_everything=False, skip_core_check=False):
        """Reload addons. load_everything=True discovers all addons (Refresh button)."""
        self.registry = {}
        if not os.path.exists(self.addon_dir): return
        enabled = self.dock.config.get("enabled_addons", [])
        for filename in sorted(os.listdir(self.addon_dir)):
            if filename.endswith(".py") and not filename.startswith("__"):
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
                        if load_everything or is_core or aid in enabled:
                            self.registry[aid] = data
                except Exception as e:
                    print(f"QFAT04 AddonManager: Failed to load {filename}: {e}")
                    traceback.print_exc()
        if not skip_core_check:
            self._ensure_core_enabled()

    def _ensure_core_enabled(self):
        """Add core addons to enabled list if not present.
        Runs every startup. Does NOT re-enable user-disabled core addons
        because disabled ones are tracked separately."""
        from qgis.PyQt.QtCore import QSettings
        s = QSettings()
        disabled_key = "QFAT/QFAT04/disabled_core_addons"
        disabled_cores = set(s.value(disabled_key, "", type=str).split("|")) - {""}
        enabled = self.dock.config.get("enabled_addons", [])
        changed = False
        for aid, data in self.registry.items():
            if data.get("core", False) and aid not in enabled and aid not in disabled_cores:
                enabled.append(aid)
                changed = True
        if changed:
            self.dock.config["enabled_addons"] = enabled
            from .qfat04_config import save_config
            save_config(self.dock.config)

    def get_active_hooks(self, hook_name):
        enabled = self.dock.config.get("enabled_addons", [])
        hooks = []
        for aid, data in self.registry.items():
            if aid in enabled:
                addon_hooks = data.get("hooks", {}).get(hook_name, [])
                if isinstance(addon_hooks, list): hooks.extend(addon_hooks)
                else: hooks.append(addon_hooks)
        return hooks

    def fire_hook(self, hook_name, *args, **kwargs):
        """Call all active hooks for the given name, passing args."""
        for fn in self.get_active_hooks(hook_name):
            try:
                if callable(fn):
                    fn(self.dock, *args, **kwargs)
            except Exception as e:
                print(f"QFAT04 addon hook '{hook_name}' error: {e}")
                traceback.print_exc()

    def fire_hook_for_addon(self, hook_name, addon_id):
        """Fire a specific hook for a single addon, regardless of enabled state."""
        data = self.registry.get(addon_id)
        if not data:
            return
        hook = data.get("hooks", {}).get(hook_name)
        if hook is None:
            return
        fns = hook if isinstance(hook, list) else [hook]
        for fn in fns:
            try:
                if callable(fn):
                    fn(self.dock)
            except Exception as e:
                print(f"QFAT04 addon hook '{hook_name}' for '{addon_id}' error: {e}")
                traceback.print_exc()

    def create_addon_panels(self):
        """Create panels for all active addons that provide the 'panel' hook."""
        from qgis.PyQt.QtWidgets import QDockWidget
        from qgis.PyQt.QtCore import Qt
        for fn in self.get_active_hooks("panel"):
            try:
                if callable(fn):
                    result = fn(self.dock)
                    if result and isinstance(result, dict):
                        title = result.get("title", "Addon Panel")
                        widget = result.get("widget")
                        area = result.get("area", "bottom")  # left, right, top, bottom
                        addon_id = result.get("id", title)
                        if widget:
                            dock_w = QDockWidget(title, self.dock.inner_window)
                            dock_w.setObjectName("QFAT04_Addon_%s" % addon_id)
                            dock_w.setWidget(widget)
                            area_map = {
                                "left": Qt.LeftDockWidgetArea,
                                "right": Qt.RightDockWidgetArea,
                                "top": Qt.TopDockWidgetArea,
                                "bottom": Qt.BottomDockWidgetArea,
                            }
                            self.dock.inner_window.addDockWidget(
                                area_map.get(area, Qt.BottomDockWidgetArea), dock_w)
                            # Tabify with console by default for bottom panels
                            if area == "bottom" and hasattr(self.dock, "dock_console"):
                                self.dock.inner_window.tabifyDockWidget(
                                    self.dock.dock_console, dock_w)
                            self._panels[addon_id] = dock_w
            except Exception as e:
                print(f"QFAT04 addon panel error: {e}")
                traceback.print_exc()

    def create_toolbar_buttons(self):
        """Create toolbar buttons for all active addons."""
        for hook in self.get_active_hooks("toolbar_button"):
            try:
                if isinstance(hook, dict):
                    name = hook.get("name", "Addon")
                    cb = hook.get("callback")
                    if cb and hasattr(self.dock, "toolbar"):
                        act = self.dock.toolbar.addAction(name)
                        act.triggered.connect(lambda _=False, f=cb: f(self.dock))
            except Exception as e:
                print(f"QFAT04 addon toolbar error: {e}")

    def create_statusbar_widgets(self):
        """Create statusbar widgets for all active addons."""
        for fn in self.get_active_hooks("statusbar_widget"):
            try:
                if callable(fn):
                    widget = fn(self.dock)
                    if widget and hasattr(self.dock, "statusbar"):
                        self.dock.statusbar.addPermanentWidget(widget)
            except Exception as e:
                print(f"QFAT04 addon statusbar error: {e}")
