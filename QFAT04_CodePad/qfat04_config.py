"""
qfat04_config.py
Central registry for constants, settings, themes, and language definitions.
"""

import os
import re
import json
import copy

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtGui import QColor, QFont

# ---------------------------------------------------------------------------
# Root key
# ---------------------------------------------------------------------------
SETTINGS_ROOT = "QFAT/QFAT04"

# ---------------------------------------------------------------------------
# File extension sets (internal: always with dots)
# ---------------------------------------------------------------------------
_DEFAULT_RUN_EXTS = {".cmd", ".bat", ".ps1", ".py", ".pyw", ".r"}
TEXT_EXTS = {
    ".tcf", ".tgc", ".tbc", ".tmf", ".tef", ".trd", ".toc", ".toz", ".ecf", ".qcf",
    ".cmd", ".bat", ".ps1",
    ".log", ".txt", ".csv", ".ini",
    ".json", ".geojson", ".yaml", ".yml",
    ".py", ".pyw", ".pyi",
    ".r", ".rmd",
    ".sql",
    ".html", ".htm", ".xml", ".xhtml", ".svg", ".qgs", ".qml",
    ".md", ".markdown",
}

def get_run_exts():
    """Return the set of runnable extensions (configurable via QSettings)."""
    raw = QSettings().value(SETTINGS_ROOT + "/run_extensions", "", type=str)
    if raw.strip():
        return {"." + x.strip().lower().lstrip(".") for x in raw.replace(",", " ").split() if x.strip()}
    return set(_DEFAULT_RUN_EXTS)

# Keep RUN_EXTS as the default for backward compat imports
RUN_EXTS = _DEFAULT_RUN_EXTS


# ---------------------------------------------------------------------------
# Editor shortcuts
# ---------------------------------------------------------------------------
SHORTCUTS_KEY = SETTINGS_ROOT + "/editor_shortcuts_json"
ADDON_SHORTCUTS_KEY = SETTINGS_ROOT + "/addon_shortcuts_json"
LANGUAGES_KEY = SETTINGS_ROOT + "/languages_json"

# ---------------------------------------------------------------------------
# Highlight priority defaults  (used as per-language fallback)
# ---------------------------------------------------------------------------
DEFAULT_HIGHLIGHT_PRIORITIES = {
    "operator":  1,
    "number":    2,
    "path":      3,
    "string":    4,
    "keyword6":  5,
    "keyword5":  6,
    "keyword4":  7,
    "keyword3":  8,
    "keyword2":  9,
    "keyword1":  10,
    "variable":  11,
    "comment":   20,
}


DEFAULT_ADDONS = ['fuzzy_loader']
DEFAULT_EDITOR_SHORTCUTS = {
    "toggle_comment": "Ctrl+/",
    "duplicate_line": "Ctrl+D",
    "save_file": "Ctrl+S",
}

def load_editor_shortcuts():
    shortcuts = dict(DEFAULT_EDITOR_SHORTCUTS)
    raw = QSettings().value(SHORTCUTS_KEY, "", type=str).strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for k, v in data.items():
                    if k in shortcuts and isinstance(v, str):
                        shortcuts[k] = v
        except Exception:
            pass
    return shortcuts

def save_editor_shortcuts(shortcuts):
    payload = {}
    for k in DEFAULT_EDITOR_SHORTCUTS:
        v = shortcuts.get(k, DEFAULT_EDITOR_SHORTCUTS[k])
        if v != DEFAULT_EDITOR_SHORTCUTS[k]:
            payload[k] = v
    QSettings().setValue(SHORTCUTS_KEY, json.dumps(payload, indent=2, sort_keys=True))

def load_addon_shortcut_overrides():
    """Return {'addon_name::shortcut_name': 'key_seq'} user overrides for addon shortcuts."""
    raw = QSettings().value(ADDON_SHORTCUTS_KEY, "", type=str).strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
    except Exception:
        pass
    return {}

def save_addon_shortcut_overrides(overrides):
    QSettings().setValue(ADDON_SHORTCUTS_KEY,
                         json.dumps(overrides or {}, indent=2, sort_keys=True))

