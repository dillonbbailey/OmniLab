"""MaterialX interchange with explicit errors for unrepresentable USD networks."""
import os
from pathlib import Path
import tempfile

import MaterialX as mx
from pxr import Gf, Sdf, Tf, UsdShade

from omnilab.usd.usd_editing import decode_value
from .catalog import USD_TYPES, default_catalog, plain
from .graph import MaterialGraph, unique_path


def value_string(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (list, tuple)):
        return ', '.join(value_string(v) for v in value)
    return str(value)


def export_materialx(graph, destination):
    document = mx.createDocument()
    document.setDataLibrary(graph.catalog.library)
    nodes = graph.nodes()
    by_path = {node['path']: node for node in nodes}
    names = {n['path']: Tf.MakeValidIdentifier(str(Sdf.Path(n['path']).MakeRelativePath(graph.path)).replace('/', '_')) for n in nodes}
    if len(set(names.values())) != len(names):
        raise ValueError('Nested node names collide in MaterialX export. Rename the conflicting nodes first.')
    errors = []
    for node in nodes:
        link = graph.shader(node['path']).GetPrim().GetCustomDataByKey('omnilab:projector')
        if link and link.get('auto'):
            errors.append(node['path'] + ': freeze its camera projector before standalone MaterialX export.')
        if node['framework'] != 'mtlx' or not node['known']:
            errors.append(node['path'] + ': only known MaterialX definitions can be exported.')
            continue
        definition = graph.catalog.definition(node['identifier'])
        outputs = definition.outputs
        type_name = next(iter(outputs.values())).type if len(outputs) == 1 else 'multioutput'
        target = document.addNode(definition.category, names[node['path']], type_name)
        target.setNodeDefString(definition.identifier)
        target.setAttribute('xpos', str(node['position'][0]))
        target.setAttribute('ypos', str(node['position'][1]))
        shader = graph.shader(node['path'])
        for port in shader.GetInputs():
            name = port.GetBaseName()
            definition_port = definition.inputs.get(name)
            if not definition_port:
                errors.append(node['path'] + '.' + name + ': not declared by the NodeDef.')
                continue
            if port.GetAttr().GetNumTimeSamples():
                errors.append(node['path'] + '.' + name + ': animated input needs an explicit bake time.')
                continue
            value = node['inputs'][name]['value']
            input_ = target.addInput(name, definition_port.type)
            if value is not None:
                if definition_port.type == 'filename':
                    asset = port.Get()
                    value = asset.resolvedPath or asset.path
                input_.setValueString(value_string(value))
            colorspace = port.GetAttr().GetColorSpace()
            if colorspace:
                input_.setColorSpace(colorspace)
            connections = port.GetAttr().GetConnections()
            if connections:
                source = connections[0]
                source_name = names.get(str(source.GetPrimPath()))
                if not source_name or len(connections) != 1 or not source.name.startswith('outputs:'):
                    errors.append(str(port.GetAttr().GetPath()) + ': unsupported external or interface connection.')
                    continue
                if input_.hasValueString():
                    input_.setAttribute('omnilab_fallback', input_.getValueString())
                    input_.removeAttribute('value')
                input_.setNodeName(source_name)
                source_definition = graph.catalog.definition(by_path[str(source.GetPrimPath())]['identifier'])
                if len(source_definition.outputs) > 1:
                    input_.setOutputString(source.name.removeprefix('outputs:'))
    material = document.addNode('surfacematerial', Tf.MakeValidIdentifier(graph.material.GetPrim().GetName()) + '_material', 'material')
    for terminal, kind in [('surface', 'surfaceshader'), ('displacement', 'displacementshader'), ('volume', 'volumeshader')]:
        output = graph.material.GetOutput('mtlx:' + terminal)
        connections = output.GetAttr().GetConnections() if output else []
        if connections:
            source = connections[0]
            if str(source.GetPrimPath()) not in names:
                errors.append('Material terminal has an external connection: ' + str(source))
            else:
                input_ = material.addInput(kind, kind)
                input_.setNodeName(names[str(source.GetPrimPath())])
                source_definition = graph.catalog.definition(by_path[str(source.GetPrimPath())]['identifier'])
                if len(source_definition.outputs) > 1:
                    input_.setOutputString(source.name.removeprefix('outputs:'))
    valid, diagnostics = document.validate()
    if not valid:
        errors.append(diagnostics)
    if errors:
        raise ValueError('MaterialX export cannot represent this graph:\n' + '\n'.join(errors))
    # The catalog is a data library, so its implementation files are not exported.
    path = Path(destination).expanduser().absolute()
    fd, temporary = tempfile.mkstemp(prefix='.omnilab-material-', suffix='.mtlx', dir=path.parent)
    os.close(fd)
    try:
        mx.writeToXmlFile(document, temporary)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(path)


