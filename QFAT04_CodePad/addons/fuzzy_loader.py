"""
fuzzy_loader.py  v0.2
Core addon: Fuzzy path extraction and smart file routing for TUFLOW control files.

v0.2: Added optional GeoPackage syntax detection (>>, &&, |, USE ALL, bare layer
names resolved via Spatial Database). Opt-in via settings (default off).

Scans text for file paths, resolves them relative to the active file,
and routes them to the editor (text files) or QGIS (GIS layers).

This is a core addon -- always enabled, cannot be disabled.
"""
__version__ = "0.9"

import os
import re
import subprocess
from collections import Counter

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QMenu, QDialog, QLineEdit, QCheckBox,
    QDialogButtonBox, QLabel, QGroupBox, QPushButton, QInputDialog,
)
from qgis.PyQt.QtCore import Qt, QSettings

# ---------------------------------------------------------------------------
# Settings keys
# ---------------------------------------------------------------------------
_S_ROOT = "QFAT/QFAT04/addon_fuzzy/"
_S_GIS_EXTS = _S_ROOT + "gis_extensions"
_S_EDITOR_EXTS = _S_ROOT + "editor_extensions"
_S_INCLUDE_COMMENTS = _S_ROOT + "include_comments"
_S_GPKG_ENABLED = _S_ROOT + "gpkg_enabled"
_S_DEBUG = _S_ROOT + "debug"

_DEFAULT_GIS_EXTS = "shp,asc,flt,gpkg,mif,mid,tif"
_DEFAULT_EDITOR_EXTS = "tgc,tcf,tbc,tef,tmf,trd,toc,toz,ecf,qcf,txt,bat,cmd,ps1"


def _get_gis_exts():
    raw = QSettings().value(_S_GIS_EXTS, _DEFAULT_GIS_EXTS, type=str)
    return {"." + x.strip().lower().lstrip(".") for x in raw.replace(",", " ").split() if x.strip()}


def _get_editor_exts():
    raw = QSettings().value(_S_EDITOR_EXTS, _DEFAULT_EDITOR_EXTS, type=str)
    return {"." + x.strip().lower().lstrip(".") for x in raw.replace(",", " ").split() if x.strip()}


def _get_include_comments():
    return QSettings().value(_S_INCLUDE_COMMENTS, False, type=bool)


def _gpkg_enabled():
    """Public getter for gpkg detection flag. Used by locator/creator/exporter."""
    return QSettings().value(_S_GPKG_ENABLED, False, type=bool)


def _debug_enabled():
    """Public getter for debug output flag."""
    return QSettings().value(_S_DEBUG, False, type=bool)


# ---------------------------------------------------------------------------
# Regex engine (public -- used by file_reference_panel addon too)
# ---------------------------------------------------------------------------
def _build_regex(gis_exts, editor_exts, include_comments=False):
    all_exts = gis_exts | editor_exts
    ext_pattern = "|".join(re.escape(ext.lstrip(".")) for ext in sorted(all_exts))
    if include_comments:
        exclude_chars = r'[^|\"\'\n\t*?<>]*?'
    else:
        exclude_chars = r'[^|!\"\'\n\t*?<>]*?'
    return re.compile(
        r"((?:[A-Za-z]:[\\\/]+|[\\\/]{2}|\.\.[\\\/]+|(?:[A-Za-z0-9_.\-# ]+[\\\/])+)"
        + exclude_chars + r"\.(?:" + ext_pattern + r"))",
        re.IGNORECASE,
    )


