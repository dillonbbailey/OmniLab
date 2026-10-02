"""Camera-projected MaterialX texture coordinates with explicit live/frozen links."""
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade


def camera_matrix(stage, camera_path, frame):
    camera = UsdGeom.Camera.Get(stage, camera_path)
    if not camera:
        raise ValueError('The linked projector camera does not exist: ' + camera_path)
    frustum = camera.GetCamera(Usd.TimeCode(frame)).frustum
    # MaterialX transformmatrix multiplies a column vector; Gf uses row vectors.
    return (frustum.ComputeViewMatrix() * frustum.ComputeProjectionMatrix()).GetTranspose()


def add_projector(graph, camera_path, texture, colorspace='srgb_texture'):
    matrix = camera_matrix(graph.stage, camera_path, graph.document.frame)
    def action():
        position = graph.add_node('ND_position_vector3', 'ProjectorPosition')
        graph.set_value(position, 'space', 'world')
        combined = graph.add_node('ND_combine4_vector4', 'ProjectorPoint')
        graph.set_value(combined, 'in4', 1.)
        for axis in range(3):
            extract = graph.add_node('ND_extract_vector3', 'Projector' + 'XYZ'[axis])
            graph.set_value(extract, 'index', axis)
            graph.connect(position, 'out', extract, 'in')
            graph.connect(extract, 'out', combined, 'in' + str(axis+1))
        transform = graph.add_node('ND_transformmatrix_vector4', 'ProjectorMatrix')
        graph.set_value(transform, 'mat', [list(row) for row in matrix])
        graph.connect(combined, 'out', transform, 'in')
        weight = graph.add_node('ND_extract_vector4', 'ProjectorW')
        graph.set_value(weight, 'index', 3)
        graph.connect(transform, 'out', weight, 'in')
        denominator = graph.add_node('ND_max_float', 'ProjectorSafeW')
        graph.set_value(denominator, 'in2', 1e-7)
        graph.connect(weight, 'out', denominator, 'in1')
        uv = graph.add_node('ND_combine2_vector2', 'ProjectorUV')
        for axis in range(2):
            extract = graph.add_node('ND_extract_vector4', 'ProjectorClip' + 'XY'[axis])
            graph.set_value(extract, 'index', axis)
            graph.connect(transform, 'out', extract, 'in')
            divide = graph.add_node('ND_divide_float', 'ProjectorDivide' + 'XY'[axis])
            graph.connect(extract, 'out', divide, 'in1')
            graph.connect(denominator, 'out', divide, 'in2')
            multiply = graph.add_node('ND_multiply_float', 'ProjectorScale' + 'XY'[axis])
            graph.set_value(multiply, 'in2', .5)
            graph.connect(divide, 'out', multiply, 'in1')
            add = graph.add_node('ND_add_float', 'ProjectorOffset' + 'XY'[axis])
            graph.set_value(add, 'in2', .5)
            graph.connect(multiply, 'out', add, 'in1')
            graph.connect(add, 'out', uv, 'in' + str(axis+1))
        depth = graph.add_node('ND_extract_vector4', 'ProjectorClipZ')
        graph.set_value(depth, 'index', 2)
        graph.connect(transform, 'out', depth, 'in')
        normalized = graph.add_node('ND_divide_float', 'ProjectorDepth')
        graph.connect(depth, 'out', normalized, 'in1')
        graph.connect(denominator, 'out', normalized, 'in2')
        absolute = graph.add_node('ND_absval_float', 'ProjectorDepthMagnitude')
        graph.connect(normalized, 'out', absolute, 'in')
        clip_depth = graph.add_node('ND_ifgreater_vector2', 'ProjectorClipDepth')
        graph.connect(absolute, 'out', clip_depth, 'value1')
        graph.set_value(clip_depth, 'value2', 1.)
        graph.set_value(clip_depth, 'in1', [-1., -1.])
        graph.connect(uv, 'out', clip_depth, 'in2')
        clip_back = graph.add_node('ND_ifgreater_vector2', 'ProjectorClipBehind')
        graph.connect(weight, 'out', clip_back, 'value1')
        graph.set_value(clip_back, 'value2', 1e-7)
        graph.connect(clip_depth, 'out', clip_back, 'in1')
        graph.set_value(clip_back, 'in2', [-1., -1.])
        image = graph.add_node('ND_image_color3', 'ProjectedTexture')
        graph.set_value(image, 'file', str(texture), colorspace)
        graph.set_value(image, 'uaddressmode', 'constant')
        graph.set_value(image, 'vaddressmode', 'constant')
        graph.connect(clip_back, 'out', image, 'texcoord')
        graph.shader(image).GetPrim().SetCustomDataByKey('omnilab:projector', dict(camera=camera_path, matrix=transform, auto=True))
        graph.shader(image).GetPrim().CreateRelationship('omnilab:projectorCamera').SetTargets([camera_path])
        graph.shader(image).GetPrim().CreateRelationship('omnilab:projectorMatrix').SetTargets([transform])
        return image
    return graph.change('Create camera projector', action)


def synchronize(stage, frame, material_path=None, freeze=False):
    """Evaluate links on a private render stage, or explicitly freeze authored links."""
    changed = []
    for prim in stage.Traverse():
        if material_path and not prim.GetPath().HasPrefix(material_path):
            continue
        link = prim.GetCustomDataByKey('omnilab:projector')
        if not link or not link.get('auto'):
            continue
        camera_rel = prim.GetRelationship('omnilab:projectorCamera')
        matrix_rel = prim.GetRelationship('omnilab:projectorMatrix')
        camera_path = str(camera_rel.GetTargets()[0]) if camera_rel and camera_rel.GetTargets() else link['camera']
        matrix_path = str(matrix_rel.GetTargets()[0]) if matrix_rel and matrix_rel.GetTargets() else link['matrix']
        shader = UsdShade.Shader.Get(stage, matrix_path)
        if not shader:
            raise ValueError('Projector matrix node is missing: ' + matrix_path)
        shader.GetInput('mat').Set(camera_matrix(stage, camera_path, frame))
        if freeze:
            prim.SetCustomDataByKey('omnilab:projector', dict(link, auto=False))
        changed.append(str(prim.GetPath()))
    return changed


def freeze_projectors(graph):
    return graph.change('Freeze camera projectors', lambda: synchronize(graph.stage, graph.document.frame, graph.path, True))
