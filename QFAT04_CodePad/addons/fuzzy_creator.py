"""
fuzzy_creator.py  v0.4
Addon: Create missing GIS files from TUFLOW naming conventions.

v0.4: When Fuzzy Loader GPKG mode is enabled, also detects missing GPKG
sub-layers (e.g. "db.gpkg >> 2d_zsh_L") and creates them inside the existing
(or new) database via QgsVectorFileWriter CreateOrOverwriteLayer. Also adds
a geometry prompt when the _P/_L/_R suffix is missing (previously fell back
to Polygon silently). USE ALL refs are skipped. Bare-layer refs with no
resolvable Spatial Database are warned about.

Supports: Shapefile (.shp) and GeoPackage (.gpkg).
CRS: project CRS by default, optional CRS selector prompt, EPSG:4326 fallback.
Geometry: _P -> Point, _L -> Line, _R -> Polygon (case insensitive), else prompt.
Fields: 48 schemas extracted from official TUFLOW empty templates.

Requires: fuzzy_loader addon (uses its path extraction engine).
"""
__version__ = "0.7"

import os
import re

from qgis.PyQt.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QCheckBox,
    QDialogButtonBox, QLabel, QGroupBox, QPushButton, QLineEdit,
    QInputDialog,
)
from qgis.PyQt.QtCore import QSettings
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsVectorFileWriter,
    QgsFields, QgsField, QgsWkbTypes, QgsCoordinateReferenceSystem,
)
try:
    from PyQt5.QtCore import QVariant
except ImportError:
    from qgis.PyQt.QtCore import QVariant

