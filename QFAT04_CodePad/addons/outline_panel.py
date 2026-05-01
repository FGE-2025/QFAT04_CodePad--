"""
outline_panel.py
Addon: Outline Panel — shows a structural outline of the active file.

For TUFLOW files, lists all lines containing '==' (command assignments).
Click an item to jump to that line in the editor.
"""
import os

from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem
from qgis.PyQt.QtCore import Qt


class OutlinePanel(QWidget):
    """Panel showing structural outline of the active document."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dock = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Outline"])
        self.tree.setRootIsDecorated(True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree)

    def set_dock(self, dock):
        self._dock = dock

    def refresh(self, dock, page):
        self.tree.clear()
        if not page:
            return
        lang_def = dock.languages.get(page.language, {}) if hasattr(dock, "languages") else {}
        base = lang_def.get("base", page.language if hasattr(page, "language") else "text")
        text = page.editor.editor_text() if hasattr(page.editor, "editor_text") else ""
        lines = text.splitlines()

        if base == "tuflow":
            root = QTreeWidgetItem(self.tree, ["Commands (%d)" % sum(
                1 for l in lines if "==" in l and not l.strip().startswith(("!", "#")))])
            root.setExpanded(True)
            for n, line in enumerate(lines, 1):
                stripped = line.strip()
                if "==" in line and not stripped.startswith(("!", "#")):
                    item = QTreeWidgetItem(root, ["%d: %s" % (n, stripped[:100])])
                    item.setData(0, Qt.UserRole, n)
        elif base == "batch":
            root = QTreeWidgetItem(self.tree, ["Labels & Commands"])
            root.setExpanded(True)
            for n, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith(":") and not stripped.startswith("::"):
                    item = QTreeWidgetItem(root, ["%d: %s" % (n, stripped[:100])])
                    item.setData(0, Qt.UserRole, n)
        elif base == "powershell":
            root = QTreeWidgetItem(self.tree, ["Functions"])
            root.setExpanded(True)
            for n, line in enumerate(lines, 1):
                stripped = line.strip().lower()
                if stripped.startswith("function "):
                    item = QTreeWidgetItem(root, ["%d: %s" % (n, line.strip()[:100])])
                    item.setData(0, Qt.UserRole, n)
        else:
            root = QTreeWidgetItem(self.tree, ["Lines: %d" % len(lines)])

        self.tree.expandAll()

    def _on_double_click(self, item, _col):
        """Jump to the line in the editor."""
        line_num = item.data(0, Qt.UserRole)
        if not line_num or not self._dock:
            return
        page = self._dock.current_page()
        if not page:
            return
        editor = page.editor
        if page.editor_kind == "scintilla":
            editor.setCursorPosition(line_num - 1, 0)
            editor.ensureLineVisible(line_num - 1)
        else:
            cursor = editor.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.NextBlock, cursor.MoveAnchor, line_num - 1)
            editor.setTextCursor(cursor)
            editor.ensureCursorVisible()
        editor.setFocus()


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------
_panel = OutlinePanel()


def _create_panel(dock):
    _panel.set_dock(dock)
    return {
        "id": "outline_panel",
        "title": "Outline",
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
        "id": "outline_panel",
        "name": "Outline Panel",
        "description": "Shows a structural outline of the active file. "
                       "TUFLOW: lists == commands. Batch: labels. PowerShell: functions. "
                       "Double-click to jump to line.",
        "builtin": True,
        "hooks": {
            "panel": _create_panel,
            "on_tab_changed": _on_tab_changed,
            "on_file_opened": _on_file_opened,
            "on_file_saved": _on_file_saved,
            "on_startup": _on_startup,
        },
    }
