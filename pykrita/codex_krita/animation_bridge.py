from krita import Krita

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QImage
from PyQt5.QtWidgets import QApplication

from .image_bridge import (
    TRANSPARENCY_PRESERVE_ALPHA,
    attach_image_to_active_layer,
    attach_image_patch_to_document,
    export_generation_context,
    load_image_with_transparency,
    save_temp_png,
)


def animation_context(start_frame=None, end_frame=None, frame_count=None, mode=None):
    doc = Krita.instance().activeDocument()
    if doc is None:
        return {"has_document": False}

    node = doc.activeNode()
    current_time = call_or_none(doc, "currentTime")
    if current_time is None:
        current_time = call_or_none(doc, "fullClipRangeStartTime")
    return {
        "has_document": True,
        "name": doc.name(),
        "width": doc.width(),
        "height": doc.height(),
        "color_model": doc.colorModel(),
        "color_depth": doc.colorDepth(),
        "active_node": node.name() if node is not None else None,
        "active_node_type": node.type() if node is not None else None,
        "active_node_animated": bool(call_or_none(node, "animated")) if node is not None else False,
        "current_frame": current_time,
        "clip_start": call_or_none(doc, "fullClipRangeStartTime"),
        "clip_end": call_or_none(doc, "fullClipRangeEndTime"),
        "frames_per_second": call_or_none(doc, "framesPerSecond"),
        "requested_start_frame": start_frame,
        "requested_end_frame": end_frame,
        "requested_frame_count": frame_count,
        "mode": mode,
    }


def validate_frame_range(start_frame, end_frame, frame_count=None):
    start = int(start_frame)
    end = int(end_frame)
    if start < 0 or end < 0:
        raise RuntimeError("Frame numbers must be zero or greater.")
    if end < start:
        raise RuntimeError("End frame must be greater than or equal to start frame.")
    if end - start > 240:
        raise RuntimeError("Frame range is too large. Use 240 frames or fewer.")
    count = int(frame_count) if frame_count is not None else None
    if count is not None and count <= 0:
        raise RuntimeError("Frame count must be greater than zero.")
    return start, end, count


def set_document_time(frame):
    doc = Krita.instance().activeDocument()
    if doc is None:
        raise RuntimeError("No active Krita document.")
    if not hasattr(doc, "setCurrentTime"):
        raise RuntimeError("This Krita build does not expose Document.setCurrentTime().")
    doc.setCurrentTime(int(frame))
    doc.refreshProjection()
    return doc


def export_animation_references(scope, target_frame, start_frame, end_frame):
    doc = Krita.instance().activeDocument()
    if doc is None:
        raise RuntimeError("No active Krita document.")

    original_frame = call_or_none(doc, "currentTime")
    references = []
    try:
        for label, frame in reference_frames(target_frame, start_frame, end_frame):
            set_document_time(frame)
            exported = export_generation_context(scope)
            exported["label"] = label
            exported["frame"] = frame
            references.append(exported)
    finally:
        if original_frame is not None:
            set_document_time(original_frame)
    return references


def reference_frames(target_frame, start_frame, end_frame):
    target = int(target_frame)
    start = int(start_frame)
    end = int(end_frame)
    candidates = [
        ("range start", start),
        ("previous frame", max(start, target - 1)),
        ("target frame before generation", target),
        ("next frame", min(end, target + 1)),
        ("range end", end),
    ]
    seen = set()
    result = []
    for label, frame in candidates:
        if frame in seen:
            continue
        seen.add(frame)
        result.append((label, frame))
    return result[:4]


def extract_animation_sheet_frames(sheet_path, start_frame, end_frame, frame_count, transparency_mode=TRANSPARENCY_PRESERVE_ALPHA):
    image = QImage(sheet_path)
    if image.isNull():
        raise RuntimeError("Could not load the generated animation sheet.")

    count = int(frame_count)
    if count <= 0:
        raise RuntimeError("Frame count must be greater than zero.")

    cell_bounds = detect_sheet_cell_bounds(image, count)
    cell_width = image.width() // count
    if cell_width <= 0:
        raise RuntimeError("Animation sheet is too narrow for the requested frame count.")

    start = int(start_frame)
    end = int(end_frame)
    step = 0 if count == 1 else (end - start) / float(count - 1)
    frames = []
    for index in range(count):
        if cell_bounds:
            x, width = cell_bounds[index]
        else:
            x = index * cell_width
            width = cell_width
        crop = image.copy(x, 0, width, image.height())
        saved = save_temp_png(crop, "krita-codex-animation-frame-ref-")
        prepared = load_image_with_transparency(saved["path"], transparency_mode)
        if not prepared.isNull():
            saved = save_temp_png(prepared, "krita-codex-animation-frame-")
        saved["label"] = "animation sheet cell"
        saved["frame"] = int(round(start + (step * index)))
        saved["sheet_index"] = index
        frames.append(saved)
    return frames


