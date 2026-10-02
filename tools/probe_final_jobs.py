from pathlib import Path
import time,json
import numpy as np
import OpenImageIO as oiio
from pxr import UsdShade
from omnilab.core.fixtures import demo_document
from omnilab.core.camera import ViewCamera
from omnilab.render.jobs import JobOptions,prepare_job,RenderJob

def run(doc,out,region=None,mode='PathTracing',aovs=('HdrColor',),frames=(1.,)):
 camera=ViewCamera(target=[0,1,0],distance=8).camera(1.5)
 job=RenderJob(prepare_job(doc,lambda _:camera,JobOptions(str(out),resolution=(192,128),samples=8,warmup=8,region=region,mode=mode,aovs=aovs,frames=frames),out.parent/'jobs'))
 job.start(); deadline=time.monotonic()+180
 while job.active and time.monotonic()<deadline:
  events=job.poll()
  for e in events: print(e,flush=True)
  time.sleep(.02)
 if job.active: job.cancel(); raise RuntimeError('timeout')
 assert job.data['state']=='complete',job.data
 return job.data

def read(path):
 image=oiio.ImageInput.open(str(path)); spec=oiio.ImageSpec(image.spec()); pixels=image.read_image(); image.close(); return spec,pixels

if __name__=='__main__':
 out=Path('artifacts/final-jobs').resolve();out.mkdir(parents=True,exist_ok=True)
 doc=demo_document(); jobs=[]
 jobs.append(run(doc,out/'beauty.exr'))
 _,full=read(out/'beauty.exr'); region=(31,13,143,91)
 jobs.append(run(doc,out/'crop.exr',region))
 _,crop=read(out/'crop.exr')
 x0,y0,x1,y1=region
 same=float(np.mean(abs(full[y0:y1,x0:x1]-crop[y0:y1,x0:x1])))
 flipped=float(np.mean(abs(full[128-y1:128-y0,x0:x1]-crop[y0:y1,x0:x1])))
 assert same < flipped * .5, 'Crop coordinates do not match the full image'
 shader=UsdShade.Shader.Get(doc.stage,'/World/Looks/Surface/Shader');shader.GetInput('base_color').Set((0.,1.,0.))
 jobs.append(run(doc,out/'beauty.exr',region))
 _,merged=read(out/'beauty.exr'); mask=np.ones((128,192),bool);mask[y0:y1,x0:x1]=False
 assert np.array_equal(full[mask],merged[mask])
 jobs.append(run(doc,out/'aovs.exr',mode='RealTimePathTracing',aovs=('HdrColor','NormalSD','DistanceToCameraSD','DistanceToImagePlaneSD','Camera3dPositionSD')))
 spec,aovs=read(out/'aovs.exr')
 jobs.append(run(doc,out/'pt-depth.exr',aovs=('HdrColor','DistanceToCameraSD')))
 depth_spec,depth_pixels=read(out/'pt-depth.exr')
 depth=float(depth_pixels[64,96,list(depth_spec.channelnames).index('DistanceToCameraSD.Z')])
 assert 3 < depth < 12, 'PT did not return the expected metric scene distance'
 finite = aovs[np.isfinite(aovs)]
 report=dict(status='passed',crop_matching_difference=same,crop_opposite_y_difference=flipped,outside_region_exact=True,channels=list(spec.channelnames),pt_center_distance_m=depth,finite_aov_range=[float(finite.min()),float(finite.max())],nonfinite_aov_values=int((~np.isfinite(aovs)).sum()),jobs=[j['directory'] for j in jobs])
 (out/'report.json').write_text(json.dumps(report,indent=2)); print(report,flush=True)
