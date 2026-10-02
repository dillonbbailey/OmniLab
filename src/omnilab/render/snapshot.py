"""Private runtime publication. Flattening here never changes durable USD saves."""
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdRender
from omnilab.core.camera import camera_payload

MODES = ("RealTimePathTracing", "PathTracing", "MinimalRendering")


def retire_snapshots(directory, loaded_path):
    """Called only after the worker acknowledges replacing its old runtime stage."""
    import shutil
    root = Path(directory).resolve()
    active = Path(loaded_path).resolve().parent
    if active.parent != root:
        return
    for path in root.iterdir():
        if path.is_dir() and path.name.isdigit() and path != active and not path.is_symlink():
            shutil.rmtree(path)


def publish(document, directory, camera, resolution=(800, 500), mode=MODES[0], samples=16,
            purposes=("default", "render"), aovs=("LdrColor",), *, wireframe=False, wireframe_mode="shaded", region=None, profile='viewport'):
    if mode not in MODES:
        raise ValueError("Unknown renderer mode.")
    if wireframe_mode not in ("shaded", "emissive"):
        raise ValueError("Unknown wireframe mode.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Flatten the composed, loaded, unmuted view only for this disposable render snapshot.
    # USD resolves relative asset paths against the original layers during flattening.
    layer = document.stage.Flatten()
    stage = Usd.Stage.Open(layer)
    from omnilab.materials.projector import synchronize
    synchronize(stage, document.frame)
    root = "/__OmniLabViewport"
    while stage.GetPrimAtPath(root):
        root += "_"
    cam_path, product_path = root + "/Camera", root + "/Product"
    cam = UsdGeom.Camera.Define(stage, cam_path)
    cam.SetFromCamera(camera)
    product = UsdRender.Product.Define(stage, product_path)
    product.CreateCameraRel().SetTargets([cam.GetPath()])
    product.CreateResolutionAttr(Gf.Vec2i(*resolution))
    if region is not None:
        from .render_region import validate_region
        x0, y0, x1, y1 = validate_region(region, *resolution)
        width, height = resolution
        product.CreateDataWindowNDCAttr(Gf.Vec4f(x0 / width, y0 / height, x1 / width, y1 / height))
    preferences = getattr(document, 'view', {})
    devices = preferences.get('renderer_config', {}).get('active_cuda_gpus') or '0'
    product.GetPrim().CreateAttribute("deviceIds", Sdf.ValueTypeNames.UIntArray).Set([int(v) for v in devices.split(',')])
    product.GetPrim().CreateAttribute("omni:rtx:rendermode", Sdf.ValueTypeNames.Token).Set(mode)
    product.GetPrim().CreateAttribute("omni:rtx:pt:samplesPerPixel", Sdf.ValueTypeNames.UInt).Set(int(samples))
    # Author both states explicitly: the renderer persists across snapshots, so
    # leaving the setting absent could retain the previous viewport's wireframe.
    product.GetPrim().CreateAttribute("omni:rtx:wireframe:enabled", Sdf.ValueTypeNames.Bool).Set(wireframe)
    product.GetPrim().CreateAttribute("omni:rtx:wireframe:mode", Sdf.ValueTypeNames.Token).Set(wireframe_mode if wireframe else "instance")
    product.GetPrim().CreateAttribute("omni:rtx:wireframe:thickness", Sdf.ValueTypeNames.Float).Set(1.5)
    from .settings import apply_product
    apply_product(product.GetPrim(), preferences.get('rtx_settings', {}).get(profile, {}))
    variables = []
    for name in aovs:
        if not Sdf.Path.IsValidIdentifier(name):
            raise ValueError("Invalid render output name: " + name)
        var = UsdRender.Var.Define(stage, product_path + "/" + name)
        var.CreateSourceNameAttr(name)
        variables.append(var.GetPath())
    product.CreateOrderedVarsRel().SetTargets(variables)
    for prim in stage.Traverse():
        imageable = UsdGeom.Imageable(prim)
        if imageable and not str(prim.GetPath()).startswith(root) and imageable.ComputePurpose() not in purposes:
            # Strong default plus all existing samples prevents animated visibility from defeating the filter.
            attr = imageable.CreateVisibilityAttr()
            for time in attr.GetTimeSamples():
                attr.ClearAtTime(time)
            attr.Set(UsdGeom.Tokens.invisible)
    path = directory / "viewport.usdc"
    if not layer.Export(str(path)):
        raise RuntimeError("Could not publish the viewport snapshot.")
    return dict(path=str(path.resolve()), product=product_path, camera=cam_path,
                frame=document.frame, time_codes_per_second=document.stage.GetTimeCodesPerSecond(),
                resolution=list(resolution), mode=mode, samples=samples, region=region, camera_data=camera_payload(camera),
                renderer_config=dict(preferences.get('renderer_config', {})),
                settings=dict(preferences.get('rtx_settings', {}).get(profile, {})), device_ids=[int(v) for v in devices.split(',')])
