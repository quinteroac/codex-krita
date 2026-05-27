from PyQt5.QtWidgets import QDockWidget
from krita import DockWidgetFactory, DockWidgetFactoryBase, Extension, Krita

from .animation_docker import AnimationDocker
from .docker import CodexDocker
from .reference_board import ReferenceBoardDocker


class CodexExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        Krita.instance().addDockWidgetFactory(
            DockWidgetFactory("codexKritaDocker", DockWidgetFactoryBase.DockRight, CodexDocker)
        )
        Krita.instance().addDockWidgetFactory(
            DockWidgetFactory("codexKritaReferenceDocker", DockWidgetFactoryBase.DockRight, ReferenceBoardDocker)
        )
        Krita.instance().addDockWidgetFactory(
            DockWidgetFactory("codexKritaAnimationDocker", DockWidgetFactoryBase.DockRight, AnimationDocker)
        )

    def createActions(self, window):
        action = window.createAction("codexKritaShowDocker", "Codex", "tools/scripts")
        action.triggered.connect(self._show_docker)
        references_action = window.createAction("codexKritaShowReferences", "Codex References", "tools/scripts")
        references_action.triggered.connect(self._show_references)
        animation_action = window.createAction("codexKritaShowAnimation", "Codex Animation", "tools/scripts")
        animation_action.triggered.connect(self._show_animation)

    def _show_docker(self):
        window = Krita.instance().activeWindow()
        if window is None:
            return
        for dock in window.qwindow().findChildren(QDockWidget):
            if dock.windowTitle() == "Codex":
                dock.setVisible(True)
                dock.raise_()

    def _show_references(self):
        window = Krita.instance().activeWindow()
        if window is None:
            return
        for dock in window.qwindow().findChildren(QDockWidget):
            if dock.windowTitle() == "Codex References":
                dock.setVisible(True)
                dock.raise_()

    def _show_animation(self):
        window = Krita.instance().activeWindow()
        if window is None:
            return
        for dock in window.qwindow().findChildren(QDockWidget):
            if dock.windowTitle() == "Codex Animation":
                dock.setVisible(True)
                dock.raise_()


Krita.instance().addExtension(CodexExtension(Krita.instance()))