# ---------------------------------------------------------------------------
# Directory paths for .json files
# ---------------------------------------------------------------------------
_PLUGIN_DIR    = os.path.dirname(__file__)
_THEMES_DIR    = os.path.join(_PLUGIN_DIR, "themes")
_LANGUAGES_DIR = os.path.join(_PLUGIN_DIR, "languages")

def _load_json_file(path):
    """Load a .json file, return dict or None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        import traceback
        traceback.print_exc()  # prints to QGIS Python console
    return None

# ---------------------------------------------------------------------------
# Built-in themes — loaded from themes/*.json, hardcoded fallback
# ---------------------------------------------------------------------------
_HARDCODED_THEMES = {
    "Dark": {
        "paper": "#1e1e1e", "text": "#d4d4d4", "comment": "#6a9955", "command": "#4fc1ff",
        "keyword": "#c586c0",
        "keyword1": "#c586c0", "keyword2": "#d7ba7d", "keyword3": "#4ec9b0",
        "keyword4": "#9cdcfe", "keyword5": "#ce9178", "keyword6": "#dcdcaa",
        "number": "#b5cea8", "string": "#ce9178", "operator": "#d4d4d4",
        "path": "#4ec9b0", "margin_bg": "#252526", "margin_fg": "#858585",
        "caret": "#ffffff", "selection": "#264f78",
        "brace_bg": "#2d3e50", "brace_fg": "#9cdcfe", "folding": "#555555",
        "font_family": "Consolas", "font_size": 10,
    },
}

def _load_themes_from_folder():
    """Load all .json files from themes/ folder. Returns dict of theme_name -> theme_dict."""
    result = {}
    if not os.path.isdir(_THEMES_DIR):
        return result
    for fname in sorted(os.listdir(_THEMES_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(_THEMES_DIR, fname)
        data = _load_json_file(path)
        if data:
            name = data.get("default_name", data.get("name", fname[:-5]))
            result[name] = data
    return result

def _get_base_themes():
    """Return the base theme dict: .json files first, hardcoded fallback."""
    themes = dict(_HARDCODED_THEMES)
    folder_themes = _load_themes_from_folder()
    themes.update(folder_themes)  # .json files override hardcoded
    return themes

THEMES = _get_base_themes()

# ---------------------------------------------------------------------------
# Theme helpers
# ---------------------------------------------------------------------------
def _theme_settings_key(theme_name):
    return SETTINGS_ROOT + "/theme_overrides/" + theme_name

def _custom_themes_key():
    return SETTINGS_ROOT + "/custom_theme_names"

def list_theme_names():
    names = list(THEMES.keys())
    s = QSettings()
    raw = s.value(_custom_themes_key(), "", type=str).strip()
    if raw:
        for name in [x.strip() for x in raw.split("|") if x.strip()]:
            if name not in names:
                names.append(name)
    return names

def register_custom_theme_name(theme_name):
    if theme_name in THEMES:
        return
    names = [x for x in list_theme_names() if x not in THEMES]
    if theme_name not in names:
        names.append(theme_name)
    QSettings().setValue(_custom_themes_key(), "|".join(names))

def remove_custom_theme_name(theme_name):
    names = [x for x in list_theme_names() if x not in THEMES and x != theme_name]
    QSettings().setValue(_custom_themes_key(), "|".join(names))

def delete_theme(theme_name):
    if theme_name in THEMES:
        return False
    s = QSettings()
    s.remove(_theme_settings_key(theme_name))
    remove_custom_theme_name(theme_name)
    return True

def get_factory_theme(theme_name):
    """Return theme data from .json files only, ignoring QSettings edits."""
    theme = dict(THEMES.get(theme_name, THEMES["Dark"]))
    theme.setdefault("style_overrides", {})
    theme.setdefault("token_styles", {})
    return theme

def get_theme(theme_name):
    s = QSettings()
    theme = dict(THEMES.get(theme_name, THEMES["Dark"]))
    theme.setdefault("style_overrides", {})
    theme.setdefault("token_styles", {})
    raw = s.value(_theme_settings_key(theme_name), "", type=str)
    if raw:
        try:
            overrides = json.loads(raw)
            if isinstance(overrides, dict):
                for k, v in overrides.items():
                    if k == "style_overrides" and isinstance(v, dict):
                        theme[k] = v
                    elif k == "token_styles" and isinstance(v, dict):
                        theme[k] = v
                    elif k == "font_family" and isinstance(v, str) and v.strip():
                        theme[k] = v.strip()
                    elif k == "font_size" and isinstance(v, int) and v > 0:
                        theme[k] = v
                    elif isinstance(v, str) and v.startswith("#"):
                        theme[k] = v
        except Exception:
            pass
    return theme

def save_theme(theme_name, theme_dict):
    s = QSettings()
    if theme_name in THEMES:
        base = THEMES.get(theme_name, THEMES["Dark"])
        payload = {}
        for k, v in theme_dict.items():
            if k in ("style_overrides", "token_styles"):
                if v:
                    payload[k] = v
            elif k == "font_family" and isinstance(v, str) and v.strip():
                if v.strip() != base.get("font_family", "Consolas"):
                    payload[k] = v.strip()
            elif k == "font_size" and isinstance(v, int) and v > 0:
                if v != base.get("font_size", 10):
                    payload[k] = v
            elif isinstance(v, str) and v.startswith("#") and base.get(k) != v:
                payload[k] = v
        s.setValue(_theme_settings_key(theme_name), json.dumps(payload, indent=2, sort_keys=True))
    else:
        register_custom_theme_name(theme_name)
        payload = {}
        for k, v in theme_dict.items():
            if k in ("style_overrides", "token_styles"):
                if v:
                    payload[k] = v
            elif k == "font_family" and isinstance(v, str) and v.strip():
                payload[k] = v.strip()
            elif k == "font_size" and isinstance(v, int) and v > 0:
                payload[k] = v
            elif isinstance(v, str) and v.startswith("#"):
                payload[k] = v
        s.setValue(_theme_settings_key(theme_name), json.dumps(payload, indent=2, sort_keys=True))

# ---------------------------------------------------------------------------
# Style-override helpers (theme-level per-token font overrides)
# ---------------------------------------------------------------------------
def get_style_override(theme_dict, style_key):
    return copy.deepcopy(theme_dict.get("style_overrides", {}).get(style_key, {}))

def set_style_override(theme_dict, style_key, override_dict):
    theme_dict.setdefault("style_overrides", {})
    clean = {}
    for k, v in (override_dict or {}).items():
        if k in ("font_family",) and isinstance(v, str) and v.strip():
            clean[k] = v.strip()
        elif k in ("font_size",) and isinstance(v, int) and v > 0:
            clean[k] = v
        elif k in ("bold", "italic", "underline") and isinstance(v, bool):
            clean[k] = v
    if clean:
        theme_dict["style_overrides"][style_key] = clean
    else:
        theme_dict.get("style_overrides", {}).pop(style_key, None)

def style_font_from_theme(theme_dict, config, style_key):
    ov = get_style_override(theme_dict, style_key)
    font = QFont(
        ov.get("font_family", config["font_family"]),
        ov.get("font_size", config["font_size"]),
    )
    font.setBold(ov.get("bold", False))
    font.setItalic(ov.get("italic", False))
    font.setUnderline(ov.get("underline", False))
    return font

# ---------------------------------------------------------------------------
# Per-language local style helpers
# ---------------------------------------------------------------------------
def language_style(lang_def, style_key):
    """Return the local style dict stored in a language definition."""
    if not isinstance(lang_def, dict):
        return {}
    styles = lang_def.get("styles", {})
    if isinstance(styles, dict):
        item = styles.get(style_key, {})
        if isinstance(item, dict):
            return copy.deepcopy(item)
    return {}

def style_color(theme_dict, lang_def, style_key):
    ov = language_style(lang_def, style_key)
    fg = ov.get("fg", "")
    if fg:
        return fg
    return theme_dict.get(style_key, "#808080")

def style_paper(theme_dict, lang_def, style_key):
    ov = language_style(lang_def, style_key)
    bg = ov.get("bg", None)
    if bg:   # non-empty string = explicit colour
        return bg
    return theme_dict.get("paper", "#ffffff")  # "" or missing = transparent (use paper)

def style_font(theme_dict, config, lang_def, style_key):
    ov   = get_style_override(theme_dict, style_key)
    lov  = language_style(lang_def, style_key)
    font = QFont(
        lov.get("font_family", ov.get("font_family", config["font_family"])),
        int(lov.get("font_size", ov.get("font_size", config["font_size"]))),
    )
    font.setBold(bool(lov.get("bold", ov.get("bold", False))))
    font.setItalic(bool(lov.get("italic", ov.get("italic", False))))
    font.setUnderline(bool(lov.get("underline", ov.get("underline", False))))
    return font

# ---------------------------------------------------------------------------
# Language system
# ---------------------------------------------------------------------------
def _norm_ext_list(items):
    """Normalise extensions to internal format (with dots, lowercase).
    Accepts: list of strings, or a single comma/space separated string.
    Input can be with or without dots: 'tcf,tgc' or '.tcf,.tgc' or ['tcf', '.tgc']
    Output always has dots: ['.tcf', '.tgc']
    """
    if isinstance(items, str):
        items = [x.strip() for x in items.replace(",", " ").split() if x.strip()]
    out = []
    for item in items or []:
        ext = str(item).strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in out:
            out.append(ext)
    return out


def _ext_list_to_display(items):
    """Convert internal extension list (with dots) to display format (no dots, comma separated).
    ['.tcf', '.tgc'] -> 'tcf,tgc'
    """
    return ",".join(e.lstrip(".") for e in (items or []))

_HARDCODED_LANGUAGE_DEFAULTS = {
    "text": {
        "default_name": "Plain Text", "name": "Plain Text", "base": "text",
        "extensions": ["txt", "csv", "ini", "json", "yaml", "yml"],
        "comment_prefixes": [], "keywords": [],
        "case_sensitive": False, "builtin": True,
    },
}

def _load_languages_from_folder():
    """Load all .json files from languages/ folder. Returns dict of key -> lang_dict."""
    result = {}
    if not os.path.isdir(_LANGUAGES_DIR):
        return result
    for fname in sorted(os.listdir(_LANGUAGES_DIR)):
        if not fname.endswith(".json"):
            continue
        key = fname[:-5]  # e.g. "tuflow" from "tuflow.json"
        path = os.path.join(_LANGUAGES_DIR, fname)
        data = _load_json_file(path)
        if data:
            data.setdefault("builtin", True)
            # Convert default_name → name if no user name set
            if "default_name" in data and "name" not in data:
                data["name"] = data["default_name"]
            result[key] = data
    return result

def _language_defaults():
    """Return language defaults: .json files first, hardcoded fallback."""
    defaults = dict(_HARDCODED_LANGUAGE_DEFAULTS)
    folder_langs = _load_languages_from_folder()
    defaults.update(folder_langs)  # .json files override hardcoded
    return defaults

def language_json_path(language_key):
    """Return the .json file path for a language, or None if no file exists."""
    path = os.path.join(_LANGUAGES_DIR, language_key + ".json")
    return path if os.path.isfile(path) else None

def theme_json_path(theme_name):
    """Return the .json file path for a theme, or None if no file exists."""
    # Theme files use the name as filename, lowercased
    for fname in os.listdir(_THEMES_DIR) if os.path.isdir(_THEMES_DIR) else []:
        if fname.endswith(".json"):
            data = _load_json_file(os.path.join(_THEMES_DIR, fname))
            if data and (data.get("name") == theme_name or data.get("default_name") == theme_name):
                return os.path.join(_THEMES_DIR, fname)
    return None

def _clean_language_fields(lang):
    """Extract and validate the extended fields of a language definition."""
    out = {}
    if not isinstance(lang, dict):
        return out
    groups = lang.get("keyword_groups")
    if isinstance(groups, list):
        gs = [str(x) for x in groups[:6]]
        out["keyword_groups"] = gs + [""] * (6 - len(gs))
    pm = lang.get("prefix_modes")
    if isinstance(pm, list):
        vals = [bool(x) for x in pm[:6]]
        out["prefix_modes"] = vals + [False] * (6 - len(vals))
    kgs = lang.get("keyword_group_styles")
    if isinstance(kgs, list):
        styles = [str(x) if str(x).strip() else "keyword%d" % (i + 1)
                  for i, x in enumerate(kgs[:6])]
        out["keyword_group_styles"] = styles + ["keyword%d" % (i + 1)
                                                for i in range(len(styles), 6)]
    for k in ("operators1", "operators2", "operators3", "operators4", "operators5", "operators6",
              "doc_text", "default_style_note",
              "comment_position", "comment_continue", "comment_close",
              "block_comment_open", "block_comment_close", "path_pattern",
              "_last_modified"):
        if k in lang:
            out[k] = str(lang.get(k, ""))
    if "fold_comments" in lang:
        out["fold_comments"] = bool(lang.get("fold_comments", True))
    if "delimiters" in lang and isinstance(lang.get("delimiters"), list):
        ds = []
        for d in lang.get("delimiters", [])[:8]:
            if isinstance(d, dict):
                ds.append({
                    "open":   str(d.get("open",   "")),
                    "escape": str(d.get("escape", "")),
                    "close":  str(d.get("close",  "")),
                })
        while len(ds) < 8:
            ds.append({"open": "", "escape": "", "close": ""})
        out["delimiters"] = ds
    if "number_style" in lang and isinstance(lang.get("number_style"), dict):
        ns = lang["number_style"]
        out["number_style"] = {
            "prefix1": str(ns.get("prefix1", "")), "prefix2": str(ns.get("prefix2", "")),
            "extras1": str(ns.get("extras1", "")), "extras2": str(ns.get("extras2", "")),
            "suffix1": str(ns.get("suffix1", "")), "suffix2": str(ns.get("suffix2", "")),
            "range":   str(ns.get("range",   "")), "decimal": str(ns.get("decimal", "dot")),
        }
    if "styles" in lang and isinstance(lang.get("styles"), dict):
        clean_styles = {}
        for sk, sv in lang["styles"].items():
            if not isinstance(sv, dict):
                continue
            item = {}
            for k, v in sv.items():
                if k in ("fg", "bg") and isinstance(v, str):
                    if v.startswith("#"):
                        item[k] = v
                    # empty string = explicitly cleared override, don't store it
                elif k == "font_family" and isinstance(v, str) and v.strip():
                    item[k] = v.strip()
                elif k == "font_size":
                    try:
                        iv = int(v)
                        if iv > 0:
                            item[k] = iv
                    except Exception:
                        pass
                elif k in ("bold", "italic", "underline"):
                    item[k] = bool(v)
                elif k == "nesting" and isinstance(v, list):
                    item[k] = [str(x) for x in v[:16]]
            if item:
                clean_styles[str(sk)] = item
        if clean_styles:
            out["styles"] = clean_styles
    for k in ("validation", "help", "folding"):
        if k in lang and isinstance(lang.get(k), dict):
            out[k] = copy.deepcopy(lang[k])
    if "snippets" in lang:
        out["snippets"] = str(lang.get("snippets", ""))
    # Per-language highlight priorities
    if "highlight_priorities" in lang and isinstance(lang.get("highlight_priorities"), dict):
        clean_pri = {}
        for k in ("operator","number","string","command",
                  "keyword1","keyword2","keyword3","keyword4","keyword5","keyword6",
                  "path","comment","variable"):
            v = lang["highlight_priorities"].get(k)
            if v is not None:
                try:
                    iv = int(v)
                    if iv >= 0:
                        clean_pri[k] = iv
                except (TypeError, ValueError):
                    pass
        if clean_pri:
            out["highlight_priorities"] = clean_pri
    # Tab override modes (0=factory, 1=custom theme, 2=custom)
    if "_tab_overrides" in lang and isinstance(lang.get("_tab_overrides"), dict):
        out["_tab_overrides"] = {str(k): int(v) if isinstance(v, (int, float)) else (2 if v else 1)
                                  for k, v in lang["_tab_overrides"].items()}
    return out


def load_languages():
    defaults = _language_defaults()
    raw = QSettings().value(LANGUAGES_KEY, "", type=str).strip()
    if not raw:
        for k in defaults:
            if isinstance(defaults[k], dict):
                defaults[k]["extensions"] = _norm_ext_list(defaults[k].get("extensions", []))
        return defaults
    try:
        data = json.loads(raw)
    except Exception:
        for k in defaults:
            if isinstance(defaults[k], dict):
                defaults[k]["extensions"] = _norm_ext_list(defaults[k].get("extensions", []))
        return defaults
    if not isinstance(data, dict):
        return defaults
    out = defaults
    # Normalize extensions on all defaults (json files may have no-dot format)
    for key in out:
        if isinstance(out[key], dict):
            out[key]["extensions"] = _norm_ext_list(out[key].get("extensions", []))
    for key, lang in data.items():
        if not isinstance(lang, dict):
            continue
        item = out.get(key, {}).copy()
        saved_name = str(lang.get("name", item.get("name", key))).strip() or item.get("name", key)
        # One-time migration: old default name → new default name
        _OLD_NAME_MAP = {"TUFLOW Control": "TUFLOW Classic/HPC"}
        if saved_name in _OLD_NAME_MAP:
            saved_name = _OLD_NAME_MAP[saved_name]
        item["name"]             = saved_name
        item["base"]             = str(lang.get("base", item.get("base", "text"))).strip().lower() or "text"
        item["extensions"]       = _norm_ext_list(lang.get("extensions") or item.get("extensions", []))
        item["comment_prefixes"] = [str(x).strip() for x in lang.get("comment_prefixes", item.get("comment_prefixes", [])) if str(x).strip()]
        item["keywords"]         = [str(x).strip() for x in lang.get("keywords", item.get("keywords", [])) if str(x).strip()]
        item["case_sensitive"]   = bool(lang.get("case_sensitive", item.get("case_sensitive", False)))
        item.update(_clean_language_fields(lang))
        item["builtin"] = key in defaults
        out[key] = item
    return out


def save_languages(languages):
    defaults = _language_defaults()
    payload = {}
    for key, lang in languages.items():
        item = {
            "name":             str(lang.get("name", key)).strip() or key,
            "base":             str(lang.get("base", "text")).strip().lower() or "text",
            "extensions":       _norm_ext_list(lang.get("extensions", [])),
            "comment_prefixes": [str(x).strip() for x in lang.get("comment_prefixes", []) if str(x).strip()],
            "keywords":         [str(x).strip() for x in lang.get("keywords", []) if str(x).strip()],
            "case_sensitive":   bool(lang.get("case_sensitive", False)),
        }
        item.update(_clean_language_fields(lang))
        if key in defaults:
            cmp = {
                "name":             str(defaults[key].get("name", defaults[key].get("default_name", key))).strip(),
                "base":             str(defaults[key].get("base", "text")).strip().lower(),
                "extensions":       _norm_ext_list(defaults[key].get("extensions", [])),
                "comment_prefixes": [str(x).strip() for x in defaults[key].get("comment_prefixes", []) if str(x).strip()],
                "keywords":         [str(x).strip() for x in defaults[key].get("keywords", []) if str(x).strip()],
                "case_sensitive":   bool(defaults[key].get("case_sensitive", False)),
            }
            cmp.update(_clean_language_fields(defaults[key]))
            if item == cmp:
                continue
        payload[key] = item
    QSettings().setValue(LANGUAGES_KEY, json.dumps(payload, indent=2, sort_keys=True))


def language_display_name(languages, key):
    lang = languages.get(key, {})
    return lang.get("name", lang.get("default_name", key))


def make_language_key(name, languages):
    base = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "language"
    key  = "custom_" + base
    i    = 2
    while key in languages:
        key = "custom_%s_%d" % (base, i)
        i  += 1
    return key


def language_for_extension(languages, ext):
    ext = (ext or "").lower()
    for key, lang in languages.items():
        if ext in lang.get("extensions", []):
            return key
    return "text"

# ---------------------------------------------------------------------------
# Main config load / save
# ---------------------------------------------------------------------------
def load_config():
    s = QSettings()
    theme = s.value(SETTINGS_ROOT + "/theme", "Dark", type=str)
    if theme not in list_theme_names():
        theme = "Dark"
    raw_tb = s.value(SETTINGS_ROOT + "/toolbar_items", "", type=str).strip()
    tb_items = (
        [x.strip() for x in raw_tb.split("|") if x.strip()]
        if raw_tb
        else ["open", "save", "reload", "run", "run_external", "stop", "prefs", "shortcuts", "float"]
    )
    languages = load_languages()
    theme_dict = get_theme(theme)
    return {
        "font_family":        theme_dict.get("font_family", "Consolas"),
        "font_size":          theme_dict.get("font_size", 10),
        "tab_width":          s.value(SETTINGS_ROOT + "/tab_width",          4,          type=int),
        "theme":              theme,
        "wrap":               s.value(SETTINGS_ROOT + "/wrap",               False,      type=bool),
        "show_line_numbers":  s.value(SETTINGS_ROOT + "/show_line_numbers",  True,       type=bool),
        "show_whitespace":    s.value(SETTINGS_ROOT + "/show_whitespace",    False,      type=bool),
        "show_eol":           s.value(SETTINGS_ROOT + "/show_eol",           False,      type=bool),
        "show_indent_guides": s.value(SETTINGS_ROOT + "/show_indent_guides", True,       type=bool),
        "folding":            s.value(SETTINGS_ROOT + "/folding",            True,       type=bool),
        "brace_matching":     s.value(SETTINGS_ROOT + "/brace_matching",     True,       type=bool),
        "zoom":               s.value(SETTINGS_ROOT + "/zoom",               0,          type=int),
        "toolbar_items":      tb_items,
        "enabled_addons": [x for x in s.value(SETTINGS_ROOT + "/enabled_addons", "fuzzy_loader|python_console", type=str).split("|") if x],
        "drop_exts":          s.value(
            SETTINGS_ROOT + "/drop_exts",
            "tcf, tgc, tmf, tef, trd, toc, ecf, bc_dbase, cmd, bat, ps1",
            type=str,
        ),
        "tab_min_width":      s.value(SETTINGS_ROOT + "/tab_min_width",      60,  type=int),
        "tab_max_width":      s.value(SETTINGS_ROOT + "/tab_max_width",      180, type=int),
        "tab_font_size":      s.value(SETTINGS_ROOT + "/tab_font_size",      8,   type=int),
        "show_tab_close":     s.value(SETTINGS_ROOT + "/show_tab_close",     True, type=bool),
        "tab_inflate_active": s.value(SETTINGS_ROOT + "/tab_inflate_active", False, type=bool),
        "editor_backend":     s.value(SETTINGS_ROOT + "/editor_backend",     "auto", type=str),
        "languages": languages,
    }

def save_config(cfg):
    s = QSettings()
    for key in [
        "tab_width", "theme", "wrap",
        "show_line_numbers", "show_whitespace", "show_eol", "show_indent_guides",
        "folding", "brace_matching", "zoom", "tab_min_width", "tab_max_width", "tab_font_size",
        "show_tab_close", "tab_inflate_active",
    ]:
        s.setValue(SETTINGS_ROOT + "/" + key, cfg[key])
    s.setValue(SETTINGS_ROOT + "/editor_backend", cfg.get("editor_backend", "auto"))
    s.setValue(SETTINGS_ROOT + "/toolbar_items",   "|".join(cfg.get("toolbar_items", [])))
    s.setValue(SETTINGS_ROOT + "/enabled_addons", "|".join(cfg.get("enabled_addons", [])))
    s.setValue(SETTINGS_ROOT + "/drop_exts",       cfg.get("drop_exts", ""))
    save_languages(cfg.get("languages", load_languages()))
