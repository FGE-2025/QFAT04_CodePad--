"""
tab_restore.py  v0.5
Addon: Save and restore open editor tabs with the QGIS project (.qgz).

Saves the ordered list of open file paths as a QGIS project variable
on project save. On project load, restores tabs based on user-chosen mode:
  - Auto:   reopen tabs immediately
  - Prompt: ask user when project is loaded
  - Delay:  reopen tabs after a configurable delay (seconds)

On QGIS close, compares current tabs to saved list. If different, warns
the user that saving tabs will also save the project.

v0.7:
  - Set core=True (always-on, cannot be disabled)
v0.6:
  - Add Cancel button to shutdown prompt — cancels QGIS close
v0.5:
  - Use QEvent.Close event filter on main window for reliable quit detection
  - Replaces QgsApplication.aboutToQuit which fired too late
v0.4:
  - Use QgsApplication.aboutToQuit (unreliable — replaced in v0.5)
v0.3:
  - Snapshot comparison instead of dirty flag
v0.2:
  - Dirty flag tracking, shutdown warning
v0.1:
  - Initial implementation
"""
__version__ = "0.9"

import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QRadioButton, QSpinBox, QDialogButtonBox, QPushButton,
    QMessageBox, QButtonGroup,
)
from qgis.PyQt.QtCore import Qt, QSettings, QTimer, QEvent, QObject
from qgis.core import QgsProject

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
_S_ROOT = "QFAT/QFAT04/addon_tab_restore/"
_S_MODE = _S_ROOT + "mode"          # "auto", "prompt", "delay"
_S_DELAY = _S_ROOT + "delay_secs"   # int, default 5

_PROJECT_VAR = "codepad_open_tabs"   # stored in project custom variables
_SEP = "||"                          # separator for path list in variable

# Module-level state
_connected = False
_dock_ref = None
_write_handler = None
_read_handler = None
_close_filter = None


# ---------------------------------------------------------------------------
# Close event filter — catches main window close reliably
# ---------------------------------------------------------------------------
class _CloseEventFilter(QObject):
    """Event filter installed on QGIS main window to detect close."""
    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self._dock = dock

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Close:
            if not _is_dock_alive(self._dock):
                return False
            result = _on_close(self._dock)
            if result == "cancel":
                event.ignore()
                return True  # block the close
        return False  # pass through


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------
def _get_mode():
    return QSettings().value(_S_MODE, "prompt", type=str)


def _get_delay():
    return QSettings().value(_S_DELAY, 5, type=int)


# ---------------------------------------------------------------------------
# Save / restore helpers
# ---------------------------------------------------------------------------
def _collect_tab_paths(dock):
    """Collect ordered list of open file paths from tabs."""
    if not _is_dock_alive(dock):
        return []
    paths = []
    for i in range(dock.tabs.count()):
        page = dock.tabs.widget(i)
        if page and getattr(page, "path", None):
            paths.append(page.path)
    return paths


def _write_tabs_to_project(paths):
    """Write tab paths to project custom variable."""
    proj = QgsProject.instance()
    cvars = proj.customVariables()
    if paths:
        cvars[_PROJECT_VAR] = _SEP.join(paths)
    else:
        cvars.pop(_PROJECT_VAR, None)
    proj.setCustomVariables(cvars)


def _read_tabs_from_project():
    """Read saved tab paths from project variable. Returns list or empty."""
    proj = QgsProject.instance()
    cvars = proj.customVariables()
    raw = cvars.get(_PROJECT_VAR, "")
    if not raw:
        return []
    return [p.strip() for p in raw.split(_SEP) if p.strip()]


def _is_dirty(dock):
    """Compare current open tabs to saved project variable."""
    if not _is_dock_alive(dock):
        return False
    return _collect_tab_paths(dock) != _read_tabs_from_project()


