"""Prim inspection and clipboard actions preserve full typed values and history."""

import json
from pxr import Sdf, UsdGeom, UsdShade
from omnilab.core.fixtures import demo_document
from omnilab.usd.property_actions import (
    copy_text,
    prim_text,
    property_value,
    bound_material_path,
    prims_with_bound_material,
)


def test_bound_material_selection_includes_inherited_bindings_and_excludes_other_materials():
    document = demo_document()
    stage = document.stage
    material = UsdShade.Material.Get(stage, "/World/Looks/Surface")
    group = UsdGeom.Xform.Define(stage, "/World/Group").GetPrim()
    child = UsdGeom.Cube.Define(stage, "/World/Group/Child").GetPrim()
    other = UsdGeom.Cube.Define(stage, "/World/Group/Other").GetPrim()
    UsdShade.MaterialBindingAPI.Apply(group).Bind(material)
    different = UsdShade.Material.Define(stage, "/World/Looks/Different")
    UsdShade.MaterialBindingAPI.Apply(other).Bind(different)
    before = stage.GetRootLayer().ExportToString()
    assert bound_material_path(child) == "/World/Looks/Surface"
    assert set(prims_with_bound_material(child)) == {
        "/World/Sphere",
        "/World/Group",
        "/World/Group/Child",
    }
    assert prims_with_bound_material(stage.GetPrimAtPath("/World/Cube")) == []
    assert prims_with_bound_material(stage.GetPseudoRoot()) == []
    assert stage.GetRootLayer().ExportToString() == before
    assert not document.edits.undo


def test_copy_prim_and_property_values_use_current_frame_without_display_truncation():
    document = demo_document()
    prim = document.stage.GetPrimAtPath("/World/Cube")
    attr = prim.CreateAttribute("test:color", Sdf.ValueTypeNames.Color3f)
    attr.Set((2.0, 0.125, 0.625), 4)
    attr.Set((0.25, 0.5, 0.75), 8)
    long_values = list(range(40))
    prim.CreateAttribute("test:array", Sdf.ValueTypeNames.IntArray).Set(long_values)
    prim.CreateRelationship("test:target").SetTargets(["/World/Sphere"])
    assert prim_text(prim, "Name", 4) == "Cube"
    assert prim_text(prim, "Path", 4) == "/World/Cube"
    assert prim_text(prim, "Type", 4) == "Cube"
    properties = json.loads(prim_text(prim, "Properties", 4))
    assert properties["attributes"]["test:color"]["value"] == [2.0, 0.125, 0.625]
    assert properties["attributes"]["test:array"]["value"] == long_values
    assert properties["relationships"]["test:target"] == ["/World/Sphere"]
    assert json.loads(
        copy_text(property_value(prim, "Attributes", "test:color", 8))
    ) == [0.25, 0.5, 0.75]
    assert not document.edits.undo
