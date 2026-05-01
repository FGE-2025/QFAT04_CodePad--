"""
fuzzy_locator.py  v0.2
Addon: Locate layers in QGIS Layers Panel (TOC) from file paths in the editor.

v0.2: Added optional GeoPackage sub-layer matching (opt-in via Fuzzy Loader
settings). When enabled, matches layers by (db, layername) tuple instead
of just file path, so the right sub-layer is highlighted.

Right-click a line or selection containing a GIS file reference -- this addon
finds the matching layer(s) in the QGIS Layer Tree and selects/highlights them.
Optionally zooms to the layer extent.

Requires: fuzzy_loader addon (uses its path extraction engine).
"""
__version__ = "2.3"

import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QCheckBox,
    QDialogButtonBox, QLabel, QGroupBox, QPushButton, QMessageBox,
)
from qgis.PyQt.QtCore import QSettings
from qgis.core import QgsProject

# ---------------------------------------------------------------------------
# Import from fuzzy_loader (dependency)
# ---------------------------------------------------------------------------
try:
    from .fuzzy_loader import (_paths_from_context, _get_gis_exts,
                               _gpkg_enabled, _gpkg_refs_from_context,
                               _debug_enabled)
    _HAS_FUZZY_LOADER = True
except ImportError:
    try:
        import sys, importlib.util
        _fl = sys.modules.get("fuzzy_loader")
        if _fl is None:
            _fl_path = os.path.join(os.path.dirname(__file__), "fuzzy_loader.py")
            if os.path.exists(_fl_path):
                _spec = importlib.util.spec_from_file_location("fuzzy_loader", _fl_path)
                _fl = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_fl)
        _paths_from_context = _fl._paths_from_context
        _get_gis_exts = _fl._get_gis_exts
        _gpkg_enabled = _fl._gpkg_enabled
        _gpkg_refs_from_context = _fl._gpkg_refs_from_context
        _debug_enabled = _fl._debug_enabled
        _HAS_FUZZY_LOADER = True
    except Exception:
        _HAS_FUZZY_LOADER = False


# ---------------------------------------------------------------------------
# Settings keys (locator-specific)
# ---------------------------------------------------------------------------
_S_ROOT = "QFAT/QFAT04/addon_fuzzy/"
_S_GIS_EXTS = _S_ROOT + "gis_extensions"
_S_EDITOR_EXTS = _S_ROOT + "editor_extensions"
_S_INCLUDE_COMMENTS = _S_ROOT + "include_comments"
_DEFAULT_GIS_EXTS = "shp,asc,flt,gpkg,mif,mid,tif"
_DEFAULT_EDITOR_EXTS = "tgc,tcf,tbc,tef,tmf,trd,toc,toz,ecf,qcf,txt,bat,cmd,ps1"


# ---------------------------------------------------------------------------
# TOC matching
# ---------------------------------------------------------------------------
def _normalise(path):
    """Normalise path for comparison."""
    return os.path.normcase(os.path.normpath(path))


def _parse_source(source):
    """Parse a QGIS layer source string into (file_path, layername_or_None).
    GPKG example: 'C:/db.gpkg|layername=2d_zsh_L|other=...'"""
    if not source:
        return "", None
    parts = source.split("|")
    file_path = parts[0]
    layer_name = None
    for part in parts[1:]:
        if part.lower().startswith("layername="):
            layer_name = part[len("layername="):]
            break
    return file_path, layer_name


def _find_layers_by_source(target_path):
    """Find all layers in QGIS TOC whose source file path matches target_path.
    Does NOT filter by sub-layer."""
    target = _normalise(target_path)
    matches = []
    for layer in QgsProject.instance().mapLayers().values():
        fp, _ = _parse_source(layer.source())
        if _normalise(fp) == target:
            matches.append(layer)
    return matches


def _find_layers_by_gpkg_ref(db_path, layer_name):
    """Find layers in TOC matching (db, sub-layer name)."""
    target_db = _normalise(db_path)
    matches = []
    for layer in QgsProject.instance().mapLayers().values():
        fp, ln = _parse_source(layer.source())
        if _normalise(fp) != target_db:
            continue
        # GPKG layer in TOC may not have explicit layername= if source is
        # exactly the .gpkg file with a single table matching the name.
        if ln is None:
            # fall back: compare layer's name() or dataProvider subLayers()
            try:
                if layer.name() == layer_name:
                    matches.append(layer)
                    continue
            except Exception:
                pass
        elif ln == layer_name:
            matches.append(layer)
    return matches