def import_materialx(document, source, name=None, catalog=None, parent='/World/Looks'):
    catalog = catalog or default_catalog()
    path = Path(source).expanduser().resolve()
    data = mx.createDocument()
    mx.readFromXmlFile(data, str(path))
    data.setDataLibrary(catalog.library)
    valid, diagnostics = data.validate()
    if not valid:
        raise ValueError('Invalid MaterialX document:\n' + diagnostics)
    materials = data.getMaterialNodes()
    if len(materials) != 1:
        raise ValueError('Import a MaterialX document containing exactly one material.')
    # Resolve named nodegraph outputs through MaterialX's connection API; flatten
    # the resulting graph into Shader prims without losing ports or values.
    nodes = [element for element in data.traverseTree() if isinstance(element, mx.Node)
             and element.getType() != 'material' and not element.getSourceUri()]
    definitions = {}
    for node in nodes:
        definition = node.getNodeDef()
        if not definition or definition.getName() not in catalog.definitions:
            raise ValueError('Unavailable NodeDef for ' + node.getNamePath() + '; import its definition library first.')
        definitions[node.getNamePath()] = catalog.definition(definition.getName())
    material_path = unique_path(document.stage, parent, name or materials[0].getName())
    result = {}
    def author():
        UsdShade.Material.Define(document.stage, material_path)
        mapping = {}
        for index, node in enumerate(nodes):
            definition = definitions[node.getNamePath()]
            shader_path = unique_path(document.stage, material_path, node.getNamePath().replace('/', '_'))
            shader = UsdShade.Shader.Define(document.stage, shader_path)
            shader.CreateIdAttr(definition.identifier)
            shader.GetPrim().SetCustomDataByKey('omnilab:position', Gf.Vec2d(
                float(node.getAttribute('xpos') or index * 280), float(node.getAttribute('ypos') or 0)))
            for output in definition.outputs.values():
                shader.CreateOutput(output.name, USD_TYPES.get(output.type, Sdf.ValueTypeNames.Token))
            mapping[node.getNamePath()] = shader
            for input_ in node.getInputs():
                if input_.getType() not in USD_TYPES:
                    raise ValueError('Unsupported port type: ' + input_.getType())
                port = shader.CreateInput(input_.getName(), USD_TYPES[input_.getType()])
                value = plain(input_.getValue())
                if input_.hasAttribute('omnilab_fallback'):
                    value = plain(mx.createValueFromStrings(input_.getAttribute('omnilab_fallback'), input_.getType()))
                if value is not None:
                    if input_.getType() == 'filename' and value and not Path(value).is_absolute():
                        value = str(path.parent / value)
                    port.Set(decode_value(port.GetTypeName(), value))
                if input_.getColorSpace():
                    port.GetAttr().SetColorSpace(input_.getColorSpace())
        def connected(input_):
            upstream = input_.getConnectedNode()
            if not upstream:
                out = input_.getConnectedOutput()
                upstream = out.getConnectedNode() if out else None
                output = out.getOutputString() if out else ''
            else:
                output = input_.getOutputString()
            if upstream:
                if upstream.getNamePath() not in mapping:
                    raise ValueError('Unsupported interface or external graph connection: ' + input_.getNamePath())
                shader = mapping[upstream.getNamePath()]
                return shader.GetOutput(output or 'out')
            if input_.getInterfaceName() or input_.getNodeName() or input_.getNodeGraphString():
                raise ValueError('Unresolved interface connection: ' + input_.getNamePath())
            return None
        for node in nodes:
            shader = mapping[node.getNamePath()]
            for input_ in node.getInputs():
                output = connected(input_)
                if output:
                    shader.GetInput(input_.getName()).ConnectToSource(output)
        material = UsdShade.Material(document.stage.GetPrimAtPath(material_path))
        for kind, terminal in [('surfaceshader', 'surface'), ('volumeshader', 'volume'), ('displacementshader', 'displacement')]:
            input_ = materials[0].getInput(kind)
            output = connected(input_) if input_ else None
            if output:
                material.CreateOutput('mtlx:' + terminal, Sdf.ValueTypeNames.Token).ConnectToSource(output)
        result['path'] = str(material_path)
    document.edits.change('Import MaterialX', author)
    document.revision += 1
    return MaterialGraph(document, result['path'], catalog)
