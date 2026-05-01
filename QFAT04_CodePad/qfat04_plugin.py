import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.gui import QgsCustomDropHandler
from .qfat04_dock import QFAT04Dock

class TuflowDropHandler(QgsCustomDropHandler):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin

    def handleFileDrop(self, file_path):
        ext = os.path.splitext(file_path)[1].lower().lstrip('.')
        
        default_exts = "tcf, tgc, tmf, tef, trd, toc, ecf, bc_dbase, cmd, bat, ps1"
        raw_exts = QSettings().value("QFAT/QFAT04/drop_exts", default_exts, type=str)
        
        allowed_exts = {x.strip().lstrip('.').lower() for x in raw_exts.split(',') if x.strip()}
        
        if ext in allowed_exts:
            self.plugin.open_file_from_drop(file_path)
            return True 
            
        return False

class QFAT04Plugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.drop_handler = TuflowDropHandler(self) 

    def initGui(self):
        from qgis.PyQt.QtGui import QIcon
        icon_path = os.path.join(os.path.dirname(__file__), "codepad_icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        self.action = QAction(icon, "QFAT04 CodePad--", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dock)
        self.iface.addPluginToMenu("QFAT04", self.action)
        try:
            self.iface.addToolBarIcon(self.action)
        except Exception:
            pass
            
        self.iface.registerCustomDropHandler(self.drop_handler)

        # Defer dock creation — only build when first shown
        self._dock_initialized = False
        was_visible = QSettings().value("QFAT/QFAT04/dock_visible", True, type=bool)
        if was_visible:
            _dock_delay = int(QSettings().value("QFAT/QFAT04/delay_dock_create", 0))
            if _dock_delay > 0:
                from qgis.PyQt.QtCore import QTimer
                QTimer.singleShot(_dock_delay, self._create_dock)
                self.action.setChecked(True)
            else:
                self._create_dock()
                self.action.setChecked(True)

    def _create_dock(self):
        if self._dock_initialized:
            return
        self._dock_initialized = True
        self.dock = QFAT04Dock(self.iface)
        # Restore last docked area (default: RightDockWidgetArea)
        saved_area = QSettings().value("QFAT/QFAT04/dock_area", int(Qt.RightDockWidgetArea), type=int)
        try:
            area = Qt.DockWidgetArea(saved_area)
        except Exception:
            area = Qt.RightDockWidgetArea
        self.iface.addDockWidget(area, self.dock)
        self.dock.setVisible(True)
        self.dock.visibilityChanged.connect(self._on_visibility_changed)
        # Save dock area whenever user moves the dock
        try:
            self.dock.dockLocationChanged.connect(self._on_dock_location_changed)
        except Exception:
            pass
        # Restore docked size if available
        try:
            size = QSettings().value("QFAT/QFAT04/dock_size", None)
            if size is not None:
                self.dock.resize(size)
        except Exception:
            pass
        # Restore display mode (floating vs docked)
        try:
            mode = QSettings().value("QFAT/QFAT04/display_mode", "docked", type=str)
            if mode == "floating":
                self.dock.detach_to_window()
        except Exception:
            pass

    def _on_dock_location_changed(self, area):
        if getattr(self, "_unloading", False):
            return
        try:
            QSettings().setValue("QFAT/QFAT04/dock_area", int(area))
        except Exception:
            pass

    def _on_visibility_changed(self, visible):
        if getattr(self, "_unloading", False):
            return
        QSettings().setValue("QFAT/QFAT04/dock_visible", visible)
        if self.action:
            self.action.setChecked(visible or self.dock.is_floating_window())

    def unload(self):
        self._unloading = True
        self.iface.unregisterCustomDropHandler(self.drop_handler)
        
        if self.dock is not None:
            # Fire addon on_shutdown hooks first so they can disconnect signals
            try:
                if hasattr(self.dock, 'addon_manager'):
                    self.dock.addon_manager.fire_hook("on_shutdown")
            except Exception:
                pass
            # Save visibility
            is_visible = self.dock.isVisible() or self.dock.is_floating_window()
            QSettings().setValue("QFAT/QFAT04/dock_visible", is_visible)
            # Save docked size (only meaningful when not floating)
            try:
                if not self.dock.is_floating_window():
                    QSettings().setValue("QFAT/QFAT04/dock_size", self.dock.size())
            except Exception:
                pass
            # If floating, save geometry and reattach before destroying
            if self.dock.is_floating_window():
                try:
                    QSettings().setValue("QFAT/QFAT04/floating_geometry",
                                        self.dock._floating_window.saveGeometry())
                except Exception:
                    pass
                try:
                    self.dock.reattach_to_dock()
                except Exception:
                    pass
            try:
                self.dock.visibilityChanged.disconnect(self._on_visibility_changed)
            except Exception:
                pass
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action is not None:
            try:
                self.iface.removePluginMenu("QFAT04", self.action)
            except Exception:
                pass
            try:
                self.iface.removeToolBarIcon(self.action)
            except Exception:
                pass
            self.action.deleteLater()
            self.action = None

    def toggle_dock(self):
        if not self._dock_initialized:
            self._create_dock()
            return
        # If floating window is open, bring it forward
        if self.dock.is_floating_window():
            self.dock._floating_window.show()
            self.dock._floating_window.raise_()
            self.dock._floating_window.activateWindow()
            return
        if self.dock.isVisible():
            self.dock.hide()
        else:
            self.dock.show()
            self.dock.raise_()

    def open_file_from_drop(self, file_path):
        if not self._dock_initialized:
            self._create_dock()
        if self.dock.is_floating_window():
            self.dock._floating_window.show()
            self.dock._floating_window.raise_()
            self.dock._floating_window.activateWindow()
        elif not self.dock.isVisible():
            self.dock.show()
            self.dock.raise_()
        self.dock.open_paths([file_path])
