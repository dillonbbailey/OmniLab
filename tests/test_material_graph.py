import pytest
from pxr import Sdf, UsdShade

from omnilab.core.document import Document
from omnilab.core.fixtures import demo_document
from omnilab.materials.catalog import default_catalog
from omnilab.materials.graph import MaterialGraph, create_material
from omnilab.materials.exchange import export_materialx, import_materialx


def test_catalog_matches_runtime_and_exposes_annotations():
    definition = default_catalog().definition('ND_open_pbr_surface_surfaceshader')
    assert len(definition.inputs) >= 40
    assert definition.inputs['specular_ior'].default == 1.5
    assert definition.inputs['base_color'].metadata['uifolder'] == 'Base'


def test_typed_connections_cycles_and_atomic_errors():
    document = demo_document()
    graph = MaterialGraph(document, '/World/Looks/Surface')
    color = graph.add_node('ND_constant_color3')
    number = graph.add_node('ND_constant_float')
    graph.connect(color, 'out', '/World/Looks/Surface/Shader', 'base_color')
    before = document.stage.GetRootLayer().ExportToString()
    with pytest.raises(ValueError, match='Cannot connect'):
        graph.connect(number, 'out', '/World/Looks/Surface/Shader', 'base_color')
    assert document.stage.GetRootLayer().ExportToString() == before
    one = graph.add_node('ND_add_float', 'one')
    two = graph.add_node('ND_add_float', 'two')
    graph.connect(one, 'out', two, 'in1')
    with pytest.raises(ValueError, match='cycle'):
        graph.connect(two, 'out', one, 'in1')


def test_tab_undo_preserves_other_graph_and_project_layout(tmp_path):
    document = demo_document()
    graph = MaterialGraph(document, '/World/Looks/Surface')
    other = create_material(document, 'Other')
    graph.set_value('/World/Looks/Surface/Shader', 'base_color', [.8, .1, .2])
    other.set_value(str(other.path) + '/Surface', 'base_metalness', .7)
    graph.restore()
    assert other.shader(str(other.path) + '/Surface').GetInput('base_metalness').Get() == pytest.approx(.7)
    graph.restore(True)
    graph.move({'/World/Looks/Surface/Shader': (120, 230)})
    document.save(tmp_path / 'material.omnilab')
    reopened = Document.open(tmp_path / 'material.omnilab')
    restored = MaterialGraph(reopened, graph.path)
    assert restored.nodes()[0]['position'] == [120, 230]
    assert restored.nodes()[0]['inputs']['base_color']['value'] == pytest.approx([.8, .1, .2])
    material, _ = UsdShade.MaterialBindingAPI(reopened.stage.GetPrimAtPath('/World/Sphere')).ComputeBoundMaterial()
    assert material.GetPath() == graph.path


def test_clipboard_rename_unknown_nodes_and_undo():
    document = demo_document()
    graph = MaterialGraph(document, '/World/Looks/Surface')
    source = graph.add_node('ND_constant_color3', 'Color')
    graph.connect(source, 'out', '/World/Looks/Surface/Shader', 'base_color')
    copies = graph.paste(graph.copy([source, '/World/Looks/Surface/Shader']))
    assert graph.shader(copies[1]).GetInput('base_color').GetAttr().GetConnections()[0].GetPrimPath() == Sdf.Path(copies[0])
    renamed = graph.rename(copies[0], 'Renamed')
    assert graph.shader(copies[1]).GetInput('base_color').GetAttr().GetConnections()[0].GetPrimPath() == Sdf.Path(renamed)
    graph.restore()
    assert document.stage.GetPrimAtPath(copies[0])
    unknown = UsdShade.Shader.Define(document.stage, str(graph.path) + '/Unknown')
    unknown.CreateIdAttr('VendorSpecial')
    unknown.CreateInput('secret', Sdf.ValueTypeNames.Float).Set(.3)
    graph.set_value(source, 'value', [.2, .3, .4])
    assert unknown.GetInput('secret').Get() == pytest.approx(.3)
    assert any('definition unavailable' in message for message in graph.diagnostics())


def test_materialx_network_roundtrip_and_failed_export_preserves_file(tmp_path):
    document = demo_document()
    graph = MaterialGraph(document, '/World/Looks/Surface')
    image = graph.add_node('ND_image_color3', 'Texture', (50, 100))
    graph.set_value(image, 'file', str(tmp_path / 'missing.<UDIM>.exr'), 'lin_rec709')
    graph.connect(image, 'out', '/World/Looks/Surface/Shader', 'base_color')
    output = tmp_path / 'material.mtlx'
    export_materialx(graph, output)
    restored = import_materialx(document, output)
    nodes = {node['name']: node for node in restored.nodes()}
    assert nodes['Texture']['position'] == [50, 100]
    assert nodes['Texture']['inputs']['file']['colorspace'] == 'lin_rec709'
    assert nodes['Shader']['inputs']['base_color']['connection'].endswith('/Texture.outputs:out')
    assert any('missing texture' in message for message in restored.diagnostics())
    before = output.read_bytes()
    graph.shader('/World/Looks/Surface/Shader').GetInput('base_color').Set((1, 0, 0), 1)
    with pytest.raises(ValueError, match='animated'):
        export_materialx(graph, output)
    assert output.read_bytes() == before


def test_projector_links_follow_copy_rename_and_camera_namespace(tmp_path):
    from pxr import Gf, Usd, UsdGeom
    from omnilab.materials.projector import add_projector, synchronize, camera_matrix, freeze_projectors
    document = demo_document()
    graph = MaterialGraph(document, '/World/Looks/Surface')
    camera = UsdGeom.Camera.Define(document.stage, '/World/Camera')
    camera.SetFromCamera(Gf.Camera())
    image = add_projector(graph, '/World/Camera', str(tmp_path/'texture.exr'))
    prim = graph.shader(image).GetPrim()
    link = prim.GetCustomDataByKey('omnilab:projector')
    renamed = graph.rename(link['matrix'], 'RenamedProjection')
    copied = graph.paste(graph.copy([n['path'] for n in graph.nodes()]))
    copied_image = next(p for p in copied if graph.shader(p).GetPrim().GetCustomDataByKey('omnilab:projector'))
    assert graph.shader(copied_image).GetPrim().GetRelationship('omnilab:projectorMatrix').GetTargets()[0] != Sdf.Path(renamed)
    editor = Usd.NamespaceEditor(document.stage)
    editor.MovePrimAtPath('/World/Camera', '/World/CameraRenamed')
    assert editor.ApplyEdits()
    synchronize(document.stage, 1.)
    matrix = graph.shader(renamed).GetInput('mat').Get()
    assert Gf.IsClose(matrix, camera_matrix(document.stage, '/World/CameraRenamed', 1.), 1e-8)
    freeze_projectors(graph)
    document.stage.RemovePrim('/World/CameraRenamed')
    assert synchronize(document.stage, 2.) == []


def test_material_creation_failure_and_undo_are_atomic():
    document = Document()
    before = document.stage.GetRootLayer().ExportToString()
    with pytest.raises(ValueError):
        create_material(document, 'Invalid', 'ND_constant_float')
    assert document.stage.GetRootLayer().ExportToString() == before
    create_material(document, 'New')
    assert len(document.edits.undo) == 1
    document.command('restore')
    assert document.stage.GetRootLayer().ExportToString() == before
