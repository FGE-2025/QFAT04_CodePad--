"""
sample_word_count.py
Sample addon demonstrating the QFAT04 addon API.
Adds a "Word Count" panel that updates when tabs change.
"""
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit


class WordCountPanel(QWidget):
    """A simple panel that shows word/line/char count for the active file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlaceholderText("Open a file to see word count.")
        layout.addWidget(self.info)
        self._dock = None

    def set_dock(self, dock):
        self._dock = dock

    def update_counts(self, dock, page):
        if page is None:
            self.info.setPlainText("No file open.")
            return
        text = page.editor.editor_text() if hasattr(page.editor, 'editor_text') else ""
        lines = text.splitlines()
        words = text.split()
        chars = len(text)
        name = page.title() if hasattr(page, 'title') else "Untitled"
        self.info.setPlainText(
            "File: %s\n"
            "Lines: %d\n"
            "Words: %d\n"
            "Characters: %d\n"
            "Non-empty lines: %d\n"
            "Comment lines: %d"
            % (name, len(lines), len(words), chars,
               sum(1 for l in lines if l.strip()),
               sum(1 for l in lines if l.strip().startswith(("!", "#", "REM", "::"))))
        )


# Global instance so hooks can reference it
_panel = WordCountPanel()


def _create_panel(dock):
    """Panel hook: return a dict with widget + placement info."""
    _panel.set_dock(dock)
    return {
        "id": "word_count",
        "title": "Word Count",
        "widget": _panel,
        "area": "bottom",  # left, right, top, bottom
    }


def _on_tab_changed(dock, page):
    """Update word count when the active tab changes."""
    _panel.update_counts(dock, page)


def _on_file_saved(dock, page, path):
    """Update word count after saving."""
    _panel.update_counts(dock, page)


def _on_startup(dock):
    """Initial count on startup."""
    page = dock.current_page()
    _panel.update_counts(dock, page)


def _settings_dialog(dock):
    """Settings hook: return a QDialog for addon configuration."""
    from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QDialogButtonBox, QLabel
    from qgis.PyQt.QtCore import QSettings

    class WordCountSettings(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Word Count Settings")
            self.resize(350, 200)
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("Configure Word Count panel behaviour:"))
            s = QSettings()
            self.chk_comments = QCheckBox("Count comment lines separately")
            self.chk_comments.setChecked(s.value("QFAT/QFAT04/addon_wordcount/show_comments", True, type=bool))
            self.chk_empty = QCheckBox("Show non-empty line count")
            self.chk_empty.setChecked(s.value("QFAT/QFAT04/addon_wordcount/show_empty", True, type=bool))
            layout.addWidget(self.chk_comments)
            layout.addWidget(self.chk_empty)
            layout.addStretch()
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(self._save_and_close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        def _save_and_close(self):
            s = QSettings()
            s.setValue("QFAT/QFAT04/addon_wordcount/show_comments", self.chk_comments.isChecked())
            s.setValue("QFAT/QFAT04/addon_wordcount/show_empty", self.chk_empty.isChecked())
            self.accept()

    return WordCountSettings(dock)


def register():
    """
    Register this addon with the QFAT04 addon system.
    
    Returns a dict with:
        id:          unique identifier
        name:        display name shown in Addon Manager
        description: short description
        hooks:       dict mapping hook names to callbacks
    """
    return {
        "id": "sample_word_count",
        "name": "Word Count Panel",
        "description": "Shows word, line, and character count for the active file.",
        "builtin": True,
        "hooks": {
            "panel": _create_panel,
            "on_tab_changed": _on_tab_changed,
            "on_file_saved": _on_file_saved,
            "on_startup": _on_startup,
            "settings_dialog": _settings_dialog,
        },
    }