def _strip_comments(text):
    """Strip TUFLOW comments (! delimiter) from text.
    Only ! is used -- # is NOT a TUFLOW comment character."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        for i, ch in enumerate(line):
            if ch == "!":
                line = line[:i]
                break
        cleaned.append(line)
    return "\n".join(cleaned)


def extract_fuzzy_paths(text, base_dir=""):
    """Extract all file paths from text, resolve relative to base_dir."""
    gis_exts = _get_gis_exts()
    editor_exts = _get_editor_exts()
    include_comments = _get_include_comments()
    regex = _build_regex(gis_exts, editor_exts, include_comments)
    if not include_comments:
        text = _strip_comments(text)
    segments = text.replace("|", "\n")
    results = []
    for p in regex.findall(segments):
        norm = os.path.normpath(p.strip())
        if not os.path.isabs(norm) and base_dir:
            norm = os.path.normpath(os.path.join(base_dir, norm))
        if os.path.exists(norm) and norm not in results:
            results.append(norm)
    return results


# ---------------------------------------------------------------------------
# GeoPackage reference parsing
# ---------------------------------------------------------------------------
_RE_SPATIAL_DB = re.compile(
    r"^\s*Spatial\s+Database\s*==\s*(.+?)\s*$",
    re.IGNORECASE,
)


def _find_spatial_db_above(page_text, ref_line_1based):
    """Walk up from ref_line-1 to line 1 in page_text. Return first
    'Spatial Database ==' value found, else None. OFF returns 'OFF' sentinel."""
    if not page_text:
        return None
    lines = page_text.splitlines()
    # lines list is 0-indexed; ref_line_1based=1 means lines[0]
    start = min(ref_line_1based - 2, len(lines) - 1)  # walk from line ref-1 upward
    for i in range(start, -1, -1):
        # strip comments
        line = lines[i]
        if "!" in line:
            line = line[:line.index("!")]
        m = _RE_SPATIAL_DB.match(line)
        if m:
            val = m.group(1).strip()
            return val  # may be "OFF" or a path
    return None


def _find_open_tcf_pages(dock):
    """Return list of EditorPage objects for open .tcf tabs."""
    results = []
    if not dock or not hasattr(dock, "tabs"):
        return results
    for i in range(dock.tabs.count()):
        page = dock.tabs.widget(i)
        if page and getattr(page, "path", None):
            if page.path.lower().endswith(".tcf"):
                results.append(page)
    return results


def _tcf_global_db(tcf_page):
    """Scan a tcf page top-to-bottom, track current Spatial Database state.
    Last non-OFF path wins. OFF clears. Return final db path or None."""
    if not tcf_page:
        return None
    try:
        text = tcf_page.editor.editor_text()
    except Exception:
        return None
    if not text:
        return None
    current = None
    for line in text.splitlines():
        if "!" in line:
            line = line[:line.index("!")]
        m = _RE_SPATIAL_DB.match(line)
        if m:
            val = m.group(1).strip()
            if val.upper() == "OFF":
                current = None
            else:
                current = val
    return current


def _resolve_spatial_db(dock, page, ref_line_1based):
    """Find active Spatial Database for a reference.
    1) Walk up current file.
    2) Fall back to .tcf global (prompt if multiple open).
    Returns absolute db path, or None if none found or user cancelled.
    Second return value: warning message string (or None)."""
    if not page:
        return None, "no active file"

    # 1. Walk up current file
    try:
        text = page.editor.editor_text()
    except Exception:
        text = ""
    local = _find_spatial_db_above(text, ref_line_1based)
    if local and local.upper() != "OFF":
        base = os.path.dirname(page.path) if page.path else ""
        abs_db = local if os.path.isabs(local) else os.path.normpath(os.path.join(base, local))
        return abs_db, None

    # 2. .tcf fallback
    tcf_pages = _find_open_tcf_pages(dock)
    if not tcf_pages:
        return None, "no .tcf open to resolve bare layer"
    if len(tcf_pages) == 1:
        chosen = tcf_pages[0]
    else:
        names = [os.path.basename(p.path) for p in tcf_pages]
        name, ok = QInputDialog.getItem(
            dock, "Multiple .tcf files open",
            "Select the .tcf to resolve 'Spatial Database' global:",
            names, 0, False)
        if not ok:
            return None, "user cancelled .tcf selection"
        chosen = tcf_pages[names.index(name)]

    db = _tcf_global_db(chosen)
    if not db:
        return None, "no 'Spatial Database' found in " + os.path.basename(chosen.path)
    base = os.path.dirname(chosen.path)
    abs_db = db if os.path.isabs(db) else os.path.normpath(os.path.join(base, db))
    return abs_db, None


def _parse_gpkg_rhs(rhs, active_db):
    """Parse the RHS of a TUFLOW command that may reference GPKG.
    rhs: string after '==' (comments already stripped).
    active_db: absolute db path from Spatial Database context, or None.
    Returns list of (db_path_or_None, layer_name_or_USE_ALL_sentinel) tuples.
    db_path is relative/raw here -- caller resolves to absolute.
    Layer == '*' sentinel for USE ALL."""
    results = []
    # Split on | -> separate refs, each may carry own db
    for seg in rhs.split("|"):
        seg = seg.strip()
        if not seg:
            continue
        # Split on >>
        if ">>" in seg:
            left, right = seg.split(">>", 1)
            db_part = left.strip()
            # Skip if left side has a non-gpkg extension
            if db_part and "." in os.path.basename(db_part.replace("\\", "/")) and not db_part.lower().endswith(".gpkg"):
                continue
            layers_part = right.strip()
            # layers_part may be "USE ALL" or "L1 && L2 && L3"
            if layers_part.upper() == "USE ALL":
                results.append((db_part or None, "*"))
            else:
                for layer in layers_part.split("&&"):
                    layer = layer.strip()
                    if layer:
                        results.append((db_part or None, layer))
        else:
            # No >>: could be bare layer(s) OR bare .gpkg path OR non-gpkg file
            # Bare .gpkg path -> layer name = file stem (rule 5)
            # Non-gpkg file (e.g. .shp, .mif, .tif) -> skip entirely
            # Bare layer(s) (no extension) -> use active_db, layer name = token
            if seg.lower().endswith(".gpkg"):
                # Normalise path separators for basename extraction
                seg_norm = seg.replace("\\", "/")
                stem = os.path.splitext(os.path.basename(seg_norm))[0]
                results.append((seg, stem))
            elif "." in os.path.basename(seg.replace("\\", "/")):
                # Has a non-gpkg extension -> not a gpkg ref, skip
                continue
            else:
                # Bare layer(s), allow && between them
                for layer in seg.split("&&"):
                    layer = layer.strip()
                    if layer:
                        results.append((None, layer))
    return results


def _resolve_db_path(db_raw, base_dir):
    """Resolve a db path string (possibly relative) to absolute."""
    if not db_raw:
        return None
    norm = os.path.normpath(db_raw)
    if not os.path.isabs(norm) and base_dir:
        norm = os.path.normpath(os.path.join(base_dir, norm))
    return norm


def extract_gpkg_refs(line_text, page, cursor_line_1based, dock):
    """Extract (db, layer) tuples from a single editor line with gpkg awareness.
    Returns list of (abs_db_path, layer_name) and list of warning strings.
    layer_name == '*' for USE ALL (caller expands via ogr)."""
    warnings = []
    if not line_text:
        return [], warnings

    # Strip comments
    if not _get_include_comments():
        line_text = _strip_comments(line_text)

    # Only process lines with '==' (TUFLOW command form)
    if "==" not in line_text:
        return [], warnings
    lhs, rhs = line_text.split("==", 1)
    rhs = rhs.strip()
    if not rhs:
        return [], warnings

    # Skip Spatial Database commands — handled by classic pass
    lhs_clean = lhs.strip().lower()
    if lhs_clean.startswith("spatial database"):
        return [], warnings

    # Parse the RHS
    tuples = _parse_gpkg_rhs(rhs, None)
    base_dir = os.path.dirname(page.path) if page and page.path else ""

    resolved = []
    bare_active_db = None  # lazy-resolved
    bare_db_tried = False

    for db_raw, layer in tuples:
        if db_raw:
            abs_db = _resolve_db_path(db_raw, base_dir)
        else:
            # Bare layer -> need active Spatial Database
            if not bare_db_tried:
                bare_active_db, warn = _resolve_spatial_db(dock, page, cursor_line_1based)
                bare_db_tried = True
                if warn:
                    warnings.append(warn)
            abs_db = bare_active_db

        if not abs_db:
            warnings.append("cannot resolve db for layer '%s'" % layer)
            continue
        if not abs_db.lower().endswith(".gpkg"):
            continue  # not a gpkg ref
        resolved.append((abs_db, layer))

    return resolved, warnings


def _expand_use_all(db_path):
    """Enumerate sub-layers in a gpkg via ogr. Returns list of layer names."""
    try:
        from osgeo import ogr
        ds = ogr.Open(db_path)
        if ds is None:
            return []
        names = [ds.GetLayerByIndex(i).GetName() for i in range(ds.GetLayerCount())]
        ds = None
        return names
    except Exception:
        return []


def _gpkg_has_layer(db_path, layer_name):
    """Check if layer_name exists inside a gpkg via ogr."""
    if not os.path.exists(db_path):
        return False
    try:
        from osgeo import ogr
        ds = ogr.Open(db_path)
        if ds is None:
            return False
        for i in range(ds.GetLayerCount()):
            if ds.GetLayerByIndex(i).GetName() == layer_name:
                ds = None
                return True
        ds = None
    except Exception:
        pass
    return False


def extract_gpkg_refs_resolved(line_text, page, cursor_line_1based, dock):
    """Like extract_gpkg_refs but expands USE ALL sentinel into real layer names.
    Returns (list of (db, layer), warnings)."""
    refs, warnings = extract_gpkg_refs(line_text, page, cursor_line_1based, dock)
    out = []
    for db, layer in refs:
        if layer == "*":
            names = _expand_use_all(db)
            if not names:
                warnings.append("USE ALL: cannot list layers in %s" % os.path.basename(db))
                continue
            for n in names:
                out.append((db, n))
        else:
            out.append((db, layer))
    return out, warnings


# ---------------------------------------------------------------------------
# Editor helpers
# ---------------------------------------------------------------------------
def _get_line_text(page):
    if not page:
        return ""
    editor = page.editor
    if page.editor_kind == "scintilla":
        line_num, _ = editor.getCursorPosition()
        return editor.text(line_num)
    else:
        return editor.textCursor().block().text()


def _get_cursor_line_1based(page):
    if not page:
        return 1
    editor = page.editor
    if page.editor_kind == "scintilla":
        line_num, _ = editor.getCursorPosition()
        return line_num + 1
    else:
        return editor.textCursor().blockNumber() + 1


def _get_selected_text(page):
    if not page:
        return None
    editor = page.editor
    if page.editor_kind == "scintilla":
        text = editor.selectedText()
        return text if text else None
    else:
        cursor = editor.textCursor()
        return cursor.selectedText() if cursor.hasSelection() else None


def _paths_from_context(page):
    if not page or not page.path:
        return [], False
    base_dir = os.path.dirname(page.path)
    selected = _get_selected_text(page)
    if selected:
        return extract_fuzzy_paths(selected, base_dir), True
    else:
        return extract_fuzzy_paths(_get_line_text(page), base_dir), False


def _gpkg_refs_from_context(dock, page):
    """Get gpkg (db, layer) tuples from current selection or cursor line.
    Returns (refs, warnings, from_selection)."""
    if not page:
        return [], [], False
    selected = _get_selected_text(page)
    if selected:
        # Process each non-empty line in selection
        cursor_line = _get_cursor_line_1based(page)
        all_refs = []
        all_warn = []
        for line in selected.splitlines():
            refs, warn = extract_gpkg_refs_resolved(line, page, cursor_line, dock)
            all_refs.extend(refs)
            all_warn.extend(warn)
        # Dedupe
        seen = set()
        uniq = []
        for r in all_refs:
            if r not in seen:
                seen.add(r)
                uniq.append(r)
        return uniq, all_warn, True
    else:
        cursor_line = _get_cursor_line_1based(page)
        refs, warn = extract_gpkg_refs_resolved(
            _get_line_text(page), page, cursor_line, dock)
        return refs, warn, False


def _summarise_paths(paths, ext_set):
    counts = Counter()
    for p in paths:
        ext = os.path.splitext(p)[1].lower().lstrip(".")
        if "." + ext in ext_set:
            counts[ext] += 1
    if not counts:
        return ""
    return ", ".join("%d %s" % (v, k) for k, v in sorted(counts.items()))


def _load_gis_layer(iface, abs_path):
    """Load a GIS layer. Returns the QgsMapLayer or None."""
    layer_name = os.path.basename(abs_path)
    ext = os.path.splitext(abs_path)[1].lower()
    raster_exts = {".tif", ".tiff", ".asc", ".flt", ".dem", ".nc"}
    if ext in raster_exts:
        layer = iface.addRasterLayer(abs_path, layer_name)
    else:
        layer = iface.addVectorLayer(abs_path, layer_name, "ogr")
    return layer if layer else None


def _load_gpkg_sublayer(iface, db_path, layer_name):
    """Load a specific sub-layer from a gpkg. Returns QgsMapLayer or None."""
    uri = "%s|layername=%s" % (db_path, layer_name)
    layer = iface.addVectorLayer(uri, layer_name, "ogr")
    return layer if layer else None


def _after_load_actions(iface, loaded_layers, select, flash, zoom, attrib, group):
    """Run after-action options on loaded layers via locator's _select_in_toc."""
    if not loaded_layers:
        return
    if not (select or flash or zoom or attrib or group):
        return
    _fn = None
    try:
        from .fuzzy_locator import _select_in_toc as _fn
    except ImportError:
        try:
            import importlib.util as _iu
            _p = os.path.join(os.path.dirname(__file__), "fuzzy_locator.py")
            if os.path.exists(_p):
                _s = _iu.spec_from_file_location("fuzzy_locator", _p)
                _m = _iu.module_from_spec(_s)
                _s.loader.exec_module(_m)
                _fn = _m._select_in_toc
        except Exception:
            pass
    if _fn:
        _fn(iface, loaded_layers, select=select, flash=flash,
            zoom=zoom, attrib=attrib, group=group)