def detect_sheet_cell_bounds(image, count):
    content_bounds = detect_horizontal_content_bounds(image)
    if content_bounds is None:
        return None

    left, right = content_bounds
    if right <= left:
        return None

    content_width = right - left + 1
    if content_width < count:
        return None

    base_width = content_width / float(count)
    bounds = []
    for index in range(count):
        x = int(round(left + (base_width * index)))
        next_x = int(round(left + (base_width * (index + 1))))
        pad = max(1, int((next_x - x) * 0.03))
        x = max(left, x - pad)
        next_x = min(right + 1, next_x + pad)
        width = max(1, next_x - x)
        bounds.append((x, width))
    return bounds


def detect_horizontal_content_bounds(image):
    sample_step_y = max(1, image.height() // 128)
    sample_step_x = max(1, image.width() // 512)
    bg = estimate_sheet_background(image)
    active_columns = []
    for x in range(0, image.width(), sample_step_x):
        active = 0
        samples = 0
        for y in range(0, image.height(), sample_step_y):
            color = image.pixelColor(x, y)
            samples += 1
            if color.alpha() > 16 and color_distance(color, bg) > 26:
                active += 1
        if samples and active / float(samples) > 0.015:
            active_columns.append(x)

    if not active_columns:
        return None

    left = max(0, min(active_columns) - sample_step_x)
    right = min(image.width() - 1, max(active_columns) + sample_step_x)
    if right - left < image.width() * 0.5:
        return None
    return left, right


def estimate_sheet_background(image):
    points = [
        (0, 0),
        (image.width() - 1, 0),
        (0, image.height() - 1),
        (image.width() - 1, image.height() - 1),
        (image.width() // 2, 0),
        (image.width() // 2, image.height() - 1),
    ]
    colors = [image.pixelColor(x, y) for x, y in points]
    red = sum(color.red() for color in colors) // len(colors)
    green = sum(color.green() for color in colors) // len(colors)
    blue = sum(color.blue() for color in colors) // len(colors)
    alpha = sum(color.alpha() for color in colors) // len(colors)
    return QColor(red, green, blue, alpha)


def color_distance(a, b):
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()) + abs(a.alpha() - b.alpha())


def normalize_image_to_document_size(path):
    doc = Krita.instance().activeDocument()
    if doc is None:
        return path
    return normalize_image_size(path, doc.width(), doc.height())


def normalize_image_size(path, width, height):
    image = QImage(path)
    if image.isNull() or image.width() == int(width) and image.height() == int(height):
        return path

    source = image.convertToFormat(QImage.Format_ARGB32)
    target_width = int(width)
    target_height = int(height)
    result = QImage(target_width, target_height, QImage.Format_ARGB32)
    result.fill(QColor(0, 0, 0, 0))

    scaled = source.scaled(target_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(result)
    painter.drawImage((target_width - scaled.width()) // 2, (target_height - scaled.height()) // 2, scaled)
    painter.end()

    saved = save_temp_png(result, "krita-codex-animation-normalized-")
    return saved["path"]


def apply_image_to_animation_frame(path, frame, destination="new_layer", transparency_mode=TRANSPARENCY_PRESERVE_ALPHA):
    doc = set_document_time(frame)
    path = normalize_image_size(path, doc.width(), doc.height())
    if destination == "active_layer":
        enable_active_layer_animation(doc)
        message = attach_image_to_active_layer(path, transparency_mode, ensure_animation_frame=True)
    else:
        message = attach_image_patch_to_document(
            path,
            0,
            0,
            transparency_mode,
            layer_name="Codex Animation - frame",
            enable_animation=True,
            ensure_animation_frame=True,
        )
    return "%s\nApplied to frame %s." % (message, int(frame))


def apply_sheet_frames_to_timeline(frame_refs, destination="new_layer", transparency_mode=TRANSPARENCY_PRESERVE_ALPHA):
    doc = Krita.instance().activeDocument()
    if doc is None:
        raise RuntimeError("No active Krita document.")
    if destination != "active_layer":
        layer = doc.createNode("Codex Animation - frames", "paintlayer")
        if hasattr(layer, "enableAnimation"):
            layer.enableAnimation()
        doc.rootNode().addChildNode(layer, None)
        if hasattr(doc, "setActiveNode"):
            doc.setActiveNode(layer)

    messages = []
    for ref in frame_refs:
        message = apply_image_to_animation_frame(
            ref["path"],
            ref["frame"],
            "active_layer",
            transparency_mode,
        )
        messages.append(message)
        QApplication.processEvents()
    return "\n".join(messages)


def enable_active_layer_animation(doc):
    node = doc.activeNode()
    if node is not None and hasattr(node, "enableAnimation") and not call_or_none(node, "animated"):
        node.enableAnimation()


def trigger_krita_action(action_name):
    action = Krita.instance().action(action_name)
    if action is None:
        return False
    action.trigger()
    return True


def call_or_none(obj, name):
    if obj is None or not hasattr(obj, name):
        return None
    value = getattr(obj, name)
    if callable(value):
        try:
            return value()
        except Exception:
            return None
    return value
