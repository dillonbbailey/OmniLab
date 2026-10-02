"""Final jobs and lossless EXR inspection, independent of the interactive viewport."""
import json
from pathlib import Path
import tempfile
import threading

from PySide6.QtCore import Qt, QTimer, Signal, QRectF
from PySide6.QtGui import QImage, QPixmap, QPen, QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter, QWidget,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QFileDialog,
    QGraphicsView, QGraphicsScene, QPlainTextEdit, QScrollArea)
from pxr import Gf, UsdGeom

from omnilab.core.document import Document
from omnilab.core.camera import scene_camera
from omnilab.render.jobs import JobOptions, RenderJob, prepare_job, frame_range
from omnilab.render.images import AOVS, atomic_copy
from omnilab.render.exr_image import inspect_exr, display_exr, PixelReader
from omnilab.render.exr_channels import channel_inventory, resolve_selection


class ImageCanvas(QGraphicsView):
    regionChanged = Signal(object)
    pixelMoved = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.item = self.scene().addPixmap(QPixmap())
        self.roi = self.scene().addRect(QRectF(), QPen(QColor('#ffb24d'), 0))
        self.roi.setZValue(1)
        self.origin = None
        self.stride = 1

    def show_image(self, image, stride=1):
        first = self.item.pixmap().isNull()
        self.item.setPixmap(QPixmap.fromImage(image))
        self.stride = stride
        self.scene().setSceneRect(self.item.boundingRect())
        if first:
            self.fitInView(self.item.boundingRect(), Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier:
            self.origin = self.mapToScene(event.position().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        self.pixelMoved.emit(int(point.x() * self.stride), int(point.y() * self.stride))
        if self.origin is not None:
            self.roi.setRect(QRectF(self.origin, point).normalized().intersected(self.item.boundingRect()))
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.origin is not None:
            rect = self.roi.rect()
            self.origin = None
            self.regionChanged.emit([round(v * self.stride) for v in (rect.left(), rect.top(), rect.right(), rect.bottom())])
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class RenderView(QDialog):
    imageReady = Signal(object, object, str, int)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle('RenderView — OmniLab')
        self.resize(1440, 900)
        self.job = None
        self.path = ''
        self.metadata = None
        self.image_info = None
        self.image_request = 0
        self.image_busy = False
        self.disposed = False
        self.resume_viewport = self.resume_preview = False
        self.scratch = tempfile.TemporaryDirectory(prefix='omnilab-exr-')
        self.pixel_reader = PixelReader()
        self.imageReady.connect(self.image_ready)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        for label, callback in [('Render', self.start), ('Cancel', self.cancel), ('Open EXR…', self.open_exr),
                                ('Save EXR as…', self.save_exr), ('Fit', self.fit), ('Job / logs', self.show_job)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, fn=callback: owner.safe(fn))
            toolbar.addWidget(button)
            if label == 'Render':
                self.render_button = button
            elif label == 'Cancel':
                self.cancel_button = button
                button.setEnabled(False)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        self.controls = QWidget()
        form = QFormLayout(self.controls)
        self.source = QComboBox()
        self.source.addItems(['USD Viewer', 'Material studio', 'USD file'])
        form.addRow('Source', self.source)
        self.source_file = QLineEdit()
        file_button = QPushButton('Choose USD…')
        file_button.clicked.connect(self.choose_source)
        form.addRow(self.source_file)
        form.addRow(file_button)
        self.camera = QComboBox()
        form.addRow('Camera', self.camera)
        self.mode = QComboBox()
        self.mode.addItems(['PathTracing', 'RealTimePathTracing'])
        form.addRow('Mode', self.mode)
        self.width, self.height = QSpinBox(), QSpinBox()
        for control, value in ((self.width, 1280), (self.height, 720)):
            control.setRange(1, 32768)
            control.setValue(value)
        form.addRow('Width', self.width)
        form.addRow('Height', self.height)
        self.samples = QSpinBox()
        self.samples.setRange(1, 1000000)
        self.samples.setValue(64)
        form.addRow('PT samples', self.samples)
        self.warmup = QSpinBox()
        self.warmup.setRange(1, 1024)
        self.warmup.setValue(16)
        form.addRow('RTPT temporal frames', self.warmup)
        self.sequence = QCheckBox('Frame range')
        form.addRow(self.sequence)
        self.start_frame, self.end_frame, self.step_frame = [QDoubleSpinBox() for _ in range(3)]
        for label, control, value in [('First', self.start_frame, owner.document.frame),
            ('Last', self.end_frame, owner.document.frame), ('Step', self.step_frame, 1)]:
            control.setRange(.001 if label == 'Step' else -1000000, 1000000)
            control.setDecimals(3)
            control.setValue(value)
            form.addRow(label, control)
        self.aovs = {}
        for name in AOVS:
            check = QCheckBox(name + (' (RTPT)' if len(AOVS[name][1]) == 1 else ' (linear beauty)' if name == 'HdrColor' else ' (meters)'))
            check.setChecked(name == 'HdrColor')
            self.aovs[name] = check
            form.addRow(check)
        self.region = QLineEdit()
        self.region.setPlaceholderText('x0, y0, x1, y1 — or Shift-drag image')
        form.addRow('Pixel region', self.region)
        clear = QPushButton('Clear region')
        clear.clicked.connect(lambda: (self.region.clear(), self.canvas.roi.setRect(QRectF())))
        form.addRow(clear)
        self.output = QLineEdit()
        directory = Path.cwd() / 'artifacts/renders'
        directory.mkdir(parents=True, exist_ok=True)
        self.output.setText(str(directory / 'image.{frame}.exr'))
        form.addRow('EXR output', self.output)
        browse = QPushButton('Choose output…')
        browse.clicked.connect(self.choose_output)
        form.addRow(browse)
        hint = QLabel('PT reports the active frame while its native step runs. RTPT counts temporal frames. Cancel retains completed files. Regions merge into each existing output EXR.')
        hint.setWordWrap(True)
        form.addRow(hint)
        scrolling = QScrollArea()
        scrolling.setWidgetResizable(True)
        scrolling.setWidget(self.controls)
        splitter.addWidget(scrolling)
        image_widget = QWidget()
        image_layout = QVBoxLayout(image_widget)
        row = QHBoxLayout()
        self.channel = QComboBox()
        self.channel.setMinimumWidth(240)
        row.addWidget(self.channel, 1)
        self.display = QComboBox()
        self.display.addItems(['auto', 'srgb', 'raw', 'signed', 'normalize'])
        row.addWidget(self.display)
        self.exposure = QDoubleSpinBox()
        self.exposure.setRange(-30, 30)
        self.exposure.setPrefix('Exposure ')
        row.addWidget(self.exposure)
        image_layout.addLayout(row)
        components = QHBoxLayout()
        self.component = QComboBox()
        self.component.addItems(['RGB', 'R', 'G', 'B', 'A'])
        components.addWidget(QLabel('Component'))
        components.addWidget(self.component)
        self.matte = QComboBox()
        self.matte.addItem('Automatic', 'auto')
        components.addWidget(QLabel('Matte'))
        components.addWidget(self.matte, 1)
        self.matte_overlay = QCheckBox('Matte overlay')
        components.addWidget(self.matte_overlay)
        image_layout.addLayout(components)
        self.canvas = ImageCanvas()
        image_layout.addWidget(self.canvas, 1)
        self.probe_label = QLabel('Original floating-point pixel values')
        self.probe_label.setWordWrap(True)
        image_layout.addWidget(self.probe_label)
        splitter.addWidget(image_widget)
        splitter.setSizes([330, 1080])
        self.status = QLabel('Ready')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        layout.addWidget(self.log)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.poll)
        self.image_timer = QTimer(self)
        self.image_timer.setSingleShot(True)
        self.image_timer.setInterval(50)
        self.image_timer.timeout.connect(self.convert_image)
        self.channel.currentIndexChanged.connect(self.schedule_image)
        self.display.currentIndexChanged.connect(self.schedule_image)
        self.exposure.valueChanged.connect(self.schedule_image)
        self.component.currentIndexChanged.connect(self.schedule_image)
        self.matte.currentIndexChanged.connect(self.schedule_image)
        self.matte_overlay.toggled.connect(self.schedule_image)
        self.source.currentIndexChanged.connect(self.refresh_cameras)
        self.canvas.regionChanged.connect(self.region_selected)
        self.canvas.pixelMoved.connect(self.probe)
        self.refresh_cameras()
        self.load_preferences()

    def load_preferences(self):
        values = self.owner.document.view.get('render_view', {})
        for name in ('width', 'height', 'samples', 'warmup', 'start_frame', 'end_frame', 'step_frame', 'exposure'):
            if name in values:
                getattr(self, name).setValue(values[name])
        for name in ('output', 'region', 'source_file'):
            if name in values:
                getattr(self, name).setText(values[name])
        for name in ('mode', 'source', 'display'):
            if name in values:
                getattr(self, name).setCurrentText(values[name])
        self.sequence.setChecked(values.get('sequence', False))
        for name, check in self.aovs.items():
            check.setChecked(name in values.get('aovs', ['HdrColor']))
        self.refresh_cameras()
        index = self.camera.findData(values.get('camera', ''))
        if index >= 0:
            self.camera.setCurrentIndex(index)

    def save_preferences(self):
        values = {name: getattr(self, name).value() for name in ('width', 'height', 'samples', 'warmup', 'start_frame', 'end_frame', 'step_frame', 'exposure')}
        values.update({name: getattr(self, name).text() for name in ('output', 'region', 'source_file')})
        values.update({name: getattr(self, name).currentText() for name in ('mode', 'source', 'display')})
        values.update(sequence=self.sequence.isChecked(), camera=self.camera.currentData(),
            aovs=[name for name, check in self.aovs.items() if check.isChecked()])
        self.owner.document.view['render_view'] = values

    def choose_source(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Render USD file', '', 'USD (*.usd *.usda *.usdc)')
        if path:
            self.source_file.setText(path)
            self.source.setCurrentText('USD file')
            self.refresh_cameras()

    def region_selected(self, region):
        if self.image_info:
            x, y = self.image_info['x'], self.image_info['y']
            region = [value + offset for value, offset in zip(region, (x, y, x, y))]
        self.region.setText(', '.join(map(str, region)))

    def refresh_cameras(self):
        self.camera.clear()
        self.camera.addItem('Current view / studio camera', '')
        document = self.owner.document
        if self.source.currentText() == 'USD file' and self.source_file.text():
            try:
                document = Document.open(self.source_file.text())
            except Exception as exc:
                self.status.setText(str(exc))
                return
        for prim in document.stage.Traverse():
            if prim.IsA(UsdGeom.Camera):
                self.camera.addItem(str(prim.GetPath()), str(prim.GetPath()))
        path = self.owner.viewport.scene_camera_path
        index = self.camera.findData(path)
        if index >= 0:
            self.camera.setCurrentIndex(index)

    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Render output', self.output.text(), 'EXR (*.exr)')
        if path:
            self.output.setText(path)

    def start(self):
        if self.job and self.job.active:
            raise ValueError('A final job is already running.')
        source = self.source.currentText()
        document = self.owner.document
        aspect = self.width.value() / self.height.value()
        view_camera = Gf.Camera(self.owner.viewport.render_camera())
        if source == 'USD file':
            document = Document.open(self.source_file.text())
        elif source == 'Material studio':
            editor = getattr(self.owner, 'material_editor', None)
            if not editor or not editor.current():
                raise ValueError('Open a material in the Material Editor first.')
            document, view_camera = editor.preview.studio_scene()
        view_camera.verticalAperture = view_camera.horizontalAperture / aspect
        camera_path = self.camera.currentData()
        camera_at = (lambda frame: scene_camera(document.stage, camera_path, frame, aspect)) if camera_path else lambda frame: view_camera
        frames = frame_range(self.start_frame.value(), self.end_frame.value(), self.step_frame.value()) if self.sequence.isChecked() else [document.frame]
        region = [int(v.strip()) for v in self.region.text().split(',')] if self.region.text().strip() else None
        options = JobOptions(output=self.output.text(), resolution=(self.width.value(), self.height.value()),
            mode=self.mode.currentText(), samples=self.samples.value(), warmup=self.warmup.value(), frames=tuple(frames),
            aovs=tuple(name for name, check in self.aovs.items() if check.isChecked()), region=region,
            purposes=tuple(name for name, check in self.owner.purposes.items() if check.isChecked()))
        job = prepare_job(document, camera_at, options, Path.cwd() / 'artifacts/render-jobs')
        self.save_preferences()
        self.begin_job(job)

    def begin_job(self, job):
        if self.job and self.job.active:
            raise ValueError('A final job is already running.')
        self.resume_viewport = self.owner.render_enabled
        self.owner.stop_renderer()
        editor = getattr(self.owner, 'material_editor', None)
        self.resume_preview = bool(editor and editor.preview.enabled)
        if editor:
            editor.preview.stop()
        self.owner.final_render_active = True
        self.job = RenderJob(job)
        try:
            self.job.start()
        except Exception:
            self.restore_interactive()
            raise
        self.controls.setEnabled(False)
        self.render_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.log.clear()
        self.log.appendPlainText('Job: ' + job['directory'])
        self.timer.start()

    def poll(self):
        for event in self.job.poll():
            if event['type'] == 'status':
                self.status.setText(event['text'])
            elif event['type'] == 'frame':
                self.load_image(event['path'])
                self.log.appendPlainText('Completed ' + event['path'])
            elif event['type'] == 'error':
                self.log.appendPlainText(event['text'])
        if not self.job.active:
            self.timer.stop()
            self.status.setText(f'Job {self.job.data["state"]} · {len(self.job.data["completed"])}/{len(self.job.data["snapshots"])} frames saved')
            self.restore_interactive()

    def restore_interactive(self):
        self.owner.final_render_active = False
        self.controls.setEnabled(True)
        self.render_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self.resume_viewport:
            self.owner.restart_renderer()
        editor = getattr(self.owner, 'material_editor', None)
        if self.resume_preview and editor:
            editor.preview.start()
        self.resume_viewport = self.resume_preview = False

    def cancel(self):
        if self.job and self.job.active:
            self.job.cancel()
            self.poll()

    def open_exr(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open EXR', '', 'EXR (*.exr)')
        if path:
            self.load_image(path)

    def load_image(self, path):
        metadata = inspect_exr(path)
        previous = self.channel.currentText()
        self.path, self.metadata = str(path), metadata
        self.image_info = None
        self.pixel_reader = PixelReader()
        self.channel.blockSignals(True)
        self.channel.clear()
        layers, scalars = channel_inventory(metadata)
        for layer in layers:
            self.channel.addItem(layer['label'], layer)
        self.channel.setCurrentIndex(max(0, self.channel.findText(previous)))
        self.channel.blockSignals(False)
        previous_matte = self.matte.currentData()
        self.matte.blockSignals(True)
        self.matte.clear()
        self.matte.addItem('Automatic', 'auto')
        for scalar in scalars:
            self.matte.addItem(scalar['label'], scalar['key'])
        self.matte.setCurrentIndex(max(0, self.matte.findData(previous_matte)))
        self.matte.blockSignals(False)
        self.schedule_image()

    def schedule_image(self, *_):
        self.image_request += 1
        self.image_timer.start()

    def convert_image(self):
        if not self.path or self.image_busy:
            return
        self.image_busy = True
        request, path = self.image_request, self.path
        layer = self.channel.currentData()
        selection = dict(layer=layer['key'], component=self.component.currentText(),
                         matte=self.matte.currentData(), overlay=self.matte_overlay.isChecked())
        metadata = self.metadata
        view = resolve_selection(metadata, selection)['view']
        display, exposure = self.display.currentText(), self.exposure.value()
        destination = Path(self.scratch.name) / f'{request}.png'
        def work():
            try:
                info = display_exr(path, destination, view, display, exposure, selection=selection, metadata=metadata)
                image, error = QImage(str(destination)), ''
                info['view'] = view
            except Exception as exc:
                image, info, error = None, None, str(exc)
            if not self.disposed:
                self.imageReady.emit(image, info, error, request)
        threading.Thread(target=work, daemon=True).start()

    def image_ready(self, image, info, error, request):
        self.image_busy = False
        if self.disposed:
            return
        if request != self.image_request:
            self.image_timer.start()
            return
        if error:
            self.log.appendPlainText(error)
            return
        self.image_info = info
        self.image_info['request'] = request
        if info.get('warning'):
            self.log.appendPlainText(info['warning'])
        self.canvas.show_image(image, info['stride'])

    def probe(self, x, y):
        if not self.image_info or not self.metadata:
            return
        try:
            view = self.image_info['view']
            part = self.metadata['parts'][view['part']]
            x, y = x + self.image_info['x'], y + self.image_info['y']
            if not (part['x'] <= x < part['x']+part['width'] and part['y'] <= y < part['y']+part['height']):
                return
            channels = self.image_info['probe_channels']
            values = self.pixel_reader.sample(self.path, x, y, channels)['values']
            self.probe_label.setText(f'({x}, {y})  ' + '  '.join(f'{v["label"]}: {v["value"]}' for v in values))
        except Exception as exc:
            self.probe_label.setText(str(exc))

    def fit(self):
        self.canvas.fitInView(self.canvas.item.boundingRect(), Qt.KeepAspectRatio)

    def save_exr(self):
        if self.path:
            path, _ = QFileDialog.getSaveFileName(self, 'Save original EXR (all parts and channels)', self.path, 'EXR (*.exr)')
            if path and Path(path).absolute() != Path(self.path).absolute():
                atomic_copy(self.path, path)

    def show_job(self):
        if self.job:
            from .window import json_dialog
            data = dict(self.job.data, logs={name: str(Path(self.job.data['directory']) / name) for name in ('worker.log', 'ovrtx.log')})
            json_dialog(self, 'Final job and diagnostics', data, readonly=True)

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)

    def shutdown(self):
        self.resume_viewport = self.resume_preview = False
        self.cancel()
        self.disposed = True
        self.close()
        # A conversion thread may still own a file in this directory. Its
        # TemporaryDirectory is cleaned when the dialog is collected.
