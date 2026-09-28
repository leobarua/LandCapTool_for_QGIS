def classFactory(iface):
    from .landcap_plugin import LandCapPlugin
    return LandCapPlugin(iface)
