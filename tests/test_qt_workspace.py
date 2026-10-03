import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pxr import UsdGeom, Usd

from omnilab.frontends.qt.window import MainWindow


@pytest.fixture
def window(tmp_path):
    from PySide6.QtCore import QSettings
    from omnilab.frontends.qt.application_settings import ApplicationSettings
    app = QApplication.instance() or QApplication([])
    settings = ApplicationSettings(QSettings(str(tmp_path/'preferences.ini'), QSettings.IniFormat))
    window = MainWindow(render_enabled=False, application_settings=settings)
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


def test_ovui_adapters_to_qt_and_back_preserve_project(window, tmp_path):
    pytest.importorskip('ovui_data_adapters')
    from omnilab.core.document import Document
    from omnilab.core.fixtures import demo_document
    from omnilab.frontends.ovui.adapters import DocumentPropertyAdapter
    from omnilab.materials.graph import MaterialGraph
    document = demo_document()
    adapter = DocumentPropertyAdapter(document, ['/World/Cube'])
    adapter.begin_edit('size')
    adapter.set_value('size', 2.25)
    adapter.end_edit('size')
    graph = MaterialGraph(document, '/World/Looks/Surface')
    graph.move({'/World/Looks/Surface/Shader': [80, 160]})
    document.save(tmp_path/'ovui.omnilab')
    window.install_document(Document.open(tmp_path/'ovui.omnilab'))
    assert window.document.stage.GetPrimAtPath('/World/Cube').GetAttribute('size').Get() == 2.25
    window.execute('set_property', dict(path='/World/Cube', group='Attributes', name='size', value=3.5))
    window.document.save(tmp_path/'qt.omnilab')
    reopened = Document.open(tmp_path/'qt.omnilab')
    assert DocumentPropertyAdapter(reopened, ['/World/Cube']).get_value('size') == 3.5
    assert MaterialGraph(reopened, graph.path).nodes()[0]['position'] == [80, 160]


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


def test_long_mdl_identifier_does_not_expand_material_editor(window, monkeypatch):
    from dataclasses import replace
    from pxr import UsdShade
    from PySide6.QtGui import QImage
    window.open_material_editor()
    editor = window.material_editor
    panel = editor.current()
    path = panel.graph.nodes()[0]['path']
    signature = 'mdl:/a/very/long/module.mdl#OmniPBR(' + ','.join(['float', 'texture_2d', 'color'] * 60) + ')'
    definition = replace(panel.graph.catalog.definition('ND_open_pbr_surface_surfaceshader'),
                         identifier=signature, framework='mdl')
    monkeypatch.setitem(panel.graph.catalog.definitions, signature, definition)
    UsdShade.Shader(window.document.stage.GetPrimAtPath(path)).GetPrim().SetCustomDataByKey('omnilab:definition', signature)
    # Reflected function signatures must remain inspectable without driving layout.
    UsdShade.Shader(window.document.stage.GetPrimAtPath(path)).SetSourceAsset('/a/very/long/module.mdl', 'mdl')
    UsdShade.Shader(window.document.stage.GetPrimAtPath(path)).GetIdAttr().Set('')
    panel.reload()
    panel.inspect(path)
    editor.resize(1400, 800)
    QApplication.processEvents()
    assert editor.width() == 1400
    assert editor.minimumSizeHint().width() < 1400
    assert panel.node_identifier.toolTip() == signature
    assert panel.node_name.text().startswith('MDL')
    assert panel.canvas.width() >= 280 and panel.inspector.width() >= 275
    assert editor.preview.width() >= 300
    image = QImage(4096, 2048, QImage.Format_RGBA8888)
    editor.preview.label.set_image(image)
    QApplication.processEvents()
    assert editor.width() == 1400
    editor.resize(1300, 800)
    QApplication.processEvents()
    assert editor.width() == 1300
    assert editor.preview.label.pixmap().width() <= editor.preview.label.width()


