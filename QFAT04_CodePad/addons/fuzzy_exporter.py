"""
fuzzy_exporter.py  v0.2
Addon: Export/copy referenced GIS files to a destination folder.

v0.2: When Fuzzy Loader GPKG mode is enabled, exports only the referenced
sub-layers from GeoPackage databases (extract-only), using gdal.VectorTranslate.
Non-gpkg references still use whole-file copy as before.

Right-click a line or selection containing GIS file references,
or select layers in QGIS TOC -- export them with all sidecar files
to a chosen destination folder (supports relative paths).

Requires: fuzzy_loader addon (uses its path extraction engine).
"""
__version__ = "0.9"

import os
import shutil

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QLineEdit,
    QDialogButtonBox, QLabel, QGroupBox, QPushButton, QFileDialog,
    QMessageBox,
)
from qgis.PyQt.QtCore import QSettings
from qgis.core import QgsProject

# ---------------------------------------------------------------------------
# Import from fuzzy_loader (dependency)
# ---------------------------------------------------------------------------
try:
    from .fuzzy_loader import (_paths_from_context, _get_gis_exts,
                               _gpkg_enabled, _gpkg_refs_from_context)
    _HAS_FUZZY_LOADER = True
except ImportError:
    try:
        import sys, importlib.util
        _fl_path = os.path.join(os.path.dirname(__file__), "fuzzy_loader.py")
        _fl = sys.modules.get("fuzzy_loader")
        if _fl is None and os.path.exists(_fl_path):
            _spec = importlib.util.spec_from_file_location("fuzzy_loader", _fl_path)
            _fl = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_fl)
        _paths_from_context = _fl._paths_from_context
        _get_gis_exts = _fl._get_gis_exts
        _gpkg_enabled = _fl._gpkg_enabled
        _gpkg_refs_from_context = _fl._gpkg_refs_from_context
        _HAS_FUZZY_LOADER = True
    except Exception:
        _HAS_FUZZY_LOADER = False

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
_S_ROOT = "QFAT/QFAT04/addon_fuzzy_exporter/"
_S_LAST_DEST = _S_ROOT + "last_destination"
_S_OVERWRITE = _S_ROOT + "overwrite"
_S_OPEN_FOLDER = _S_ROOT + "open_folder_after"

_SIDECAR_SHP = [".shx", ".dbf", ".prj", ".cpg", ".shp.xml", ".sbn", ".sbx", ".qix"]
_SIDECAR_GPKG = [".gpkg-wal", ".gpkg-shm"]


# ---------------------------------------------------------------------------
# Sidecar file collection
# ---------------------------------------------------------------------------
def _collect_sidecar_files(filepath):
    base, ext = os.path.splitext(filepath)
    ext_lower = ext.lower()
    sidecars = []
    if ext_lower == ".shp":
        for sc in _SIDECAR_SHP:
            c = base + sc
            if os.path.exists(c):
                sidecars.append(c)
            cu = base + sc.upper()
            if os.path.exists(cu) and cu not in sidecars:
                sidecars.append(cu)
    elif ext_lower == ".gpkg":
        for sc in _SIDECAR_GPKG:
            c = base + ext + sc
            if os.path.exists(c):
                sidecars.append(c)
    return sidecars


def _copy_file_with_sidecars(filepath, dest_dir, overwrite=False):
    copied, skipped, errors = 0, 0, []
    all_files = [filepath] + _collect_sidecar_files(filepath)
    for src in all_files:
        dst = os.path.join(dest_dir, os.path.basename(src))
        if os.path.exists(dst) and not overwrite:
            skipped += 1
            continue
        try:
            shutil.copy2(src, dst)
            copied += 1
        except Exception as e:
            errors.append("%s: %s" % (os.path.basename(src), str(e)))
    return copied, skipped, errors


