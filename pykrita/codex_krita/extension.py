from PyQt5.QtWidgets import QDockWidget
from krita import DockWidgetFactory, DockWidgetFactoryBase, Extension, Krita

from .docker import CodexDocker


class CodexExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        factory = DockWidgetFactory("codexKritaDocker", DockWidgetFactoryBase.DockRight, CodexDocker)
        Krita.instance().addDockWidgetFactory(factory)

    def createActions(self, window):
        action = window.createAction("codexKritaShowDocker", "Codex", "tools/scripts")
        action.triggered.connect(self._show_docker)

    def _show_docker(self):
        window = Krita.instance().activeWindow()
        if window is None:
            return
        for dock in window.qwindow().findChildren(QDockWidget):
            if dock.windowTitle() == "Codex":
                dock.setVisible(True)
                dock.raise_()


Krita.instance().addExtension(CodexExtension(Krita.instance()))
