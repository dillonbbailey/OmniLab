"""MCP adapter over the same document, graph and render services used by Qt."""
import base64
from dataclasses import asdict
import os
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from omnilab.materials.catalog import default_catalog
from omnilab.materials.graph import MaterialGraph, create_material
from omnilab.materials.exchange import export_materialx
from omnilab.render.jobs import JobOptions, prepare_job
from omnilab.core.camera import scene_camera


class EditorController:
    def __init__(self, window, editor_id):
        self.window, self.editor_id = window, editor_id

    def close(self):
        pass

    def dispatch(self, method, params):
        allowed = {'get_state', 'get_graph', 'describe_shader', 'list_shaders', 'edit_graph', 'document_command',
                   'new_material', 'render_preview', 'get_preview', 'render_final', 'get_job', 'cancel_job',
                   'save_document', 'export_materialx'}
        if method not in allowed:
            raise ValueError('Unknown editor command: ' + method)
        return getattr(self, method)(**params)

    def check(self, expected_revision):
        if type(expected_revision) is not int or expected_revision != self.window.document.revision:
            raise ValueError('The document revision changed. Read the current state and retry.')

    def get_state(self):
        document = self.window.document
        editor = getattr(self.window, 'material_editor', None)
        preview = editor.preview if editor else None
        return dict(editor_id=self.editor_id, pid=os.getpid(), title=self.window.windowTitle(),
            path=document.path, dirty=document.dirty, revision=document.revision, selection=document.selection,
            frame=document.frame, materials=[str(p.GetPath()) for p in document.stage.Traverse() if p.GetTypeName() == 'Material'],
            can_undo=bool(document.edits.undo), can_redo=bool(document.edits.redo),
            preview=dict(request=preview.request, presented=preview.presented_request, enabled=preview.enabled) if preview else None)

    def get_graph(self, material):
        graph = MaterialGraph(self.window.document, material)
        return dict(revision=self.window.document.revision, material=str(graph.path), nodes=graph.nodes(),
                    diagnostics=graph.diagnostics(), terminals={p.GetBaseName(): [str(path) for path in p.GetAttr().GetConnections()]
                        for p in graph.material.GetOutputs()})

    def describe_shader(self, identifier):
        return asdict(default_catalog().definition(identifier))

    def list_shaders(self, query='', framework=None):
        return [dict(identifier=d.identifier, framework=d.framework, label=d.label) for d in default_catalog().search(query, framework)][:100]

    def edit_graph(self, material, operations, expected_revision):
        self.check(expected_revision)
        if not isinstance(operations, list) or not 1 <= len(operations) <= 200:
            raise ValueError('Use 1–200 graph operations per transaction.')
        graph = MaterialGraph(self.window.document, material)
        refs = {}
        def resolve(path):
            return refs[path[1:]] if path.startswith('$') else path
        def action():
            for item in operations:
                op = item['op']
                if op == 'add_node':
                    path = graph.add_node(item['identifier'], item.get('name', ''), item.get('position', (0, 0)))
                    if item.get('ref'):
                        if item['ref'] in refs:
                            raise ValueError('Duplicate temporary node reference.')
                        refs[item['ref']] = path
                elif op == 'set_value':
                    graph.set_value(resolve(item['node']), item['input'], item['value'], item.get('colorspace'))
                elif op == 'connect':
                    graph.connect(resolve(item['source']), item.get('output', 'out'), resolve(item['target']), item['input'])
                elif op == 'disconnect':
                    graph.disconnect(resolve(item['node']), item['input'])
                elif op == 'set_terminal':
                    graph.set_terminal(resolve(item['node']), item.get('output', 'out'), item.get('terminal', 'surface'))
                elif op == 'remove':
                    graph.remove([resolve(path) for path in item['nodes']])
                elif op == 'move':
                    graph.move({resolve(path): position for path, position in item['positions'].items()})
                elif op == 'rename':
                    graph.rename(resolve(item['node']), item['name'])
                else:
                    raise ValueError('Unknown graph operation: ' + op)
        graph.change('MCP graph edit', action)
        self.refresh()
        return dict(revision=self.window.document.revision, created=refs)

    def refresh(self):
        self.window.refresh()
        self.window.schedule_view()
        editor = getattr(self.window, 'material_editor', None)
        if editor:
            for index in reversed(range(editor.tabs.count())):
                panel = editor.tabs.widget(index)
                if not self.window.document.stage.GetPrimAtPath(panel.graph.path):
                    editor.close_tab(index)
                else:
                    panel.reload()
            editor.current_changed()

    def document_command(self, command, arguments, expected_revision):
        self.check(expected_revision)
        self.window.document.command(command, *arguments)
        self.refresh()
        return self.get_state()

    def new_material(self, name, identifier, expected_revision):
        self.check(expected_revision)
        graph = create_material(self.window.document, name, identifier)
        self.refresh()
        return dict(material=str(graph.path), revision=self.window.document.revision)

    def render_preview(self, material):
        self.window.open_material_editor()
        editor = self.window.material_editor
        editor.open_material(material)
        editor.preview.start()
        return self.get_state()['preview']

    def get_preview(self):
        editor = getattr(self.window, 'material_editor', None)
        if not editor or editor.preview.picture.isNull():
            raise ValueError('No material preview has completed.')
        if editor.preview.presented_request != editor.preview.request:
            raise ValueError('The current material preview is still rendering; the retained image is stale.')
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        editor.preview.picture.save(buffer, 'PNG')
        return dict(mime='image/png', data=base64.b64encode(bytes(buffer.data())).decode())

    def render_final(self, options, camera=None):
        self.window.open_render_view()
        view = self.window.render_view
        if view.job and view.job.active:
            raise ValueError('A final render is already active.')
        settings = JobOptions(**options)
        document = self.window.document
        aspect = settings.resolution[0] / settings.resolution[1]
        current = self.window.viewport.render_camera()
        current.verticalAperture = current.horizontalAperture / aspect
        camera_at = (lambda frame: scene_camera(document.stage, camera, frame, aspect)) if camera else lambda frame: current
        job = prepare_job(document, camera_at, settings, Path.cwd()/'artifacts/render-jobs')
        view.begin_job(job)
        return self.get_job()

    def get_job(self):
        view = getattr(self.window, 'render_view', None)
        return dict(view.job.data) if view and view.job else None

    def cancel_job(self):
        view = getattr(self.window, 'render_view', None)
        if view:
            view.cancel()
        return self.get_job()

    def save_document(self, path, expected_revision, overwrite=False):
        self.check(expected_revision)
        target = Path(path).expanduser()
        if not target.is_absolute():
            raise ValueError('Use an absolute file path.')
        if target.exists() and str(target) != self.window.document.path and not overwrite:
            raise ValueError('The destination exists; pass overwrite=true to replace it.')
        self.window.document.save(target)
        self.window.refresh()
        return dict(path=str(target))

    def export_materialx(self, material, path, overwrite=False):
        target = Path(path).expanduser()
        if not target.is_absolute():
            raise ValueError('Use an absolute output path.')
        if target.exists() and not overwrite:
            raise ValueError('The destination exists; pass overwrite=true to replace it.')
        export_materialx(MaterialGraph(self.window.document, material), target)
        return dict(path=str(target))