# ---------------------------------------------------------------------------
# Import from fuzzy_loader (dependency)
# ---------------------------------------------------------------------------
try:
    from .fuzzy_loader import (extract_fuzzy_paths, _get_gis_exts,
                               _get_editor_exts, _build_regex,
                               _get_include_comments, _strip_comments,
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
        extract_fuzzy_paths = _fl.extract_fuzzy_paths
        _get_gis_exts = _fl._get_gis_exts
        _get_editor_exts = _fl._get_editor_exts
        _build_regex = _fl._build_regex
        _get_include_comments = _fl._get_include_comments
        _strip_comments = _fl._strip_comments
        _gpkg_enabled = _fl._gpkg_enabled
        _gpkg_refs_from_context = _fl._gpkg_refs_from_context
        _HAS_FUZZY_LOADER = True
    except Exception:
        _HAS_FUZZY_LOADER = False

_S_ROOT = "QFAT/QFAT04/addon_fuzzy_creator/"
_S_USE_PROJECT_CRS = _S_ROOT + "use_project_crs"
_S_ALLOW_CRS_PROMPT = _S_ROOT + "allow_crs_prompt"
_S_LOAD_AFTER = _S_ROOT + "load_after"
_S_SELECT_AFTER = _S_ROOT + "select_after"
_S_FLASH_AFTER = _S_ROOT + "flash_after"
_S_ATTRIB_AFTER = _S_ROOT + "attrib_after"
_CREATABLE_EXTS = {".shp", ".gpkg"}

# ---------------------------------------------------------------------------
# TUFLOW field templates
# ---------------------------------------------------------------------------
_TUFLOW_TEMPLATES = {
    "0d_rl": [("Name", "C", 32, 0)],
    "1d_bc": [("Type", "C", 2, 0), ("Flags", "C", 6, 0), ("Name", "C", 50, 0), ("Descriptio", "C", 250, 0)],
    "1d_iwl": [("IWL", "N", 16, 5)],
    "1d_mh": [("ID", "C", 36, 0), ("Type", "C", 8, 0), ("Loss_Appro", "C", 4, 0), ("Ignore", "C", 1, 0), ("Invert_Lev", "N", 16, 5), ("Flow_Width", "N", 16, 5), ("Flow_Lengt", "N", 16, 5), ("ANA", "N", 16, 5), ("K_Fixed", "N", 16, 5), ("Km", "N", 16, 5), ("K_Bend_Max", "N", 16, 5), ("C_reserved", "C", 12, 0), ("N1_reserve", "N", 16, 5), ("N2_reserve", "N", 16, 5), ("N3_reserve", "N", 16, 5)],
    "1d_na": [("Source", "C", 50, 0), ("Type", "C", 2, 0), ("Flags", "C", 8, 0), ("Column_1", "C", 20, 0), ("Column_2", "C", 20, 0), ("not_used_6", "C", 20, 0), ("not_used_7", "C", 20, 0), ("not_used_8", "C", 20, 0), ("not_used_9", "C", 20, 0)],
    "1d_nd": [("ID", "C", 36, 0), ("Type", "C", 8, 0), ("Ignore", "C", 1, 0), ("Bed_Level", "N", 16, 5), ("ANA", "N", 16, 5), ("Conn_1D_2D", "C", 4, 0), ("Conn_Width", "N", 16, 5), ("R1", "N", 16, 5), ("R2", "N", 16, 5), ("R3", "N", 16, 5)],
    "1d_nwk": [("ID", "C", 36, 0), ("Type", "C", 8, 0), ("Ignore", "C", 1, 0), ("UCS", "C", 1, 0), ("Len_or_ANA", "N", 16, 5), ("n_nF_Cd", "N", 16, 5), ("US_Invert", "N", 16, 5), ("DS_Invert", "N", 16, 5), ("Form_Loss", "N", 16, 5), ("pBlockage", "N", 16, 5), ("Inlet_Type", "C", 50, 0), ("Conn_1D_2D", "C", 4, 0), ("Conn_No", "N", 8, 0), ("Width_or_D", "N", 16, 5), ("Height_or_", "N", 16, 5), ("Number_of", "N", 8, 0), ("HConF_or_W", "N", 16, 5), ("WConF_or_W", "N", 16, 5), ("EntryC_or_", "N", 16, 5), ("ExitC_or_W", "N", 16, 5)],
    "1d_nwkb": [("ID", "C", 36, 0), ("Type", "C", 8, 0), ("Ignore", "C", 1, 0), ("UCS", "C", 1, 0), ("Len_or_ANA", "N", 16, 5), ("n_nF_Cd", "N", 16, 5), ("US_Invert", "N", 16, 5), ("DS_Invert", "N", 16, 5), ("Form_Loss", "N", 16, 5), ("pBlockage", "C", 12, 0), ("Inlet_Type", "C", 50, 0), ("Conn_1D_2D", "C", 4, 0), ("Conn_No", "N", 8, 0), ("Width_or_D", "N", 16, 5), ("Height_or_", "N", 16, 5), ("Number_of", "N", 8, 0), ("HConF_or_W", "N", 16, 5), ("WConF_or_W", "N", 16, 5), ("EntryC_or_", "N", 16, 5), ("ExitC_or_W", "N", 16, 5)],
    "1d_nwke": [("ID", "C", 36, 0), ("Type", "C", 8, 0), ("Ignore", "C", 1, 0), ("UCS", "C", 1, 0), ("Len_or_ANA", "N", 16, 5), ("n_nF_Cd", "N", 16, 5), ("US_Invert", "N", 16, 5), ("DS_Invert", "N", 16, 5), ("Form_Loss", "N", 16, 5), ("pBlockage", "N", 16, 5), ("Inlet_Type", "C", 50, 0), ("Conn_1D_2D", "C", 4, 0), ("Conn_No", "N", 8, 0), ("Width_or_D", "N", 16, 5), ("Height_or_", "N", 16, 5), ("Number_of", "N", 8, 0), ("HConF_or_W", "N", 16, 5), ("WConF_or_W", "N", 16, 5), ("EntryC_or_", "N", 16, 5), ("ExitC_or_W", "N", 16, 5), ("eS1", "C", 50, 0), ("eS2", "C", 50, 0), ("eN1", "N", 16, 5), ("eN2", "N", 16, 5), ("eN3", "N", 16, 5), ("eN4", "N", 16, 5), ("eN5", "N", 16, 5), ("eN6", "N", 16, 5), ("eN7", "N", 16, 5), ("eN8", "N", 16, 5)],
    "1d_pit": [("ID", "C", 12, 0), ("Type", "C", 8, 0), ("VP_Network", "N", 8, 0), ("Inlet_Type", "C", 32, 0), ("VP_Sur_Ind", "N", 16, 5), ("VP_QMax", "N", 16, 5), ("Width", "N", 16, 5), ("Conn_2D", "C", 8, 0), ("Conn_No", "N", 8, 0), ("pBlockage", "N", 16, 5), ("Number_of", "N", 8, 0), ("Lag_Approa", "C", 8, 0), ("Lag_Value", "N", 16, 5)],
    "1d_tab": [("Source", "C", 50, 0), ("Type", "C", 2, 0), ("Flags", "C", 8, 0), ("Column_1", "C", 20, 0), ("Column_2", "C", 20, 0), ("Column_3", "C", 20, 0), ("Column_4", "C", 20, 0), ("Column_5", "C", 20, 0), ("Column_6", "C", 20, 0), ("Z_Incremen", "N", 16, 5), ("Z_Maximum", "N", 16, 5), ("Skew", "N", 16, 5)],
    "1d_wll": [("Dist_for_A", "N", 16, 5)],
    "1d_xs": [("Source", "C", 50, 0), ("Type", "C", 2, 0), ("Flags", "C", 8, 0), ("Column_1", "C", 20, 0), ("Column_2", "C", 20, 0), ("Column_3", "C", 20, 0), ("Column_4", "C", 20, 0), ("Column_5", "C", 20, 0), ("Column_6", "C", 20, 0), ("Z_Incremen", "N", 16, 5), ("Z_Maximum", "N", 16, 5), ("Skew", "N", 16, 5)],
    "2d_at": [("AT", "N", 8, 0)],
    "2d_bc": [("Type", "C", 2, 0), ("Flags", "C", 3, 0), ("Name", "C", 100, 0), ("f", "N", 16, 5), ("d", "N", 16, 5), ("td", "N", 16, 5), ("a", "N", 16, 5), ("b", "N", 16, 5)],
    "2d_bg": [("ID", "C", 32, 0), ("Options", "C", 32, 0), ("Pier_pBloc", "N", 16, 5), ("Pier_FLC", "N", 16, 5), ("Deck_Soffi", "N", 16, 5), ("Deck_Depth", "N", 16, 5), ("Deck_width", "N", 16, 5), ("Deck_pBloc", "N", 16, 5), ("Rail_Depth", "N", 16, 5), ("Rail_pBloc", "N", 16, 5), ("SuperS_FLC", "N", 16, 5), ("SuperS_IPf", "N", 16, 5), ("Notes", "C", 64, 0)],
    "2d_bg_pts": [("Deck_Soffi", "N", 16, 5), ("Deck_Depth", "N", 16, 5), ("Rail_Depth", "N", 16, 5), ("R1", "N", 16, 5), ("R2", "N", 16, 5), ("R3", "N", 16, 5)],
    "2d_code": [("Code", "N", 8, 0)],
    "2d_cwf": [("CWF", "N", 16, 5)],
    "2d_cyc": [("Time", "N", 16, 5), ("p0", "N", 16, 5), ("pn", "N", 16, 5), ("R", "N", 16, 5), ("B", "N", 16, 5), ("rho_air", "N", 16, 5), ("km", "N", 16, 5), ("ThetaMax", "N", 16, 5), ("DeltaFM", "N", 16, 5), ("bw_speed", "N", 16, 5), ("bw_dirn", "N", 16, 5)],
    "2d_fc": [("Type", "C", 2, 0), ("Invert", "N", 16, 5), ("Obvert_or_", "N", 16, 5), ("u_width_fa", "N", 16, 5), ("v_width_fa", "N", 16, 5), ("Add_form_l", "N", 16, 5), ("Mannings_n", "N", 16, 5), ("No_walls_o", "N", 16, 5), ("Blocked_si", "C", 10, 0), ("Invert_2", "C", 10, 0), ("Obvert_2", "C", 10, 0), ("Comment", "C", 250, 0)],
    "2d_fcsh": [("Invert", "N", 16, 5), ("Obvert_or_", "N", 16, 5), ("Shape_Widt", "N", 16, 5), ("Shape_Opti", "C", 20, 0), ("FC_Type", "C", 2, 0), ("pBlockage", "N", 16, 5), ("FLC_or_FLC", "N", 16, 5), ("Mannings_n", "N", 16, 5), ("BC_Width", "N", 16, 5)],
    "2d_flc": [("FLC", "N", 16, 5)],
    "2d_glo": [("Datafile", "C", 254, 0), ("Bottom_Ele", "N", 16, 5), ("Top_Elevat", "N", 16, 5), ("Increment", "N", 16, 5)],
    "2d_gw": [("Groundwate", "N", 16, 5)],
    "2d_iwl": [("IWL", "N", 16, 5)],
    "2d_lfcsh": [("Invert", "N", 16, 5), ("dZ", "N", 16, 5), ("Shape_Widt", "N", 16, 5), ("Shape_Opti", "C", 20, 0), ("L1_Obvert", "N", 16, 5), ("L1_pBlocka", "N", 16, 5), ("L1_FLC", "N", 16, 5), ("L2_Depth", "N", 16, 5), ("L2_pBlocka", "N", 16, 5), ("L2_or_L23_", "N", 16, 5), ("L3_Depth", "N", 16, 5), ("L3_pBlocka", "N", 16, 5), ("L3_FLC_or_", "N", 16, 5), ("Notes", "C", 40, 0)],
    "2d_lfcsh_pts": [("Invert", "N", 16, 5), ("L1_Obvert", "N", 16, 5), ("L2_Depth", "N", 16, 5), ("L3_Depth", "N", 16, 5)],
    "2d_loc": [("Comment", "C", 250, 0)],
    "2d_lp": [("Type", "C", 20, 0), ("Label", "C", 30, 0), ("Comment", "C", 250, 0)],
    "2d_mat": [("Material", "N", 8, 0)],
    "2d_obj": [("Trigger_Le", "N", 16, 5)],
    "2d_oz": [("Not_Used", "C", 20, 0)],
    "2d_po": [("Type", "C", 20, 0), ("Label", "C", 30, 0), ("Comment", "C", 250, 0)],
    "2d_qnl": [("Nest_Level", "N", 8, 0)],
    "2d_rec": [("Trigger_Le", "N", 16, 5)],
    "2d_rf": [("Name", "C", 100, 0), ("f1", "N", 16, 5), ("f2", "N", 16, 5)],
    "2d_sa": [("Name", "C", 100, 0)],
    "2d_sa_rf": [("Name", "C", 100, 0), ("Catchment_", "N", 16, 5), ("Rain_Gauge", "N", 16, 5), ("IL", "N", 16, 5), ("CL", "N", 16, 5)],
    "2d_sa_tr": [("Name", "C", 100, 0), ("Trigger_Ty", "C", 40, 0), ("Trigger_Lo", "C", 40, 0), ("Trigger_Va", "N", 16, 5)],
    "2d_soil": [("SoilID", "N", 8, 0)],
    "2d_vzsh": [("Z", "N", 16, 5), ("dZ", "N", 16, 5), ("Shape_Widt", "N", 16, 5), ("Shape_Opti", "C", 20, 0), ("Trigger_1", "C", 20, 0), ("Trigger_2", "C", 20, 0), ("Trigger_Va", "N", 16, 5), ("Period", "N", 16, 5), ("Restore_In", "N", 16, 5), ("Restore_Pe", "N", 16, 5)],
    "2d_wrf": [("WrF", "N", 16, 5)],
    "2d_z__": [("Elevation", "N", 16, 5)],
    "2d_zsh": [("Z", "N", 16, 5), ("dZ", "N", 16, 5), ("Shape_Widt", "N", 16, 5), ("Shape_Opti", "C", 20, 0)],
    "2d_zshr": [("Z", "N", 16, 5), ("dZ", "N", 16, 5), ("Shape_Widt", "N", 16, 5), ("Shape_Opti", "C", 20, 0), ("Route_Name", "C", 40, 0), ("Cut_Off_Ty", "C", 40, 0), ("Cut_Off_Va", "C", 80, 0)],
    "2d_ztin": [("Z", "N", 16, 5), ("dZ", "N", 16, 5)],
    "swmm_iu": [("Inlet", "C", 50, 0), ("StreetXSEC", "C", 50, 0), ("Elevation", "N", 16, 5), ("SlopePct_L", "N", 16, 5), ("Number", "N", 8, 0), ("CloggedPct", "N", 16, 5), ("Qmax", "N", 16, 5), ("aLocal", "N", 16, 5), ("wLocal", "N", 16, 5), ("Placement", "C", 10, 0), ("Conn1D_2D", "C", 10, 0), ("Conn_width", "N", 16, 5)],
}


# ---------------------------------------------------------------------------
# Geometry + schema inference
# ---------------------------------------------------------------------------
def _detect_geometry_from_name(name_no_ext):
    """Return QgsWkbTypes.* or None if no suffix match."""
    u = name_no_ext.upper()
    if u.endswith("_P"):
        return QgsWkbTypes.Point
    if u.endswith("_L"):
        return QgsWkbTypes.LineString
    if u.endswith("_R"):
        return QgsWkbTypes.Polygon
    return None


def _detect_geometry(filepath):
    base = os.path.splitext(os.path.basename(filepath))[0]
    g = _detect_geometry_from_name(base)
    return g  # may be None -- caller handles prompt


def _prompt_geometry(parent, display_name):
    """Prompt user to choose a geometry type. Returns QgsWkbTypes or None."""
    opts = ["Point", "LineString", "Polygon"]
    choice, ok = QInputDialog.getItem(
        parent, "Geometry type",
        "Cannot infer geometry for '%s' (no _P/_L/_R suffix).\n"
        "Choose geometry:" % display_name,
        opts, 2, False)
    if not ok:
        return None
    return {"Point": QgsWkbTypes.Point,
            "LineString": QgsWkbTypes.LineString,
            "Polygon": QgsWkbTypes.Polygon}[choice]


def _detect_tuflow_prefix_from_name(name_no_ext):
    n = name_no_ext.lower()
    for prefix in sorted(_TUFLOW_TEMPLATES.keys(), key=len, reverse=True):
        if n.startswith(prefix):
            return prefix
    return None


def _detect_tuflow_prefix(filepath):
    return _detect_tuflow_prefix_from_name(
        os.path.splitext(os.path.basename(filepath))[0])


def _build_fields(prefix):
    fields = QgsFields()
    template = _TUFLOW_TEMPLATES.get(prefix)
    if not template:
        fields.append(QgsField("ID", QVariant.String, "String", 100))
        return fields
    for name, dbf_type, length, decimal in template:
        if dbf_type == "C":
            fields.append(QgsField(name, QVariant.String, "String", length))
        elif dbf_type == "N":
            if decimal > 0:
                fields.append(QgsField(name, QVariant.Double, "Real", length, decimal))
            else:
                fields.append(QgsField(name, QVariant.Int, "Integer", length))
        else:
            fields.append(QgsField(name, QVariant.String, "String", length))
    return fields


def _get_crs(use_project_crs, allow_prompt):
    if use_project_crs:
        crs = QgsProject.instance().crs()
        if crs and crs.isValid():
            return crs
    if allow_prompt:
        try:
            from qgis.gui import QgsProjectionSelectionDialog
            dlg = QgsProjectionSelectionDialog()
            dlg.setWindowTitle("Select CRS for new layer")
            if dlg.exec_():
                crs = dlg.crs()
                if crs and crs.isValid():
                    return crs
        except Exception:
            pass
    return QgsCoordinateReferenceSystem("EPSG:4326")


def _create_gis_file(filepath, geom_type, fields, crs=None):
    """Create an empty Shapefile or standalone GPKG (whole-file mode)."""
    if crs is None:
        crs = QgsCoordinateReferenceSystem("EPSG:4326")
    dirpath = os.path.dirname(filepath)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)
    ext = os.path.splitext(filepath)[1].lower()
    driver = "GPKG" if ext == ".gpkg" else "ESRI Shapefile"
    writer = QgsVectorFileWriter(filepath, "UTF-8", fields, geom_type, crs, driver)
    if writer.hasError() != QgsVectorFileWriter.NoError:
        return False, writer.errorMessage()
    del writer
    return True, ""


