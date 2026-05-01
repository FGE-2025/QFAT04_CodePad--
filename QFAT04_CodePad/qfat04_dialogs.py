"""
qfat04_dialogs.py
All UI popup / dialog code.

Dialogs:
  LocalStylerDialog       – per-token style editor (fg/bg/font/bold/italic/underline)
  LanguageEditorDialog    – 13-tab language definition editor
  LanguageManagerDialog   – create / edit / duplicate / delete languages
  Color Theme tab in SettingsDialog – global theme chrome editor
  SettingsDialog          – preferences
  ShortcutCaptureDialog   – capture a key sequence
  ShortcutsDialog         – editor shortcut manager
  PlaceholderDialog       – generic "not yet implemented"
"""

import os
import re
import copy
import json

from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QColor, QFont, QKeySequence
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .qfat04_config import (
    THEMES,
    DEFAULT_EDITOR_SHORTCUTS,
    _language_defaults,
    _clean_language_fields,
    _norm_ext_list,
    list_theme_names,
    get_theme,
    save_theme,
    delete_theme,
    get_style_override,
    set_style_override,
    style_font_from_theme,
    style_color,
    style_paper,
    style_font,
    language_display_name,
    make_language_key,
    load_editor_shortcuts,
    load_config,
    save_config,
    DEFAULT_HIGHLIGHT_PRIORITIES,
)
from .qfat04_languages import BasicHighlighter


# ===========================================================================
# LocalStylerDialog
# ===========================================================================
class LocalStylerDialog(QDialog):
    """Small Styler popup attached to a specific token type inside the Language Editor.
    
    Empty fg/bg = no override (Tier 1 theme color is used).
    Filled fg/bg = Tier 3 user override.
    Transparent bg = no background color (inherits paper).
    """

    def __init__(self, style_name, style_data=None, parent=None, theme_color=None, reset_label=None):
        super().__init__(parent)
        self.setWindowTitle("Styler – %s" % style_name)
        self.resize(480, 320)
        self._data         = copy.deepcopy(style_data or {})
        self._style_name   = style_name
        self._theme_fg     = (theme_color or {}).get("fg", "#808080")
        self._theme_bg     = (theme_color or {}).get("bg", "")
        self._theme_font   = (theme_color or {}).get("font_family", "Consolas")
        self._theme_size   = (theme_color or {}).get("font_size", 10)
        self._theme_bold   = (theme_color or {}).get("bold", False)
        self._theme_italic = (theme_color or {}).get("italic", False)
        self._theme_underline = (theme_color or {}).get("underline", False)

        self._fg_override  = self._data.get("fg", "")
        self._bg_override  = self._data.get("bg", "")

        root = QVBoxLayout(self)

        font_grp = QGroupBox("Font options")
        fg = QGridLayout(font_grp)

        self.cmb_font = QFontComboBox()
        if self._data.get("font_family"):
            self.cmb_font.setCurrentFont(QFont(self._data["font_family"]))
        else:
            self.cmb_font.setCurrentFont(QFont(self._theme_font))

        self.cmb_size = QComboBox()
        self.cmb_size.setEditable(True)
        for i in range(6, 49):
            self.cmb_size.addItem(str(i))
        if self._data.get("font_size"):
            self.cmb_size.setCurrentText(str(int(self._data["font_size"])))
        else:
            self.cmb_size.setCurrentText(str(self._theme_size))

        self.chk_bold      = QCheckBox("Bold");      self.chk_bold.setChecked(bool(self._data.get("bold",      False)))
        self.chk_italic    = QCheckBox("Italic");    self.chk_italic.setChecked(bool(self._data.get("italic",    False)))
        self.chk_underline = QCheckBox("Underline"); self.chk_underline.setChecked(bool(self._data.get("underline", False)))

        # Foreground — swatch shows effective color (theme or custom)
        self.btn_fg = QPushButton(""); self.btn_fg.setFixedSize(40, 26)
        self.lbl_fg_status = QLabel()
        self.btn_fg.clicked.connect(lambda: self._pick("fg"))

        # Background — swatch + Transparent checkbox
        self.btn_bg = QPushButton(""); self.btn_bg.setFixedSize(40, 26)
        self.lbl_bg_status = QLabel()
        self.chk_transparent = QCheckBox("Transparent")
        self.chk_transparent.setToolTip("No background colour — inherits editor paper")
        self.chk_transparent.setChecked(self._bg_override == "")
        self.chk_transparent.toggled.connect(self._transparent_toggled)
        self.btn_bg.clicked.connect(lambda: self._pick("bg"))

        fg.addWidget(QLabel("Font:"),        0, 0); fg.addWidget(self.cmb_font,         0, 1, 1, 3); fg.addWidget(self.chk_bold,      0, 4)
        fg.addWidget(QLabel("Size:"),        1, 0); fg.addWidget(self.cmb_size,         1, 1);       fg.addWidget(self.chk_italic,    1, 4)
        fg.addWidget(QLabel("Foreground:"),  2, 0); fg.addWidget(self.btn_fg,           2, 1); fg.addWidget(self.lbl_fg_status, 2, 2, 1, 2); fg.addWidget(self.chk_underline, 2, 4)
        fg.addWidget(QLabel("Background:"),  3, 0); fg.addWidget(self.btn_bg,           3, 1); fg.addWidget(self.chk_transparent, 3, 2); fg.addWidget(self.lbl_bg_status, 3, 3)

        root.addWidget(font_grp)

        btn_reset = QPushButton(reset_label or "Fill Active Theme Color and Style")
        btn_reset.setToolTip("Fills the fields with the source colour and font.\nYou can then edit from there. Click OK to save.")
        btn_reset.clicked.connect(self._fill_from_theme)
        root.addWidget(btn_reset)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._refresh_fg_display()
        self._refresh_bg_display()

    def _effective_fg(self):
        return self._fg_override if self._fg_override else self._theme_fg

    def _effective_bg(self):
        return self._bg_override if self._bg_override else self._theme_bg

    def _paint(self, btn, color):
        if color:
            btn.setStyleSheet("background:%s; border:1px solid #666;" % color)
            btn.setText("")
        else:
            btn.setStyleSheet("border:1px solid #666; color:gray;")
            btn.setText("—")

    def _refresh_fg_display(self):
        self._paint(self.btn_fg, self._effective_fg())
        if self._fg_override:
            self.lbl_fg_status.setText("(custom: %s)" % self._fg_override)
        else:
            self.lbl_fg_status.setText("(theme: %s)" % self._theme_fg)

    def _refresh_bg_display(self):
        is_transparent = self.chk_transparent.isChecked()
        if is_transparent:
            self.btn_bg.setStyleSheet("border:1px solid #666; color:gray;")
            self.btn_bg.setText("—")
            self.btn_bg.setEnabled(False)
            self.lbl_bg_status.setText("(transparent)")
        else:
            self.btn_bg.setEnabled(True)
            bg = self._effective_bg()
            if bg:
                self._paint(self.btn_bg, bg)
            else:
                self.btn_bg.setStyleSheet("border:1px solid #666; color:gray;")
                self.btn_bg.setText("—")
            if self._bg_override:
                self.lbl_bg_status.setText("(custom: %s)" % self._bg_override)
            else:
                self.lbl_bg_status.setText("(theme)" if not self._theme_bg else "(theme: %s)" % self._theme_bg)

    def _transparent_toggled(self, checked):
        if checked:
            self._bg_override = ""
        self._refresh_bg_display()

    def _pick(self, which):
        if which == "bg" and self.chk_transparent.isChecked():
            return
        if which == "fg":
            start = QColor(self._effective_fg())
        else:
            start = QColor(self._effective_bg() or "#1e1e1e")
        color = QColorDialog.getColor(start, self, "Choose colour")
        if not color.isValid():
            return
        if which == "fg":
            self._fg_override = color.name()
            self._refresh_fg_display()
        else:
            self._bg_override = color.name()
            self.chk_transparent.setChecked(False)
            self._refresh_bg_display()

    def _fill_from_theme(self):
        """Fill all fields with active theme values as a starting point for editing."""
        self._fg_override = self._theme_fg
        self._bg_override = self._theme_bg
        if self._theme_bg:
            self.chk_transparent.setChecked(False)
        else:
            self.chk_transparent.setChecked(True)
        self._refresh_fg_display()
        self._refresh_bg_display()
        self.cmb_font.setCurrentFont(QFont(self._theme_font))
        self.cmb_size.setCurrentText(str(self._theme_size))
        self.chk_bold.setChecked(bool(self._theme_bold))
        self.chk_italic.setChecked(bool(self._theme_italic))
        self.chk_underline.setChecked(bool(self._theme_underline))

    def values(self):
        try:
            size = int(self.cmb_size.currentText().strip())
        except Exception:
            size = 10
        return {
            "font_family": self.cmb_font.currentFont().family(),
            "font_size":   size,
            "bold":        self.chk_bold.isChecked(),
            "italic":      self.chk_italic.isChecked(),
            "underline":   self.chk_underline.isChecked(),
            "fg":          self._fg_override,
            "bg":          self._bg_override,
        }


