import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QPoint, QPointF
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
