"""Typed graph editing directly on UsdShade; scoped history preserves other tabs."""
from pathlib import Path
import glob

from pxr import Gf, Sdf, Tf, Usd, UsdShade

from omnilab.usd.usd_editing import decode_value, encode_value
from .catalog import USD_TYPES, default_catalog


def unique_path(stage, parent, name):
    name = Tf.MakeValidIdentifier(name.strip() or 'Node')
    path = Sdf.Path(parent).AppendChild(name)
    index = 1
    while stage.GetPrimAtPath(path):
        path = Sdf.Path(parent).AppendChild(f'{name}_{index}')
        index += 1
    return path


def framework(shader):
    return 'mdl' if shader.GetSourceAsset('mdl') else 'mtlx' if str(shader.GetIdAttr().Get() or '').startswith('ND_') else 'usd'


def author_node(stage, path, definition, position):
    if definition.metadata.get('unsupported'):
        raise ValueError(definition.metadata['unsupported'])
    shader = UsdShade.Shader.Define(stage, path)
    if definition.framework == 'mdl':
        shader.SetSourceAsset(Sdf.AssetPath(definition.metadata.get('runtime_module', definition.metadata['module'])), 'mdl')
        shader.SetSourceAssetSubIdentifier(definition.metadata['subidentifier'], 'mdl')
        shader.GetPrim().SetCustomDataByKey('omnilab:definition', definition.identifier)
    else:
        shader.CreateIdAttr(definition.identifier)
    shader.GetPrim().SetCustomDataByKey('omnilab:position', Gf.Vec2d(*position))
    for port in definition.outputs.values():
        shader.CreateOutput(port.name, USD_TYPES.get(port.type, Sdf.ValueTypeNames.Token))
    return shader


