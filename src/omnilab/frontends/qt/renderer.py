"""Qt process bridge. Native imports and frame reads never block the UI thread."""
import multiprocessing
from pathlib import Path
import queue
import threading

from PySide6.QtCore import QObject, Signal
from omnilab.render.worker import run


class RendererBridge(QObject):
    event = Signal(dict)

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.process = None
        self.epoch = 0

    def start(self, config=None):
        self.stop()
        self.epoch += 1
        self.config = dict(config or {})
        epoch = self.epoch
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=run, args=(child, str(self.directory), config), daemon=True)
        self.process.start()
        child.close()
        self.outgoing = queue.Queue()
        connection, outgoing = self.connection, self.outgoing

        def receive():
            try:
                while True:
                    message = connection.recv()
                    if epoch != self.epoch:
                        return
                    self.event.emit(dict(message, epoch=epoch))
            except (EOFError, OSError):
                if epoch == self.epoch:
                    self.event.emit(dict(type="stopped", epoch=epoch))

        def send():
            try:
                while True:
                    message = outgoing.get()
                    if message is None:
                        return
                    connection.send(message)
            except (EOFError, OSError):
                pass
        threading.Thread(target=receive, daemon=True).start()
        threading.Thread(target=send, daemon=True).start()

    def send(self, message):
        if self.process is not None and self.process.is_alive():
            self.outgoing.put(message)

    def stop(self):
        self.epoch += 1
        if self.process is None:
            return
        self.outgoing.put(None)
        # The only bounded cancellation available during a blocking native step is
        # terminating this owned worker. The authoritative document stays in the UI.
        self.process.terminate()
        self.process.join(timeout=1)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=1)
        self.connection.close()
        self.process.close()
        self.process = None
