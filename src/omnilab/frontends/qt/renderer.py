"""Qt signal adapter for the shared native-process transport."""
from PySide6.QtCore import QObject, Signal
from omnilab.render.process import RendererProcess


class RendererBridge(QObject):
    event = Signal(dict)

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.transport = RendererProcess(directory, self.event.emit)

    def __getattr__(self, name):
        return getattr(self.transport, name)

    def start(self, config=None):
        self.transport.start(config)

    def send(self, message):
        self.transport.send(message)

    def stop(self):
        self.transport.stop()