def _create_gpkg_sublayer(db_path, layer_name, geom_type, fields, crs):
    """Create a named sub-layer inside a gpkg. Db may or may not exist.
    Uses SaveVectorOptions with CreateOrOverwriteLayer if db exists,
    CreateOrOverwriteFile if not."""
    if crs is None:
        crs = QgsCoordinateReferenceSystem("EPSG:4326")
    dirpath = os.path.dirname(db_path)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)

    # Build an in-memory layer with the schema
    geom_str = {
        QgsWkbTypes.Point: "Point",
        QgsWkbTypes.LineString: "LineString",
        QgsWkbTypes.Polygon: "Polygon",
    }.get(geom_type, "Polygon")
    mem_uri = "%s?crs=%s" % (geom_str, crs.authid() or "EPSG:4326")
    mem = QgsVectorLayer(mem_uri, "tmp", "memory")
    if not mem.isValid():
        return False, "could not create in-memory template"
    pr = mem.dataProvider()
    pr.addAttributes([fields.field(i) for i in range(fields.count())])
    mem.updateFields()

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = layer_name
    opts.fileEncoding = "UTF-8"
    if os.path.exists(db_path):
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    else:
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

    # Use the context-based writer API (v3 signature)
    try:
        transform_context = QgsProject.instance().transformContext()
        err = QgsVectorFileWriter.writeAsVectorFormatV3(
            mem, db_path, transform_context, opts)
    except AttributeError:
        # Fallback: V2 signature
        try:
            err = QgsVectorFileWriter.writeAsVectorFormatV2(
                mem, db_path, QgsProject.instance().transformContext(), opts)
        except Exception as e:
            return False, str(e)
    except Exception as e:
        return False, str(e)

    # err is typically a tuple (code, message) or just code in older APIs
    if isinstance(err, tuple):
        code = err[0]
        msg = err[1] if len(err) > 1 else ""
    else:
        code, msg = err, ""
    if code != QgsVectorFileWriter.NoError:
        return False, "writer error %s: %s" % (code, msg)
    return True, ""


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


