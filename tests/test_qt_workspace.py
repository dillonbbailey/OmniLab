import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QPoint, QPointF, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pxr import UsdGeom, Usd

from omnilab.frontends.qt.window import MainWindow


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(render_enabled=False)
    window.show()
    window.new_demo()
    app.processEvents()
    yield window
    window.document.edits.saved = {layer: layer.ExportToString() for layer in window.document.edits.saved}
    window.close()
    app.processEvents()


def test_selection_transform_and_undo_use_shared_document(window):
    window.document.select(['/World/Sphere'])
    window.refresh()
    fields = window.transform_fields['translate']
    fields[0].setValue(3)
    window.apply_transform()
    assert UsdGeom.Xformable(window.document.stage.GetPrimAtPath('/World/Sphere')).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()[0] == 3
    window.execute('restore')
    assert UsdGeom.Xformable(window.document.stage.GetPrimAtPath('/World/Sphere')).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()[0] == 0
    assert window.document.dirty is False


def test_camera_gestures_do_not_dirty_document(window):
    camera = window.viewport.camera.to_dict()
    QTest.mousePress(window.viewport, Qt.LeftButton, Qt.AltModifier, QPoint(100, 100))
    QTest.mouseMove(window.viewport, QPoint(180, 110), 10)
    QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.AltModifier, QPoint(180, 110))
    assert window.viewport.camera.to_dict() != camera
    assert not window.document.dirty


def test_gizmo_drag_is_one_undo_and_escape_cancels(window):
    window.document.select(['/World/Sphere'])
    window.refresh()
    QApplication.processEvents()
    axis, start, end, size = window.viewport.handles[0]
    QTest.mousePress(window.viewport, Qt.LeftButton, Qt.NoModifier, end.toPoint())
    QTest.mouseMove(window.viewport, end.toPoint() + QPoint(60, 0), 10)
    QTest.keyClick(window.viewport, Qt.Key_Escape)
    QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.NoModifier, end.toPoint() + QPoint(60, 0))
    assert not window.document.edits.undo
    QTest.mousePress(window.viewport, Qt.LeftButton, Qt.NoModifier, end.toPoint())
    QTest.mouseMove(window.viewport, end.toPoint() + QPoint(60, 0), 10)
    QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.NoModifier, end.toPoint() + QPoint(60, 0))
    assert len(window.document.edits.undo) == 1
    window.execute('restore')
    assert not window.document.dirty


def test_stale_frame_is_rejected_and_old_worker_epoch_ignored(window):
    window.request = 10
    window.renderer_event(dict(type='frame', epoch=window.bridge.epoch, request=9, shape=(1, 1, 4), pixels=b'\xff'*4))
    assert window.stale_frame_count == 1 and window.viewport.image.isNull()
    window.renderer_event(dict(type='ready', epoch=window.bridge.epoch - 1))
    assert not window.renderer_ready


def test_continuous_camera_motion_presents_frames_and_bounds_pending_work(window, monkeypatch):
    sent = []
    presented = []
    window.render_enabled = window.renderer_ready = True

    def send(message):
        if message['type'] != 'view':
            return
        sent.append(message)
        event = dict(type='frame', epoch=window.bridge.epoch, request=message['request'],
                     shape=(1, 1, 4), pixels=b'\xff' * 4, milliseconds=50, hits=None)
        QTimer.singleShot(50, lambda: window.renderer_event(event))

    monkeypatch.setattr(window.bridge, 'send', send)
    original = window.viewport.set_frame
    monkeypatch.setattr(window.viewport, 'set_frame', lambda event: (presented.append(event['request']), original(event)))
    window.schedule_view()
    QTest.qWait(100)
    snapshot = window.snapshot['path']
    initial_count = len(presented)
    for _ in range(60):
        window.viewport.camera.orbit(1, 0)
        window.viewport.cameraChanged.emit()
        QTest.qWait(5)
    # Rendering must progress before the input stream stops, even if a frame
    # takes longer than the interval between input events.
    assert len(presented) >= initial_count + 2
    assert len(sent) < 20
    QTest.qWait(150)
    assert window.presented_request == window.request
    assert presented == sorted(set(presented))
    assert all(view['snapshot']['path'] == snapshot for view in sent)
    assert not window.document.dirty


