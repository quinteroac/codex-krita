from PyQt5.QtCore import QThread, pyqtSignal


class RpcWorker(QThread):
    activity = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, client, method, params, parent=None, quiet_activity=False):
        super().__init__(parent)
        self.client = client
        self.method = method
        self.params = params
        self.quiet_activity = quiet_activity

    def run(self):
        try:
            if hasattr(self.client, "set_activity_callback"):
                self.client.set_activity_callback(self._activity)
            self.finished.emit(self.client.call(self.method, self.params))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if hasattr(self.client, "set_activity_callback"):
                self.client.set_activity_callback(None)

    def _activity(self, message):
        if self.quiet_activity and self._is_noisy_activity(message):
            return
        self.activity.emit(message)

    def _is_noisy_activity(self, message):
        return (
            message.startswith("assistant delta:")
            or message.startswith("event:")
            or message.startswith("item completed:")
            or message == "token usage updated"
        )