def _load_multiple(iface, paths, select=False, flash=False, zoom=False,
                   attrib=False, group=False):
    gis_exts = _get_gis_exts()
    loaded_layers = []
    for p in paths:
        if os.path.splitext(p)[1].lower() in gis_exts:
            layer = _load_gis_layer(iface, p)
            if layer:
                loaded_layers.append(layer)
    _after_load_actions(iface, loaded_layers, select, flash, zoom, attrib, group)
    return len(loaded_layers)


def _load_gpkg_refs(iface, refs, select=False, flash=False, zoom=False,
                    attrib=False, group=False):
    """Load a list of (db, layer) tuples as gpkg sub-layers.
    layer==None means db-only ref (Spatial Database cmd) -> prompt user."""
    loaded_layers = []
    for db, layer in refs:
        l = _load_gpkg_sublayer(iface, db, layer)
        if l:
            loaded_layers.append(l)
    _after_load_actions(iface, loaded_layers, select, flash, zoom, attrib, group)
    return len(loaded_layers)


def _open_multiple_editor(dock, paths):
    editor_exts = _get_editor_exts()
    for p in paths:
        if os.path.splitext(p)[1].lower() in editor_exts:
            dock.new_tab(p)


def _show_in_explorer(path):
    if not path or not os.path.exists(path):
        return
    try:
        if os.name == "nt":
            subprocess.run(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Context menu builder
# ---------------------------------------------------------------------------
def _build_context_menu(dock, menu):
    page = dock.current_page()
    if not page or not page.path:
        return False

    # Read shared after-action settings
    _s = QSettings()
    _shared = "QFAT/QFAT04/addon_fuzzy/"
    opt_select = _s.value(_shared + "opt_select", True, type=bool)
    opt_flash = _s.value(_shared + "opt_flash", True, type=bool)
    opt_zoom = _s.value(_shared + "opt_zoom", False, type=bool)
    opt_attrib = _s.value(_shared + "opt_attrib", False, type=bool)
    opt_group = _s.value(_shared + "opt_group", False, type=bool)

    added = False
    gpkg_refs = []

    # --- GPKG-aware pass (opt-in) ---
    if _gpkg_enabled():
        gpkg_refs, gpkg_warnings, from_sel = _gpkg_refs_from_context(dock, page)
        if gpkg_refs:
            source = "selection" if from_sel else "this line"
            # Separate db-only refs (layer==None) from layer refs
            # db-only refs are handled by classic path-based pass below
            layer_refs = [(d, l) for d, l in gpkg_refs if l is not None]
            # Only show layers that actually exist on disk
            layer_refs = [(d, l) for d, l in layer_refs
                          if os.path.exists(d) and _gpkg_has_layer(d, l)]
            if layer_refs:
                act = menu.addAction("Load GPKG layers on %s (%d layers)"
                                     % (source, len(layer_refs)))
                act.triggered.connect(
                    lambda _=False, r=layer_refs: _load_gpkg_refs(
                        dock.iface, r, select=opt_select, flash=opt_flash,
                        zoom=opt_zoom, attrib=opt_attrib, group=opt_group))
                added = True
        for w in gpkg_warnings:
            dock.messages.append("[Fuzzy Loader] " + w)

    # --- Classic path-based pass ---
    paths, from_selection = _paths_from_context(page)
    if not paths:
        return added

    gis_exts = _get_gis_exts()
    editor_exts = _get_editor_exts()
    gis_paths = [p for p in paths if os.path.splitext(p)[1].lower() in gis_exts]
    editor_paths = [p for p in paths if os.path.splitext(p)[1].lower() in editor_exts]

    # When gpkg pass already added load items, skip .gpkg from classic pass
    if added:
        gis_paths = [p for p in gis_paths if not p.lower().endswith(".gpkg")]

    source = "selection" if from_selection else "this line"

    if gis_paths:
        summary = _summarise_paths(gis_paths, gis_exts)
        act = menu.addAction("Load GIS on %s (%s)" % (source, summary))
        act.triggered.connect(
            lambda _=False, ps=gis_paths: _load_multiple(
                dock.iface, ps, select=opt_select, flash=opt_flash,
                zoom=opt_zoom, attrib=opt_attrib, group=opt_group))
        added = True
    if editor_paths:
        summary = _summarise_paths(editor_paths, editor_exts)
        act = menu.addAction("Open files on %s (%s)" % (source, summary))
        act.triggered.connect(lambda _=False, ps=editor_paths: _open_multiple_editor(dock, ps))
        added = True
    if len(paths) == 1:
        act = menu.addAction("Show in Explorer")
        act.triggered.connect(lambda _=False, p=paths[0]: _show_in_explorer(p))
        added = True
    elif len(paths) > 1:
        exp_menu = menu.addMenu("Show in Explorer")
        for p in paths:
            act = exp_menu.addAction(os.path.basename(p))
            act.setToolTip(p)
            act.triggered.connect(lambda _=False, pp=p: _show_in_explorer(pp))
        added = True
    return added


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class FuzzyLoaderSettings(QDialog):
    def __init__(self, dock, parent=None):
        super().__init__(parent or dock)
        self.setWindowTitle("Fuzzy Loader Settings  v" + __version__)
        self.resize(500, 380)
        s = QSettings()
        layout = QVBoxLayout(self)

        gis_grp = QGroupBox("GIS layer extensions (loadable into QGIS)")
        gis_lay = QVBoxLayout(gis_grp)
        gis_lay.addWidget(QLabel("Comma-separated list of extensions (without dots):"))
        self.ed_gis = QLineEdit()
        self.ed_gis.setText(s.value(_S_GIS_EXTS, _DEFAULT_GIS_EXTS, type=str))
        self.ed_gis.setPlaceholderText(_DEFAULT_GIS_EXTS)
        gis_lay.addWidget(self.ed_gis)
        layout.addWidget(gis_grp)

        ed_grp = QGroupBox("Text file extensions (openable in editor)")
        ed_lay = QVBoxLayout(ed_grp)
        ed_lay.addWidget(QLabel("Comma-separated list of extensions (without dots):"))
        self.ed_editor = QLineEdit()
        self.ed_editor.setText(s.value(_S_EDITOR_EXTS, _DEFAULT_EDITOR_EXTS, type=str))
        self.ed_editor.setPlaceholderText(_DEFAULT_EDITOR_EXTS)
        ed_lay.addWidget(self.ed_editor)
        layout.addWidget(ed_grp)

        opt_grp = QGroupBox("Options")
        opt_lay = QVBoxLayout(opt_grp)
        self.chk_comments = QCheckBox("Include commented text when scanning for paths")
        self.chk_comments.setToolTip(
            "When off (default), text after ! on a line is ignored.\n"
            "When on, comments are also scanned for file paths.")
        self.chk_comments.setChecked(s.value(_S_INCLUDE_COMMENTS, False, type=bool))
        opt_lay.addWidget(self.chk_comments)

        self.chk_gpkg = QCheckBox("Enable GeoPackage syntax detection (TUFLOW >>, &&, |, USE ALL)")
        self.chk_gpkg.setToolTip(
            "When on, recognises TUFLOW GPKG layer syntax:\n"
            "  Read GIS Z Shape == db.gpkg >> 2d_zsh_L\n"
            "  Read GIS Z Shape == 2d_zsh_L  (uses active Spatial Database)\n"
            "  Read GIS Z Shape == db.gpkg >> USE ALL\n"
            "Also applies to Fuzzy Locator, Creator and Exporter.")
        self.chk_gpkg.setChecked(s.value(_S_GPKG_ENABLED, False, type=bool))
        opt_lay.addWidget(self.chk_gpkg)
        layout.addWidget(opt_grp)

        act_grp = QGroupBox("After loading (shared with Locator / Creator)")
        act_lay = QVBoxLayout(act_grp)
        _shared = "QFAT/QFAT04/addon_fuzzy/"
        self.chk_select = QCheckBox("Select layer in Layers Panel")
        self.chk_select.setChecked(s.value(_shared + "opt_select", True, type=bool))
        act_lay.addWidget(self.chk_select)
        self.chk_flash = QCheckBox("Flash layer in Layers Panel")
        self.chk_flash.setChecked(s.value(_shared + "opt_flash", True, type=bool))
        act_lay.addWidget(self.chk_flash)
        self.chk_zoom = QCheckBox("Zoom to layer extent")
        self.chk_zoom.setChecked(s.value(_shared + "opt_zoom", False, type=bool))
        act_lay.addWidget(self.chk_zoom)
        self.chk_attrib = QCheckBox("Open attribute table")
        self.chk_attrib.setChecked(s.value(_shared + "opt_attrib", False, type=bool))
        act_lay.addWidget(self.chk_attrib)
        self.chk_group = QCheckBox("Place in a new group")
        self.chk_group.setChecked(s.value(_shared + "opt_group", False, type=bool))
        act_lay.addWidget(self.chk_group)
        layout.addWidget(act_grp)

        dev_grp = QGroupBox("Developer")
        dev_lay = QVBoxLayout(dev_grp)
        self.chk_debug = QCheckBox("Enable debug output to Messages panel")
        self.chk_debug.setChecked(s.value(_S_DEBUG, False, type=bool))
        dev_lay.addWidget(self.chk_debug)
        layout.addWidget(dev_grp)

        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._reset_defaults)
        layout.addWidget(btn_reset)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reset_defaults(self):
        self.ed_gis.setText(_DEFAULT_GIS_EXTS)
        self.ed_editor.setText(_DEFAULT_EDITOR_EXTS)
        self.chk_comments.setChecked(False)
        self.chk_gpkg.setChecked(False)
        self.chk_select.setChecked(True)
        self.chk_flash.setChecked(True)
        self.chk_zoom.setChecked(False)
        self.chk_attrib.setChecked(False)
        self.chk_group.setChecked(False)
        self.chk_debug.setChecked(False)

    def _save_and_close(self):
        s = QSettings()
        s.setValue(_S_GIS_EXTS, self.ed_gis.text().strip())
        s.setValue(_S_EDITOR_EXTS, self.ed_editor.text().strip())
        s.setValue(_S_INCLUDE_COMMENTS, self.chk_comments.isChecked())
        s.setValue(_S_GPKG_ENABLED, self.chk_gpkg.isChecked())
        s.setValue(_S_DEBUG, self.chk_debug.isChecked())
        _shared = "QFAT/QFAT04/addon_fuzzy/"
        s.setValue(_shared + "opt_select", self.chk_select.isChecked())
        s.setValue(_shared + "opt_flash", self.chk_flash.isChecked())
        s.setValue(_shared + "opt_zoom", self.chk_zoom.isChecked())
        s.setValue(_shared + "opt_attrib", self.chk_attrib.isChecked())
        s.setValue(_shared + "opt_group", self.chk_group.isChecked())
        self.accept()


def _settings_dialog(dock):
    return FuzzyLoaderSettings(dock)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def register():
    return {
        "id": "fuzzy_loader",
        "name": "Fuzzy Loader  v" + __version__,
        "description": "Smart path extraction and file routing for TUFLOW control files. "
                       "Right-click to open text files or load GIS layers. "
                       "Optional GeoPackage syntax detection (opt-in).",
        "core": True,
        "builtin": True,
        "hooks": {
            "editor_context_builder": _build_context_menu,
            "settings_dialog": _settings_dialog,
        },
    }
