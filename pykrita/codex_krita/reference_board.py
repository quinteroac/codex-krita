import os

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from krita import DockWidget

from .image_bridge import (
    TRANSPARENCY_PRESERVE_ALPHA,
    attach_image_to_active_layer,
    attach_image_to_document,
)


_REFERENCE_IMAGES = []
_REFERENCE_DOCKERS = []
_PIXMAP_CACHE = {}


def add_reference_image(path, title=None):
    if not path:
        return "No image path was available for the reference panel."
    item = {"path": path, "title": title or os.path.basename(path)}
    _REFERENCE_IMAGES.append(item)
    cached_pixmap(path)
    for docker in list(_REFERENCE_DOCKERS):
        docker.add_item(item)
    if _REFERENCE_DOCKERS:
        return "Added image to the Codex reference panel."
    return "Added image to the Codex reference panel. Open Tools > Scripts > Codex References to view it."


class ReferenceBoardDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Codex References")
        self._build_ui()
        _REFERENCE_DOCKERS.append(self)
        self.refresh_items()

    def canvasChanged(self, canvas):
        pass

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        size_row = QHBoxLayout()
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(96, 160)
        self.size_slider.setSingleStep(16)
        self.size_slider.setPageStep(48)
        self.size_slider.setValue(160)
        size_row.addWidget(self.size_slider)
        layout.addLayout(size_row)

        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setIconSize(QSize(self.size_slider.value(), self.size_slider.value()))
        self.list_widget.setSpacing(8)
        layout.addWidget(self.list_widget)

        manage_row = QHBoxLayout()
        self.remove_btn = QPushButton("Remove")
        self.clear_btn = QPushButton("Clear")
        manage_row.addWidget(self.remove_btn)
        manage_row.addWidget(self.clear_btn)
        layout.addLayout(manage_row)

        send_row = QHBoxLayout()
        self.new_layer_btn = QPushButton("To New Layer")
        self.active_layer_btn = QPushButton("To Active Layer")
        send_row.addWidget(self.new_layer_btn)
        send_row.addWidget(self.active_layer_btn)
        layout.addLayout(send_row)

        self.size_slider.valueChanged.connect(self.set_thumbnail_size)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn.clicked.connect(self.clear_items)
        self.new_layer_btn.clicked.connect(self.send_to_new_layer)
        self.active_layer_btn.clicked.connect(self.send_to_active_layer)

        self.setWidget(root)

    def refresh_items(self):
        self.update_size_limit()
        self.list_widget.clear()
        for item in _REFERENCE_IMAGES:
            self.add_item(item)

    def add_item(self, item):
        self.update_size_limit()
        path = item["path"]
        title = os.path.basename(path)
        pixmap = cached_pixmap(path)
        if not pixmap.isNull():
            size = self.size_slider.value()
            pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        list_item = QListWidgetItem(QIcon(pixmap), title)
        list_item.setData(Qt.UserRole, path)
        list_item.setToolTip(path)
        self.list_widget.addItem(list_item)

    def update_size_limit(self):
        largest = 160
        for item in _REFERENCE_IMAGES:
            pixmap = cached_pixmap(item["path"])
            if pixmap.isNull():
                continue
            largest = max(largest, pixmap.width(), pixmap.height())
        blocked = self.size_slider.blockSignals(True)
        self.size_slider.setMaximum(largest)
        if self.size_slider.value() > largest:
            self.size_slider.setValue(largest)
        self.size_slider.blockSignals(blocked)

    def selected_path(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def set_thumbnail_size(self, value):
        size = QSize(value, value)
        self.list_widget.setIconSize(size)
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            path = item.data(Qt.UserRole)
            pixmap = cached_pixmap(path)
            if pixmap.isNull():
                continue
            item.setIcon(QIcon(pixmap.scaled(value, value, Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    def remove_selected(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        path = self.list_widget.item(row).data(Qt.UserRole)
        self.list_widget.takeItem(row)
        for index, item in enumerate(list(_REFERENCE_IMAGES)):
            if item["path"] == path:
                del _REFERENCE_IMAGES[index]
                break
        for docker in list(_REFERENCE_DOCKERS):
            if docker is not self:
                docker.refresh_items()

    def clear_items(self):
        _REFERENCE_IMAGES[:] = []
        _PIXMAP_CACHE.clear()
        for docker in list(_REFERENCE_DOCKERS):
            docker.refresh_items()

    def send_to_new_layer(self):
        path = self.selected_path()
        if path:
            attach_image_to_document(path, TRANSPARENCY_PRESERVE_ALPHA)

    def send_to_active_layer(self):
        path = self.selected_path()
        if path:
            attach_image_to_active_layer(path, TRANSPARENCY_PRESERVE_ALPHA)


def cached_pixmap(path):
    pixmap = _PIXMAP_CACHE.get(path)
    if pixmap is None:
        pixmap = QPixmap(path)
        _PIXMAP_CACHE[path] = pixmap
    return pixmap