# ---------------------------------------------------------------------------
# Post-create actions
# ---------------------------------------------------------------------------
def _post_create_actions(iface, filepath_or_uri, layer_name=None,
                         load=True, select=True, flash=True, attrib=False, group=False):
    if not load:
        return
    name = layer_name or os.path.basename(filepath_or_uri)
    layer = iface.addVectorLayer(filepath_or_uri, name, "ogr")
    if not layer or not layer.isValid():
        return
    if select or flash or group:
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
            _fn(iface, [layer], select=select, flash=flash, zoom=False,
                attrib=attrib, group=group)
            return
    if attrib:
        try:
            iface.showAttributeTable(layer)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Editor helpers
# ---------------------------------------------------------------------------
def _get_line_text(page):
    if not page:
        return ""
    e = page.editor
    if page.editor_kind == "scintilla":
        ln, _ = e.getCursorPosition()
        return e.text(ln)
    return e.textCursor().block().text()


def _get_selected_text(page):
    if not page:
        return None
    e = page.editor
    if page.editor_kind == "scintilla":
        t = e.selectedText()
        return t if t else None
    c = e.textCursor()
    return c.selectedText() if c.hasSelection() else None


def _missing_paths_from_context(page):
    """Whole-file missing-path detection (pre-existing logic)."""
    if not page or not page.path:
        return []
    base_dir = os.path.dirname(page.path)
    gis_exts = _get_gis_exts()
    sel = _get_selected_text(page)
    text = sel if sel else _get_line_text(page)
    include_comments = _get_include_comments()
    regex = _build_regex(gis_exts, _get_editor_exts(), include_comments)
    if not include_comments:
        text = _strip_comments(text)
    results = []
    for p in regex.findall(text.replace("|", "\n")):
        norm = os.path.normpath(p.strip())
        if not os.path.isabs(norm) and base_dir:
            norm = os.path.normpath(os.path.join(base_dir, norm))
        ext = os.path.splitext(norm)[1].lower()
        if ext in _CREATABLE_EXTS and not os.path.exists(norm) and norm not in results:
            results.append(norm)
    return results


