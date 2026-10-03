"""Qt-first USD workspace over the frontend-independent document API."""
import json
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import Qt, QTimer, Signal, QSignalBlocker, QProcess, QItemSelectionModel
from PySide6.QtGui import QAction, QImage, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QTableWidget, QTableWidgetItem, QLineEdit,
    QLabel, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QDockWidget,
    QPlainTextEdit, QFileDialog, QMessageBox, QInputDialog, QMenu, QDialog, QDialogButtonBox,
    QAbstractItemView, QFormLayout, QGroupBox, QScrollArea, QFrame, QSizePolicy, QStackedWidget)
from pxr import Gf, Sdf, Usd, UsdGeom

from omnilab.core.document import Document
from omnilab.core.fixtures import demo_document
from omnilab.core.camera import ViewCamera, camera_payload
from omnilab.render.snapshot import publish, MODES
from omnilab.usd.usd_editing import PRIM_TYPES, property_info
from omnilab.usd.usd_layers import layer_entries, layer_text
from omnilab.usd.usd_transform_pose import pose_info
from omnilab.usd.usd_transforms import quaternion_from_euler, euler_from_quaternion, checked_values
from omnilab.usd.usd_inspection import property_rows
from omnilab.usd.usd_variants import variant_choices
from .renderer import RendererBridge
from .viewport import Viewport
from .application_settings import ApplicationSettings, ApplicationSettingsDialog
from .numeric_editor import NumericEditor, numeric_editor
from .timeline import Timeline


