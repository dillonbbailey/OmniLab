import pytest
from pxr import Gf, Sdf, UsdGeom

from omnilab.core.camera import ViewCamera, camera_payload
from omnilab.core.fixtures import demo_document
from omnilab.render.settings import validate, export_settings
from omnilab.render.snapshot import publish


@pytest.mark.parametrize('axis', ['Y', 'Z'])
@pytest.mark.parametrize('orthographic', [False, True])
def test_scene_camera_navigation_preserves_pose_lens_shift_and_clipping(axis, orthographic):
    original = ViewCamera(target=[2, 3, -4], distance=13., yaw=-67., pitch=41., roll=31.,
        focal_length=70., horizontal_aperture=42., up_axis=axis, orthographic=orthographic,
        horizontal_offset=2., vertical_offset=-1., clipping=[.2, 700.]).camera(1.7)
    restored = ViewCamera.from_camera(original, 13., axis).camera(1.7)
    assert Gf.IsClose(original.transform, restored.transform, 1e-8)
    for field in ('horizontalAperture', 'verticalAperture', 'focalLength', 'horizontalApertureOffset', 'verticalApertureOffset'):
        assert getattr(original, field) == pytest.approx(getattr(restored, field))
    assert original.clippingRange == restored.clippingRange


def test_orthographic_camera_navigation_authors_one_undo_and_frame_sample():
    doc = demo_document()
    camera = UsdGeom.Camera.Define(doc.stage, '/World/Camera')
    source = ViewCamera(orthographic=True, horizontal_offset=2.).camera(1.5)
    camera.SetFromCamera(source)
    before = doc.stage.GetRootLayer().ExportToString()
    matrix = Gf.Matrix4d(source.transform)
    matrix.SetTranslateOnly((4, 5, 6))
    doc.command('set_camera_view', dict(path='/World/Camera', values={'matrix': [list(r) for r in matrix]},
        frame=1.25, time='frame', apertures=[20., 20./1.5]))
    assert len(doc.edits.undo) == 1
    assert camera.GetHorizontalApertureAttr().Get(1.25) == 20.
    assert camera.GetHorizontalApertureAttr().Get() == source.horizontalAperture
    doc.command('restore')
    assert doc.stage.GetRootLayer().ExportToString() == before


def test_settings_types_restart_enums_and_profiles_are_isolated(tmp_path):
    doc = demo_document()
    name = 'omni:rtx:pt:limits:maxBounces'
    assert validate(name, 7) == 7
    with pytest.raises(ValueError):
        validate(name, 7.5)
    with pytest.raises(ValueError):
        validate('motion_bvh', 9, True)
    with pytest.raises(ValueError):
        validate('omni:rtx:rendermode', 'PathTracing')
    with pytest.raises(ValueError):
        validate('active_cuda_gpus', '0,no', True)
    assert validate('active_cuda_gpus', '0,1', True) == '0,1'
    doc.view['rtx_settings'] = {'viewport': {name: 2}, 'final': {name: 7}}
    doc.view['renderer_config'] = {'active_cuda_gpus': '0'}
    camera = ViewCamera().camera(1)
    before = doc.stage.GetRootLayer().ExportToString()
    for profile, expected in [('viewport', 2), ('final', 7)]:
        snapshot = publish(doc, tmp_path / profile, camera, profile=profile)
        stage = Sdf.Layer.FindOrOpen(snapshot['path'])
        assert stage.GetAttributeAtPath(snapshot['product'] + '.' + name).default == expected
    assert doc.stage.GetRootLayer().ExportToString() == before
    report = export_settings(doc)
    assert 'unknown' in report['effective_values']
    assert report['renderer_creation']['active_cuda_gpus'] == '0'
