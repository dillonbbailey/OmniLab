"""Native acceptance for calibrated maps, temporal UV blur and camera projection."""
import json
from pathlib import Path
import time

import numpy as np
import OpenImageIO as oiio
from pxr import Gf, UsdGeom

from omnilab.core.fixtures import demo_document
from omnilab.materials.graph import MaterialGraph
from omnilab.materials.bake import prepare_bake
from omnilab.materials.projector import add_projector, freeze_projectors
from omnilab.render.jobs import RenderJob


def read(path):
    image = oiio.ImageInput.open(str(path))
    try:
        return image.read_image()
    finally:
        image.close()


def bake(graph, node, path, motion=None):
    job = RenderJob(prepare_bake(graph, node, path, path.parent / 'jobs', size=64, samples=4, motion=motion))
    job.start()
    deadline = time.monotonic() + 180
    try:
        while job.active and time.monotonic() < deadline:
            job.poll()
            time.sleep(.02)
        assert job.data['state'] == 'complete', job.data.get('error') or job.data['state']
    finally:
        if job.active:
            job.cancel()
    return read(path)


def main():
    out = Path('artifacts/bake-projector').resolve()
    out.mkdir(parents=True, exist_ok=True)
    doc = demo_document()
    graph = MaterialGraph(doc, '/World/Looks/Surface')
    constant = graph.add_node('ND_constant_color3')
    graph.set_value(constant, 'value', [.2, .4, 2.])
    data = bake(graph, constant, out/'constant.exr')
    mean = data[8:-8, 8:-8, :3].mean(axis=(0, 1))
    np.testing.assert_allclose(mean, [.2, .4, 2.], rtol=.01, atol=.002)
    # A repeated red stripe evaluates source UV wrapping during temporal samples.
    pixels = np.zeros((32, 32, 3), np.float32)
    pixels[:, :16, 0] = 1
    image = oiio.ImageOutput.create(str(out/'stripes.exr'))
    image.open(str(out/'stripes.exr'), oiio.ImageSpec(32, 32, 3, oiio.FLOAT))
    image.write_image(pixels)
    image.close()
    texture = graph.add_node('ND_image_color3')
    graph.set_value(texture, 'file', str(out/'stripes.exr'), 'lin_rec709')
    graph.set_value(texture, 'uaddressmode', 'periodic')
    graph.set_value(texture, 'vaddressmode', 'periodic')
    plain = bake(graph, texture, out/'plain.exr')
    directional = bake(graph, texture, out/'directional.exr', dict(type='directional', samples=16, distance=1., direction=0))
    rotational = bake(graph, texture, out/'rotational.exr', dict(type='rotational', samples=16, angle=360., center=[.5,.5]))
    assert np.std(directional[:, :, 0]) < np.std(plain[:, :, 0]) * .15
    np.testing.assert_allclose(directional[4:-4, 4:-4, 0].mean(), .5, atol=.02)
    assert np.std(rotational[8:-8, 8:-8, 0]) < np.std(plain[:, :, 0]) * .2
    pixels[:] = 0
    pixels[:16, :, 0] = 1
    pixels[16:, :, 1] = 1
    pixels[:, 16:, 2] = 1
    image = oiio.ImageOutput.create(str(out/'quadrants.exr'))
    image.open(str(out/'quadrants.exr'), oiio.ImageSpec(32, 32, 3, oiio.FLOAT))
    image.write_image(pixels)
    image.close()
    usd_camera = UsdGeom.Camera.Define(doc.stage, '/World/Projector')
    camera = Gf.Camera()
    camera.projection = Gf.Camera.Orthographic
    camera.horizontalAperture = camera.verticalAperture = 20
    camera.transform = Gf.Matrix4d().SetTranslate((0, 0, 3))
    camera.clippingRange = Gf.Range1f(.01, 100)
    usd_camera.SetFromCamera(camera)
    projected = add_projector(graph, '/World/Projector', str(out/'quadrants.exr'), 'lin_rec709')
    orthographic = bake(graph, projected, out/'orthographic.exr')
    camera.projection = Gf.Camera.Perspective
    camera.focalLength = 30  # Match the same two-unit field at distance three.
    usd_camera.SetFromCamera(camera)
    perspective = bake(graph, projected, out/'perspective.exr')
    expected = [[1,0,0], [1,0,1], [0,1,0], [0,1,1]]
    def quadrants(data):
        return [data[y-3:y+3, x-3:x+3, :3].mean(axis=(0,1)).tolist() for x,y in [(16,16),(48,16),(16,48),(48,48)]]
    for data in (orthographic, perspective):
        np.testing.assert_allclose(quadrants(data), expected, atol=.01)
    # A live link follows the camera, including far/near and behind-camera rejection.
    camera.transform = Gf.Matrix4d().SetTranslate((0, 0, -3))
    usd_camera.SetFromCamera(camera)
    behind = bake(graph, projected, out/'behind.exr')
    assert np.max(behind[:, :, :3]) < .001
    camera.transform = Gf.Matrix4d().SetTranslate((0, 0, 3))
    camera.clippingRange = Gf.Range1f(4, 100)
    usd_camera.SetFromCamera(camera)
    clipped = bake(graph, projected, out/'near-clipped.exr')
    assert np.max(clipped[:, :, :3]) < .001
    camera.clippingRange = Gf.Range1f(.01, 100)
    usd_camera.SetFromCamera(camera)
    freeze_projectors(graph)
    camera.transform = Gf.Matrix4d().SetTranslate((0, 0, -3))
    usd_camera.SetFromCamera(camera)
    frozen = bake(graph, projected, out/'frozen.exr')
    np.testing.assert_allclose(quadrants(frozen), expected, atol=.01)
    report = dict(status='passed', constant_mean=mean.tolist(), directional_wrap_mean=float(directional[:,:,0].mean()),
        plain_std=float(plain[:,:,0].std()), directional_std=float(directional[:,:,0].std()),
        rotational_std=float(rotational[8:-8,8:-8,0].std()), orthographic=quadrants(orthographic),
        perspective=quadrants(perspective), behind_camera_black=True, near_clip_black=True, frozen_link=True)
    (out/'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
