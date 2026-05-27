from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from krita import DockWidget

from .animation_bridge import (
    animation_context,
    apply_sheet_frames_to_timeline,
    export_animation_references,
    extract_animation_sheet_frames,
    set_document_time,
    validate_frame_range,
)
from .client import CodexDirectClient
from .image_bridge import (
    TRANSPARENCY_OPAQUE,
    TRANSPARENCY_PRESERVE_ALPHA,
    TRANSPARENCY_REMOVE_FLAT_BACKGROUND,
    attach_image_patch_to_document,
    document_context,
)
from .worker import RpcWorker


class AnimationDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Codex Animation")
        self.client = CodexDirectClient()
        self.worker = None
        self.pending_plan = None
        self.animation_sheet_path = None
        self.sheet_frame_refs = []
        self._build_ui()

    def canvasChanged(self, canvas):
        self.refresh_context()

    def _build_ui(self):
        root = QWidget()
        root.setMinimumSize(0, 0)
        root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self.setMinimumSize(0, 0)
        layout = QVBoxLayout(root)

        self.status = QLabel("Animation mode: plan and generate frames for the active Krita timeline.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("Storyboard", "storyboard")
        self.mode.addItem("Inbetweens", "inbetweens")
        self.mode.addItem("Loop", "loop")
        self.mode.addItem("Cleanup", "cleanup")

        self.start_frame = QSpinBox()
        self.start_frame.setRange(0, 100000)
        self.end_frame = QSpinBox()
        self.end_frame.setRange(0, 100000)
        self.end_frame.setValue(12)
        self.frame_count = QSpinBox()
        self.frame_count.setRange(1, 240)
        self.frame_count.setValue(4)
        self.target_frame = QSpinBox()
        self.target_frame.setRange(0, 100000)

        self.reference_scope = QComboBox()
        self.reference_scope.addItems(["document", "active_layer", "selection"])

        self.output_destination = QComboBox()
        self.output_destination.addItem("New layer", "new_layer")
        self.output_destination.addItem("Active layer", "active_layer")

        self.transparency = QComboBox()
        self.transparency.addItem("Transparent cutout", TRANSPARENCY_REMOVE_FLAT_BACKGROUND)
        self.transparency.addItem("Preserve PNG alpha", TRANSPARENCY_PRESERVE_ALPHA)
        self.transparency.addItem("Opaque", TRANSPARENCY_OPAQUE)

        self.quality = QComboBox()
        self.quality.addItems(["medium", "high", "low"])

        form.addRow("Mode", self.mode)
        form.addRow("Start frame", self.start_frame)
        form.addRow("End frame", self.end_frame)
        form.addRow("Frame count", self.frame_count)
        form.addRow("Target frame", self.target_frame)
        form.addRow("Reference", self.reference_scope)
        form.addRow("Apply output", self.output_destination)
        form.addRow("Transparency", self.transparency)
        form.addRow("Quality", self.quality)
        layout.addLayout(form)

        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("Describe the motion, timing, character action, loop, cleanup, or storyboard beat.")
        self.prompt.setMinimumHeight(56)
        self.prompt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        layout.addWidget(self.prompt)

        button_row = QHBoxLayout()
        self.plan_btn = QPushButton("Plan + Sheet")
        self.generate_btn = QPushButton("Regenerate Sheet")
        self.apply_btn = QPushButton("Reapply Sheet")
        self.apply_btn.setEnabled(False)
        button_row.addWidget(self.plan_btn)
        button_row.addWidget(self.generate_btn)
        button_row.addWidget(self.apply_btn)
        layout.addLayout(button_row)

        frame_row = QHBoxLayout()
        self.goto_start_btn = QPushButton("Go Start")
        self.goto_target_btn = QPushButton("Go Target")
        self.goto_end_btn = QPushButton("Go End")
        frame_row.addWidget(self.goto_start_btn)
        frame_row.addWidget(self.goto_target_btn)
        frame_row.addWidget(self.goto_end_btn)
        layout.addLayout(frame_row)

        self.plan_preview = QTextEdit()
        self.plan_preview.setPlaceholderText("Animation plan appears here.")
        self.plan_preview.setMinimumHeight(72)
        self.plan_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        layout.addWidget(self.plan_preview)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(56)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        layout.addWidget(self.log)

        self.plan_btn.clicked.connect(self.plan_animation)
        self.generate_btn.clicked.connect(self.generate_animation_sheet)
        self.apply_btn.clicked.connect(self.apply_to_timeline)
        self.goto_start_btn.clicked.connect(lambda: self.go_to_frame(self.start_frame.value()))
        self.goto_target_btn.clicked.connect(lambda: self.go_to_frame(self.target_frame.value()))
        self.goto_end_btn.clicked.connect(lambda: self.go_to_frame(self.end_frame.value()))

        self.setWidget(root)
        self.refresh_context()

    def refresh_context(self):
        context = animation_context(
            self.start_frame.value() if hasattr(self, "start_frame") else None,
            self.end_frame.value() if hasattr(self, "end_frame") else None,
            self.frame_count.value() if hasattr(self, "frame_count") else None,
            self.mode.currentData() if hasattr(self, "mode") else None,
        )
        if context.get("has_document"):
            self.status.setText(
                "%s - %sx%s - frame: %s - active: %s"
                % (
                    context["name"],
                    context["width"],
                    context["height"],
                    context.get("current_frame"),
                    context.get("active_node"),
                )
            )
        else:
            self.status.setText("No active document. Open a Krita document to use animation tools.")

    def prompt_text(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            raise RuntimeError("Prompt is empty.")
        return text

    def selected_transparency_mode(self):
        return self.transparency.currentData()

    def selected_output_destination(self):
        return self.output_destination.currentData()

    def set_busy(self, busy):
        for button in (
            self.plan_btn,
            self.generate_btn,
            self.goto_start_btn,
            self.goto_target_btn,
            self.goto_end_btn,
        ):
            button.setEnabled(not busy)
        self.apply_btn.setEnabled((not busy) and bool(self.sheet_frame_refs))
        self.status.setText("Working..." if busy else "Ready")

    def call_worker(self, method, params, callback):
        self.set_busy(True)
        self.worker = RpcWorker(self.client, method, params, self, quiet_activity=True)
        self.worker.activity.connect(self._worker_activity)
        self.worker.finished.connect(lambda result: self._worker_done(result, callback))
        self.worker.failed.connect(self._worker_failed)
        self.worker.start()

    def _worker_activity(self, message):
        self.append_log(message)

    def _worker_done(self, result, callback):
        self.set_busy(False)
        callback(result)
        self.refresh_context()

    def _worker_failed(self, message):
        self.set_busy(False)
        self.append_log("Error: %s" % message)
        self.refresh_context()

    def append_log(self, text):
        self.log.append(text)

    def plan_animation(self):
        try:
            start, end, count = validate_frame_range(
                self.start_frame.value(),
                self.end_frame.value(),
                self.frame_count.value(),
            )
            self.call_worker(
                "propose_animation_plan",
                {
                    "task": self.prompt_text(),
                    "document_context": document_context(),
                    "animation_context": animation_context(start, end, count, self.mode.currentData()),
                },
                self._set_pending_plan,
            )
        except Exception as exc:
            self.append_log("Error: %s" % exc)

    def _set_pending_plan(self, result):
        self.pending_plan = result
        plan_text = result.get("plan_text") or result.get("text") or ""
        self.plan_preview.setPlainText(plan_text)
        self.append_log("Animation plan ready.")
        self.generate_animation_sheet()

    def generate_animation_sheet(self):
        try:
            start, end, count = validate_frame_range(
                self.start_frame.value(),
                self.end_frame.value(),
                self.frame_count.value(),
            )
            references = export_animation_references(
                self.reference_scope.currentText(),
                self.start_frame.value(),
                start,
                end,
            )
            self.call_worker(
                "generate_animation_sheet",
                {
                    "prompt": self.prompt_text(),
                    "plan_text": self.plan_preview.toPlainText().strip(),
                    "mode": self.mode.currentData(),
                    "start_frame": start,
                    "end_frame": end,
                    "frame_count": count,
                    "quality": self.quality.currentText(),
                    "transparency_mode": self.selected_transparency_mode(),
                    "image_path": references[0]["path"] if references else None,
                    "context_scope": self.reference_scope.currentText(),
                    "animation_context": animation_context(start, end, count, self.mode.currentData()),
                },
                lambda sheet_result: self._store_animation_sheet(sheet_result, start, end, count),
            )
        except Exception as exc:
            self.append_log("Error: %s" % exc)

    def _store_animation_sheet(self, result, start, end, count):
        if not result.get("image_path"):
            self.append_log(result.get("text", "No animation sheet image artifact was returned by Codex."))
            return
        self.animation_sheet_path = result["image_path"]
        self.sheet_frame_refs = extract_animation_sheet_frames(
            self.animation_sheet_path,
            start,
            end,
            count,
            self.selected_transparency_mode(),
        )
        QApplication.processEvents()
        self.apply_btn.setEnabled(bool(self.sheet_frame_refs))
        sheet_message = attach_image_patch_to_document(
            self.animation_sheet_path,
            0,
            0,
            TRANSPARENCY_PRESERVE_ALPHA,
            layer_name="Codex Animation - sheet",
        )
        QApplication.processEvents()
        frame_messages = apply_sheet_frames_to_timeline(
            self.sheet_frame_refs,
            self.selected_output_destination(),
            self.selected_transparency_mode(),
        )
        self.append_log(
            "%s\n%s\nAnimation sheet: %s\nExtracted and applied frames: %s\n%s"
            % (
                result.get("text", "Animation sheet generated."),
                sheet_message,
                self.animation_sheet_path,
                ", ".join("frame %s" % ref.get("frame") for ref in self.sheet_frame_refs),
                frame_messages,
            )
        )

    def generate_frame(self):
        try:
            self.generate_animation_sheet()
        except Exception as exc:
            self.set_busy(False)
            self.append_log("Error: %s" % exc)

    def apply_to_timeline(self):
        try:
            if not self.sheet_frame_refs:
                raise RuntimeError("No extracted sheet frames are ready to apply.")
            message = apply_sheet_frames_to_timeline(
                self.sheet_frame_refs,
                self.selected_output_destination(),
                self.selected_transparency_mode(),
            )
            self.append_log(message)
            self.refresh_context()
        except Exception as exc:
            self.append_log("Error: %s" % exc)

    def go_to_frame(self, frame):
        try:
            set_document_time(frame)
            self.refresh_context()
        except Exception as exc:
            self.append_log("Error: %s" % exc)