class MaterialGraph:
    def __init__(self, document, path, catalog=None):
        self.document = document
        self.path = Sdf.Path(path)
        self.catalog = catalog or default_catalog()
        if not UsdShade.Material(document.stage.GetPrimAtPath(self.path)):
            raise ValueError('Select a USD Material.')
        histories = document.__dict__.setdefault('_material_histories', {})
        self.undo, self.redo = histories.setdefault(str(self.path), ([], []))

    @property
    def stage(self):
        return self.document.stage

    @property
    def material(self):
        return UsdShade.Material(self.stage.GetPrimAtPath(self.path))

    def _snapshot(self, layer):
        result = Sdf.Layer.CreateAnonymous('material-history.usda')
        if layer.GetPrimAtPath(self.path):
            Sdf.CreatePrimInLayer(result, self.path.GetParentPath())
            Sdf.CopySpec(layer, self.path, result, self.path)
        return result

    def _restore(self, layer, snapshot):
        with Sdf.ChangeBlock():
            spec = layer.GetPrimAtPath(self.path)
            if spec:
                del (spec.nameParent or layer.pseudoRoot).nameChildren[spec.name]
            if snapshot.GetPrimAtPath(self.path):
                Sdf.CreatePrimInLayer(layer, self.path.GetParentPath())
                Sdf.CopySpec(snapshot, self.path, layer, self.path)

    def change(self, label, action):
        if getattr(self, '_change_depth', 0):
            return action()
        layer = self.document.edits.track_layer(self.document.edits.layer)
        if not layer.permissionToEdit:
            raise ValueError('The edit target is read-only.')
        # Local layer paths must match stage paths; variant edit targets need a
        # dedicated mapping before subtree histories can be safe.
        if self.stage.GetEditTarget().MapToSpecPath(self.path) != self.path:
            raise ValueError('Graph editing inside a variant edit target is not supported; select a local layer.')
        before = self._snapshot(layer)
        global_before = layer.ExportToString()
        self._change_depth = 1
        try:
            result = action()
        except Exception:
            self._restore(layer, before)
            raise
        finally:
            self._change_depth = 0
        after = self._snapshot(layer)
        if before.ExportToString() != after.ExportToString():
            self.undo.append((label, layer, before, after))
            del self.undo[:-100]
            self.redo.clear()
            self.document.edits.record_change(label, global_before, layer)
            self.document.revision += 1
        return result

    def restore(self, redo=False):
        source, destination = (self.redo, self.undo) if redo else (self.undo, self.redo)
        if not source:
            return
        item = source[-1]
        label, layer, before, after = item
        if layer not in self.stage.GetLayerStack() or not layer.permissionToEdit:
            raise ValueError('The graph history layer is no longer editable in this document.')
        expected = before if redo else after
        if self._snapshot(layer).ExportToString() != expected.ExportToString():
            self.undo.clear()
            self.redo.clear()
            raise ValueError('This material changed outside its graph history. Its local history has been reset; the document Undo still holds the global history.')
        global_before = layer.ExportToString()
        self._restore(layer, after if redo else before)
        self.document.edits.record_change(('Redo ' if redo else 'Undo ') + label, global_before, layer)
        source.pop()
        destination.append(item)
        self.document.revision += 1

    def shader(self, path):
        path = Sdf.Path(path)
        shader = UsdShade.Shader(self.stage.GetPrimAtPath(path))
        if not shader or not path.HasPrefix(self.path):
            raise ValueError('Shader must belong to this material.')
        return shader

    def definition(self, shader):
        identifier = shader.GetPrim().GetCustomDataByKey('omnilab:definition') or str(shader.GetIdAttr().Get() or '')
        definition = self.catalog.definitions.get(identifier)
        if not definition and shader.GetSourceAsset('mdl'):
            asset = shader.GetSourceAsset('mdl')
            module = str(Path(asset.resolvedPath or asset.path).resolve())
            definition = next((d for d in self.catalog.definitions.values() if d.framework == 'mdl'
                and module in (d.metadata['module'], d.metadata.get('runtime_module')) and d.metadata['subidentifier'] == shader.GetSourceAssetSubIdentifier('mdl')), None)
        return definition

    def nodes(self):
        result = []
        for prim in Usd.PrimRange(self.material.GetPrim()):
            shader = UsdShade.Shader(prim)
            if not shader:
                continue
            identifier = str(shader.GetIdAttr().Get() or shader.GetSourceAssetSubIdentifier('mdl') or '')
            definition = self.definition(shader)
            if definition:
                identifier = definition.identifier
            inputs = {}
            for name, port in (definition.inputs.items() if definition else []):
                inputs[name] = dict(type=port.type, value=port.default, metadata=port.metadata, connection=None)
            for port in shader.GetInputs():
                connections = port.GetAttr().GetConnections()
                inputs.setdefault(port.GetBaseName(), dict(type=str(port.GetTypeName()), metadata={}))
                inputs[port.GetBaseName()].update(value=encode_value(port.Get()),
                    connection=str(connections[0]) if connections else None,
                    colorspace=port.GetAttr().GetColorSpace())
            outputs = {p.GetBaseName(): str(p.GetTypeName()) for p in shader.GetOutputs()}
            if definition:
                outputs.update({name: port.type for name, port in definition.outputs.items()})
            result.append(dict(path=str(prim.GetPath()), name=prim.GetName(), identifier=identifier,
                framework=framework(shader), known=definition is not None,
                position=list(prim.GetCustomDataByKey('omnilab:position') or (0, 0)),
                inputs=inputs, outputs=outputs))
        return result

    def add_node(self, identifier, name='', position=(0, 0)):
        definition = self.catalog.definition(identifier)
        def action():
            path = unique_path(self.stage, self.path, name or definition.category)
            author_node(self.stage, path, definition, position)
            return str(path)
        return self.change('Add ' + definition.label, action)

    def set_value(self, path, name, value, colorspace=None):
        shader = self.shader(path)
        definition = self.definition(shader)
        port = definition.inputs.get(name) if definition else None
        existing = shader.GetInput(name)
        type_name = USD_TYPES.get(port.type) if port else existing.GetTypeName() if existing else None
        if not type_name:
            raise ValueError('Unknown or unsupported input type. The existing USD input is preserved.')
        decoded = decode_value(type_name, value)
        def action():
            input_ = shader.CreateInput(name, type_name)
            input_.Set(decoded)
            if colorspace is not None:
                input_.GetAttr().SetColorSpace(colorspace)
        self.change('Set ' + name, action)

    def _port(self, shader, name, output=False):
        definition = self.definition(shader)
        port = (definition.outputs if output else definition.inputs).get(name) if definition else None
        existing = shader.GetOutput(name) if output else shader.GetInput(name)
        if port and port.type in USD_TYPES:
            return port.type, USD_TYPES[port.type]
        if existing:
            return str(existing.GetTypeName()), existing.GetTypeName()
        raise ValueError('Unknown port: ' + name)

    def connect(self, source, output, target, input_):
        src, dst = self.shader(source), self.shader(target)
        if framework(src) != framework(dst):
            raise ValueError('Connections between shader frameworks require an explicit conversion.')
        src_type, src_usd = self._port(src, output, True)
        dst_type, dst_usd = self._port(dst, input_)
        if src_type != dst_type:
            raise ValueError(f'Cannot connect {src_type} to {dst_type}. Add an explicit conversion node.')
        # Walking upstream from the proposed source must not reach its target.
        pending, seen = [src.GetPath()], set()
        while pending:
            path = pending.pop()
            if path == dst.GetPath():
                raise ValueError('This connection would create a cycle.')
            if path in seen:
                continue
            seen.add(path)
            prim = self.stage.GetPrimAtPath(path)
            if prim:
                pending.extend(p.GetPrimPath() for a in prim.GetAttributes() for p in a.GetConnections())
        self.change('Connect ' + input_, lambda: dst.CreateInput(input_, dst_usd).ConnectToSource(src.CreateOutput(output, src_usd)))

    def disconnect(self, path, input_):
        shader = self.shader(path)
        _, type_name = self._port(shader, input_)
        self.change('Disconnect ' + input_, lambda: shader.CreateInput(input_, type_name).DisconnectSource())

    def set_terminal(self, path, output='out', terminal='surface'):
        shader = self.shader(path)
        kind, type_name = self._port(shader, output, True)
        expected = {'surface': 'surfaceshader', 'volume': 'volumeshader', 'displacement': 'displacementshader'}
        if terminal not in expected or (framework(shader) in ('mtlx', 'mdl') and kind != expected[terminal]):
            raise ValueError('The output does not match this material terminal.')
        context = framework(shader)
        context = '' if context == 'usd' else context
        self.change('Set material ' + terminal, lambda: self.material.CreateOutput(
            (context + ':' if context else '') + terminal, Sdf.ValueTypeNames.Token).ConnectToSource(shader.CreateOutput(output, type_name)))

    def move(self, positions):
        for path in positions:
            self.shader(path)
        self.change('Arrange nodes', lambda: [self.shader(path).GetPrim().SetCustomDataByKey(
            'omnilab:position', Gf.Vec2d(*position)) for path, position in positions.items()])

    def remove(self, paths):
        paths = {self.shader(path).GetPath() for path in paths}
        def action():
            for prim in Usd.PrimRange(self.material.GetPrim()):
                for attr in prim.GetAttributes():
                    connections = attr.GetConnections()
                    kept = [p for p in connections if p.GetPrimPath() not in paths]
                    if kept != connections:
                        attr.SetConnections(kept)
            for path in paths:
                self.stage.RemovePrim(path)
                if self.stage.GetPrimAtPath(path):
                    raise ValueError('This node is defined in another layer; remove it at its source.')
        self.change('Delete nodes', action)

    def copy(self, paths):
        paths = [self.shader(path).GetPath() for path in paths]
        flattened = self.stage.Flatten()
        layer = Sdf.Layer.CreateAnonymous('clipboard.usda')
        for path in paths:
            Sdf.CreatePrimInLayer(layer, path.GetParentPath())
            Sdf.CopySpec(flattened, path, layer, path)
        return dict(format='omnilab-material-nodes', version=1, paths=[str(p) for p in paths], layer=layer.ExportToString())

    def paste(self, data):
        if data.get('format') != 'omnilab-material-nodes' or data.get('version') != 1:
            raise ValueError('The clipboard does not contain OmniLab material nodes.')
        text = data.get('layer', '')
        if len(text) > 5_000_000:
            raise ValueError('The node clipboard exceeds 5 MB.')
        layer = Sdf.Layer.CreateAnonymous('clipboard.usda')
        if not layer.ImportFromString(text):
            raise ValueError('Invalid node clipboard.')
        def action():
            mapping = {}
            for old in data['paths']:
                old = Sdf.Path(old)
                spec = layer.GetPrimAtPath(old)
                if not spec or spec.typeName != 'Shader':
                    raise ValueError('Clipboard entries must be Shader prims.')
                target = unique_path(self.stage, self.path, old.name)
                Sdf.CreatePrimInLayer(self.document.edits.layer, target.GetParentPath())
                Sdf.CopySpec(layer, old, self.document.edits.layer, target)
                mapping[old] = target
            for target in mapping.values():
                shader = self.shader(target)
                position = shader.GetPrim().GetCustomDataByKey('omnilab:position') or (0, 0)
                shader.GetPrim().SetCustomDataByKey('omnilab:position', Gf.Vec2d(position[0] + 40, position[1] + 40))
                for rel in shader.GetPrim().GetRelationships():
                    rel.SetTargets([mapping.get(p, p) for p in rel.GetTargets()])
                link = shader.GetPrim().GetCustomDataByKey('omnilab:projector')
                if link:
                    source = Sdf.Path(link['matrix'])
                    if source in mapping:
                        shader.GetPrim().SetCustomDataByKey('omnilab:projector', dict(link, matrix=str(mapping[source])))
                    else:
                        shader.GetPrim().ClearCustomDataByKey('omnilab:projector')
                        shader.GetPrim().RemoveProperty('omnilab:projectorCamera')
                        shader.GetPrim().RemoveProperty('omnilab:projectorMatrix')
                for attr in shader.GetPrim().GetAttributes():
                    connections = attr.GetConnections()
                    if connections:
                        attr.SetConnections([p.ReplacePrefix(p.GetPrimPath(), mapping[p.GetPrimPath()])
                                             for p in connections if p.GetPrimPath() in mapping])
            return [str(p) for p in mapping.values()]
        return self.change('Paste nodes', action)

    def rename(self, path, name):
        shader = self.shader(path)
        if not Sdf.Path.IsValidIdentifier(name):
            raise ValueError('Use a valid USD identifier for the node name.')
        old, target = shader.GetPath(), shader.GetPath().GetParentPath().AppendChild(name)
        if old == target:
            return str(old)
        if self.stage.GetPrimAtPath(target):
            raise ValueError('A node already has that name.')
        def action():
            layer = self.document.edits.layer
            if not layer.GetPrimAtPath(old):
                raise ValueError('Rename the node in its defining layer.')
            for prim in self.stage.Traverse():
                if prim.GetPath().HasPrefix(self.path):
                    continue
                if any(p.HasPrefix(old) for attr in prim.GetAttributes() for p in attr.GetConnections()):
                    raise ValueError('The node has external connections; rename through the USD namespace editor.')
            Sdf.CopySpec(layer, old, layer, target)
            self.stage.RemovePrim(old)
            if self.stage.GetPrimAtPath(old):
                raise ValueError('The node also exists in a weaker layer; rename it at its source.')
            for prim in Usd.PrimRange(self.material.GetPrim()):
                for rel in prim.GetRelationships():
                    targets = rel.GetTargets()
                    if any(p.HasPrefix(old) for p in targets):
                        rel.SetTargets([p.ReplacePrefix(old, target) for p in targets])
                link = prim.GetCustomDataByKey('omnilab:projector')
                if link and Sdf.Path(link['matrix']).HasPrefix(old):
                    prim.SetCustomDataByKey('omnilab:projector', dict(link, matrix=str(Sdf.Path(link['matrix']).ReplacePrefix(old, target))))
                for attr in prim.GetAttributes():
                    connections = attr.GetConnections()
                    if any(p.HasPrefix(old) for p in connections):
                        attr.SetConnections([p.ReplacePrefix(old, target) for p in connections])
            return str(target)
        return self.change('Rename node', action)

    def diagnostics(self):
        messages = []
        for node in self.nodes():
            if not node['known']:
                messages.append(node['path'] + ': definition unavailable; authored values and connections are preserved.')
            for name, input_ in node['inputs'].items():
                if input_['connection'] and not self.stage.GetPropertyAtPath(input_['connection']):
                    messages.append(node['path'] + '.' + name + ': missing connection source ' + input_['connection'])
                if input_['type'] not in ('asset', 'filename') or not input_['value']:
                    continue
                attr = self.shader(node['path']).GetInput(name).GetAttr()
                asset = attr.Get() if attr else None
                if not isinstance(asset, Sdf.AssetPath):
                    continue
                path = asset.resolvedPath or asset.path
                if not glob.glob(path.replace('<UDIM>', '[0-9][0-9][0-9][0-9]')):
                    messages.append(node['path'] + '.' + name + ': missing texture ' + path)
        return messages


def create_material(document, name='Material', identifier='ND_open_pbr_surface_surfaceshader', parent='/World/Looks', catalog=None):
    catalog = catalog or default_catalog()
    definition = catalog.definition(identifier)
    if definition.outputs.get('out') is None or definition.outputs['out'].type != 'surfaceshader':
        raise ValueError('Choose a surface material definition.')
    path = unique_path(document.stage, parent, name)
    if document.stage.GetEditTarget().MapToSpecPath(path) != path:
        raise ValueError('Select a local layer before creating a material.')
    def action():
        material = UsdShade.Material.Define(document.stage, path)
        shader = author_node(document.stage, path.AppendChild('Surface'), definition, (300, 0))
        material.CreateSurfaceOutput(definition.framework).ConnectToSource(shader.GetOutput('out'))
    document.edits.change('Create material', action)
    document.revision += 1
    return MaterialGraph(document, path, catalog)