# ---------------------------------------------------------------------------
# Locate actions
# ---------------------------------------------------------------------------
def _select_in_toc(iface, layers, select=True, flash=True, zoom=False, attrib=False, group=False):
    """Locate layers in TOC with optional select, flash in TOC, zoom,
    open attribute table, place in new group."""
    tree_view = iface.layerTreeView()
    if not tree_view:
        return 0
    model = tree_view.layerTreeModel()
    root = QgsProject.instance().layerTreeRoot()

    indices = []
    for layer in layers:
        node = root.findLayer(layer.id())
        if node:
            src_idx = model.node2index(node)
            # Map through proxy model if the view uses one
            proxy = tree_view.model()
            if proxy != model and src_idx.isValid():
                idx = proxy.mapFromSource(src_idx) if hasattr(proxy, 'mapFromSource') else src_idx
            else:
                idx = src_idx
            if idx.isValid():
                indices.append((layer, node, idx))
    if not indices:
        return 0

    # Place in new group (move layers into a QGIS default-named group)
    if group:
        # Name group after first layer's source file basename
        first_layer = indices[0][0]
        src = first_layer.source().split("|")[0]
        grp_name = os.path.splitext(os.path.basename(src))[0] if src else "Group"

        # Insert group at same position as first matched layer
        first_node = indices[0][1]
        first_parent = first_node.parent() or root
        pos = 0
        for i in range(len(first_parent.children())):
            if first_parent.children()[i] == first_node:
                pos = i
                break
        grp = first_parent.insertGroup(pos, grp_name)

        # Move existing nodes into group (preserves layer registry entry)
        for layer, node, _idx in indices:
            parent = node.parent()
            if parent:
                cloned = node.clone()
                grp.addChildNode(cloned)
                parent.removeChildNode(node)

        # Re-resolve indices after move
        indices = []
        for layer in layers:
            node = root.findLayer(layer.id())
            if node:
                src_idx = model.node2index(node)
                if proxy != model and src_idx.isValid():
                    idx = proxy.mapFromSource(src_idx) if hasattr(proxy, 'mapFromSource') else src_idx
                else:
                    idx = src_idx
                if idx.isValid():
                    indices.append((layer, node, idx))
        if not indices:
            return 0

    tree_view.scrollTo(indices[0][2])

    if select:
        from qgis.PyQt.QtCore import QItemSelectionModel
        sel_model = tree_view.selectionModel()
        sel_model.clearSelection()
        for i, (_layer, _node, idx) in enumerate(indices):
            if i == 0:
                # First layer: ClearAndSelect to set it as active
                sel_model.select(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
                sel_model.setCurrentIndex(idx, QItemSelectionModel.Current)
            else:
                # Additional layers: add to selection
                sel_model.select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        # Give focus to Layers Panel so selection shows blue
        # Delay slightly so it fires after the context menu releases focus
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(50, tree_view.setFocus)

    if flash:
        from qgis.PyQt.QtCore import QTimer
        flash_nodes = [(node, node.itemVisibilityChecked()) for _l, node, _i in indices]

        def _do_flash(count=[0]):
            for node, _orig in flash_nodes:
                node.setItemVisibilityChecked(not node.itemVisibilityChecked())
            count[0] += 1
            if count[0] < 6:
                QTimer.singleShot(150, _do_flash)
            else:
                for node, orig in flash_nodes:
                    node.setItemVisibilityChecked(orig)

        QTimer.singleShot(100, _do_flash)

    if zoom and layers:
        from qgis.core import QgsRectangle
        extent = QgsRectangle()
        for layer in layers:
            if layer.extent() and not layer.extent().isNull():
                extent.combineExtentWith(layer.extent())
        if not extent.isNull():
            canvas = iface.mapCanvas()
            try:
                from qgis.core import QgsCoordinateTransform
                ct = QgsCoordinateTransform(
                    layers[0].crs(), canvas.mapSettings().destinationCrs(),
                    QgsProject.instance())
                extent = ct.transformBoundingBox(extent)
            except Exception:
                pass
            extent.scale(1.1)
            canvas.setExtent(extent)
            canvas.refresh()

    if attrib:
        for layer in layers:
            try:
                iface.showAttributeTable(layer)
            except Exception:
                pass
    return len(indices)


# ---------------------------------------------------------------------------
# Context menu builder
# ---------------------------------------------------------------------------
def _build_context_menu(dock, menu):
    if not _HAS_FUZZY_LOADER:
        act = menu.addAction("Fuzzy Locator: requires Fuzzy Loader addon")
        act.setEnabled(False)
        return True
    page = dock.current_page()
    if not page or not page.path:
        return False

    s = QSettings()
    opt_select = s.value(_S_ROOT + "opt_select", True, type=bool)
    opt_flash = s.value(_S_ROOT + "opt_flash", True, type=bool)
    opt_zoom = s.value(_S_ROOT + "opt_zoom", False, type=bool)
    opt_attrib = s.value(_S_ROOT + "opt_attrib", False, type=bool)
    opt_group = s.value(_S_ROOT + "opt_group", False, type=bool)

    def _do_locate(layers_list):
        _select_in_toc(dock.iface, layers_list,
                       select=opt_select, flash=opt_flash,
                       zoom=opt_zoom, attrib=opt_attrib,
                       group=opt_group)

    added = False
    gpkg_refs = []
    _dbg = _debug_enabled()

    # --- GPKG-aware pass (opt-in) ---
    if _gpkg_enabled():
        gpkg_refs, _warn, from_sel = _gpkg_refs_from_context(dock, page)
        if _dbg:
            dock.messages.append("[Locator] gpkg_refs: %s" % repr(gpkg_refs))
        # gpkg pass only handles layer refs (Spatial Database lines skipped by parser)
        if gpkg_refs:
            found = {}  # key: (db, layer) -> list of QgsMapLayer
            for db, layer in gpkg_refs:
                matches = _find_layers_by_gpkg_ref(db, layer)
                if matches:
                    found[(db, layer)] = matches

            if found:
                if len(found) == 1:
                    (db, layer), layers = next(iter(found.items()))
                    label = '%s >> %s' % (os.path.basename(db), layer)
                    act = menu.addAction('Locate "%s" in Layers Panel' % label)
                    act.triggered.connect(lambda _=False, ls=layers: _do_locate(ls))
                else:
                    source = "selection" if from_sel else "this line"
                    sub = menu.addMenu("Locate GPKG layers in Layers Panel (%d on %s)"
                                       % (len(found), source))
                    for (db, layer), layers in found.items():
                        label = '%s >> %s' % (os.path.basename(db), layer)
                        act = sub.addAction(label)
                        act.setToolTip("%s >> %s" % (db, layer))
                        act.triggered.connect(lambda _=False, ls=layers: _do_locate(ls))
                    sub.addSeparator()
                    all_layers = [l for ls in found.values() for l in ls]
                    act_all = sub.addAction("Locate all %d layers" % len(all_layers))
                    act_all.triggered.connect(lambda _=False, ls=all_layers: _do_locate(ls))
                added = True

    # --- Classic path-based pass ---
    paths, from_selection = _paths_from_context(page)
    if _dbg:
        dock.messages.append("[Locator] classic paths: %s" % paths)
    if not paths:
        return added
    gis_exts = _get_gis_exts()
    gis_paths = [p for p in paths if os.path.splitext(p)[1].lower() in gis_exts]

    # When gpkg pass already added locate items, skip .gpkg from classic pass
    # to avoid duplicates. Otherwise keep .gpkg for classic handling.
    if added:
        gis_paths = [p for p in gis_paths if not p.lower().endswith(".gpkg")]

    if _dbg:
        dock.messages.append("[Locator] gis_paths: %d, added=%s" % (len(gis_paths), added))

    if not gis_paths:
        return added

    found = {}
    for p in gis_paths:
        layers = _find_layers_by_source(p)
        if _dbg:
            dock.messages.append("[Locator] %s -> %d TOC matches" % (os.path.basename(p), len(layers)))
        if layers:
            found[p] = layers
    if not found:
        return added

    if len(found) == 1:
        path, layers = next(iter(found.items()))
        name = os.path.basename(path)
        act = menu.addAction('Locate "%s" in Layers Panel' % name)
        act.triggered.connect(lambda _=False, ls=layers: _do_locate(ls))
    else:
        source = "selection" if from_selection else "this line"
        sub = menu.addMenu("Locate in Layers Panel (%d on %s)" % (len(found), source))
        for path, layers in found.items():
            name = os.path.basename(path)
            act = sub.addAction(name)
            act.setToolTip(path)
            act.triggered.connect(lambda _=False, ls=layers: _do_locate(ls))
        sub.addSeparator()
        all_layers = [l for ls in found.values() for l in ls]
        act_all = sub.addAction("Locate all %d layers" % len(all_layers))
        act_all.triggered.connect(lambda _=False, ls=all_layers: _do_locate(ls))
    return True


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class FuzzyLocatorSettings(QDialog):
    def __init__(self, dock, parent=None):
        super().__init__(parent or dock)
        self.setWindowTitle("Fuzzy Locator Settings  v" + __version__)
        self.resize(500, 420)
        s = QSettings()
        layout = QVBoxLayout(self)

        gis_grp = QGroupBox("GIS layer extensions (locatable in Layers Panel)")
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

        opt_grp = QGroupBox("Locate actions (what happens when you click Locate)")
        opt_lay = QVBoxLayout(opt_grp)
        self.chk_select = QCheckBox("Select layer in Layers Panel")
        self.chk_select.setChecked(s.value(_S_ROOT + "opt_select", True, type=bool))
        opt_lay.addWidget(self.chk_select)
        self.chk_flash = QCheckBox("Flash layer in Layers Panel")
        self.chk_flash.setChecked(s.value(_S_ROOT + "opt_flash", True, type=bool))
        opt_lay.addWidget(self.chk_flash)
        self.chk_zoom = QCheckBox("Zoom to layer extent")
        self.chk_zoom.setChecked(s.value(_S_ROOT + "opt_zoom", False, type=bool))
        opt_lay.addWidget(self.chk_zoom)
        self.chk_attrib = QCheckBox("Open attribute table")
        self.chk_attrib.setChecked(s.value(_S_ROOT + "opt_attrib", False, type=bool))
        opt_lay.addWidget(self.chk_attrib)
        self.chk_group = QCheckBox("Place in a new group")
        self.chk_group.setChecked(s.value(_S_ROOT + "opt_group", False, type=bool))
        opt_lay.addWidget(self.chk_group)
        layout.addWidget(opt_grp)

        scan_grp = QGroupBox("Scanning options")
        scan_lay = QVBoxLayout(scan_grp)
        self.chk_comments = QCheckBox("Include commented text when scanning for paths")
        self.chk_comments.setChecked(s.value(_S_INCLUDE_COMMENTS, False, type=bool))
        scan_lay.addWidget(self.chk_comments)
        layout.addWidget(scan_grp)

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
        self.chk_select.setChecked(True)
        self.chk_flash.setChecked(True)
        self.chk_zoom.setChecked(False)
        self.chk_attrib.setChecked(False)
        self.chk_group.setChecked(False)
        self.chk_comments.setChecked(False)

    def _save_and_close(self):
        s = QSettings()
        s.setValue(_S_GIS_EXTS, self.ed_gis.text().strip())
        s.setValue(_S_EDITOR_EXTS, self.ed_editor.text().strip())
        s.setValue(_S_INCLUDE_COMMENTS, self.chk_comments.isChecked())
        s.setValue(_S_ROOT + "opt_select", self.chk_select.isChecked())
        s.setValue(_S_ROOT + "opt_flash", self.chk_flash.isChecked())
        s.setValue(_S_ROOT + "opt_zoom", self.chk_zoom.isChecked())
        s.setValue(_S_ROOT + "opt_attrib", self.chk_attrib.isChecked())
        s.setValue(_S_ROOT + "opt_group", self.chk_group.isChecked())
        self.accept()


def _settings_dialog(dock):
    return FuzzyLocatorSettings(dock)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def register():
    return {
        "id": "fuzzy_locator",
        "name": "Fuzzy Locator  v" + __version__,
        "description": "Locate GIS layers in QGIS Layers Panel from file references in the editor. "
                       "Supports GPKG sub-layer matching when enabled in Fuzzy Loader settings. "
                       "Requires Fuzzy Loader addon.",
        "core": True,
        "builtin": True,
        "hooks": {
            "editor_context_builder": _build_context_menu,
            "settings_dialog": _settings_dialog,
        },
    }