def test_material_library_sections_filter_independently(window):
    from omnilab.materials.catalog import material_section
    window.open_material_editor()
    panel = window.material_editor.current()
    for index, section in enumerate(['OpenPBR', 'MDL', 'MaterialX']):
        panel.library_sections.setCurrentIndex(index)
        panel.search.clear()
        panel.refresh_library()
        identifiers = [panel.library.item(i).data(Qt.UserRole) for i in range(panel.library.count())]
        assert all(material_section(key, panel.graph.catalog.definition(key).framework) == section for key in identifiers)
        if section != 'MDL':
            assert identifiers
    panel.search.setText('constant color3')
    assert panel.library.count() and panel.library.item(0).data(Qt.UserRole) == 'ND_constant_color3'


def test_relaunch_failure_keeps_unsaved_editor_open(window, tmp_path, monkeypatch):
    from PySide6.QtCore import QProcess
    from omnilab.core import relaunch
    original = relaunch.write_checkpoint
    monkeypatch.setattr(relaunch, 'write_checkpoint', lambda doc, state: original(doc, state, tmp_path))
    monkeypatch.setattr(QProcess, 'startDetached', lambda *args: (False, 0))
    window.execute('set_property', dict(path='/World/Cube', group='Attributes', name='size', value=4))
    with pytest.raises(OSError, match='remains open'):
        window.relaunch()
    assert window.isVisible() and not window.relaunching and window.document.dirty
    assert len(list(tmp_path.glob('*.omnilab'))) == 1


def test_relaunch_starts_same_python_and_restores_materials_without_running_console(window, tmp_path, monkeypatch):
    import sys
    from PySide6.QtCore import QProcess
    from omnilab.core import relaunch
    from omnilab.materials.graph import create_material
    original = relaunch.write_checkpoint
    monkeypatch.setattr(relaunch, 'write_checkpoint', lambda doc, state: original(doc, state, tmp_path))
    launches = []
    monkeypatch.setattr(QProcess, 'startDetached', lambda *args: (launches.append(args) or (True, 123)))
    window.open_material_editor()
    second = create_material(window.document, 'Second')
    window.material_editor.open_material(second.path)
    window.document.select(['/World/Cube'])  # Bound to Surface, while Second is active.
    window.open_python_console()
    window.python_console.code.setPlainText("raise RuntimeError('do not execute')")
    window.execute('set_property', dict(path='/World/Cube', group='Attributes', name='size', value=4))
    window.relaunch()
    assert not window.isVisible() and window.relaunching
    executable, args, _ = launches[0]
    assert executable == sys.executable and args[:2] == ['-m', 'omnilab.app'] and '--no-render' in args
    document, state = relaunch.read_checkpoint(args[3])
    assert document.dirty and state['material_editor']
    replacement = MainWindow(render_enabled=False)
    try:
        replacement.install_document(document)
        replacement.restore_workspace(state)
        assert replacement.material_editor.isVisible()
        assert replacement.material_editor.current().graph.path == second.path
        assert replacement.python_console.code.toPlainText() == state['console']
        assert replacement.python_console.process is None
    finally:
        replacement.relaunching = True
        replacement.close()


def property_editor(window, name):
    row = next(i for i, data in enumerate(window.property_data) if data['name'] == name)
    return window.properties.cellWidget(row, 2)


def parameter_editor(panel, name):
    for group_index in range(panel.parameters.topLevelItemCount()):
        group = panel.parameters.topLevelItem(group_index)
        for index in range(group.childCount()):
            item = group.child(index)
            if item.data(0, Qt.UserRole) == name:
                return panel.parameters.itemWidget(item, 2)
    raise AssertionError('Missing parameter ' + name)


def enter_number(editor, text):
    editor.setFocus()
    editor.selectAll()
    QTest.keyClicks(editor, text)
    QTest.keyClick(editor, Qt.Key_Return)
    QApplication.processEvents()


