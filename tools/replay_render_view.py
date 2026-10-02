from pathlib import Path
import json,time
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from omnilab.frontends.qt.window import MainWindow

def main():
 out=Path('artifacts/render-view').resolve();out.mkdir(parents=True,exist_ok=True)
 app=QApplication([]);app.setStyle('Fusion');w=MainWindow(False);w.new_demo();w.show();w.open_render_view();v=w.render_view
 def wait_for(predicate):
  deadline=time.monotonic()+150
  while not predicate():
   if time.monotonic()>deadline:raise TimeoutError(v.status.text()+' '+v.log.toPlainText())
   app.processEvents();QTest.qWait(10)
 try:
  v.width.setValue(384);v.height.setValue(256);v.samples.setValue(16);v.output.setText(str(out/'beauty.exr'))
  QTest.mouseClick(v.render_button,Qt.LeftButton);wait_for(lambda:v.job is not None and not v.job.active)
  assert v.job.data['state']=='complete',v.log.toPlainText()
  wait_for(lambda:v.image_info is not None);v.fit();app.processEvents();v.grab().save(str(out/'render-view.png'))
  v.component.setCurrentText('A');wait_for(lambda:v.image_info is not None and v.image_info['request']==v.image_request)
  v.probe(192,128);assert 'Matte:' in v.probe_label.text()
  v.component.setCurrentText('RGB');v.matte_overlay.setChecked(True);wait_for(lambda:v.image_info is not None and v.image_info['request']==v.image_request)
  v.matte_overlay.setChecked(False)
  v.samples.setValue(1000000);v.start();wait_for(lambda:'Rendering frame' in v.status.text());started=time.monotonic();v.cancel();cancel=time.monotonic()-started
  assert v.job.data['state']=='cancelled'
  v.samples.setValue(4);v.sequence.setChecked(True);v.start_frame.setValue(1.25);v.end_frame.setValue(1.5);v.step_frame.setValue(.25);v.output.setText(str(out/'sequence.{frame}.exr'));v.start();wait_for(lambda:not v.job.active)
  assert v.job.data['state']=='complete',v.log.toPlainText()
  (out/'report.json').write_text(json.dumps(dict(status='passed',cancel_seconds=cancel,fractional_frames=[x['frame'] for x in v.job.data['completed']],exr_display=True,matte_component_and_pixel_probe=True),indent=2))
 finally:
  v.shutdown();w.document.edits.saved={layer:layer.ExportToString() for layer in w.document.edits.saved};w.close()
if __name__=='__main__':main()