def test_scene_change_rejects_inflight_camera_frame(window, monkeypatch):
    sent = []
    monkeypatch.setattr(window.bridge, 'send', sent.append)
    window.render_enabled = window.renderer_ready = True
    window.schedule_view()
    window.flush_view()
    old_request = window.submitted_request
    window.schedule_view(False, interactive=True)
    window.schedule_view()  # A scene change while the camera frame is rendering.
    window.flush_view()
    assert len(sent) == 1  # At most one view waits for its first frame.
    window.renderer_event(dict(type='frame', epoch=window.bridge.epoch, request=old_request,
                               shape=(1, 1, 4), pixels=b'\xff' * 4, milliseconds=1, hits=[]))
    assert window.viewport.image.isNull()
    assert window.stale_frame_count == 1
    window.flush_view()
    assert window.submitted_request == window.request


def test_scene_camera_navigation_commit_escape_and_detach(window):
    from pxr import Gf
    from omnilab.core.camera import ViewCamera
    camera = UsdGeom.Camera.Define(window.document.stage, '/World/Camera')
    camera.SetFromCamera(ViewCamera(target=[0, 1, 0], distance=8, yaw=51, roll=13).camera(1.5))
    window.refresh()
    window.cameras.setCurrentIndex(window.cameras.findData('/World/Camera'))
    before = camera.GetCamera().transform
    window.camera_edit.setChecked(True)
    start, end = QPoint(120, 150), QPoint(200, 170)
    QTest.mousePress(window.viewport, Qt.LeftButton, Qt.AltModifier, start)
    QTest.mouseMove(window.viewport, end, 10)
    assert camera.GetCamera().transform == before
    QTest.keyClick(window.viewport, Qt.Key_Escape)
    QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.AltModifier, end)
    assert camera.GetCamera().transform == before and not window.document.edits.undo
    QTest.mousePress(window.viewport, Qt.LeftButton, Qt.AltModifier, start)
    QTest.mouseMove(window.viewport, end, 10)
    QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.AltModifier, end)
    assert not Gf.IsClose(camera.GetCamera().transform, before, 1e-6)
    assert len(window.document.edits.undo) == 1
    window.execute('restore')
    assert Gf.IsClose(camera.GetCamera().transform, before, 1e-6)
    window.camera_edit.setChecked(False)
    QTest.mousePress(window.viewport, Qt.LeftButton, Qt.AltModifier, start)
    QTest.mouseMove(window.viewport, end, 10)
    QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.AltModifier, end)
    assert not window.viewport.scene_camera_path
    assert not window.cameras.currentData()
    assert Gf.IsClose(camera.GetCamera().transform, before, 1e-6)


def test_depth_overlay_rejects_occluded_and_behind_camera_points(window):
    import numpy as np
    from pxr import Gf
    from omnilab.core.camera import ViewCamera
    from PySide6.QtGui import QImage
    viewport = window.viewport
    viewport.camera = ViewCamera(distance=5, yaw=0, pitch=0)
    camera = viewport.camera.camera(1)
    viewport._view_matrix = camera.frustum.ComputeViewMatrix()
    viewport._view_projection = viewport._view_matrix * camera.frustum.ComputeProjectionMatrix()
    UsdGeom.SetStageMetersPerUnit(window.document.stage, 1.)
    viewport.image = QImage(100, 100, QImage.Format_RGBA8888)
    viewport.depth = np.full((100, 100), 5., dtype=np.float32)
    points = []
    class Painter:
        def drawPoint(self, point):
            points.append(point)
    viewport.depth_points(Painter(), np.array([[0., 0., 0., 1.], [0., 0., -2., 1.], [0., 0., 6., 1.]]))
    assert len(points) == 1


def test_document_undo_refreshes_material_tabs_and_accepted_frame_is_displayed(window):
    from omnilab.materials.graph import create_material
    graph = create_material(window.document, 'Temporary')
    window.open_material_editor()
    editor = window.material_editor
    editor.open_material(str(graph.path))
    window.execute('restore')
    assert all(str(editor.tabs.widget(i).graph.path) != str(graph.path) for i in range(editor.tabs.count()))
    window.request = window.submitted_request = window.frame_floor = 500
    window.renderer_event(dict(type='frame', epoch=window.bridge.epoch, request=500,
        shape=(1,1,4), pixels=b'\xff\x00\x00\xff', milliseconds=1, hits=None))
    assert not window.viewport.image.isNull()
    assert window.viewport.image.pixelColor(0, 0).red() == 255
