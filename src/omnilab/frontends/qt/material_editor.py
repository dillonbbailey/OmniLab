"""Material tabs with a typed node canvas, inspector and native preview studio."""
import json
import threading
from pathlib import Path
from importlib.util import find_spec

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLineEdit, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QTabBar, QPushButton, QLabel, QCheckBox, QFileDialog, QInputDialog, QColorDialog,
    QMessageBox, QMenu, QSizePolicy, QHeaderView)
from pxr import Sdf, UsdShade

from omnilab.materials.catalog import default_catalog, material_section
from omnilab.materials.graph import MaterialGraph, create_material
from omnilab.materials.exchange import export_materialx, import_materialx
from .material_canvas import GraphCanvas
from .material_preview import MaterialPreview
from .texture_preview import TexturePreview
from .labels import ElidedLabel
from .application_settings import ApplicationSettings
from .numeric_editor import NumericEditor, numeric_editor
from .value_menu import copy_value, install_editor_menu


def parameter_text(value):
    if isinstance(value, float):
        return f'{value:.6g}'
    if isinstance(value, (tuple, list)):
        return '[' + ', '.join(parameter_text(item) for item in value) + ']'
    return json.dumps(value)


class GraphPanel(QWidget):
    changed = Signal()

    def __init__(self, graph, parent=None, *, application_settings=None):
        super().__init__(parent)
        self.graph = graph
        self.application_settings = application_settings if application_settings is not None else ApplicationSettings()
        self.current_node = ''
        self.initial_frame_pending = True
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        for label, command in [('Undo', 'undo'), ('Redo', 'redo'), ('Copy', 'copy'), ('Paste', 'paste'),
                               ('Duplicate', 'duplicate'), ('Delete', 'delete'), ('Arrange', 'arrange')]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, command=command: self.command(command))
            toolbar.addWidget(button)
        ports = QCheckBox('All ports')
        ports.toggled.connect(self.show_ports)
        toolbar.addWidget(ports)
        layout.addLayout(toolbar)
        splitter = self.splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        library = QWidget()
        library.setMinimumWidth(245)
        library_layout = QVBoxLayout(library)
        self.library_sections = QTabBar()
        for name in ('OpenPBR', 'MDL', 'MaterialX'):
            self.library_sections.addTab(name)
        library_layout.addWidget(self.library_sections)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find nodes: image, noise, mix…')
        library_layout.addWidget(self.search)
        self.library = QListWidget()
        library_layout.addWidget(self.library)
        splitter.addWidget(library)
        self.canvas = GraphCanvas()
        self.canvas.setMinimumWidth(280)
        splitter.addWidget(self.canvas)
        inspector = self.inspector = QWidget()
        inspector.setMinimumWidth(275)
        inspector_layout = QVBoxLayout(inspector)
        self.node_name = ElidedLabel('Select a node')
        inspector_layout.addWidget(self.node_name)
        self.node_identifier = ElidedLabel()
        inspector_layout.addWidget(self.node_identifier)
        self.parameters = QTreeWidget()
        self.parameters.setHeaderLabels(['Input', 'Type', 'Value'])
        self.parameters.header().setSectionResizeMode(QHeaderView.Interactive)
        self.parameters.header().setStretchLastSection(True)
        self.parameters.setContextMenuPolicy(Qt.CustomContextMenu)
        self.parameters.customContextMenuRequested.connect(self.parameter_menu)
        inspector_layout.addWidget(self.parameters)
        self.texture_preview = TexturePreview()
        inspector_layout.addWidget(self.texture_preview)
        self.diagnostics = QLabel()
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        inspector_layout.addWidget(self.diagnostics)
        splitter.addWidget(inspector)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([245, 495, 320])
        nodes = graph.nodes()
        section = material_section(nodes[0]['identifier'], nodes[0]['framework']) if nodes else 'OpenPBR'
        self.library_sections.setCurrentIndex({'OpenPBR': 0, 'MDL': 1, 'MaterialX': 2}.get(section, 2))
        self.library_sections.currentChanged.connect(self.refresh_library)
        self.search.textChanged.connect(self.refresh_library)
        self.library.itemDoubleClicked.connect(self.add_node)
        self.canvas.selectionChanged.connect(self.inspect)
        self.canvas.connected.connect(lambda *args: self.edit(lambda: graph.connect(*args)), Qt.QueuedConnection)
        self.canvas.disconnected.connect(lambda *args: self.edit(lambda: graph.disconnect(*args)), Qt.QueuedConnection)
        self.canvas.terminalRequested.connect(self.set_terminal, Qt.QueuedConnection)
        self.canvas.positionsChanged.connect(lambda positions: self.edit(lambda: graph.move(positions)), Qt.QueuedConnection)
        self.canvas.commandRequested.connect(self.command, Qt.QueuedConnection)
        self.canvas.renamed.connect(self.rename, Qt.QueuedConnection)
        self.parameters.itemDoubleClicked.connect(lambda item, column: self.edit_parameter(item))
        self.refresh_library()
        self.reload()

    def showEvent(self, event):
        super().showEvent(event)
        if self.initial_frame_pending:
            self.initial_frame_pending = False
            QTimer.singleShot(0, self.canvas.frame_nodes)

    def error(self, error):
        QMessageBox.warning(self, 'Material graph', str(error))

    def edit(self, callback):
        try:
            result = callback()
            self.reload()
            self.changed.emit()
            return result
        except Exception as error:
            self.error(error)

    def reload(self):
        selected = self.canvas.selected_paths()
        self.canvas.load(self.graph.nodes(), selected)
        self.inspect(selected[0] if selected else '')
        self.diagnostics.setText('\n'.join(self.graph.diagnostics()[:10]))

    def refresh_library(self):
        self.library.clear()
        definitions = self.graph.catalog.search(self.search.text())
        section = self.library_sections.tabText(self.library_sections.currentIndex())
        definitions = [d for d in definitions if material_section(d.identifier, d.framework) == section]
        self.library.setToolTip('Load an MDL module from the MDL menu to populate this section.' if section == 'MDL' else section + ' nodes')
        definitions.sort(key=lambda d: (d.identifier != 'ND_open_pbr_surface_surfaceshader', d.category, d.identifier))
        for definition in definitions:
            item = QListWidgetItem(definition.label + ' · ' + ', '.join(p.type for p in definition.outputs.values()))
            item.setData(Qt.UserRole, definition.identifier)
            item.setToolTip(definition.identifier + '\n' + definition.metadata.get('doc', ''))
            self.library.addItem(item)

    def add_node(self, item):
        point = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        self.edit(lambda: self.graph.add_node(item.data(Qt.UserRole), position=(point.x(), point.y())))

    def show_ports(self, enabled):
        self.canvas.all_ports = enabled
        self.reload()

    def inspect(self, path):
        self.parameters.setColumnHidden(1, not self.application_settings.show_property_types())
        self.current_node = path
        for editor in self.parameters.findChildren(NumericEditor):
            editor.blockSignals(True)
        self.parameters.clear()
        node = next((n for n in self.graph.nodes() if n['path'] == path), None)
        if not node:
            self.node_name.setText('Select a node')
            self.node_identifier.clear()
            self.texture_preview.show_texture()
            return
        section = material_section(node['identifier'], node['framework'])
        self.node_name.setText(section + ' · ' + node['name'])
        self.node_identifier.setText(node['identifier'])
        for name, port in node['inputs'].items():
            if port['type'] in ('filename', 'asset') and port.get('value'):
                asset = self.graph.shader(path).GetInput(name).Get()
                if isinstance(asset, Sdf.AssetPath):
                    self.texture_preview.show_texture(asset.resolvedPath or asset.path, port.get('colorspace') == 'raw')
                    break
        else:
            self.texture_preview.show_texture()
        groups = {}
        for name, port in node['inputs'].items():
            group = port['metadata'].get('uifolder', 'Inputs')
            if group not in groups:
                groups[group] = QTreeWidgetItem([group])
                self.parameters.addTopLevelItem(groups[group])
            value = port['connection'] or parameter_text(port['value'])
            item = QTreeWidgetItem([port['metadata'].get('uiname', name), port['type'], value])
            item.setData(0, Qt.UserRole, name)
            item.setToolTip(0, port['metadata'].get('doc', name))
            item.setToolTip(2, 'Double-click to edit; right-click for raw values or connections.\n' + (port['connection'] or json.dumps(port['value'])))
            groups[group].addChild(item)
            if not port['connection'] or port['type'] in ('color3', 'color3f'):
                editor = numeric_editor(port['type'], port['value'], self.application_settings)
                if editor is not None:
                    editor.setEnabled(not port['connection'])
                    install_editor_menu(editor, lambda value=port['value']: value)
                    editor.setToolTip(item.toolTip(2) + '\nEnter or leave the field to commit; Escape cancels.')
                    revision = self.graph.document.revision
                    editor.committed.connect(lambda value, path=path, name=name, revision=revision:
                        self.set_numeric_parameter(path, name, value, revision), Qt.QueuedConnection)
                    self.parameters.setItemWidget(item, 2, editor)
        self.parameters.expandAll()
        self.parameters.setColumnWidth(0, 155)
        self.parameters.setColumnWidth(1, 70)

    def set_numeric_parameter(self, path, name, value, revision):
        if self.graph.document.revision != revision:
            return
        try:
            self.graph.set_value(path, name, value)
        except Exception as error:
            self.inspect(self.current_node)
            self.error(error)
            return
        self.reload()
        self.changed.emit()

    def edit_parameter(self, item, raw=False):
        name = item.data(0, Qt.UserRole)
        if not name or not self.current_node:
            return
        node = next(n for n in self.graph.nodes() if n['path'] == self.current_node)
        port = node['inputs'][name]
        value = port['value']
        if port['type'] in ('filename', 'asset') and not raw:
            value, _ = QFileDialog.getOpenFileName(self, 'Texture', value or '', 'Images (*)')
            if not value:
                return
            colorspace, ok = QInputDialog.getItem(self, 'Texture colorspace', 'Source colorspace',
                ['auto', 'srgb_texture', 'lin_rec709', 'raw'], editable=True)
            if ok:
                self.edit(lambda: self.graph.set_value(self.current_node, name, value, colorspace))
            return
        if port['type'] in ('color3', 'color3f') and value is not None and not raw:
            color = QColorDialog.getColor(QColor.fromRgbF(*[max(0, min(1, v)) for v in value]), self, 'Color (raw values via right-click)')
            if not color.isValid():
                return
            value = [color.redF(), color.greenF(), color.blueF()]
        else:
            text, ok = QInputDialog.getText(self, 'Edit ' + name, port['type'] + ' · JSON value', text=json.dumps(value))
            if not ok:
                return
            try:
                value = json.loads(text)
            except ValueError as error:
                self.error(error)
                return
        self.edit(lambda: self.graph.set_value(self.current_node, name, value))

    def parameter_menu(self, point):
        item = self.parameters.itemAt(point)
        if not item or not item.data(0, Qt.UserRole):
            return
        menu = QMenu(self)
        name = item.data(0, Qt.UserRole)
        node = next(n for n in self.graph.nodes() if n['path'] == self.current_node)
        menu.addAction('Copy values', lambda: copy_value(node['inputs'][name]['value']))
        menu.addAction('Edit raw value…', lambda: self.edit_parameter(item, True))
        menu.addAction('Disconnect input', lambda: self.edit(lambda: self.graph.disconnect(self.current_node, item.data(0, Qt.UserRole))))
        menu.exec(self.parameters.viewport().mapToGlobal(point))

    def set_terminal(self, path, output):
        shader = self.graph.shader(path)
        kind, _ = self.graph._port(shader, output, True)
        terminal = {'surfaceshader': 'surface', 'volumeshader': 'volume', 'displacementshader': 'displacement'}.get(kind, 'surface')
        self.edit(lambda: self.graph.set_terminal(path, output, terminal))

    def rename(self, path):
        name, ok = QInputDialog.getText(self, 'Rename node', 'Name', text=path.rsplit('/', 1)[-1])
        if ok:
            self.edit(lambda: self.graph.rename(path, name))

    def command(self, command):
        paths = self.canvas.selected_paths()
        if command == 'copy':
            QApplication.clipboard().setText(json.dumps(self.graph.copy(paths)))
        elif command == 'paste':
            self.edit(lambda: self.graph.paste(json.loads(QApplication.clipboard().text())))
        elif command == 'duplicate':
            self.edit(lambda: self.graph.paste(self.graph.copy(paths)))
        elif command == 'delete':
            self.edit(lambda: self.graph.remove(paths))
        elif command in ('undo', 'redo'):
            self.edit(lambda: self.graph.restore(command == 'redo'))
        elif command == 'arrange':
            nodes = self.graph.nodes()
            levels = {n['path']: 0 for n in nodes}
            for _ in nodes:
                for node in nodes:
                    sources = [p['connection'].split('.outputs:')[0] for p in node['inputs'].values() if p['connection']]
                    levels[node['path']] = max([levels.get(source, -1) + 1 for source in sources] or [0])
            counts, positions = {}, {}
            for node in nodes:
                level = levels[node['path']]
                positions[node['path']] = (level * 360, counts.get(level, 0))
                counts[level] = counts.get(level, 0) + self.canvas.nodes[node['path']].rect().height() + 80
            self.edit(lambda: self.graph.move(positions))
            self.canvas.frame_nodes()