def _open_tabs(dock, paths):
    """Open file paths as tabs, skip missing files and already-open paths."""
    if not _is_dock_alive(dock):
        return
    open_paths = set()
    for i in range(dock.tabs.count()):
        page = dock.tabs.widget(i)
        if page and getattr(page, "path", None):
            open_paths.add(os.path.normpath(page.path))
    opened = 0
    missing = []
    for p in paths:
        norm = os.path.normpath(p)
        if norm in open_paths:
            continue
        if os.path.exists(norm):
            dock.new_tab(p)
            open_paths.add(norm)
            opened += 1
        else:
            missing.append(os.path.basename(p))
    msg = "Restored %d tab(s)." % opened
    if missing:
        msg += " Missing: %s" % ", ".join(missing[:5])
        if len(missing) > 5:
            msg += " +%d more" % (len(missing) - 5)
    if opened or missing:
        dock.messages.append("[Tab Restore] " + msg)


# ---------------------------------------------------------------------------
# Signal handlers
# ---------------------------------------------------------------------------
def _is_dock_alive(dock):
    """Check if dock and its tabs widget are still valid Qt objects."""
    try:
        from qgis.PyQt import sip
    except ImportError:
        try:
            import sip
        except ImportError:
            return True  # can't check, assume alive
    try:
        if sip.isdeleted(dock) or sip.isdeleted(dock.tabs):
            return False
    except Exception:
        return False
    return True


def _on_write_project(dock):
    """Connected to QgsProject.writeProject — save tabs."""
    if not _is_dock_alive(dock):
        return
    try:
        paths = _collect_tab_paths(dock)
        _write_tabs_to_project(paths)
    except Exception as e:
        try:
            if _is_dock_alive(dock):
                dock.messages.append("[Tab Restore] Save error: %s" % str(e))
        except Exception:
            pass


def _on_read_project(dock):
    """Connected to QgsProject.readProject — restore tabs based on mode."""
    if not _is_dock_alive(dock):
        return
    paths = _read_tabs_from_project()
    if not paths:
        return
    mode = _get_mode()
    if mode == "auto":
        _open_tabs(dock, paths)
    elif mode == "delay":
        delay_ms = _get_delay() * 1000
        QTimer.singleShot(delay_ms, lambda: _open_tabs(dock, paths))
    else:  # prompt
        _prompt_restore(dock, paths)


