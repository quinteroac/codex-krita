import base64
import os
import tempfile
import time
from array import array

from PyQt5.QtCore import QByteArray, QBuffer, QIODevice
from PyQt5.QtGui import QColor, QImage
from krita import InfoObject, Krita


TRANSPARENCY_OPAQUE = "opaque"
TRANSPARENCY_PRESERVE_ALPHA = "preserve_alpha"
TRANSPARENCY_REMOVE_FLAT_BACKGROUND = "remove_flat_background"


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
    selection = selection_pixels()
    if selection is None:
        return None

    width, height, raw = selection
    if not raw or max(raw) == 0:
        return None

    pixels = bytearray(width * height * 4)
    for index, selected in enumerate(raw):
        offset = index * 4
        pixels[offset] = 255
        pixels[offset + 1] = 255
        pixels[offset + 2] = 255
        pixels[offset + 3] = 255 - selected

    return save_temp_argb32(pixels, width, height, "krita-codex-mask-")


def export_inpaint_masks(padding=64, feather=24):
    selection = selection_pixels()
    if selection is None:
        return None

    width, height, raw = selection
    if not raw or max(raw) == 0:
        return None

    padding = max(0, int(padding))
    feather = max(0, int(feather))
    distances = distance_to_selection(raw, width, height, padding)
    edit_pixels = bytearray(width * height * 4)
    blend_pixels = bytearray(width * height * 4)

    for index, selected in enumerate(raw):
        distance = distances[index]
        editable = 255 if distance <= padding else 0
        offset = index * 4
        edit_pixels[offset] = 255
        edit_pixels[offset + 1] = 255
        edit_pixels[offset + 2] = 255
        edit_pixels[offset + 3] = 255 - editable
        blend_pixels[offset] = 255
        blend_pixels[offset + 1] = 255
        blend_pixels[offset + 2] = 255
        blend_pixels[offset + 3] = blend_alpha(selected, distance, padding, feather)

    edit = save_temp_argb32(edit_pixels, width, height, "krita-codex-edit-mask-")
    blend = save_temp_argb32(blend_pixels, width, height, "krita-codex-blend-mask-")
    return {
        "edit_mask_path": edit["path"],
        "edit_mask_b64": edit["image_b64"],
        "blend_mask_path": blend["path"],
        "blend_mask_b64": blend["image_b64"],
        "mime_type": "image/png",
        "padding": padding,
        "feather": feather,
    }


def selection_pixels():
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
    return width, height, bytes(data)[: width * height]


def distance_to_selection(raw, width, height, max_distance):
    cap = min(65535, max(1, int(max_distance)) + 1)
    total = width * height
    distances = array("H", [cap]) * total
    for index, selected in enumerate(raw):
        if selected:
            distances[index] = 0

    for y in range(height):
        row_offset = y * width
        for x in range(width):
            index = row_offset + x
            current = distances[index]
            if current == 0:
                continue
            if x > 0:
                current = min(current, distances[index - 1] + 1)
            if y > 0:
                current = min(current, distances[index - width] + 1)
            distances[index] = min(current, cap)

    for y in range(height - 1, -1, -1):
        row_offset = y * width
        for x in range(width - 1, -1, -1):
            index = row_offset + x
            current = distances[index]
            if current == 0:
                continue
            if x + 1 < width:
                current = min(current, distances[index + 1] + 1)
            if y + 1 < height:
                current = min(current, distances[index + width] + 1)
            distances[index] = min(current, cap)

    return distances


def blend_alpha(selected, distance, padding, feather):
    if selected:
        return selected
    if padding <= 0 or distance > padding:
        return 0
    if feather <= 0:
        return 255

    solid_distance = max(0, padding - feather)
    if distance <= solid_distance:
        return 255
    return max(0, min(255, int(255 * ((padding - distance) / float(feather)))))


def save_temp_png(image, prefix):
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    encoded = base64.b64encode(bytes(buffer.data())).decode("utf-8")
    handle = tempfile.NamedTemporaryFile(prefix=prefix, suffix=".png", delete=False)
    path = handle.name
    handle.close()
    image.save(path, "PNG")
    return {"path": path, "image_b64": encoded, "mime_type": "image/png"}


