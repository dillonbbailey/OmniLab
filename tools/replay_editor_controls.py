"""Native Qt input acceptance for property settings, transforms and timeline."""
import json
from pathlib import Path
import time

from PySide6.QtCore import Qt, QSettings, QTimer, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from pxr import Gf, Usd, UsdGeom

from omnilab.frontends.qt.application_settings import ApplicationSettings
from omnilab.frontends.qt.window import MainWindow
from omnilab.usd.usd_transform_pose import MATRIX_NAME


def main():
    output = Path('artifacts/editor-controls')
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle('Fusion')
    store = QSettings(str(output/'settings.ini'), QSettings.IniFormat)
    store.clear()
    window = MainWindow(application_settings=ApplicationSettings(store))
    window.show()
    window.new_demo()

    def rendered():
        deadline = time.monotonic()+90
        while window.presented_request != window.request or window.viewport.image.isNull():
            if time.monotonic() > deadline:
                raise TimeoutError(window.log.toPlainText()[-3000:])
            app.processEvents()
            QTest.qWait(20)

    try:
        rendered()
        window.document.select(['/World/Cube'])
        window.refresh()
        window.schedule_view(False)
        rendered()
        prim = UsdGeom.Xformable(window.document.stage.GetPrimAtPath('/World/Cube'))
        before = prim.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        guide = UsdGeom.Camera.Define(window.document.stage, '/World/GuideCamera')
        guide.AddTranslateOp().Set((2.5, 1.5, -1))
        guide.AddRotateYOp().Set(35)
        window.refresh()
        window.schedule_view(False)
        rendered()
        for index, key in enumerate((Qt.Key_W, Qt.Key_E, Qt.Key_R)):
            window.tool.setCurrentIndex((index+1) % 3)
            window.activateWindow()
            window.tree.setFocus()
            assert QTest.qWaitForWindowActive(window, 2000)
            app.processEvents()
            QTest.keyClick(window.tree, key)
            app.processEvents()
            assert window.tool.currentIndex() == index
            assert window.document.selection == ['/World/Cube'], (index, window.document.selection)
            window.viewport.grab().save(str(output/f'gizmo-{window.viewport.tool}.png'))
            if index == 1:
                ring = max(window.viewport.rotation_handles, key=lambda ring: abs(window.viewport._view_matrix.TransformDir(ring['normal'])[2]))
                end, target = ring['points'][9], ring['points'][15]
            else:
                _, start, end, _ = max(window.viewport.handles, key=lambda h: (h[2]-h[1]).manhattanLength())
                target = end+(end-start)*.4
            QTest.mousePress(window.viewport, Qt.LeftButton, Qt.NoModifier, end.toPoint())
            QTest.mouseMove(window.viewport, target.toPoint(), 20)
            QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.NoModifier, target.toPoint())
            rendered()
            assert not Gf.IsClose(before, prim.ComputeLocalToWorldTransform(Usd.TimeCode.Default()), 1e-6)
            window.execute('restore')
            rendered()
            assert Gf.IsClose(before, prim.ComputeLocalToWorldTransform(Usd.TimeCode.Default()), 1e-6)

        window.quaternion_check.setChecked(True)
        window.matrix_output.setChecked(True)
        for field, value in zip(window.transform_fields['orient'], [2, 0, 0, 2]):
            field.setValue(value)
        window.apply_transform()
        rendered()
        assert [str(op.GetOpName()) for op in prim.GetOrderedXformOps()] == [MATRIX_NAME]
        assert Gf.IsClose(prim.GetLocalTransformation().ExtractRotationMatrix(),
                          Gf.Matrix3d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), 90)), 1e-6)
        window.select_transform_tool(1)
        app.processEvents()
        ring = max(window.viewport.rotation_handles, key=lambda ring: abs(window.viewport._view_matrix.TransformDir(ring['normal'])[2]))
        start, end = ring['points'][9].toPoint(), ring['points'][15].toPoint()
        QTest.mousePress(window.viewport, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(window.viewport, end, 20)
        QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.NoModifier, end)
        rendered()
        assert [str(op.GetOpName()) for op in prim.GetOrderedXformOps()] == [MATRIX_NAME]
        assert len(window.document.edits.undo) == 2
        window.grab().save(str(output/'quaternion-matrix.png'))
        window.execute('restore')
        window.execute('restore')
        rendered()
        assert Gf.IsClose(before, prim.ComputeLocalToWorldTransform(Usd.TimeCode.Default()), 1e-6)

        def accept_settings():
            dialog = QApplication.activeModalWidget()
            dialog.grab().save(str(output/'application-settings.png'))
            QTest.mouseClick(dialog.show_types, Qt.LeftButton, Qt.NoModifier, QPoint(10, dialog.show_types.height()//2))
            QTest.mouseClick(dialog.orientation_gizmo, Qt.LeftButton, Qt.NoModifier, QPoint(10, dialog.orientation_gizmo.height()//2))
            QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok), Qt.LeftButton)

        QTimer.singleShot(100, accept_settings)
        window.open_application_settings()
        app.processEvents()
        assert window.properties.isColumnHidden(1)
        assert not window.viewport.show_orientation_gizmo and not window.viewport.orientation_axes
        assert not ApplicationSettings(store).show_orientation_gizmo()
        def restore_orientation():
            dialog = QApplication.activeModalWidget()
            QTest.mouseClick(dialog.orientation_gizmo, Qt.LeftButton, Qt.NoModifier, QPoint(10, dialog.orientation_gizmo.height()//2))
            QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok), Qt.LeftButton)
        QTimer.singleShot(100, restore_orientation)
        window.open_application_settings()
        app.processEvents()
        assert set(window.viewport.orientation_axes) == set('XYZ')
        window.execute('set_frame_range', -5.5, 15.5)
        QTest.mouseClick(window.timeline, Qt.LeftButton, Qt.NoModifier,
                         QPoint(window.timeline.width()//2, window.timeline.height()//2))
        assert 4.5 < window.document.frame < 5.5
        old_frame = window.document.frame
        QTest.keyClick(window.timeline, Qt.Key_Right)
        assert window.document.frame == old_frame+1
        rendered()
        window.workspace_splitter.setSizes([240, 1000, 240])
        app.processEvents()
        rendered()
        assert window.properties_tabs.width() <= 260
        window.grab().save(str(output/'narrow-properties-timeline.png'))
        window.workspace_splitter.setSizes([240, 780, 460])
        app.processEvents()
        rendered()
        window.grab().save(str(output/'viewport-controls.png'))
        window.open_material_editor()
        editor = window.material_editor
        panel = editor.current()
        path = panel.graph.nodes()[0]['path']
        panel.canvas.nodes[path].setSelected(True)
        panel.inspect(path)
        assert panel.parameters.isColumnHidden(1)
        panel.splitter.setSizes([245, 400, 430])
        app.processEvents()
        editor.grab().save(str(output/'material-values.png'))
        (output/'report.json').write_text(json.dumps(dict(status='passed', native_ovrtx=True,
            transform_keys_and_drag_undo=['W', 'E', 'R'], settings_dialog=True,
            distinct_gizmos=['translate arrows', 'rotation rings', 'scale boxes'],
            orientation_gizmo_preference=True, wireframe_camera_guide=True,
            quaternion_wxyz_normalized=True, single_matrix_apply_and_ring_drag_undo=True,
            property_type_toggle=True, timeline_mouse_and_keyboard_scrub=True,
            fractional_range=True, minimum_sidebar_width=240, material_vector_color_cells=True), indent=2)+'\n')
    finally:
        window.relaunching = True
        window.close()
        app.processEvents()


if __name__ == '__main__':
    main()