def _prompt_restore(dock, paths):
    """Show a message box asking user to restore tabs."""
    count = len(paths)
    reply = QMessageBox.question(
        dock,
        "Restore Tabs",
        "This project has %d saved CodePad tab(s).\n\nRestore them now?" % count,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if reply == QMessageBox.Yes:
        _open_tabs(dock, paths)


# ---------------------------------------------------------------------------
# Startup — connect signals once
# ---------------------------------------------------------------------------
def _on_startup(dock):
    global _connected, _dock_ref, _close_filter, _write_handler, _read_handler
    if _connected:
        return
    _dock_ref = dock
    proj = QgsProject.instance()
    _write_handler = lambda _doc=None: _on_write_project(dock)
    _read_handler = lambda _doc=None: _on_read_project(dock)
    proj.writeProject.connect(_write_handler)
    proj.readProject.connect(_read_handler)

    # Install close event filter on QGIS main window
    main_window = dock.iface.mainWindow()
    _close_filter = _CloseEventFilter(dock, main_window)
    main_window.installEventFilter(_close_filter)

    _connected = True

    # If a project is already loaded at startup, check for saved tabs
    if proj.fileName():
        paths = _read_tabs_from_project()
        if paths:
            mode = _get_mode()
            if mode == "auto":
                _open_tabs(dock, paths)
            elif mode == "delay":
                delay_ms = _get_delay() * 1000
                QTimer.singleShot(delay_ms, lambda: _open_tabs(dock, paths))
            else:
                _prompt_restore(dock, paths)


# ---------------------------------------------------------------------------
# Close handler — compare and prompt if different
# Returns "cancel" to block close, anything else to allow
# ---------------------------------------------------------------------------
def _on_close(dock):
    proj = QgsProject.instance()
    if proj.fileName() and _is_dirty(dock):
        reply = QMessageBox.question(
            dock,
            "Save Tab List",
            "Your open tabs have changed since the last project save.\n\n"
            "Saving the tab list will also save all project changes.\n\n"
            "Save now?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            paths = _collect_tab_paths(dock)
            _write_tabs_to_project(paths)
            proj.write()
            return "save"
        elif reply == QMessageBox.Cancel:
            return "cancel"
    return "ok"


# ---------------------------------------------------------------------------
# Shutdown — disconnect signals, remove event filter
# ---------------------------------------------------------------------------
def _on_shutdown(dock):
    global _connected, _dock_ref, _close_filter, _write_handler, _read_handler
    if _connected:
        try:
            proj = QgsProject.instance()
            if _write_handler is not None:
                try:
                    proj.writeProject.disconnect(_write_handler)
                except Exception:
                    pass
            if _read_handler is not None:
                try:
                    proj.readProject.disconnect(_read_handler)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if _close_filter:
                dock.iface.mainWindow().removeEventFilter(_close_filter)
                _close_filter = None
        except Exception:
            pass
        _connected = False
    _dock_ref = None
    _write_handler = None
    _read_handler = None


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class TabRestoreSettings(QDialog):
    def __init__(self, dock, parent=None):
        super().__init__(parent or dock)
        self.setWindowTitle("Tab Restore Settings  v" + __version__)
        self.resize(400, 280)
        s = QSettings()
        layout = QVBoxLayout(self)

        # Mode
        mode_grp = QGroupBox("Restore mode (when a project is loaded)")
        mode_lay = QVBoxLayout(mode_grp)
        self.btn_group = QButtonGroup(self)
        self.rb_auto = QRadioButton("Auto — reopen tabs immediately")
        self.rb_prompt = QRadioButton("Prompt — ask before restoring")
        self.rb_delay = QRadioButton("Delay — reopen tabs after a delay")
        self.btn_group.addButton(self.rb_auto)
        self.btn_group.addButton(self.rb_prompt)
        self.btn_group.addButton(self.rb_delay)
        mode_lay.addWidget(self.rb_auto)
        mode_lay.addWidget(self.rb_prompt)
        mode_lay.addWidget(self.rb_delay)
        current_mode = s.value(_S_MODE, "prompt", type=str)
        if current_mode == "auto":
            self.rb_auto.setChecked(True)
        elif current_mode == "delay":
            self.rb_delay.setChecked(True)
        else:
            self.rb_prompt.setChecked(True)
        layout.addWidget(mode_grp)

        # Delay spinner
        delay_grp = QGroupBox("Delay settings")
        delay_lay = QHBoxLayout(delay_grp)
        delay_lay.addWidget(QLabel("Delay (seconds):"))
        self.spn_delay = QSpinBox()
        self.spn_delay.setRange(1, 120)
        self.spn_delay.setValue(s.value(_S_DELAY, 5, type=int))
        delay_lay.addWidget(self.spn_delay)
        delay_lay.addStretch()
        layout.addWidget(delay_grp)

        # Reset
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._reset)
        layout.addWidget(btn_reset)

        # OK / Cancel
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reset(self):
        self.rb_prompt.setChecked(True)
        self.spn_delay.setValue(5)

    def _save(self):
        s = QSettings()
        if self.rb_auto.isChecked():
            s.setValue(_S_MODE, "auto")
        elif self.rb_delay.isChecked():
            s.setValue(_S_MODE, "delay")
        else:
            s.setValue(_S_MODE, "prompt")
        s.setValue(_S_DELAY, self.spn_delay.value())
        self.accept()


def _settings_dialog(dock):
    return TabRestoreSettings(dock)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def register():
    return {
        "id": "tab_restore",
        "name": "Tab Restore  v" + __version__,
        "description": "Save open editor tabs with the QGIS project and restore "
                       "them on project load. Modes: auto, prompt, or delayed.",
        "core": True,
        "builtin": True,
        "hooks": {
            "on_startup": _on_startup,
            "on_shutdown": _on_shutdown,
            "settings_dialog": _settings_dialog,
        },
    }