def save_temp_argb32(pixels, width, height, prefix):
    data = bytes(pixels)
    image = QImage(data, width, height, width * 4, QImage.Format_ARGB32)
    return save_temp_png(image, prefix)


def write_result_image(image_b64):
    data = base64.b64decode(image_b64)
    path = os.path.join(tempfile.gettempdir(), "krita-codex-result-%d.png" % int(time.time()))
    with open(path, "wb") as image_file:
        image_file.write(data)
    return path


def clip_image_to_inpaint_mask(image_path, blend_mask_path):
    image = QImage(image_path)
    mask = QImage(blend_mask_path)
    if image.isNull() or mask.isNull():
        raise RuntimeError("Could not load the edited image or selection mask.")

    image = image.convertToFormat(QImage.Format_ARGB32)
    mask = mask.convertToFormat(QImage.Format_ARGB32)
    if image.width() != mask.width() or image.height() != mask.height():
        raise RuntimeError(
            "Edited image size %sx%s does not match selection mask size %sx%s."
            % (image.width(), image.height(), mask.width(), mask.height())
        )

    result = image.copy()
    for y in range(result.height()):
        for x in range(result.width()):
            color = result.pixelColor(x, y)
            blend = mask.pixelColor(x, y).alpha()
            color.setAlpha(int(color.alpha() * (blend / 255.0)))
            result.setPixelColor(x, y, color)

    handle = tempfile.NamedTemporaryFile(prefix="krita-codex-inpaint-", suffix=".png", delete=False)
    clipped_path = handle.name
    handle.close()
    result.save(clipped_path, "PNG")
    return clipped_path


def attach_image_to_document(path, transparency_mode=TRANSPARENCY_PRESERVE_ALPHA):
    path = prepare_image_for_transparency_mode(path, transparency_mode)
    app = Krita.instance()
    doc = app.activeDocument()
    if doc is None:
        new_doc = app.openDocument(path)
        if app.activeWindow() is not None:
            app.activeWindow().addView(new_doc)
        return "Opened generated image as a new document."

    paint_result = attach_image_as_transparent_paint_layer(doc, path, transparency_mode)
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


def attach_image_as_transparent_paint_layer(doc, path, transparency_mode=TRANSPARENCY_PRESERVE_ALPHA):
    image = load_image_with_transparency(path, transparency_mode)
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


def prepare_image_for_transparency_mode(path, transparency_mode):
    if transparency_mode == TRANSPARENCY_PRESERVE_ALPHA:
        return path

    image = load_image_with_transparency(path, transparency_mode)
    if image.isNull():
        return path

    handle = tempfile.NamedTemporaryFile(prefix="krita-codex-import-", suffix=".png", delete=False)
    prepared_path = handle.name
    handle.close()
    image.save(prepared_path, "PNG")
    return prepared_path


def load_image_with_transparency(path, transparency_mode=TRANSPARENCY_PRESERVE_ALPHA):
    image = QImage(path)
    if image.isNull():
        return image

    image = image.convertToFormat(QImage.Format_ARGB32)
    if transparency_mode == TRANSPARENCY_OPAQUE:
        return force_opaque(image)

    if transparency_mode == TRANSPARENCY_PRESERVE_ALPHA:
        return image

    if has_useful_alpha(image):
        return image

    if transparency_mode == TRANSPARENCY_REMOVE_FLAT_BACKGROUND:
        keyed = remove_flat_edge_background(image)
        if keyed is not None:
            return keyed
    return image


def force_opaque(image):
    result = image.copy()
    for y in range(result.height()):
        for x in range(result.width()):
            color = result.pixelColor(x, y)
            color.setAlpha(255)
            result.setPixelColor(x, y, color)
    return result


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

    result = remove_matching_background(image, bg)
    return result if has_useful_alpha(result) else None


def remove_matching_background(image, bg):
    width = image.width()
    height = image.height()
    result = image.copy()
    tolerance = 44
    feather = 56

    for y in range(height):
        for x in range(width):
            color = result.pixelColor(x, y)
            distance = color_distance(color, bg)
            if distance > tolerance + feather:
                continue

            if distance <= tolerance:
                color.setAlpha(0)
            else:
                alpha = int(255 * ((distance - tolerance) / float(feather)))
                color.setAlpha(max(0, min(255, alpha)))
            result.setPixelColor(x, y, color)

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
