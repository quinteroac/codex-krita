from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from krita import DockWidget

from .client import CodexDirectClient
from .image_bridge import (
    TRANSPARENCY_OPAQUE,
    TRANSPARENCY_PRESERVE_ALPHA,
    TRANSPARENCY_REMOVE_FLAT_BACKGROUND,
    attach_image_to_document,
    clip_image_to_inpaint_mask,
    document_context,
    export_active_context,
    export_selection_mask,
    write_result_image,
)
from .script_runner import run_krita_script
from .setup import diagnostics, save_detected_config, setup_status_text
from .worker import RpcWorker


class CodexDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Codex")
        self.client = CodexDirectClient()
        self.worker = None
        self.pending_script = None
        self._build_ui()

    def canvasChanged(self, canvas):
        self.refresh_context()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        self.status = QLabel("Direct Codex mode: using the local Codex SDK from Krita's Python.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        setup_row = QHBoxLayout()
        self.check_setup_btn = QPushButton("Check Setup")
        self.configure_bin_btn = QPushButton("Save Config")
        setup_row.addWidget(self.check_setup_btn)
        setup_row.addWidget(self.configure_bin_btn)
        layout.addLayout(setup_row)

        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItems(["document", "active_layer", "selection"])
        self.size = QComboBox()
        self.size.addItems(
            [
                "auto",
                "1024x1024 square",
                "1536x1024 landscape",
                "1024x1536 portrait",
                "2048x2048 2K square",
                "2048x1152 2K landscape",
                "3840x2160 4K landscape",
                "2160x3840 4K portrait",
            ]
        )
        self.quality = QComboBox()
        self.quality.addItems(["medium", "high", "low"])
        self.transparency = QComboBox()
        self.transparency.addItem("Opaque", TRANSPARENCY_OPAQUE)
        self.transparency.addItem("Preserve PNG alpha", TRANSPARENCY_PRESERVE_ALPHA)
        self.transparency.addItem("Remove flat background", TRANSPARENCY_REMOVE_FLAT_BACKGROUND)
        form.addRow("Context", self.scope)
        form.addRow("Size", self.size)
        form.addRow("Quality", self.quality)
        form.addRow("Transparency", self.transparency)
        layout.addLayout(form)

        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("Ask Codex to analyze, generate, edit, or script something for this artwork.")
        self.prompt.setMinimumHeight(110)
        layout.addWidget(self.prompt)

        button_row = QHBoxLayout()
        self.analyze_btn = QPushButton("Analyze")
        self.generate_btn = QPushButton("Generate")
        self.edit_btn = QPushButton("Edit Selection")
        button_row.addWidget(self.analyze_btn)
        button_row.addWidget(self.generate_btn)
        button_row.addWidget(self.edit_btn)
        layout.addLayout(button_row)

        script_row = QHBoxLayout()
        self.script_btn = QPushButton("Propose Script")
        self.run_script_btn = QPushButton("Run Script")
        self.run_script_btn.setEnabled(False)
        script_row.addWidget(self.script_btn)
        script_row.addWidget(self.run_script_btn)
        layout.addLayout(script_row)

        self.script_preview = QTextEdit()
        self.script_preview.setPlaceholderText("Generated Krita Python script appears here.")
        self.script_preview.setMinimumHeight(140)
        layout.addWidget(self.script_preview)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(180)
        layout.addWidget(self.log)

        self.analyze_btn.clicked.connect(self.analyze)
        self.generate_btn.clicked.connect(self.generate)
        self.edit_btn.clicked.connect(self.edit_selection)
        self.script_btn.clicked.connect(self.propose_script)
        self.run_script_btn.clicked.connect(self.run_script)
        self.check_setup_btn.clicked.connect(self.check_setup)
        self.configure_bin_btn.clicked.connect(self.configure_codex_bin)

        self.setWidget(root)
        self.refresh_context()

    def refresh_context(self):
        context = document_context()
        if context.get("has_document"):
            self.status.setText(
                "%s - %sx%s - active: %s"
                % (context["name"], context["width"], context["height"], context.get("active_node"))
            )
        else:
            self.status.setText("No active document. Direct Codex mode is ready if the Codex SDK is installed.")

    def prompt_text(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            raise RuntimeError("Prompt is empty.")
        return text

    def selected_size(self):
        return self.size.currentText().split(" ", 1)[0]

    def selected_transparency_mode(self):
        return self.transparency.currentData()

    def set_busy(self, busy):
        for button in (self.analyze_btn, self.generate_btn, self.edit_btn, self.script_btn, self.run_script_btn):
            if button is self.run_script_btn:
                button.setEnabled((not busy) and self.pending_script is not None)
            else:
                button.setEnabled(not busy)
        self.status.setText("Working..." if busy else "Ready")

    def call_worker(self, method, params, callback):
        self.set_busy(True)
        self.worker = RpcWorker(self.client, method, params, self)
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

    def check_setup(self):
        self.append_log(setup_status_text())

    def configure_codex_bin(self):
        try:
            info = diagnostics()
            message = save_detected_config(info["codex_bin"])
            self.append_log(message)
        except Exception as exc:
            self.append_log("Setup error: %s" % exc)

    def analyze(self):
        try:
            exported = export_active_context(self.scope.currentText())
            self.call_worker(
                "analyze_image",
                {
                    "image_b64": exported["image_b64"],
                    "image_path": exported["path"],
                    "mime_type": exported["mime_type"],
                    "question": self.prompt.toPlainText().strip(),
                },
                lambda result: self.append_log(result.get("text", "")),
            )
        except Exception as exc:
            self.append_log("Error: %s" % exc)

    def generate(self):
        try:
            self.call_worker(
                "generate_image",
                {
                    "prompt": self.prompt_text(),
                    "size": self.selected_size(),
                    "quality": self.quality.currentText(),
                    "transparency_mode": self.selected_transparency_mode(),
                },
                self._attach_generated_result,
            )
        except Exception as exc:
            self.append_log("Error: %s" % exc)

    def edit_selection(self):
        try:
            exported = export_active_context(self.scope.currentText())
            mask = export_selection_mask()
            if mask is None:
                raise RuntimeError("Select an area first. Edit Selection uses the selected area as the inpainting region.")
            self.call_worker(
                "edit_image",
                {
                    "prompt": self.prompt_text(),
                    "image_path": exported["path"],
                    "mask_path": mask["path"] if mask else None,
                    "size": self.selected_size(),
                    "quality": self.quality.currentText(),
                },
                lambda result: self._attach_edited_selection_result(result, mask["path"]),
            )
        except Exception as exc:
            self.append_log("Error: %s" % exc)

    def _attach_generated_result(self, result):
        if result.get("image_path"):
            message = attach_image_to_document(result["image_path"], self.selected_transparency_mode())
            self.append_log("%s\n%s" % (message, result["image_path"]))
            return
        if result.get("text"):
            self.append_log(result["text"])
            return
        path = write_result_image(result["image_b64"])
        message = attach_image_to_document(path, self.selected_transparency_mode())
        self.append_log("%s\n%s" % (message, path))

    def _attach_edited_selection_result(self, result, mask_path):
        try:
            if result.get("image_path"):
                path = clip_image_to_inpaint_mask(result["image_path"], mask_path)
                message = attach_image_to_document(path, TRANSPARENCY_PRESERVE_ALPHA)
                self.append_log("%s\n%s" % (message, path))
                return
            if result.get("text") and not result.get("image_b64"):
                self.append_log(result["text"])
                return
            path = write_result_image(result["image_b64"])
            path = clip_image_to_inpaint_mask(path, mask_path)
            message = attach_image_to_document(path, TRANSPARENCY_PRESERVE_ALPHA)
            self.append_log("%s\n%s" % (message, path))
        except Exception as exc:
            self.append_log("Error: %s" % exc)

    def propose_script(self):
        try:
            self.call_worker(
                "propose_script",
                {
                    "task": self.prompt_text(),
                    "document_context": document_context(),
                },
                self._set_pending_script,
            )
        except Exception as exc:
            self.append_log("Error: %s" % exc)

    def _set_pending_script(self, result):
        self.pending_script = result.get("code", "")
        self.script_preview.setPlainText(self.pending_script)
        self.run_script_btn.setEnabled(bool(self.pending_script))
        self.append_log("Script proposed: %s" % result.get("expected_effect", ""))

    def run_script(self):
        code = self.script_preview.toPlainText().strip()
        if not code:
            self.append_log("No script to run.")
            return
        try:
            result = run_krita_script(code)
            self.append_log("Script executed.\nstdout:\n%s\nstderr:\n%s" % (result["stdout"], result["stderr"]))
        except Exception as exc:
            self.append_log("Script error: %s" % exc)
