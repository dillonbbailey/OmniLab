from pathlib import Path
import shutil
import pytest

from omnilab.materials.catalog import Catalog
from omnilab.materials.mdl import load_module, sdk_configuration


@pytest.fixture
def sdk():
    try:
        return sdk_configuration()
    except ValueError as error:
        pytest.skip(str(error))


def test_mdl_reflection_import_closure_and_failed_reload_keep_cached_material(sdk, tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    library = tmp_path/'library'
    (library/'paint').mkdir(parents=True)
    (library/'paint/colors.mdl').write_text('mdl 1.7; export color tint() = color(0.2, 0.4, 0.8);')
    module = source/'custom.mdl'
    module.write_text('mdl 1.7; import ::df::*; import ::paint::colors::*; export material matte(color tint = ::paint::colors::tint()) = material(surface: material_surface(scattering: df::diffuse_reflection_bsdf(tint: tint)));')
    catalog = Catalog()
    definitions, report = load_module(catalog, module, [library])
    assert len(definitions) == 1
    assert definitions[0].inputs['tint'].type == 'color3'
    cached = Path(report['runtime_module'])
    assert cached.is_file() and 'import ::paint::colors' not in cached.read_text()
    before = cached.read_bytes()
    module.write_text('mdl 1.7; export material syntax_error(')
    with pytest.raises(ValueError, match='expected|not defined'):
        load_module(catalog, module, [library])
    assert catalog.definition(definitions[0].identifier) is definitions[0]
    assert cached.read_bytes() == before
    shutil.rmtree(library)
    assert cached.is_file()


def test_mdl_annotations_and_function_ports(sdk):
    catalog = Catalog()
    definitions, report = load_module(catalog, Path(__file__).parent/'fixtures/materials/omnilab_test.mdl')
    material = next(d for d in definitions if d.metadata['material'])
    function = next(d for d in definitions if not d.metadata['material'])
    assert material.inputs['roughness'].metadata['uimax'] == 1.
    assert material.inputs['tint'].metadata['uiname'] == 'Tint'
    assert function.outputs['out'].type == 'color3'


def test_mdl_texture_bundle_publishes_without_original_search_paths(sdk, tmp_path):
    import json
    from PIL import Image
    from pxr import Usd, UsdGeom, UsdShade
    from omnilab.core.document import Document
    from omnilab.materials.graph import create_material
    from omnilab.usd.usd_asset_publish import publish_asset
    source = tmp_path / 'source'
    source.mkdir()
    Image.new('RGB', (4,4), (180,70,20)).save(source/'albedo.png')
    module = source / 'textured.mdl'
    module.write_text('''mdl 1.7;
import ::df::*;
import ::tex::*;
export material textured(uniform texture_2d image = texture_2d("albedo.png")) =
    material(surface: material_surface(scattering: df::diffuse_reflection_bsdf(
        tint: tex::lookup_color(image, float2(0.5)))));
''')
    catalog = Catalog()
    definitions, report = load_module(catalog, module)
    runtime = Path(report['runtime_module'])
    manifest = json.loads((runtime.parent/'omnilab_bundle.json').read_text())
    assert len(manifest['files']) >= 2
    doc = Document()
    cube = UsdGeom.Cube.Define(doc.stage, '/World/Cube')
    graph = create_material(doc, 'Textured', definitions[0].identifier, catalog=catalog)
    UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(graph.material)
    before = doc.stage.GetRootLayer().ExportToString()
    result = publish_asset(doc.stage, '/World/Cube', tmp_path, 'Published')
    assert doc.stage.GetRootLayer().ExportToString() == before
    shutil.rmtree(source)
    stage = Usd.Stage.Open(result['path'])
    assets = [UsdShade.Shader(p).GetSourceAsset('mdl') for p in stage.Traverse() if p.IsA(UsdShade.Shader)]
    assert assets and all(asset and Path(asset.resolvedPath).is_file() for asset in assets)
    assert all(str(tmp_path/'Published') in asset.resolvedPath for asset in assets)
    for asset in assets:
        bundle = Path(asset.resolvedPath).parent
        assert all((bundle / name).is_file() for name in manifest['files'])
