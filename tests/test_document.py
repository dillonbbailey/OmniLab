import json

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

from omnilab.core.document import Document
from omnilab.core.fixtures import demo_document
from omnilab.core.camera import ViewCamera
from omnilab.render.snapshot import publish


def test_project_preserves_session_target_variants_muting_and_view(tmp_path):
    doc = demo_document()
    child = doc.command("create_sublayer", dict(identifier=doc.edits.layer.identifier, storage="memory", name="child", expected=[]))
    doc.command("set_layer_muted", child, True)
    doc.edits.set_edit_target(doc.stage.GetSessionLayer().identifier)
    doc.command("variant", "/World/Sphere", "create", "look")
    doc.command("variant", "/World/Sphere", "add", "look", "red")
    doc.command("set_transform", dict(path="/World/Sphere", values={"translate": [2, 3, 4]}))
    doc.frame = 42
    doc.view = {"camera": ViewCamera().to_dict()}
    doc.select(["/World/Sphere"])
    doc.save(tmp_path / "test.omnilab")
    assert not doc.dirty
    restored = Document.open(tmp_path / "test.omnilab")
    assert restored.edits.layer == restored.stage.GetSessionLayer()
    assert restored.stage.GetPrimAtPath('/World/Sphere').GetVariantSet('look').GetVariantSelection() == 'red'
    assert len(restored.stage.GetMutedLayers()) == 1
    assert restored.frame == 42 and restored.selection == ["/World/Sphere"]
    assert restored.view == doc.view
    assert tuple(restored.stage.GetPrimAtPath('/World/Sphere').GetAttribute('xformOp:translate').Get()) == (2, 3, 4)
    assert not restored.dirty


def test_mute_undo_marks_project_dirty_without_editing_usd(tmp_path):
    doc = Document()
    child = doc.command("create_sublayer", dict(identifier=doc.edits.layer.identifier, storage="memory", name="edits", expected=[]))
    doc.save(tmp_path / "scene.omnilab")
    doc.command("set_layer_muted", child, True)
    assert doc.dirty
    doc.command("restore")
    assert not doc.dirty


def test_snapshot_includes_current_time_purpose_and_never_authors_viewport_in_document(tmp_path):
    doc = demo_document()
    sphere = doc.stage.GetPrimAtPath('/World/Sphere')
    UsdGeom.Imageable(sphere).CreatePurposeAttr('proxy')
    doc.command('set_transform', dict(path='/World/Cube', values={'translate': [9, 1, 0]}, frame=48, time='frame'))
    doc.frame = 48
    before = doc.stage.GetRootLayer().ExportToString()
    result = publish(doc, tmp_path / 'runtime', ViewCamera().camera(1.6), purposes=('default', 'render'))
    stage = Usd.Stage.Open(result['path'])
    assert UsdGeom.Imageable(stage.GetPrimAtPath('/World/Sphere')).ComputeVisibility(48) == 'invisible'
    assert tuple(stage.GetPrimAtPath('/World/Cube').GetAttribute('xformOp:translate').Get(48)) == (9, 1, 0)
    assert stage.GetPrimAtPath(result['product']).GetAttribute('omni:rtx:rendermode').Get() == 'RealTimePathTracing'
    assert doc.stage.GetRootLayer().ExportToString() == before
    doc.save(tmp_path / 'durable.usda')
    saved = Document.open(tmp_path / 'durable.usda')
    assert not saved.stage.GetPrimAtPath(result['product'])
    assert UsdGeom.Imageable(saved.stage.GetPrimAtPath('/World/Sphere')).ComputeVisibility(48) == 'inherited'


def test_camera_projection_and_navigation_stay_finite():
    camera = ViewCamera()
    for axis in ('Y', 'Z'):
        camera.up_axis = axis
        camera.pan(20, -10, 800)
        camera.orbit(300, -1000)
        camera.dolly(-20)
        matrix = camera.matrix()
        assert Gf.IsClose(matrix * matrix.GetInverse(), Gf.Matrix4d(1), 1e-7)


def test_failed_command_and_save_leave_document_usable(tmp_path, monkeypatch):
    doc = demo_document()
    before = doc.stage.GetRootLayer().ExportToString()
    with pytest.raises(ValueError):
        doc.command('set_property', dict(path='/World/Sphere', group='Attributes', name='radius', value='bad'))
    assert doc.stage.GetRootLayer().ExportToString() == before
    doc.save(tmp_path / 'document.omnilab')
    saved = (tmp_path / 'document.omnilab').read_bytes()
    doc.command('remove_prim', '/World/Sphere')
    monkeypatch.setattr('omnilab.core.document.os.replace', lambda *a: (_ for _ in ()).throw(OSError('disk failed')))
    with pytest.raises(OSError):
        doc.save()
    assert doc.dirty
    assert (tmp_path / 'document.omnilab').read_bytes() == saved
    doc.command('restore')
    assert doc.stage.GetPrimAtPath('/World/Sphere')


def test_rename_undo_remaps_selection_without_flattening():
    doc = demo_document()
    doc.select(['/World/Sphere'])
    doc.command('reparent_prim', dict(path='/World/Sphere', parent='/World', name='Ball', mode='namespace'))
    assert doc.selection == ['/World/Ball']
    doc.command('restore')
    assert doc.selection == ['/World/Sphere']
    doc.command('restore', True)
    assert doc.selection == ['/World/Ball']