class MaterialEditor(QDialog):
    moduleLoaded = Signal(object, str, bool)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.document = owner.document
        from omnilab.materials.mdl import install_module
        for report in self.document.view.get('mdl_catalog', []):
            install_module(default_catalog(), report, self.document.view.get('mdl_search_paths', []))
        self.disposed = False
        self.loading_module = False
        self.moduleLoaded.connect(self.finish_module)
        self.setWindowTitle('Material Editor — OmniLab')
        available = owner.screen().availableGeometry()
        self.resize(min(1480, available.width()-60), min(900, available.height()-80))
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        for label, entries in [
            ('OpenPBR', [('New OpenPBR material…', self.new_material)]),
            ('MDL', [('New OmniPBR material…', self.new_omnipbr), ('New MDL material…', self.new_mdl_material),
                     ('Load / reload module…', self.load_mdl), ('Module search paths…', self.mdl_paths)]),
            ('MaterialX', [('Import .mtlx…', self.import_file), ('Export .mtlx…', self.export_file)]),
        ]:
            button = QPushButton(label)
            menu = QMenu(button)
            for title, callback in entries:
                menu.addAction(title, lambda checked=False, callback=callback: owner.safe(callback))
            button.setMenu(menu)
            row.addWidget(button)
        for label, callback in [('Open material…', self.choose_material), ('Bind to selection', self.bind)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, callback=callback: owner.safe(callback))
            row.addWidget(button)
        row.addStretch()
        tools_button = QPushButton('Tools')
        tools_menu = QMenu(tools_button)
        for label, callback in [('Bake selected map…', self.bake_map), ('Insert baked EXR…', self.insert_bake)]:
            action = tools_menu.addAction(label)
            action.triggered.connect(lambda checked=False, callback=callback: owner.safe(callback))
        for label, callback in [('Camera projector…', self.add_projector), ('Freeze camera projectors', self.freeze_projectors)]:
            action = tools_menu.addAction(label)
            action.triggered.connect(lambda checked=False, callback=callback: owner.safe(callback))
        tools_button.setMenu(tools_menu)
        tools_menu.addSeparator()
        tools_menu.addAction('Application Settings…', lambda: owner.safe(owner.open_application_settings))
        tools_menu.addAction('Relaunch OmniLab', lambda: owner.safe(owner.relaunch))
        row.addWidget(tools_button)
        layout.addLayout(row)
        self.module_status = QLabel()
        self.module_status.setWordWrap(True)
        self.module_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.module_status)
        splitter = self.splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        splitter.addWidget(self.tabs)
        self.preview = MaterialPreview()
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1120, 320])
        self.tabs.currentChanged.connect(self.current_changed)
        saved_tabs = dict(self.document.view.get('materials', {}))
        paths = saved_tabs.get('tabs', [])
        for path in paths:
            if UsdShade.Material(self.document.stage.GetPrimAtPath(path)):
                self.open_material(path)
        if self.tabs.count():
            self.tabs.setCurrentIndex(min(saved_tabs.get('active', 0), self.tabs.count()-1))

    def mdl_paths(self):
        paths = self.document.view.get('mdl_search_paths', [])
        value, ok = QInputDialog.getMultiLineText(self, 'MDL search paths', 'One directory per line', '\n'.join(paths))
        if ok:
            paths = [str(Path(path.strip()).expanduser().resolve()) for path in value.splitlines() if path.strip()]
            if any(not Path(path).is_dir() for path in paths):
                raise ValueError('Every MDL search path must be an existing directory.')
            self.document.view['mdl_search_paths'] = paths

    def load_mdl(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load or reload MDL module', '', 'MDL (*.mdl)')
        if path:
            self.inspect_module(path)

    def new_omnipbr(self):
        spec = find_spec('ovrtx')
        if not spec:
            raise ValueError('Install the rtx extra to use the bundled OmniPBR module.')
        self.inspect_module(str(Path(spec.origin).parent / 'bin/library/mdl/Base/OmniPBR.mdl'), True)

    def new_mdl_material(self):
        definitions = [d for d in default_catalog().definitions.values() if d.framework == 'mdl' and d.metadata['material']]
        if not definitions:
            raise ValueError('Load an MDL module first.')
        labels = [d.label + ' — ' + Path(d.metadata['module']).name for d in definitions]
        label, ok = QInputDialog.getItem(self, 'New MDL material', 'Definition', labels, editable=False)
        if ok:
            definition = definitions[labels.index(label)]
            graph = create_material(self.document, definition.label, definition.identifier)
            self.open_material(graph.path)
            self.changed()

    def inspect_module(self, path, create=False):
        if self.loading_module:
            raise ValueError('A module is already being inspected.')
        from omnilab.materials.mdl import reflect_module
        self.loading_module = True
        self.module_status.setText('Compiling MDL module and reading its definitions…')
        paths = list(self.document.view.get('mdl_search_paths', []))
        def work():
            try:
                result, error = reflect_module(path, paths), ''
            except Exception as exc:
                result, error = None, str(exc)
            if not self.disposed:
                self.moduleLoaded.emit(result, error, create)
        threading.Thread(target=work, daemon=True).start()

    def finish_module(self, report, error, create):
        self.loading_module = False
        if self.disposed:
            return
        if error:
            self.module_status.setText('MDL load failed; previous definitions and preview retained.\n' + error[:1500])
            return
        from omnilab.materials.mdl import install_module
        definitions = install_module(default_catalog(), report, self.document.view.get('mdl_search_paths', []))
        reports = self.document.view.setdefault('mdl_catalog', [])
        reports[:] = [r for r in reports if r['module'] != report['module']] + [report]
        self.module_status.setText(f'Loaded {len(definitions)} definitions from {Path(report["module"]).name}.')
        modules = self.document.view.setdefault('mdl_modules', [])
        if report['module'] not in modules:
            modules.append(report['module'])
        by_identifier = {d.identifier: d for d in definitions}
        def reload_sources():
            for prim in self.document.stage.Traverse():
                definition = by_identifier.get(prim.GetCustomDataByKey('omnilab:definition'))
                if definition:
                    shader = UsdShade.Shader(prim)
                    shader.SetSourceAsset(Sdf.AssetPath(definition.metadata['runtime_module']), 'mdl')
        self.document.edits.change('Reload MDL module', reload_sources)
        self.document.revision += 1
        for index in range(self.tabs.count()):
            panel = self.tabs.widget(index)
            panel.refresh_library()
            panel.reload()
        materials = [d for d in definitions if d.metadata['material']]
        if create and materials:
            graph = create_material(self.document, materials[0].label, materials[0].identifier)
            self.open_material(graph.path)
            self.changed()
        elif self.current():
            self.current().search.setText(Path(report['module']).stem)
        self.changed()

    def current(self):
        return self.tabs.currentWidget()

    def open_material(self, path):
        path = str(path)
        for index in range(self.tabs.count()):
            if str(self.tabs.widget(index).graph.path) == path:
                self.tabs.setCurrentIndex(index)
                return
        panel = GraphPanel(MaterialGraph(self.document, path), application_settings=self.owner.application_settings)
        panel.changed.connect(self.changed)
        self.tabs.addTab(panel, path.rsplit('/', 1)[-1])
        self.tabs.setCurrentWidget(panel)
        self.current_changed()

    def current_changed(self, *_):
        panel = self.current()
        self.preview.set_graph(panel.graph if panel else None)
        self.document.view['materials'] = dict(tabs=[str(self.tabs.widget(i).graph.path) for i in range(self.tabs.count())],
                                               active=self.tabs.currentIndex())

    def changed(self):
        self.owner.refresh()
        self.owner.schedule_view()
        self.current_changed()

    def close_tab(self, index):
        panel = self.tabs.widget(index)
        panel.texture_preview.shutdown()
        self.tabs.removeTab(index)
        panel.deleteLater()
        self.current_changed()

    def new_material(self):
        name, ok = QInputDialog.getText(self, 'New OpenPBR material', 'Name', text='Material')
        if ok:
            graph = create_material(self.document, name)
            self.open_material(graph.path)
            self.changed()

    def choose_material(self):
        paths = [str(prim.GetPath()) for prim in self.document.stage.Traverse() if prim.IsA(UsdShade.Material)]
        if not paths:
            self.new_material()
            return
        path, ok = QInputDialog.getItem(self, 'Open material', 'Material', paths, editable=False)
        if ok:
            self.open_material(path)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import MaterialX', '', 'MaterialX (*.mtlx)')
        if path:
            graph = import_materialx(self.document, path)
            self.open_material(graph.path)
            self.changed()

    def export_file(self):
        if not self.current():
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export MaterialX', 'material.mtlx', 'MaterialX (*.mtlx)')
        if path:
            export_materialx(self.current().graph, path)

    def bind(self):
        if self.current():
            self.owner.execute('bind_scene_material', str(self.current().graph.path), self.document.selection)

    def bake_map(self):
        from omnilab.materials.bake import prepare_bake
        from .window import json_dialog
        panel = self.current()
        paths = panel.canvas.selected_paths() if panel else []
        if len(paths) != 1:
            raise ValueError('Select one nonnegative MaterialX color or float map node to bake.')
        destination, _ = QFileDialog.getSaveFileName(self, 'Bake linear map to EXR', 'baked-map.exr', 'EXR (*.exr)')
        if not destination:
            return
        options = json_dialog(self, 'UV-card bake and optional temporal blur', dict(size=512, samples=16,
            motion=dict(type='none', samples=32, angle=30, center=[.5, .5], distance=.1, direction=0)))
        if options is None:
            return
        self.owner.open_render_view()
        view = self.owner.render_view
        if view.job and view.job.active:
            raise ValueError('Wait for the active final job or cancel it first.')
        job = prepare_bake(panel.graph, paths[0], destination, Path.cwd() / 'artifacts/render-jobs',
                           size=options['size'], samples=options['samples'], motion=options['motion'])
        view.begin_job(job)

    def insert_bake(self):
        if not self.current():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Insert baked linear EXR', '', 'EXR (*.exr)')
        if not path:
            return
        graph = self.current().graph
        def action():
            node = graph.add_node('ND_image_color3', Path(path).stem)
            graph.set_value(node, 'file', path, 'lin_rec709')
        graph.change('Insert baked texture', action)
        self.current().reload()
        self.changed()

    def add_projector(self):
        from omnilab.materials.projector import add_projector
        from pxr import UsdGeom
        if not self.current():
            return
        cameras = [str(p.GetPath()) for p in self.document.stage.Traverse() if p.IsA(UsdGeom.Camera)]
        if not cameras:
            raise ValueError('Create a USD Camera in the stage to use as a projector.')
        camera, ok = QInputDialog.getItem(self, 'Projector camera', 'Live camera link (updates in rendered snapshots)', cameras, editable=False)
        if not ok:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Projected texture', '', 'Images (*.png *.jpg *.exr *.tif)')
        if path:
            colorspace, ok = QInputDialog.getItem(self, 'Projected texture', 'Source colorspace',
                ['lin_rec709', 'srgb_texture', 'raw'], 0 if Path(path).suffix.lower() == '.exr' else 1, False)
            if not ok:
                return
            add_projector(self.current().graph, camera, path, colorspace)
            self.current().reload()
            self.current().command('arrange')
            self.changed()

    def freeze_projectors(self):
        from omnilab.materials.projector import freeze_projectors
        if self.current():
            freeze_projectors(self.current().graph)
            self.current().reload()
            self.changed()

    def closeEvent(self, event):
        self.preview.stop()
        super().closeEvent(event)

    def shutdown(self):
        self.disposed = True
        for index in range(self.tabs.count()):
            self.tabs.widget(index).texture_preview.shutdown()
        self.preview.close()
        self.close()
