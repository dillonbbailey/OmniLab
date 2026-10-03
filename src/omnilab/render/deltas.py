"""Runtime-only world-transform previews shared by frontend manipulators."""

from pxr import Usd, UsdGeom


def transform_deltas(document, path, before, after):
    delta = before.GetInverse() * after
    root = document.stage.GetPrimAtPath(path)
    cache = UsdGeom.XformCache(Usd.TimeCode(document.frame))
    skip, result = [], {}
    for prim in Usd.PrimRange(root):
        xform = UsdGeom.Xformable(prim)
        if not xform or any(prim.GetPath().HasPrefix(p) for p in skip):
            continue
        if prim != root and xform.GetResetXformStack():
            skip.append(prim.GetPath())
            continue
        matrix = cache.GetLocalToWorldTransform(prim) * delta
        name = str(prim.GetPath())
        result[name + ".omni:xform"] = dict(
            path=name,
            attribute="omni:xform",
            value=[list(r) for r in matrix],
            dtype="float64",
            lanes=16,
        )
    return result