def test_inline_float_double_precision_noop_and_undo(window):
    from PySide6.QtWidgets import QDoubleSpinBox
    from pxr import Sdf
    prim = window.document.stage.GetPrimAtPath('/World/Cube')
    attr = prim.CreateAttribute('test:float', Sdf.ValueTypeNames.Float)
    attr.Set(.123456789)
    window.document.select(['/World/Cube'])
    window.refresh()
    before = window.document.stage.GetRootLayer().ExportToString()
    number = property_editor(window, 'test:float')
    assert isinstance(number, QDoubleSpinBox) and number.decimals() == 6
    assert property_editor(window, 'size').decimals() == 12
    assert len(property_editor(window, 'xformOp:translate').fields) == 3
    enter_number(number, number.text())
    assert window.document.stage.GetRootLayer().ExportToString() == before
    assert not window.document.edits.undo
    enter_number(property_editor(window, 'test:float'), '-2.125')
    assert attr.Get() == pytest.approx(-2.125)
    assert len(window.document.edits.undo) == 1
    window.execute('restore')
    assert attr.Get() == pytest.approx(.123456789)
    enter_number(property_editor(window, 'size'), '3.123456789012')
    assert prim.GetAttribute('size').Get() == pytest.approx(3.123456789012, abs=1e-13)


def test_inline_number_authors_selected_frame_and_escape_cancels(window):
    window.document.select(['/World/Cube'])
    window.document.frame = 3.5
    window.time_mode.setCurrentIndex(1)
    window.refresh()
    editor = property_editor(window, 'size')
    editor.setFocus()
    editor.selectAll()
    QTest.keyClicks(editor, '20')
    QTest.keyClick(editor, Qt.Key_Escape)
    QTest.keyClick(editor, Qt.Key_Return)
    QApplication.processEvents()
    assert not window.document.edits.undo
    enter_number(property_editor(window, 'size'), '4.25')
    attr = window.document.stage.GetPrimAtPath('/World/Cube').GetAttribute('size')
    assert attr.GetTimeSamples() == [3.5]
    assert attr.Get(3.5) == 4.25 and attr.Get() == 1.5
    window.execute('restore')
    assert not attr.GetTimeSamples()


@pytest.mark.parametrize('material', ['openpbr', 'mdl'])
def test_material_numbers_commit_with_local_undo_and_preserve_connections(window, material):
    window.new_demo(material)
    window.open_material_editor()
    panel = window.material_editor.current()
    path = panel.graph.nodes()[0]['path']
    panel.canvas.nodes[path].setSelected(True)
    panel.inspect(path)
    name = 'specular_roughness' if material == 'openpbr' else 'reflection_roughness_constant'
    editor = parameter_editor(panel, name)
    assert editor.decimals() == 6
    original = panel.graph.shader(path).GetInput(name).Get()
    enter_number(editor, '.654321')
    assert panel.graph.shader(path).GetInput(name).Get() == pytest.approx(.654321)
    assert len(panel.graph.undo) == 1
    panel.command('undo')
    assert panel.graph.shader(path).GetInput(name).Get() == original
    if material == 'openpbr':
        source = panel.graph.add_node('ND_constant_float')
        panel.graph.connect(source, 'out', path, name)
        panel.reload()
        panel.inspect(path)
        assert parameter_editor(panel, name) is None


