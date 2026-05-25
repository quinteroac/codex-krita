import base64
import os
import tempfile
import time

from PyQt5.QtCore import QByteArray, QBuffer, QIODevice
from PyQt5.QtGui import QImage
from krita import InfoObject, Krita


def document_context():
    doc = Krita.instance().activeDocument()
    if doc is None:
        return {"has_document": False}

    node = doc.activeNode()
    return {
        "has_document": True,
        "name": doc.name(),
        "width": doc.width(),
        "height": doc.height(),
        "color_model": doc.colorModel(),
        "color_depth": doc.colorDepth(),
        "active_node": node.name() if node is not None else None,
        "active_node_type": node.type() if node is not None else None,
    }


def export_active_context(scope):
    doc = Krita.instance().activeDocument()
    if doc is None:
        raise RuntimeError("No active Krita document.")

    suffix = ".png"
    handle = tempfile.NamedTemporaryFile(prefix="krita-codex-", suffix=suffix, delete=False)
    path = handle.name
    handle.close()

    if scope == "active_layer" and doc.activeNode() is not None:
        doc.activeNode().save(path, doc.xRes(), doc.yRes(), InfoObject())
    else:
        doc.exportImage(path, InfoObject())

    with open(path, "rb") as image_file:
        image_b64 = base64.b64encode(image_file.read()).decode("utf-8")

    return {"path": path, "image_b64": image_b64, "mime_type": "image/png"}


def export_selection_mask():
    doc = Krita.instance().activeDocument()
    if doc is None or not hasattr(doc, "selection"):
        return None

    selection = doc.selection()
    if selection is None or not hasattr(selection, "pixelData"):
        return None

    width = doc.width()
    height = doc.height()
    data = selection.pixelData(0, 0, width, height)
    if data is None:
        return None

    raw = bytes(data)
    image = QImage(raw[: width * height], width, height, width, QImage.Format_Grayscale8)

    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    encoded = base64.b64encode(bytes(buffer.data())).decode("utf-8")
    handle = tempfile.NamedTemporaryFile(prefix="krita-codex-mask-", suffix=".png", delete=False)
    path = handle.name
    handle.close()
    image.save(path, "PNG")
    return {"path": path, "image_b64": encoded, "mime_type": "image/png"}


def write_result_image(image_b64):
    data = base64.b64decode(image_b64)
    path = os.path.join(tempfile.gettempdir(), "krita-codex-result-%d.png" % int(time.time()))
    with open(path, "wb") as image_file:
        image_file.write(data)
    return path


def attach_image_to_document(path):
    app = Krita.instance()
    doc = app.activeDocument()
    if doc is None:
        new_doc = app.openDocument(path)
        if app.activeWindow() is not None:
            app.activeWindow().addView(new_doc)
        return "Opened generated image as a new document."

    root = doc.rootNode()
    if hasattr(doc, "createFileLayer"):
        layer = doc.createFileLayer("Codex - generated", path, "None")
        root.addChildNode(layer, None)
        doc.refreshProjection()
        return "Added generated image as a file layer."

    new_doc = app.openDocument(path)
    if app.activeWindow() is not None:
        app.activeWindow().addView(new_doc)
    return "Opened generated image as a new document; this Krita build did not expose createFileLayer()."
