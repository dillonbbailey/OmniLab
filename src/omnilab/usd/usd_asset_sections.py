"""Rebuild independent geometry payloads from the publisher's clean snapshot."""
import hashlib

from pxr import Sdf, Usd, UsdGeom


def geometry_sections(stage, root):
    prim = stage.GetPrimAtPath(root)
    if not prim:
        return []

    def geometry(prim):
        return prim.IsA(UsdGeom.Gprim) or prim.IsA(UsdGeom.PointInstancer)

    def contains(prim):
        return any(geometry(p) for p in Usd.PrimRange(prim))

    # Ignore chains of organizational scopes/Xforms until the first geometry
    # split. A leaf mesh (with its GeomSubsets) always stays in one payload.
    while not geometry(prim):
        children = [p for p in prim.GetChildren() if contains(p)]
        if len(children) != 1:
            return [p.GetPath() for p in children]
        prim = children[0]
    return [prim.GetPath()]


def write_sections(publisher, folder):
    geometry = publisher.geometry
    structure = Sdf.Layer.CreateAnonymous("structure.usda")
    structure.TransferContent(geometry)
    paths = [path for scope in ("Geometry", "Dependencies")
             for path in geometry_sections(publisher.stage, publisher.root.AppendChild(scope))]
    sections = []
    for path in paths:
        part = Sdf.Layer.CreateAnonymous("part.usdc")
        for key in geometry.pseudoRoot.ListInfoKeys():
            part.pseudoRoot.SetInfo(key, geometry.pseudoRoot.GetInfo(key))
        Sdf.CreatePrimInLayer(part, path.GetParentPath())
        if not Sdf.CopySpec(geometry, path, part, path):
            raise ValueError(f"Could not split geometry section {path}.")
        edit = Sdf.BatchNamespaceEdit()
        edit.Add(path, Sdf.Path.emptyPath)
        if not structure.Apply(edit):
            raise ValueError(f"Could not replace geometry section {path} with a payload.")
        stub = Sdf.CreatePrimInLayer(structure, path)
        stub.specifier = Sdf.SpecifierDef
        stub.typeName = geometry.GetPrimAtPath(path).typeName
        # Relationships/connections can cross section boundaries (skeletons,
        # proxyPrim, instancer prototypes). Keep those opinions at asset scope,
        # outside the narrower namespace of a section's payload arc.
        def move_links(spec):
            for prop in list(spec.properties):
                if isinstance(prop, Sdf.RelationshipSpec):
                    Sdf.CreatePrimInLayer(structure, spec.path)
                    Sdf.CopySpec(part, prop.path, structure, prop.path)
                    spec.RemoveProperty(prop)
                elif prop.HasInfo("connectionPaths"):
                    owner = Sdf.CreatePrimInLayer(structure, spec.path)
                    target = Sdf.AttributeSpec(owner, prop.name, prop.typeName, prop.variability, prop.custom)
                    target.connectionPathList.explicitItems = prop.connectionPathList.GetAppliedItems()
                    prop.connectionPathList.ClearEdits()
            for child in spec.nameChildren:
                move_links(child)
        move_links(part.GetPrimAtPath(path))
        filename = path.name + "_" + hashlib.sha256(str(path).encode()).hexdigest()[:8] + ".usdc"
        if not part.Export(str(folder / filename)):
            raise OSError(f"Could not write {filename}.")
        stub.payloadList.prependedItems = [Sdf.Payload("./" + filename, path)]
        sections.append(dict(prim=str(path), file="payload/" + filename))
    if not structure.Export(str(folder / "structure.usda")):
        raise OSError("Could not write structure.usda.")
    return sections
