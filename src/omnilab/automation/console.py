"""Isolated Python execution with revision-checked, composition-preserving commits."""
from contextlib import contextmanager
import json
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdSkel, Vt
from omnilab.core.document import Document
from omnilab.usd.usd_project import capture_stage, restore_stage, stage_layers, remap_assets, ProjectLayers, RULES
from omnilab.materials.graph import MaterialGraph, create_material
from .console_execution import Executor


def snapshot(document):
    layers = stage_layers(document.stage, document.retained)
    result = capture_stage(document.stage, document.retained, inline=layers)
    result['layers'].sort(key=lambda row: row['identifier'])
    return result


class ConsoleAPI:
    def __init__(self, document):
        self.document = document

    def command(self, name, *args, **kwargs):
        return self.document.command(name, *args, **kwargs)

    def select(self, paths):
        self.document.select([paths] if isinstance(paths, str) else paths)

    def selection(self):
        return list(self.document.selection)

    def frame(self, value=None):
        if value is not None:
            self.document.frame = float(value)
        return self.document.frame

    def stage(self):
        return self.document.stage

    def edit_target(self, layer=None):
        if layer is not None:
            self.document.edits.set_edit_target(layer.identifier if isinstance(layer, Sdf.Layer) else layer)
        return self.document.edits.layer

    @contextmanager
    def edit(self, label='Python edit', layers=()):
        before = {layer: layer.ExportToString() for layer in (*self.document.stage.GetLayerStack(), *layers)}
        try:
            yield self
        except BaseException:
            with Sdf.ChangeBlock():
                for layer, text in before.items():
                    layer.ImportFromString(text)
            raise

    def material(self, path):
        return MaterialGraph(self.document, path)

    def create_material(self, name='Material', identifier='ND_open_pbr_surface_surfaceshader'):
        return create_material(self.document, name, identifier)


def run_worker(connection):
    executor = Executor()
    document = None
    last = None
    try:
        while True:
            request = connection.recv()
            if request['type'] == 'stop':
                return
            if request['stage'] != last:
                stage, retained, target = restore_stage(request['stage'])
                document = Document(stage, retained, target)
                executor.reset()
            document.frame = request['frame']
            document.selection = request['selection']
            api = ConsoleAPI(document)
            def emit(event, **data):
                connection.send(dict(type=event, **data))
            status = executor.run(request['code'], request['id'], request['cancel'], emit,
                dict(usd=api, stage=document.stage, document=document, Usd=Usd, Sdf=Sdf, Gf=Gf,
                     UsdGeom=UsdGeom, UsdShade=UsdShade, UsdSkel=UsdSkel, Vt=Vt))
            result = snapshot(document) if status == 'ok' else None
            connection.send(dict(type='finished', status=status, stage=result,
                                 selection=document.selection, frame=document.frame))
            last = result
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


def apply_result(document, before, result, label='Python console'):
    """Update the existing owned layers, preserving its prior global undo stack."""
    if snapshot(document) != before:
        raise ValueError('The document changed while Python was running. Its result was not applied; run again against the current document.')
    data = result['stage']
    if (data['root'], data['session']) != (before['root'], before['session']):
        raise ValueError('A console cell cannot replace the document root/session. Use New/Open for document replacement.')
    if not isinstance(document.retained, ProjectLayers):
        document.retained = ProjectLayers(document.retained)
    owned = stage_layers(document.stage, document.retained)
    aliases = document.retained.identifiers
    by_id = {aliases.get(key, key): layer for key, layer in owned.items()}
    new_layers = []
    for record in data['layers']:
        if record['identifier'] not in by_id:
            layer = Sdf.Layer.CreateAnonymous(record['name'])
            by_id[record['identifier']] = layer
            new_layers.append((record['identifier'], layer))
    prepared = []
    previous_records = {record['identifier']: record for record in before['layers']}
    for record in data['layers']:
        layer = by_id[record['identifier']]
        if record == previous_records.get(record['identifier']):
            continue
        clone = Sdf.Layer.CreateAnonymous('console-result.usda')
        if 'text' not in record or not clone.ImportFromString(record['text']):
            raise ValueError('Console returned an unreadable layer.')
        remap_assets(clone, lambda path: by_id[path].identifier if path in by_id else path)
        after = clone.ExportToString()
        if after != layer.ExportToString():
            if not layer.permissionToEdit:
                raise ValueError('A console result tried to change a read-only layer.')
            prepared.append((document.edits.track_layer(layer), layer.ExportToString(), after))
    old_rules = document.stage.GetLoadRules()
    old_muted = tuple(document.stage.GetMutedLayers())
    old_target = document.edits.layer.identifier
    rules = Usd.StageLoadRules()
    rules.SetRules([(Sdf.Path(path), RULES[rule]) for path, rule in data.get('load_rules', [])])
    try:
        with Sdf.ChangeBlock():
            for layer, _, after in prepared:
                if not layer.ImportFromString(after):
                    raise ValueError('Could not commit the console layer.')
        muted = {by_id[name].identifier for name in data.get('muted_layers', [])}
        current = set(document.stage.GetMutedLayers())
        document.stage.MuteAndUnmuteLayers(sorted(muted-current), sorted(current-muted))
        document.stage.SetLoadRules(rules)
        document.stage.SetEditTarget(document.stage.GetEditTargetForLocalLayer(by_id[data['target']]))
    except BaseException:
        with Sdf.ChangeBlock():
            for layer, text, _ in prepared:
                layer.ImportFromString(text)
        document.stage.SetLoadRules(old_rules)
        current = set(document.stage.GetMutedLayers())
        document.stage.MuteAndUnmuteLayers(sorted(set(old_muted)-current), sorted(current-set(old_muted)))
        document.edits.set_edit_target(old_target)
        raise
    for identifier, layer in new_layers:
        document.retained.append(layer)
        document.retained.identifiers[layer.identifier] = identifier
    if prepared or old_muted != tuple(document.stage.GetMutedLayers()) or old_rules.GetRules() != rules.GetRules():
        document.edits.undo.append((label, tuple(row[0] for row in prepared), tuple(row[1] for row in prepared),
            dict(load_rules=old_rules, muted_layers=old_muted, edit_target=old_target)))
        document.edits.undo = document.edits.undo[-100:]
        document.edits.redo.clear()
        document.revision += 1
    document.select(result['selection'])
    document.frame = result['frame']