def _missing_gpkg_sublayers(dock, page):
    """Return list of (db, layer) tuples for gpkg sub-layers that don't exist.
    Skips USE ALL ('*'). Warns for unresolvable bare layers."""
    refs, warnings, _from_sel = _gpkg_refs_from_context(dock, page)
    for w in warnings:
        dock.messages.append("[Fuzzy Creator] " + w)
    missing = []
    seen = set()
    for db, layer in refs:
        if layer == "*":
            continue  # skip USE ALL
        key = (os.path.normcase(os.path.normpath(db)), layer)
        if key in seen:
            continue
        seen.add(key)
        if not _gpkg_has_layer(db, layer):
            missing.append((db, layer))
    return missing


_GN = {QgsWkbTypes.Point: "Point", QgsWkbTypes.LineString: "Line", QgsWkbTypes.Polygon: "Polygon"}
_GS = {QgsWkbTypes.Point: "Pt", QgsWkbTypes.LineString: "Ln", QgsWkbTypes.Polygon: "Pg"}


# ---------------------------------------------------------------------------
# Action runners
# ---------------------------------------------------------------------------
def _do_create_whole_file(dock, fp, use_crs, allow_prompt,
                          opt_load, opt_sel, opt_flash, opt_attr, opt_group):
    gt = _detect_geometry(fp)
    if gt is None:
        gt = _prompt_geometry(dock, os.path.basename(fp))
        if gt is None:
            dock.messages.append("[Fuzzy Creator] cancelled: %s" % os.path.basename(fp))
            return
    pf = _detect_tuflow_prefix(fp)
    flds = _build_fields(pf)
    crs = _get_crs(use_crs, allow_prompt)
    ok, err = _create_gis_file(fp, gt, flds, crs)
    ext_label = "GPKG" if os.path.splitext(fp)[1].lower() == ".gpkg" else "SHP"
    if ok:
        dock.messages.append("Created %s: %s (%s, %s, %d fields, %s)" % (
            ext_label, os.path.basename(fp),
            pf or "generic", _GN.get(gt, "?"), flds.count(), crs.authid()))
        _post_create_actions(dock.iface, fp, load=opt_load,
                             select=opt_sel, flash=opt_flash,
                             attrib=opt_attr, group=opt_group)
    else:
        dock.messages.append("Failed: %s: %s" % (os.path.basename(fp), err))


