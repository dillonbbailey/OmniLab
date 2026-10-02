"""Responsive Python console; native calls run in an owned cancellable process."""
import multiprocessing
from pathlib import Path
import tempfile
import time
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QPlainTextEdit, QFileDialog

from omnilab.automation.console import run_worker, snapshot, apply_result


class PythonConsole(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle('Python Console — OmniLab')
        self.resize(950, 700)
        self.process = None
        self.running = False
        self.cancelled_at = None
        self.scratch = tempfile.TemporaryDirectory(prefix='omnilab-console-')
        self.cancel_path = Path(self.scratch.name) / 'cancel'
        layout = QVBoxLayout(self)
        hint = QLabel('stage, usd, document, Usd, UsdGeom, UsdShade, Sdf, Gf and Vt are available. Successful cells commit as one undo step; errors and Stop retain the current document. Filesystem writes performed by your script are outside USD undo.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.code = QPlainTextEdit()
        self.code.setPlaceholderText("with usd.edit('Create cube'):\n    UsdGeom.Cube.Define(stage, '/World/Cube')")
        layout.addWidget(self.code, 1)
        row = QHBoxLayout()
        for text, callback in [('Run', self.run), ('Stop', self.stop), ('Open script…', self.open_script), ('Save script…', self.save_script), ('Reset context', self.reset)]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, callback=callback: owner.safe(callback))
            row.addWidget(button)
            if text == 'Run':
                self.run_button = button
        layout.addLayout(row)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(5000)
        layout.addWidget(self.output, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.poll)

    def start_process(self):
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=run_worker, args=(child,), daemon=True)
        self.process.start()
        child.close()

    def run(self):
        if self.running:
            return
        if self.process is None or not self.process.is_alive():
            self.reset()
            self.start_process()
        self.document = self.owner.document
        self.before = snapshot(self.document)
        self.cancel_path.unlink(missing_ok=True)
        self.cancelled_at = None
        self.owner.play_timer.stop()
        self.connection.send(dict(type='execute', id=uuid.uuid4().hex, stage=self.before, frame=self.document.frame,
            selection=self.document.selection, code=self.code.toPlainText(), cancel=str(self.cancel_path)))
        self.running = True
        self.run_button.setEnabled(False)
        self.timer.start()

    def poll(self):
        if not self.running:
            return
        try:
            while self.connection.poll():
                message = self.connection.recv()
                if 'text' in message:
                    self.output.appendPlainText(message['text'])
                if message['type'] == 'finished':
                    if message['status'] == 'ok' and self.cancelled_at is None:
                        if self.owner.document is not self.document:
                            raise ValueError('The document was replaced; the Python result was not applied.')
                        apply_result(self.document, self.before, message)
                        self.owner.refresh()
                        self.owner.refresh_material_tabs()
                        self.owner.schedule_view()
                    self.output.appendPlainText('Cell ' + message['status'])
                    self.finish()
                    break
            if self.running and self.cancelled_at and time.monotonic()-self.cancelled_at > .5:
                self.reset()
                self.output.appendPlainText('Stopped native call. USD edits were not committed.')
            elif self.running and not self.process.is_alive():
                raise RuntimeError('Python worker exited. Run again to create a fresh context.')
        except Exception as exc:
            self.output.appendPlainText(str(exc))
            self.reset()

    def finish(self):
        self.running = False
        self.timer.stop()
        self.run_button.setEnabled(True)

    def stop(self):
        if self.running:
            self.cancelled_at = time.monotonic()
            self.cancel_path.touch()

    def reset(self):
        self.finish()
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)
            self.process.close()
            self.connection.close()
            self.process = None

    def open_script(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open Python script (does not execute)', '', 'Python (*.py)')
        if path:
            self.code.setPlainText(Path(path).read_text())

    def save_script(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save Python script', 'script.py', 'Python (*.py)')
        if path:
            Path(path).write_text(self.code.toPlainText())

    def closeEvent(self, event):
        self.reset()
        super().closeEvent(event)
