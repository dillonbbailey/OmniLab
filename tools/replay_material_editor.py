import json, time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QPoint
from omnilab.frontends.qt.window import MainWindow
from omnilab.materials.graph import create_material

def main():
    out=Path('artifacts/material-editor');out.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);app.setStyle('Fusion');w=MainWindow(False);w.new_demo();w.open_material_editor()
    editor=w.material_editor;panel=editor.current();preview=editor.preview
    def wait_for(predicate):
        deadline=time.monotonic()+120
        while not predicate():
            if time.monotonic()>deadline:raise TimeoutError(preview.status.text())
            app.processEvents();QTest.qWait(10)
    try:
        QTest.mouseClick(panel.library_sections, Qt.LeftButton, Qt.NoModifier, panel.library_sections.tabRect(2).center())
        panel.search.setText('constant color3');app.processEvents();QTest.qWait(200)
        item=panel.library.item(0);assert item.data(Qt.UserRole)=='ND_constant_color3'
        QTest.mouseClick(panel.library.viewport(),Qt.LeftButton,Qt.NoModifier,panel.library.visualItemRect(item).center())
        QTest.mouseDClick(panel.library.viewport(),Qt.LeftButton,Qt.NoModifier,panel.library.visualItemRect(item).center())
        app.processEvents();assert len(panel.graph.nodes())==2
        node=next(n for n in panel.graph.nodes() if n['identifier']=='ND_constant_color3')
        panel.graph.set_value(node['path'],'value',[.8,.08,.02]);panel.reload()
        panel.canvas.all_ports=True;panel.reload();panel.command('arrange');app.processEvents()
        source=panel.canvas.nodes[node['path']].ports[('out',True)]
        target=panel.canvas.nodes['/World/Looks/Surface/Shader'].ports[('base_color',False)]
        a=panel.canvas.mapFromScene(source.scenePos());b=panel.canvas.mapFromScene(target.scenePos())
        QTest.mousePress(panel.canvas.viewport(),Qt.LeftButton,Qt.NoModifier,a)
        QTest.mouseMove(panel.canvas.viewport(),b,20)
        QTest.mouseRelease(panel.canvas.viewport(),Qt.LeftButton,Qt.NoModifier,b)
        app.processEvents();assert panel.graph.shader('/World/Looks/Surface/Shader').GetInput('base_color').HasConnectedSource()
        preview.start();wait_for(lambda:preview.presented_request==preview.request);QTest.qWait(300)
        panel.show_ports(False);panel.command('arrange');panel.canvas.nodes['/World/Looks/Surface/Shader'].setSelected(True)
        app.processEvents();wait_for(lambda:preview.presented_request==preview.request)
        preview.picture.save(str(out/'openpbr-red.png'));editor.grab().save(str(out/'editor.png'))
        panel.graph.set_value(node['path'],'value',[.02,.8,.04]);panel.reload();editor.changed()
        wait_for(lambda:preview.presented_request==preview.request);QTest.qWait(300)
        preview.picture.save(str(out/'openpbr-green.png'))
        layer_before = w.document.stage.GetRootLayer().ExportToString()
        camera_before = preview.camera.to_dict()
        QTest.mousePress(preview.label, Qt.LeftButton, Qt.NoModifier, QPoint(100,100))
        QTest.mouseMove(preview.label, QPoint(155,115), 10)
        QTest.mouseRelease(preview.label, Qt.LeftButton, Qt.NoModifier, QPoint(155,115))
        wait_for(lambda:preview.presented_request==preview.request)
        assert preview.camera.to_dict() != camera_before
        assert w.document.stage.GetRootLayer().ExportToString() == layer_before
        from PIL import Image
        texture = out/'texture.1001.png'
        Image.new('RGB',(64,32),(200,50,20)).save(texture)
        image_node = panel.graph.add_node('ND_image_color3')
        panel.graph.set_value(image_node, 'file', str(texture.resolve()).replace('1001','<UDIM>'), 'srgb_texture')
        panel.reload();panel.inspect(image_node)
        wait_for(lambda:panel.texture_preview.pixmap() is not None and not panel.texture_preview.pixmap().isNull())
        assert '64 × 32' in panel.texture_preview.toolTip()
        second=create_material(w.document,'Second');editor.open_material(second.path);app.processEvents()
        assert preview.picture.isNull()
        editor.tabs.setCurrentIndex(0);wait_for(lambda:not preview.picture.isNull())
        w.document.save(out/'graphs.omnilab')
        (out/'report.json').write_text(json.dumps(dict(status='passed',node_library=True,port_drag=True,tab_preview_isolation=True,preview_camera_navigation=True,udim_thumbnail=True),indent=2)+'\n')
    finally:
        editor.shutdown();w.document.edits.saved={layer:layer.ExportToString() for layer in w.document.edits.saved};w.close();app.processEvents()
if __name__=='__main__':main()