def _do_create_gpkg_sublayer(dock, db, layer, use_crs, allow_prompt,
                             opt_load, opt_sel, opt_flash, opt_attr, opt_group):
    gt = _detect_geometry_from_name(layer)
    if gt is None:
        gt = _prompt_geometry(dock, layer)
        if gt is None:
            dock.messages.append("[Fuzzy Creator] cancelled: %s >> %s"
                                 % (os.path.basename(db), layer))
            return
    pf = _detect_tuflow_prefix_from_name(layer)
    flds = _build_fields(pf)
    crs = _get_crs(use_crs, allow_prompt)
    ok, err = _create_gpkg_sublayer(db, layer, gt, flds, crs)
    if ok:
        dock.messages.append("Created GPKG layer: %s >> %s (%s, %s, %d fields, %s)" % (
            os.path.basename(db), layer,
            pf or "generic", _GN.get(gt, "?"), flds.count(), crs.authid()))
        uri = "%s|layername=%s" % (db, layer)
        _post_create_actions(dock.iface, uri, layer_name=layer,
                             load=opt_load, select=opt_sel,
                             flash=opt_flash, attrib=opt_attr,
                             group=opt_group)
    else:
        dock.messages.append("Failed: %s >> %s: %s"
                             % (os.path.basename(db), layer, err))


