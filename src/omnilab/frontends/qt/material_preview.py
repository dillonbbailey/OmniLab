"""One bounded native preview worker shared by the material tabs."""
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QDoubleSpinBox, QFileDialog

from omnilab.core.camera import ViewCamera, camera_payload
from omnilab.render.snapshot import publish
from .renderer import RendererBridge


class PreviewImage(QLabel):
    navigated = Signal(str, float, float)

    def __init__(self, text):
        super().__init__(text)
        self.drag = None

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self.drag = (event.position(), event.button())

    def mouseMoveEvent(self, event):
        if self.drag:
            old, button = self.drag
            delta = event.position() - old
            self.drag = (event.position(), button)
            self.navigated.emit('pan' if button == Qt.MiddleButton else 'orbit', delta.x(), delta.y())

    def mouseReleaseEvent(self, event):
        self.drag = None

    def wheelEvent(self, event):
        self.navigated.emit('dolly', -event.angleDelta().y()/1200., 0.)
        event.accept()


class MaterialPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.label = PreviewImage('Select Preview to start ovRTX.')
        self.label.setToolTip('Drag to orbit; middle drag to pan; wheel to dolly.')
        self.label.navigated.connect(self.navigate)
        self.label.setMinimumSize(300, 300)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label, 1)
        row = QHBoxLayout()
        self.geometry = QComboBox()
        self.geometry.addItems(['Sphere', 'Cube', 'Card'])
        self.mode = QComboBox()
        self.mode.addItems(['RealTimePathTracing', 'PathTracing'])
        row.addWidget(self.geometry)
        row.addWidget(self.mode)
        layout.addLayout(row)
        self.light = QDoubleSpinBox()
        self.light.setRange(0, 100)
        self.light.setValue(1)
        self.light.setPrefix('Studio light × ')
        layout.addWidget(self.light)
        hdri = QPushButton('Choose HDRI…')
        hdri.clicked.connect(self.choose_hdri)
        layout.addWidget(hdri)
        self.button = QPushButton('Preview')
        self.button.clicked.connect(self.start)
        layout.addWidget(self.button)
        stop = QPushButton('Stop preview')
        stop.clicked.connect(self.stop)
        layout.addWidget(stop)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.scratch = tempfile.TemporaryDirectory(prefix='omnilab-material-')
        self.bridge = RendererBridge(Path(self.scratch.name) / 'runtime', self)
        self.bridge.event.connect(self.renderer_event)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.flush)
        self.graph = None
        self.request = 0
        self.presented_request = -1
        self.inflight = None
        self.ready = self.enabled = False
        self.hdri = ''
        self.camera = ViewCamera(target=[0, 1, 0], distance=5, yaw=24, pitch=12)
        self.picture = QImage()
        self.geometry.currentTextChanged.connect(self.schedule)
        self.mode.currentTextChanged.connect(self.schedule)
        self.light.valueChanged.connect(self.schedule)

    def choose_hdri(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Preview HDRI', '', 'Images (*.exr *.hdr *.png)')
        if path:
            self.hdri = path
            self.schedule()

    def set_graph(self, graph):
        if (str(graph.path) if graph else None) != (str(self.graph.path) if self.graph else None):
            self.picture = QImage()
            self.label.setText('Preview pending' if self.enabled else 'Select Preview to start ovRTX.')
            self.graph = None
            state = graph.document.view.get('material_studios', {}).get(str(graph.path), {}) if graph else {}
            self.camera = ViewCamera.from_dict(state.get('camera', dict(target=[0,1,0], distance=5, yaw=24, pitch=12)))
            self.hdri = state.get('hdri', '')
            self.geometry.setCurrentText(state.get('geometry', 'Sphere'))
            self.mode.setCurrentText(state.get('mode', 'RealTimePathTracing'))
            self.light.setValue(state.get('light', 1.))
        self.graph = graph
        self.schedule()

    def navigate(self, kind, x, y):
        if kind == 'pan':
            self.camera.pan(x, y, self.label.width())
        elif kind == 'orbit':
            self.camera.orbit(x, y)
        else:
            self.camera.dolly(x)
        self.schedule()

    def start(self):
        editor = self.parent()
        while editor is not None and not hasattr(editor, "owner"):
            editor = editor.parent()
        owner = getattr(editor, "owner", None)
        if owner and getattr(owner, "final_render_active", False):
            self.status.setText("Preview resumes after the final render finishes.")
            return
        if not self.enabled:
            self.enabled = True
            self.bridge.start(self.graph.document.view.get('renderer_config', {}) if self.graph else {})
        self.schedule()

    def stop(self):
        self.enabled = self.ready = False
        self.inflight = None
        self.timer.stop()
        self.bridge.stop()
        self.status.setText('Preview stopped; last image retained.')

    def schedule(self, *_):
        self.request += 1
        if self.graph:
            self.graph.document.view.setdefault('material_studios', {})[str(self.graph.path)] = dict(
                camera=self.camera.to_dict(), geometry=self.geometry.currentText(), mode=self.mode.currentText(),
                light=self.light.value(), hdri=self.hdri)
        if self.enabled:
            self.timer.start()

    def studio_scene(self):
        from omnilab.materials.studio import studio_scene
        return studio_scene(self.graph, self.camera, self.geometry.currentText(), self.light.value(), self.hdri)

    def flush(self):
        if not self.enabled or not self.ready or not self.graph or self.inflight is not None:
            return
        try:
            document, camera = self.studio_scene()
            snapshot = publish(document, Path(self.scratch.name) / str(self.request), camera,
                               (384, 384), self.mode.currentText(), 32, profile='material')
            self.bridge.send(dict(type='view', request=self.request, snapshot=snapshot,
                                  camera=camera_payload(camera), deltas={}, selection=[]))
            self.inflight = self.request
            self.status.setText('Rendering ' + str(self.graph.path))
        except Exception as error:
            self.status.setText(str(error))

    def renderer_event(self, event):
        if event.get('epoch') != self.bridge.epoch:
            return
        if event['type'] == 'ready':
            self.ready = True
            self.flush()
        elif event['type'] == 'loaded':
            from omnilab.render.snapshot import retire_snapshots
            retire_snapshots(self.scratch.name, event['path'])
        elif event['type'] == 'frame':
            self.bridge.send(dict(type='ack'))
            if event['request'] == self.inflight:
                self.inflight = None
            if event['request'] != self.request:
                if not self.timer.isActive():
                    self.timer.start()
                return
            height, width, _ = event['shape']
            self.picture = QImage(event['pixels'], width, height, width * 4, QImage.Format_RGBA8888).copy()
            self.presented_request = event['request']
            self.label.setPixmap(QPixmap.fromImage(self.picture).scaled(self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.status.setText(f'{self.mode.currentText()} · {event["milliseconds"]:.1f} ms')
        elif event['type'] in ('error', 'stopped'):
            self.ready = self.enabled = False
            self.inflight = None
            self.status.setText(event.get('text', 'Renderer stopped.'))

    def close(self):
        self.stop()
        self.scratch.cleanup()
        return super().close()
