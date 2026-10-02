from pathlib import Path
import json
import numpy as np
from PIL import Image
from pxr import UsdShade
from omnilab.core.fixtures import demo_document
from omnilab.core.camera import ViewCamera
from omnilab.materials.graph import create_material
from omnilab.materials.catalog import default_catalog
from omnilab.materials.mdl import load_module
from omnilab.render.backend import Backend
from omnilab.render.snapshot import publish

out=Path('artifacts/mdl-graph');out.mkdir(parents=True,exist_ok=True)
catalog=default_catalog();definitions,report=load_module(catalog,'tests/fixtures/materials/omnilab_test.mdl')
document=demo_document();graph=create_material(document,'MDL',next(d.identifier for d in definitions if d.metadata['material']))
function=graph.add_node(next(d.identifier for d in definitions if not d.metadata['material']))
graph.connect(function,'out',str(graph.path)+'/Surface','tint')
UsdShade.MaterialBindingAPI(document.stage.GetPrimAtPath('/World/Sphere')).Bind(graph.material)
camera=ViewCamera(target=[-.5,.8,0],distance=12,yaw=24,pitch=18).camera(1.6)
backend=Backend(out/'renderer.log')
images=[]
try:
 for name,color in [('red',[.8,.03,.01]),('green',[.02,.8,.04])]:
  graph.set_value(function,'value',color)
  snapshot=publish(document,out/name,camera,(640,400))
  backend.load(snapshot)
  for _ in range(8):arrays,hits,ms=backend.render()
  image=arrays['LdrColor'];Image.fromarray(image).save(out/(name+'.png'));images.append(image)
 difference=float(np.abs(images[0].astype(float)-images[1]).mean())
 assert difference>1,difference
 (out/'report.json').write_text(json.dumps(dict(status='passed',function_graph_difference=difference,reflection=report),indent=2)+'\n')
 print(difference)
finally:backend.close()