def test_application_precision_dialog_persists_and_refreshes_both_panels(window):
    from PySide6.QtWidgets import QDialogButtonBox
    from omnilab.frontends.qt.application_settings import ApplicationSettings, ApplicationSettingsDialog
    window.document.select(['/World/Cube'])
    window.refresh()
    window.open_material_editor()
    panel = window.material_editor.current()
    path = panel.graph.nodes()[0]['path']
    panel.inspect(path)
    before = window.document.stage.GetRootLayer().ExportToString()

    def accept_settings():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ApplicationSettingsDialog)
        dialog.precision['float'].setValue(3)
        dialog.precision['double'].setValue(9)
        dialog.show_types.setChecked(False)
        dialog.orientation_gizmo.setChecked(False)
        QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok), Qt.LeftButton)

    QTimer.singleShot(0, accept_settings)
    window.open_application_settings()
    assert property_editor(window, 'size').decimals() == 9
    assert parameter_editor(panel, 'specular_roughness').decimals() == 3
    assert window.properties.isColumnHidden(1) and panel.parameters.isColumnHidden(1)
    restored = ApplicationSettings(window.application_settings.storage)
    assert restored.decimals('float') == 3 and restored.decimals('double') == 9
    assert not restored.show_property_types()
    QApplication.processEvents()
    assert not restored.show_orientation_gizmo()
    assert not window.viewport.show_orientation_gizmo and not window.viewport.orientation_axes
    from omnilab.frontends.qt.settings_editor import SettingsEditor
    renderer_settings = SettingsEditor(window)
    assert renderer_settings.table.isColumnHidden(1)
    renderer_settings.close()
    assert window.document.stage.GetRootLayer().ExportToString() == before
    assert not window.document.edits.undo
    dialog = ApplicationSettingsDialog(restored)
    dialog.restore_defaults()
    assert dialog.precision['float'].value() == 6 and dialog.precision['double'].value() == 12
    assert dialog.show_types.isChecked()
    assert dialog.orientation_gizmo.isChecked()
    dialog.reject()
    assert restored.decimals('float') == 3  # Cancel does not save restored defaults.
    assert not restored.show_property_types()


@pytest.mark.parametrize('key,index,tool', [(Qt.Key_W, 0, 'translate'), (Qt.Key_E, 1, 'orient'), (Qt.Key_R, 2, 'scale')])
def test_transform_shortcuts_from_stage_author_drag_and_undo(window, key, index, tool):
    from pxr import Gf
    window.document.select(['/World/Cube'])
    window.refresh()
    window.tool.setCurrentIndex((index + 1) % 3)
    window.activateWindow()
    window.tree.setFocus()
    QApplication.processEvents()
    QTest.keyClick(window.tree, key)
    QApplication.processEvents()
    assert window.document.selection == ['/World/Cube']
    assert window.tool.currentIndex() == index and window.viewport.tool == tool
    assert window.viewport.hasFocus()
    prim = UsdGeom.Xformable(window.document.stage.GetPrimAtPath('/World/Cube'))
    original = prim.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    parent = UsdGeom.Xformable(window.document.stage.GetPrimAtPath('/World'))
    parent_before = parent.GetLocalTransformation()
    if tool == 'orient':
        assert not window.viewport.handles
        ring = max(window.viewport.rotation_handles, key=lambda ring: abs(window.viewport._view_matrix.TransformDir(ring['normal'])[2]))
        end, target = ring['points'][9], ring['points'][15]
    else:
        assert not window.viewport.rotation_handles
        _, start, end, _ = max(window.viewport.handles, key=lambda h: (h[2]-h[1]).manhattanLength())
        target = end + (end-start)*.5
    QTest.mousePress(window.viewport, Qt.LeftButton, Qt.NoModifier, end.toPoint())
    QTest.mouseMove(window.viewport, target.toPoint(), 10)
    QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.NoModifier, target.toPoint())
    changed = prim.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    assert Gf.IsClose(parent.GetLocalTransformation(), parent_before, 1e-6)
    assert not Gf.IsClose(original, changed, 1e-6)
    assert len(window.document.edits.undo) == 1
    if tool == 'translate':
        assert not Gf.IsClose(original.ExtractTranslation(), changed.ExtractTranslation(), 1e-6)
    else:
        assert Gf.IsClose(original.ExtractTranslation(), changed.ExtractTranslation(), 1e-6)
        if tool == 'scale':
            assert not Gf.IsClose(Gf.Transform(original).GetScale(), Gf.Transform(changed).GetScale(), 1e-6)
        else:
            assert not Gf.IsClose(original.ExtractRotationMatrix(), changed.ExtractRotationMatrix(), 1e-6)
    window.execute('restore')
    assert Gf.IsClose(original, prim.ComputeLocalToWorldTransform(Usd.TimeCode.Default()), 1e-6)


