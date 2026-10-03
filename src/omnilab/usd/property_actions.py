"""Read-only property and prim actions shared by both editor frontends."""

import json
from pxr import Sdf, Usd, UsdShade
from .usd_editing import encode_value


def json_value(value):
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, Sdf.Path):
        return str(value)
    try:
        return encode_value(value)
    except TypeError:
        return str(value)


def copy_text(value):
    return (
        value
        if isinstance(value, str)
        else json.dumps(json_value(value), ensure_ascii=False)
    )


def property_value(prim, group, name, frame):
    if group == "Attributes":
        return prim.GetAttribute(name).Get(Usd.TimeCode(frame))
    if group == "Relationships":
        return [str(p) for p in prim.GetRelationship(name).GetTargets()]
    return prim.GetMetadata(name)


def prim_text(prim, part, frame):
    if part == "Name":
        return str(prim.GetName())
    if part == "Path":
        return str(prim.GetPath())
    if part == "Type":
        return prim.GetTypeName()
    if part != "Properties":
        raise ValueError("Unknown prim information: " + part)
    return json.dumps(
        dict(
            attributes={
                a.GetName(): dict(
                    type=str(a.GetTypeName()),
                    value=json_value(a.Get(Usd.TimeCode(frame))),
                    connections=[str(p) for p in a.GetConnections()],
                )
                for a in prim.GetAttributes()
            },
            relationships={
                r.GetName(): [str(p) for p in r.GetTargets()]
                for r in prim.GetRelationships()
            },
        ),
        ensure_ascii=False,
        indent=2,
    )


def bound_material_path(prim):
    if not prim or prim.IsPseudoRoot():
        return None
    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    return str(material.GetPath()) if material else None


def prims_with_bound_material(prim):
    material = bound_material_path(prim)
    if not material:
        return []
    return [
        str(p.GetPath())
        for p in Usd.PrimRange.Stage(prim.GetStage(), Usd.TraverseInstanceProxies())
        if bound_material_path(p) == material
    ]