def json_dialog(parent, title, value, readonly=False):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(720, 450)
    layout = QVBoxLayout(dialog)
    editor = QPlainTextEdit(json.dumps(value, indent=2) if not isinstance(value, str) or not readonly else value)
    editor.setReadOnly(readonly)
    editor.setFont(QFont("monospace", 10))
    layout.addWidget(editor)
    buttons = QDialogButtonBox(QDialogButtonBox.Close if readonly else QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.Accepted:
        return json.loads(editor.toPlainText())
    return None


class PrimTree(QTreeWidget):
    moveRequested = Signal(str, str)

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        current = self.currentItem()
        if current:
            self.moveRequested.emit(current.data(0, Qt.UserRole), item.data(0, Qt.UserRole) if item else "/")
        event.ignore()


class MainWindow(QMainWindow):
    def __init__(self, render_enabled=True, *, application_settings=None):
        super().__init__()
        self.application_settings = application_settings if application_settings is not None else ApplicationSettings()
        self.resize(1500, 940)
        self.setFont(QFont("Ubuntu Sans", 10))
        self.document = Document()
        self.scratch = tempfile.TemporaryDirectory(prefix="omnilab-")
        self.bridge = RendererBridge(Path(self.scratch.name) / "runtime", self)
        self.bridge.event.connect(self.renderer_event)
        self.render_enabled = render_enabled
        self.renderer_ready = False
        self.request = 0
        self.presented_request = -1
        self.submitted_request = None
        self.inflight_request = None
        self.frame_floor = 0
        self.snapshot = None
        self.deltas = {}
        self.snapshot_dirty = True
        self.snapshot_number = 0
        self.publication_ms = 0.
        self._refreshing = False
        self._updating = False
        self.frame_count = 0
        self.stale_frame_count = 0
        self.relaunching = False
        self.publish_timer = QTimer(self)
        self.publish_timer.setSingleShot(True)
        self.publish_timer.setInterval(16)
        self.publish_timer.setTimerType(Qt.PreciseTimer)
        self.publish_timer.timeout.connect(self.flush_view)
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self.play_step)
        self.build_workspace()
        self.build_menus()
        self.install_document(self.document)
        if render_enabled:
            self.bridge.start()

    def action(self, menu, text, callback, shortcut=None):
        action = QAction(text, self)
        action.triggered.connect(lambda checked=False: self.safe(callback))
        if shortcut:
            action.setShortcut(shortcut)
        menu.addAction(action)
        return action

    def build_menus(self):
        menu = self.menuBar().addMenu("&File")
        self.action(menu, "New USD stage", self.new_document, "Ctrl+N")
        self.action(menu, "New OpenPBR demo", self.new_demo)
        self.action(menu, "New MDL demo", lambda: self.new_demo("mdl"))
        self.action(menu, "Open USD / project…", self.open_dialog, "Ctrl+O")
        self.action(menu, "Save", self.save, "Ctrl+S")
        self.action(menu, "Save as…", lambda: self.save(True), "Ctrl+Shift+S")
        self.action(menu, "Export flattened USD…", self.export_flattened)
        self.action(menu, "Publish selected prim as asset…", self.publish_asset)
        self.action(menu, "Save viewport image…", self.save_image)
        self.action(menu, "Reload from disk", self.reload)
        self.relaunch_action = self.action(menu, "Relaunch OmniLab", self.relaunch)
        self.relaunch_action.setToolTip('Reload application code and restore the current document. Undo and Python execution state start fresh.')
        menu.addSeparator()
        self.action(menu, "Close", self.close, "Ctrl+Q")
        menu = self.menuBar().addMenu("&Edit")
        self.undo_action = self.action(menu, "Undo", lambda: self.execute("restore"), "Ctrl+Z")
        self.redo_action = self.action(menu, "Redo", lambda: self.execute("restore", True), "Ctrl+Shift+Z")
        self.action(menu, "Duplicate selected prim", self.duplicate, "Ctrl+D")
        self.action(menu, "Delete selected prim", self.remove, "Delete")
        self.action(menu, "Rename selected prim…", self.rename, "F2")
        self.action(menu, "Bind existing material…", self.bind_material)
        menu.addSeparator()
        self.action(menu, "Application Settings…", self.open_application_settings)
        menu = self.menuBar().addMenu("&Create")
        for kind in PRIM_TYPES:
            self.action(menu, kind, lambda kind=kind: self.create_prim(kind))
        menu = self.menuBar().addMenu("&View")
        self.action(menu, "Material Editor…", self.open_material_editor, "Ctrl+M")
        self.action(menu, "RenderView…", self.open_render_view, "F6")
        self.action(menu, "Python Console…", self.open_python_console, "F8")
        self.mcp_action = self.action(menu, "Start MCP", self.toggle_mcp)
        self.action(menu, "Frame selected", lambda: self.frame_selection(False), "F")
        self.action(menu, "Frame all", lambda: self.frame_selection(True), "Shift+F")
        self.action(menu, "Restart renderer", self.restart_renderer)
        self.action(menu, "Stop renderer", self.stop_renderer)
        self.action(menu, "Renderer logs", self.show_renderer_logs)
        self.timeline_action = QAction('Show Timeline', self)
        self.timeline_action.setCheckable(True)
        self.timeline_action.setChecked(self.application_settings.timeline_visible())
        self.timeline_action.toggled.connect(self.set_timeline_visible)
        menu.addAction(self.timeline_action)
        menu.addAction(self.log_dock.toggleViewAction())
        menu = self.menuBar().addMenu("&Help")
        self.action(menu, "Controls and scope", self.about)

    def build_workspace(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        self.setCentralWidget(central)
        splitter = self.workspace_splitter = QSplitter()
        layout.addWidget(splitter, 1)
        left = QTabWidget()
        splitter.addWidget(left)
        hierarchy = QWidget()
        h_layout = QVBoxLayout(hierarchy)
        h_layout.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter prim name, path or type")
        self.filter.textChanged.connect(self.refresh_tree)
        h_layout.addWidget(self.filter)
        self.tree = PrimTree()
        self.tree.setHeaderLabels(["Prim", "Type"])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.prim_menu)
        self.tree.itemSelectionChanged.connect(self.tree_selection)
        self.tree.itemExpanded.connect(self.expand_item)
        self.tree.moveRequested.connect(lambda path, parent: self.safe(lambda: self.execute("reparent_prim", dict(path=path, parent=parent, mode="namespace"))))
        h_layout.addWidget(self.tree)
        left.addTab(hierarchy, "Stage")
        layer_widget = QWidget()
        layers_layout = QVBoxLayout(layer_widget)
        self.layers = QTreeWidget()
        self.layers.setHeaderLabels(["Layer", "Role"])
        self.layers.itemDoubleClicked.connect(lambda item, column: self.safe(lambda: self.set_target(item.data(0, Qt.UserRole))))
        self.layers.setContextMenuPolicy(Qt.CustomContextMenu)
        self.layers.customContextMenuRequested.connect(self.layer_menu)
        layers_layout.addWidget(QLabel("Double-click a local layer to edit it."))
        layers_layout.addWidget(self.layers)
        self.target_label = QLabel()
        self.target_label.setWordWrap(True)
        layers_layout.addWidget(self.target_label)
        left.addTab(layer_widget, "Layers")

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        center_layout.addLayout(controls)
        self.tool = QComboBox()
        self.tool.addItems(["Translate", "Rotate", "Scale"])
        controls.addWidget(self.tool)
        self.space = QComboBox()
        self.space.addItems(["World", "Local"])
        controls.addWidget(self.space)
        self.cameras = QComboBox()
        self.cameras.setMinimumWidth(150)
        controls.addWidget(self.cameras, 1)
        self.ortho = QCheckBox("Ortho")
        controls.addWidget(self.ortho)
        self.camera_edit = QCheckBox('Edit camera')
        self.camera_edit.setToolTip('Navigation edits the selected USD camera. A drag is one undo step; Escape cancels it.')
        controls.addWidget(self.camera_edit)
        self.viewport = Viewport()
        self.viewport.show_orientation_gizmo = self.application_settings.show_orientation_gizmo()
        center_layout.addWidget(self.viewport, 1)
        splitter.addWidget(center)
        self.viewport.cameraChanged.connect(self.navigation_changed)
        self.viewport.resized.connect(lambda: self.schedule_view())
        self.viewport.pickRequested.connect(self.pick)
        self.viewport.transformCommitted.connect(lambda data: self.safe(lambda: self.commit_viewport_transform(data)))
        self.viewport.transformPreviewChanged.connect(lambda data: self.safe(lambda: self.preview_transform(data)))
        self.viewport.cameraCommitted.connect(lambda data: self.safe(lambda: self.execute('set_camera_view', data)))
        self.camera_edit.toggled.connect(lambda value: setattr(self.viewport, 'edit_camera', value))
        self.viewport.frameRequested.connect(self.frame_selection)
        self.viewport.toolChanged.connect(lambda tool: self.tool.setCurrentIndex(('translate', 'orient', 'scale').index(tool)))
        self.tool.currentIndexChanged.connect(self.tool_changed)
        self.transform_shortcuts = []
        for index, key in enumerate(('W', 'E', 'R')):
            for widget in (self.viewport, self.tree):
                shortcut = QShortcut(QKeySequence(key), widget)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.activated.connect(lambda index=index: self.select_transform_tool(index))
                self.transform_shortcuts.append(shortcut)
        self.tool.setToolTip('W: Translate · E: Rotate · R: Scale. Drag an axis to author the selected prim.')
        self.space.currentTextChanged.connect(self.space_changed)
        self.cameras.currentIndexChanged.connect(self.camera_changed)
        self.ortho.toggled.connect(self.projection_changed)

        right = self.properties_tabs = QTabWidget()
        right.setMinimumWidth(240)
        right.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        splitter.addWidget(right)
        properties = QWidget()
        p_layout = QVBoxLayout(properties)
        self.selection_label = QLabel("No selection")
        self.selection_label.setWordWrap(True)
        self.selection_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        p_layout.addWidget(self.selection_label)
        transform = QGroupBox("Transform")
        form = QFormLayout(transform)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.transform_fields = {}
        def transform_row(key, components, decimals=4):
            row = QWidget()
            row.setMinimumWidth(190)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            fields = []
            for component in components:
                field = QDoubleSpinBox()
                field.setRange(-1e10, 1e10)
                field.setDecimals(decimals)
                field.setSingleStep(.1)
                field.setKeyboardTracking(False)
                field.setMinimumWidth(0)
                field.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
                field.setAccessibleName(key + ' ' + component)
                row_layout.addWidget(field, 1)
                fields.append(field)
            self.transform_fields[key] = fields
            return row
        form.addRow('Translate', transform_row('translate', 'XYZ'))
        self.rotation_label = QLabel('Rotate XYZ')
        self.quaternion_check = QCheckBox('Quaternion')
        self.quaternion_check.setToolTip('Edit rotation as W, X, Y, Z. Nonzero quaternions are normalized on Apply.')
        self.rotation_fields = QStackedWidget()
        self.rotation_fields.addWidget(transform_row('rotateXYZ', 'XYZ'))
        self.rotation_fields.addWidget(transform_row('orient', 'WXYZ', 12))
        form.addRow(self.rotation_label, self.rotation_fields)
        form.addRow(self.quaternion_check)
        form.addRow('Scale', transform_row('scale', 'XYZ'))
        self.quaternion_check.toggled.connect(lambda enabled: self.safe(lambda: self.rotation_mode_changed(enabled)))
        self.matrix_output = QCheckBox('Output as matrix')
        self.matrix_output.setToolTip('Apply and viewport drags write one combined matrix4d xform op. Existing key poses are retained; interpolation between keys can change.')
        self.matrix_output.toggled.connect(self.store_transform_preferences)
        form.addRow(self.matrix_output)
        self.time_mode = QComboBox()
        self.time_mode.addItems(["Default value", "Key at frame"])
        self.time_mode.currentIndexChanged.connect(lambda i: setattr(self.viewport, "edit_time", "frame" if i else "default"))
        form.addRow("Authoring", self.time_mode)
        apply = QPushButton("Apply transform")
        apply.clicked.connect(lambda: self.safe(self.apply_transform))
        form.addRow(apply)
        p_layout.addWidget(transform)
        self.properties = QTableWidget(0, 3)
        self.properties.setHorizontalHeaderLabels(["Property", "Type", "Value"])
        self.properties.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.properties.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.properties.cellDoubleClicked.connect(lambda row, col: self.safe(lambda: self.edit_property(row)))
        self.properties.horizontalHeader().setStretchLastSection(True)
        p_layout.addWidget(self.properties, 1)
        property_scroll = QScrollArea()
        property_scroll.setFrameShape(QFrame.NoFrame)
        property_scroll.setWidgetResizable(True)
        property_scroll.setWidget(properties)
        right.addTab(property_scroll, "Properties")

        rendering = QWidget()
        r_layout = QFormLayout(rendering)
        self.mode = QComboBox()
        self.mode.addItems(MODES[:2])
        self.mode.currentTextChanged.connect(lambda _: self.schedule_view())
        r_layout.addRow("Render mode", self.mode)
        self.samples = QSpinBox()
        self.samples.setRange(1, 4096)
        self.samples.setValue(16)
        self.samples.setToolTip("PathTracing sample limit. RTPT uses eight preview warm-up frames.")
        self.samples.valueChanged.connect(lambda _: self.schedule_view())
        r_layout.addRow("PT samples", self.samples)
        self.purposes = {}
        for name in ("default", "render", "proxy", "guide"):
            check = QCheckBox(name)
            check.setChecked(name in ("default", "render"))
            check.toggled.connect(lambda _: self.schedule_view())
            r_layout.addRow("Purpose", check)
            self.purposes[name] = check
        self.grid_check = QCheckBox("Grid")
        self.grid_check.setChecked(True)
        self.grid_check.toggled.connect(lambda value: self.overlay("grid", value))
        r_layout.addRow(self.grid_check)
        guides = QCheckBox("Camera / light guides")
        guides.setChecked(True)
        guides.toggled.connect(lambda value: self.overlay("guides", value))
        r_layout.addRow(guides)
        self.display = QComboBox()
        self.display.addItems(["Shaded", "Shaded Wireframe", "Unlit Wireframe", "Wire over Shaded", "Points"])
        self.display.setToolTip("Native shaded/unlit wireframe shows triangulated render edges. Wire over Shaded and Points draw authored mesh edges/vertices against native distance for occlusion; displacement/deformation can differ from authored geometry.")
        self.display.currentTextChanged.connect(self.display_changed)
        r_layout.addRow("Display", self.display)
        for text, callback in (("Restart renderer", self.restart_renderer), ("Stop renderer", self.stop_renderer), ("Inspect all ovRTX settings", self.settings_catalog)):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, callback=callback: self.safe(callback))
            r_layout.addRow(button)
        note = QLabel("Ctrl+M: Material Editor · F6: RenderView.\nMoonRay graph conversion: P7.\nPoints / filled wire overlay use authored meshes and native depth.")
        note.setWordWrap(True)
        r_layout.addRow(note)
        rendering_scroll = QScrollArea()
        rendering_scroll.setFrameShape(QFrame.NoFrame)
        rendering_scroll.setWidgetResizable(True)
        rendering_scroll.setWidget(rendering)
        right.addTab(rendering_scroll, "Viewport")
        splitter.setSizes([280, 800, 420])

        timeline = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_play)
        timeline.addWidget(self.play_button)
        self.start_frame = QDoubleSpinBox()
        self.end_frame = QDoubleSpinBox()
        self.frame = QDoubleSpinBox()
        for spin in (self.start_frame, self.end_frame, self.frame):
            spin.setRange(-2 ** 31, 2 ** 31 - 1)
            spin.setKeyboardTracking(False)
        self.frame.valueChanged.connect(self.frame_changed)
        timeline.addWidget(QLabel("Frame"))
        timeline.addWidget(self.frame)
        self.timeline = Timeline()
        self.timeline.timeChanged.connect(self.scrub_frame)
        self.timeline.setVisible(self.application_settings.timeline_visible())
        timeline.addWidget(self.timeline, 1)
        timeline.addWidget(QLabel("Range"))
        timeline.addWidget(self.start_frame)
        timeline.addWidget(self.end_frame)
        range_button = QPushButton("Set range")
        range_button.clicked.connect(lambda: self.safe(lambda: self.execute("set_frame_range", self.start_frame.value(), self.end_frame.value())))
        timeline.addWidget(range_button)
        self.stats = QLabel("Renderer stopped")
        timeline.addWidget(self.stats)
        layout.addLayout(timeline)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log_dock = QDockWidget("Activity log", self)
        self.log_dock.setWidget(self.log)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

    def safe(self, callback):
        try:
            return callback()
        except Exception as exc:
            self.log.appendPlainText(str(exc))
            QMessageBox.warning(self, "OmniLab", str(exc))
            return None

    def discard_guard(self):
        if not self.document.dirty:
            return True
        response = QMessageBox.question(self, "Unsaved edits", "Save changes before continuing?",
                                        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if response == QMessageBox.Save:
            return bool(self.safe(self.save))
        return response == QMessageBox.Discard

    def install_document(self, document):
        document.revision = max(document.revision, self.document.revision + 1)
        if getattr(self, 'material_editor', None):
            self.material_editor.shutdown()
            self.material_editor.deleteLater()
            self.material_editor = None
        self.play_timer.stop()
        self.play_button.setText("Play")
        self.document = document
        self.viewport.document = document
        self.viewport.camera = ViewCamera.from_dict(document.view.get("camera", {}))
        self.viewport.camera.up_axis = str(UsdGeom.GetStageUpAxis(document.stage))
        if not document.view:
            self.viewport.camera.frame(document.bounds())
        self.viewport.scene_camera_path = document.view.get("scene_camera", "")
        transform_options = document.view.get('transform_authoring', {})
        with QSignalBlocker(self.quaternion_check), QSignalBlocker(self.matrix_output):
            self.quaternion_check.setChecked(bool(transform_options.get('quaternion', False)))
            self.matrix_output.setChecked(bool(transform_options.get('output_as_matrix', False)))
        self.update_rotation_ui()
        preferences = document.view.get("viewport", {})
        mode = preferences.get("mode", MODES[0])
        self.mode.setCurrentText(mode if mode in MODES[:2] else MODES[0])
        self.samples.setValue(int(preferences.get("samples", 16)))
        display = preferences.get("display", "Shaded")
        if display == "Wireframe":  # Projects saved before the two wireframe choices.
            display = "Shaded Wireframe"
        self.display.setCurrentIndex(max(0, self.display.findText(display)))
        self.ortho.setChecked(self.viewport.camera.orthographic)
        for name, check in self.purposes.items():
            check.setChecked(name in preferences.get("purposes", ("default", "render")))
        self.viewport.image = QImage()
        self.viewport.message = "Waiting for ovRTX" if self.render_enabled else "Renderer stopped"
        self.snapshot = None
        self.refresh()
        if (self.render_enabled and not getattr(self, 'final_render_active', False)
                and getattr(self.bridge, 'config', {}) != document.view.get('renderer_config', {})):
            self.restart_renderer()
        self.schedule_view()

    def new_document(self):
        if self.discard_guard():
            self.install_document(Document())

    def new_demo(self, material="openpbr"):
        if self.discard_guard():
            self.install_document(demo_document(material))
            self.viewport.camera = ViewCamera(target=[-.5, .8, 0], distance=12, yaw=24, pitch=18)
            self.schedule_view()

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open USD or OmniLab project", "", "USD / OmniLab (*.usd *.usda *.usdc *.usdz *.omnilab)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        if self.discard_guard():
            self.install_document(Document.open(path))
            self.log.appendPlainText("Opened " + str(path))

    def save(self, save_as=False):
        path = self.document.path
        if save_as or not path:
            path, selected = QFileDialog.getSaveFileName(self, "Save document", path or "Untitled.usda",
                "USD composition (*.usda *.usd *.usdc);;OmniLab project (*.omnilab)")
            if not path:
                return False
            if not Path(path).suffix:
                path += ".omnilab" if "project" in selected else ".usda"
        self.capture_view_preferences()
        self.document.save(path)
        self.refresh_title()
        self.log.appendPlainText("Saved " + path)
        return True

    def capture_view_preferences(self):
        if getattr(self, 'render_view', None):
            self.render_view.save_preferences()
        if getattr(self, 'material_editor', None):
            self.material_editor.preview.save_state()
        self.document.view.update(camera=self.viewport.camera.to_dict(), scene_camera=self.viewport.scene_camera_path,
            viewport=dict(mode=self.mode.currentText(), samples=self.samples.value(), display=self.display.currentText(),
                          purposes=[name for name, check in self.purposes.items() if check.isChecked()]))

    def relaunch(self):
        if self.relaunching:
            return
        console = getattr(self, 'python_console', None)
        view = getattr(self, 'render_view', None)
        materials = getattr(self, 'material_editor', None)
        if console and console.running:
            raise ValueError('Stop or finish the Python cell before relaunching.')
        if view and view.job and view.job.active:
            raise ValueError('Cancel or finish the final render before relaunching.')
        if materials and materials.loading_module:
            raise ValueError('Wait for the MDL module to finish loading before relaunching.')
        from omnilab.core.relaunch import write_checkpoint
        import sys
        self.capture_view_preferences()
        state = dict(material_editor=bool(materials and materials.isVisible()),
                     preview=bool(materials and materials.preview.enabled),
                     console=console.code.toPlainText() if console else None,
                     console_visible=bool(console and console.isVisible()),
                     render_view=bool(view and view.isVisible()))
        checkpoint = write_checkpoint(self.document, state)
        arguments = ['-m', 'omnilab.app', '--resume-session', str(checkpoint)]
        if not self.render_enabled:
            arguments.append('--no-render')
        started, _ = QProcess.startDetached(sys.executable, arguments, str(Path.cwd()))
        if not started:
            raise OSError('Could not launch OmniLab. This window remains open; checkpoint: ' + str(checkpoint))
        self.relaunching = True
        self.close()

    def restore_workspace(self, state):
        if state.get('material_editor'):
            self.open_material_editor(follow_selection=False)
            if state.get('preview') and self.material_editor.current():
                self.material_editor.preview.start()
        if state.get('render_view'):
            self.open_render_view()
        if state.get('console') is not None:
            self.open_python_console()
            self.python_console.code.setPlainText(state['console'])
            self.python_console.setVisible(state.get('console_visible', False))
        self.log.appendPlainText('Relaunched OmniLab; document restored. Undo and Python execution state start fresh.')
        self.refresh_title()

    def export_flattened(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export flattened USD", "flattened.usda", "USD (*.usda *.usd *.usdc)")
        if path:
            self.document.edits.export(path, self.document.retained, flattened=True)

    def publish_asset(self):
        from omnilab.usd.usd_asset_publish import publish_asset
        path = self.selected_path()
        if not path or path == '/':
            raise ValueError('Select a prim to publish.')
        directory = QFileDialog.getExistingDirectory(self, 'Publish into a new asset directory')
        if not directory:
            return
        name, ok = QInputDialog.getText(self, 'Asset name', 'New directory and asset name', text=path.rsplit('/', 1)[-1])
        if not ok:
            return
        options = json_dialog(self, 'Publish options', dict(placement='local', layout='single'))
        if options is None:
            return
        result = publish_asset(self.document.stage, path, directory, name, frame=self.document.frame,
                               placement=options['placement'], layout=options['layout'], progress=self.log.appendPlainText)
        self.log.appendPlainText('Published asset: ' + result['path'])
        self.log_dock.show()

    def reload(self):
        if self.document.path:
            self.open_path(self.document.path)

    def save_image(self):
        if self.viewport.image.isNull():
            raise ValueError("No viewport image is available yet.")
        path, _ = QFileDialog.getSaveFileName(self, "Save viewport image", "viewport.png", "PNG (*.png)")
        if path and not self.viewport.image.save(path):
            raise ValueError("Could not write the viewport image.")

    def refresh_title(self):
        self.setWindowTitle(f"{Path(self.document.path).name if self.document.path else 'Untitled'}{' *' if self.document.dirty else ''} — OmniLab")
        state = self.document.edits.state()
        self.undo_action.setText("Undo " + state["undo"])
        self.undo_action.setEnabled(bool(state["undo"]))
        self.redo_action.setText("Redo " + state["redo"])
        self.redo_action.setEnabled(bool(state["redo"]))

    def refresh(self):
        self._refreshing = True
        try:
            self.refresh_title()
            self.refresh_tree()
            self.refresh_layers()
            self.refresh_properties()
            self.frame.setValue(self.document.frame)
            self.start_frame.setValue(self.document.stage.GetStartTimeCode())
            self.end_frame.setValue(self.document.stage.GetEndTimeCode())
            self.timeline.set_range(self.document.stage.GetStartTimeCode(), self.document.stage.GetEndTimeCode(),
                                    self.document.frame, self.frame.decimals())
            selected_camera = self.viewport.scene_camera_path
            with QSignalBlocker(self.cameras):
                self.cameras.clear()
                self.cameras.addItem("Free camera", "")
                for prim in self.document.stage.Traverse():
                    if prim.IsA(UsdGeom.Camera):
                        self.cameras.addItem(str(prim.GetPath()), str(prim.GetPath()))
                index = self.cameras.findData(selected_camera)
                self.cameras.setCurrentIndex(max(0, index))
                if index < 0:
                    self.viewport.scene_camera_path = ""
        finally:
            self._refreshing = False
        self.viewport.update()

    def refresh_tree(self):
        if not hasattr(self, "tree"):
            return
        expanded = {path for path, item in getattr(self, "tree_items", {}).items() if item.isExpanded()}
        self.tree_items = {}
        with QSignalBlocker(self.tree):
            self.tree.clear()
            root = QTreeWidgetItem(["/", "Stage"])
            root.setData(0, Qt.UserRole, "/")
            self.tree.addTopLevelItem(root)
            self.tree_items["/"] = root
            root.setExpanded(True)
            query = self.filter.text().strip().lower()
            # Build ancestors of matches/selection; populate other branches lazily.
            visible = set()
            if query:
                for prim in self.document.stage.TraverseAll():
                    if query in (str(prim.GetPath()) + " " + prim.GetTypeName()).lower():
                        visible.update(str(p) for p in prim.GetPath().GetPrefixes())
            opened = expanded | {"/"}
            for path in self.document.selection:
                opened.update(str(p) for p in Sdf.Path(path).GetPrefixes()[:-1])
            def populate(parent, prim):
                for child in prim.GetFilteredChildren(Usd.PrimAllPrimsPredicate):
                    path = str(child.GetPath())
                    if query and path not in visible:
                        continue
                    item = self.prim_item(child)
                    parent.addChild(item)
                    if path in opened or query:
                        populate(item, child)
                        item.setExpanded(True)
            populate(root, self.document.stage.GetPseudoRoot())
            for path in self.document.selection:
                if path in self.tree_items:
                    self.tree_items[path].setSelected(True)
            if self.document.selection and self.document.selection[0] in self.tree_items:
                self.tree.setCurrentItem(self.tree_items[self.document.selection[0]], 0, QItemSelectionModel.NoUpdate)
        self.tree.resizeColumnToContents(0)

    def prim_item(self, prim):
        path = str(prim.GetPath())
        label = prim.GetName() + (" (inactive)" if not prim.IsActive() else "")
        item = QTreeWidgetItem([label, prim.GetTypeName() or prim.GetSpecifier().displayName])
        item.setData(0, Qt.UserRole, path)
        if prim.GetFilteredChildren(Usd.PrimAllPrimsPredicate):
            item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self.tree_items[path] = item
        return item

    def expand_item(self, item):
        if item.childCount():
            return
        prim = self.document.stage.GetPrimAtPath(item.data(0, Qt.UserRole))
        if prim:
            for child in prim.GetFilteredChildren(Usd.PrimAllPrimsPredicate):
                item.addChild(self.prim_item(child))

    def tree_selection(self):
        if self._refreshing:
            return
        self.document.select([item.data(0, Qt.UserRole) for item in self.tree.selectedItems()])
        self.refresh_properties()
        self.viewport.update()
        self.schedule_view(False)

    def refresh_layers(self):
        self.layer_rows = layer_entries(self.document.stage, self.document.edits, getattr(self.document.retained, "sources", {}))
        self.layers.clear()
        for row in self.layer_rows:
            item = QTreeWidgetItem([("→ " if row["active"] else "") + row["name"] + (" *" if row["modified"] else ""),
                                    "Muted" if row["muted"] else row["role"]])
            item.setData(0, Qt.UserRole, row["identifier"])
            item.setToolTip(0, row["identifier"] + "\n" + row["reason"])
            self.layers.addTopLevelItem(item)
        self.target_label.setText("Edit target: " + self.document.edits.layer.GetDisplayName())
        self.layers.resizeColumnToContents(0)

    def selected_path(self):
        return self.document.selection[0] if self.document.selection else "/"

    def refresh_properties(self):
        self.properties.setColumnHidden(1, not self.application_settings.show_property_types())
        path = self.selected_path()
        prim = self.document.stage.GetPrimAtPath(path)
        self.selection_label.setText(path)
        representation = 'trs' if self.quaternion_check.isChecked() else 'euler'
        info = pose_info(prim, self.document.frame, space=self.space.currentText().lower(), representation=representation) if prim and not prim.IsPseudoRoot() else {}
        for key, fields in self.transform_fields.items():
            default = [1, 1, 1] if key == 'scale' else [1, 0, 0, 0] if key == 'orient' else [0, 0, 0]
            values = info.get("values", {}).get(key, default)
            for field, value in zip(fields, values):
                field.setEnabled(info.get("editable", False))
                field.setValue(value)
                field.setToolTip(info.get("reason", ""))
        for editor in self.properties.findChildren(NumericEditor):
            editor.blockSignals(True)
        self.properties.clearContents()
        self.property_data = property_rows(prim, Usd.TimeCode(self.document.frame)) if prim else []
        self.properties.setRowCount(len(self.property_data))
        for row, data in enumerate(self.property_data):
            for column, key in enumerate(("name", "type", "value")):
                item = QTableWidgetItem(str(data[key]))
                item.setToolTip(f"{data['group']} · {data.get('source', '')}\n{data['value']}")
                self.properties.setItem(row, column, item)
            value = prim.GetAttribute(data['name']).Get(Usd.TimeCode(self.document.frame)) if data['group'] == 'Attributes' else data['value']
            editor = numeric_editor(data['type'], value, self.application_settings)
            if editor is not None and not data.get('connections'):
                editor.setEnabled(data['editable'])
                editor.setToolTip(self.properties.item(row, 2).toolTip() + '\nEnter or leave the field to commit; Escape cancels.')
                context = dict(path=path, group=data['group'], name=data['name'], frame=self.document.frame)
                document, revision = self.document, self.document.revision
                editor.committed.connect(lambda value, context=context, document=document, revision=revision:
                    self.safe(lambda: self.set_numeric_property(document, revision, context, value)), Qt.QueuedConnection)
                self.properties.setCellWidget(row, 2, editor)
            elif editor is not None:
                editor.deleteLater()
        self.properties.setColumnWidth(0, 130)
        self.properties.setColumnWidth(1, 75)

    def set_numeric_property(self, document, revision, context, value):
        if self.document is not document or document.revision != revision:
            return  # An old widget must not overwrite a newer edit or Undo.
        try:
            self.execute('set_property', dict(context, value=value,
                time='frame' if self.time_mode.currentIndex() else 'default'))
        except Exception:
            self.refresh_properties()
            raise

    def open_application_settings(self):
        dialog = ApplicationSettingsDialog(self.application_settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.viewport.show_orientation_gizmo = self.application_settings.show_orientation_gizmo()
            self.viewport.update()
            self.refresh_properties()
            editor = getattr(self, 'material_editor', None)
            if editor:
                for index in range(editor.tabs.count()):
                    panel = editor.tabs.widget(index)
                    panel.inspect(panel.current_node)

    def execute(self, name, *args, **kwargs):
        result = self.document.command(name, *args, **kwargs)
        if name in ("add_prim", "duplicate_prim", "reparent_prim") and isinstance(result, str):
            self.document.select([result])
        # Only the renderer-probed shader inputs use a fast path. Structural edits,
        # animation, connections, undo and all other attributes republish a snapshot.
        delta = None
        if name == "set_property" and self.snapshot is not None and not self.snapshot_dirty:
            data = args[0]
            if data.get("group") == "Attributes" and data["name"] in ("inputs:base_color", "inputs:diffuse_color_constant"):
                prim = self.document.stage.GetPrimAtPath(data["path"])
                attr = prim.GetAttribute(data["name"])
                if prim.GetTypeName() == "Shader" and attr.GetTypeName() == Sdf.ValueTypeNames.Color3f and not attr.HasAuthoredConnections() and not attr.ValueMightBeTimeVarying():
                    delta = dict(path=data["path"], attribute=data["name"], value=list(attr.Get(Usd.TimeCode(self.document.frame))), dtype="float32", lanes=3)
        if delta:
            self.deltas[delta["path"] + "." + delta["attribute"]] = delta
        self.refresh()
        self.refresh_material_tabs()
        self.schedule_view(snapshot=delta is None)
        return result

    def refresh_material_tabs(self):
        editor = getattr(self, 'material_editor', None)
        if editor is None:
            return
        from pxr import UsdShade
        for index in reversed(range(editor.tabs.count())):
            panel = editor.tabs.widget(index)
            if not UsdShade.Material(self.document.stage.GetPrimAtPath(panel.graph.path)):
                editor.close_tab(index)
            else:
                panel.reload()
        editor.current_changed()

    def apply_transform(self):
        rotation = 'orient' if self.quaternion_check.isChecked() else 'rotateXYZ'
        values = {key: [field.value() for field in self.transform_fields[key]] for key in ('translate', rotation, 'scale')}
        self.execute("set_transform", dict(path=self.selected_path(), values=values,
                    space=self.space.currentText().lower(), representation='trs' if rotation == 'orient' else 'euler', frame=self.document.frame,
                    output_as_matrix=self.matrix_output.isChecked(),
                    time="frame" if self.time_mode.currentIndex() else "default"))

    def update_rotation_ui(self):
        enabled = self.quaternion_check.isChecked()
        self.rotation_label.setText('Rotate WXYZ' if enabled else 'Rotate XYZ')
        self.rotation_fields.setCurrentIndex(int(enabled))

    def rotation_mode_changed(self, enabled):
        try:
            if enabled:
                values = quaternion_from_euler([field.value() for field in self.transform_fields['rotateXYZ']])
            else:
                q = checked_values({'orient': [field.value() for field in self.transform_fields['orient']]})['orient']
                values = euler_from_quaternion(q)
        except ValueError:
            with QSignalBlocker(self.quaternion_check):
                self.quaternion_check.setChecked(not enabled)
            raise
        for field, value in zip(self.transform_fields['orient' if enabled else 'rotateXYZ'], values):
            field.setValue(value)
        self.update_rotation_ui()
        self.store_transform_preferences()

    def store_transform_preferences(self, *_):
        self.document.view['transform_authoring'] = dict(quaternion=self.quaternion_check.isChecked(),
                                                       output_as_matrix=self.matrix_output.isChecked())

    def commit_viewport_transform(self, data):
        self.execute('set_transform', dict(data, output_as_matrix=self.matrix_output.isChecked(),
                     representation='trs' if self.quaternion_check.isChecked() else 'euler'))

    def preview_transform(self, data):
        if data is None:
            self.schedule_view()
            return
        before = Gf.Matrix4d(*[value for row in data['before'] for value in row])
        after = Gf.Matrix4d(*[value for row in data['matrix'] for value in row])
        from omnilab.render.deltas import transform_deltas
        self.deltas.update(transform_deltas(self.document, data['path'], before, after))
        self.schedule_view(False, interactive=True)

    def edit_property(self, row):
        data = self.property_data[row]
        if not data["editable"]:
            json_dialog(self, data["name"], data, readonly=True)
            return
        info = property_info(self.document.stage.GetPrimAtPath(self.selected_path()), data["group"], data["name"], Usd.TimeCode(self.document.frame))
        value = json_dialog(self, "Edit " + data["name"] + " (JSON)", info["value"])
        if value is not None:
            self.execute("set_property", dict(path=self.selected_path(), group=data["group"], name=data["name"], value=value,
                frame=self.document.frame, time="frame" if self.time_mode.currentIndex() else "default"))

    def create_prim(self, kind):
        name, ok = QInputDialog.getText(self, "Create " + kind, "Prim name", text=kind)
        if ok:
            self.execute("add_prim", self.selected_path(), name, kind)

    def duplicate(self):
        self.execute("duplicate_prim", self.selected_path(), "copy")

    def remove(self):
        self.execute("remove_prim", self.selected_path())

    def rename(self):
        path = self.selected_path()
        name, ok = QInputDialog.getText(self, "Rename prim", "Name", text=Sdf.Path(path).name)
        if ok:
            self.execute("reparent_prim", dict(path=path, parent=str(Sdf.Path(path).GetParentPath()), name=name, mode="namespace"))

    def bind_material(self):
        materials = [str(p.GetPath()) for p in self.document.stage.Traverse() if p.GetTypeName() == "Material"]
        if not materials:
            raise ValueError("This stage has no materials.")
        material, ok = QInputDialog.getItem(self, "Bind material", "Material", materials, editable=False)
        if ok:
            self.execute("bind_scene_material", material, self.document.selection)

    def open_render_view(self):
        from .render_view import RenderView
        if not getattr(self, 'render_view', None):
            self.render_view = RenderView(self)
        self.render_view.refresh_cameras()
        self.render_view.show()
        self.render_view.raise_()

    def open_python_console(self):
        from .python_console import PythonConsole
        if not getattr(self, 'python_console', None):
            self.python_console = PythonConsole(self)
        self.python_console.show()
        self.python_console.raise_()

    def toggle_mcp(self):
        bridge = getattr(self, 'mcp_bridge', None)
        if bridge:
            bridge.close()
            bridge.deleteLater()
            self.mcp_bridge = None
            self.mcp_action.setText('Start MCP')
            self.log.appendPlainText('MCP stopped.')
        else:
            from .mcp_bridge import EditorBridge
            self.mcp_bridge = EditorBridge(self)
            self.mcp_action.setText('Stop MCP')
            self.log.appendPlainText('MCP enabled for this editor: ' + self.mcp_bridge.editor_id)
            self.log.appendPlainText('Stdio client command: ' + str(Path(__file__).resolve().parents[4] / '.venv/bin/omnilab-mcp'))
            self.log_dock.show()

    def open_material_editor(self, *, follow_selection=True):
        from pxr import UsdShade
        from .material_editor import MaterialEditor
        if not getattr(self, 'material_editor', None):
            self.material_editor = MaterialEditor(self)
        editor = self.material_editor
        for path in self.document.selection if follow_selection else ():
            prim = self.document.stage.GetPrimAtPath(path)
            material = UsdShade.Material(prim)
            if not material:
                material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
            if material:
                editor.open_material(material.GetPath())
                break
        if not editor.tabs.count():
            for prim in self.document.stage.Traverse():
                if prim.IsA(UsdShade.Material):
                    editor.open_material(prim.GetPath())
                    break
        editor.show()
        editor.raise_()

    def prim_menu(self, position):
        path = self.selected_path()
        prim = self.document.stage.GetPrimAtPath(path)
        menu = QMenu(self)
        self.action(menu, "Rename…", self.rename)
        self.action(menu, "Duplicate", self.duplicate)
        self.action(menu, "Delete", self.remove)
        if prim and not prim.IsPseudoRoot():
            self.action(menu, "Deactivate" if prim.IsActive() else "Activate", lambda: self.execute("set_prim_active", path, not prim.IsActive()))
            self.action(menu, "Lock transforms", lambda: self.execute("set_transform_lock", path, True))
            self.action(menu, "Unlock transforms", lambda: self.execute("set_transform_lock", path, False))
            self.action(menu, "Set default prim", lambda: self.execute("set_default_prim", path))
            self.action(menu, "Convert to mesh", lambda: self.execute("convert_to_mesh", path))
            self.action(menu, "Load payload", lambda: self.execute("payload", path, True))
            self.action(menu, "Unload payload", lambda: self.execute("payload", path, False))
            self.action(menu, "Add composition arc…", self.add_arc)
            self.action(menu, "Apply API schema…", self.apply_schema)
            self.action(menu, "Inspect composition", self.inspect_composition)
            for variant in variant_choices(prim):
                submenu = menu.addMenu("Variant: " + variant["name"])
                for name in variant["variants"]:
                    action = self.action(submenu, name, lambda name=name, set_name=variant["name"]: self.execute("variant", path, "select", set_name, name))
                    action.setCheckable(True)
                    action.setChecked(name == variant["selection"])
            self.action(menu, "Create variant set…", self.create_variant)
            self.action(menu, "Add variant…", self.add_variant)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def create_variant(self):
        name, ok = QInputDialog.getText(self, "Create variant set", "Set name")
        if ok:
            self.execute("variant", self.selected_path(), "create", name)

    def add_variant(self):
        choices = [v["name"] for v in variant_choices(self.document.stage.GetPrimAtPath(self.selected_path()))]
        if not choices:
            raise ValueError("Create a variant set first.")
        set_name, ok = QInputDialog.getItem(self, "Add variant", "Set", choices, editable=False)
        if ok:
            name, ok = QInputDialog.getText(self, "Add variant", "Variant name")
            if ok:
                self.execute("variant", self.selected_path(), "add", set_name, name)

    def add_arc(self):
        value = json_dialog(self, "Add composition arc", dict(path=self.selected_path(), kind="reference", asset="", prim_path=""))
        if value is not None:
            self.execute("add_arc", value)

    def apply_schema(self):
        from omnilab.usd.usd_schemas import schema_choices
        choices = [v["name"] for v in schema_choices(self.document.stage.GetPrimAtPath(self.selected_path())) if v["enabled"]]
        name, ok = QInputDialog.getItem(self, "Apply USD API schema", "Schema", choices, editable=False)
        if ok:
            instance = ""
            if Usd.SchemaRegistry().IsMultipleApplyAPISchema(name):
                instance, ok = QInputDialog.getText(self, "Instance name", "Instance")
            if ok:
                self.execute("apply_schema", self.selected_path(), name, instance)

    def inspect_composition(self):
        from omnilab.usd.usd_composition_inspection import inspect_composition
        json_dialog(self, "Composition", inspect_composition(self.document.stage, self.selected_path(), "arcs", Usd.TimeCode(self.document.frame)), readonly=True)

    def set_target(self, identifier):
        self.document.edits.set_edit_target(identifier)
        self.refresh_layers()

    def layer_menu(self, position):
        item = self.layers.itemAt(position)
        if not item:
            return
        row = next(row for row in self.layer_rows if row["identifier"] == item.data(0, Qt.UserRole))
        identifier = row["identifier"]
        menu = QMenu(self)
        self.action(menu, "Set edit target", lambda: self.set_target(identifier)).setEnabled(row["editable"])
        self.action(menu, "Unmute" if row["muted"] else "Mute", lambda: self.execute("set_layer_muted", identifier, not row["muted"])).setEnabled(row["can_mute"])
        self.action(menu, "Inspect layer text", lambda: json_dialog(self, row["name"], layer_text(self.document.stage, identifier, self.document.edits), readonly=True))
        self.action(menu, "Edit sublayer order / offsets…", lambda: self.edit_sublayers(row)).setEnabled(row["editable"])
        self.action(menu, "New in-memory sublayer…", lambda: self.new_sublayer(identifier)).setEnabled(row["editable"])
        menu.exec(self.layers.viewport().mapToGlobal(position))

    def edit_sublayers(self, row):
        values = json_dialog(self, "Sublayers (strongest first)", row["sublayers"])
        if values is not None:
            self.execute("set_sublayers", dict(identifier=row["identifier"], sublayers=values, expected=row["sublayers"]))

    def new_sublayer(self, identifier):
        from omnilab.usd.usd_composition import sublayer_entries
        expected = sublayer_entries(Sdf.Layer.Find(identifier))
        name, ok = QInputDialog.getText(self, "New sublayer", "Name", text="edits.usda")
        if ok:
            self.execute("create_sublayer", dict(identifier=identifier, storage="memory", name=name, expected=expected))

    def tool_changed(self, index):
        self.viewport.set_tool(("translate", "orient", "scale")[index])

    def select_transform_tool(self, index):
        self.tool.setCurrentIndex(index)
        self.viewport.set_tool(('translate', 'orient', 'scale')[index])
        self.viewport.setFocus(Qt.ShortcutFocusReason)
        self.viewport.update()

    def space_changed(self, value):
        self.viewport.space = value.lower()
        self.refresh_properties()
        self.viewport.update()

    def overlay(self, key, value):
        setattr(self.viewport, key, value)
        self.viewport.update()

    def display_changed(self, value):
        self.viewport.display = value
        self.schedule_view()

    def camera_changed(self):
        if self._refreshing:
            return
        self.viewport.scene_camera_path = self.cameras.currentData() or ""
        self.schedule_view()

    def projection_changed(self, enabled):
        self.viewport.camera.orthographic = enabled
        self.schedule_view()

    def navigation_changed(self):
        self.cameras.blockSignals(True)
        self.cameras.setCurrentIndex(max(0, self.cameras.findData(self.viewport.scene_camera_path)))
        self.cameras.blockSignals(False)
        self.schedule_view(False, interactive=True)

    def frame_selection(self, all_prims=False):
        self.viewport.scene_camera_path = ""
        self.viewport.camera.frame(self.document.bounds([] if all_prims else self.document.selection))
        self.viewport.update()
        self.schedule_view(False)

    def frame_changed(self, frame):
        if self._refreshing:
            return
        self.document.frame = frame
        self.timeline.set_time(frame)
        self.refresh_properties()
        self.refresh_material_tabs()
        self.schedule_view()

    def scrub_frame(self, frame):
        if self.play_timer.isActive():
            self.toggle_play()
        self.frame.setValue(frame)

    def set_timeline_visible(self, visible):
        self.timeline.setVisible(visible)
        self.application_settings.set_timeline_visible(visible)

    def toggle_play(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.play_button.setText("Play")
        else:
            self.play_timer.start(max(16, round(1000 / self.document.stage.GetTimeCodesPerSecond())))
            self.play_button.setText("Pause")

    def play_step(self):
        # Advance after presentation, avoiding an unbounded queue of scene snapshots.
        if self.render_enabled and self.presented_request != self.request:
            return
        frame = self.frame.value() + 1
        self.frame.setValue(self.start_frame.value() if frame > self.end_frame.value() else frame)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "viewport"):
            self.schedule_view()

    def schedule_view(self, snapshot=True, *, interactive=False):
        self.request += 1
        self.viewport.depth_current = False
        self.viewport.visible_purposes = {name for name, check in self.purposes.items() if check.isChecked()}
        # Camera-only motion may present an intermediate view while the newest
        # camera waits. Scene/settings/selection changes invalidate all old images.
        if not interactive or snapshot:
            self.frame_floor = self.request
        self.snapshot_dirty = self.snapshot_dirty or snapshot
        self.viewport.message = "Updating viewport…" if self.render_enabled else "Renderer stopped"
        self.viewport.update()
        if self.render_enabled and not self.publish_timer.isActive():
            self.publish_timer.start()

    def flush_view(self):
        self.publish_timer.stop()
        if (not self.render_enabled or not self.renderer_ready or self.inflight_request is not None
                or self.submitted_request == self.request):
            return
        try:
            camera = self.viewport.render_camera()
            if self.snapshot_dirty or self.snapshot is None:
                self.snapshot_number += 1
                w = min(960, max(320, self.viewport.width()))
                h = max(1, round(w * self.viewport.height() / max(1, self.viewport.width())))
                started = time.perf_counter()
                self.snapshot = publish(self.document, Path(self.scratch.name) / str(self.snapshot_number), camera,
                    (w, h), self.mode.currentText(), self.samples.value(),
                    tuple(name for name, check in self.purposes.items() if check.isChecked()),
                    aovs=('LdrColor', 'DistanceToCameraSD') if self.display.currentText() in ('Points', 'Wire over Shaded') else ('LdrColor',),
                    wireframe=self.display.currentText() in ("Shaded Wireframe", "Unlit Wireframe"),
                    wireframe_mode="emissive" if self.display.currentText() == "Unlit Wireframe" else "shaded")
                self.deltas = {}
                self.publication_ms = (time.perf_counter() - started) * 1000
                self.snapshot_dirty = False
            self.bridge.send(dict(type="view", request=self.request, snapshot=self.snapshot,
                                  camera=camera_payload(camera), deltas=dict(self.deltas), selection=[p for p in self.document.selection if p != "/"]))
            self.submitted_request = self.request
            self.inflight_request = self.request
        except Exception as exc:
            self.viewport.message = "Publication failed; see Activity log"
            self.log.appendPlainText(str(exc))
            self.log_dock.show()

    def renderer_event(self, message):
        if message.get("epoch") != self.bridge.epoch:
            return
        kind = message["type"]
        if kind == "ready":
            self.renderer_ready = True
            self.flush_view()
        elif kind == "status":
            self.log.appendPlainText(message["text"])
            self.stats.setText(message["text"])
        elif kind == 'loaded':
            from omnilab.render.snapshot import retire_snapshots
            retire_snapshots(self.scratch.name, message['path'])
        elif kind == "frame":
            self.bridge.send(dict(type="ack"))
            request = message["request"]
            if request == self.inflight_request:
                self.inflight_request = None
            if self.request != self.submitted_request and not self.publish_timer.isActive():
                self.publish_timer.start()
            if (request != self.submitted_request or request < self.frame_floor
                    or request < self.presented_request):
                self.stale_frame_count += 1
                return
            self.viewport.set_frame(dict(message, depth_current=request == self.request))
            self.presented_request = request
            self.frame_count += 1
            self.stats.setText(f"ovRTX · {message['milliseconds']:.1f} ms · publish {self.publication_ms:.1f} ms")
            if message["hits"] is not None and request == self.request:
                paths = [hit["path"] for hit in message["hits"]]
                self.document.select((self.document.selection if message["additive"] else []) + paths)
                self.refresh_tree()
                self.refresh_properties()
                self.schedule_view(False)
        elif kind in ("error", "stopped"):
            self.renderer_ready = False
            self.inflight_request = None
            self.stats.setText("Renderer stopped — use View → Restart renderer")
            self.viewport.message = self.stats.text()
            self.log.appendPlainText(message.get("text", self.stats.text()))
            self.log_dock.show()
        self.viewport.update()

    def pick(self, rect, additive):
        if self.renderer_ready and self.presented_request == self.request:
            self.bridge.send(dict(type="pick", request=self.request, rect=rect, additive=additive))

    def restart_renderer(self):
        if getattr(self, "final_render_active", False):
            raise ValueError("The viewport resumes after the final render finishes.")
        self.renderer_ready = False
        self.inflight_request = None
        self.submitted_request = None
        self.render_enabled = True
        self.bridge.start(self.document.view.get('renderer_config', {}))
        self.schedule_view()

    def stop_renderer(self):
        self.render_enabled = False
        self.renderer_ready = False
        self.inflight_request = None
        self.publish_timer.stop()
        self.play_timer.stop()
        self.play_button.setText("Play")
        self.bridge.stop()
        self.stats.setText("Renderer stopped")
        self.viewport.message = "Renderer stopped — document edits are preserved"
        self.viewport.update()

    def show_renderer_logs(self):
        for name in ("worker.log", "ovrtx.log"):
            path = self.bridge.directory / name
            if path.exists():
                self.log.appendPlainText(path.read_text(errors="replace")[-40000:])
        self.log_dock.show()

    def settings_catalog(self):
        from .settings_editor import SettingsEditor
        dialog = SettingsEditor(self)
        dialog.exec()
        return
    def about(self):
        QMessageBox.information(self, "OmniLab preview", "Qt USD editor + native ovRTX worker.\n\n"
            "Alt+left drag: orbit; middle drag: pan; wheel: dolly.\nF: frame selection; Shift+F: frame all.\n"
            "W/E/R: translate/rotate/scale. Drag an axis; Escape cancels.\nClick or drag a rectangle to select; Ctrl adds.\n"
            "Double-click properties to edit typed JSON.\n\nCtrl+M: MaterialX / MDL graph editor. F6: final RenderView.\nMoonRay graph conversion remains P7.")

    def closeEvent(self, event):
        if not self.relaunching and not self.discard_guard():
            event.ignore()
            return
        self.publish_timer.stop()
        self.play_timer.stop()
        if getattr(self, 'material_editor', None):
            self.material_editor.shutdown()
        if getattr(self, "render_view", None):
            self.render_view.shutdown()
        if getattr(self, 'python_console', None):
            self.python_console.close()
        if getattr(self, 'mcp_bridge', None):
            self.mcp_bridge.close()
        self.bridge.stop()
        self.scratch.cleanup()
        event.accept()