# ---------------------------------------------------------------------------
# GPKG extract-only export
# ---------------------------------------------------------------------------
def _extract_gpkg_sublayers(src_db, layer_names, dest_dir, overwrite):
    """Extract specific sub-layers from src_db into a new gpkg at dest_dir
    with the same basename. Uses gdal.VectorTranslate.
    Returns (copied_count, skipped_count, errors)."""
    copied, skipped, errors = 0, 0, []
    dst_db = os.path.join(dest_dir, os.path.basename(src_db))
    if os.path.exists(dst_db) and not overwrite:
        skipped += len(layer_names)
        return copied, skipped, errors

    # Remove dst if overwriting (VectorTranslate appends by default)
    if os.path.exists(dst_db) and overwrite:
        try:
            os.remove(dst_db)
        except Exception as e:
            errors.append("%s: cannot remove existing: %s" % (os.path.basename(dst_db), str(e)))
            return copied, skipped, errors

    try:
        from osgeo import gdal
        gdal.UseExceptions()
        opts = gdal.VectorTranslateOptions(
            format="GPKG",
            layers=layer_names,
            accessMode=None,  # create new
        )
        ds = gdal.VectorTranslate(dst_db, src_db, options=opts)
        if ds is None:
            errors.append("%s: VectorTranslate returned None" % os.path.basename(src_db))
        else:
            ds = None
            copied += len(layer_names)
    except Exception as e:
        errors.append("%s: %s" % (os.path.basename(src_db), str(e)))
    return copied, skipped, errors


def _open_folder(path):
    try:
        import subprocess
        if os.name == "nt":
            subprocess.run(["explorer", os.path.normpath(path)])
        else:
            subprocess.run(["xdg-open", path])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Export dialog
