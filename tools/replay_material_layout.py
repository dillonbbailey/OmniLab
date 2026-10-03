"""Check real OmniPBR layout and native preview on an isolated desktop display."""
import json
import time
from pathlib import Path
from importlib.util import find_spec

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from omnilab.frontends.qt.window import MainWindow
from omnilab.materials.catalog import default_catalog
from omnilab.materials.graph import create_material
from omnilab.materials.mdl import reflect_module, install_module


def main():
    out = Path('artifacts/material-layout')
    out.mkdir(parents=True, exist_ok=True)
    module = Path(find_spec('ovrtx').origin).parent/'bin/library/mdl/Base/OmniPBR.mdl'
    report = reflect_module(module)
    definition = install_module(default_catalog(), report)[0]
    app = QApplication([])
    app.setStyle('Fusion')
    window = MainWindow(False)
    window.new_demo()
    graph = create_material(window.document, 'OmniPBR', definition.identifier)
    window.document.view['mdl_catalog'] = [report]
    window.document.select([str(graph.path)])
    window.show()
    window.open_material_editor()
    editor, panel = window.material_editor, window.material_editor.current()
    try:
        editor.resize(1480, 900)
        app.processEvents()
        node = panel.canvas.nodes[graph.nodes()[0]['path']]
        point = panel.canvas.mapFromScene(node.sceneBoundingRect().center())
        QTest.mouseClick(panel.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        app.processEvents()
        assert panel.current_node == str(node.node['path'])
        assert panel.node_identifier.toolTip() == definition.identifier
        assert editor.width() == 1480
        assert panel.canvas.width() >= 280 and panel.inspector.width() >= 275
        assert editor.preview.width() >= 300
        editor.preview.start()
        deadline = time.monotonic()+90
        while editor.preview.picture.isNull():
            if time.monotonic()>deadline:
                raise TimeoutError(editor.preview.status.text())
            app.processEvents()
            QTest.qWait(20)
        editor.grab().save(str(out/'mdl-layout.png'))
        size = [editor.width(), editor.height()]
        editor.resize(1300, 800)
        app.processEvents()
        assert editor.width() == 1300
        assert editor.preview.label.pixmap().width() <= editor.preview.label.width()
        editor.grab().save(str(out/'mdl-compact.png'))
        for index, name in enumerate(['OpenPBR', 'MDL', 'MaterialX']):
            QTest.mouseClick(panel.library_sections, Qt.LeftButton, Qt.NoModifier,
                             panel.library_sections.tabRect(index).center())
            app.processEvents()
            assert panel.library_sections.tabText(panel.library_sections.currentIndex()) == name
        window.document.save(out/'omnipbr.omnilab')
        (out/'report.json').write_text(json.dumps(dict(status='passed', size=size,
            compact_width=editor.width(), identifier_length=len(definition.identifier),
            canvas_width=panel.canvas.width(), inspector_width=panel.inspector.width(),
            preview_width=editor.preview.width(), framework_sections=True, native_mdl_preview=True), indent=2)+'\n')
    finally:
        window.relaunching = True
        window.close()
        app.processEvents()


if __name__ == '__main__':
    main()