def test_transform_shortcuts_do_not_intercept_typing(window):
    window.activateWindow()
    window.filter.setFocus()
    QTest.keyClicks(window.filter, 'wer')
    assert window.filter.text() == 'wer' and window.viewport.tool == 'translate'
    window.viewport.setFocus()
    QTest.keyClick(window.viewport, Qt.Key_E)
    assert window.viewport.tool == 'orient' and window.tool.currentText() == 'Rotate'
    QTest.keyClick(window.viewport, Qt.Key_R, Qt.ControlModifier)
    assert window.viewport.tool == 'orient'


def test_timeline_toggle_scrub_and_fractional_range_follow_document(window):
    from omnilab.frontends.qt.application_settings import ApplicationSettings
    window.execute('set_frame_range', -2.5, 7.5)
    history = len(window.document.edits.undo)
    window.frame.setValue(2.5)
    assert window.timeline.value() == window.timeline.maximum()//2
    window.toggle_play()
    window.timeline.setValue(window.timeline.maximum()//4)
    assert window.document.frame == 0 and window.frame.value() == 0
    assert not window.play_timer.isActive()
    assert len(window.document.edits.undo) == history
    window.timeline_action.trigger()
    assert not window.timeline.isVisible()
    assert not ApplicationSettings(window.application_settings.storage).timeline_visible()
    window.timeline_action.trigger()
    assert window.timeline.isVisible()
    window.execute('set_frame_range', 4., 4.)
    assert not window.timeline.isEnabled()


def test_properties_sidebar_can_shrink_with_transform_controls_visible(window):
    window.document.select(['/World/Cube'])
    window.refresh()
    window.workspace_splitter.setSizes([280, 960, 240])
    QApplication.processEvents()
    assert 240 <= window.properties_tabs.width() <= 260
    assert window.properties.isVisible()
    for quaternion in (False, True):
        window.quaternion_check.setChecked(quaternion)
        QApplication.processEvents()
        rotation = 'orient' if quaternion else 'rotateXYZ'
        assert all(field.isVisible() for key in ('translate', rotation, 'scale') for field in window.transform_fields[key])
        assert window.properties_tabs.width() <= 260


def test_quaternion_fields_convert_without_authoring_and_persist(window, tmp_path):
    from pxr import Gf
    from omnilab.core.document import Document
    from omnilab.usd.usd_transforms import quaternion_from_euler
    window.document.select(['/World/Cube'])
    window.refresh()
    angles = [20, 30, 40]
    for field, value in zip(window.transform_fields['rotateXYZ'], angles):
        field.setValue(value)
    window.transform_fields['translate'][0].setValue(7)
    window.transform_fields['scale'][1].setValue(3)
    before = window.document.stage.GetRootLayer().ExportToString()
    window.quaternion_check.setChecked(True)
    assert [field.accessibleName() for field in window.transform_fields['orient']] == ['orient '+c for c in 'WXYZ']
    values = [field.value() for field in window.transform_fields['orient']]
    assert values == pytest.approx(quaternion_from_euler(angles), abs=1e-11)
    assert window.transform_fields['translate'][0].value() == 7
    assert window.transform_fields['scale'][1].value() == 3
    window.quaternion_check.setChecked(False)
    q = quaternion_from_euler([field.value() for field in window.transform_fields['rotateXYZ']])
    assert Gf.IsClose(Gf.Matrix3d().SetRotate(Gf.Quatd(q[0], Gf.Vec3d(*q[1:]))),
                      Gf.Matrix3d().SetRotate(Gf.Quatd(values[0], Gf.Vec3d(*values[1:]))), 1e-5)
    assert window.document.stage.GetRootLayer().ExportToString() == before
    assert not window.document.edits.undo
    window.quaternion_check.setChecked(True)
    window.matrix_output.setChecked(True)
    window.document.save(tmp_path/'transforms.omnilab')
    window.install_document(Document.open(tmp_path/'transforms.omnilab'))
    assert window.quaternion_check.isChecked() and window.matrix_output.isChecked()
    assert window.rotation_fields.currentIndex() == 1


@pytest.mark.parametrize('matrix', [False, True])
def test_quaternion_apply_normalizes_and_matrix_has_one_active_op(window, matrix):
    from pxr import Gf
    from omnilab.usd.usd_transform_pose import MATRIX_NAME
    window.document.select(['/World/Cube'])
    window.refresh()
    window.quaternion_check.setChecked(True)
    window.matrix_output.setChecked(matrix)
    for field, value in zip(window.transform_fields['orient'], [2, 0, 0, 2]):
        field.setValue(value)
    window.apply_transform()
    prim = window.document.stage.GetPrimAtPath('/World/Cube')
    xform = UsdGeom.Xformable(prim)
    assert Gf.IsClose(xform.GetLocalTransformation().ExtractRotationMatrix(), Gf.Matrix3d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), 90)), 1e-6)
    if matrix:
        assert [str(op.GetOpName()) for op in xform.GetOrderedXformOps()] == [MATRIX_NAME]
    else:
        assert prim.GetAttribute('xformOp:orient').Get().GetLength() == pytest.approx(1.)
    assert len(window.document.edits.undo) == 1
    window.execute('restore')
    assert not window.document.dirty


