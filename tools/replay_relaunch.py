"""Exercise the Qt relaunch menu and inspect its real replacement on an X display."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from PySide6.QtCore import QProcess, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from omnilab.core.relaunch import read_checkpoint
from omnilab.frontends.qt.window import MainWindow


def child_windows(pid):
    tree = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
    result = {}
    for line in tree.splitlines():
        match = re.match(r'\s+(0x[0-9a-f]+) "([^"]+)"', line)
        if not match or 'OmniLab' not in match[2]:
            continue
        prop = subprocess.check_output(['xprop', '-id', match[1], '_NET_WM_PID'], text=True)
        if prop.strip().endswith('= ' + str(pid)):
            result[match[2]] = int(match[1], 16)
    return result


def main():
    out = Path('artifacts/relaunch').resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ['XDG_CACHE_HOME'] = str(out/'cache')
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    window = MainWindow(False)
    window.new_demo()
    source = out/'restart.omnilab'
    window.document.save(source)
    original = source.read_bytes()
    window.execute('set_property', dict(path='/World/Cube', group='Attributes', name='size', value=4))
    window.document.select(['/World/Cube'])
    window.document.frame = 2.5
    window.open_material_editor()
    window.open_python_console()
    marker = out/'console-executed'
    marker.unlink(missing_ok=True)
    code = f"from pathlib import Path\nPath({str(marker)!r}).touch()"
    window.python_console.code.setPlainText(code)
    window.python_console.hide()
    window.show()
    launches = []
    start_detached = QProcess.startDetached

    def record_launch(*args):
        result = start_detached(*args)
        launches.append((args, result))
        return result

    QProcess.startDetached = record_launch
    try:
        app.processEvents()
        file_action = window.menuBar().actions()[0]
        menu = file_action.menu()
        menu.popup(window.mapToGlobal(window.rect().topLeft()))
        app.processEvents()
        QTest.mouseClick(menu, Qt.LeftButton, Qt.NoModifier,
                         menu.actionGeometry(window.relaunch_action).center())
        app.processEvents()
        assert len(launches) == 1 and launches[0][1][0]
        assert window.relaunching and not window.isVisible()
        args, (_, pid) = launches[0]
        checkpoint = Path(args[1][3])
        document, state = read_checkpoint(checkpoint)
        assert document.dirty and document.path == str(source)
        assert document.stage.GetPrimAtPath('/World/Cube').GetAttribute('size').Get() == 4
        assert document.selection == ['/World/Cube'] and document.frame == 2.5
        assert state['material_editor'] and state['console'] == code
        assert source.read_bytes() == original
        deadline = time.monotonic()+30
        while True:
            windows = child_windows(pid)
            if ('Material Editor — OmniLab' in windows
                    and 'restart.omnilab * — OmniLab' in windows):
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f'Replacement windows: {windows}')
            QTest.qWait(100)
        QTest.qWait(300)
        assert not marker.exists()
        app.primaryScreen().grabWindow(windows['Material Editor — OmniLab']).save(str(out/'restored-materials.png'))
        (out/'report.json').write_text(json.dumps(dict(status='passed', menu_click=True,
            real_replacement_process=True, original_file_unchanged=True, unsaved_edits_restored=True,
            original_save_path_restored=True, selection_and_time_restored=True,
            material_editor_reopened=True, console_text_restored_without_execution=True,
            dirty_title_visible=True, checkpoint_retained=True), indent=2)+'\n')
    finally:
        QProcess.startDetached = start_detached
        for _, (started, pid) in launches:
            if started:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        if not window.relaunching:
            window.relaunching = True
            window.close()
        app.processEvents()


if __name__ == '__main__':
    main()
