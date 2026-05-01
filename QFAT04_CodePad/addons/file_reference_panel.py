"""
file_reference_panel.py
Addon: File Reference Panel — shows all files referenced in the active document.

Scans the entire file for paths and displays them in a tree panel,
split into Text Files and GIS Layers. Double-click to open/load.

Uses the fuzzy_loader addon's extraction engine.
"""
import os

from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QMenu
from qgis.PyQt.QtCore import Qt


def _get_fuzzy_loader():
    """Import functions from fuzzy_loader addon (must be loaded first)."""
    try:
        from . import fuzzy_loader
        return fuzzy_loader
    except ImportError:
        return None


class FileReferencesPanel(QWidget):
    """Panel showing all referenced files in the active document."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dock = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Referenced Files"])
        self.tree.setRootIsDecorated(True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree)

    def set_dock(self, dock):
        self._dock = dock

    def refresh(self, dock, page):
        self.tree.clear()
        fl = _get_fuzzy_loader()
        if not fl or not page or not page.path:
            return
        text = page.editor.editor_text() if hasattr(page.editor, "editor_text") else ""
        base_dir = os.path.dirname(page.path)
        all_paths = fl.extract_fuzzy_paths(text, base_dir)
        gis_exts = fl._get_gis_exts()
        editor_exts = fl._get_editor_exts()
        editor_files = []
        gis_files = []
        for p in all_paths:
            ext = os.path.splitext(p)[1].lower()
            if ext in gis_exts:
                gis_files.append(p)
            elif ext in editor_exts:
                editor_files.append(p)
            else:
                editor_files.append(p)

        if editor_files:
            grp = QTreeWidgetItem(self.tree, ["Text Files (%d)" % len(editor_files)])
            grp.setExpanded(True)
            for p in editor_files:
                item = QTreeWidgetItem(grp, [os.path.basename(p)])
                item.setData(0, Qt.UserRole, p)
                item.setToolTip(0, p)

        if gis_files:
            grp = QTreeWidgetItem(self.tree, ["GIS Layers (%d)" % len(gis_files)])
            grp.setExpanded(True)
            for p in gis_files:
                item = QTreeWidgetItem(grp, [os.path.basename(p)])
                item.setData(0, Qt.UserRole, p)
                item.setToolTip(0, p)

        if not editor_files and not gis_files:
            self.tree.addTopLevelItem(QTreeWidgetItem(["No file references found"]))

    def _on_double_click(self, item, _col):
        path = item.data(0, Qt.UserRole)
        if not path or not self._dock:
            return
        fl = _get_fuzzy_loader()
        if not fl:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in fl._get_gis_exts():
            fl._load_gis_layer(self._dock.iface, path)
        else:
            self._dock.new_tab(path)

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        fl = _get_fuzzy_loader()
        if not fl:
            return
        menu = QMenu(self)
        ext = os.path.splitext(path)[1].lower()
        if ext in fl._get_gis_exts():
            act = menu.addAction("Load to QGIS")
            act.triggered.connect(lambda: fl._load_gis_layer(self._dock.iface, path))
        if ext in fl._get_editor_exts():
            act = menu.addAction("Open in Editor")
            act.triggered.connect(lambda: self._dock.new_tab(path))
        act_exp = menu.addAction("Show in Explorer")
        act_exp.triggered.connect(lambda: fl._show_in_explorer(path))
        menu.exec_(self.tree.viewport().mapToGlobal(pos))


# ---------------------------------------------------------------------------
# Global panel instance
# ---------------------------------------------------------------------------
_panel = FileReferencesPanel()


def _create_panel(dock):
    _panel.set_dock(dock)
    return {
        "id": "file_reference_panel",
        "title": "File References",
        "widget": _panel,
        "area": "left",
    }


def _on_tab_changed(dock, page):
    _panel.refresh(dock, page)


def _on_file_opened(dock, page, path):
    _panel.refresh(dock, page)


def _on_file_saved(dock, page, path):
    _panel.refresh(dock, page)


def _on_startup(dock):
    page = dock.current_page()
    _panel.refresh(dock, page)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def register():
    return {
        "id": "file_reference_panel",
        "name": "File Reference Panel",
        "description": "Shows all files referenced in the active document. "
                       "Requires Fuzzy Loader addon.",
        "builtin": True,
        "hooks": {
            "panel": _create_panel,
            "on_tab_changed": _on_tab_changed,
            "on_file_opened": _on_file_opened,
            "on_file_saved": _on_file_saved,
            "on_startup": _on_startup,
        },
    }