def test_rotate_ring_cancel_then_commit_single_matrix(window):
    from pxr import Gf
    from omnilab.usd.usd_transform_pose import MATRIX_NAME
    window.document.select(['/World/Cube'])
    window.refresh()
    window.matrix_output.setChecked(True)
    window.select_transform_tool(1)
    QApplication.processEvents()
    ring = max(window.viewport.rotation_handles, key=lambda ring: abs(window.viewport._view_matrix.TransformDir(ring['normal'])[2]))
    start, end = ring['points'][9].toPoint(), ring['points'][15].toPoint()
    xform = UsdGeom.Xformable(window.document.stage.GetPrimAtPath('/World/Cube'))
    before = xform.GetLocalTransformation()
    for cancel in (True, False):
        QTest.mousePress(window.viewport, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(window.viewport, end, 10)
        assert window.viewport.preview_world is not None
        if cancel:
            QTest.keyClick(window.viewport, Qt.Key_Escape)
        QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.NoModifier, end)
        assert len(window.document.edits.undo) == (0 if cancel else 1)
    assert [str(op.GetOpName()) for op in xform.GetOrderedXformOps()] == [MATRIX_NAME]
    assert not Gf.IsClose(xform.GetLocalTransformation(), before, 1e-6)
    window.execute('restore')
    assert Gf.IsClose(xform.GetLocalTransformation(), before, 1e-6)


def test_orientation_gizmo_tracks_camera_without_authoring(window):
    assert set(window.viewport.orientation_axes) == set('XYZ')
    before = dict(window.viewport.orientation_axes)
    window.viewport.camera.orbit(60, 20)
    window.viewport.repaint()
    assert before != window.viewport.orientation_axes
    assert all(point.x() > window.viewport.width()-115 and point.y() > window.viewport.height()-120
               for point in window.viewport.orientation_axes.values())
    assert not window.document.edits.undo
    window.viewport.show_orientation_gizmo = False
    window.viewport.repaint()
    assert not window.viewport.orientation_axes


