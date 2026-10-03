"""Shared native material-preview scene for every frontend."""

import math
from pxr import Sdf, Usd, UsdShade, UsdGeom, UsdLux
from omnilab.core.fixtures import demo_document


def studio_scene(graph, view_camera, geometry="Sphere", light=1.0, hdri=""):
    if not graph:
        raise ValueError("Select a material before rendering the studio.")
    document = demo_document()
    document.view = dict(graph.document.view)
    document.frame = graph.document.frame
    # A smooth UV sphere makes roughness, normal maps and image nodes
    # readable; the runtime's implicit-sphere tessellation is coarse.
    document.stage.RemovePrim("/World/Sphere")
    sphere = UsdGeom.Mesh.Define(document.stage, "/World/Sphere")
    points, normals, uvs, counts, indices = [], [], [], [], []
    for latitude in range(33):
        v = latitude / 32
        for longitude in range(65):
            u = longitude / 64
            normal = (
                math.sin(math.pi * v) * math.cos(2 * math.pi * u),
                math.cos(math.pi * v),
                math.sin(math.pi * v) * math.sin(2 * math.pi * u),
            )
            normals.append(normal)
            points.append((normal[0], normal[1] + 1, normal[2]))
            uvs.append((u, 1 - v))
    for y in range(32):
        for x in range(64):
            a = y * 65 + x
            face = [a, a + 1, a + 66, a + 65]
            if y == 0:
                face = [a, a + 66, a + 65]
            elif y == 31:
                face = [a, a + 1, a + 65]
            counts.append(len(face))
            indices.extend(face)
    sphere.CreatePointsAttr(points)
    sphere.CreateFaceVertexCountsAttr(counts)
    sphere.CreateFaceVertexIndicesAttr(indices)
    sphere.CreateNormalsAttr(normals)
    sphere.SetNormalsInterpolation("vertex")
    sphere.CreateSubdivisionSchemeAttr("none")
    UsdGeom.PrimvarsAPI(sphere).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, "vertex"
    ).Set(uvs)
    document.stage.RemovePrim("/World/Looks/Surface")
    flattened = graph.stage.Flatten()
    from omnilab.materials.projector import synchronize

    synchronize(Usd.Stage.Open(flattened), graph.document.frame, graph.path, True)
    Sdf.CreatePrimInLayer(document.stage.GetRootLayer(), graph.path.GetParentPath())
    Sdf.CopySpec(flattened, graph.path, document.stage.GetRootLayer(), graph.path)
    for path in ["/World/Sphere", "/World/Cube"]:
        UsdShade.MaterialBindingAPI.Apply(document.stage.GetPrimAtPath(path)).Bind(
            UsdShade.Material(document.stage.GetPrimAtPath(graph.path))
        )
    if geometry == "Sphere":
        document.stage.RemovePrim("/World/Cube")
    else:
        document.stage.RemovePrim("/World/Sphere")
        cube = UsdGeom.Xformable(document.stage.GetPrimAtPath("/World/Cube"))
        cube.ClearXformOpOrder()
        cube.AddTranslateOp().Set((0, 1, 0))
        if geometry == "Card":
            document.stage.RemovePrim("/World/Cube")
            card = UsdGeom.Mesh.Define(document.stage, "/World/Card")
            card.CreatePointsAttr(
                [(-1.3, -0.3, 0), (1.3, -0.3, 0), (1.3, 2.3, 0), (-1.3, 2.3, 0)]
            )
            card.CreateFaceVertexCountsAttr([4])
            card.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
            card.CreateSubdivisionSchemeAttr("none")
            UsdGeom.PrimvarsAPI(card).CreatePrimvar(
                "st", Sdf.ValueTypeNames.TexCoord2fArray, "vertex"
            ).Set([(0, 0), (1, 0), (1, 1), (0, 1)])
            UsdShade.MaterialBindingAPI.Apply(card.GetPrim()).Bind(
                UsdShade.Material.Get(document.stage, graph.path)
            )
    UsdLux.DistantLight(
        document.stage.GetPrimAtPath("/World/Key")
    ).GetIntensityAttr().Set(2500 * light)
    dome = UsdLux.DomeLight(document.stage.GetPrimAtPath("/World/Fill"))
    dome.GetIntensityAttr().Set(250 * light if not hdri else light)
    if hdri:
        dome.CreateTextureFileAttr().Set(Sdf.AssetPath(hdri))
    camera = view_camera.camera(1)
    return document, camera
