"""Bounded source texture thumbnails, decoded in an owned image process."""
import glob
import json
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel


class TexturePreview(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(160)
        self.setMaximumHeight(220)
        self.scratch = tempfile.TemporaryDirectory(prefix='omnilab-texture-')
        self.process = QProcess(self)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(lambda error: self.setText(self.process.errorString()))
        self.pending = None
        self.active = None
        self.key = None

    def show_texture(self, path='', raw=False):
        matches = sorted(glob.glob(path.replace('<UDIM>', '????'))) if path else []
        path = matches[0] if matches else path
        stamp = Path(path).stat().st_mtime_ns if path and Path(path).is_file() else 0
        key = (path, raw, stamp)
        if key == self.key:
            return
        self.key = key
        self.clear()
        self.setToolTip(path + ('\nRaw channel preview' if raw else '\nSource texture preview'))
        self.pending = key if stamp else None
        if not stamp:
            self.setText('Texture not found' if path else '')
        else:
            self.setText('Reading texture…')
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
        else:
            self.start_pending()

    def start_pending(self):
        self.active, self.pending = self.pending, None
        if not self.active:
            return
        path, raw, _ = self.active
        script = ('import json,sys; from omnilab.render.texture_thumbnail import make_thumbnail; '
                  'print(json.dumps(make_thumbnail(sys.argv[1],sys.argv[2],sys.argv[3]=="1")))')
        self.process.start(sys.executable, ['-c', script, path, str(Path(self.scratch.name)/'thumbnail.png'), '1' if raw else '0'])

    def finished(self, code, status):
        output = bytes(self.process.readAllStandardOutput()).decode(errors='replace')
        error = bytes(self.process.readAllStandardError()).decode(errors='replace')
        if self.active == self.key:
            if code == 0:
                try:
                    result = json.loads(output)
                    pixmap = QPixmap(result['image'])
                    self.setPixmap(pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    self.setToolTip(self.toolTip() + f"\n{result['width']} × {result['height']}")
                except (ValueError, KeyError):
                    self.setText('Texture preview failed')
            else:
                self.setText('Texture preview failed')
                self.setToolTip(error[-1000:])
        self.active = None
        self.start_pending()

    def shutdown(self):
        self.pending = None
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        self.scratch.cleanup()