# ---------------------------------------------------------------------------
# Context menu builder
# ---------------------------------------------------------------------------
def _build_context_menu(dock, menu):
    if not _HAS_FUZZY_LOADER:
        a = menu.addAction("Fuzzy Creator: requires Fuzzy Loader addon")
        a.setEnabled(False)
        return True
    page = dock.current_page()
    if not page or not page.path:
        return False

    s = QSettings()
    use_crs = s.value(_S_USE_PROJECT_CRS, True, type=bool)
    allow_prompt = s.value(_S_ALLOW_CRS_PROMPT, False, type=bool)
    opt_load = s.value(_S_LOAD_AFTER, True, type=bool)
    opt_sel = s.value(_S_SELECT_AFTER, True, type=bool)
    opt_flash = s.value(_S_FLASH_AFTER, True, type=bool)
    opt_attr = s.value(_S_ATTRIB_AFTER, False, type=bool)
    opt_group = s.value("QFAT/QFAT04/addon_fuzzy/opt_group", False, type=bool)

    added = False

    # --- GPKG-aware missing sub-layer detection (opt-in) ---
    gpkg_missing = []
    if _gpkg_enabled():
        gpkg_missing = _missing_gpkg_sublayers(dock, page)

    # --- Classic whole-file missing detection ---
    missing_files = _missing_paths_from_context(page)

    # If gpkg mode is on, exclude .gpkg db files from whole-file creation
    # when we're already handling them as sub-layer creations -- we don't
    # want to create an empty-schema .gpkg alongside a >> sub-layer ref.
    if gpkg_missing:
        skip_dbs = {os.path.normcase(os.path.normpath(d)) for d, _l in gpkg_missing}
        missing_files = [f for f in missing_files
                         if os.path.normcase(os.path.normpath(f)) not in skip_dbs]

    if not gpkg_missing and not missing_files:
        return False

    # --- GPKG sub-layer menu items ---
    if gpkg_missing:
        if len(gpkg_missing) == 1:
            db, layer = gpkg_missing[0]
            gt = _detect_geometry_from_name(layer)
            pf = _detect_tuflow_prefix_from_name(layer)
            geom_lbl = _GN.get(gt, "?") if gt else "prompt"
            a = menu.addAction('Create GPKG layer "%s >> %s" (%s, %s)'
                               % (os.path.basename(db), layer,
                                  pf or "generic", geom_lbl))
            a.triggered.connect(
                lambda _=False, d=db, l=layer: _do_create_gpkg_sublayer(
                    dock, d, l, use_crs, allow_prompt,
                    opt_load, opt_sel, opt_flash, opt_attr, opt_group))
        else:
            sub = menu.addMenu("Create missing GPKG layers (%d)" % len(gpkg_missing))
            for db, layer in gpkg_missing:
                gt = _detect_geometry_from_name(layer)
                pf = _detect_tuflow_prefix_from_name(layer)
                geom_lbl = _GS.get(gt, "?") if gt else "?"
                a = sub.addAction("%s >> %s (%s, %s)"
                                  % (os.path.basename(db), layer,
                                     pf or "generic", geom_lbl))
                a.triggered.connect(
                    lambda _=False, d=db, l=layer: _do_create_gpkg_sublayer(
                        dock, d, l, use_crs, allow_prompt,
                        opt_load, opt_sel, opt_flash, opt_attr, opt_group))
            sub.addSeparator()
            a_all = sub.addAction("Create all %d layers" % len(gpkg_missing))
            a_all.triggered.connect(
                lambda _=False, items=gpkg_missing[:]:
                [_do_create_gpkg_sublayer(dock, d, l, use_crs, allow_prompt,
                                          opt_load, opt_sel, opt_flash, opt_attr, opt_group)
                 for d, l in items])
        added = True

    # --- Whole-file menu items ---
    if missing_files:
        if len(missing_files) == 1:
            fp = missing_files[0]
            nm = os.path.basename(fp)
            gt = _detect_geometry(fp)
            pf = _detect_tuflow_prefix(fp)
            geom_lbl = _GN.get(gt, "?") if gt else "prompt"
            a = menu.addAction('Create "%s" (%s, %s)' % (nm, pf or "generic", geom_lbl))
            a.triggered.connect(
                lambda _=False, f=fp: _do_create_whole_file(
                    dock, f, use_crs, allow_prompt,
                    opt_load, opt_sel, opt_flash, opt_attr, opt_group))
        else:
            sub = menu.addMenu("Create missing files (%d)" % len(missing_files))
            for fp in missing_files:
                nm = os.path.basename(fp)
                gt = _detect_geometry(fp)
                pf = _detect_tuflow_prefix(fp)
                geom_lbl = _GS.get(gt, "?") if gt else "?"
                a = sub.addAction("%s (%s, %s)" % (nm, pf or "generic", geom_lbl))
                a.triggered.connect(
                    lambda _=False, f=fp: _do_create_whole_file(
                        dock, f, use_crs, allow_prompt,
                        opt_load, opt_sel, opt_flash, opt_attr, opt_group))
            sub.addSeparator()
            a_all = sub.addAction("Create all %d files" % len(missing_files))
            a_all.triggered.connect(
                lambda _=False, fps=missing_files[:]:
                [_do_create_whole_file(dock, f, use_crs, allow_prompt,
                                       opt_load, opt_sel, opt_flash, opt_attr, opt_group)
                 for f in fps])
        added = True

    return added


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class FuzzyCreatorSettings(QDialog):
    def __init__(self, dock, parent=None):
        super().__init__(parent or dock)
        self.setWindowTitle("Fuzzy Creator Settings  v" + __version__)
        self.resize(500, 380)
        s = QSettings()
        layout = QVBoxLayout(self)

        cg = QGroupBox("Coordinate Reference System")
        cl = QVBoxLayout(cg)
        self.chk_crs = QCheckBox("Use project CRS for new layers")
        self.chk_crs.setToolTip("On: use active QGIS project CRS. Off: EPSG:4326.")
        self.chk_crs.setChecked(s.value(_S_USE_PROJECT_CRS, True, type=bool))
        cl.addWidget(self.chk_crs)
        self.chk_crs_prompt = QCheckBox("Prompt to select CRS if project CRS unavailable")
        self.chk_crs_prompt.setChecked(s.value(_S_ALLOW_CRS_PROMPT, False, type=bool))
        cl.addWidget(self.chk_crs_prompt)
        layout.addWidget(cg)

        pg = QGroupBox("After creation")
        pl = QVBoxLayout(pg)
        self.chk_load = QCheckBox("Load into QGIS")
        self.chk_load.setChecked(s.value(_S_LOAD_AFTER, True, type=bool))
        pl.addWidget(self.chk_load)
        self.chk_sel = QCheckBox("Select in Layers Panel")
        self.chk_sel.setChecked(s.value(_S_SELECT_AFTER, True, type=bool))
        pl.addWidget(self.chk_sel)
        self.chk_flash = QCheckBox("Flash in Layers Panel")
        self.chk_flash.setChecked(s.value(_S_FLASH_AFTER, True, type=bool))
        pl.addWidget(self.chk_flash)
        self.chk_attr = QCheckBox("Open attribute table")
        self.chk_attr.setChecked(s.value(_S_ATTRIB_AFTER, False, type=bool))
        pl.addWidget(self.chk_attr)
        layout.addWidget(pg)

        br = QPushButton("Reset to Defaults")
        br.clicked.connect(self._reset)
        layout.addWidget(br)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _reset(self):
        self.chk_crs.setChecked(True)
        self.chk_crs_prompt.setChecked(False)
        self.chk_load.setChecked(True)
        self.chk_sel.setChecked(True)
        self.chk_flash.setChecked(True)
        self.chk_attr.setChecked(False)

    def _save(self):
        s = QSettings()
        s.setValue(_S_USE_PROJECT_CRS, self.chk_crs.isChecked())
        s.setValue(_S_ALLOW_CRS_PROMPT, self.chk_crs_prompt.isChecked())
        s.setValue(_S_LOAD_AFTER, self.chk_load.isChecked())
        s.setValue(_S_SELECT_AFTER, self.chk_sel.isChecked())
        s.setValue(_S_FLASH_AFTER, self.chk_flash.isChecked())
        s.setValue(_S_ATTRIB_AFTER, self.chk_attr.isChecked())
        self.accept()


def _settings_dialog(dock):
    return FuzzyCreatorSettings(dock)


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
def register():
    return {
        "id": "fuzzy_creator",
        "name": "Fuzzy Creator  v" + __version__,
        "description": "Create missing TUFLOW GIS files from editor references. "
                       "48 official templates, auto geometry detection, geometry prompt "
                       "for ambiguous names. Creates GPKG sub-layers when Fuzzy Loader "
                       "GPKG detection is enabled. Requires Fuzzy Loader.",
        "core": True,
        "builtin": True,
        "hooks": {
            "editor_context_builder": _build_context_menu,
            "settings_dialog": _settings_dialog,
        },
    }
