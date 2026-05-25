from PyQt5.QtCore import QThread, pyqtSignal


class RpcWorker(QThread):
    activity = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, client, method, params, parent=None):
        super().__init__(parent)
        self.client = client
        self.method = method
        self.params = params

    def run(self):
        try:
            if hasattr(self.client, "set_activity_callback"):
                self.client.set_activity_callback(self.activity.emit)
            self.finished.emit(self.client.call(self.method, self.params))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if hasattr(self.client, "set_activity_callback"):
                self.client.set_activity_callback(None)
