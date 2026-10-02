"""Small, self-contained authoring and renderer acceptance scene."""
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdShade
from .document import Document


def demo_document(material="openpbr"):
    doc = Document()
    stage = doc.stage
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    stage.SetStartTimeCode(1)
    stage.SetEndTimeCode(120)
    stage.SetTimeCodesPerSecond(24)
    looks = UsdShade.Material.Define(stage, "/World/Looks/Surface")
    shader = UsdShade.Shader.Define(stage, "/World/Looks/Surface/Shader")
    if material == "mdl":
        # An absolute SDK asset path survives USD's save/reanchor path handling.
        # The module is provided by the user's runtime installation, never copied.
        from importlib.util import find_spec
        from pathlib import Path
        spec = find_spec("ovrtx")
        module = Path(spec.origin).parent / "bin/library/mdl/Base/OmniPBR.mdl" if spec else None
        if module is None or not module.exists():
            raise ValueError("Install the rtx extra to create the bundled MDL demo.")
        shader.SetSourceAsset(Sdf.AssetPath(str(module)), "mdl")
        shader.SetSourceAssetSubIdentifier("OmniPBR", "mdl")
        shader.CreateInput("diffuse_color_constant", Sdf.ValueTypeNames.Color3f).Set((.06, .35, .8))
        shader.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(.25)
        looks.CreateSurfaceOutput("mdl").ConnectToSource(shader.CreateOutput("out", Sdf.ValueTypeNames.Token))
    else:
        shader.CreateIdAttr("ND_open_pbr_surface_surfaceshader")
        shader.CreateInput("base_color", Sdf.ValueTypeNames.Color3f).Set((.08, .32, .65))
        shader.CreateInput("base_metalness", Sdf.ValueTypeNames.Float).Set(.35)
        shader.CreateInput("specular_roughness", Sdf.ValueTypeNames.Float).Set(.23)
        looks.CreateSurfaceOutput("mtlx").ConnectToSource(shader.CreateOutput("out", Sdf.ValueTypeNames.Token))
    ball = UsdGeom.Sphere.Define(stage, "/World/Sphere")
    ball.AddTranslateOp().Set((0, 1, 0))
    UsdShade.MaterialBindingAPI.Apply(ball.GetPrim()).Bind(looks)
    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube.CreateSizeAttr(1.5)
    cube.AddTranslateOp().Set((-2.3, .75, 0))
    cube.CreateDisplayColorAttr([(0.7, 0.18, 0.06)])
    floor = UsdGeom.Cube.Define(stage, "/World/Floor")
    floor.AddTranslateOp().Set((0, -.15, 0))
    floor.AddScaleOp().Set((5, .15, 5))
    floor.CreateDisplayColorAttr([(.2, .22, .25)])
    light = UsdLux.DistantLight.Define(stage, "/World/Key")
    light.CreateIntensityAttr(2500)
    light.CreateAngleAttr(8)
    light.AddRotateXYZOp().Set((-35, -25, 0))
    fill = UsdLux.DomeLight.Define(stage, "/World/Fill")
    fill.CreateIntensityAttr(250)
    camera = UsdGeom.Camera.Define(stage, "/World/Camera")
    matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(6, 4, 10), Gf.Vec3d(-.5, .7, 0), Gf.Vec3d(0, 1, 0)).GetInverse()
    camera.AddTransformOp().Set(matrix)
    doc.frame = 1
    doc.edits.saved = {layer: layer.ExportToString() for layer in doc.edits.saved}
    return doc
