def classFactory(iface):
    from .qfat04_plugin import QFAT04Plugin
    return QFAT04Plugin(iface)