# ---------------------------------------------------------------------------
class ExportDialog(QDialog):
    """Dialog to choose destination folder and options.

    `files` = list of whole-file paths to copy.
    `gpkg_extracts` = dict {db_path: [layer, layer, ...]} for extract-only."""
    def __init__(self, files, gpkg_extracts, base_dir, parent=None):
        super().__init__(parent)
        total = len(files) + sum(len(ls) for ls in gpkg_extracts.values())
        self.setWindowTitle("Export %d item(s)" % total)
        self.resize(500, 220)
        self.files = files
        self.gpkg_extracts = gpkg_extracts
        self.base_dir = base_dir
        s = QSettings()

        layout = QVBoxLayout(self)

        # Summary
        parts = []
        if files:
            parts.append("%d whole file(s)" % len(files))
        if gpkg_extracts:
            nlayers = sum(len(ls) for ls in gpkg_extracts.values())
            parts.append("%d gpkg layer(s) from %d db(s)"
                         % (nlayers, len(gpkg_extracts)))
        layout.addWidget(QLabel("Exporting: " + ", ".join(parts)))

        dest_grp = QGroupBox("Destination")
        dest_lay = QHBoxLayout(dest_grp)
        self.ed_dest = QLineEdit()
        self.ed_dest.setText(s.value(_S_LAST_DEST, "", type=str))
        self.ed_dest.setPlaceholderText("Enter path or browse... (relative paths supported)")
        self.ed_dest.setToolTip(
            "Absolute path: C:\\export\\gis\n"
            "Relative path: ..\\exported  (relative to the active file)")
        dest_lay.addWidget(self.ed_dest)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse)
        dest_lay.addWidget(btn_browse)
        layout.addWidget(dest_grp)

        self.chk_overwrite = QCheckBox("Overwrite existing files")
        self.chk_overwrite.setChecked(s.value(_S_OVERWRITE, False, type=bool))
        layout.addWidget(self.chk_overwrite)

        self.chk_open = QCheckBox("Open destination folder after export")
        self.chk_open.setChecked(s.value(_S_OPEN_FOLDER, True, type=bool))
        layout.addWidget(self.chk_open)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Export")
        buttons.accepted.connect(self._do_export)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if folder:
            self.ed_dest.setText(folder)

    def _resolve_dest(self):
        dest = self.ed_dest.text().strip()
        if not dest:
            return None
        if not os.path.isabs(dest) and self.base_dir:
            dest = os.path.normpath(os.path.join(self.base_dir, dest))
        return dest

    def _do_export(self):
        dest = self._resolve_dest()
        if not dest:
            QMessageBox.warning(self, "Export", "Please enter a destination path.")
            return
        try:
            os.makedirs(dest, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Export", "Cannot create folder: %s" % str(e))
            return

        overwrite = self.chk_overwrite.isChecked()
        total_copied = 0
        total_skipped = 0
        all_errors = []

        # Whole-file copies
        for fp in self.files:
            if not os.path.exists(fp):
                continue
            c, s_, e = _copy_file_with_sidecars(fp, dest, overwrite)
            total_copied += c
            total_skipped += s_
            all_errors.extend(e)

        # GPKG extract-only
        for db, layer_names in self.gpkg_extracts.items():
            if not os.path.exists(db):
                continue
            c, s_, e = _extract_gpkg_sublayers(db, layer_names, dest, overwrite)
            total_copied += c
            total_skipped += s_
            all_errors.extend(e)

        s = QSettings()
        s.setValue(_S_LAST_DEST, self.ed_dest.text().strip())
        s.setValue(_S_OVERWRITE, overwrite)
        s.setValue(_S_OPEN_FOLDER, self.chk_open.isChecked())

        msg = "Exported %d items to %s" % (total_copied, dest)
        if total_skipped:
            msg += "\nSkipped %d (already exist)" % total_skipped
        if all_errors:
            msg += "\nErrors:\n" + "\n".join(all_errors)
        QMessageBox.information(self, "Export Complete", msg)

        if self.chk_open.isChecked():
            _open_folder(dest)

        self.accept()


# ---------------------------------------------------------------------------
# TOC selection -> paths
# ---------------------------------------------------------------------------
def _get_toc_selected_paths(iface):
    paths = []
    for layer in iface.layerTreeView().selectedLayers():
        source = layer.source()
        if not source:
            continue
        source_clean = source.split("|")[0]
        if os.path.exists(source_clean) and source_clean not in paths:
            paths.append(source_clean)
    return paths


# ---------------------------------------------------------------------------
# GPKG sub-layer enumeration
# ---------------------------------------------------------------------------
def _list_gpkg_layers(db_path):
    """Return set of layer names in a gpkg, or empty set on error."""
    try:
        from osgeo import ogr
        ds = ogr.Open(db_path)
        if ds is None:
            return set()
        names = {ds.GetLayerByIndex(i).GetName() for i in range(ds.GetLayerCount())}
        ds = None
        return names
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Context menu builder
# ---------------------------------------------------------------------------
def _build_context_menu(dock, menu):
    if not _HAS_FUZZY_LOADER:
        act = menu.addAction("Fuzzy Exporter: requires Fuzzy Loader addon")
        act.setEnabled(False)
        return True

    page = dock.current_page()
    base_dir = os.path.dirname(page.path) if page and page.path else ""

    # --- GPKG-aware extract collection (opt-in) ---
    gpkg_extracts = {}  # db -> list of layer names
    if _gpkg_enabled() and page and page.path:
        gpkg_refs, _warn, _from_sel = _gpkg_refs_from_context(dock, page)
        for db, layer in gpkg_refs:
            gpkg_extracts.setdefault(db, [])
            if layer not in gpkg_extracts[db]:
                gpkg_extracts[db].append(layer)

        # Filter out sub-layers that don't actually exist in the db
        for db in list(gpkg_extracts.keys()):
            if not os.path.exists(db):
                del gpkg_extracts[db]
                continue
            existing = _list_gpkg_layers(db)
            gpkg_extracts[db] = [l for l in gpkg_extracts[db] if l in existing]
            if not gpkg_extracts[db]:
                del gpkg_extracts[db]

    # --- Classic whole-file path collection ---
    editor_paths = []
    if page and page.path:
        paths, _from_sel = _paths_from_context(page)
        gis_exts = _get_gis_exts()
        editor_paths = [p for p in paths if os.path.splitext(p)[1].lower() in gis_exts]

    # When gpkg pass found extract-only layers, skip those dbs from classic
    if gpkg_extracts:
        extracted_dbs = {os.path.normcase(os.path.normpath(d)) for d in gpkg_extracts}
        editor_paths = [p for p in editor_paths
                        if os.path.normcase(os.path.normpath(p)) not in extracted_dbs]

    toc_paths = _get_toc_selected_paths(dock.iface)

    whole_files = list(dict.fromkeys(editor_paths + toc_paths))

    if not whole_files and not gpkg_extracts:
        return False

    def _show_export(files, extracts):
        dlg = ExportDialog(files, extracts, base_dir, dock)
        dlg.exec_()

    total = len(whole_files) + sum(len(ls) for ls in gpkg_extracts.values())
    if total == 1 and whole_files:
        name = os.path.basename(whole_files[0])
        act = menu.addAction('Export "%s" to...' % name)
    else:
        parts = []
        if whole_files:
            parts.append("%d file(s)" % len(whole_files))
        if gpkg_extracts:
            parts.append("%d gpkg layer(s)"
                         % sum(len(ls) for ls in gpkg_extracts.values()))
        act = menu.addAction("Export " + " + ".join(parts) + " to...")
    act.triggered.connect(
        lambda _=False, f=whole_files, g=gpkg_extracts: _show_export(f, g))

    return True


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class FuzzyExporterSettings(QDialog):
    def __init__(self, dock, parent=None):
        super().__init__(parent or dock)
        self.setWindowTitle("Fuzzy Exporter Settings  v" + __version__)
        self.resize(450, 250)
        s = QSettings()
        layout = QVBoxLayout(self)

        opt_grp = QGroupBox("Export options")
        opt_lay = QVBoxLayout(opt_grp)
        self.chk_overwrite = QCheckBox("Overwrite existing files by default")
        self.chk_overwrite.setChecked(s.value(_S_OVERWRITE, False, type=bool))
        opt_lay.addWidget(self.chk_overwrite)
        self.chk_open = QCheckBox("Open destination folder after export")
        self.chk_open.setChecked(s.value(_S_OPEN_FOLDER, True, type=bool))
        opt_lay.addWidget(self.chk_open)
        layout.addWidget(opt_grp)

        dest_grp = QGroupBox("Default destination")
        dest_lay = QVBoxLayout(dest_grp)
        dest_lay.addWidget(QLabel("Last used destination (editable):"))
        self.ed_dest = QLineEdit()
        self.ed_dest.setText(s.value(_S_LAST_DEST, "", type=str))
        self.ed_dest.setPlaceholderText("No default -- will prompt each time")
        dest_lay.addWidget(self.ed_dest)
        layout.addWidget(dest_grp)

        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._reset)
        layout.addWidget(btn_reset)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reset(self):
        self.chk_overwrite.setChecked(False)
        self.chk_open.setChecked(True)
        self.ed_dest.setText("")

    def _save(self):
        s = QSettings()
        s.setValue(_S_OVERWRITE, self.chk_overwrite.isChecked())
        s.setValue(_S_OPEN_FOLDER, self.chk_open.isChecked())
        s.setValue(_S_LAST_DEST, self.ed_dest.text().strip())
        self.accept()


def _settings_dialog(dock):
    return FuzzyExporterSettings(dock)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def register():
    return {
        "id": "fuzzy_exporter",
        "name": "Fuzzy Exporter  v" + __version__,
        "description": "Export GIS files from editor references or TOC selection. "
                       "Whole-file copy with sidecars; GPKG extract-only mode when "
                       "Fuzzy Loader GPKG detection is enabled. Requires Fuzzy Loader.",
        "core": True,
        "builtin": True,
        "hooks": {
            "editor_context_builder": _build_context_menu,
            "settings_dialog": _settings_dialog,
        },
    }
