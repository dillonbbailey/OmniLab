"""Select resolved material users and bind an existing material without copying it."""
from pxr import Usd, UsdGeom, UsdShade, UsdLux

from .usd_editing import editable_prim



def scene_material(stage, path):
    material = UsdShade.Material.Get(stage, path)
    if not material or not material.GetPrim().IsActive() or material.GetPrim().IsInPrototype():
        raise ValueError("Choose an active Material in the USD scene.")
    return material


def material_users(stage):
    """Yield effective users once, sharing selection and menu-availability rules."""
    for prim in stage.Traverse(Usd.TraverseInstanceProxies()):
        # Include renderable users, face subsets, and explicit binding owners.
        subset = UsdGeom.Subset(prim)
        material_subset = (subset and subset.GetElementTypeAttr().Get() == UsdGeom.Tokens.face
                           and subset.GetFamilyNameAttr().Get() == UsdShade.Tokens.materialBind)
        if not (prim.IsA(UsdGeom.Gprim) or prim.IsA(UsdGeom.PointInstancer)
                or material_subset or any(
                    (r.GetName() == "material:binding" or r.GetName().startswith("material:binding:")) and r.GetTargets()
                    for r in prim.GetRelationships())):
            continue
        api = UsdShade.MaterialBindingAPI(prim)
        materials = set()
        for purpose in UsdShade.MaterialBindingAPI.GetMaterialPurposes():
            resolved, _ = api.ComputeBoundMaterial(purpose)
            if resolved:
                materials.add(str(resolved.GetPath()))
        if materials:
            yield str(prim.GetPath()), materials


def bound_prim_paths(stage, material_path):
    material_path = str(scene_material(stage, material_path).GetPath())
    return [path for path, materials in material_users(stage) if material_path in materials]


def bound_material_paths(stage):
    return {material for _, materials in material_users(stage) for material in materials}


def bind_existing_material(stage, material_path, paths):
    """Call inside StageEdits.change so a failed assignment rolls back the batch."""
    material = scene_material(stage, material_path)
    paths = list(dict.fromkeys(paths))
    if not paths:
        raise ValueError("Select one or more prims in USD Viewer first.")
    prims = [stage.GetPrimAtPath(path) for path in paths]
    for path, prim in zip(paths, prims):
        if not editable_prim(prim) or not can_bind_material(prim):
            raise ValueError("Cannot bind a material to " + path + ". Select editable geometry, transforms/scopes or mesh face subsets.")
    for prim in prims:
        prepare_material_binding(prim)
        api = UsdShade.MaterialBindingAPI.Apply(prim)
        for purpose in (UsdShade.Tokens.allPurpose, UsdShade.Tokens.full, UsdShade.Tokens.preview):
            resolved, _ = api.ComputeBoundMaterial(purpose)
            if purpose != UsdShade.Tokens.allPurpose and resolved and resolved.GetPath() == material.GetPath():
                continue
            relationship = api.GetDirectBindingRel(purpose)
            strength = UsdShade.MaterialBindingAPI.GetMaterialBindingStrength(relationship)
            if not api.Bind(material, bindingStrength=strength, materialPurpose=purpose):
                raise ValueError("USD could not bind the material to " + str(prim.GetPath()))
    for prim in prims:
        api = UsdShade.MaterialBindingAPI(prim)
        for purpose in UsdShade.MaterialBindingAPI.GetMaterialPurposes():
            resolved, _ = api.ComputeBoundMaterial(purpose)
            if not resolved or resolved.GetPath() != material.GetPath():
                raise ValueError("A stronger layer, ancestor or collection binding takes precedence on " +
                                 str(prim.GetPath()) + ". No assignments were applied; adjust that binding or the edit target first.")
    return dict(material=str(material.GetPath()), paths=paths)


def can_bind_material(prim):
    if not prim or prim.IsPseudoRoot() or not prim.IsActive() or prim.IsInstanceProxy() or prim.IsInPrototype():
        return False
    if prim.IsA(UsdGeom.Subset):
        return prim.GetParent().IsA(UsdGeom.Mesh) and UsdGeom.Subset(prim).GetElementTypeAttr().Get() == UsdGeom.Tokens.face
    return bool(UsdGeom.Imageable(prim) and not prim.IsA(UsdGeom.Camera) and
                (not prim.HasAPI(UsdLux.LightAPI) or prim.IsA(UsdGeom.Gprim)))


def prepare_material_binding(prim):
    if prim.IsA(UsdGeom.Subset):
        subset = UsdGeom.Subset(prim)
        subset.CreateFamilyNameAttr(UsdShade.Tokens.materialBind)
        mesh_api = UsdShade.MaterialBindingAPI.Apply(prim.GetParent())
        if mesh_api.GetMaterialBindSubsetsFamilyType() != UsdGeom.Tokens.partition:
            mesh_api.SetMaterialBindSubsetsFamilyType(UsdGeom.Tokens.nonOverlapping)
        valid, reason = UsdGeom.Subset.ValidateFamily(UsdGeom.Imageable(prim.GetParent()), UsdGeom.Tokens.face,
                                                    UsdShade.Tokens.materialBind)
        if not valid:
            raise ValueError("Cannot bind this GeomSubset: " + reason)
