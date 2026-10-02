"""Desktop acceptance replay using actual Qt input and the native worker.

Run from the repository: .venv/bin/python tools/replay_qt.py
Uses the current desktop, or QT_QPA_PLATFORM=offscreen for headless verification.
"""
import json
from pathlib import Path
import shutil
import statistics
import time

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pxr import Gf, Usd, UsdGeom

from omnilab.core.document import Document
from omnilab.frontends.qt.window import MainWindow


def main():
    output = Path("artifacts/qt-replay").resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    window.new_demo()
    report = {}
    render_started = set()
    window.bridge.event.connect(lambda event: render_started.add(event['request']) if event['type'] == 'render_started' else None)

    def wait_for(predicate, timeout=120):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise TimeoutError(window.log.toPlainText()[-5000:])
            app.processEvents()
            QTest.qWait(10)

    def rendered():
        wait_for(lambda: window.presented_request == window.request and not window.viewport.image.isNull())
        app.processEvents()

    def settle():
        rendered()
        QTest.qWait(300)
        app.processEvents()

    try:
        settle()
        report['initial_frames'] = window.frame_count
        window.grab().save(str(output / '01-editor.png'))
        # Click the projected sphere center, checking Qt coordinates against native picking.
        center = window.viewport.project(Gf.Vec3d(0, 1, 0)).toPoint()
        QTest.mouseClick(window.viewport, Qt.LeftButton, Qt.NoModifier, center)
        wait_for(lambda: '/World/Sphere' in window.document.selection)
        settle()
        report['picked'] = list(window.document.selection)
        window.grab().save(str(output / '02-selected.png'))
        # A real manipulator drag commits exactly one document history entry.
        axis, start, end, size = window.viewport.handles[0]
        undo_count = len(window.document.edits.undo)
        QTest.mousePress(window.viewport, Qt.LeftButton, Qt.NoModifier, end.toPoint())
        QTest.mouseMove(window.viewport, end.toPoint() + QPoint(55, 0), 20)
        QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.NoModifier, end.toPoint() + QPoint(55, 0))
        settle()
        assert len(window.document.edits.undo) == undo_count + 1
        report['gizmo_single_undo'] = True
        window.execute('restore')
        settle()
        sphere = UsdGeom.Xformable(window.document.stage.GetPrimAtPath('/World/Sphere'))
        assert Gf.IsClose(sphere.ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation(), Gf.Vec3d(0, 1, 0), 1e-6)
        # Scalar material update must stay on the existing runtime snapshot.
        snapshot = window.snapshot['path']
        window.execute('set_property', dict(path='/World/Looks/Surface/Shader', group='Attributes', name='inputs:base_color', value=[.03, .8, .07]))
        settle()
        assert window.snapshot['path'] == snapshot
        report['material_delta_without_reload'] = True
        window.grab().save(str(output / '03-material-edit.png'))
        # Continuous real mouse motion must present new frames before release.
        pid = window.bridge.process.pid
        snapshot = window.snapshot['path']
        updates = []
        before_drag = window.request
        def record_frame(event):
            if (event['type'] == 'frame' and event['request'] == window.presented_request
                    and event['request'] > before_drag):
                updates.append(time.monotonic())
        window.bridge.event.connect(record_frame)
        start = QPoint(window.viewport.width() // 2, window.viewport.height() // 2)
        drag_started = time.monotonic()
        QTest.mousePress(window.viewport, Qt.LeftButton, Qt.AltModifier, start)
        for i in range(120):
            QTest.mouseMove(window.viewport, start + QPoint(i * 2, (i % 20) - 10))
            QTest.qWait(8)
        frames_during_drag = len(updates)
        release = time.monotonic()
        QTest.mouseRelease(window.viewport, Qt.LeftButton, Qt.AltModifier, start + QPoint(238, 9))
        rendered()
        final_latency = time.monotonic() - release
        window.bridge.event.disconnect(record_frame)
        assert frames_during_drag >= 3, 'Camera rendering starved during continuous input'
        assert window.snapshot['path'] == snapshot
        report['continuous_camera'] = dict(frames_during_drag=frames_during_drag,
            drag_seconds=release - drag_started, first_frame_ms=(updates[0] - drag_started) * 1000,
            median_frame_interval_ms=statistics.median((b - a) * 1000 for a, b in zip(updates, updates[1:])),
            final_camera_after_release_ms=final_latency * 1000, snapshot_reused=True)
        settle()
        assert window.bridge.process.pid == pid
        report['persistent_worker_camera'] = True
        # Save/reopen, then stop and recover with the authored result intact.
        window.document.save(output / 'scene.omnilab')
        window.install_document(Document.open(output / 'scene.omnilab'))
        settle()
        # Interrupt an in-progress long PT step, rather than only an idle worker.
        window.mode.setCurrentText('PathTracing')
        window.samples.setValue(4096)
        wait_for(lambda: window.request in render_started)
        QTest.qWait(100)
        was_pending = window.presented_request != window.request
        stop_started = time.monotonic()
        window.stop_renderer()
        report['cancel_inflight'] = was_pending
        report['cancel_seconds'] = time.monotonic() - stop_started
        assert was_pending and report['cancel_seconds'] < 2.5
        window.mode.setCurrentText('RealTimePathTracing')
        window.samples.setValue(16)
        start = time.monotonic()
        window.restart_renderer()
        settle()
        report['restart_seconds'] = time.monotonic() - start
        assert window.bridge.process.pid != pid
        assert list(window.document.stage.GetPrimAtPath('/World/Looks/Surface/Shader').GetAttribute('inputs:base_color').Get())[1] > .79
        report['save_reopen_recovery'] = True
        for i in range(3):
            window.install_document(Document.open(output / 'scene.omnilab'))
            settle()
        report['repeated_open'] = 3
        window.grab().save(str(output / '04-recovered.png'))
        report['frames'] = window.frame_count
        report['stale_frames_rejected'] = window.stale_frame_count
        report['status'] = 'passed'
    except Exception:
        import traceback
        report['status'] = 'failed'
        report['error'] = traceback.format_exc()
        window.grab().save(str(output / 'failure.png'))
        raise
    finally:
        for name in ('worker.log', 'ovrtx.log'):
            if (window.bridge.directory / name).exists():
                shutil.copy2(window.bridge.directory / name, output / name)
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        window.document.edits.saved = {layer: layer.ExportToString() for layer in window.document.edits.saved}
        window.close()
        app.processEvents()
    print(output / 'report.json')


if __name__ == '__main__':
    main()
