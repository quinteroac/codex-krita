import base64
from collections import deque
import os
import tempfile
import time

from PyQt5.QtCore import QByteArray, QBuffer, QIODevice
from PyQt5.QtGui import QColor, QImage
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

    paint_result = attach_image_as_transparent_paint_layer(doc, path)
    if paint_result:
        return paint_result

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


def attach_image_as_transparent_paint_layer(doc, path):
    image = load_image_with_transparency(path)
    if image.isNull():
        return None

    if doc.colorModel() != "RGBA" or doc.colorDepth() != "U8":
        return None

    image = image.convertToFormat(QImage.Format_ARGB32)
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        return None

    packed = bytearray(width * height * 4)

    transparent_pixels = 0
    semi_transparent_pixels = 0
    for y in range(height):
        row_offset = y * width * 4
        for x in range(width):
            color = image.pixelColor(x, y)
            alpha = color.alpha()
            if alpha == 0:
                transparent_pixels += 1
            elif alpha < 255:
                semi_transparent_pixels += 1

            offset = row_offset + (x * 4)
            # Krita integer RGBA/U8 pixelData uses BGRA channel order.
            packed[offset] = color.blue()
            packed[offset + 1] = color.green()
            packed[offset + 2] = color.red()
            packed[offset + 3] = alpha

    layer = doc.createNode("Codex - generated", "paintlayer")
    layer.setOpacity(255)
    doc.rootNode().addChildNode(layer, None)
    ok = layer.setPixelData(QByteArray(bytes(packed)), 0, 0, width, height)
    doc.refreshProjection()
    if not ok:
        return None
    return (
        "Added generated image as a transparent paint layer "
        "(transparent=%s, semi=%s)." % (transparent_pixels, semi_transparent_pixels)
    )


def load_image_with_transparency(path):
    image = QImage(path)
    if image.isNull():
        return image

    image = image.convertToFormat(QImage.Format_ARGB32)
    if has_useful_alpha(image):
        return image

    keyed = remove_flat_edge_background(image)
    if keyed is not None:
        return keyed
    return image


def has_useful_alpha(image):
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        return False

    sample_step = max(1, min(width, height) // 64)
    transparent = 0
    total = 0
    for y in range(0, height, sample_step):
        for x in range(0, width, sample_step):
            total += 1
            if image.pixelColor(x, y).alpha() < 250:
                transparent += 1
    return total > 0 and transparent / total > 0.01


def remove_flat_edge_background(image):
    width = image.width()
    height = image.height()
    if width < 4 or height < 4:
        return None

    bg = estimate_background_color(image)
    if bg is None:
        return None

    result = flood_remove_background(image, bg)
    return result if has_useful_alpha(result) else None


def flood_remove_background(image, bg):
    width = image.width()
    height = image.height()
    result = image.copy()
    tolerance = 44
    feather = 56
    visited = bytearray(width * height)
    queue = deque()

    def enqueue(x, y):
        if x < 0 or y < 0 or x >= width or y >= height:
            return
        index = y * width + x
        if visited[index]:
            return
        color = result.pixelColor(x, y)
        if color_distance(color, bg) > tolerance + feather:
            return
        visited[index] = 1
        queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        color = result.pixelColor(x, y)
        distance = color_distance(color, bg)
        if distance <= tolerance:
            color.setAlpha(0)
        else:
            alpha = int(255 * ((distance - tolerance) / float(feather)))
            color.setAlpha(max(0, min(255, alpha)))
        result.setPixelColor(x, y, color)

        enqueue(x + 1, y)
        enqueue(x - 1, y)
        enqueue(x, y + 1)
        enqueue(x, y - 1)

    return result


def estimate_background_color(image):
    width = image.width()
    height = image.height()
    samples = []
    step = max(1, min(width, height) // 32)

    for x in range(0, width, step):
        samples.append(image.pixelColor(x, 0))
        samples.append(image.pixelColor(x, height - 1))
    for y in range(0, height, step):
        samples.append(image.pixelColor(0, y))
        samples.append(image.pixelColor(width - 1, y))

    if not samples:
        return None

    red = sorted(color.red() for color in samples)[len(samples) // 2]
    green = sorted(color.green() for color in samples)[len(samples) // 2]
    blue = sorted(color.blue() for color in samples)[len(samples) // 2]
    bg = QColor(red, green, blue)

    close = sum(1 for color in samples if color_distance(color, bg) <= 28)
    if close / float(len(samples)) < 0.55:
        return None
    return bg


def color_distance(a, b):
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue()))
