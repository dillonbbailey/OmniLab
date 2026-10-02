"""UV-card map evaluation and temporal blur through native ovRTX shading."""
import glob
import math
from pathlib import Path

from pxr import Gf, Sdf, UsdGeom, UsdShade
from omnilab.core.document import Document, atomic_json
from omnilab.core.camera import camera_payload
from omnilab.render.jobs import JobOptions, prepare_job
from .graph import MaterialGraph, framework


def bake_scene(graph, node, output='out'):
    shader = graph.shader(node)
    kind, _ = graph._port(shader, output, True)
    if framework(shader) != 'mtlx' or kind not in ('float', 'color3'):
        raise ValueError('UV-card baking accepts nonnegative MaterialX float/color3 maps. Signed vectors and normals require a data-baking backend.')
    document = Document()
    document.view = dict(graph.document.view)
    document.frame = graph.document.frame
    source = graph.stage.Flatten()
    from pxr import Usd
    from .projector import synchronize
    synchronize(Usd.Stage.Open(source), graph.document.frame, graph.path, True)
    layer = document.stage.GetRootLayer()
    Sdf.CreatePrimInLayer(layer, graph.path.GetParentPath())
    Sdf.CopySpec(source, graph.path, layer, graph.path)
    baked = MaterialGraph(document, graph.path, graph.catalog)
    surface = baked.add_node('ND_surface_unlit', 'BakeSurface')
    document._bake_surface = surface
    baked.set_value(surface, 'emission', 1000.)
    if kind != 'color3':
        convert = baked.add_node('ND_convert_' + kind + '_color3', 'BakeColor')
        baked.connect(node, output, convert, 'in')
        node, output = convert, 'out'
    baked.connect(node, output, surface, 'emission_color')
    baked.set_terminal(surface)
    # A wide card lets motion samples evaluate the original graph's UV wrap
    # modes beyond [0,1]. No resampling or display encoding is baked into data.
    mesh = UsdGeom.Mesh.Define(document.stage, '/__OmniLabBake/Card')
    mesh.CreatePointsAttr([(-32, -32, 0), (32, -32, 0), (32, 32, 0), (-32, 32, 0)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    mesh.CreateNormalsAttr([(0, 0, 1)]*4)
    mesh.SetNormalsInterpolation('vertex')
    mesh.CreateSubdivisionSchemeAttr('none')
    UsdGeom.PrimvarsAPI(mesh).CreatePrimvar('st', Sdf.ValueTypeNames.TexCoord2fArray, 'vertex').Set(
        [(-15.5, -15.5), (16.5, -15.5), (16.5, 16.5), (-15.5, 16.5)])
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(baked.material)
    camera = Gf.Camera()
    camera.projection = Gf.Camera.Orthographic
    camera.horizontalAperture = camera.verticalAperture = 20
    camera.transform = Gf.Matrix4d().SetTranslate((0, 0, 3))
    camera.clippingRange = Gf.Range1f(.01, 100)
    return document, camera


def motion_cameras(camera, motion):
    kind = motion.get('type', 'none')
    if kind == 'none':
        return [camera_payload(camera)]
    if kind not in ('rotational', 'directional'):
        raise ValueError('Choose rotational or directional blur.')
    count = motion.get('samples', 32)
    if type(count) is not int or not 2 <= count <= 1024:
        raise ValueError('Use 2–1024 temporal samples.')
    angle, distance, direction = [float(motion.get(k, v)) for k, v in [('angle', 30), ('distance', .1), ('direction', 0)]]
    center = motion.get('center', [.5, .5])
    if not (0 <= angle <= 3600 and 0 <= distance <= 1 and 0 <= direction <= 360 and len(center) == 2
            and all(math.isfinite(v) and -10 <= v <= 10 for v in center)):
        raise ValueError('Use finite blur settings: angle 0–3600°, distance 0–1 UV, direction 0–360°, center −10–10.')
    cameras = []
    for index in range(count):
        fraction = (index + .5)/count - .5
        sample = Gf.Camera(camera)
        if kind == 'rotational':
            px, py = (2 * value - 1 for value in center)
            rotation = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), fraction * angle))
            sample.transform = Gf.Matrix4d().SetTranslate((-px, -py, 0)) * rotation * Gf.Matrix4d().SetTranslate((px, py, 3))
        else:
            radians = math.radians(direction)
            sample.transform = Gf.Matrix4d().SetTranslate((2*fraction*distance*math.cos(radians), 2*fraction*distance*math.sin(radians), 3))
        cameras.append(camera_payload(sample))
    return cameras


def prepare_bake(graph, node, destination, directory, size=512, samples=16, motion=None):
    if type(size) is not int or not 16 <= size <= 8192:
        raise ValueError('Bake resolution must be 16–8192 pixels.')
    target = Path(destination).expanduser().resolve()
    for shader in graph.nodes():
        for name, port in shader['inputs'].items():
            if port['type'] in ('filename', 'asset') and port.get('value'):
                asset = graph.shader(shader['path']).GetInput(name).Get()
                if asset and any(Path(p).resolve() == target for p in glob.glob((asset.resolvedPath or asset.path).replace('<UDIM>', '????'))):
                    raise ValueError('A bake cannot overwrite one of its input textures.')
    document, camera = bake_scene(graph, node)
    job = prepare_job(document, lambda frame: camera, JobOptions(str(target), resolution=(size, size),
        samples=samples, frames=(document.frame,)), directory)
    job['snapshots'][0]['bake_cameras'] = motion_cameras(camera, motion or {})
    # HdrColor carries physical luminance, not the raw shader value. Measure the
    # same unlit surface with a unit input at this job's camera/settings, then
    # remove that linear gain. Never guess a fixed renderer-version scale.
    baked = MaterialGraph(document, graph.path)
    surface = document._bake_surface
    baked.disconnect(surface, 'emission_color')
    baked.set_value(surface, 'emission_color', [1., 1., 1.])
    from omnilab.render.snapshot import publish
    job['calibration'] = publish(document, Path(job['directory']) / 'calibration', camera,
        (32, 32), 'PathTracing', samples, aovs=('HdrColor',), profile='final')
    job['bake'] = dict(material=str(graph.path), node=node, motion=motion or {'type': 'none'},
                       method='native UV-card nonnegative color evaluation; measured unit-emission normalization; linear temporal supersampling')
    atomic_json(Path(job['directory']) / 'job.json', job)
    return job