# ===========================================================================
# LanguageEditorDialog  – 13 tabs
# ===========================================================================
class LanguageEditorDialog(QDialog):
    """
    Deep editor for a single language definition.

    Tabs: General | Extensions | Commands | Keyword Groups |
          Comments | Numbers | Operators | Delimiters |
          Folding | Validation | Help & IntelliSense | Snippets | Preview
    """

    def __init__(self, language_key, language, parent=None, allow_delete=False, dock=None):
        super().__init__(parent)
        self.language_key    = language_key
        self.language        = copy.deepcopy(language)
        self.delete_requested = False
        self.allow_delete    = allow_delete
        self._dock           = dock
        # Store config reference for theme font lookups
        if dock and hasattr(dock, "config"):
            self._config_ref = dock.config
        elif parent and hasattr(parent, "config"):
            self._config_ref = parent.config
        else:
            self._config_ref = {}
        self.setWindowTitle("Language Editor – %s" % language.get("name", language_key))
        self.resize(1060, 780)

        root = QVBoxLayout(self)

        # ── top bar: name + action buttons ─────────────────────────────
        top = QHBoxLayout()
        self.txt_name = QLineEdit(self.language.get("name", self.language.get("default_name", language_key)))
        self.txt_name.setToolTip("Display name for this language.\nUsed in the Language menu and tab labels.")
        self.btn_save_as = QPushButton("Save As Copy...")
        self.btn_save_as.setToolTip("Create a copy of this language with a new name.\nUseful for creating a custom variant of a built-in language.")
        self.btn_rename  = QPushButton("Rename")
        self.btn_rename.setToolTip("Change the internal key and display name of this language.")
        self.btn_remove  = QPushButton("Remove")
        self.btn_remove.setToolTip("Delete this language definition.\nBuilt-in languages cannot be removed.")
        top.addWidget(QLabel("Language name:"))
        top.addWidget(self.txt_name, 1)
        for b in (self.btn_save_as, self.btn_rename, self.btn_remove):
            top.addWidget(b)
        root.addLayout(top)

        # ── row 2: case-sensitive + import/export ───────────────────────
        row2 = QHBoxLayout()
        self.chk_case_sensitive = QCheckBox("Case sensitive for all rules")
        self.chk_case_sensitive.setToolTip("When checked, keyword matching and comment prefix detection\nwill be case-sensitive for this language.")
        self.chk_case_sensitive.setChecked(bool(self.language.get("case_sensitive", False)))
        self.btn_import = QPushButton("Import...")
        self.btn_import.setToolTip("Import a language definition from a .json file.")
        self.btn_export = QPushButton("Export...")
        self.btn_export.setToolTip("Export this language definition to a .json file\nfor backup or sharing with others.")
        row2.addWidget(self.chk_case_sensitive)
        row2.addStretch(1)
        row2.addWidget(self.btn_import)
        row2.addWidget(self.btn_export)
        root.addLayout(row2)

        # ── tab widget ──────────────────────────────────────────────────
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # Override tracking: maps tab_key -> (QRadioButton_default, QRadioButton_override, [widgets_to_toggle])
        self._override_radios = {}
        self._override_widgets = {}

        self._build_general_tab()
        self._build_operators_tab()
        self._build_numbers_tab()
        self._build_path_tab()
        self._build_delimiters_tab()
        self._build_keyword_groups_tab()
        self._build_variables_tab()
        self._build_comments_tab()
        self._build_folding_tab()
        self._build_addon_tabs()
        self._build_theme_tab()

        # ── buttons ─────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.btn_fill_defaults = QPushButton("Fill in Factory Base Language Rules")
        self.btn_fill_defaults.setToolTip(
            "Copy the Base Language's default rules into the current tab's fields.\n"
            "The tab stays in Custom mode so you can edit from there.\n"
            "Useful as a starting point when customising.")
        self.btn_fill_factory_theme = QPushButton("Fill in Factory Theme Styles")
        self.btn_fill_factory_theme.setToolTip(
            "Copy the factory theme's colours and font into the current tab's token style.\n"
            "Reads from the theme's .json file only (ignoring Theme Editor edits).\n"
            "The tab stays in its current mode.")
        self.btn_fill_factory_theme.clicked.connect(self._fill_factory_theme_style)
        self.btn_set_theme_style = QPushButton("Fill in Custom Theme Styles")
        self.btn_set_theme_style.setToolTip(
            "Copy the active theme's colours and font into the current tab's token style.\n"
            "Includes your Theme Editor edits.\n"
            "The tab stays in its current mode.")
        btn_row.addWidget(self.btn_fill_defaults)
        btn_row.addWidget(self.btn_fill_factory_theme)
        btn_row.addWidget(self.btn_set_theme_style)
        self.btn_clear_tab = QPushButton("Clear Current Tab")
        self.btn_clear_tab.setToolTip(
            "Empty out all fields on the current tab.\n"
            "The tab stays in Custom mode — empty fields mean no detection for that token type.\n"
            "Shift+double-click to clear ALL tabs at once.")
        self.btn_clear_tab.clicked.connect(self._clear_current_tab)
        self.btn_clear_tab.installEventFilter(self)
        self.btn_clear_tab.setProperty("_clear_all_tabs", True)
        btn_row.addWidget(self.btn_clear_tab)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        root.addWidget(buttons)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply_live)
        self.btn_fill_defaults.clicked.connect(self._fill_default_rules)
        self.btn_set_theme_style.clicked.connect(self._set_theme_style_current)
        self.btn_save_as.clicked.connect(self._save_as)
        self.btn_rename.clicked.connect(self._rename)
        self.btn_remove.clicked.connect(self._remove_language)
        self.btn_import.clicked.connect(self._import_language)
        self.btn_export.clicked.connect(self._export_language)

        self._populate_from_language(self.language)
        # Mark init complete so _toggle_override_3 starts working
        self._init_complete = True
        # Now apply override modes (triggers stash/restore and enable/disable)
        saved_overrides = self.language.get("_tab_overrides", {})
        for tab_key in ("general", "keywords", "comments", "numbers",
                        "operators", "delimiters", "folding", "path", "variables"):
            val = saved_overrides.get(tab_key, 1)
            if isinstance(val, bool):
                val = 2 if val else 1
            self._set_override_mode(tab_key, int(val))
    # ------------------------------------------------------------------
    # Override toggle helpers
    # ------------------------------------------------------------------
    def _make_override_header(self, tab_key, layout):
        """Add 3-option radio buttons to top of a tab layout.
        Option 1: Follow Factory Rules + Factory Theme Style (T1)
        Option 2: Follow Factory Rules + Active Theme Style (T1 rules + T2 style)
        Option 3: Custom Rules + Custom Style (T3)
        """
        from qgis.PyQt.QtWidgets import QButtonGroup
        row = QHBoxLayout()
        rad_factory  = QRadioButton("Factory Rules && Factory Theme")
        rad_factory.setToolTip(
            "Use the Base Language's built-in rules.\n"
            "Token colours come from the theme's .json file only (ignoring Theme Editor edits).\n"
            "All fields are greyed out.\n"
            "Shift+double-click to apply this mode to ALL tabs.")
        rad_theme    = QRadioButton("Factory Rules && Active Theme")
        rad_theme.setToolTip(
            "Use the Base Language's built-in rules.\n"
            "Token colours follow the active Color Theme (including your Theme Editor edits).\n"
            "All fields are greyed out.\n"
            "Shift+double-click to apply this mode to ALL tabs.")
        rad_custom   = QRadioButton("Custom Rules && Style")
        rad_custom.setToolTip(
            "Define your own rules and style for this tab.\n"
            "Fields become editable — your settings override the Base Language defaults.\n"
            "Leave fields empty to disable detection for that token type.\n"
            "Colours: use Styler to set per-language overrides. If not set, follows active theme.\n"
            "Shift+double-click to apply this mode to ALL tabs.")
        grp = QButtonGroup(self)
        grp.addButton(rad_factory, 0)
        grp.addButton(rad_theme, 1)
        grp.addButton(rad_custom, 2)
        row.addWidget(rad_factory)
        row.addWidget(rad_theme)
        row.addWidget(rad_custom)
        row.addStretch(1)
        layout.addLayout(row)
        hint = QLabel("Leave empty will disable detection for this token type.")
        hint.setStyleSheet("color: gray; font-size: 10px; font-style: italic;")
        hint.setVisible(False)
        layout.addWidget(hint)
        self._override_radios[tab_key] = (rad_factory, rad_theme, rad_custom)
        self._override_widgets[tab_key] = []
        self._override_hints = getattr(self, "_override_hints", {})
        self._override_hints[tab_key] = hint
        rad_factory.toggled.connect(lambda _: self._toggle_override_3(tab_key))
        rad_theme.toggled.connect(lambda _: self._toggle_override_3(tab_key))
        rad_custom.toggled.connect(lambda _: self._toggle_override_3(tab_key))
        # Shift+double-click on any radio → apply that mode to ALL tabs
        for mode_idx, rad in enumerate((rad_factory, rad_theme, rad_custom)):
            rad.installEventFilter(self)
            rad.setProperty("_override_mode", mode_idx)
        return rad_factory, rad_theme, rad_custom

    def _register_override_widgets(self, tab_key, widgets):
        """Register widgets that should be enabled/disabled by the override toggle."""
        self._override_widgets[tab_key] = widgets

    def _toggle_override_3(self, tab_key):
        """Enable or disable widgets based on 3-radio state.
        Mode 0/1: stash custom values (only if user was in mode 2), show factory defaults.
        Mode 2: restore custom values (editable)."""
        # Guard: don't run during __init__ before tabs are built
        if not hasattr(self, "_init_complete"):
            return
        mode = self._get_override_mode(tab_key)
        is_custom = (mode == 2)
        for w in self._override_widgets.get(tab_key, []):
            w.setEnabled(is_custom)
        hints = getattr(self, "_override_hints", {})
        if tab_key in hints:
            hints[tab_key].setVisible(is_custom)

        if not hasattr(self, "_custom_stash"):
            self._custom_stash = {}
        if not hasattr(self, "_was_in_custom"):
            self._was_in_custom = set()

        if mode in (0, 1):
            # Only stash if user has actually been in custom mode this session
            if tab_key in self._was_in_custom and tab_key not in self._custom_stash:
                self._custom_stash[tab_key] = self._read_tab_fields(tab_key)
            self._fill_factory_values(tab_key)
        elif mode == 2:
            self._was_in_custom.add(tab_key)
            # Restore stashed custom values if available
            if tab_key in self._custom_stash:
                self._write_tab_fields(tab_key, self._custom_stash[tab_key])
                del self._custom_stash[tab_key]
            # Auto-populate T3 font for tokens that don't have one yet
            # This makes Mode 2 font independent from theme changes
            self._ensure_t3_font(tab_key)

    def _toggle_override(self, tab_key, is_override):
        """Legacy compat — set to custom (2) or theme (1)."""
        self._set_override_mode(tab_key, 2 if is_override else 1)

    def _get_override_mode(self, tab_key):
        """Return 0=factory, 1=theme, 2=custom."""
        radios = self._override_radios.get(tab_key)
        if not radios or len(radios) < 3:
            return 2
        if radios[0].isChecked(): return 0
        if radios[1].isChecked(): return 1
        return 2

    def _is_override(self, tab_key):
        """Check if a tab is in Custom mode (mode 2)."""
        return self._get_override_mode(tab_key) == 2

    def _set_override_state(self, tab_key, is_override):
        """Legacy compat — set custom or theme mode."""
        self._set_override_mode(tab_key, 2 if is_override else 1)

    def _read_tab_fields(self, tab_key):
        """Read current field values from a tab into a dict for stashing."""
        data = {}
        if tab_key == "general":
            data["extensions"] = self.ed_exts.text()
            data["case_sensitive"] = self.chk_case_sensitive.isChecked()
        elif tab_key == "comments":
            data["comment_open"] = self.ed_comment_open.text()
            data["comment_continue"] = self.ed_comment_continue.text()
            data["comment_close"] = self.ed_comment_close.text()
            data["block_open"] = self.ed_block_comment_open.text()
            data["block_close"] = self.ed_block_comment_close.text()
            data["comment_any"] = self.rad_comment_any.isChecked()
            data["fold_comments"] = self.chk_fold_comments.isChecked()
        elif tab_key == "keywords":
            data["groups"] = [self.keyword_edits[i].toPlainText() for i in range(6)]
            data["prefix_modes"] = [self.prefix_checks[i].isChecked() for i in range(6)]
        elif tab_key == "numbers":
            data["prefix1"] = self.ed_num_prefix1.text()
            data["prefix2"] = self.ed_num_prefix2.text()
            data["extras1"] = self.ed_num_extras1.text()
            data["extras2"] = self.ed_num_extras2.text()
            data["suffix1"] = self.ed_num_suffix1.text()
            data["suffix2"] = self.ed_num_suffix2.text()
            data["range"] = self.ed_num_range.text()
            data["dec_dot"] = self.rad_dec_dot.isChecked()
            data["dec_comma"] = self.rad_dec_comma.isChecked()
            data["dec_both"] = self.rad_dec_both.isChecked()
        elif tab_key == "operators":
            data["ops"] = [self.ed_ops[i].text() for i in range(6)]
        elif tab_key == "delimiters":
            data["delims"] = []
            for grp in self._delim_grp_boxes:
                edits = grp.findChildren(QLineEdit)
                data["delims"].append([e.text() for e in edits])
        elif tab_key == "folding":
            data["folds"] = [(o.text(), m.text(), c.text()) for o, m, c in self._fold_edits]
            data["compact"] = self.chk_fold_compact.isChecked()
        elif tab_key == "path":
            data["pattern"] = self.ed_path_pattern.toPlainText()
        elif tab_key == "variables":
            data["patterns"] = [self.var_list.item(i).text() for i in range(self.var_list.count())]
        return data

    def _write_tab_fields(self, tab_key, data):
        """Restore stashed field values back into a tab."""
        if not data:
            return
        if tab_key == "general":
            self.ed_exts.setText(data.get("extensions", ""))
            self.chk_case_sensitive.setChecked(data.get("case_sensitive", False))
        elif tab_key == "comments":
            self.ed_comment_open.setText(data.get("comment_open", ""))
            self.ed_comment_continue.setText(data.get("comment_continue", ""))
            self.ed_comment_close.setText(data.get("comment_close", ""))
            self.ed_block_comment_open.setText(data.get("block_open", ""))
            self.ed_block_comment_close.setText(data.get("block_close", ""))
            if data.get("comment_any", True):
                self.rad_comment_any.setChecked(True)
            self.chk_fold_comments.setChecked(data.get("fold_comments", True))
        elif tab_key == "keywords":
            for i, text in enumerate(data.get("groups", [])):
                if i < 6: self.keyword_edits[i].setPlainText(text)
            for i, checked in enumerate(data.get("prefix_modes", [])):
                if i < 6: self.prefix_checks[i].setChecked(checked)
        elif tab_key == "numbers":
            self.ed_num_prefix1.setText(data.get("prefix1", ""))
            self.ed_num_prefix2.setText(data.get("prefix2", ""))
            self.ed_num_extras1.setText(data.get("extras1", ""))
            self.ed_num_extras2.setText(data.get("extras2", ""))
            self.ed_num_suffix1.setText(data.get("suffix1", ""))
            self.ed_num_suffix2.setText(data.get("suffix2", ""))
            self.ed_num_range.setText(data.get("range", ""))
            if data.get("dec_dot"): self.rad_dec_dot.setChecked(True)
            elif data.get("dec_comma"): self.rad_dec_comma.setChecked(True)
            elif data.get("dec_both"): self.rad_dec_both.setChecked(True)
        elif tab_key == "operators":
            for i, text in enumerate(data.get("ops", [])):
                if i < 6: self.ed_ops[i].setText(text)
        elif tab_key == "delimiters":
            for idx, delim_vals in enumerate(data.get("delims", [])):
                if idx < len(self._delim_grp_boxes):
                    edits = self._delim_grp_boxes[idx].findChildren(QLineEdit)
                    for j, val in enumerate(delim_vals):
                        if j < len(edits): edits[j].setText(val)
        elif tab_key == "folding":
            for idx, (ov, mv, cv) in enumerate(data.get("folds", [])):
                if idx < len(self._fold_edits):
                    o, m, c = self._fold_edits[idx]
                    o.setText(ov); m.setText(mv); c.setText(cv)
            self.chk_fold_compact.setChecked(data.get("compact", False))
        elif tab_key == "path":
            self.ed_path_pattern.setPlainText(data.get("pattern", ""))
        elif tab_key == "variables":
            self.var_list.clear()
            for pat in data.get("patterns", []):
                if pat.strip():
                    self.var_list.addItem(QListWidgetItem(pat.strip()))

    def _set_override_mode(self, tab_key, mode):
        """Set the override mode: 0=factory, 1=theme, 2=custom."""
        radios = self._override_radios.get(tab_key)
        if radios and len(radios) >= 3:
            radios[mode].setChecked(True)
            self._toggle_override_3(tab_key)

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------
    def _build_general_tab(self):
        tab  = QWidget(); root = QVBoxLayout(tab); root.setSpacing(4)

        # ── Base language (always editable) ──
        base_row = QHBoxLayout()
        self._lbl_base = QLabel("Base language:")
        base_row.addWidget(self._lbl_base)
        self.cmb_base = QComboBox(); self.cmb_base.addItems(["tuflow", "batch", "powershell", "python", "r", "sql", "html", "text"])
        self.cmb_base.setToolTip("Select the base language engine.\nDetermines the default highlighting behaviour, comment style, and operator set.")
        self.cmb_base.currentTextChanged.connect(self._on_base_changed)
        base_row.addWidget(self.cmb_base); base_row.addStretch(1)
        root.addLayout(base_row)

        # ── Override toggle ──
        rad_fac, rad_thm, rad_cust = self._make_override_header("general", root)

        # ── Extensions + Case sensitive + Normal text (single compact row group) ──
        settings_grp = QGroupBox()
        sg = QGridLayout(settings_grp); sg.setContentsMargins(6, 4, 6, 4); sg.setSpacing(4)
        self.ed_exts = QLineEdit(); self.ed_exts.setPlaceholderText("tcf,tgc,tmf,tef,trd,toc,ecf")
        self.ed_exts.setToolTip("File extensions that will use this language for syntax highlighting.\nComma-separated, no dots, e.g. tcf,tgc,tmf")
        sg.addWidget(QLabel("Extensions:"), 0, 0); sg.addWidget(self.ed_exts, 0, 1, 1, 3)
        sg.addWidget(self.chk_case_sensitive, 1, 0, 1, 2)
        sg.addWidget(QLabel("Normal text:"), 1, 2)
        self.btn_normal_styler = QPushButton("Styler...")
        self.btn_normal_styler.setToolTip(
            "Open the style editor for Normal text (unmatched text).\n"
            "Set a custom foreground colour, background colour, font, and font style.\n"
            "Use 'Follow Theme Style (Color and Font)' inside the editor to revert to the active Color Theme.\n"
            "Only applies when 'Custom rules and style' is selected.")
        self.btn_normal_styler.clicked.connect(lambda: self._open_styler("text"))
        sg.addWidget(self.btn_normal_styler, 1, 3)
        sg.setColumnStretch(1, 1)
        root.addWidget(settings_grp)

        # ── Priorities (compact) ──
        pri_grp = QGroupBox("Highlight priorities — drag to reorder (top = lowest)")
        pri_v = QVBoxLayout(pri_grp); pri_v.setContentsMargins(6, 4, 6, 4); pri_v.setSpacing(2)
        self._pri_list = QListWidget()
        self._pri_list.setDragDropMode(QListWidget.InternalMove)
        self._pri_list.setMaximumHeight(180)
        self._pri_token_labels = {
            "operator":  "Operator  (==, >, <, +, …)",
            "number":    "Number",
            "string":    "String / Delimiter",
            "keyword1":  "Keyword Group 1",
            "keyword2":  "Keyword Group 2",
            "keyword3":  "Keyword Group 3",
            "keyword4":  "Keyword Group 4",
            "keyword5":  "Keyword Group 5",
            "keyword6":  "Keyword Group 6",
            "path":      "Path  (file / folder)",
            "variable":  "Variable",
            "comment":   "Comment  🔒 always highest",
        }
        default_order = sorted(
            [(k,v) for k,v in DEFAULT_HIGHLIGHT_PRIORITIES.items() if k != "comment"],
            key=lambda x: x[1]
        )
        for key, _ in default_order:
            item = QListWidgetItem(self._pri_token_labels.get(key, key))
            item.setData(Qt.UserRole, key)
            self._pri_list.addItem(item)
        comment_item = QListWidgetItem(self._pri_token_labels["comment"])
        comment_item.setData(Qt.UserRole, "comment")
        comment_item.setFlags(comment_item.flags() & ~Qt.ItemIsDragEnabled)
        self._pri_list.addItem(comment_item)
        self._pri_list.model().rowsMoved.connect(self._enforce_comment_last)
        pri_v.addWidget(self._pri_list)
        btn_reset_pri = QPushButton("Reset priorities")
        btn_reset_pri.setMaximumWidth(120)
        btn_reset_pri.setToolTip("Reset the highlight priority order to the built-in defaults.")
        btn_reset_pri.clicked.connect(self._reset_priorities)
        pri_v.addWidget(btn_reset_pri)
        root.addWidget(pri_grp)

        # ── Notes (compact) ──
        doc_grp = QGroupBox("Notes")
        doc_l = QVBoxLayout(doc_grp); doc_l.setContentsMargins(6, 4, 6, 4)
        self.ed_doc_text = QPlainTextEdit()
        self.ed_doc_text.setPlaceholderText("Reference notes / documentation URL")
        self.ed_doc_text.setMaximumHeight(60)
        doc_l.addWidget(self.ed_doc_text)
        self.ed_default_style_note = QPlainTextEdit()
        self.ed_default_style_note.setMaximumHeight(0)
        self.ed_default_style_note.setVisible(False)
        root.addWidget(doc_grp)
        root.addStretch(1)
        self.tabs.addTab(tab, "General")

        self._register_override_widgets("general", [
            settings_grp, pri_grp, btn_reset_pri,
        ])

        # Hidden feature: Shift+double-click on "Base language:" label opens the .json file
        self._lbl_base.installEventFilter(self)


    def _build_keyword_groups_tab(self):
        tab  = QWidget(); root = QVBoxLayout(tab)

        rad_fac, rad_thm, rad_cust = self._make_override_header("keywords", root)

        root.addWidget(QLabel(
            "Up to 6 keyword groups.  Each group highlights exact whole-word matches.  "
            "One keyword per line.  Each group has its own style."
        ))
        grid = QGridLayout()
        self.keyword_edits         = []
        self.prefix_checks         = []
        self.keyword_style_buttons = []
        self._keyword_grp_boxes    = []
        labels = ["Group 1", "Group 2", "Group 3", "Group 4", "Group 5", "Group 6"]
        for i in range(6):
            grp = QGroupBox(labels[i]); lay = QVBoxLayout(grp)
            row = QHBoxLayout()
            btn = QPushButton("Styler...")
            btn.setToolTip(
                "Open the style editor for Keyword Group %d tokens.\n"
                "Set a custom foreground colour, background colour, font, and font style.\n"
                "Use 'Follow Theme Style (Color and Font)' inside the editor to revert to the active Color Theme.\n"
                "Only applies when 'Custom rules and style' is selected." % (i + 1))
            btn.clicked.connect(lambda _=False, idx=i: self._open_styler("keyword%d" % (idx + 1)))
            chk = QCheckBox("Prefix mode")
            chk.setToolTip("When checked, keywords in this group match as prefixes\n(the start of a word) rather than exact whole-word matches.")
            row.addWidget(btn); row.addWidget(chk); row.addStretch(1)
            lay.addLayout(row)
            ed = QPlainTextEdit()
            ed.setPlaceholderText("One keyword per line")
            lay.addWidget(ed, 1)
            self.keyword_edits.append(ed)
            self.prefix_checks.append(chk)
            self.keyword_style_buttons.append(btn)
            self._keyword_grp_boxes.append(grp)
            grid.addWidget(grp, i // 2, i % 2)
        root.addLayout(grid, 1)
        self.tabs.addTab(tab, "Keyword Groups")

        self._register_override_widgets("keywords", self._keyword_grp_boxes)

    def _build_comments_tab(self):
        tab  = QWidget(); root = QVBoxLayout(tab)

        rad_fac, rad_thm, rad_cust = self._make_override_header("comments", root)

        pos_grp = QGroupBox("Line comment position")
        pos_l   = QVBoxLayout(pos_grp)
        self.rad_comment_any   = QRadioButton("Allow anywhere")
        self.rad_comment_start = QRadioButton("Force at start of line")
        self.rad_comment_ws    = QRadioButton("Allow preceding whitespace")
        pos_l.addWidget(self.rad_comment_any)
        pos_l.addWidget(self.rad_comment_start)
        pos_l.addWidget(self.rad_comment_ws)
        self.rad_comment_any.setChecked(True)

        self.chk_fold_comments = QCheckBox("Allow folding of comments")
        top_row = QHBoxLayout()
        top_row.addWidget(pos_grp)
        top_row.addWidget(self.chk_fold_comments)
        top_row.addStretch(1)
        root.addLayout(top_row)

        line_grp = QGroupBox("Line comment prefixes")
        fl = QFormLayout(line_grp)
        self.ed_comment_open     = QLineEdit(); self.ed_comment_open.setPlaceholderText("e.g.  !   or  !, #   or  REM")
        self.ed_comment_continue = QLineEdit(); self.ed_comment_continue.setPlaceholderText("continuation character (optional)")
        self.ed_comment_close    = QLineEdit(); self.ed_comment_close.setPlaceholderText("close character (optional)")
        fl.addRow("Prefix(es) – comma separated", self.ed_comment_open)
        fl.addRow("Continue character",            self.ed_comment_continue)
        fl.addRow("Close",                         self.ed_comment_close)

        block_grp = QGroupBox("Block comment")
        fb = QFormLayout(block_grp)
        self.ed_block_comment_open  = QLineEdit(); self.ed_block_comment_open.setPlaceholderText("open  e.g. /*")
        self.ed_block_comment_close = QLineEdit(); self.ed_block_comment_close.setPlaceholderText("close e.g. */")
        fb.addRow("Open",  self.ed_block_comment_open)
        fb.addRow("Close", self.ed_block_comment_close)

        mid = QHBoxLayout()
        mid.addWidget(line_grp, 1)
        mid.addWidget(block_grp, 1)
        root.addLayout(mid)

        sty = QHBoxLayout()
        sty.addWidget(QLabel("Comment style:"))
        self.btn_comment_styler = QPushButton("Styler...")
        self.btn_comment_styler.setToolTip(
            "Open the style editor for Comment tokens.\n"
            "Set a custom foreground colour, background colour, font, and font style.\n"
            "Use 'Follow Theme Style (Color and Font)' inside the editor to revert to the active Color Theme.\n"
            "Only applies when 'Custom rules and style' is selected.")
        self.btn_comment_styler.clicked.connect(lambda: self._open_styler("comment"))
        sty.addWidget(self.btn_comment_styler); sty.addStretch(1)
        root.addLayout(sty)
        root.addStretch(1)
        self.tabs.addTab(tab, "Comments")

        self._register_override_widgets("comments", [
            pos_grp, self.chk_fold_comments, line_grp, block_grp, self.btn_comment_styler,
        ])

    def _build_numbers_tab(self):
        tab = QWidget(); root = QVBoxLayout(tab)
        rad_fac, rad_thm, rad_cust = self._make_override_header("numbers", root)

        grp = QGroupBox("Number style"); ng = QGridLayout(grp)
        self.ed_num_prefix1 = QLineEdit(); self.ed_num_prefix2 = QLineEdit()
        self.ed_num_extras1 = QLineEdit(); self.ed_num_extras2 = QLineEdit()
        self.ed_num_suffix1 = QLineEdit(); self.ed_num_suffix2 = QLineEdit()
        self.ed_num_range   = QLineEdit()

        self.ed_num_prefix1.setToolTip("Characters that appear BEFORE a number to trigger detection.\nExample: '0x' for hex numbers (0xFF), '#' for colour codes (#FF0000).\nLeave empty for plain digits only.")
        self.ed_num_prefix2.setToolTip("Second prefix option. Matched as alternative to Prefix 1.\nExample: Prefix 1 = '0x', Prefix 2 = '0b' (binary 0b1010).")
        self.ed_num_extras1.setToolTip("Extra characters allowed INSIDE a number alongside digits.\nExample: 'a-fA-F' for hex digits, '_' for thousand separators (1_000).\nThese characters are added to the digit character class.")
        self.ed_num_extras2.setToolTip("Second set of extra characters. Combined with Extras 1.\nExample: Extras 1 = 'a-f', Extras 2 = 'A-F'.")
        self.ed_num_suffix1.setToolTip("Characters that appear AFTER a number.\nExample: 'px' for CSS pixels (100px), 'L' for C long (42L), '%' for percentages.\nLeave empty if numbers end with digits only.")
        self.ed_num_suffix2.setToolTip("Second suffix option. Matched as alternative to Suffix 1.\nExample: Suffix 1 = 'px', Suffix 2 = 'em'.")
        self.ed_num_range.setToolTip("Character that connects two numbers as a range.\nExample: '-' to match '1-10' or ':' to match '1:100'.\nLeave empty to disable range detection.")

        ng.addWidget(QLabel("Prefix 1"), 0, 0); ng.addWidget(self.ed_num_prefix1, 0, 1)
        ng.addWidget(QLabel("Prefix 2"), 0, 2); ng.addWidget(self.ed_num_prefix2, 0, 3)
        ng.addWidget(QLabel("Extras 1"), 1, 0); ng.addWidget(self.ed_num_extras1, 1, 1)
        ng.addWidget(QLabel("Extras 2"), 1, 2); ng.addWidget(self.ed_num_extras2, 1, 3)
        ng.addWidget(QLabel("Suffix 1"), 2, 0); ng.addWidget(self.ed_num_suffix1, 2, 1)
        ng.addWidget(QLabel("Suffix 2"), 2, 2); ng.addWidget(self.ed_num_suffix2, 2, 3)
        ng.addWidget(QLabel("Range"),    3, 0); ng.addWidget(self.ed_num_range,   3, 1, 1, 3)
        dec_grp = QGroupBox("Decimal separator"); dl = QVBoxLayout(dec_grp)
        self.rad_dec_dot   = QRadioButton("Dot");   self.rad_dec_dot.setChecked(True)
        self.rad_dec_comma = QRadioButton("Comma")
        self.rad_dec_both  = QRadioButton("Both")
        self.rad_dec_dot.setToolTip("Decimal point is a dot: 3.14")
        self.rad_dec_comma.setToolTip("Decimal point is a comma: 3,14")
        self.rad_dec_both.setToolTip("Accept both dot and comma: 3.14 or 3,14")
        dl.addWidget(self.rad_dec_dot); dl.addWidget(self.rad_dec_comma); dl.addWidget(self.rad_dec_both)
        ng.addWidget(dec_grp, 0, 4, 4, 1)
        root.addWidget(grp)

        sty = QHBoxLayout(); sty.addWidget(QLabel("Number style:"))
        self.btn_number_styler = QPushButton("Styler...")
        self.btn_number_styler.setToolTip(
            "Open the style editor for Number tokens.\n"
            "Set a custom foreground colour, background colour, font, and font style.\n"
            "Use 'Follow Theme Style (Color and Font)' inside the editor to revert to the active Color Theme.\n"
            "Only applies when 'Custom rules and style' is selected.")
        self.btn_number_styler.clicked.connect(lambda: self._open_styler("number"))
        sty.addWidget(self.btn_number_styler); sty.addStretch(1)
        root.addLayout(sty)
        root.addStretch(1)
        self.tabs.addTab(tab, "Numbers")
        self._register_override_widgets("numbers", [grp, self.btn_number_styler])

    def _build_operators_tab(self):
        tab = QWidget(); root = QVBoxLayout(tab)
        rad_fac, rad_thm, rad_cust = self._make_override_header("operators", root)
        grp = QGroupBox("Operators (space or comma separated)")
        og = QGridLayout(grp)
        self.ed_ops = []
        for i in range(6):
            og.addWidget(QLabel("Operators %d" % (i + 1)), i // 2 * 2, i % 2)
            ed = QLineEdit()
            og.addWidget(ed, i // 2 * 2 + 1, i % 2)
            self.ed_ops.append(ed)
        root.addWidget(grp)
        sty = QHBoxLayout(); sty.addWidget(QLabel("Operator style:"))
        self.btn_operator_styler = QPushButton("Styler...")
        self.btn_operator_styler.setToolTip(
            "Open the style editor for Operator tokens.\n"
            "Set a custom foreground colour, background colour, font, and font style.\n"
            "Use 'Follow Theme Style (Color and Font)' inside the editor to revert to the active Color Theme.\n"
            "Only applies when 'Custom rules and style' is selected.")
        self.btn_operator_styler.clicked.connect(lambda: self._open_styler("operator"))
        sty.addWidget(self.btn_operator_styler); sty.addStretch(1)
        root.addLayout(sty)
        root.addStretch(1)
        self.tabs.addTab(tab, "Operators")
        self._register_override_widgets("operators", [grp, self.btn_operator_styler])

    def _build_delimiters_tab(self):
        tab = QWidget(); root = QVBoxLayout(tab)
        rad_fac, rad_thm, rad_cust = self._make_override_header("delimiters", root)
        root.addWidget(QLabel(
            "Define up to 5 string/delimiter pairs. Text between Open and Close characters\n"
            "will be highlighted as a string token. Leave empty to disable a slot."))
        # Examples
        ex = QLabel(
            '<span style="color:gray; font-size:8pt;">'
            'Examples: Double-quoted string: Open <b>"</b> Close <b>"</b> Escape <b>\\</b> &nbsp;|&nbsp; '
            'Single-quoted: Open <b>\'</b> Close <b>\'</b> &nbsp;|&nbsp; '
            'Backtick: Open <b>`</b> Close <b>`</b></span>')
        root.addWidget(ex)
        grid = QGridLayout()
        self.delim_edits = []
        self._delim_grp_boxes = []
        for i in range(5):
            grp  = QGroupBox("String %d" % (i + 1)); form = QFormLayout(grp)
            form.setContentsMargins(4, 2, 4, 2)
            o, e, c = QLineEdit(), QLineEdit(), QLineEdit()
            o.setToolTip(
                "The opening character(s) that start a string.\n"
                "Examples: \" (double quote), ' (single quote), ` (backtick), /* (block comment open)")
            e.setToolTip(
                "The escape character inside the string that prevents the Close character from ending it.\n"
                "Example: \\ (backslash) — so \\\" inside a string is treated as a literal quote, not the end.\n"
                "Leave empty if no escape character is used.")
            c.setToolTip(
                "The closing character(s) that end a string.\n"
                "Usually the same as Open for quotes: \" or '\n"
                "Can differ for bracket-style: Open ( → Close )\n"
                "Leave empty to use the same character as Open.")
            form.addRow("Open",   o)
            form.addRow("Escape", e)
            form.addRow("Close",  c)
            self.delim_edits.append((o, e, c))
            self._delim_grp_boxes.append(grp)
            grid.addWidget(grp, i // 2, i % 2)
        root.addLayout(grid)
        sty = QHBoxLayout(); sty.addWidget(QLabel("String style:"))
        self.btn_string_styler = QPushButton("Styler...")
        self.btn_string_styler.setToolTip(
            "Open the style editor for String / Delimiter tokens.\n"
            "Set a custom foreground colour, background colour, font, and font style.\n"
            "Use 'Follow Theme Style (Color and Font)' inside the editor to revert to the active Color Theme.\n"
            "Only applies when 'Custom rules and style' is selected.")
        self.btn_string_styler.clicked.connect(lambda: self._open_styler("string"))
        sty.addWidget(self.btn_string_styler); sty.addStretch(1)
        root.addLayout(sty)
        self.tabs.addTab(tab, "String")
        self._register_override_widgets("delimiters", self._delim_grp_boxes + [self.btn_string_styler])

    def _build_folding_tab(self):
        tab = QWidget(); root = QVBoxLayout(tab)
        rad_fac, rad_thm, rad_cust = self._make_override_header("folding", root)

        # Python indent folding note (hidden by default)
        self._fold_python_note = QLabel(
            "<b>Python uses indentation-based folding.</b><br>"
            "Fold pairs below are not used. Blocks are detected automatically "
            "from indent level changes (def, class, if, for, etc.).")
        self._fold_python_note.setStyleSheet("color: #0066cc; padding: 6px; background: #e8f0fe; border-radius: 4px;")
        self._fold_python_note.setWordWrap(True)
        self._fold_python_note.setVisible(False)
        root.addWidget(self._fold_python_note)

        # Map: UI pair index -> json key prefix
        # Pair 1 = comment_*, Pair 2 = code1_*, ... Pair 6 = code5_*
        self._fold_key_prefixes = ["comment", "code1", "code2", "code3", "code4", "code5"]
        self._fold_edits = []  # list of (open, middle, close) tuples
        self._fold_grps = []
        open_tip = "The keyword that starts a foldable block.\nExample: 'If Scenario', 'Start 2D Domain'"
        mid_tip = "Optional keyword for an intermediate section inside the block.\nExample: 'Else If Scenario' between 'If Scenario' and 'End If'.\nLeave empty if not needed."
        close_tip = "The keyword that ends a foldable block.\nExample: 'End If', 'End 2D Domain'"
        for i in range(6):
            grp = QGroupBox("Fold pair %d" % (i + 1))
            f = QFormLayout(grp); f.setContentsMargins(4, 2, 4, 2)
            ed_open = QLineEdit(); ed_mid = QLineEdit(); ed_close = QLineEdit()
            ed_open.setToolTip(open_tip); ed_mid.setToolTip(mid_tip); ed_close.setToolTip(close_tip)
            f.addRow("Open", ed_open); f.addRow("Middle", ed_mid); f.addRow("Close", ed_close)
            self._fold_edits.append((ed_open, ed_mid, ed_close))
            self._fold_grps.append(grp)

        self.chk_fold_compact = QCheckBox("Compact folding (fold empty lines too)")
        self.chk_fold_compact.setToolTip(
            "When enabled, blank lines immediately following a fold block\n"
            "are included in the collapsed region.\n\n"
            "When disabled, blank lines after 'End If' stay visible\n"
            "even when the block above is collapsed.")

        # Layout: 3 rows of 2
        row1 = QHBoxLayout(); row1.addWidget(self._fold_grps[0]); row1.addWidget(self._fold_grps[1])
        root.addLayout(row1)
        row2 = QHBoxLayout(); row2.addWidget(self._fold_grps[2]); row2.addWidget(self._fold_grps[3])
        root.addLayout(row2)
        row3 = QHBoxLayout(); row3.addWidget(self._fold_grps[4]); row3.addWidget(self._fold_grps[5])
        root.addLayout(row3)
        root.addWidget(self.chk_fold_compact)

        sty_row = QHBoxLayout()
        sty_row.addWidget(QLabel("Folding marker style:"))
        self.btn_folding_styler = QPushButton("Styler...")
        self.btn_folding_styler.setToolTip(
            "Open the style editor for Folding marker tokens.\n"
            "Set a custom foreground colour, background colour, font, and font style.\n"
            "Use 'Follow Theme Style (Color and Font)' inside the editor to revert to the active Color Theme.\n"
            "Only applies when 'Custom rules and style' is selected.")
        self.btn_folding_styler.clicked.connect(lambda: self._open_styler("folding"))
        sty_row.addWidget(self.btn_folding_styler)
        sty_row.addStretch(1)
        root.addLayout(sty_row)
        root.addStretch(1)
        self.tabs.addTab(tab, "Folding")
        self._register_override_widgets("folding",
            self._fold_grps + [self.chk_fold_compact, self.btn_folding_styler])

    def _build_path_tab(self):
        """Path detection pattern + Styler."""
        tab  = QWidget(); root = QVBoxLayout(tab)
        rad_fac, rad_thm, rad_cust = self._make_override_header("path", root)
        root.addWidget(QLabel(
            "Path highlighting detects file and folder references in the text.\n"
            "Enter a regex pattern below, or leave empty to disable path detection."
        ))
        pat_grp = QGroupBox("Path detection pattern (regex)")
        pat_l   = QVBoxLayout(pat_grp)
        self.ed_path_pattern = QPlainTextEdit()
        self.ed_path_pattern.setMaximumHeight(80)
        self.ed_path_pattern.setPlainText(
            str(self.language.get("path_pattern", ""))
        )
        pat_l.addWidget(self.ed_path_pattern)
        root.addWidget(pat_grp)

        # Preset reference
        ref_grp = QGroupBox("Preset patterns (copy and paste into the field above)")
        ref_l = QVBoxLayout(ref_grp)
        presets = [
            ("TUFLOW (default)",
             r"[A-Za-z]:\\[^\s,!]+|\.\.?[\\\/][^\s,!]+|[\/\\][^\s,!]+"),
            ("All-in-one (drives, UNC, relative, Unix, quoted)",
             r"""[A-Za-z]:\\[^\s,!]+|\\\\[^\s,!]+|\.\.?[\\\/][^\s,!]+|[\/\\][^\s,!]+|"[^"]+"|'[^']+'"""),
            ("Windows only (drives + UNC)",
             r"[A-Za-z]:\\[^\s,!]+|\\\\[^\s,!]+"),
            ("Relative only",
             r"\.\.?[\\\/][^\s,!]+"),
            ("URLs (http/https/ftp)",
             r"https?://[^\s,!]+|ftp://[^\s,!]+"),
            ("Disabled", ""),
        ]
        for name, pattern in presets:
            row = QHBoxLayout()
            lbl = QLabel("<b>%s</b>" % name)
            lbl.setMinimumWidth(220)
            pat_field = QLineEdit(pattern)
            pat_field.setReadOnly(True)
            pat_field.setStyleSheet("background: #f4f4f4; font-family: monospace; font-size: 8pt;")
            pat_field.setToolTip("Click to select, then Ctrl+C to copy.\nOr double-click to select all.")
            row.addWidget(lbl)
            row.addWidget(pat_field, 1)
            ref_l.addLayout(row)
        root.addWidget(ref_grp)

        sty_row = QHBoxLayout()
        sty_row.addWidget(QLabel("Path style:"))
        self.btn_path_styler = QPushButton("Styler...")
        self.btn_path_styler.setToolTip(
            "Open the style editor for Path tokens.\n"
            "Set a custom foreground colour, background colour, font, and font style.\n"
            "Use 'Follow Theme Style (Color and Font)' inside the editor to revert to the active Color Theme.\n"
            "Only applies when 'Custom rules and style' is selected.")
        self.btn_path_styler.clicked.connect(lambda: self._open_styler("path"))
        sty_row.addWidget(self.btn_path_styler)
        sty_row.addStretch(1)
        root.addLayout(sty_row)
        root.addStretch(1)
        self.tabs.addTab(tab, "Path")
        self._register_override_widgets("path", [pat_grp, self.btn_path_styler])

    def _build_variables_tab(self):
        """Variable pattern list + Styler."""
        from qgis.PyQt.QtGui import QFont as _QFont
        tab  = QWidget(); root = QVBoxLayout(tab)
        rad_fac, rad_thm, rad_cust = self._make_override_header("variables", root)
        root.addWidget(QLabel(
            "Define variable patterns for this language.\n"
            "Use  ...  as a placeholder for the variable content,  e.g.  %...%   <<...>>   $..."
        ))

        self.var_list = QListWidget()
        self.var_list.setDragDropMode(QListWidget.InternalMove)
        self.var_list.setMaximumHeight(160)
        root.addWidget(self.var_list)

        add_row = QHBoxLayout()
        self.var_input = QLineEdit()
        self.var_input.setPlaceholderText("Add pattern, e.g.  %...%   <<...>>   $...   !...!")
        self.var_input.setFont(_QFont("Courier New", 10))
        self.btn_var_add = QPushButton("Add")
        self.btn_var_add.clicked.connect(self._add_variable_pattern)
        self.var_input.returnPressed.connect(self._add_variable_pattern)
        self.btn_var_del = QPushButton("Remove selected")
        self.btn_var_del.clicked.connect(self._remove_variable_pattern)
        add_row.addWidget(self.var_input, 1)
        add_row.addWidget(self.btn_var_add)
        add_row.addWidget(self.btn_var_del)
        root.addLayout(add_row)

        help_grp = QGroupBox("Pattern syntax")
        help_grid = QGridLayout(help_grp)
        syntax_rows = [
            ("%...%",   "wrapper — content between % delimiters, e.g. %EX%"),
            ("<<...>>", "wrapper — content between << >> delimiters, e.g. <<scenario>>"),
            ("~...~",   "wrapper — content between ~ delimiters, e.g. ~s1~"),
            ("$...",    "prefix  — word identifier after $, e.g. $varName"),
            ("!...!",   "wrapper — content between ! delimiters, e.g. !var!"),
            ("(regex)", "raw regex — used exactly as written"),
        ]
        for row_idx, (pat, desc) in enumerate(syntax_rows):
            lbl = QLabel(pat); lbl.setFont(_QFont("Courier New", 10))
            help_grid.addWidget(lbl,           row_idx, 0)
            help_grid.addWidget(QLabel(desc),  row_idx, 1)
        help_grid.setColumnStretch(1, 1)
        root.addWidget(help_grp)

        sty_row = QHBoxLayout()
        sty_row.addWidget(QLabel("Variable style:"))
        self.btn_variable_styler = QPushButton("Styler...")
        self.btn_variable_styler.setToolTip(
            "Open the style editor for Variable tokens.\n"
            "Set a custom foreground colour, background colour, font, and font style.\n"
            "Use 'Follow Theme Style (Color and Font)' inside the editor to revert to the active Color Theme.\n"
            "Only applies when 'Custom rules and style' is selected.")
        self.btn_variable_styler.clicked.connect(lambda: self._open_styler("variable"))
        sty_row.addWidget(self.btn_variable_styler)
        sty_row.addStretch(1)
        root.addLayout(sty_row)

        note = QLabel("Priority is set in the General tab priority list.")
        note.setStyleSheet("color: gray; font-size: 11px;")
        root.addWidget(note)
        root.addStretch(1)
        self.tabs.addTab(tab, "Variables")
        self._register_override_widgets("variables", [
            self.var_list, self.var_input, self.btn_var_add, self.btn_var_del,
            help_grp, self.btn_variable_styler,
        ])

    def _add_variable_pattern(self):
        text = self.var_input.text().strip()
        if not text:
            return
        for i in range(self.var_list.count()):
            if self.var_list.item(i).text() == text:
                self.var_input.clear()
                return
        self.var_list.addItem(QListWidgetItem(text))
        self.var_input.clear()

    def _remove_variable_pattern(self):
        row = self.var_list.currentRow()
        if row >= 0:
            self.var_list.takeItem(row)

    def _build_theme_tab(self):
        """Per-language colour overrides (Tier 3). Hidden for now — each tab has its own Styler."""
        pass  # Color Overrides tab hidden — functionality available per-tab via Styler buttons


    def _build_addon_tabs(self):
        """Let addons inject tabs into the Language Editor via the language_editor_tab hook."""
        # Hidden dummy widgets for backward compat — collect/populate still read these
        self.chk_auto = QCheckBox(); self.chk_hover = QCheckBox(); self.chk_sig = QCheckBox()
        self.ed_snippets = QPlainTextEdit()
        # Addon tabs
        if hasattr(self, '_dock') and self._dock and hasattr(self._dock, 'addon_manager'):
            hooks = self._dock.addon_manager.get_active_hooks("language_editor_tab")
            for hook_fn in hooks:
                try:
                    result = hook_fn(self._dock, self, self.language_key, self.language)
                    if isinstance(result, dict) and "title" in result and "widget" in result:
                        self.tabs.addTab(result["widget"], result["title"])
                except Exception as e:
                    print("QFAT04: language_editor_tab hook error: %s" % e)


    def _enforce_comment_last(self, *_):
        """Keep comment item pinned at the bottom after any drag."""
        lst = self._pri_list
        n   = lst.count()
        if n < 2:
            return
        last = lst.item(n - 1)
        if last and last.data(Qt.UserRole) == "comment":
            return
        # Find comment and move to bottom
        for i in range(n):
            item = lst.item(i)
            if item and item.data(Qt.UserRole) == "comment":
                lst.takeItem(i)
                lst.addItem(item)
                break

    def _reset_priorities(self):
        """Restore default order in the drag list."""
        lst = self._pri_list
        lst.clear()
        default_order = sorted(
            [(k,v) for k,v in DEFAULT_HIGHLIGHT_PRIORITIES.items() if k != "comment"],
            key=lambda x: x[1]
        )
        for key, _ in default_order:
            item = QListWidgetItem(self._pri_token_labels.get(key, key))
            item.setData(Qt.UserRole, key)
            lst.addItem(item)
        comment_item = QListWidgetItem(self._pri_token_labels["comment"])
        comment_item.setData(Qt.UserRole, "comment")
        comment_item.setFlags(comment_item.flags() & ~Qt.ItemIsDragEnabled)
        lst.addItem(comment_item)

    def _collect_priorities(self):
        """Assign priority values 1..N from list position (top=low, bottom=high)."""
        lst    = self._pri_list
        result = {}
        pri    = 1
        for i in range(lst.count()):
            item = lst.item(i)
            key  = item.data(Qt.UserRole)
            result[key] = pri
            pri += 1
        # Comment always gets max
        result["comment"] = pri
        return result


    def _populate_from_language(self, prof):
        prof = copy.deepcopy(prof or {})
        self.txt_name.setText(prof.get("name", prof.get("default_name", self.language_key)))
        self.cmb_base.setCurrentText(prof.get("base", "text"))
        self._on_base_changed(self.cmb_base.currentText())
        self.chk_case_sensitive.setChecked(bool(prof.get("case_sensitive", False)))
        self.ed_exts.setText(",".join(e.lstrip(".") for e in prof.get("extensions", [])))
        self.ed_doc_text.setPlainText(str(prof.get("doc_text", "")))
        self.ed_default_style_note.setPlainText(str(prof.get("default_style_note", "")))

        # Keyword groups
        groups       = self._split_keywords_for_display(prof)
        prefix_modes = prof.get("prefix_modes", [False] * 6)
        for i in range(6):
            self.keyword_edits[i].setPlainText(groups[i] if i < len(groups) else "")
            self.prefix_checks[i].setChecked(bool(prefix_modes[i]) if i < len(prefix_modes) else False)

        # Comments
        cpos = str(prof.get("comment_position", "anywhere"))
        self.rad_comment_any.setChecked(cpos == "anywhere")
        self.rad_comment_start.setChecked(cpos == "start")
        self.rad_comment_ws.setChecked(cpos == "whitespace")
        self.chk_fold_comments.setChecked(bool(prof.get("fold_comments", True)))
        self.ed_comment_open.setText(", ".join(prof.get("comment_prefixes", [])))
        self.ed_comment_continue.setText(str(prof.get("comment_continue", "")))
        self.ed_comment_close.setText(str(prof.get("comment_close", "")))
        self.ed_block_comment_open.setText(str(prof.get("block_comment_open", "")))
        self.ed_block_comment_close.setText(str(prof.get("block_comment_close", "")))

        # Numbers
        ns = prof.get("number_style", {}) if isinstance(prof.get("number_style"), dict) else {}
        self.ed_num_prefix1.setText(str(ns.get("prefix1", ""))); self.ed_num_prefix2.setText(str(ns.get("prefix2", "")))
        self.ed_num_extras1.setText(str(ns.get("extras1", ""))); self.ed_num_extras2.setText(str(ns.get("extras2", "")))
        self.ed_num_suffix1.setText(str(ns.get("suffix1", ""))); self.ed_num_suffix2.setText(str(ns.get("suffix2", "")))
        self.ed_num_range.setText(str(ns.get("range", "")))
        dec = str(ns.get("decimal", "dot"))
        self.rad_dec_dot.setChecked(dec == "dot")
        self.rad_dec_comma.setChecked(dec == "comma")
        self.rad_dec_both.setChecked(dec == "both")

        # Operators / delimiters
        for oi in range(6):
            self.ed_ops[oi].setText(str(prof.get("operators%d" % (oi + 1), "")))
        dels = prof.get("delimiters", []) if isinstance(prof.get("delimiters"), list) else []
        for i, triple in enumerate(self.delim_edits):
            d = dels[i] if i < len(dels) and isinstance(dels[i], dict) else {}
            triple[0].setText(str(d.get("open",   "")))
            triple[1].setText(str(d.get("escape", "")))
            triple[2].setText(str(d.get("close",  "")))

        # Folding
        fold = prof.get("folding", {}) if isinstance(prof.get("folding"), dict) else {}
        for i, prefix in enumerate(self._fold_key_prefixes):
            o, m, c = self._fold_edits[i]
            o.setText(str(fold.get(prefix + "_open", "")))
            m.setText(str(fold.get(prefix + "_middle", "")))
            c.setText(str(fold.get(prefix + "_close", "")))
        self.chk_fold_compact.setChecked(bool(fold.get("compact", False)))

        # Help
        h = prof.get("help", {}) if isinstance(prof.get("help"), dict) else {}
        self.chk_auto.setChecked(bool(h.get("autocomplete", False)))
        self.chk_hover.setChecked(bool(h.get("hover",       False)))
        self.chk_sig.setChecked(bool(h.get("signature",     False)))

        # Snippets
        self.ed_snippets.setPlainText(str(prof.get("snippets", "")))

        # Variable patterns
        self.var_list.clear()
        for pat in (prof.get("variable_patterns") or []):
            if str(pat).strip():
                self.var_list.addItem(QListWidgetItem(str(pat).strip()))

        # Highlight priorities — restore list order
        user_pri = prof.get("highlight_priorities", {})
        if isinstance(user_pri, dict) and user_pri:
            lst = self._pri_list
            lst.clear()
            non_comment = {k: v for k,v in user_pri.items() if k != "comment"}
            ordered = sorted(non_comment.items(), key=lambda x: x[1])
            # Fill in any missing keys at end (before comment)
            present = {k for k,_ in ordered}
            for k in self._pri_token_labels:
                if k != "comment" and k not in present:
                    ordered.append((k, 999))
            for key, _ in ordered:
                if key == "comment": continue
                item = QListWidgetItem(self._pri_token_labels.get(key, key))
                item.setData(Qt.UserRole, key)
                lst.addItem(item)
            comment_item = QListWidgetItem(self._pri_token_labels["comment"])
            comment_item.setData(Qt.UserRole, "comment")
            comment_item.setFlags(comment_item.flags() & ~Qt.ItemIsDragEnabled)
            lst.addItem(comment_item)
        else:
            self._reset_priorities()

        # Override modes are set in __init__ after _init_complete flag
        lst = self._pri_list
        n   = lst.count()
        if n < 2: return
        if lst.item(n-1) and lst.item(n-1).data(Qt.UserRole) == "comment": return
        for i in range(n):
            item = lst.item(i)
            if item and item.data(Qt.UserRole) == "comment":
                lst.takeItem(i); lst.addItem(item); break

    def _reset_priorities(self):
        lst = self._pri_list; lst.clear()
        from .qfat04_config import DEFAULT_HIGHLIGHT_PRIORITIES
        default_order = sorted(
            [(k,v) for k,v in DEFAULT_HIGHLIGHT_PRIORITIES.items() if k != "comment"],
            key=lambda x: x[1]
        )
        for key, _ in default_order:
            item = QListWidgetItem(self._pri_token_labels.get(key, key))
            item.setData(Qt.UserRole, key); lst.addItem(item)
        ci = QListWidgetItem(self._pri_token_labels.get("comment","Comment 🔒"))
        ci.setData(Qt.UserRole, "comment")
        ci.setFlags(ci.flags() & ~Qt.ItemIsDragEnabled)
        lst.addItem(ci)

    def _collect_priorities(self):
        lst = self._pri_list; result = {}; pri = 1
        for i in range(lst.count()):
            item = lst.item(i)
            key  = item.data(Qt.UserRole)
            result[key] = pri; pri += 1
        result["comment"] = pri
        return result

    def _split_keywords_for_display(self, prof):
        groups = prof.get("keyword_groups")
        if isinstance(groups, list) and groups:
            gs = [str(x) for x in groups[:6]]
            return gs + [""] * (6 - len(gs))
        kw = [str(x).strip() for x in prof.get("keywords", []) if str(x).strip()]
        gs    = [""] * 6
        gs[0] = "\n".join(kw)
        return gs

    def _collect_values(self):
        result = {
            "name":             self.txt_name.text().strip() or self.language_key,
            "base":             self.cmb_base.currentText(),
            "help": {
                "autocomplete": self.chk_auto.isChecked(),
                "hover":        self.chk_hover.isChecked(),
                "signature":    self.chk_sig.isChecked(),
            },
            "snippets":           self.ed_snippets.toPlainText(),
            "doc_text":           self.ed_doc_text.toPlainText(),
            "default_style_note": self.ed_default_style_note.toPlainText(),
            "builtin":            bool(self.language.get("builtin", False)),
        }

        # General tab — always collect (fields show factory values when mode 0/1)
        result["extensions"]           = _norm_ext_list(self.ed_exts.text())
        result["case_sensitive"]       = self.chk_case_sensitive.isChecked()
        if self._is_override("general"):
            result["highlight_priorities"] = self._collect_priorities()

        # Keywords — always collect
        groups = [ed.toPlainText().strip() for ed in self.keyword_edits]
        all_keywords = []
        for text in groups:
            all_keywords.extend(t for t in text.replace("\n", " ").replace("\r", " ").replace("\t", " ").split() if t)
        result["keyword_groups"]       = groups
        result["keywords"]             = list(dict.fromkeys(all_keywords))
        result["prefix_modes"]         = [chk.isChecked() for chk in self.prefix_checks]
        result["keyword_group_styles"] = ["keyword%d" % (i + 1) for i in range(6)]

        # Comments — always collect
        comment_pos = "anywhere"
        if self.rad_comment_start.isChecked():  comment_pos = "start"
        elif self.rad_comment_ws.isChecked():    comment_pos = "whitespace"
        result["comment_prefixes"]   = [x for x in re.split(r"[\s,;]+", self.ed_comment_open.text().strip()) if x]
        result["comment_position"]   = comment_pos
        result["fold_comments"]      = self.chk_fold_comments.isChecked()
        result["comment_continue"]   = self.ed_comment_continue.text().strip()
        result["comment_close"]      = self.ed_comment_close.text().strip()
        result["block_comment_open"] = self.ed_block_comment_open.text().strip()
        result["block_comment_close"] = self.ed_block_comment_close.text().strip()

        # Numbers — always collect
        # If all fields empty, save {} = no detection
        num_prefix1 = self.ed_num_prefix1.text().strip()
        num_prefix2 = self.ed_num_prefix2.text().strip()
        num_extras1 = self.ed_num_extras1.text().strip()
        num_extras2 = self.ed_num_extras2.text().strip()
        num_suffix1 = self.ed_num_suffix1.text().strip()
        num_suffix2 = self.ed_num_suffix2.text().strip()
        num_range   = self.ed_num_range.text().strip()
        has_any_num = any([num_prefix1, num_prefix2, num_extras1, num_extras2,
                           num_suffix1, num_suffix2, num_range])
        if has_any_num or self.rad_dec_comma.isChecked() or self.rad_dec_both.isChecked():
            decimal = "dot"
            if self.rad_dec_comma.isChecked():  decimal = "comma"
            elif self.rad_dec_both.isChecked(): decimal = "both"
            result["number_style"] = {
                "prefix1": num_prefix1, "prefix2": num_prefix2,
                "extras1": num_extras1, "extras2": num_extras2,
                "suffix1": num_suffix1, "suffix2": num_suffix2,
                "range":   num_range,   "decimal": decimal,
            }
        else:
            # All empty + dot (default) = no detection
            result["number_style"] = {}

        # Operators — always collect
        for oi in range(6):
            result["operators%d" % (oi + 1)] = self.ed_ops[oi].text().strip()

        # Delimiters — always collect
        result["delimiters"] = [
            {"open": a.text().strip(), "escape": b.text().strip(), "close": c.text().strip()}
            for a, b, c in self.delim_edits
        ]

        # Folding — always collect
        fold_data = {"compact": self.chk_fold_compact.isChecked()}
        any_set = False
        for i, prefix in enumerate(self._fold_key_prefixes):
            o, m, c = self._fold_edits[i]
            ov, mv, cv = o.text().strip(), m.text().strip(), c.text().strip()
            fold_data[prefix + "_open"]   = ov
            fold_data[prefix + "_middle"] = mv
            fold_data[prefix + "_close"]  = cv
            if ov or mv or cv:
                any_set = True
        if not any_set and not fold_data["compact"]:
            fold_data = {}
        result["folding"] = fold_data

        # Path — always collect
        result["path_pattern"] = self.ed_path_pattern.toPlainText().strip()

        # Variables — always collect
        result["variable_patterns"] = [
            self.var_list.item(i).text()
            for i in range(self.var_list.count())
            if self.var_list.item(i).text().strip()
        ]

        # Styles (Tier 3) — always include if present
        styles = self.language.get("styles", {})
        if styles:
            result["styles"] = copy.deepcopy(styles)

        # Save override mode per tab (0=factory, 1=theme, 2=custom)
        result["_tab_overrides"] = {
            tab_key: self._get_override_mode(tab_key)
            for tab_key in ("general", "keywords", "comments", "numbers",
                            "operators", "delimiters", "folding", "path", "variables")
        }

        return result

    def values(self):
        return self._collect_values()

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def _sample_text(self, base):
        if base == "tuflow":
            return (
                "! Heading comment\n"
                "Read GIS Mat == ..\\model\\gis\\2d_mat.shp\n"
                "Geometry Control File == model\\main.tgc\n"
                "Output Folder == results\\\n"
                "Cell Size == 5\n"
                "Scenario == EX\n"
            )
        if base == "batch":
            return "@echo off\nREM batch comment\nset RUN_NAME=test\nif exist results echo done\n"
        if base == "powershell":
            return "# powershell comment\n$runName = \"test\"\nif ($runName) { Write-Host $runName }\n"
        return "Plain text preview\nNo special syntax\n"


    def _open_styler(self, style_key):
        styles = self.language.setdefault("styles", {})
        # Resolve current theme color for this token (Tier 1)
        # Walk parent chain to find config
        config = {}
        parent = self.parent()
        while parent:
            if hasattr(parent, "config") and isinstance(getattr(parent, "config", None), dict):
                config = parent.config
                break
            parent = getattr(parent, "parent", lambda: None)()
        theme_name = config.get("theme", "Dark")
        theme_dict = get_theme(theme_name)
        # Effective color currently rendering: Tier 3 override or Tier 1 theme
        current_style = copy.deepcopy(styles.get(style_key, {}))
        tier3_fg = current_style.get("fg", "")
        tier1_fg = theme_dict.get(style_key, theme_dict.get("text", "#808080"))
        ts = theme_dict.get("token_styles", {}).get(style_key, {})
        tier1_bg = ts.get("bg", "")  # empty = transparent (inherits paper)
        theme_color = {
            "fg": tier1_fg,
            "bg": tier1_bg,
            "font_family": theme_dict.get("font_family", "Consolas"),
            "font_size": theme_dict.get("font_size", 10),
            "bold": ts.get("bold", False),
            "italic": ts.get("italic", False),
            "underline": ts.get("underline", False),
        }
        dlg = LocalStylerDialog(style_key, current_style, self, theme_color=theme_color)
        if dlg.exec_() == QDialog.Accepted:
            result = dlg.values()
            # Only store non-empty overrides
            clean = {}
            for k, v in result.items():
                if k in ("fg", "bg"):
                    if v and v.startswith("#"):
                        clean[k] = v
                elif k in ("bold", "italic", "underline"):
                    if v:
                        clean[k] = v
                elif k == "font_family" and v and v.strip():
                    clean[k] = v.strip()
                elif k == "font_size" and isinstance(v, int) and v > 0:
                    clean[k] = v
            if clean:
                styles[style_key] = clean
            else:
                styles.pop(style_key, None)
            self.language["styles"] = styles
            self._live_apply_to_dock()

    def _live_apply_to_dock(self):
        parent = self.parent()
        while parent and not hasattr(parent, "config"):
            parent = parent.parent()
        if parent and hasattr(parent, "config") and hasattr(parent, "tabs"):
            langs = parent.config.setdefault("languages", {})
            langs[self.language_key] = copy.deepcopy(self._collect_values())
            for i in range(parent.tabs.count()):
                try:
                    parent.tabs.widget(i).apply_config(parent.config)
                except Exception:
                    pass

    def _apply_live(self):
        """Apply button — push all current settings to the editor without closing."""
        self._live_apply_to_dock()

    def eventFilter(self, obj, event):
        """Hidden features:
        - Shift+double-click on 'Base language:' label → opens the .json file
        - Shift+double-click on a radio button → apply that mode to ALL tabs
        - Shift+double-click on Clear Current Tab → clear ALL tabs
        """
        from qgis.PyQt.QtCore import QEvent
        from qgis.PyQt.QtGui import QGuiApplication
        if obj is self._lbl_base and event.type() == QEvent.MouseButtonDblClick:
            if QGuiApplication.keyboardModifiers() & Qt.ShiftModifier:
                self._open_language_json()
                return True
        # Shift+double-click on override radio → set all tabs to that mode
        if event.type() == QEvent.MouseButtonDblClick and isinstance(obj, QRadioButton):
            if QGuiApplication.keyboardModifiers() & Qt.ShiftModifier:
                mode = obj.property("_override_mode")
                if mode is not None:
                    self._set_all_tabs_mode(int(mode))
                    return True
        # Shift+double-click on Clear Current Tab → clear all tabs
        if event.type() == QEvent.MouseButtonDblClick and obj.property("_clear_all_tabs"):
            if QGuiApplication.keyboardModifiers() & Qt.ShiftModifier:
                self._clear_all_tabs()
                return True
        return super().eventFilter(obj, event)

    def _set_all_tabs_mode(self, mode):
        """Set all tabs to the given override mode (0/1/2). Secret Shift+double-click feature."""
        for tab_key in self._override_radios:
            self._set_override_mode(tab_key, mode)

    def _ensure_t3_font(self, tab_key):
        """Auto-populate T3 font from current theme for tokens without a font override.
        Makes Mode 2 font independent from theme font changes."""
        style_keys = self._TAB_STYLE_MAP.get(tab_key, [])
        if not style_keys:
            return
        styles = self.language.setdefault("styles", {})
        # Get current theme font as the source
        config = getattr(self, "_config_ref", None) or {}
        theme_family = config.get("font_family", "Consolas")
        theme_size = config.get("font_size", 10)
        for sk in style_keys:
            if sk not in styles:
                styles[sk] = {}
            if not styles[sk].get("font_family"):
                styles[sk]["font_family"] = theme_family
            if not styles[sk].get("font_size"):
                styles[sk]["font_size"] = theme_size

    def _clear_all_tabs(self):
        """Clear all tabs — empty all fields, set all to Custom mode."""
        for tab_key in self._override_radios:
            self._set_override_mode(tab_key, 2)
            self._clear_tab_fields(tab_key)

    def _clear_tab_fields(self, tab_key):
        """Empty out all fields on a specific tab."""
        if tab_key == "general":
            self.ed_exts.clear()
            self.chk_case_sensitive.setChecked(False)
        elif tab_key == "comments":
            self.ed_comment_open.clear()
            self.ed_comment_continue.clear()
            self.ed_comment_close.clear()
            self.ed_block_comment_open.clear()
            self.ed_block_comment_close.clear()
            self.rad_comment_any.setChecked(True)
            self.chk_fold_comments.setChecked(False)
        elif tab_key == "keywords":
            for ed in self.keyword_edits: ed.clear()
            for chk in self.prefix_checks: chk.setChecked(False)
        elif tab_key == "numbers":
            self.ed_num_prefix1.clear(); self.ed_num_prefix2.clear()
            self.ed_num_extras1.clear(); self.ed_num_extras2.clear()
            self.ed_num_suffix1.clear(); self.ed_num_suffix2.clear()
            self.ed_num_range.clear()
            self.rad_dec_dot.setChecked(True)
        elif tab_key == "operators":
            for ed in self.ed_ops: ed.clear()
        elif tab_key == "delimiters":
            for grp in self._delim_grp_boxes:
                for ed in grp.findChildren(QLineEdit): ed.clear()
        elif tab_key == "folding":
            for o, m, c in self._fold_edits:
                o.clear(); m.clear(); c.clear()
            self.chk_fold_compact.setChecked(False)
        elif tab_key == "path":
            self.ed_path_pattern.clear()
        elif tab_key == "variables":
            self.var_list.clear()

    def _fill_factory_theme_style(self):
        """Copy the factory theme's colours into the current tab's token style.
        Reads from the theme's .json file only (ignoring QSettings edits)."""
        tab_key = self._current_tab_key()
        if not tab_key:
            return
        style_keys = self._TAB_STYLE_MAP.get(tab_key, [])
        if not style_keys:
            return
        from .qfat04_config import theme_json_path
        import json as _json
        theme_name = getattr(self, "_config_ref", {}).get("theme", "Dark") if hasattr(self, "_config_ref") else "Dark"
        json_path = theme_json_path(theme_name)
        factory_theme = {}
        if json_path:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    factory_theme = _json.load(f)
            except Exception:
                pass
        if not factory_theme:
            return
        token_styles = factory_theme.get("token_styles", {})
        styles = self.language.setdefault("styles", {})
        for sk in style_keys:
            ts = token_styles.get(sk, {})
            if ts:
                styles[sk] = dict(ts)
            elif sk in styles:
                del styles[sk]

    def _open_language_json(self):
        """Open the .json file for the current language in the dock's code editor."""
        from .qfat04_config import language_json_path
        base_key = self.cmb_base.currentText()
        path = language_json_path(base_key)
        if not path:
            QMessageBox.information(self, "JSON Editor",
                "No .json file found for '%s'.\n"
                "Only built-in languages shipped with the plugin have .json files." % base_key)
            return
        # Walk parent chain to find dock
        parent = self.parent()
        while parent and not hasattr(parent, "new_tab"):
            parent = getattr(parent, "parent", lambda: None)()
        if parent and hasattr(parent, "new_tab"):
            parent.new_tab(path)
            QMessageBox.information(self, "JSON Editor",
                "Opened '%s' in the editor.\n"
                "Edit and save to modify Tier 2 defaults.\n"
                "Restart QGIS or reload the plugin for changes to take effect." % os.path.basename(path))
        else:
            QMessageBox.information(self, "JSON Editor",
                "Could not open editor. File path:\n%s" % path)

    # ------------------------------------------------------------------
    # Wire preview-refresh signals (once, on dialog open)
    # ------------------------------------------------------------------

    # Tab key → style keys affected by that tab
    _TAB_STYLE_MAP = {
        "general":    ["text"],
        "keywords":   ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6"],
        "comments":   ["comment"],
        "numbers":    ["number"],
        "operators":  ["operator"],
        "delimiters": ["string"],
        "folding":    ["folding"],
        "path":       ["path"],
        "variables":  ["variable"],
    }

    # Tab index → tab_key (set after tabs are built)
    _TAB_INDEX_MAP = {
        0: "general",     # General
        1: "operators",   # Operators
        2: "numbers",     # Numbers
        3: "path",        # Path
        4: "delimiters",  # Delimiters
        5: "keywords",    # Keyword Groups
        6: "variables",   # Variables
        7: "comments",    # Comments
        8: "folding",     # Folding
    }

    def _current_tab_key(self):
        """Return the tab_key for the currently active tab, or None."""
        idx = self.tabs.currentIndex()
        return self._TAB_INDEX_MAP.get(idx)

    def _on_base_changed(self, base_text):
        """React to base language combo change — disable folding fields for Python."""
        is_python = (base_text == "python")
        self._fold_python_note.setVisible(is_python)
        for grp in self._fold_grps:
            grp.setEnabled(not is_python)
        self.chk_fold_compact.setEnabled(not is_python)

    def _reset_all_to_builtin(self):
        """Switch every tab to Factory Rules + Active Theme Style (Option 2)."""
        if QMessageBox.question(
            self, "Reset All Tabs",
            "Switch all tabs to follow Factory Rules and Active Theme Style?\n"
            "Per-language font style overrides will be reset.\n"
            "Per-language colours are preserved.",
        ) != QMessageBox.Yes:
            return
        for tab_key in self._override_radios:
            self._set_override_mode(tab_key, 1)  # Option 2: Factory + Active Theme
        # Reset font styles but keep colors
        styles = self.language.get("styles", {})
        for sk in list(styles.keys()):
            if isinstance(styles[sk], dict):
                styles[sk].pop("bold", None)
                styles[sk].pop("italic", None)
                styles[sk].pop("underline", None)
                styles[sk].pop("font_family", None)
                styles[sk].pop("font_size", None)
                # Keep fg, bg
                if not styles[sk]:
                    del styles[sk]
        self.language["styles"] = styles

    def _fill_default_rules(self):
        """Populate the current tab's fields with built-in Tier 2 defaults.
        Keeps the tab in Custom mode so the user can edit from there."""
        tab_key = self._current_tab_key()
        if not tab_key:
            QMessageBox.information(self, "Fill Defaults", "This tab has no overridable rules.")
            return
        try:
            # Ensure override mode is on so fields are editable
            self._set_override_mode(tab_key, 2)
            self._fill_factory_values(tab_key)
        except Exception as e:
            QMessageBox.warning(self, "Fill Defaults", "Error: %s" % str(e))

    def _fill_factory_values(self, tab_key):
        """Populate a tab's fields with factory .json defaults.
        Used when switching to Option 0/1 (greyed out) or when user clicks Fill Defaults."""
        from .qfat04_config import language_json_path
        import json as _json
        # Try to load from the language's own .json file first
        json_path = language_json_path(self.language_key)
        default = {}
        if json_path:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    default = _json.load(f)
            except Exception as e:
                self.setWindowTitle("Language Editor – %s  ⚠ JSON error: %s" % (
                    self.language.get("name", self.language_key), e))
        # Fall back to hardcoded defaults
        if not default:
            defaults = _language_defaults()
            base_key = self.cmb_base.currentText()
            default = defaults.get(base_key, defaults.get("text", {}))

        base_key = self.cmb_base.currentText()
        if tab_key == "general":
            self.ed_exts.setText(",".join(e.lstrip(".") for e in default.get("extensions", [])))
            self.chk_case_sensitive.setChecked(bool(default.get("case_sensitive", False)))
        elif tab_key == "comments":
            self.ed_comment_open.setText(", ".join(default.get("comment_prefixes", [])))
            self.ed_comment_continue.setText("")
            self.ed_comment_close.setText("")
            self.ed_block_comment_open.setText("")
            self.ed_block_comment_close.setText("")
            self.rad_comment_any.setChecked(True)
            self.chk_fold_comments.setChecked(True)
        elif tab_key == "keywords":
            groups = default.get("keyword_groups", [""] * 6)
            for i in range(6):
                self.keyword_edits[i].setPlainText(groups[i] if i < len(groups) else "")
                pm = default.get("prefix_modes", [False] * 6)
                self.prefix_checks[i].setChecked(bool(pm[i]) if i < len(pm) else False)
        elif tab_key == "numbers":
            ns = default.get("number_style", {})
            if isinstance(ns, dict) and ns:
                self.ed_num_prefix1.setText(str(ns.get("prefix1", "")))
                self.ed_num_prefix2.setText(str(ns.get("prefix2", "")))
                self.ed_num_extras1.setText(str(ns.get("extras1", "")))
                self.ed_num_extras2.setText(str(ns.get("extras2", "")))
                self.ed_num_suffix1.setText(str(ns.get("suffix1", "")))
                self.ed_num_suffix2.setText(str(ns.get("suffix2", "")))
                self.ed_num_range.setText(str(ns.get("range", "")))
                dec = str(ns.get("decimal", "dot"))
                if dec == "comma": self.rad_dec_comma.setChecked(True)
                elif dec == "both": self.rad_dec_both.setChecked(True)
                else: self.rad_dec_dot.setChecked(True)
            else:
                # Empty number_style = no detection
                self.ed_num_prefix1.clear(); self.ed_num_prefix2.clear()
                self.ed_num_extras1.clear(); self.ed_num_extras2.clear()
                self.ed_num_suffix1.clear(); self.ed_num_suffix2.clear()
                self.ed_num_range.clear()
                self.rad_dec_dot.setChecked(True)
        elif tab_key == "operators":
            ops = default.get("operators1", "")
            self.ed_ops[0].setText(str(ops))
            for oi in range(1, 6):
                key = "operators%d" % (oi + 1)
                self.ed_ops[oi].setText(str(default.get(key, "")))
        elif tab_key == "delimiters":
            dels = default.get("delimiters", [])
            for i, (o, e, c) in enumerate(self.delim_edits):
                d = dels[i] if i < len(dels) and isinstance(dels[i], dict) else {}
                o.setText(str(d.get("open", ""))); e.setText(str(d.get("escape", ""))); c.setText(str(d.get("close", "")))
        elif tab_key == "folding":
            fold = default.get("folding", {})
            for i, prefix in enumerate(self._fold_key_prefixes):
                o, m, c = self._fold_edits[i]
                o.setText(str(fold.get(prefix + "_open", "")))
                m.setText(str(fold.get(prefix + "_middle", "")))
                c.setText(str(fold.get(prefix + "_close", "")))
            self.chk_fold_compact.setChecked(bool(fold.get("compact", False)))
        elif tab_key == "path":
            self.ed_path_pattern.setPlainText(str(default.get("path_pattern", "")))
        elif tab_key == "variables":
            self.var_list.clear()
            for pat in (default.get("variable_patterns") or []):
                if str(pat).strip():
                    self.var_list.addItem(QListWidgetItem(str(pat).strip()))

    def _set_theme_style_current(self):
        """Copy active theme font styles into T3 for the current tab's tokens.
        Colours are NOT touched — only font style (bold/italic/underline/font) is reset to theme."""
        tab_key = self._current_tab_key()
        if not tab_key:
            return
        style_keys = self._TAB_STYLE_MAP.get(tab_key, [])
        if not style_keys:
            return
        # Get active theme font info
        from .qfat04_config import get_theme
        theme = get_theme(self._config_ref.get("theme", "Dark") if hasattr(self, "_config_ref") else "Dark")
        styles = self.language.get("styles", {})
        for sk in style_keys:
            if sk not in styles:
                styles[sk] = {}
            # Reset font style to theme defaults, keep colors
            styles[sk].pop("bold", None)
            styles[sk].pop("italic", None)
            styles[sk].pop("underline", None)
            styles[sk].pop("font_family", None)
            styles[sk].pop("font_size", None)
            if not styles[sk]:
                del styles[sk]
        self.language["styles"] = styles

    def _clear_current_tab(self):
        """Empty out all fields on the current tab. Tab stays in Custom mode."""
        tab_key = self._current_tab_key()
        if not tab_key:
            return
        self._set_override_mode(tab_key, 2)
        self._clear_tab_fields(tab_key)

    def _save_as(self):
        name, ok = QInputDialog.getText(
            self, "Save As Copy", "New language name:",
            text=(self.txt_name.text().strip() or self.language_key) + " Copy",
        )
        if ok and name.strip():
            self.txt_name.setText(name.strip())
            self.language_key = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "custom_language"
            self.language["builtin"] = False

    def _rename(self):
        name, ok = QInputDialog.getText(
            self, "Rename Language", "Language name:",
            text=self.txt_name.text().strip() or self.language_key,
        )
        if ok and name.strip():
            self.txt_name.setText(name.strip())
            self.language_key = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or self.language_key

    def _remove_language(self):
        if self.allow_delete and not self.language.get("builtin", False):
            if QMessageBox.question(
                self, "Remove Language",
                "Remove language '%s'?" % self.language.get("name", self.language_key),
            ) == QMessageBox.Yes:
                self.delete_requested = True
                self.accept()
        else:
            QMessageBox.information(
                self, "Remove Language",
                "Built-in languages cannot be removed — use Reset All Tabs.\n"
                "To delete a custom language use Language Manager.",
            )

    def _import_language(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import language", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("JSON must contain a language object")
            merged = copy.deepcopy(self.language)
            merged.update(data)
            self.language = merged
            self._populate_from_language(self.language)
            QMessageBox.information(self, "Import", "Language imported.")
        except Exception as e:
            QMessageBox.warning(self, "Import failed", str(e))

    def _export_language(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export language",
            (self.language_key or "language") + ".json", "JSON (*.json)",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.values(), f, indent=2, sort_keys=True)


# ===========================================================================
# LanguageManagerDialog
# ===========================================================================
class LanguageManagerDialog(QDialog):
    """
    Control centre for creating, editing, duplicating, and deleting languages.
    """

    def __init__(self, languages, parent=None, dock=None):
        super().__init__(parent)
        self.setWindowTitle("Language Manager")
        self.resize(780, 520)
        self.languages = copy.deepcopy(languages)
        self._dock = dock

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Select a language and click Edit to open the Language Editor.\n"
            "Built-in languages can be edited and reset but not deleted."
        ))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Language", "Base", "Extensions", "Case Sensitive", "Last Updated"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSortingEnabled(True)
        self.tree.header().setSectionsClickable(True)
        self.tree.setDragDropMode(QTreeWidget.InternalMove)
        self.tree.setDefaultDropAction(Qt.MoveAction)
        self.tree.itemDoubleClicked.connect(self._edit_language)
        root.addWidget(self.tree, 1)

        btn_row = QHBoxLayout()
        self.btn_new       = QPushButton("New Language...")
        self.btn_edit      = QPushButton("Edit Selected...")
        self.btn_dup       = QPushButton("Duplicate...")
        self.btn_del       = QPushButton("Delete")
        self.btn_reset_def = QPushButton("Factory Reset")
        self.btn_move_up   = QPushButton("Move Up")
        self.btn_move_down = QPushButton("Move Down")
        self.btn_move_up.setToolTip("Move the selected language up in the list.\nThis order is used in the Language menu.")
        self.btn_move_down.setToolTip("Move the selected language down in the list.\nThis order is used in the Language menu.")
        self.btn_move_up.clicked.connect(self._move_up)
        self.btn_move_down.clicked.connect(self._move_down)
        self.btn_reset_def.setToolTip(
            "Set all tabs to Factory Rules && Factory Theme (Mode 0).\n"
            "Rules use .json factory defaults.\n"
            "Styles use factory theme .json colours.\n"
            "T3 colour overrides are preserved but ignored.")
        for b in (self.btn_new, self.btn_edit, self.btn_dup,
                  self.btn_del, self.btn_reset_def, self.btn_move_up, self.btn_move_down):
            btn_row.addWidget(b)
        btn_row.addStretch()
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.btn_new.clicked.connect(self._new_language)
        self.btn_edit.clicked.connect(self._edit_language)
        self.btn_dup.clicked.connect(self._duplicate_language)
        self.btn_del.clicked.connect(self._delete_language)
        self.btn_reset_def.clicked.connect(self._reset_language)

        self._reload()

    def _selected_key(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def _move_up(self):
        idx = self.tree.indexOfTopLevelItem(self.tree.currentItem())
        if idx <= 0:
            return
        item = self.tree.takeTopLevelItem(idx)
        self.tree.insertTopLevelItem(idx - 1, item)
        self.tree.setCurrentItem(item)

    def _move_down(self):
        idx = self.tree.indexOfTopLevelItem(self.tree.currentItem())
        if idx < 0 or idx >= self.tree.topLevelItemCount() - 1:
            return
        item = self.tree.takeTopLevelItem(idx)
        self.tree.insertTopLevelItem(idx + 1, item)
        self.tree.setCurrentItem(item)

    def get_language_order(self):
        """Return the current language key order from the tree."""
        return [self.tree.topLevelItem(i).data(0, Qt.UserRole)
                for i in range(self.tree.topLevelItemCount())]

    def select_key(self, key):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == key:
                self.tree.setCurrentItem(item)
                break

    def _reload(self, select_key=None):
        self.tree.clear()
        # Load saved order from QSettings
        saved_order = QSettings().value("QFAT/QFAT04/language_order", "", type=str)
        saved_order = [x for x in saved_order.split("|") if x] if saved_order else []

        # All language keys
        all_keys = list(self.languages.keys())

        # Order: saved order first (preserving user arrangement), then any new languages sorted
        ordered_keys = []
        for k in saved_order:
            if k in all_keys:
                ordered_keys.append(k)
        for k in all_keys:
            if k not in ordered_keys:
                ordered_keys.append(k)

        for key in ordered_keys:
            prof = self.languages[key]
            # Determine last updated date
            last_updated = ""
            if prof.get("_last_modified"):
                last_updated = str(prof["_last_modified"])
            else:
                # Try .json file modification date for built-ins
                from .qfat04_config import language_json_path
                json_path = language_json_path(key)
                if json_path:
                    try:
                        import datetime
                        mtime = os.path.getmtime(json_path)
                        last_updated = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        last_updated = "(built-in)"
            item = QTreeWidgetItem([
                prof.get("name", key),
                prof.get("base", "text"),
                ",".join(e.lstrip(".") for e in prof.get("extensions", [])),
                "Yes" if prof.get("case_sensitive") else "No",
                last_updated,
            ])
            item.setData(0, Qt.UserRole, key)
            if prof.get("builtin"):
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            self.tree.addTopLevelItem(item)
        for i in range(5):
            self.tree.resizeColumnToContents(i)
        if select_key:
            self.select_key(select_key)
        elif self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _new_language(self):
        name, ok = QInputDialog.getText(self, "New Language", "Language name:")
        if not ok or not name.strip():
            return
        key  = make_language_key(name.strip(), self.languages)
        prof = {
            "name": name.strip(), "base": "text",
            "extensions": [], "comment_prefixes": [],
            "keywords": [], "case_sensitive": False, "builtin": False,
        }
        dlg = LanguageEditorDialog(key, prof, self, dock=self._dock)
        if dlg.exec_() and not dlg.delete_requested:
            self.languages[key] = dlg.values()
            self.languages[key]["builtin"] = False
            self._reload(select_key=key)

    def _edit_language(self, *_):
        key = self._selected_key()
        if not key:
            return
        prof = self.languages[key]
        dlg  = LanguageEditorDialog(
            key, prof, self,
            allow_delete=not prof.get("builtin", False),
            dock=self._dock,
        )
        if dlg.exec_():
            if dlg.delete_requested and not prof.get("builtin", False):
                self.languages.pop(key, None)
                self._reload()
            else:
                import datetime
                new_key = dlg.language_key
                updated = dlg.values()
                updated["builtin"] = bool(prof.get("builtin", False) and new_key == key)
                updated["_last_modified"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                if new_key != key and not prof.get("builtin", False):
                    self.languages.pop(key, None)
                self.languages[new_key] = updated
                self._reload(select_key=new_key)

    def _duplicate_language(self):
        key = self._selected_key()
        if not key:
            return
        src  = copy.deepcopy(self.languages[key])
        name, ok = QInputDialog.getText(
            self, "Duplicate Language", "New language name:",
            text=src.get("name", key) + " Copy",
        )
        if not ok or not name.strip():
            return
        new_key         = make_language_key(name.strip(), self.languages)
        src["name"]     = name.strip()
        src["builtin"]  = False
        self.languages[new_key] = src
        self._reload(select_key=new_key)

    def _delete_language(self):
        key = self._selected_key()
        if not key:
            return
        if self.languages[key].get("builtin", False):
            QMessageBox.information(
                self, "Built-in Language",
                "Built-in languages cannot be deleted.\nUse 'Reset All Tabs' instead.",
            )
            return
        if QMessageBox.question(
            self, "Delete Language",
            "Delete language '%s'?" % self.languages[key].get("name", key),
        ) == QMessageBox.Yes:
            self.languages.pop(key, None)
            self._reload()

    def _reset_language(self):
        key = self._selected_key()
        if not key:
            return
        lang = self.languages.get(key, {})
        if QMessageBox.question(
            self, "Factory Reset",
            "Set all tabs for '%s' to Factory Rules && Factory Theme (Mode 0)?\n\n"
            "Rules will use .json factory defaults.\n"
            "Styles will use factory theme colours.\n"
            "T3 colour overrides are preserved but ignored." % lang.get("name", key),
        ) != QMessageBox.Yes:
            return
        # Set all tabs to Mode 0
        lang["_tab_overrides"] = {
            tab_key: 0
            for tab_key in ("general", "keywords", "comments", "numbers",
                            "operators", "delimiters", "folding", "path", "variables")
        }
        self.languages[key] = lang
        self._reload(select_key=key)

    def values(self):
        return self.languages



# ===========================================================================
# SettingsDialog
# ===========================================================================
# ===========================================================================
# Theme Editor Dialog
# ===========================================================================
class ThemeEditorDialog(QDialog):
    """Full theme editor with chrome colours, token colours + Styler buttons, and font settings."""

    _CHROME_KEYS = [
        ("paper",     "Background (paper)"),
        ("caret",     "Caret"),
        ("selection", "Selection"),
        ("margin_bg", "Margin background"),
        ("margin_fg", "Margin text"),
        ("brace_bg",  "Brace match background"),
        ("brace_fg",  "Brace match text"),
    ]

    _TOKEN_KEYS = [
        ("text",     "Normal text"),
        ("comment",  "Comment"),
        ("command",  "Command"),
        ("keyword1", "Keyword Group 1"),
        ("keyword2", "Keyword Group 2"),
        ("keyword3", "Keyword Group 3"),
        ("keyword4", "Keyword Group 4"),
        ("keyword5", "Keyword Group 5"),
        ("keyword6", "Keyword Group 6"),
        ("number",   "Number"),
        ("string",   "String"),
        ("operator", "Operator"),
        ("path",     "Path"),
        ("variable", "Variable"),
    ]

    def __init__(self, theme_name, theme_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Theme Editor — %s" % theme_name)
        self.resize(720, 640)
        self._theme_name = theme_name
        self._theme = copy.deepcopy(theme_dict)
        self._theme.setdefault("token_styles", {})

        root = QVBoxLayout(self)

        # ── Chrome colours (#2) ──
        chrome_grp = QGroupBox("Editor chrome colours")
        chrome_layout = QVBoxLayout(chrome_grp)
        chrome_grid = QGridLayout()
        chrome_grid.setHorizontalSpacing(4)
        self._chrome_btns = {}
        self._chrome_vals = {}
        for idx, (key, label) in enumerate(self._CHROME_KEYS):
            row = idx // 2; pair = idx % 2
            col_btn = pair * 3; col_lbl = pair * 3 + 1
            val = self._theme.get(key, "#808080")
            self._chrome_vals[key] = val
            btn = QPushButton(); btn.setFixedSize(32, 20)
            btn.setStyleSheet("background:%s; border:1px solid #666;" % val)
            btn.clicked.connect(lambda _=False, k=key: self._pick_chrome(k))
            self._chrome_btns[key] = btn
            chrome_grid.addWidget(btn, row, col_btn)
            chrome_grid.addWidget(QLabel(label), row, col_lbl)
        chrome_grid.setColumnMinimumWidth(2, 16)
        chrome_layout.addLayout(chrome_grid)
        # Factory Reset button for chrome
        chrome_btn_row = QHBoxLayout()
        chrome_btn_row.addStretch(1)
        self.btn_factory_reset_chrome = QPushButton("Factory Reset Chrome")
        self.btn_factory_reset_chrome.setToolTip(
            "Reset all editor chrome colours back to the theme's .json factory defaults.\n"
            "Token styles are not affected.")
        self.btn_factory_reset_chrome.clicked.connect(self._factory_reset_chrome)
        chrome_btn_row.addWidget(self.btn_factory_reset_chrome)
        chrome_layout.addLayout(chrome_btn_row)
        root.addWidget(chrome_grp)

        # ── Quick Set Font (#1, moved here) ──
        font_grp = QGroupBox("Quick Set Font")
        font_lay = QHBoxLayout(font_grp)
        font_lay.addWidget(QLabel("Font:"))
        self.cmb_font = QFontComboBox()
        self.cmb_font.setCurrentFont(QFont(self._theme.get("font_family", "Consolas")))
        font_lay.addWidget(self.cmb_font, 1)
        font_lay.addWidget(QLabel("Size:"))
        self.spn_size = QSpinBox(); self.spn_size.setRange(6, 48)
        self.spn_size.setValue(self._theme.get("font_size", 10))
        font_lay.addWidget(self.spn_size)
        self.btn_apply_noncustom = QPushButton("Apply to Non-Customised Tokens")
        self.btn_apply_noncustom.setToolTip(
            "Set this font on tokens that don't have a Styler font override.\n"
            "Tokens with custom font from Styler are left unchanged.")
        self.btn_apply_noncustom.clicked.connect(self._apply_font_noncustomised)
        font_lay.addWidget(self.btn_apply_noncustom)
        self.btn_apply_all = QPushButton("Apply to All Tokens")
        self.btn_apply_all.setToolTip(
            "Set this font on every token, overwriting any Styler font overrides.\n"
            "Colours, bold, italic, and underline from Styler are kept.")
        self.btn_apply_all.clicked.connect(self._apply_font_all)
        font_lay.addWidget(self.btn_apply_all)
        root.addWidget(font_grp)

        # ── Token colours + Styler (#3, grouped logically) ──
        self._token_btns = {}
        self._token_vals = {}
        self._token_styler_btns = {}

        def _add_token_row(grid, row, key, label):
            val = self._theme.get(key, "#808080")
            self._token_vals[key] = val
            btn = QPushButton(); btn.setFixedSize(28, 18)
            btn.setStyleSheet("background:%s; border:1px solid #666;" % val)
            btn.setToolTip("Quick colour change for %s" % label)
            btn.clicked.connect(lambda _=False, k=key: self._pick_token(k))
            self._token_btns[key] = btn
            sbtn = QPushButton("Styler...")
            sbtn.setFixedWidth(48)
            sbtn.clicked.connect(lambda _=False, k=key, l=label: self._open_token_styler(k, l))
            self._token_styler_btns[key] = sbtn
            self._update_styler_btn(key)
            grid.addWidget(btn,        row, 0)
            grid.addWidget(QLabel(label), row, 1)
            grid.addWidget(sbtn,       row, 2)

        # Text & Comments
        grp1 = QGroupBox("Text && Comments")
        g1 = QGridLayout(grp1); g1.setSpacing(2); g1.setContentsMargins(4, 2, 4, 2)
        _add_token_row(g1, 0, "text",    "Normal text")
        _add_token_row(g1, 1, "comment", "Comment")

        # Keywords
        grp2 = QGroupBox("Keywords")
        g2 = QGridLayout(grp2); g2.setSpacing(2); g2.setContentsMargins(4, 2, 4, 2)
        for i in range(6):
            _add_token_row(g2, i, "keyword%d" % (i + 1), "Group %d" % (i + 1))

        # Values
        grp3 = QGroupBox("Values")
        g3 = QGridLayout(grp3); g3.setSpacing(2); g3.setContentsMargins(4, 2, 4, 2)
        _add_token_row(g3, 0, "number",   "Number")
        _add_token_row(g3, 1, "string",   "String")
        _add_token_row(g3, 2, "operator", "Operator")

        # References
        grp4 = QGroupBox("References")
        g4 = QGridLayout(grp4); g4.setSpacing(2); g4.setContentsMargins(4, 2, 4, 2)
        _add_token_row(g4, 0, "path",     "Path")
        _add_token_row(g4, 1, "variable", "Variable")
        _add_token_row(g4, 2, "command",  "Command")

        # Layout: two columns of group boxes
        token_outer = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addWidget(grp1)
        left_col.addWidget(grp3)
        left_col.addWidget(grp4)
        left_col.addStretch(1)
        right_col = QVBoxLayout()
        right_col.addWidget(grp2)
        right_col.addStretch(1)
        token_outer.addLayout(left_col)
        token_outer.addLayout(right_col)
        root.addLayout(token_outer)

        # ── Save / Cancel ──
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _update_styler_btn(self, key):
        """Update Styler button appearance — bold if token has style overrides."""
        sbtn = self._token_styler_btns.get(key)
        if not sbtn:
            return
        ts = self._theme.get("token_styles", {}).get(key, {})
        has_override = bool(ts)
        font = sbtn.font()
        font.setBold(has_override)
        sbtn.setFont(font)
        if has_override:
            parts = []
            if ts.get("bg"): parts.append("bg: %s" % ts["bg"])
            if ts.get("bold"): parts.append("bold")
            if ts.get("italic"): parts.append("italic")
            if ts.get("underline"): parts.append("underline")
            if ts.get("font_family"): parts.append("font: %s" % ts["font_family"])
            if ts.get("font_size"): parts.append("size: %s" % ts["font_size"])
            sbtn.setToolTip("Custom style: %s\nClick to edit." % ", ".join(parts))
        else:
            sbtn.setToolTip("Using Theme Font and base colour.\nClick to customise.")

    def _apply_font_noncustomised(self):
        """Apply font to tokens that don't have a Styler font override."""
        font_family = self.cmb_font.currentFont().family()
        font_size = self.spn_size.value()
        ts = self._theme.get("token_styles", {})
        for key, _ in self._TOKEN_KEYS:
            token_style = ts.get(key, {})
            # Only set if token has no custom font from Styler
            if not token_style.get("font_family") and not token_style.get("font_size"):
                if key not in ts:
                    ts[key] = {}
                ts[key]["font_family"] = font_family
                ts[key]["font_size"] = font_size
            self._update_styler_btn(key)
        self._theme["token_styles"] = ts

    def _apply_font_all(self):
        """Apply font to all tokens, overwriting Styler font overrides."""
        font_family = self.cmb_font.currentFont().family()
        font_size = self.spn_size.value()
        ts = self._theme.get("token_styles", {})
        for key, _ in self._TOKEN_KEYS:
            if key not in ts:
                ts[key] = {}
            ts[key]["font_family"] = font_family
            ts[key]["font_size"] = font_size
            self._update_styler_btn(key)
        self._theme["token_styles"] = ts

    def _factory_reset_chrome(self):
        """Reset chrome colours to factory .json defaults."""
        from .qfat04_config import get_factory_theme
        factory = get_factory_theme(self._theme_name)
        for key, _ in self._CHROME_KEYS:
            val = factory.get(key, "#808080")
            self._chrome_vals[key] = val
            self._chrome_btns[key].setStyleSheet(
                "background:%s; border:1px solid #666;" % val)

    def _pick_chrome(self, key):
        current = QColor(self._chrome_vals.get(key, "#808080"))
        color = QColorDialog.getColor(current, self, "Pick colour — %s" % key)
        if color.isValid():
            self._chrome_vals[key] = color.name()
            self._chrome_btns[key].setStyleSheet(
                "background:%s; border:1px solid #666;" % color.name())

    def _pick_token(self, key):
        current = QColor(self._token_vals.get(key, "#808080"))
        color = QColorDialog.getColor(current, self, "Pick colour — %s" % key)
        if color.isValid():
            self._token_vals[key] = color.name()
            self._token_btns[key].setStyleSheet(
                "background:%s; border:1px solid #666;" % color.name())

    def _open_token_styler(self, key, label):
        ts = self._theme.get("token_styles", {})
        style_data = copy.deepcopy(ts.get(key, {}))
        if not style_data.get("fg"):
            style_data["fg"] = self._token_vals.get(key, "#808080")
        # For the fill button: use factory theme values
        from .qfat04_config import get_factory_theme
        factory = get_factory_theme(self._theme_name)
        factory_ts = factory.get("token_styles", {}).get(key, {})
        factory_color = {
            "fg": factory.get(key, "#808080"),
            "bg": factory_ts.get("bg", ""),
            "font_family": factory.get("font_family", "Consolas"),
            "font_size": factory.get("font_size", 10),
            "bold": factory_ts.get("bold", False),
            "italic": factory_ts.get("italic", False),
            "underline": factory_ts.get("underline", False),
        }
        dlg = LocalStylerDialog(label, style_data, self, theme_color=factory_color,
                                reset_label="Fill Factory Color and Style")
        if dlg.exec_() == QDialog.Accepted:
            result = dlg.values()
            if result.get("fg") and result["fg"].startswith("#"):
                self._token_vals[key] = result["fg"]
                self._token_btns[key].setStyleSheet(
                    "background:%s; border:1px solid #666;" % result["fg"])
            clean = {}
            for k, v in result.items():
                if k == "fg":
                    continue
                if k == "bg" and v and v.startswith("#"):
                    clean[k] = v
                elif k in ("bold", "italic", "underline") and v:
                    clean[k] = v
                elif k == "font_family" and v and v.strip():
                    clean[k] = v.strip()
                elif k == "font_size" and v:
                    clean[k] = v
            if clean:
                self._theme.setdefault("token_styles", {})[key] = clean
            else:
                self._theme.get("token_styles", {}).pop(key, None)
            self._update_styler_btn(key)

    def _save_and_accept(self):
        self.accept()

    def values(self):
        result = copy.deepcopy(self._theme)
        result.update(self._chrome_vals)
        result.update(self._token_vals)
        # Save font as top-level theme property (used by config as fallback)
        result["font_family"] = self.cmb_font.currentFont().family()
        result["font_size"] = self.spn_size.value()
        return result


# ===========================================================================
# SettingsDialog
# ===========================================================================
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QFAT04 CodePad-- Preferences")
        self.resize(660, 540)
        self._config = config
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ── Editor tab ─────────────────────────────────────────────────
        editor_w = QWidget(); form = QFormLayout(editor_w)
        self.zoom           = QSpinBox(); self.zoom.setRange(-8, 20);     self.zoom.setValue(config["zoom"])
        self.folding        = QCheckBox(); self.folding.setChecked(config["folding"])
        self.brace_matching = QCheckBox(); self.brace_matching.setChecked(config["brace_matching"])
        self.drop_exts      = QLineEdit(); self.drop_exts.setText(config.get("drop_exts", "tcf, tgc, tmf, tef, trd, toc, ecf, bc_dbase, cmd, bat, ps1"))
        self.tab_min_width  = QSpinBox(); self.tab_min_width.setRange(30, 300); self.tab_min_width.setValue(config.get("tab_min_width", 60)); self.tab_min_width.setSuffix(" px")
        self.tab_max_width  = QSpinBox(); self.tab_max_width.setRange(60, 600); self.tab_max_width.setValue(config.get("tab_max_width", 180)); self.tab_max_width.setSuffix(" px")
        self.tab_font_size  = QSpinBox(); self.tab_font_size.setRange(6, 20); self.tab_font_size.setValue(config.get("tab_font_size", 8)); self.tab_font_size.setSuffix(" pt")
        self.show_tab_close = QCheckBox(); self.show_tab_close.setChecked(config.get("show_tab_close", True))
        self.tab_inflate_active = QCheckBox(); self.tab_inflate_active.setChecked(config.get("tab_inflate_active", False))
        self.tab_inflate_active.setToolTip(
            "When on, the active tab grows to show its full filename.\n"
            "May cause cursor offset glitches when dragging tabs to reorder.\n"
            "Default: off (all tabs use the max width).")
        # ── Startup delays (stored in QSettings, not config) ──
        _s = QSettings()
        self.delay_dock    = QSpinBox(); self.delay_dock.setRange(0, 60000);    self.delay_dock.setSuffix(" ms"); self.delay_dock.setSingleStep(100)
        self.delay_dock.setValue(int(_s.value("QFAT/QFAT04/delay_dock_create", 0)))
        self.delay_addons  = QSpinBox(); self.delay_addons.setRange(0, 60000);  self.delay_addons.setSuffix(" ms"); self.delay_addons.setSingleStep(100)
        self.delay_addons.setValue(int(_s.value("QFAT/QFAT04/delay_addon_load", 5000)))
        self.delay_drops   = QSpinBox(); self.delay_drops.setRange(0, 60000);   self.delay_drops.setSuffix(" ms"); self.delay_drops.setSingleStep(100)
        self.delay_drops.setValue(int(_s.value("QFAT/QFAT04/delay_drop_targets", 1000)))
        self.cmb_backend = QComboBox()
        self.cmb_backend.addItems(["Auto (QScintilla if available)", "QScintilla", "PlainTextEdit"])
        backend = config.get("editor_backend", "auto")
        if backend == "scintilla": self.cmb_backend.setCurrentIndex(1)
        elif backend == "plain": self.cmb_backend.setCurrentIndex(2)
        else: self.cmb_backend.setCurrentIndex(0)
        form.addRow("Zoom",                                   self.zoom)
        form.addRow("Code folding",                           self.folding)
        form.addRow("Brace matching",                         self.brace_matching)
        form.addRow("Editor backend",                         self.cmb_backend)
        form.addRow("Drag & Drop file types (comma sep.)",    self.drop_exts)
        form.addRow("Tab bar min width",                      self.tab_min_width)
        form.addRow("Tab bar max width",                      self.tab_max_width)
        form.addRow("Tab bar font size",                      self.tab_font_size)
        form.addRow("Show tab close button",                  self.show_tab_close)
        form.addRow("Inflate active tab to full name",        self.tab_inflate_active)
        form.addRow("Dock creation delay (restart)",          self.delay_dock)
        form.addRow("Addon loader delay (restart)",           self.delay_addons)
        form.addRow("Drop targets delay (restart)",           self.delay_drops)
        self.tabs.addTab(editor_w, "Editor")

        # ── Toolbar tab ────────────────────────────────────────────────
        tb_w   = QWidget(); tb_lay = QVBoxLayout(tb_w)
        tb_lay.addWidget(QLabel("Check to show, drag to reorder."))
        self.tb_list = QListWidget(); self.tb_list.setDragDropMode(QListWidget.InternalMove)
        all_tools = {
            "new": "New Tab", "open": "Open File", "save": "Save",
            "save_as": "Save As", "save_all": "Save All",
            "reload": "Reload from Disk", "close": "Close Tab", "print": "Print",
            "undo": "Undo", "redo": "Redo",
            "cut": "Cut", "copy": "Copy", "paste": "Paste",
            "find": "Find", "replace": "Replace",
            "run": "Run Internal", "run_external": "Run External", "stop": "Stop Script",
            "prefs": "Preferences", "shortcuts": "Editor Shortcuts",
            "zoom_in": "Zoom In", "zoom_out": "Zoom Out",
            "float": "Floating Mode",
        }
        active = config.get("toolbar_items", [])
        for t in active:
            if t in all_tools:
                item = QListWidgetItem(all_tools[t]); item.setData(Qt.UserRole, t)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable); item.setCheckState(Qt.Checked)
                self.tb_list.addItem(item)
        for k, v in all_tools.items():
            if k not in active:
                item = QListWidgetItem(v); item.setData(Qt.UserRole, k)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable); item.setCheckState(Qt.Unchecked)
                self.tb_list.addItem(item)
        tb_lay.addWidget(self.tb_list)
        self.tabs.addTab(tb_w, "Toolbar")

        # ── Interpreters tab ───────────────────────────────────────
        interp_w = QWidget(); interp_lay = QVBoxLayout(interp_w)
        interp_lay.addWidget(QLabel(
            "Configure interpreter paths for running scripts.\n"
            "Leave empty to auto-detect from system PATH.\n"
            "Python (F5 Internal) always uses QGIS's built-in Python."))
        interp_form = QFormLayout()
        self.ed_python_path = QLineEdit()
        self.ed_python_path.setPlaceholderText("Auto-detect (python3 or python)")
        self.ed_python_path.setText(QSettings().value("QFAT/QFAT04/interpreter_python", "", type=str))
        self.ed_python_path.setToolTip(
            "Path to Python interpreter for Run External (F6).\n"
            "Leave empty to auto-detect from PATH.\n"
            "Example: C:\\Python312\\python.exe")
        py_row = QHBoxLayout()
        py_row.addWidget(self.ed_python_path, 1)
        btn_py_browse = QPushButton("Browse...")
        btn_py_browse.clicked.connect(lambda: self._browse_interpreter(self.ed_python_path, "Python Executable (python*.exe python3)"))
        py_row.addWidget(btn_py_browse)
        btn_py_test = QPushButton("Test")
        btn_py_test.clicked.connect(lambda: self._test_interpreter(self.ed_python_path.text().strip() or "python", "--version"))
        py_row.addWidget(btn_py_test)
        interp_form.addRow("Python (F6 External):", py_row)

        # PowerShell interpreter (Windows default path often not on PATH)
        self.ed_ps_path = QLineEdit()
        default_ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        self.ed_ps_path.setPlaceholderText(default_ps)
        self.ed_ps_path.setText(QSettings().value("QFAT/QFAT04/interpreter_powershell", "", type=str))
        self.ed_ps_path.setToolTip(
            "Path to powershell.exe (or pwsh.exe).\n"
            "Leave empty to auto-detect. Used for F5 (internal) and F6 (external).\n"
            "Default: " + default_ps)
        ps_row = QHBoxLayout()
        ps_row.addWidget(self.ed_ps_path, 1)
        btn_ps_browse = QPushButton("Browse...")
        btn_ps_browse.clicked.connect(lambda: self._browse_interpreter(self.ed_ps_path, "PowerShell (powershell.exe pwsh.exe)"))
        ps_row.addWidget(btn_ps_browse)
        btn_ps_test = QPushButton("Test")
        btn_ps_test.clicked.connect(lambda: self._test_interpreter(self.ed_ps_path.text().strip() or default_ps, "-NoProfile", "-Command", "$PSVersionTable.PSVersion"))
        ps_row.addWidget(btn_ps_test)
        interp_form.addRow("PowerShell:", ps_row)

        self.ed_r_path = QLineEdit()
        self.ed_r_path.setPlaceholderText("Auto-detect (Rscript)")
        self.ed_r_path.setText(QSettings().value("QFAT/QFAT04/interpreter_r", "", type=str))
        self.ed_r_path.setToolTip(
            "Path to Rscript interpreter.\n"
            "Leave empty to auto-detect from PATH.\n"
            "Example: C:\\Program Files\\R\\R-4.3.2\\bin\\Rscript.exe")
        r_row = QHBoxLayout()
        r_row.addWidget(self.ed_r_path, 1)
        btn_r_browse = QPushButton("Browse...")
        btn_r_browse.clicked.connect(lambda: self._browse_interpreter(self.ed_r_path, "Rscript Executable (Rscript*.exe Rscript)"))
        r_row.addWidget(btn_r_browse)
        btn_r_test = QPushButton("Test")
        btn_r_test.clicked.connect(lambda: self._test_interpreter(self.ed_r_path.text().strip() or "Rscript", "--version"))
        r_row.addWidget(btn_r_test)
        interp_form.addRow("R (Rscript):", r_row)

        self.ed_run_exts = QLineEdit()
        self.ed_run_exts.setPlaceholderText("cmd,bat,ps1,py,pyw,r")
        self.ed_run_exts.setText(QSettings().value("QFAT/QFAT04/run_extensions", "", type=str))
        self.ed_run_exts.setToolTip(
            "Comma-separated list of extensions that can be run (no dots).\n"
            "Leave empty to use defaults: cmd,bat,ps1,py,pyw,r")
        interp_form.addRow("Runnable extensions:", self.ed_run_exts)

        interp_lay.addLayout(interp_form)
        interp_lay.addStretch(1)
        self.tabs.addTab(interp_w, "Interpreters")

        # ── Theme Manager tab ─────────────────────────────────────
        theme_w   = QWidget(); theme_lay = QVBoxLayout(theme_w)
        theme_lay.addWidget(QLabel(
            "Manage colour themes for the editor.\n"
            "Per-language overrides are set in Language Editor → Styler buttons."
        ))
        sel_row = QHBoxLayout()
        self._lbl_active_theme = QLabel("Active theme:")
        sel_row.addWidget(self._lbl_active_theme)
        self._lbl_active_theme.installEventFilter(self)
        from .qfat04_config import list_theme_names as _ltn, get_theme as _gt2, THEMES, _theme_settings_key
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(_ltn())
        # Bold customised or user-created themes
        from qgis.PyQt.QtCore import QSettings as _QS
        import json as _json2
        self._theme_bold_indices = set()
        for i in range(self.cmb_theme.count()):
            name = self.cmb_theme.itemText(i)
            is_custom = name not in THEMES  # user-created theme
            raw = _QS().value(_theme_settings_key(name), "", type=str).strip()
            has_overrides = False
            if raw:
                try:
                    has_overrides = bool(_json2.loads(raw))
                except Exception:
                    has_overrides = True
            if is_custom or has_overrides:
                font = QFont(self.cmb_theme.font())
                font.setBold(True)
                self.cmb_theme.setItemData(i, font, Qt.FontRole)
                self._theme_bold_indices.add(i)
        self.cmb_theme.setCurrentText(config.get("theme", "Dark"))
        self._update_theme_combo_font()
        sel_row.addWidget(self.cmb_theme, 1)
        self.cmb_theme.currentIndexChanged.connect(lambda _: self._update_theme_combo_font())
        self.cmb_theme.currentTextChanged.connect(self._update_theme_preview)
        theme_lay.addLayout(sel_row)

        btn_row_theme = QHBoxLayout()
        self.btn_edit_theme   = QPushButton("Edit...")
        self.btn_edit_theme.setToolTip("Open the Theme Editor to customise colours, fonts, and styles for the selected theme.")
        self.btn_new_theme    = QPushButton("New...")
        self.btn_new_theme.setToolTip("Create a new empty theme based on the currently selected one.")
        self.btn_dup_theme    = QPushButton("Duplicate...")
        self.btn_dup_theme.setToolTip("Create an exact copy of the selected theme with a new name.")
        self.btn_delete_theme = QPushButton("Delete")
        self.btn_delete_theme.setToolTip("Delete the selected custom theme.\nBuilt-in themes cannot be deleted.")
        self.btn_reset_theme  = QPushButton("Factory Reset")
        self.btn_reset_theme.setToolTip("Clear all customisations for this theme.\nReverts to the built-in .json file defaults.\nOnly works on built-in themes.")
        self.btn_edit_theme.clicked.connect(self._edit_theme)
        self.btn_new_theme.clicked.connect(self._new_theme)
        self.btn_dup_theme.clicked.connect(self._duplicate_theme)
        self.btn_delete_theme.clicked.connect(self._delete_theme)
        self.btn_reset_theme.clicked.connect(self._reset_theme_to_builtin)
        for b in (self.btn_edit_theme, self.btn_new_theme, self.btn_dup_theme,
                  self.btn_delete_theme, self.btn_reset_theme):
            btn_row_theme.addWidget(b)
        btn_row_theme.addStretch(1)
        theme_lay.addLayout(btn_row_theme)

        # ── Preview ──
        preview_grp = QGroupBox("Preview (sample — not reflecting any settings)")
        preview_lay = QVBoxLayout(preview_grp)
        self._theme_preview = QTextEdit()
        self._theme_preview.setReadOnly(True)
        self._theme_preview.setMinimumHeight(200)
        self._update_theme_preview()
        preview_lay.addWidget(self._theme_preview)
        theme_lay.addWidget(preview_grp, 1)

        theme_lay.addStretch(1)
        self.tabs.addTab(theme_w, "Theme Manager")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        buttons.accepted.connect(self._save_interpreters_and_accept); buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply_settings)
        layout.addWidget(buttons)

    def _save_interpreters_and_accept(self):
        s = QSettings()
        s.setValue("QFAT/QFAT04/interpreter_python", self.ed_python_path.text().strip())
        s.setValue("QFAT/QFAT04/interpreter_powershell", self.ed_ps_path.text().strip())
        s.setValue("QFAT/QFAT04/interpreter_r", self.ed_r_path.text().strip())
        s.setValue("QFAT/QFAT04/run_extensions", self.ed_run_exts.text().strip())
        s.setValue("QFAT/QFAT04/delay_dock_create",  self.delay_dock.value())
        s.setValue("QFAT/QFAT04/delay_addon_load",   self.delay_addons.value())
        s.setValue("QFAT/QFAT04/delay_drop_targets", self.delay_drops.value())
        self.accept()

    def _update_theme_combo_font(self):
        """Bold the combo display text if current theme is customised."""
        font = QFont(self.cmb_theme.font())
        font.setBold(self.cmb_theme.currentIndex() in self._theme_bold_indices)
        self.cmb_theme.setFont(font)

    def _refresh_theme_bold(self):
        """Recalculate which themes are bold (customised or user-created)."""
        from .qfat04_config import THEMES, _theme_settings_key
        from qgis.PyQt.QtCore import QSettings as _QS
        import json as _json
        self._theme_bold_indices = set()
        for i in range(self.cmb_theme.count()):
            name = self.cmb_theme.itemText(i)
            is_custom = name not in THEMES
            raw = _QS().value(_theme_settings_key(name), "", type=str).strip()
            has_overrides = False
            if raw:
                try:
                    has_overrides = bool(_json.loads(raw))  # {} is falsy
                except Exception:
                    has_overrides = True
            if is_custom or has_overrides:
                font = QFont(self.cmb_theme.font())
                font.setBold(True)
                self.cmb_theme.setItemData(i, font, Qt.FontRole)
                self._theme_bold_indices.add(i)
            else:
                font = QFont(self.cmb_theme.font())
                font.setBold(False)
                self.cmb_theme.setItemData(i, font, Qt.FontRole)
                self._theme_bold_indices.discard(i)
        self._update_theme_combo_font()

    def _update_theme_preview(self):
        """Show a visual summary of the current theme."""
        from .qfat04_config import get_theme as _gt
        name = self.cmb_theme.currentText() if hasattr(self, 'cmb_theme') else "Dark"
        t = _gt(name)
        paper = t.get("paper", "#1e1e1e")
        text_c = t.get("text", "#d4d4d4")
        font = t.get("font_family", "Consolas")
        size = t.get("font_size", 10)
        lines = []
        lines.append("<b>%s</b> — %s %dpt" % (name, font, size))
        lines.append("")
        # Chrome
        for key, label in [("paper", "Paper"), ("text", "Normal text"), ("caret", "Caret"),
                           ("selection", "Selection"), ("margin_bg", "Margin bg"), ("margin_fg", "Margin fg")]:
            c = t.get(key, "#808080")
            lines.append('<span style="background:%s; color:%s; padding:1px 6px;">■</span> %s: %s' % (c, c, label, c))
        lines.append("")
        # Tokens
        for key, label in [("comment", "Comment"), ("command", "Command"),
                           ("keyword1", "Keyword 1"), ("keyword2", "Keyword 2"), ("keyword3", "Keyword 3"),
                           ("keyword4", "Keyword 4"), ("keyword5", "Keyword 5"),
                           ("keyword6", "Keyword 6"),
                           ("number", "Number"), ("string", "String"), ("operator", "Operator"),
                           ("path", "Path"), ("variable", "Variable")]:
            c = t.get(key, "#808080")
            ts = t.get("token_styles", {}).get(key, {})
            extras = []
            if ts.get("bold"): extras.append("bold")
            if ts.get("italic"): extras.append("italic")
            if ts.get("underline"): extras.append("underline")
            extra_str = " (%s)" % ", ".join(extras) if extras else ""
            lines.append('<span style="color:%s;">■ %s</span>: %s%s' % (c, label, c, extra_str))
        self._theme_preview.setHtml("<div style='background:%s; color:%s; padding:8px; font-family:%s; font-size:%dpt;'>%s</div>"
            % (paper, text_c, font, max(size - 2, 7), "<br>".join(lines)))

    def _edit_theme(self):
        from .qfat04_config import get_theme as _gt, save_theme as _st
        name = self.cmb_theme.currentText()
        theme = _gt(name)
        dlg = ThemeEditorDialog(name, theme, self)
        if dlg.exec_() == QDialog.Accepted:
            updated = dlg.values()
            _st(name, updated)
            self._refresh_theme_bold()
            self._update_theme_preview()

    def _new_theme(self):
        from .qfat04_config import list_theme_names, save_theme as _st, get_theme as _gt
        name, ok = QInputDialog.getText(self, "New Theme", "Theme name:")
        if not ok or not name.strip(): return
        if name.strip() in list_theme_names():
            QMessageBox.warning(self, "Exists", "A theme with that name already exists.")
            return
        theme = _gt(self.cmb_theme.currentText())
        _st(name.strip(), theme)
        self.cmb_theme.addItem(name.strip())
        self.cmb_theme.setCurrentText(name.strip())
        self._refresh_theme_bold()
        self._update_theme_preview()

    def _duplicate_theme(self):
        from .qfat04_config import list_theme_names, save_theme as _st, get_theme as _gt
        src_name = self.cmb_theme.currentText()
        name, ok = QInputDialog.getText(self, "Duplicate Theme", "New theme name:",
                                        text=src_name + " Copy")
        if not ok or not name.strip(): return
        if name.strip() in list_theme_names():
            QMessageBox.warning(self, "Exists", "A theme with that name already exists.")
            return
        theme = _gt(src_name)
        _st(name.strip(), theme)
        self.cmb_theme.addItem(name.strip())
        self.cmb_theme.setCurrentText(name.strip())
        self._refresh_theme_bold()
        self._update_theme_preview()

    def _delete_theme(self):
        from .qfat04_config import THEMES, delete_theme as _dt
        name = self.cmb_theme.currentText()
        if name in THEMES:
            QMessageBox.information(self, "Built-in", "Built-in themes cannot be deleted.")
            return
        if QMessageBox.question(self, "Delete", "Delete theme '%s'?" % name) == QMessageBox.Yes:
            _dt(name)
            idx = self.cmb_theme.findText(name)
            if idx >= 0: self.cmb_theme.removeItem(idx)
            self.cmb_theme.setCurrentText("Dark")
            self._refresh_theme_bold()
            self._update_theme_preview()

    def _reset_theme_to_builtin(self):
        """Clear QSettings overrides for current theme, revert to .json defaults."""
        from .qfat04_config import THEMES, _theme_settings_key
        name = self.cmb_theme.currentText()
        if name not in THEMES:
            QMessageBox.information(self, "Reset",
                "Only built-in themes can be reset to defaults.\n"
                "Custom themes have no .json base to revert to.")
            return
        if QMessageBox.question(self, "Factory Reset",
            "Reset '%s' to its built-in defaults?\n"
            "All customisations for this theme will be lost." % name
        ) != QMessageBox.Yes:
            return
        QSettings().remove(_theme_settings_key(name))
        self._refresh_theme_bold()
        self._update_theme_preview()

    def values(self):
        cfg  = self._config
        tb   = [self.tb_list.item(i).data(Qt.UserRole)
                for i in range(self.tb_list.count())
                if self.tb_list.item(i).checkState() == Qt.Checked]
        # Font comes from the saved theme, not the unsaved combo box
        from .qfat04_config import get_theme as _gt
        saved_theme = _gt(self.cmb_theme.currentText())
        return {
            "font_family":           saved_theme.get("font_family", "Consolas"),
            "font_size":             saved_theme.get("font_size", 10),
            "theme":                 self.cmb_theme.currentText(),
            "tab_width":             cfg.get("tab_width", 4),
            "zoom":                  self.zoom.value(),
            "wrap":                  cfg.get("wrap", False),
            "show_line_numbers":     cfg.get("show_line_numbers", True),
            "show_whitespace":       cfg.get("show_whitespace", False),
            "show_eol":              cfg.get("show_eol", False),
            "show_indent_guides":    cfg.get("show_indent_guides", True),
            "folding":               self.folding.isChecked(),
            "brace_matching":        self.brace_matching.isChecked(),
            "toolbar_items":         tb,
            "drop_exts":             self.drop_exts.text().strip(),
            "tab_min_width":         self.tab_min_width.value(),
            "tab_max_width":         self.tab_max_width.value(),
            "tab_font_size":         self.tab_font_size.value(),
            "show_tab_close":        self.show_tab_close.isChecked(),
            "tab_inflate_active":    self.tab_inflate_active.isChecked(),
            "editor_backend":        ["auto", "scintilla", "plain"][self.cmb_backend.currentIndex()],
            "languages":             cfg.get("languages", {}),
        }

    def _apply_settings(self):
        """Apply button — push settings to the editor without closing."""
        from .qfat04_config import save_config
        # Save interpreter settings to QSettings
        s = QSettings()
        s.setValue("QFAT/QFAT04/interpreter_python", self.ed_python_path.text().strip())
        s.setValue("QFAT/QFAT04/interpreter_powershell", self.ed_ps_path.text().strip())
        s.setValue("QFAT/QFAT04/interpreter_r", self.ed_r_path.text().strip())
        s.setValue("QFAT/QFAT04/run_extensions", self.ed_run_exts.text().strip())
        parent = self.parent()
        while parent and not hasattr(parent, "config"):
            parent = getattr(parent, "parent", lambda: None)()
        if parent and hasattr(parent, "config"):
            new_cfg = self.values()
            parent.config.update(new_cfg)
            save_config(parent.config)
            if hasattr(parent, "tabs"):
                parent.tabs.set_tab_limits(new_cfg.get("tab_min_width", 60), new_cfg.get("tab_max_width", 180))
                parent.tabs.set_tab_font_size(new_cfg.get("tab_font_size", 8))
                parent.tabs.set_show_close_button(new_cfg.get("show_tab_close", True))
                parent.tabs.set_inflate_active(new_cfg.get("tab_inflate_active", False))
                for i in range(parent.tabs.count()):
                    try:
                        parent.tabs.widget(i).apply_config(parent.config)
                    except Exception:
                        pass
            if hasattr(parent, "_refresh_toolbar"):
                parent._refresh_toolbar()
            if hasattr(parent, "_refresh_titles"):
                parent._refresh_titles()

    def eventFilter(self, obj, event):
        """Hidden feature: Shift+double-click on 'Active theme:' label opens the theme .json file."""
        from qgis.PyQt.QtCore import QEvent
        from qgis.PyQt.QtGui import QGuiApplication
        if obj is self._lbl_active_theme and event.type() == QEvent.MouseButtonDblClick:
            if QGuiApplication.keyboardModifiers() & Qt.ShiftModifier:
                self._open_theme_json()
                return True
        return super().eventFilter(obj, event)

    def _open_theme_json(self):
        """Open the .json file for the current theme in the dock's code editor."""
        from .qfat04_config import theme_json_path
        name = self.cmb_theme.currentText()
        path = theme_json_path(name)
        if not path:
            QMessageBox.information(self, "JSON Editor",
                "No .json file found for theme '%s'." % name)
            return
        parent = self.parent()
        while parent and not hasattr(parent, "new_tab"):
            parent = getattr(parent, "parent", lambda: None)()
        if parent and hasattr(parent, "new_tab"):
            parent.new_tab(path)
            QMessageBox.information(self, "JSON Editor",
                "Opened '%s' in the editor.\n"
                "Edit and save to modify theme defaults.\n"
                "Restart QGIS or reload the plugin for changes to take effect." % os.path.basename(path))
        else:
            QMessageBox.information(self, "JSON Editor",
                "Could not open editor. File path:\n%s" % path)

    def _browse_interpreter(self, line_edit, filter_text):
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Select Interpreter", "", "All Files (*)")
        if path:
            line_edit.setText(path)

    def _test_interpreter(self, cmd, *args):
        import subprocess
        try:
            result = subprocess.run([cmd, *args], capture_output=True, text=True, timeout=10)
            output = (result.stdout + result.stderr).strip()
            QMessageBox.information(self, "Interpreter Test",
                "Command: %s %s\n\n%s" % (cmd, " ".join(args), output or "(no output)"))
        except FileNotFoundError:
            QMessageBox.warning(self, "Interpreter Test",
                "Not found: %s\n\nMake sure it's installed and on your PATH,\nor set the full path." % cmd)
        except Exception as e:
            QMessageBox.warning(self, "Interpreter Test", "Error: %s" % str(e))


# ===========================================================================
# Shortcut dialogs
# ===========================================================================
class ShortcutCaptureDialog(QDialog):
    def __init__(self, action_label, current_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Shortcut")
        self.resize(420, 120)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Press the new shortcut for: %s" % action_label))
        self.edit = QKeySequenceEdit()
        if current_text:
            self.edit.setKeySequence(QKeySequence(current_text))
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def sequence_text(self):
        return self.edit.keySequence().toString(QKeySequence.NativeText)


class ShortcutsDialog(QDialog):
    ACTION_ROWS = [
        ("toggle_comment", "Edit", "Toggle Comment"),
        ("duplicate_line", "Edit", "Duplicate Line"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QFAT04 Editor Shortcut Manager")
        self.resize(820, 460)
        self._accepted = False
        self.shortcuts = dict(getattr(parent, "editor_shortcuts", load_editor_shortcuts()))
        # Addon shortcuts: list of dicts with key/default_key/name/addon/callback
        self._addon_shortcuts = parent._get_addon_shortcuts() if hasattr(parent, "_get_addon_shortcuts") else []
        # Build editable copy keyed by "addon::name" → current key sequence
        self.addon_overrides = {}
        for asc in self._addon_shortcuts:
            oid = "%s::%s" % (asc.get("addon", ""), asc.get("name", ""))
            self.addon_overrides[oid] = asc.get("key", "")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Custom Editor Shortcuts (Copy/Paste/Undo use OS defaults)."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Category", "Action", "Shortcut", "Default"])
        self.tree.setRootIsDecorated(False)
        self._reload_tree()
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.btn_change         = QPushButton("Change...")
        self.btn_clear          = QPushButton("Clear")
        self.btn_reset_selected = QPushButton("Reset Selected")
        self.btn_reset_all      = QPushButton("Reset All")
        for b in (self.btn_change, self.btn_clear, self.btn_reset_selected, self.btn_reset_all):
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.btn_change.clicked.connect(self.change_selected)
        self.btn_clear.clicked.connect(self.clear_selected)
        self.btn_reset_selected.clicked.connect(self.reset_selected)
        self.btn_reset_all.clicked.connect(self.reset_all)
        self.tree.itemDoubleClicked.connect(lambda *_: self.change_selected())

    def _reload_tree(self):
        self.tree.clear()
        # Collect all shortcuts for conflict detection
        all_shortcuts = {}  # normalised key -> list of (category, label)
        for key, category, label in self.ACTION_ROWS:
            seq = self.shortcuts.get(key, "")
            if seq:
                norm = QKeySequence(seq).toString(QKeySequence.PortableText)
                if norm:
                    all_shortcuts.setdefault(norm, []).append((category, label))
        for asc in self._addon_shortcuts:
            oid = "%s::%s" % (asc.get("addon", ""), asc.get("name", ""))
            seq = self.addon_overrides.get(oid, "")
            if seq:
                norm = QKeySequence(seq).toString(QKeySequence.PortableText)
                if norm:
                    all_shortcuts.setdefault(norm, []).append(("Addon: " + asc.get("addon", ""), asc.get("name", "")))

        conflict_keys = {k for k, v in all_shortcuts.items() if len(v) > 1}

        # Built-in rows
        for key, category, label in self.ACTION_ROWS:
            seq = self.shortcuts.get(key, "")
            item = QTreeWidgetItem(self.tree, [category, label, seq, DEFAULT_EDITOR_SHORTCUTS.get(key, "")])
            item.setData(0, Qt.UserRole, ("builtin", key))
            norm = QKeySequence(seq).toString(QKeySequence.PortableText) if seq else ""
            if norm in conflict_keys:
                for col in range(4):
                    item.setForeground(col, QColor("#cc0000"))
                item.setToolTip(0, "Shortcut conflict: '%s' is used by multiple actions" % seq)

        # Addon rows — grouped by addon name, editable
        grouped = {}
        for asc in self._addon_shortcuts:
            grouped.setdefault(asc.get("addon", "Addon"), []).append(asc)
        for addon_name in sorted(grouped.keys()):
            for asc in grouped[addon_name]:
                oid = "%s::%s" % (addon_name, asc.get("name", ""))
                seq = self.addon_overrides.get(oid, "")
                default_key = asc.get("default_key", "")
                item = QTreeWidgetItem(self.tree, [
                    "Addon: %s" % addon_name,
                    asc.get("name", ""),
                    seq,
                    default_key,
                ])
                item.setData(0, Qt.UserRole, ("addon", oid))
                font = item.font(0); font.setItalic(True)
                for col in range(4):
                    item.setFont(col, font)
                norm = QKeySequence(seq).toString(QKeySequence.PortableText) if seq else ""
                if norm in conflict_keys:
                    for col in range(4):
                        item.setForeground(col, QColor("#cc0000"))
                    item.setToolTip(0, "Shortcut conflict: '%s' is used by multiple actions" % seq)

        for i in range(4): self.tree.resizeColumnToContents(i)

    def _selected_ref(self):
        """Returns (kind, id) tuple or None."""
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def _selected_label(self):
        item = self.tree.currentItem()
        return item.text(1) if item else "Shortcut"

    def _current_seq(self, ref):
        kind, ident = ref
        if kind == "builtin":
            return self.shortcuts.get(ident, "")
        return self.addon_overrides.get(ident, "")

    def _default_seq(self, ref):
        kind, ident = ref
        if kind == "builtin":
            return DEFAULT_EDITOR_SHORTCUTS.get(ident, "")
        for asc in self._addon_shortcuts:
            if "%s::%s" % (asc.get("addon", ""), asc.get("name", "")) == ident:
                return asc.get("default_key", "")
        return ""

    def _set_seq(self, ref, seq):
        kind, ident = ref
        if kind == "builtin":
            self.shortcuts[ident] = seq
        else:
            self.addon_overrides[ident] = seq

    def _conflicting_action(self, ref, sequence_text):
        if not sequence_text: return None
        candidate = QKeySequence(sequence_text).toString(QKeySequence.PortableText)
        kind, ident = ref
        for other_key, _cat, label in self.ACTION_ROWS:
            if kind == "builtin" and other_key == ident: continue
            other = QKeySequence(self.shortcuts.get(other_key, "")).toString(QKeySequence.PortableText)
            if other and other == candidate: return label
        for asc in self._addon_shortcuts:
            oid = "%s::%s" % (asc.get("addon", ""), asc.get("name", ""))
            if kind == "addon" and oid == ident: continue
            norm = QKeySequence(self.addon_overrides.get(oid, "")).toString(QKeySequence.PortableText)
            if norm and norm == candidate:
                return "Addon: %s — %s" % (asc.get("addon", ""), asc.get("name", ""))
        return None

    def change_selected(self):
        ref = self._selected_ref()
        if not ref: return
        dlg = ShortcutCaptureDialog(self._selected_label(), self._current_seq(ref), self)
        if dlg.exec_() != QDialog.Accepted: return
        seq = dlg.sequence_text().strip()
        conflict = self._conflicting_action(ref, seq)
        if conflict: QMessageBox.warning(self, "Shortcut Conflict", "That shortcut is already used by: %s" % conflict); return
        self._set_seq(ref, seq); self._reload_tree()

    def clear_selected(self):
        ref = self._selected_ref()
        if ref: self._set_seq(ref, ""); self._reload_tree()

    def reset_selected(self):
        ref = self._selected_ref()
        if ref: self._set_seq(ref, self._default_seq(ref)); self._reload_tree()

    def reset_all(self):
        self.shortcuts = dict(DEFAULT_EDITOR_SHORTCUTS)
        for asc in self._addon_shortcuts:
            oid = "%s::%s" % (asc.get("addon", ""), asc.get("name", ""))
            self.addon_overrides[oid] = asc.get("default_key", "")
        self._reload_tree()

    def _on_accept(self):
        self._accepted = True; self.accept()

    def was_accepted(self):
        return self._accepted


# ===========================================================================
# PlaceholderDialog
# ===========================================================================
class PlaceholderDialog(QDialog):
    def __init__(self, title, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(680, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(text), 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject); buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class _AddonTreeItem(QTreeWidgetItem):
    """QTreeWidgetItem that sorts column 0 by check state instead of text."""
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
        self.setWindowTitle("QFAT04 Addon Manager")
        self.resize(600, 420)
        self._addon_manager = addon_manager
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Enable or disable addons discovered in the /addons/ folder.\n"
            "Addons with a settings icon can be configured."))

        # Use a tree widget for columns: [checkbox] [name] [description] [settings] [status]
        self.addon_list = QTreeWidget()
        self.addon_list.setHeaderLabels(["On", "Addon", "Description", "", "Status"])
        self.addon_list.setRootIsDecorated(False)
        self.addon_list.setColumnWidth(0, 40)
        self.addon_list.setColumnWidth(1, 180)
        self.addon_list.setColumnWidth(3, 70)
        self.addon_list.setColumnWidth(4, 80)
        self.addon_list.setSortingEnabled(True)
        self.addon_list.sortByColumn(1, Qt.AscendingOrder)
        self.addon_list.itemChanged.connect(self._on_addon_check_changed)
        active_addons = config.get("enabled_addons", [])
        self._original_states = {}  # addon_id -> was_checked (bool)

        self._settings_btns = {}
        self._hidden_addons = set(
            QSettings().value("QFAT/QFAT04/hidden_addons", "", type=str).split("|")
        ) - {""}
        for key, data in addon_manager.registry.items():
            if key in self._hidden_addons:
                continue  # hidden by user
            item = _AddonTreeItem([
                "",
                data.get("name", key),
                data.get("description", ""),
                "",
                "",
            ])
            item.setData(0, Qt.UserRole, key)
            is_core = data.get("core", False)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            checked = key in active_addons
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            self._original_states[key] = checked
            if is_core:
                item.setToolTip(1, "Core addon — enabled by default on first install")
                font = item.font(1); font.setBold(True); item.setFont(1, font)
            self.addon_list.addTopLevelItem(item)

            # Check if addon has settings_dialog hook
            hooks = data.get("hooks", {})
            settings_fn = hooks.get("settings_dialog")
            if settings_fn and callable(settings_fn):
                btn = QPushButton("Settings...")
                btn.setToolTip("Open configuration for '%s'" % data.get("name", key))
                btn.setMaximumWidth(65)
                btn.clicked.connect(lambda _=False, fn=settings_fn: self._open_addon_settings(fn))
                self.addon_list.setItemWidget(item, 3, btn)
                self._settings_btns[key] = btn

        layout.addWidget(self.addon_list)

        # Addon info area
        self._info = QLabel()
        self._info.setWordWrap(True)
        self._info.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self._info)
        self.addon_list.currentItemChanged.connect(self._show_addon_info)
        self.addon_list.itemDoubleClicked.connect(self._on_addon_dblclick)

        # Options row
        opt_row = QHBoxLayout()
        self.chk_scan_startup = QCheckBox("Scan addons folder on startup")
        self.chk_scan_startup.setToolTip(
            "When checked, the addons folder is scanned automatically when QGIS starts.\n"
            "When unchecked, use the Refresh button to discover new addons.")
        self.chk_scan_startup.setChecked(
            QSettings().value("QFAT/QFAT04/addon_scan_on_startup", False, type=bool))
        btn_remove = QPushButton("Remove")
        btn_remove.setToolTip(
            "Remove the selected addon from the list.\n"
            "The .py file is NOT deleted — use Refresh to bring it back.\n"
            "Core and factory addons cannot be removed.")
        btn_remove.setMaximumWidth(70)
        btn_remove.clicked.connect(self._remove_addon)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.setToolTip("Rescan the addons folder for new or updated addons.")
        btn_refresh.setMaximumWidth(80)
        btn_refresh.clicked.connect(self._refresh_addons)
        opt_row.addWidget(self.chk_scan_startup)
        opt_row.addStretch(1)
        btn_open_folder = QPushButton("Open Addons Folder")
        btn_open_folder.setToolTip("Open the addons folder in the file manager.\nDrop .py addon files here.")
        btn_open_folder.setMaximumWidth(130)
        btn_open_folder.clicked.connect(self._open_addons_folder)
        opt_row.addWidget(btn_open_folder)
        opt_row.addWidget(btn_remove)
        opt_row.addWidget(btn_refresh)
        layout.addLayout(opt_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_addon_info(self, current, _prev):
        if not current:
            self._info.setText("")
            return
        key = current.data(0, Qt.UserRole)
        data = self._addon_manager.registry.get(key, {})
        hooks = list(data.get("hooks", {}).keys())
        self._info.setText(
            "ID: %s\nHooks: %s" % (key, ", ".join(hooks) if hooks else "none"))

    def _refresh_addons(self):
        """Rescan the addons folder and rebuild the list."""
        currently_enabled = self.get_enabled_addons()
        self._addon_manager.load_all(load_everything=True)  # full scan
        self._hidden_addons.clear()  # Refresh clears hidden list
        self._rebuild_list(currently_enabled)

    def _remove_addon(self):
        """Remove selected addon from the list (hide it). File stays in folder."""
        item = self.addon_list.currentItem()
        if not item:
            return
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        data = self._addon_manager.registry.get(key, {})
        if data.get("core", False):
            QMessageBox.information(self, "Remove Addon",
                "Core addons cannot be removed from the list.\n"
                "You can disable them by unchecking the checkbox.")
            return
        self._hidden_addons.add(key)
        self._rebuild_list(self.get_enabled_addons())

    def _on_addon_dblclick(self, item, col):
        """Only open addon source on Shift+double-click."""
        from qgis.PyQt.QtGui import QGuiApplication
        if QGuiApplication.keyboardModifiers() & Qt.ShiftModifier:
            self._open_addon_source(item, col)

    def _open_addon_source(self, item, _col):
        """Double-click an addon to open its .py source file in the editor."""
        key = item.data(0, Qt.UserRole) if item else None
        if not key:
            return
        data = self._addon_manager.registry.get(key, {})
        mod = data.get("module")
        py_path = None
        if mod and hasattr(mod, "__file__") and mod.__file__:
            py_path = mod.__file__
        if not py_path or not os.path.isfile(py_path):
            # Fallback: try key as filename
            py_path = os.path.join(self._addon_manager.addon_dir, key + ".py")
        if not os.path.isfile(py_path):
            return
        parent = self.parent()
        while parent and not hasattr(parent, "new_tab"):
            parent = getattr(parent, "parent", lambda: None)()
        if parent and hasattr(parent, "new_tab"):
            parent.new_tab(py_path)

    def _rebuild_list(self, active_addons):
        """Rebuild the tree from the current registry."""
        self.addon_list.setSortingEnabled(False)
        self.addon_list.clear()
        self._settings_btns = {}
        for key, data in self._addon_manager.registry.items():
            if key in self._hidden_addons:
                continue
            item = _AddonTreeItem([
                "",
                data.get("name", key),
                data.get("description", ""),
                "",
                "",
            ])
            item.setData(0, Qt.UserRole, key)
            is_core = data.get("core", False)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            checked = key in active_addons
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            if is_core:
                item.setToolTip(1, "Core addon — enabled by default on first install")
                font = item.font(1); font.setBold(True); item.setFont(1, font)
            self.addon_list.addTopLevelItem(item)
            hooks = data.get("hooks", {})
            settings_fn = hooks.get("settings_dialog")
            if settings_fn and callable(settings_fn):
                btn = QPushButton("Settings...")
                btn.setToolTip("Open configuration for '%s'" % data.get("name", key))
                btn.setMaximumWidth(65)
                btn.clicked.connect(lambda _=False, fn=settings_fn: self._open_addon_settings(fn))
                self.addon_list.setItemWidget(item, 3, btn)
                self._settings_btns[key] = btn
        self.addon_list.setSortingEnabled(True)

    def _on_accept(self):
        """Save scan_on_startup, hidden addons, and disabled core addons."""
        s = QSettings()
        s.setValue("QFAT/QFAT04/addon_scan_on_startup",
                   self.chk_scan_startup.isChecked())
        s.setValue("QFAT/QFAT04/hidden_addons",
                   "|".join(self._hidden_addons) if self._hidden_addons else "")
        # Track which core addons the user explicitly disabled
        enabled = self.get_enabled_addons()
        disabled_cores = []
        for aid, data in self._addon_manager.registry.items():
            if data.get("core", False) and aid not in enabled:
                disabled_cores.append(aid)
        s.setValue("QFAT/QFAT04/disabled_core_addons",
                   "|".join(disabled_cores) if disabled_cores else "")
        self.accept()

    def _open_addons_folder(self):
        """Open the addons folder in the OS file manager."""
        import subprocess
        folder = self._addon_manager.addon_dir
        if not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        try:
            if os.name == "nt":
                subprocess.run(["explorer", os.path.normpath(folder)])
            else:
                subprocess.run(["xdg-open", folder])
        except Exception as e:
            QMessageBox.warning(self, "Open Folder", "Could not open folder: %s" % str(e))

    def _open_addon_settings(self, settings_fn):
        try:
            dlg = settings_fn(self._addon_manager.dock)
            if dlg and hasattr(dlg, 'exec_'):
                dlg.exec_()
            elif dlg and hasattr(dlg, 'exec'):
                dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "Addon Settings", "Error opening settings: %s" % str(e))

    def get_enabled_addons(self):
        result = []
        for i in range(self.addon_list.topLevelItemCount()):
            item = self.addon_list.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                result.append(item.data(0, Qt.UserRole))
        return result

    def _on_addon_check_changed(self, item, column):
        if column != 0:
            return
        key = item.data(0, Qt.UserRole)
        now_checked = item.checkState(0) == Qt.Checked
        original = self._original_states.get(key)
        if original is not None and now_checked != original:
            # Check if addon has on_enable/on_disable hooks (live toggle)
            data = self._addon_manager.registry.get(key, {})
            hooks = data.get("hooks", {})
            has_live = ("on_enable" in hooks) if now_checked else ("on_disable" in hooks)
            if has_live:
                item.setText(4, "✓ Live")
                item.setToolTip(4, "Change takes effect immediately")
                from qgis.PyQt.QtGui import QColor
                item.setForeground(4, QColor("#27ae60"))
            else:
                item.setText(4, "⚠ Restart")
                item.setToolTip(4, "QGIS restart needed for this change to take effect")
                from qgis.PyQt.QtGui import QColor
                item.setForeground(4, QColor("#e67e22"))
        else:
            item.setText(4, "")
            item.setToolTip(4, "")
        # Re-sort if sorted by col 0
        if self.addon_list.sortColumn() == 0:
            order = self.addon_list.header().sortIndicatorOrder()
            self.addon_list.sortItems(0, order)