def test_camera_guide_draws_wire_body_and_frustum(window, monkeypatch):
    from pxr import Gf
    camera = UsdGeom.Camera.Define(window.document.stage, '/World/GuideCamera')
    camera.AddTranslateOp().Set((2, 1, -1))
    segments = []
    monkeypatch.setattr(window.viewport, 'line3d', lambda painter, a, b: segments.append((a, b)))
    matrix = camera.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    window.viewport.draw_camera_guide(None, camera.GetPrim(), matrix, Usd.TimeCode.Default())
    assert len(segments) == 20  # Four lens rays, four frame edges, twelve body edges.
    assert all(Gf.IsClose(a, matrix.ExtractTranslation(), 1e-12) for a, _ in segments[:4])
    assert all(b[2] < -1 for _, b in segments[:4])


@pytest.mark.parametrize('kind,count,decimals', [('Float2', 2, 6), ('Float3', 3, 6), ('Float4', 4, 6),
                                               ('Double2', 2, 12), ('Double3', 3, 12), ('Double4', 4, 12)])
def test_vector_value_cells_preserve_other_components_and_undo(window, kind, count, decimals):
    from pxr import Sdf
    from omnilab.usd.usd_editing import decode_value
    prim = window.document.stage.GetPrimAtPath('/World/Cube')
    type_name = getattr(Sdf.ValueTypeNames, kind)
    attr = prim.CreateAttribute('test:vector', type_name)
    attr.Set(decode_value(type_name, [.12345678912345]*count))
    original = list(attr.Get())
    window.document.select(['/World/Cube'])
    window.refresh()
    editor = property_editor(window, 'test:vector')
    assert len(editor.fields) == count and editor.swatch is None
    assert all(field.decimals() == decimals for field in editor.fields)
    enter_number(editor.fields[1], '-3.125')
    assert list(attr.Get()) == original[:1] + [-3.125] + original[2:]
    assert len(window.document.edits.undo) == 1
    window.execute('restore')
    assert list(attr.Get()) == original


@pytest.mark.parametrize('kind,count', [('Color3f', 3), ('Color4f', 4)])
def test_color_cell_swatch_and_picker_commit_one_edit(window, monkeypatch, kind, count):
    from pxr import Sdf
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog
    from omnilab.usd.usd_editing import decode_value
    prim = window.document.stage.GetPrimAtPath('/World/Cube')
    type_name = getattr(Sdf.ValueTypeNames, kind)
    attr = prim.CreateAttribute('test:color', type_name)
    attr.Set(decode_value(type_name, [2., .25, .5, .75][:count]))
    original = list(attr.Get())
    window.document.select(['/World/Cube'])
    window.refresh()
    editor = property_editor(window, 'test:color')
    assert editor.swatch is not None and len(editor.fields) == count
    assert editor.fields[0].value() == 2.  # Display swatch clamps; numeric HDR value survives.
    picked = QColor.fromRgbF(.1, .2, .3, .4)
    monkeypatch.setattr(QColorDialog, 'getColor', lambda *args: picked)
    QTest.mouseClick(editor.swatch, Qt.LeftButton)
    QApplication.processEvents()
    assert list(attr.Get()) == pytest.approx(picked.getRgbF()[:count])
    assert len(window.document.edits.undo) == 1
    window.execute('restore')
    assert list(attr.Get()) == original


def test_material_color_and_vector_cells_use_precision_preferences(window):
    window.application_settings.save_precision(4, 10)
    window.open_material_editor()
    panel = window.material_editor.current()
    path = panel.graph.nodes()[0]['path']
    panel.canvas.nodes[path].setSelected(True)
    panel.inspect(path)
    color = parameter_editor(panel, 'base_color')
    assert len(color.fields) == 3 and color.swatch is not None
    assert all(field.decimals() == 4 for field in color.fields)
    original = list(panel.graph.shader(path).GetInput('base_color').Get())
    enter_number(color.fields[0], '1.25')
    assert list(panel.graph.shader(path).GetInput('base_color').Get()) == [1.25] + original[1:]
    assert len(panel.graph.undo) == 1
    panel.command('undo')
    assert list(panel.graph.shader(path).GetInput('base_color').Get()) == original
